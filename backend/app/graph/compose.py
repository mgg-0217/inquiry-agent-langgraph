"""回复生成 + 事实校验 + 失败重写（PRD F7）。

校验不通过时重写一次；仍不通过则把 `fact_check_ok=false` 写进状态，
由 `after_compose` 强制走审批（不会自动发出）。
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.graph.fact_check import FactCheckResult, check_reply
from app.graph.prompts.compose import build_compose_messages, build_rewrite_messages
from app.graph.state import AgentState

logger = logging.getLogger(__name__)


def _invoke(llm, messages) -> str:
    response = llm.invoke(messages)
    content = getattr(response, "content", "") or ""
    return str(content).strip()


def facts_from_state(state: AgentState) -> dict:
    """把 state 里的报价/库存转成 fact_check 的允许数字集合。"""
    quote = state.get("quote")
    inventory = state.get("inventory")
    facts: dict = {"valid_days": settings.quote_valid_days}
    if quote is not None:
        facts["unit_price"] = quote.unit_price
        facts["total"] = quote.total
        facts["tier_prices"] = [tier.unit_price for tier in quote.tiers]
    if inventory is not None and inventory.lead_time:
        match = re.search(r"(\d+)", inventory.lead_time)
        if match:
            facts["lead_time_days"] = int(match.group(1))
    return facts


def _empty_result() -> FactCheckResult:
    return FactCheckResult(ok=False, violations=["回复为空"])


def compose_reply(llm, state: AgentState) -> tuple[str, FactCheckResult]:
    messages = build_compose_messages(state)
    reply = _invoke(llm, messages)
    if not reply:
        reply = _invoke(llm, messages)
    if not reply:
        return "", _empty_result()

    result = check_reply(reply, facts_from_state(state))
    if result.ok:
        return reply, result

    logger.warning("事实校验失败，附反馈重写一次：%s", result.feedback)
    rewritten = _invoke(llm, build_rewrite_messages(messages, reply, result.feedback))
    if not rewritten:
        return "", _empty_result()
    result = check_reply(rewritten, facts_from_state(state))
    if result.ok:
        return rewritten, result

    logger.warning("重写后仍未通过事实校验：%s", result.feedback)
    return rewritten, result
