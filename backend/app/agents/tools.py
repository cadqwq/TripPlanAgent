"""LangChain 工具定义 — 将高德MCP服务包装为标准 Function Calling 工具"""

import json
from langchain_core.tools import tool
from ..services.amap_service import get_amap_service


@tool
def search_attractions(keywords: str, city: str) -> str:
    """
    搜索指定城市的旅游景点。

    根据关键词和城市名搜索相关景点，返回景点列表，包含名称、地址、经纬度、评分等信息。

    Args:
        keywords: 搜索关键词，如 '历史文化'、'自然风光'、'博物馆'、'公园'
        city: 城市名称，如 '北京'、'上海'
    """
    service = get_amap_service()
    results = service.search_poi(keywords=keywords, city=city)
    if not results:
        return json.dumps({"message": f"未找到{keywords}相关景点", "pois": []}, ensure_ascii=False)
    return json.dumps({"pois": results}, ensure_ascii=False)


@tool
def query_weather(city: str) -> str:
    """
    查询指定城市的天气预报。

    返回多日天气信息，包括白天/夜间天气状况、温度、风向风力。

    Args:
        city: 城市名称，如 '北京'、'杭州'
    """
    service = get_amap_service()
    results = service.get_weather(city=city)
    if not results:
        return json.dumps({"message": f"未获取到{city}的天气信息", "forecasts": []}, ensure_ascii=False)
    return json.dumps({"forecasts": results}, ensure_ascii=False)


@tool
def search_hotels(city: str, keywords: str = "酒店") -> str:
    """
    搜索指定城市的酒店住宿。

    根据城市和关键词搜索酒店，返回酒店列表，包含名称、地址、评分、价格等信息。

    Args:
        city: 城市名称，如 '北京'
        keywords: 搜索关键词，如 '酒店'、'经济型酒店'、'民宿'
    """
    service = get_amap_service()
    results = service.search_poi(keywords=keywords, city=city)
    if not results:
        return json.dumps({"message": f"未找到{keywords}", "hotels": []}, ensure_ascii=False)
    return json.dumps({"hotels": results}, ensure_ascii=False)


@tool
def plan_route_between(
    origin_address: str,
    destination_address: str,
    route_type: str = "walking"
) -> str:
    """
    规划两个地点之间的路线，返回距离和预计时间。

    用于验证旅行计划中相邻景点的距离是否合理。

    Args:
        origin_address: 起点地址
        destination_address: 终点地址
        route_type: 出行方式，'walking'（步行）、'driving'（驾车）、'transit'（公交）
    """
    service = get_amap_service()
    result = service.plan_route(
        origin_address=origin_address,
        destination_address=destination_address,
        route_type=route_type,
    )
    if not result:
        return json.dumps({"message": "路线规划失败"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ==================== 工具注册表 ====================

ALL_TOOLS = [
    search_attractions,
    query_weather,
    search_hotels,
    plan_route_between,
]

# 按Agent角色分组的工具
ATTRACTION_TOOLS = [search_attractions]
WEATHER_TOOLS = [query_weather]
HOTEL_TOOLS = [search_hotels]
REVIEWER_TOOLS = [plan_route_between]  # Reviewer可以用路线工具验证距离
