"""配置管理模块"""

import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "TripPlanAgent智能旅行助手"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS配置 — 允许哪些前端地址跨域访问
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = ""

    # Unsplash API配置（可选）
    unsplash_access_key: str = ""
    unsplash_secret_key: str = ""

    # LLM配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4"

    # 日志配置
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

    def get_cors_origins_list(self) -> List[str]:
        """将逗号分隔的CORS字符串转换为列表"""
        return [origin.strip() for origin in self.cors_origins.split(',')]


# 全局单例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def validate_config():
    """验证必要配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        errors.append("AMAP_API_KEY未配置")

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        from loguru import logger
        for w in warnings:
            logger.warning("配置警告: {}", w)

    return True


def setup_logging():
    """配置 loguru 结构化日志"""
    import sys
    from loguru import logger

    # 移除默认 handler
    logger.remove()

    # 控制台输出：彩色格式
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
        level=settings.log_level,
        colorize=True,
    )

    # 文件输出：结构化格式（便于后续接入 ELK/Loki）
    logger.add(
        "logs/trip_agent_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    return logger


def print_config():
    """打印当前配置(隐藏敏感信息)"""
    from loguru import logger
    logger.info("应用名称: {}", settings.app_name)
    logger.info("版本: {}", settings.app_version)
    logger.info("服务器: {}:{}", settings.host, settings.port)
    logger.info("高德地图API Key: {}", '已配置' if settings.amap_api_key else '未配置')

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or settings.openai_model

    logger.info("LLM API Key: {}", '已配置' if llm_api_key else '未配置')
    logger.info("LLM Base URL: {}", llm_base_url)
    logger.info("LLM Model: {}", llm_model)
    logger.info("日志级别: {}", settings.log_level)
