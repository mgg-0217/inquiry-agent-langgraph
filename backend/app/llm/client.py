"""ChatOpenAI 封装（重试 / 超时 / 温度）。"""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import settings


@lru_cache(maxsize=8)
def get_chat_llm(temperature: float | None = None) -> ChatOpenAI:
    """按温度缓存 LLM 实例。

    判断类节点用 `LLM_TEMPERATURE_JUDGE`（0，保证可复现），
    撰写类节点用 `LLM_TEMPERATURE_COMPOSE`（0.3，语言更自然）。
    """
    temp = settings.llm_temperature_judge if temperature is None else temperature
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=temp,
        timeout=60,
        max_retries=2,
    )
