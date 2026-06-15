"""FastAPI主应用"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, setup_logging, print_config
from .routes import trip, poi, map as map_routes

settings = get_settings()

# 初始化日志系统
logger = setup_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于 LangGraph 多智能体的旅行规划助手API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(trip.router, prefix="/api")
app.include_router(poi.router, prefix="/api")
app.include_router(map_routes.router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("=" * 50)
    logger.info("{} v{} 启动中...", settings.app_name, settings.app_version)
    logger.info("=" * 50)
    try:
        validate_config()
        logger.info("配置验证通过")
    except ValueError as e:
        logger.error("配置验证失败: {}", e)
        raise
    print_config()
    logger.info("API文档: http://localhost:8000/docs")
    logger.info("=" * 50)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy", "service": settings.app_name}