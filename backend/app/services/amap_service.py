"""高德地图服务封装 — 直接调用高德 REST API"""

import json
from typing import List, Dict, Any, Optional
import httpx
from loguru import logger
from ..config import get_settings

# 高德地图 API 基础地址
AMAP_BASE_URL = "https://restapi.amap.com/v3"


class AmapService:
    """高德地图服务封装类 — 直接 HTTP 调用，无 MCP 依赖"""

    def __init__(self):
        settings = get_settings()
        if not settings.amap_api_key:
            raise ValueError("高德地图API Key未配置，请在.env文件中设置AMAP_API_KEY")
        self.api_key = settings.amap_api_key
        self._client = httpx.Client(timeout=15.0)
        logger.info("高德地图服务初始化成功 (REST API)")

    def _get(self, path: str, params: dict) -> dict:
        """统一 GET 请求"""
        params["key"] = self.api_key
        url = f"{AMAP_BASE_URL}{path}"
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "1":
                logger.warning("高德API返回异常 | info={} path={}", data.get('info', 'unknown'), path)
                return {}
            return data
        except Exception as e:
            logger.error("高德API请求失败 | path={} error={}", path, e)
            return {}

    # ==================== POI 搜索 ====================

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[dict]:
        """
        搜索POI（兴趣点）

        API: https://restapi.amap.com/v3/place/text
        """
        data = self._get("/place/text", {
            "keywords": keywords,
            "city": city,
            "citylimit": str(citylimit).lower(),
            "offset": "20",
            "page": "1",
            "extensions": "all",
        })

        if not data:
            return []

        pois = data.get("pois", [])
        results = []
        for p in pois:
            # 解析 location "116.397128,39.916527"
            loc_str = p.get("location", "0,0")
            try:
                lng_str, lat_str = loc_str.split(",")
                lng, lat = float(lng_str), float(lat_str)
            except (ValueError, AttributeError):
                lng, lat = 0.0, 0.0

            # 扩展信息
            biz_ext = p.get("biz_ext", {}) or {}
            deep_info = p.get("deep_info", {}) or {}

            results.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "address": p.get("address", ""),
                "location": {"longitude": lng, "latitude": lat},
                "tel": p.get("tel", "") or "",
                "rating": biz_ext.get("rating", "") or deep_info.get("rating", ""),
                "cost": biz_ext.get("cost", "") or "",
                "photos": [pic.get("url") for pic in p.get("photos", [])],
            })

        logger.info("POI搜索完成 | keywords={} city={} count={}", keywords, city, len(results))
        return results

    # ==================== 天气查询 ====================

    def get_weather(self, city: str) -> List[dict]:
        """
        查询天气预报

        API: https://restapi.amap.com/v3/weather/weatherInfo
        返回多日天气预报
        """
        # 先获取城市编码
        adcode = self._get_adcode(city)

        data = self._get("/weather/weatherInfo", {
            "city": adcode or city,
            "extensions": "all",  # 返回多日预报
        })

        if not data:
            return []

        results = []

        # 处理 forecasts（多日预报）
        forecasts = data.get("forecasts", [])
        for forecast in forecasts:
            casts = forecast.get("casts", [])
            for cast in casts:
                results.append({
                    "date": cast.get("date", ""),
                    "day_weather": cast.get("dayweather", ""),
                    "night_weather": cast.get("nightweather", ""),
                    "day_temp": self._parse_temp(cast.get("daytemp", "0")),
                    "night_temp": self._parse_temp(cast.get("nighttemp", "0")),
                    "wind_direction": cast.get("daywind", ""),
                    "wind_power": cast.get("daypower", ""),
                })

        # 如果 forecasts 为空，尝试 lives（实时天气）
        if not results:
            lives = data.get("lives", [])
            for live in lives:
                results.append({
                    "date": live.get("reporttime", ""),
                    "day_weather": live.get("weather", ""),
                    "night_weather": live.get("weather", ""),
                    "day_temp": self._parse_temp(live.get("temperature", "0")),
                    "night_temp": self._parse_temp(live.get("temperature", "0")),
                    "wind_direction": live.get("winddirection", ""),
                    "wind_power": live.get("windpower", ""),
                })

        logger.info("天气查询完成 | city={} days={}", city, len(results))
        return results

    def _get_adcode(self, city: str) -> str:
        """通过城市名获取 adcode（行政区划代码）"""
        # 缓存
        if not hasattr(self, '_adcode_cache'):
            self._adcode_cache = {}

        if city in self._adcode_cache:
            return self._adcode_cache[city]

        data = self._get("/config/district", {
            "keywords": city,
            "subdistrict": "0",
        })

        districts = data.get("districts", [])
        if districts:
            adcode = districts[0].get("adcode", "")
            self._adcode_cache[city] = adcode
            return adcode
        return ""

    @staticmethod
    def _parse_temp(temp_value: Any) -> int:
        """解析温度值"""
        if isinstance(temp_value, (int, float)):
            return int(temp_value)
        if isinstance(temp_value, str):
            temp_value = temp_value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(temp_value)
            except ValueError:
                return 0
        return 0

    # ==================== 路线规划 ====================

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """
        规划两点之间的路线

        API:
        - walking: /direction/walking
        - driving: /direction/driving
        - transit: /direction/transit/integrated
        """
        try:
            # 先地理编码获取坐标
            origin_lnglat = self._geocode_address(origin_address, origin_city)
            dest_lnglat = self._geocode_address(destination_address, destination_city)

            if not origin_lnglat or not dest_lnglat:
                return {}

            origin = f"{origin_lnglat[0]},{origin_lnglat[1]}"
            destination = f"{dest_lnglat[0]},{dest_lnglat[1]}"

            path_map = {
                "walking": "/direction/walking",
                "driving": "/direction/driving",
                "transit": "/direction/transit/integrated",
            }

            path = path_map.get(route_type, "/direction/walking")
            data = self._get(path, {
                "origin": origin,
                "destination": destination,
            })

            if not data:
                return {}

            route = data.get("route", {})
            paths = route.get("paths", [])
            if paths:
                p = paths[0]
                distance = int(p.get("distance", 0))
                duration = int(p.get("duration", 0))
                return {
                    "distance": distance,
                    "duration": duration,
                    "route_type": route_type,
                    "description": f"距离{distance}米，约需{duration // 60}分钟",
                    "origin": origin_address,
                    "destination": destination_address,
                }

            return {}

        except Exception as e:
            logger.error("路线规划失败 | error={}", e)
            return {}

    def _geocode_address(self, address: str, city: Optional[str] = None) -> Optional[tuple]:
        """地理编码：地址 → (lng, lat)"""
        params = {"address": address}
        if city:
            params["city"] = city

        data = self._get("/geocode/geo", params)
        geocodes = data.get("geocodes", [])
        if geocodes:
            loc_str = geocodes[0].get("location", "")
            if "," in loc_str:
                lng, lat = loc_str.split(",")
                return (float(lng), float(lat))
        return None

    # ==================== 地理编码 ====================

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[dict]:
        """地理编码：地址 → 经纬度"""
        lnglat = self._geocode_address(address, city)
        if lnglat:
            return {"longitude": lnglat[0], "latitude": lnglat[1]}
        return None

    # ==================== POI 详情 ====================

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """获取POI详细信息"""
        data = self._get("/place/detail", {"id": poi_id})

        if not data:
            return {}

        pois = data.get("pois", [])
        if pois:
            p = pois[0]
            loc_str = p.get("location", "0,0")
            lng_str, lat_str = loc_str.split(",")
            return {
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "address": p.get("address", ""),
                "location": {"longitude": float(lng_str), "latitude": float(lat_str)},
                "tel": p.get("tel", ""),
                "photos": [pic.get("url") for pic in p.get("photos", [])],
                "description": p.get("deep_info", {}).get("intro", ""),
            }

        return {}


# ==================== 全局单例 ====================

_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例（单例模式）"""
    global _amap_service
    if _amap_service is None:
        _amap_service = AmapService()
    return _amap_service
