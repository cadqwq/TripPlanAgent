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
import traceback
from datetime import datetime, timedelta
from typing import TypedDict, Literal

# ===== 修复 Windows GBK 编码问题 =====
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import builtins as _builtins

_super_print = _builtins.print

def _utf8_safe_print(*args, **kw):
    try:
        _super_print(*args, **kw)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            safe = [str(a).encode('ascii', errors='replace').decode('ascii') for a in args]
            _super_print(*safe, **kw)
        except Exception:
            pass

_builtins.print = _utf8_safe_print
# =====

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage

from ..services.llm_service import get_llm, get_llm_json_mode
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, WeatherInfo, Location, Hotel, Budget
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

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_query),
    ])

    # 检查 LLM 是否发起了工具调用
    tool_calls = getattr(response, 'tool_calls', []) or []

    for tc in tool_calls:
        name = tc.get('name', '')
        if name == expected_tool and name in _TOOL_MAP:
            try:
                result = _TOOL_MAP[name].invoke(tc['args'])
                return result if isinstance(result, str) else str(result)
            except Exception as e:
                print(f"⚠️  工具 {name} 执行失败: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

    # LLM 没有调用工具，返回它的文本回复
    content = getattr(response, 'content', '') or str(response)
    print(f"⚠️  {expected_tool} Agent 未调用工具，返回文本: {content[:100]}...")
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

    print(f"📍 [Attraction Agent] 搜索 {city} 的 {keywords} 相关景点...")

    result = _run_tool_agent(
        system_prompt=(
            f"你是景点搜索专家。"
            f"你必须使用 search_attractions 工具搜索景点，绝对不要编造信息。"
        ),
        user_query=f"请搜索{city}的{keywords}相关景点",
        tools=ATTRACTION_TOOLS,
        expected_tool="search_attractions",
    )

    print(f"📍 [Attraction Agent] 完成，结果长度: {len(result)} 字符")
    return {"attractions_raw": result}


def weather_agent(state: TripPlanState) -> dict:
    """
    天气查询 Agent（并行节点2/3）

    职责: 查询目的地天气预报
    工具: query_weather
    产出: weather_raw
    """
    city = state['city']

    print(f"🌤️  [Weather Agent] 查询 {city} 天气...")

    result = _run_tool_agent(
        system_prompt=(
            f"你是天气查询专家。"
            f"你必须使用 query_weather 工具查询天气，绝对不要编造信息。"
        ),
        user_query=f"请查询{city}的天气预报",
        tools=WEATHER_TOOLS,
        expected_tool="query_weather",
    )

    print(f"🌤️  [Weather Agent] 完成，结果长度: {len(result)} 字符")
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

    print(f"🏨 [Hotel Agent] 搜索 {city} 的 {accommodation}...")

    result = _run_tool_agent(
        system_prompt=(
            f"你是酒店推荐专家。"
            f"你必须使用 search_hotels 工具搜索酒店，绝对不要编造信息。"
        ),
        user_query=f"请搜索{city}的{accommodation}",
        tools=HOTEL_TOOLS,
        expected_tool="search_hotels",
    )

    print(f"🏨 [Hotel Agent] 完成，结果长度: {len(result)} 字符")
    return {"hotels_raw": result}


def planner_agent(state: TripPlanState) -> dict:
    """
    行程规划 Agent

    职责: 整合景点、天气、酒店信息，生成结构化的旅行计划 JSON
    输入: attractions_raw + weather_raw + hotels_raw + review_result(如果有)
    产出: draft_plan
    """
    print(f"📋 [Planner Agent] 第 {state.get('iteration', 0) + 1} 轮规划...")

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

    prompt = f"""你是一位资深的旅行规划师。请根据以下信息生成一份详细的旅行计划。

**目的地信息:**
- 城市: {state['city']}
- 日期: {state['start_date']} 至 {state['end_date']}
- 天数: {state['travel_days']} 天
- 交通方式: {state['transportation']}
- 住宿偏好: {state['accommodation']}
- 旅行偏好: {', '.join(state.get('preferences', [])) or '无特殊偏好'}
- 额外要求: {state.get('free_text_input', '无')}

**景点数据:**
{state.get('attractions_raw', '暂无景点数据')}

**天气数据:**
{state.get('weather_raw', '暂无天气数据')}

**酒店数据:**
{state.get('hotels_raw', '暂无酒店数据')}

{feedback_section}
**要求:**
1. 每天安排2-3个景点，景点之间距离合理
2. 每天必须包含早、中、晚三餐
3. 每天推荐一个具体酒店（从酒店数据中选择）
4. 考虑天气情况调整行程（雨天多安排室内景点）
5. 提供完整的预算估算
6. 景点的经纬度坐标必须基于真实数据

**返回严格的 JSON 格式（不要 markdown 代码块标记）:**
{{
  "city": "{state['city']}",
  "start_date": "{state['start_date']}",
  "end_date": "{state['end_date']}",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述，200字以内",
      "transportation": "{state['transportation']}",
      "accommodation": "{state['accommodation']}",
      "hotel": {{
        "name": "酒店名称",
        "address": "酒店地址",
        "location": {{"longitude": 116.397, "latitude": 39.916}},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "{state['accommodation']}",
        "estimated_cost": 400
      }},
      "attractions": [
        {{
          "name": "景点名称",
          "address": "详细地址",
          "location": {{"longitude": 116.397, "latitude": 39.916}},
          "visit_duration": 120,
          "description": "景点描述，100字以内",
          "category": "景点类别",
          "ticket_price": 60
        }}
      ],
      "meals": [
        {{"type": "breakfast", "name": "早餐推荐", "description": "特色早餐", "estimated_cost": 30}},
        {{"type": "lunch", "name": "午餐推荐", "description": "午餐推荐", "estimated_cost": 50}},
        {{"type": "dinner", "name": "晚餐推荐", "description": "晚餐推荐", "estimated_cost": 80}}
      ]
    }}
  ],
  "weather_info": [
    {{
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }}
  ],
  "overall_suggestions": "旅行总体建议，300字以内",
  "budget": {{
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }}
}}
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

        print(f"📋 [Planner Agent] 第 {iteration} 轮规划完成")
        return {
            "draft_plan": plan,
            "iteration": iteration,
        }

    except json.JSONDecodeError as e:
        print(f"❌ [Planner Agent] JSON 解析失败: {e}")
        print(f"   原始内容前200字符: {content[:200]}")
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
        print("⚠️  [Reviewer Agent] 没有可审查的计划，跳过")
        return {"review_result": {"score": 1.0, "passes": [], "issues": [], "suggestions": []}}

    print(f"🔍 [Reviewer Agent] 审查计划... ({state.get('iteration', 0)} 轮)")

    llm = get_llm_json_mode()

    # 提取关键信息用于审查
    days = plan.get('days', [])
    day_count = len(days)

    # 实际验证景点间距离（抽样检查每天前2个景点间距离）
    route_checks = []
    for day in days:
        attractions = day.get('attractions', [])
        if len(attractions) >= 2:
            a1 = attractions[0]
            a2 = attractions[1]
            try:
                route_result = plan_route_between.invoke({
                    "origin_address": a1.get('address', ''),
                    "destination_address": a2.get('address', ''),
                    "route_type": "walking",
                })
                route_checks.append({
                    "day": day.get('day_index', 0),
                    "from": a1.get('name', '?'),
                    "to": a2.get('name', '?'),
                    "route_data": route_result[:300],
                })
            except Exception as e:
                route_checks.append({
                    "day": day.get('day_index', 0),
                    "from": a1.get('name', '?'),
                    "to": a2.get('name', '?'),
                    "error": str(e),
                })

    prompt = f"""你是一个严格的旅行计划审查专家。审查以下 {day_count} 天旅行计划并打分。

**旅行计划:**
{json.dumps(plan, ensure_ascii=False, indent=2)}

**用户偏好:** {state.get('preferences', [])}

**实测景点间路线数据（抽样）:**
{json.dumps(route_checks, ensure_ascii=False, indent=2)}

**从以下5个维度评分(0-1)，加权计算总分:**

| 维度 | 权重 | 检查内容 |
|------|------|---------|
| 地理合理性 | 0.30 | 相邻景点距离是否合理？实测路线距离是否<5km？一天内景点是否在同一区域？|
| 时间可行性 | 0.25 | 游览时间+交通时间是否超出每天10小时可用时间？|
| 预算准确性 | 0.15 | budget.total 是否等于各项加总？各项费用是否合理？|
| 多样性 | 0.15 | 景点类别是否多样？是否全是同一类型（如全是寺庙）？|
| 偏好匹配 | 0.15 | 是否覆盖了用户偏好？偏好标签中有多少被实际安排？|

**通过标准:**
- score ≥ 0.80 → 合格，可以发布
- score < 0.80 → 不合格，需要 Planner 修正

**返回严格的 JSON 格式（不要 markdown 代码块）:**
{{
  "score": 0.85,
  "dimension_scores": {{
    "地理合理性": 0.9,
    "时间可行性": 0.8,
    "预算准确性": 0.85,
    "多样性": 0.9,
    "偏好匹配": 0.8
  }},
  "passes": ["地理分布合理，景点集中在同一区域", "预算计算正确"],
  "issues": [
    {{"severity": "high", "dimension": "地理合理性", "detail": "第2天故宫和长城相距50km，步行不现实"}}
  ],
  "suggestions": ["第2天建议只安排故宫+景山公园，将长城移到第3天"]
}}
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
        print(f"🔍 [Reviewer Agent] 评分: {score:.2f} | 问题: {issues_count} 个 | {'✅ 通过' if score >= 0.8 else '❌ 需修正'}")

        return {"review_result": review}

    except json.JSONDecodeError as e:
        print(f"❌ [Reviewer Agent] JSON 解析失败: {e}")
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
        print(f"✅ Plan-Verify Loop 结束: 评分 {score:.2f} ≥ 0.8，通过")
        return "end"

    if iteration >= 3:
        print(f"⚠️  Plan-Verify Loop 结束: 已达最大 {iteration} 轮修订，强制通过")
        return "end"

    print(f"🔄 Plan-Verify Loop: 评分 {score:.2f} < 0.8，返回 Planner 修订（第 {iteration + 1} 轮）")
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

    # 条件边: Reviewer → Planner（修订循环）或 END（通过）
    graph.add_conditional_edges(
        "reviewer_agent",
        should_continue,
        {
            "planner": "planner_agent",
            "end": END,
        }
    )

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
        print("🔄 开始初始化 LangGraph 多智能体旅行规划系统...")

        try:
            self.graph = build_trip_planner_graph()
            print("✅ LangGraph 图构建成功")
            print("   节点: attraction_agent, weather_agent, hotel_agent, planner_agent, reviewer_agent")
            print("   拓扑: Fan-out(3并行) → Planner → Reviewer → [条件循环]")
        except Exception as e:
            print(f"❌ LangGraph 图构建失败: {str(e)}")
            traceback.print_exc()
            raise

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """
        使用 LangGraph 多智能体协作生成旅行计划

        Args:
            request: 旅行请求

        Returns:
            旅行计划
        """
        try:
            print(f"\n{'='*60}")
            print(f"🚀 开始 LangGraph 多智能体协作规划...")
            print(f"目的地: {request.city}")
            print(f"日期: {request.start_date} 至 {request.end_date}")
            print(f"天数: {request.travel_days}天")
            print(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
            print(f"{'='*60}\n")

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
            print("⚡ 执行 LangGraph 图...")
            result = self.graph.invoke(initial_state)

            # 提取最终计划
            plan_dict = result.get('draft_plan', {})
            review = result.get('review_result', {})
            iteration = result.get('iteration', 0)

            if not plan_dict or not plan_dict.get('days'):
                raise ValueError("LangGraph 未生成有效的旅行计划")

            trip_plan = TripPlan(**plan_dict)

            print(f"\n{'='*60}")
            print(f"✅ 旅行计划生成完成!")
            print(f"   总修订轮次: {iteration}")
            print(f"   审查评分: {review.get('score', 'N/A')}")
            print(f"   行程天数: {len(trip_plan.days)}")
            print(f"{'='*60}\n")

            return trip_plan

        except Exception as e:
            print(f"❌ LangGraph 规划失败: {str(e)}")
            traceback.print_exc()
            return self._create_fallback_plan(request)

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
