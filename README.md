# TripPlanAgent

> 基于 **LangGraph 图编排**的多智能体协作旅行规划系统。5 个专业 Agent 通过 StateGraph 协同工作，自动搜索景点/天气/酒店，生成旅行计划，并通过 Plan-Verify Loop 自我审查修正。

## 🧠 LangGraph 多 Agent 架构

### 图拓扑

```
                         ┌─────────────────┐
                         │      START       │
                         └────────┬────────┘
                                  │
               ┌──────────────────┼──────────────────┐
               │                  │                  │
               ▼                  ▼                  ▼
     ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
     │ attraction_agent│ │weather_agent│ │   hotel_agent   │
     │    景点搜索专家   │ │  天气查询专家 │ │   酒店推荐专家    │
     └───────┬─────────┘ └──────┬──────┘ └───────┬─────────┘
             │                  │                  │
             └──────────────────┼──────────────────┘
                                │  ← LangGraph 自动汇聚
                                ▼
                      ┌─────────────────┐
                      │  planner_agent  │
                      │   行程规划专家    │
                      └───────┬─────────┘
                              │
                              ▼
                      ┌─────────────────┐
                      │ reviewer_agent  │
                      │   质量审查专家    │
                      └───────┬─────────┘
                              │
                    ┌─────────┴─────────┐
                    │ should_continue   │
                    │                   │
               score ≥ 0.8         score < 0.8
                    │                   │
                    ▼                   │
              ┌──────────┐              │
              │   END    │              │
              └──────────┘              │
                    ▲                   │
                    └───────────────────┘
                   (最多 3 轮修订)
```

### 核心设计理念

#### 1. 共享状态（State）— Agent 间的"黑板"

所有 Agent 共享一个 `TripPlanState`（TypedDict），这是 LangGraph 的核心抽象：

```python
class TripPlanState(TypedDict):
    # 用户输入
    city: str
    travel_days: int
    preferences: list[str]
    ...

    # 各 Agent 产出（并行写入，无冲突）
    attractions_raw: str    # 景点 Agent 写入
    weather_raw: str        # 天气 Agent 写入
    hotels_raw: str         # 酒店 Agent 写入

    # 规划与审查
    draft_plan: dict        # Planner 写入
    review_result: dict     # Reviewer 写入
    iteration: int          # 修订轮次
```

每个 Agent 节点是一个纯函数：**读 State → 执行 → 返回部分更新**。LangGraph 自动完成状态合并，并发节点写入不同 Key 不会冲突。

#### 2. Fan-out / Fan-in 并行执行

3 个研究 Agent 从 START 同时启动，互不依赖：

```python
# Fan-out: START → 3 个节点并行
graph.add_edge(START, "attraction_agent")
graph.add_edge(START, "weather_agent")
graph.add_edge(START, "hotel_agent")

# Fan-in: 3 个节点 → Planner（LangGraph 自动等待全部完成）
graph.add_edge("attraction_agent", "planner_agent")
graph.add_edge("weather_agent", "planner_agent")
graph.add_edge("hotel_agent", "planner_agent")
```

#### 3. Plan-Verify Loop（规划-审查循环）

核心创新：不是一次性生成就返回，而是引入 **Reviewer Agent** 进行质量把关：

| 审查维度 | 权重 | 检查内容 |
|---------|------|---------|
| 地理合理性 | 30% | 相邻景点距离是否合理（实测高德路线数据） |
| 时间可行性 | 25% | 游览+交通是否超出每天可用时间 |
| 预算准确性 | 15% | 各项费用加总是否正确 |
| 多样性 | 15% | 景点类型是否过于单一 |
| 偏好匹配 | 15% | 是否覆盖用户偏好标签 |

```python
def should_continue(state: TripPlanState) -> str:
    score = state["review_result"]["score"]
    iteration = state["iteration"]

    if score >= 0.8 or iteration >= 3:
        return "end"      # 达标或已修订3轮，结束
    return "planner"      # 不达标，回炉修正
```

条件边实现：
```python
graph.add_conditional_edges(
    "reviewer_agent", should_continue,
    {"planner": "planner_agent", "end": END}
)
```

#### 4. 标准 Function Calling

工具通过 `@tool` 装饰器定义，LLM 通过原生 Function Calling 协议调用（不再是文本格式 `[TOOL_CALL:...]`）：

```python
@tool
def search_attractions(keywords: str, city: str) -> str:
    """搜索指定城市的旅游景点"""
    ...

@tool
def query_weather(city: str) -> str:
    """查询城市天气预报"""
    ...

@tool
def search_hotels(city: str, keywords: str = "酒店") -> str:
    """搜索酒店住宿"""
    ...
```

Agent 节点使用 `bind_tools` 绑定工具：

```python
def attraction_agent(state: TripPlanState) -> dict:
    llm = get_llm().bind_tools(ATTRACTION_TOOLS)
    response = llm.invoke([
        SystemMessage(content="你是景点搜索专家，必须使用工具搜索..."),
        HumanMessage(content=f"搜索{state['city']}的景点")
    ])
    # 提取工具调用结果
    ...
    return {"attractions_raw": result}
```

### 5 个 Agent 角色

| Agent | 节点函数 | 工具 | 职责 |
|-------|---------|------|------|
| AttractionAgent | `attraction_agent` | `search_attractions` | 根据偏好搜索景点 |
| WeatherAgent | `weather_agent` | `query_weather` | 查询目的地天气 |
| HotelAgent | `hotel_agent` | `search_hotels` | 按住宿偏好搜索酒店 |
| PlannerAgent | `planner_agent` | JSON mode LLM | 整合信息生成结构化计划 |
| ReviewerAgent | `reviewer_agent` | JSON mode LLM + `plan_route_between` | 5维度审查+实测路线验证 |

---

## 🛠 技术栈

| 层 | 技术 |
|---|------|
| Agent 编排 | **LangGraph** (StateGraph + Conditional Edges) |
| LLM 调用 | **langchain-openai** (ChatOpenAI, 兼容 DeepSeek API) |
| 工具系统 | **langchain_core.tools** (@tool 装饰器, Function Calling) |
| 后端框架 | FastAPI + Pydantic v2 |
| 地图服务 | 高德 REST API (httpx 直调) |
| 前端 | Vue 3 + TypeScript + Ant Design Vue 4 + Vite |
| 图片服务 | Unsplash API |

---

## 📁 项目结构

```
TripPlanAgent/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── trip_planner_agent.py   # LangGraph 图定义 + 5个Agent节点
│   │   │   └── tools.py                # @tool 工具定义
│   │   ├── services/
│   │   │   ├── llm_service.py          # ChatOpenAI 封装
│   │   │   ├── amap_service.py         # 高德 REST API
│   │   │   └── unsplash_service.py     # 图片搜索
│   │   ├── models/schemas.py           # Pydantic 数据模型
│   │   ├── api/routes/                 # FastAPI 路由
│   │   └── config.py                   # 配置管理
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   └── src/
│       ├── views/Home.vue              # 旅行表单
│       ├── views/Result.vue            # 计划展示
│       ├── services/api.ts             # HTTP 客户端
│       └── types/index.ts              # TypeScript 类型
└── README.md
```

核心代码量：`trip_planner_agent.py`（~350 行）包含完整的 LangGraph 编排逻辑。

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 后端
cd backend
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 2. 配置环境变量

复制 `backend/.env.example` 为 `backend/.env`，填入 API 密钥：

```env
LLM_MODEL_ID=deepseek-v4-pro
LLM_API_KEY=your_deepseek_api_key
LLM_BASE_URL=https://api.deepseek.com
AMAP_API_KEY=your_amap_api_key
```

### 3. 启动

```bash
# 终端 1：后端
cd backend
python run.py          # → http://localhost:8000

# 终端 2：前端
cd frontend
npm run dev            # → http://localhost:5173
```

---

## 📡 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/trip/plan` | 生成旅行计划（核心接口） |
| GET | `/api/trip/health` | Agent 健康检查 |
| GET | `/api/poi/search` | POI 搜索 |
| GET | `/api/poi/photo` | 获取景点图片 |
| GET | `/api/map/weather` | 天气查询 |
| POST | `/api/map/route` | 路线规划 |

详细文档：启动后端后访问 `http://localhost:8000/docs`
