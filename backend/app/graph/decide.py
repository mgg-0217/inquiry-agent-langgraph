"""决策路由（PRD F8）。

分工：**模型建议 + 代码硬规则否决**。
- 模型：语气、策略、是否提历史、是否升级
- 代码：超授权、合规需复核、议价轮、没有报价 —— 这些一律 escalate，不看模型
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.graph.prompts.decide import build_decide_messages
from app.graph.state import AgentState, Decision
from app.llm.structured import structured_output

logger = logging.getLogger(__name__)


def suggest_decision(llm, state: AgentState) -> Decision:
    """模型建议；失败时保守 escalate。"""
    try:
        raw = structured_output(llm, Decision).invoke(build_decide_messages(state))
        suggestion = raw if isinstance(raw, Decision) else Decision.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("决策建议失败，兜底转人工：%s", exc)
        return Decision(action="escalate", reason=f"决策失败：{exc}", confidence=0.0)
    return suggestion


def apply_hard_rules(suggestion: Decision, state: AgentState) -> Decision:
    """硬规则覆盖模型建议（PRD ADR-10）。"""
    quote = state.get("quote")
    verdict = state.get("verdict")
    triage = state.get("triage")
    mail = state.get("mail")

    action = suggestion.action
    reasons: list[str] = []

    if verdict is not None and verdict.result == "reject":
        return Decision(
            action="reject",
            reason="合规拦截（代码硬规则）",
            confidence=1.0,
        )

    if quote is None:
        action = "escalate"
        reasons.append("没有可报价的产品/数量")

    if verdict is not None and verdict.result == "need_review":
        action = "escalate"
        reasons.append("合规需人工复核")

    if triage is not None and triage.need_review:
        action = "escalate"
        reasons.append("分诊需人工复核")

    if quote is not None and quote.total > settings.auto_reply_limit:
        action = "escalate"
        reasons.append(
            f"总价 ${quote.total:,.0f} 超授权额度 ${settings.auto_reply_limit:,.0f}"
        )

    if (
        state.get("is_followup")
        and state.get("round", 1) >= 2
        and mail is not None
        and mail.is_price_negotiation
    ):
        # 议价轮：数量变化按阶梯价报价可以自动回；只有“客户要求低于本次报价”才转人工
        offered = mail.client_offered_price if mail is not None else None
        quoted = quote.unit_price if quote is not None else None
        if offered is not None and quoted is not None and offered < quoted:
            action = "escalate"
            reasons.append(
                f"客户目标价 ${offered:g} 低于本次报价 ${quoted:g}，需人工决定是否让价"
            )
        # 否则交给模型：数量档位自动给价，不需要人工

    if action == suggestion.action and not reasons:
        reason = suggestion.reason or "模型建议"
    elif action == "escalate":
        reason = "；".join(reasons) or suggestion.reason or "转人工"
    else:
        reason = suggestion.reason or "模型建议"

    return Decision(
        action=action,
        reason=reason,
        confidence=suggestion.confidence,
    )


def decide(llm, state: AgentState) -> Decision:
    return apply_hard_rules(suggest_decision(llm, state), state)
