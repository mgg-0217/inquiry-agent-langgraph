"""合规筛查测试（第 5—6 天自检）。

前置：`python scripts/fetch_sanctions.py --out backend/data/sanctions/ --insecure`
      生成 `entries.json`，否则整个文件跳过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.compliance.disambiguate import SanctionsIndex, screen_name
from app.compliance.loader import load_json

DATA = Path(__file__).resolve().parents[2] / "data" / "sanctions" / "entries.json"

pytestmark = pytest.mark.skipif(
    not DATA.exists(), reason="缺制裁名单数据，先跑 scripts/fetch_sanctions.py"
)


@pytest.fixture(scope="module")
def sanctions() -> SanctionsIndex:
    records = load_json(DATA)
    assert records, "entries.json 为空"
    return SanctionsIndex(records)


# ---------------------------------------------------------------- 真实条目命中


def test_exact_name_hits_real_ofac_entry(sanctions: SanctionsIndex):
    hits = screen_name("BANCO NACIONAL DE CUBA", sanctions.records, index=sanctions)
    assert hits, "应当命中真实 SDN 条目"
    top = hits[0]
    assert top.entry_no == "306"
    assert top.score >= 0.95
    assert "OFAC SDN #306" in top.evidence


def test_alias_hits_same_entry(sanctions: SanctionsIndex):
    hits = screen_name("BNC", sanctions.records, index=sanctions)
    assert hits
    assert hits[0].entry_no == "306"
    assert hits[0].score >= 0.95
    assert hits[0].matched_alias


def test_vessel_or_company_name_hits(sanctions: SanctionsIndex):
    hits = screen_name("AEROCARIBBEAN AIRLINES", sanctions.records, index=sanctions)
    assert hits and hits[0].entry_no == "36"
    assert hits[0].score >= 0.95


def test_country_adds_small_bonus(sanctions: SanctionsIndex):
    without_country = screen_name("BANCO NACIONAL DE CUBA", sanctions.records, index=sanctions)
    with_country = screen_name(
        "BANCO NACIONAL DE CUBA", sanctions.records, country="CU", index=sanctions
    )
    assert with_country[0].score >= without_country[0].score


# ---------------------------------------------------------------- 不误杀


def test_clean_company_is_not_flagged(sanctions: SanctionsIndex):
    hits = screen_name("Acme Import S.L.", sanctions.records, index=sanctions)
    assert not hits or hits[0].score < 0.75


def test_common_business_words_do_not_cause_false_positive(sanctions: SanctionsIndex):
    """NewCo Trading 只与 NEWTON TRADING FZE 共享 TRADING（停用词）。"""
    hits = screen_name("NewCo Trading", sanctions.records, index=sanctions)
    assert not hits or hits[0].score < 0.75


# ---------------------------------------------------------------- 工具与节点


def test_tool_returns_hits_and_evidence(sanctions: SanctionsIndex):
    from app.tools.compliance import screen_compliance

    result = screen_compliance("BANCO NACIONAL DE CUBA", "CU", index=sanctions)
    assert result["ok"] is True
    data = result["data"]
    assert data["list_loaded"] is True
    assert data["score"] >= 0.95
    assert data["hits"][0]["entry_no"] == "306"
    assert data["evidence"][0].startswith("OFAC SDN #306")


def test_tool_without_list_does_not_claim_pass(session, monkeypatch):
    import app.tools.compliance as tool_mod

    monkeypatch.setattr(tool_mod, "_index_cache", None)
    monkeypatch.setattr(tool_mod, "load_from_db", lambda _session: [])
    result = tool_mod.screen_compliance("Acme", session=session)
    assert result["data"]["list_loaded"] is False
    assert "不可作为放行依据" in result["message"]


def _verdict_for(session_factory, monkeypatch, payload: dict, customer_name: str = "Test Co"):
    from app.db.models import Customer
    from app.graph.nodes import make_compliance_node
    import app.graph.nodes as nodes_mod

    with session_factory() as db:
        customer = Customer(email=f"{customer_name}@test.example", name=customer_name)
        db.add(customer)
        db.commit()
        customer_id = customer.id

    monkeypatch.setattr(nodes_mod, "screen_compliance", lambda *a, **k: payload)
    node = make_compliance_node(session_factory)
    state = {
        "mail": {"message_id": "<c@x>"},
        "customer_id": customer_id,
        "step": 0,
        "trace": [],
    }
    out = node(state)  # type: ignore[arg-type]
    return out["verdict"]


def test_node_rejects_on_high_score(session_factory, monkeypatch):
    verdict = _verdict_for(
        session_factory,
        monkeypatch,
        {
            "ok": True,
            "data": {
                "list_loaded": True,
                "score": 0.99,
                "hits": [{"list_name": "OFAC SDN", "entry_no": "306", "name": "X", "score": 0.99, "evidence": "OFAC SDN #306"}],
                "evidence": ["OFAC SDN #306"],
            },
        },
    )
    assert verdict.result == "reject"
    assert "SANCTION_HIT" in verdict.rules_hit


def test_node_marks_review_on_medium_score(session_factory, monkeypatch):
    verdict = _verdict_for(
        session_factory,
        monkeypatch,
        {
            "ok": True,
            "data": {
                "list_loaded": True,
                "score": 0.8,
                "hits": [],
                "evidence": [],
            },
        },
    )
    assert verdict.result == "need_review"


def test_node_passes_on_low_score(session_factory, monkeypatch):
    verdict = _verdict_for(
        session_factory,
        monkeypatch,
        {"ok": True, "data": {"list_loaded": True, "score": 0.2, "hits": [], "evidence": []}},
    )
    assert verdict.result == "pass"


def test_node_requires_review_when_list_missing(session_factory, monkeypatch):
    verdict = _verdict_for(
        session_factory,
        monkeypatch,
        {"ok": True, "data": {"list_loaded": False, "score": 0.0, "hits": [], "evidence": []}},
    )
    assert verdict.result == "need_review"
    assert "SANCTIONS_NOT_LOADED" in verdict.rules_hit
