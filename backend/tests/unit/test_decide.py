from __future__ import annotations

from app.config import settings
from app.graph.decide import apply_hard_rules, decide
from app.graph.state import (
    AgentState,
    Decision,
    MailInput,
    Quote,
    Triage,
    Verdict,
)
from tests.fakes import FakeLLM


def make_mail(**kwargs) -> MailInput:
    data = dict(
        message_id="<decide-1@acme-import.example>",
        subject="Inquiry",
        from_email="buyer@newco.example",
        body_text="Please quote.",
    )
    data.update(kwargs)
    return MailInput(**data)


def make_quote(*, unit_price: float = 350.0, qty: int = 120) -> Quote:
    return Quote(
        sku="X200",
        qty=qty,
        unit_price=unit_price,
        floor_price=338.0,
        total=round(unit_price * qty, 2),
        incoterm="CIF",
        destination="Valencia",
    )


def base_state(**kwargs) -> AgentState:
    state: AgentState = {
        "mail": make_mail(),
        "quote": make_quote(),
        "verdict": Verdict(result="pass", score=0.0),
        "triage": Triage(complete=True, confidence=0.95),
        "round": 1,
        "is_followup": False,
    }
    state.update(kwargs)
    return state


# ---------------------------------------------------------------- 硬规则


def test_over_authorization_forces_escalate_even_if_model_says_auto():
    state = base_state(quote=make_quote(qty=500))  # 175,000 > 150,000
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "escalate"
    assert "超授权" in result.reason


def test_compliance_reject_forces_reject():
    state = base_state(verdict=Verdict(result="reject", score=0.99))
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "reject"


def test_compliance_need_review_forces_escalate():
    state = base_state(verdict=Verdict(result="need_review", score=0.8))
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "escalate"
    assert "合规" in result.reason


def test_triage_need_review_forces_escalate():
    state = base_state(triage=Triage(complete=True, need_review=True))
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "escalate"


def test_no_quote_forces_escalate():
    state = base_state(quote=None)
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "escalate"


def test_negotiation_below_quoted_price_forces_escalate():
    """客户要求低于本次报价 → 必须人工决定是否让价。"""
    state = base_state(
        is_followup=True,
        round=2,
        mail=make_mail(is_price_negotiation=True, client_offered_price=340.0),
    )
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "escalate"
    assert "低于本次报价" in result.reason


def test_negotiation_volume_tier_keeps_auto_reply():
    """数量变化、只问优惠（没给目标价）→ 按阶梯价自动回复，不转人工。"""
    state = base_state(
        is_followup=True,
        round=2,
        mail=make_mail(is_price_negotiation=True, client_offered_price=None),
    )
    result = apply_hard_rules(Decision(action="auto_reply"), state)
    assert result.action == "auto_reply"


def test_model_escalate_is_kept():
    result = apply_hard_rules(Decision(action="escalate", reason="模型想转人工"), base_state())
    assert result.action == "escalate"
    assert result.reason == "模型想转人工"


def test_auto_reply_within_limit_is_kept():
    result = apply_hard_rules(Decision(action="auto_reply", reason="授权内"), base_state())
    assert result.action == "auto_reply"


# ---------------------------------------------------------------- 模型调用


def test_decide_uses_model_suggestion_when_no_hard_rule():
    llm = FakeLLM({Decision: Decision(action="escalate", reason="客户要求账期")})
    decision = decide(llm, base_state())
    assert decision.action == "escalate"
    assert decision.reason == "客户要求账期"


def test_decide_falls_back_to_escalate_when_model_fails():
    llm = FakeLLM({Decision: RuntimeError("timeout")})
    decision = decide(llm, base_state())
    assert decision.action == "escalate"
    assert "决策失败" in decision.reason
