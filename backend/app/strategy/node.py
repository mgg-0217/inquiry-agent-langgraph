"""策略判断的调用封装 + 重试兜底（PRD 7.8.2 调用方式）。

只依赖一个"能 with_structured_output 的 llm"协议，因此可以完全脱库测试；
真实 LLM 在 `llm/client.py` 里构造（第 4 天接）。
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.strategy.prompt import build_messages
from app.strategy.resolve import guard
from app.strategy.schema import ReplyStrategy, StrategyContext

logger = logging.getLogger(__name__)

FALLBACK = ReplyStrategy(
    stance="escalate",
    mention_history=False,
    price_adjustment="none",
    key_points=[],
    rationale="",
)


def assess_strategy(
    llm,
    context: StrategyContext,
    *,
    retries: int = 1,
    structured_method: str = "function_calling",
) -> ReplyStrategy:
    """调用模型拿结构化策略；失败重试 `retries` 次，仍失败返回 escalate 兜底。

    `structured_method` 默认走 function calling：DeepSeek 目前不支持
    `response_format: json_schema`（会返回 400），而 function calling 已实测可用。
    temperature 由调用方在构造 llm 时设为 0（判断类节点要求可复现，PRD 11.3）。
    """
    structured = llm.with_structured_output(ReplyStrategy, method=structured_method)
    messages = build_messages(context)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = structured.invoke(messages)
            if isinstance(raw, ReplyStrategy):
                return raw
            return ReplyStrategy.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - 任何模型/解析错误都走兜底
            last_error = exc
            logger.warning("策略判断失败（第 %d 次）：%s", attempt + 1, exc)

    fallback = FALLBACK.model_copy(deep=True)
    fallback.rationale = f"策略判断连续失败 {retries + 1} 次，兜底转人工：{last_error}"
    return fallback


def assess_and_guard(
    llm,
    context: StrategyContext,
    quote,
    customer: dict | None,
    *,
    retries: int = 1,
    structured_method: str = "function_calling",
    settings: Settings | None = None,
) -> ReplyStrategy:
    """模型判断 + 代码校验，返回可直接使用的策略对象。"""
    strategy = assess_strategy(
        llm, context, retries=retries, structured_method=structured_method
    )
    return guard(strategy, quote, customer, settings)
