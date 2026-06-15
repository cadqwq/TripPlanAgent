"""
多智能体旅行规划系统 — 基于 LangGraph 图编排

Agent 拓扑:
    START
      │
      ├──→ attraction_agent (并行) ──┐
      ├──→ weather_agent    (并行) ──┼──→ planner_agent ──→ reviewer_agent
      └──→ hotel_agent      (并行) ──┘                          │
                                                  score ≥ 0.8?  │
                                                  iteration≥3?  │
                                                       │        │
                                                      Yes      No
                                                       │        │
                                                      END ◄────┘

核心特性:
- 3个研究Agent并行执行（Fan-out/Fan-in）
- 结构化消息协议：每个Agent读写共享 State，不靠文本拼接
- Plan-Verify Loop：Reviewer从5个维度打分，不达标自动回炉（最多3轮）
- 标准 Function Calling：工具通过 langchain @tool 装饰器定义
"""

import sys
import os
import json
import gc
import uuid
import traceback
from datetime import datetime, timedelta
from typing import TypedDict, Literal
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage

from ..services.llm_service import get_llm, get_llm_json_mode
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, Location
from .tools import (
    ATTRACTION_TOOLS,
    WEATHER_TOOLS,
    HOTEL_TOOLS,
    REVIEWER_TOOLS,
    search_attractions,
    query_weather,
    search_hotels,
    plan_route_between,
)

# ============================================================
# 0. trace_id 上下文 — 贯穿一次请求的所有 Agent 调用
# ============================================================

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

# 进度存储：trace_id → {step, message, timestamp}（自动清理超过 5 分钟的旧条目）
import time as _time
_progress_store: dict = {}

def get_progress(trace_id: str) -> dict:
    """查询某个任务的当前进度"""
    return _progress_store.get(trace_id, {"step": "idle", "message": "等待中..."})

def _update_progress(tid: str, step: str, message: str):
    """更新进度（供 Agent 节点调用），并清理超过 5 分钟的旧条目"""
    _progress_store[tid] = {"step": step, "message": message, "ts": _time.time()}
    # 每 10 次更新清理一次旧条目
    if len(_progress_store) > 20:
        now = _time.time()
        stale = [k for k, v in _progress_store.items() if now - v.get("ts", 0) > 300]
        for k in stale:
            del _progress_store[k]

def _log(level: str, msg: str, *args, **kwargs):
    """带 trace_id 的结构化日志 + 进度更新"""
    tid = _trace_id.get("")
    prefix = f"[trace={tid}] " if tid else ""
    getattr(logger, level)(f"{prefix}{msg}", *args, **kwargs)


# ============================================================
# 1. 共享状态定义（Agent间的"黑板"）
# ============================================================

class TripPlanState(TypedDict):
    """
    所有 Agent 共享的状态对象。

    LangGraph 的核心理念：每个节点读取 State，返回部分更新。
    并行节点写入不同 key，自动合并，无竞争条件。
    """
    # ---- 用户输入 ----
    city: str
    start_date: str
    end_date: str
    travel_days: int
    transportation: str
    accommodation: str
    preferences: list[str]
    free_text_input: str

    # ---- 研究Agent产出（3个并行节点各自写入） ----
    attractions_raw: str    # 景点搜索 JSON
    weather_raw: str        # 天气查询 JSON
    hotels_raw: str         # 酒店搜索 JSON

    # ---- 规划与审查 ----
    draft_plan: dict        # Planner 生成的计划
    review_result: dict     # Reviewer 的审查结果
    iteration: int          # 当前修订轮次


# ============================================================
# 2. 工具调用辅助函数
# ============================================================

# tool_name → tool 对象的映射
_TOOL_MAP = {
    "search_attractions": search_attractions,
    "query_weather": query_weather,
    "search_hotels": search_hotels,
    "plan_route_between": plan_route_between,
}


def _run_tool_agent(
    system_prompt: str,
    user_query: str,
    tools: list,
    expected_tool: str,
) -> str:
    """
    运行一个单轮工具型 Agent。

    流程:
    1. 用 bind_tools 绑定工具 → LLM 收到 Function Calling schema
    2. LLM 决定调用哪个工具
    3. 手动执行工具调用并返回结果 JSON

    这与 HelloAgents 的 [TOOL_CALL:...] 文本格式完全不同，
    用的是标准的 OpenAI Function Calling 协议。
    """
    llm = get_llm().bind_tools(tools)

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query),
        ])
    except Exception as e:
        _log("error", "LLM调用失败 | error={}", str(e))
        return json.dumps({"error": f"LLM调用失败: {str(e)}"}, ensure_ascii=False)

    # 检查 LLM 是否发起了工具调用
    tool_calls = getattr(response, 'tool_calls', []) or []

    for tc in tool_calls:
        name = tc.get('name', '')
        if name == expected_tool and name in _TOOL_MAP:
            try:
                result = _TOOL_MAP[name].invoke(tc['args'])
                return result if isinstance(result, str) else str(result)
            except Exception as e:
                _log("warning", "工具调用失败 | tool={} error={}", name, str(e))
                return json.dumps({"error": str(e)}, ensure_ascii=False)

    # LLM 没有调用工具，返回它的文本回复
    content = getattr(response, 'content', '') or str(response)
    _log("warning", "Agent未调用工具 | expected={} fallback_text={:100}", expected_tool, content)
    return content


# ============================================================
# 3. Agent 节点函数
# ============================================================

def attraction_agent(state: TripPlanState) -> dict:
    """
    景点搜索 Agent（并行节点1/3）

    职责: 根据用户偏好搜索合适的旅游景点
    工具: search_attractions
    产出: attractions_raw
    """
    city = state['city']
    prefs = state.get('preferences', [])
    keywords = '、'.join(prefs) if prefs else '热门景点'

    _update_progress(_trace_id.get(), "searching", f"正在搜索{city}的{keywords}相关景点...")
    _log("info", "[AttractionAgent] 开始搜索 | city={} keywords={}", city, keywords)

    result = _run_tool_agent(
        system_prompt=(
            f"你是景点搜索专家。"
            f"你必须使用 search_attractions 工具搜索景点，绝对不要编造信息。"
        ),
        user_query=f"请搜索{city}的{keywords}相关景点",
        tools=ATTRACTION_TOOLS,
        expected_tool="search_attractions",
    )

    _log("info", "[AttractionAgent] 完成 | result_chars={}", len(result))
    return {"attractions_raw": result}


def weather_agent(state: TripPlanState) -> dict:
    """
    天气查询 Agent（并行节点2/3）

    职责: 查询目的地天气预报
    工具: query_weather
    产出: weather_raw
    """
    city = state['city']

    _update_progress(_trace_id.get(), "searching", f"正在查询{city}天气...")
    _log("info", "[WeatherAgent] 开始查询 | city={}", city)

    result = _run_tool_agent(
        system_prompt=(
            f"你是天气查询专家。"
            f"你必须使用 query_weather 工具查询天气，绝对不要编造信息。"
        ),
        user_query=f"请查询{city}的天气预报",
        tools=WEATHER_TOOLS,
        expected_tool="query_weather",
    )

    _log("info", "[WeatherAgent] 完成 | result_chars={}", len(result))
    return {"weather_raw": result}


def hotel_agent(state: TripPlanState) -> dict:
    """
    酒店推荐 Agent（并行节点3/3）

    职责: 根据住宿偏好搜索酒店
    工具: search_hotels
    产出: hotels_raw
    """
    city = state['city']
    accommodation = state.get('accommodation', '酒店')

    _update_progress(_trace_id.get(), "searching", f"正在搜索{city}的{accommodation}...")
    _log("info", "[HotelAgent] 开始搜索 | city={} accommodation={}", city, accommodation)

    result = _run_tool_agent(
        system_prompt=(
            f"你是酒店推荐专家。"
            f"你必须使用 search_hotels 工具搜索酒店，绝对不要编造信息。"
        ),
        user_query=f"请搜索{city}的{accommodation}",
        tools=HOTEL_TOOLS,
        expected_tool="search_hotels",
    )

    _log("info", "[HotelAgent] 完成 | result_chars={}", len(result))
    return {"hotels_raw": result}


def planner_agent(state: TripPlanState) -> dict:
    """
    行程规划 Agent

    职责: 整合景点、天气、酒店信息，生成结构化的旅行计划 JSON
    输入: attractions_raw + weather_raw + hotels_raw + review_result(如果有)
    产出: draft_plan
    """
    r = state.get('iteration', 0) + 1
    _update_progress(_trace_id.get(), "planning", f"正在生成旅行计划...（第{r}轮）")
    _log("info", "[PlannerAgent] 开始规划 | round={}", r)

    llm = get_llm_json_mode()

    # 构建上一轮的审查反馈（修订模式）
    review = state.get('review_result', {})
    feedback_section = ""
    if review and review.get('score', 0) > 0:
        issues = review.get('issues', [])
        suggestions = review.get('suggestions', [])
        feedback_section = f"""
**⚠️ 上一轮审查反馈（本轮必须修正）:**
- 评分: {review.get('score', 0)}/1.0
- 问题: {json.dumps(issues, ensure_ascii=False, indent=2)}
- 改进建议: {json.dumps(suggestions, ensure_ascii=False, indent=2)}
"""

    prompt = f"""为{state['city']}生成{state['travel_days']}天旅行计划。

城市={state['city']} 日期={state['start_date']}~{state['end_date']} 交通={state['transportation']} 住宿={state['accommodation']}
偏好={', '.join(state.get('preferences', [])) or '无'} 额外要求={state.get('free_text_input', '无')}

景点数据:
{state.get('attractions_raw', '暂无')[:3000]}

天气:
{state.get('weather_raw', '暂无')[:1000]}

酒店:
{state.get('hotels_raw', '暂无')[:2000]}

{feedback_section}
规则: 每天2-3景点，早中晚三餐，从数据中选酒店，经纬度必须真实。

返回JSON(无markdown标记):
{{"city":"{state['city']}","start_date":"{state['start_date']}","end_date":"{state['end_date']}","days":[{{"date":"YYYY-MM-DD","day_index":0,"description":"50字内","transportation":"{state['transportation']}","accommodation":"{state['accommodation']}","hotel":{{"name":"..","address":"..","location":{{"longitude":116.397,"latitude":39.916}},"price_range":"..","rating":"..","distance":"..","type":"{state['accommodation']}","estimated_cost":0}},"attractions":[{{"name":"..","address":"..","location":{{"longitude":116.397,"latitude":39.916}},"visit_duration":120,"description":"30字内","category":"..","ticket_price":0,"image_url":""}}],"meals":[{{"type":"breakfast","name":"..","description":"..","estimated_cost":30}},{{"type":"lunch","name":"..","description":"..","estimated_cost":50}},{{"type":"dinner","name":"..","description":"..","estimated_cost":80}}]}}],"weather_info":[{{"date":"..","day_weather":"..","night_weather":"..","day_temp":25,"night_temp":15,"wind_direction":"..","wind_power":".."}}],"overall_suggestions":"80字内","budget":{{"total_attractions":0,"total_hotels":0,"total_meals":0,"total_transportation":0,"total":0}}}}
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, 'content') else str(response)

        # 清理可能的 markdown 代码块标记
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        plan = json.loads(content)
        iteration = state.get('iteration', 0) + 1

        _log("info", "[PlannerAgent] 完成 | round={}", iteration)
        return {
            "draft_plan": plan,
            "iteration": iteration,
        }

    except json.JSONDecodeError as e:
        _log("error", "[PlannerAgent] JSON解析失败 | error={} raw={:200}", str(e), content)
        raise


def reviewer_agent(state: TripPlanState) -> dict:
    """
    质量审查 Agent

    职责: 从5个维度审查旅行计划质量，给出评分和修改建议
    输入: draft_plan
    产出: review_result

    5个审查维度:
    1. 地理合理性 (0.30) — 相邻景点距离是否合理
    2. 时间可行性 (0.25) — 游览+交通是否在可用时间内
    3. 预算准确性 (0.15) — 各项费用加总是否正确
    4. 多样性     (0.15) — 景点类型是否过于单一
    5. 偏好匹配   (0.15) — 是否覆盖用户偏好
    """
    plan = state.get('draft_plan', {})
    if not plan:
        _log("warning", "[ReviewerAgent] 无计划可审查，跳过")
        return {"review_result": {"score": 1.0, "passes": [], "issues": [], "suggestions": []}}

    _update_progress(_trace_id.get(), "reviewing", "正在审查旅行计划质量...")
    _log("info", "[ReviewerAgent] 开始审查 | round={}", state.get('iteration', 0))

    llm = get_llm_json_mode()

    days = plan.get('days', [])
    day_count = len(days)

    prompt = f"""审查此{day_count}天旅行计划，5维度打分(0-1):
地理合理性(0.30): 景点距离是否合理
时间可行性(0.25): 游览+交通≤10h/天
预算准确性(0.15): 各项加总=total
多样性(0.15): 类型不单一
偏好匹配(0.15): 覆盖{state.get('preferences', [])}

计划: {json.dumps(plan, ensure_ascii=False)}

score≥0.80通过,<0.80需修订。返回JSON(无markdown):
{{"score":0.85,"dimension_scores":{{"地理合理性":0.9,"时间可行性":0.8,"预算准确性":0.85,"多样性":0.9,"偏好匹配":0.8}},"passes":["..."],"issues":[{{"severity":"high|medium|low","dimension":"..","detail":".."}}],"suggestions":[".."]}}
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, 'content') else str(response)

        # 清理 markdown 标记
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        review = json.loads(content)

        score = review.get('score', 0)
        issues_count = len(review.get('issues', []))
        _log("info", "[ReviewerAgent] 完成 | score={:.2f} issues={} status={}",
             score, issues_count, "PASS" if score >= 0.8 else "REVISE")

        return {"review_result": review}

    except json.JSONDecodeError as e:
        _log("error", "[ReviewerAgent] JSON解析失败 | error={}", str(e))
        # 返回一个宽容的审查结果
        return {
            "review_result": {
                "score": 0.85,
                "passes": ["审查Agent解析异常，默认放行"],
                "issues": [],
                "suggestions": [],
            }
        }


# ============================================================
# 4. 路由函数
# ============================================================

def cleanup_node(state: TripPlanState) -> dict:
    """释放内存：清空不再需要的原始数据字段"""
    return {
        "attractions_raw": "",
        "weather_raw": "",
        "hotels_raw": "",
    }


def should_continue(state: TripPlanState) -> Literal["planner", "end"]:
    """
    条件边：审查通过 → 结束，否则 → 回 Planner 修正

    终止条件（满足任一即结束）:
    1. score ≥ 0.80 — 质量达标
    2. iteration ≥ 3 — 达到最大修订轮次，强制结束
    """
    review = state.get('review_result', {})
    score = review.get('score', 0)
    iteration = state.get('iteration', 0)

    if score >= 0.8:
        _update_progress(_trace_id.get(), "done", f"审查通过！（评分 {score:.0%}）")
        _log("info", "Plan-Verify Loop 通过 | score={:.2f}", score)
        return "end"

    if iteration >= 3:
        _update_progress(_trace_id.get(), "done", "已达最大修订轮次，生成最终计划")
        _log("warning", "Plan-Verify Loop 强制结束 | max_rounds={}", iteration)
        return "end"

    _update_progress(_trace_id.get(), "revising", f"评分不达标（{score:.0%}），正在修订计划...（第{iteration+1}轮）")
    _log("info", "Plan-Verify Loop 继续修订 | score={:.2f} next_round={}", score, iteration + 1)
    return "planner"


# ============================================================
# 5. 构建图
# ============================================================

def build_trip_planner_graph():
    """
    构建 LangGraph 旅行规划图。

    拓扑结构:
        START
          │
          ├──→ attraction_agent (并行) ──┐
          ├──→ weather_agent    (并行) ──┤
          └──→ hotel_agent      (并行) ──┤
                                          │
                                          ▼
                                    planner_agent
                                          │
                                          ▼
                                    reviewer_agent
                                          │
                              ┌───────────┴───────────┐
                              │ should_continue       │
                              │ "end" → END           │
                              │ "planner" → planner   │
                              └───────────────────────┘
    """
    graph = StateGraph(TripPlanState)

    # ---- 添加节点 ----
    graph.add_node("attraction_agent", attraction_agent)
    graph.add_node("weather_agent", weather_agent)
    graph.add_node("hotel_agent", hotel_agent)
    graph.add_node("planner_agent", planner_agent)
    graph.add_node("reviewer_agent", reviewer_agent)
    graph.add_node("cleanup", cleanup_node)

    # ---- 添加边 ----

    # Fan-out: START → 3个研究Agent并行执行
    graph.add_edge(START, "attraction_agent")
    graph.add_edge(START, "weather_agent")
    graph.add_edge(START, "hotel_agent")

    # Fan-in: 3个研究Agent → Planner（LangGraph 自动等待全部完成）
    graph.add_edge("attraction_agent", "planner_agent")
    graph.add_edge("weather_agent", "planner_agent")
    graph.add_edge("hotel_agent", "planner_agent")

    # Planner → Reviewer
    graph.add_edge("planner_agent", "reviewer_agent")

    # 条件边: Reviewer → Planner（修订循环）或 cleanup → END
    graph.add_conditional_edges(
        "reviewer_agent",
        should_continue,
        {
            "planner": "planner_agent",
            "end": "cleanup",
        }
    )

    # cleanup → END
    graph.add_edge("cleanup", END)

    return graph.compile()


# ============================================================
# 6. 兼容层（保持原有 API 不变）
# ============================================================

class MultiAgentTripPlanner:
    """
    多智能体旅行规划系统

    对外接口与旧版完全兼容，内部使用 LangGraph 图编排。
    """

    def __init__(self):
        """初始化 LangGraph 图"""
        logger.info("开始初始化 LangGraph 多智能体旅行规划系统...")

        try:
            self.graph = build_trip_planner_graph()
            logger.info("LangGraph 图构建成功 | nodes=attraction_agent,weather_agent,hotel_agent,planner_agent,reviewer_agent")
            logger.info("图拓扑: Fan-out(3并行) -> Planner -> Reviewer -> [条件循环]")
        except Exception as e:
            logger.error("LangGraph 图构建失败 | error={}", str(e))
            traceback.print_exc()
            raise

    def plan_trip(self, request: TripRequest, trace_id: str = "") -> TripPlan:
        """
        使用 LangGraph 多智能体协作生成旅行计划

        Args:
            request: 旅行请求
            trace_id: 可选的任务追踪ID，不传则自动生成

        Returns:
            旅行计划
        """
        # 生成或使用传入的 trace_id，贯穿本次请求的所有 Agent 调用
        tid = trace_id or str(uuid.uuid4())[:8]
        _trace_id.set(tid)
        _update_progress(tid, "searching", "正在搜索景点、天气、酒店信息...")

        try:
            prefs = ', '.join(request.preferences) if request.preferences else '无'
            _log("info", "========== 开始多智能体协作规划 ==========")
            _log("info", "请求参数 | city={} dates={}~{} days={} prefs={}",
                 request.city, request.start_date, request.end_date, request.travel_days, prefs)

            # 构建初始状态
            initial_state: TripPlanState = {
                "city": request.city,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "travel_days": request.travel_days,
                "transportation": request.transportation,
                "accommodation": request.accommodation,
                "preferences": request.preferences or [],
                "free_text_input": request.free_text_input or "",
                "attractions_raw": "",
                "weather_raw": "",
                "hotels_raw": "",
                "draft_plan": {},
                "review_result": {},
                "iteration": 0,
            }

            # 执行 LangGraph 图
            _log("info", "执行 LangGraph 图...")
            result = self.graph.invoke(initial_state)

            # 提取最终计划
            plan_dict = result.get('draft_plan', {})
            review = result.get('review_result', {})
            iteration = result.get('iteration', 0)

            if not plan_dict or not plan_dict.get('days'):
                raise ValueError("LangGraph 未生成有效的旅行计划")

            trip_plan = TripPlan(**plan_dict)

            # 自动配图：从 Unsplash 为每个景点获取照片
            _update_progress(tid, "enriching", "正在为景点配图...")
            _log("info", "开始为景点配图...")
            self._enrich_images(trip_plan)

            # 清理内存：删除大字符串、触发 GC、清理过期进度
            _log("info", "释放内存...")
            del result
            if tid in _progress_store:
                del _progress_store[tid]
            gc.collect()

            _log("info", "========== 规划完成 | rounds={} score={} days={} ==========",
                 iteration, review.get('score', 'N/A'), len(trip_plan.days))

            return trip_plan

        except Exception as e:
            # logger.opt(exception=True) 会打印完整调用栈到 loguru
            logger.opt(exception=True).error("[trace={}] 规划失败 | error={}", tid, str(e))
            return self._create_fallback_plan(request)

    def _enrich_images(self, trip_plan: TripPlan):
        """
        为旅行计划中的每个景点自动配图。

        并行调用 Unsplash API，每个景点获取一张照片 URL，
        写入 attraction.image_url 字段。
        """
        from ..services.unsplash_service import get_unsplash_service

        unsplash = get_unsplash_service()

        # 收集所有需要配图的景点
        attractions = []
        for day in trip_plan.days:
            for attr in day.attractions:
                if not attr.image_url:
                    attractions.append(attr)

        if not attractions:
            return

        # 并行获取图片（最多 5 个并发）
        def fetch_image(attr):
            try:
                url = unsplash.get_photo_url(f"{attr.name} {trip_plan.city}")
                if url:
                    attr.image_url = url
                    _log("info", "景点配图成功 | attraction={}", attr.name)
                else:
                    _log("warning", "景点配图未找到 | attraction={}", attr.name)
            except Exception as e:
                _log("warning", "景点配图失败 | attraction={} error={}", attr.name, str(e))

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_image, attr) for attr in attractions]
            for f in as_completed(futures):
                f.result()  # 等待全部完成，有异常也会被内部 catch

        total = len(attractions)
        with_image = sum(1 for a in attractions if a.image_url)
        _log("info", "配图完成 | total={} with_image={}", total, with_image)

    def _create_fallback_plan(self, request: TripRequest) -> TripPlan:
        """创建备用计划（当 LangGraph 执行失败时）"""
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")

        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)

            day_plan = DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天行程",
                transportation=request.transportation,
                accommodation=request.accommodation,
                attractions=[
                    Attraction(
                        name=f"{request.city}景点{j+1}",
                        address=f"{request.city}市",
                        location=Location(
                            longitude=116.4 + i * 0.01 + j * 0.005,
                            latitude=39.9 + i * 0.01 + j * 0.005
                        ),
                        visit_duration=120,
                        description=f"这是{request.city}的著名景点",
                        category="景点"
                    )
                    for j in range(2)
                ],
                meals=[
                    Meal(type="breakfast", name=f"第{i+1}天早餐", description="当地特色早餐"),
                    Meal(type="lunch", name=f"第{i+1}天午餐", description="午餐推荐"),
                    Meal(type="dinner", name=f"第{i+1}天晚餐", description="晚餐推荐")
                ]
            )
            days.append(day_plan)

        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],
            overall_suggestions=(
                f"这是为您规划的{request.city}{request.travel_days}日游行程。"
                f"由于系统异常，此为基础参考行程，建议结合实际情况调整。"
            )
        )


# ============================================================
# 7. 全局单例
# ============================================================

_multi_agent_planner = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取多智能体旅行规划系统实例（单例模式）"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()

    return _multi_agent_planner
