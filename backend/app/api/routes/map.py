"""地图服务API路由"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...models.schemas import POISearchResponse, RouteRequest, RouteResponse, WeatherResponse
from ...services.amap_service import get_amap_service

router = APIRouter(prefix="/map", tags=["地图服务"])


@router.get("/poi", response_model=POISearchResponse, summary="搜索POI")
async def search_poi(
        keywords: str = Query(..., description="搜索关键词"),
        city: str = Query(..., description="城市"),
        citylimit: bool = Query(True, description="是否限制在城市范围内")
):
    """搜索POI（兴趣点）"""
    try:
        service = get_amap_service()
        pois = service.search_poi(keywords, city, citylimit)
        return POISearchResponse(success=True, message="POI搜索成功", data=pois)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"POI搜索失败: {str(e)}")


@router.get("/weather", response_model=WeatherResponse, summary="查询天气")
async def get_weather(
        city: str = Query(..., description="城市名称")
):
    """查询指定城市的天气"""
    try:
        service = get_amap_service()
        weather_info = service.get_weather(city)
        return WeatherResponse(success=True, message="天气查询成功", data=weather_info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"天气查询失败: {str(e)}")


@router.post("/route", response_model=RouteResponse, summary="规划路线")
async def plan_route(request: RouteRequest):
    """规划两点之间的路线"""
    try:
        service = get_amap_service()
        route_info = service.plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type
        )
        return RouteResponse(success=True, message="路线规划成功", data=route_info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"路线规划失败: {str(e)}")