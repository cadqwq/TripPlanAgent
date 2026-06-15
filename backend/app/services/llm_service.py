"""LLM服务模块 — 基于 langchain-openai 封装 DeepSeek 大模型调用"""

import os
from langchain_openai import ChatOpenAI
from ..config import get_settings

# 全局单例，整个应用只初始化一次
_llm_instance = None


def get_llm() -> ChatOpenAI:
    """
    获取 ChatOpenAI 实例（单例模式）

    DeepSeek API 兼容 OpenAI SDK，直接用 ChatOpenAI 即可。
    第一次调用时初始化，之后返回同一个实例。
    """
    global _llm_instance

    if _llm_instance is None:
        settings = get_settings()

        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("LLM_BASE_URL") or "https://api.deepseek.com"
        model = os.getenv("LLM_MODEL_ID") or "deepseek-v4-pro"

        _llm_instance = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=4096,
            timeout=60,
            max_retries=2,
        )

        print(f"✅  LLM服务初始化成功 (langchain-openai)")
        print(f"   模型: {model}")
        print(f"   Base URL: {base_url}")

    return _llm_instance


def get_llm_json_mode() -> ChatOpenAI:
    """
    获取 JSON 模式（结构化输出）的 LLM 实例

    用于 Planner 和 Reviewer 等需要返回 JSON 的场景。
    """
    llm = get_llm()
    return llm.bind(response_format={"type": "json_object"})
