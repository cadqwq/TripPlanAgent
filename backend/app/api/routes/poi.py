from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from ...services.amap_service import get_amap_service
from ...services.unsplash_service import get_unsplash_service

router = APIRouter(prefix="/poi", tags=["POI"])


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.get("/search", summary="搜索POI")
async def search_poi(
        keywords: str = Query(..., description="搜索关键词"),
        city: str = Query("北京", description="城市名称")
):
    """根据关键词搜索POI"""
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi(keywords, city)
        return {"success": True, "message": "搜索成功", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索POI失败: {str(e)}")


@router.get("/detail/{poi_id}", response_model=POIDetailResponse, summary="获取POI详情")
async def get_poi_detail(poi_id: str):
    """根据POI ID获取详细信息"""
    try:
        amap_service = get_amap_service()
        result = amap_service.get_poi_detail(poi_id)
        return POIDetailResponse(success=True, message="获取POI详情成功", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取POI详情失败: {str(e)}")


@router.get("/photo", summary="获取景点图片")
async def get_attraction_photo(name: str = Query(..., description="景点名称")):
    """从Unsplash获取景点图片"""
    try:
        unsplash_service = get_unsplash_service()
        photo_url = unsplash_service.get_photo_url(f"{name} China landmark")
        if not photo_url:
            photo_url = unsplash_service.get_photo_url(name)
        return {
            "success": True,
            "message": "获取图片成功",
            "data": {"name": name, "photo_url": photo_url}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取景点图片失败: {str(e)}")