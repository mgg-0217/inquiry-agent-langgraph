from __future__ import annotations

from app.graph.nodes import make_triage_node
from app.graph.state import MailInput, Triage
from app.graph.triage import rule_prefilter, triage_mail
from tests.fakes import FakeLLM

NORMAL_BODY = "Please quote 100 units of X200, 380V/50Hz, CIF Valencia."


def make_mail(**kwargs) -> MailInput:
    data = dict(
        message_id="<triage-1@acme-import.example>",
        subject="Inquiry: X200",
        from_email="buyer@acme-import.example",
        from_name="Buyer",
        body_text=NORMAL_BODY,
    )
    data.update(kwargs)
    return MailInput(**data)


# ---------------------------------------------------------------- L1 规则


def test_empty_body_is_spam():
    pre = rule_prefilter(make_mail(body_text="", body_html=""))
    assert pre is not None
    assert pre.is_spam is True
    assert pre.spam_reason == "无正文"


def test_blacklisted_domain_is_spam():
    pre = rule_prefilter(
        make_mail(from_email="promo@spam-xyz.example", body_text="Buy now!")
    )
    assert pre is not None
    assert "黑名单域名" in pre.spam_reason


def test_too_many_links_is_spam():
    links = " ".join(f"https://spam.example/{i}" for i in range(12))
    pre = rule_prefilter(make_mail(body_text=f"Check these: {links}"))
    assert pre is not None
    assert "外链" in pre.spam_reason


def test_normal_mail_passes_prefilter():
    assert rule_prefilter(make_mail()) is None


# ---------------------------------------------------------------- L2 LLM


def test_normal_mail_uses_llm_and_is_complete():
    llm = FakeLLM({Triage: Triage(complete=True, confidence=0.9)})
    triage = triage_mail(llm, make_mail())
    assert triage.is_spam is False
    assert triage.complete is True
    assert triage.need_review is False


def test_llm_failure_is_conservative_and_marked_for_review():
    llm = FakeLLM({Triage: RuntimeError("timeout")})
    triage = triage_mail(llm, make_mail())
    # 宁可漏判，不可误杀：放行但标记人工复核
    assert triage.is_spam is False
    assert triage.need_review is True
    assert "分诊失败" in triage.spam_reason


def test_low_confidence_spam_is_marked_for_review():
    llm = FakeLLM({Triage: Triage(is_spam=True, confidence=0.5)})
    triage = triage_mail(llm, make_mail())
    assert triage.is_spam is True
    assert triage.need_review is True


# ---------------------------------------------------------------- 节点行为


def test_negotiation_is_written_back_to_mail():
    llm = FakeLLM(
        {
            Triage: Triage(
                complete=True,
                confidence=0.95,
                is_negotiation=True,
                client_offered_price=350.0,
            )
        }
    )
    node = make_triage_node(llm)
    state = {
        "mail": make_mail(body_text="USD 364 is above our budget. Competitor offers USD 350."),
        "step": 0,
        "trace": [],
        "clarify_count": 0,
    }
    out = node(state)

    assert out["triage"].is_negotiation is True
    # after_decide 读的是 state["mail"].is_price_negotiation（PRD 7.3.1）
    assert out["mail"].is_price_negotiation is True
    assert out["mail"].client_offered_price == 350.0
    assert "还价" in out["trace"][0].summary


def test_manual_restore_skips_spam_judgement():
    llm = FakeLLM({Triage: Triage(is_spam=True, confidence=0.99)})
    node = make_triage_node(llm)
    state = {
        "mail": make_mail(),
        "step": 0,
        "trace": [],
        "clarify_count": 0,
        "manual_restore": True,
    }
    out = node(state)
    assert out["triage"].is_spam is False
    assert out["triage"].complete is True
