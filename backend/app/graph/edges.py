"""4 个条件分支（PRD 7.3）。

分支函数必须是纯函数：只读 state，返回下一节点名。
"""

from __future__ import annotations

from typing import Literal

from app.config import settings
from app.graph.state import AgentState


def after_triage(state: AgentState) -> Literal["archive", "clarify", "resolve"]:
    """垃圾 → 归档；信息不完整且追问未超限 → 追问；否则继续。"""
    triage = state.get("triage")
    if triage is None:
        return "resolve"
    # 宁可漏判 spam，不可误杀真询盘：只有高置信度才自动归档（ADR-11）
    if triage.is_spam and triage.confidence >= settings.spam_threshold:
        return "archive"
    if not triage.complete and state.get("clarify_count", 0) < 2:
        return "clarify"
    return "resolve"


def after_compliance(state: AgentState) -> Literal["archive", "decide"]:
    verdict = state.get("verdict")
    if verdict is not None and verdict.result == "reject":
        return "archive"
    return "decide"


def after_decide(state: AgentState) -> Literal["archive", "compose", "dispatch"]:
    """议价轮一律转人工（C2 / ADR-17），与模型给出的 action 无关。"""
    mail = state.get("mail")
    if (
        state.get("is_followup")
        and state.get("round", 1) >= 2
        and mail is not None
        and mail.is_price_negotiation
    ):
        return "compose"

    decision = state.get("decision")
    if decision is not None:
        if decision.action == "reject":
            return "archive"
        if decision.action == "escalate":
            return "compose"
    # 授权内自动回复：也必须先生成 + fact_check，不能发空邮件
    return "compose"


def after_compose(state: AgentState) -> Literal["dispatch", "approval"]:
    """事实校验通过且模型判 auto_reply → 直接发；否则一律送审。"""
    decision = state.get("decision")
    if (
        decision is not None
        and decision.action == "auto_reply"
        and state.get("fact_check_ok") is True
    ):
        return "dispatch"
    return "approval"


def after_approval(
    state: AgentState,
) -> Literal["dispatch", "compose", "archive", "approval"]:
    approval = state.get("approval")
    if approval is None:
        return "archive"
    if approval.action == "approve":
        return "dispatch"
    if approval.action == "modify":
        return "compose"
    if approval.action == "reassign":
        # 转他人：重新挂起，等新的审批人
        return "approval"
    return "archive"
