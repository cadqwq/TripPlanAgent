from fastapi import APIRouter, HTTPException
from ...models.schemas import TripRequest, TripPlanResponse
from ...agents.trip_planner_agent import get_trip_planner_agent

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
async def plan_trip(request: TripRequest):
    """生成旅行计划"""
    try:
        agent = get_trip_planner_agent()
        trip_plan = agent.plan_trip(request)
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=trip_plan
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成旅行计划失败: {str(e)}")


@router.get("/health", summary="健康检查")
async def health_check():
    """检查服务是否正常"""
    try:
        agent = get_trip_planner_agent()
        return {
            "status": "healthy",
            "service": "trip-planner",
            "attraction_agent": agent.attraction_agent.name,
            "weather_agent": agent.weather_agent.name,
            "hotel_agent": agent.hotel_agent.name,
            "planner_agent": agent.planner_agent.name
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"服务不可用: {str(e)}")