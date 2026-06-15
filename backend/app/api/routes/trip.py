import uuid
from fastapi import APIRouter, HTTPException, Query
from ...models.schemas import TripRequest, TripPlanResponse
from ...agents.trip_planner_agent import get_trip_planner_agent, get_progress

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post("/plan", summary="生成旅行计划")
async def plan_trip(request: TripRequest, trace_id: str = Query("", description="可选的任务追踪ID")):
    """
    生成旅行计划。

    前端可先生成 trace_id 传入，然后并行轮询 GET /api/trip/progress?trace_id=xxx
    获取实时进度。不传则后端自动生成。
    """
    tid = trace_id or str(uuid.uuid4())[:8]
    try:
        agent = get_trip_planner_agent()
        trip_plan = agent.plan_trip(request, trace_id=tid)
        return {
            "success": True,
            "message": "旅行计划生成成功",
            "trace_id": tid,
            "data": trip_plan.model_dump() if trip_plan else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成旅行计划失败: {str(e)}")


@router.get("/progress", summary="查询规划进度")
async def get_plan_progress(trace_id: str = Query(..., description="任务追踪ID")):
    """
    查询旅行规划任务的实时进度。

    前端轮询此接口（每1秒），根据返回的 step 更新进度条。
    可能的 step 值:
      - idle: 等待中
      - searching: 搜索景点/天气/酒店
      - planning: 生成旅行计划
      - reviewing: 审查计划质量
      - revising: 修订计划
      - enriching: 景点配图
      - done: 完成
    """
    progress = get_progress(trace_id)
    return {
        "trace_id": trace_id,
        "step": progress["step"],
        "message": progress["message"],
    }


@router.get("/health", summary="健康检查")
async def health_check():
    """检查服务是否正常"""
    try:
        agent = get_trip_planner_agent()
        return {
            "status": "healthy",
            "service": "trip-planner",
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"服务不可用: {str(e)}")
