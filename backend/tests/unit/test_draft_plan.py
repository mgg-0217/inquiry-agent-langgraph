from __future__ import annotations

from app.graph.draft_plan import build_quote
from app.graph.nodes import make_draft_plan_node
from app.graph.state import InquirySpec, MailInput, MemoryContext, MemoryFact, ReplyStrategy
from tests.fakes import FakeLLM

BODY = "Dear Sales, please quote 120 units of X200 pump, 380V/50Hz, CIF Valencia."


def make_mail(body: str = BODY) -> MailInput:
    return MailInput(
        message_id="<draft-1@acme-import.example>",
        subject="Inquiry: X200 120 units",
        from_email="carlos@acme-import.example",
        from_name="Carlos",
        body_text=body,
    )


def make_node(session_factory, *, spec: InquirySpec, strategy: ReplyStrategy | None = None):
    llm = FakeLLM(
        {
            InquirySpec: spec,
            ReplyStrategy: strategy
            or ReplyStrategy(
                stance="standard",
                mention_history=False,
                price_adjustment="none",
                key_points=["price", "lead_time", "validity"],
                rationale="常规报价",
            ),
        }
    )
    return make_draft_plan_node(llm, session_factory)


def run(node, memory: MemoryContext | None = None):
    state = {
        "mail": make_mail(),
        "customer_id": None,
        "step": 0,
        "trace": [],
        "round": 1,
        "memory": memory,
    }
    return node(state)


# ---------------------------------------------------------------- 正常算价


def test_quote_comes_from_calc_price_tool(session_factory):
    node = make_node(
        session_factory,
        spec=InquirySpec(sku="X200", quantity=120, incoterm="CIF", destination="Valencia"),
    )
    out = run(node)

    quote = out["quote"]
    assert quote is not None
    assert quote.sku == "X200"
    assert quote.qty == 120
    assert quote.unit_price == 364.0
    assert quote.total == 43680.0
    assert quote.floor_price == 338.0
    assert quote.incoterm == "CIF"
    assert out["inventory"] is not None and out["inventory"].lead_time == "25 days"
    assert out["strategy"] is not None


def test_large_quantity_uses_top_tier_and_extends_lead_time(session_factory):
    node = make_node(
        session_factory,
        spec=InquirySpec(sku="X200", quantity=500, incoterm="CIF", destination="Valencia"),
    )
    out = run(node)
    assert out["quote"].unit_price == 350.0
    assert out["quote"].total == 175000.0
    assert out["inventory"].lead_time == "35 days"


def test_target_price_from_memory_is_passed_to_tool(session_factory):
    memory = MemoryContext(
        facts=[MemoryFact(key="target_price", value="350", confidence=0.95)],
        recent=[],
        pending=[],
        block="target_price=350",
    )
    node = make_node(
        session_factory,
        spec=InquirySpec(sku="X200", quantity=300, incoterm="CIF", destination="Valencia"),
        strategy=ReplyStrategy(
            stance="re_engage",
            mention_history=True,
            price_adjustment="match_target",
            key_points=["price"],
            rationale="目标价达标",
        ),
    )
    out = run(node, memory=memory)

    assert out["quote"].target_matched_price == 350.0
    assert out["strategy"].price_adjustment == "match_target"
    assert out["strategy"].stance == "re_engage"


# ---------------------------------------------------------------- 边界


def test_missing_quantity_returns_no_quote(session_factory):
    node = make_node(session_factory, spec=InquirySpec(product_keyword="pump"))
    out = run(node)
    assert out["quote"] is None
    assert out["strategy"] is None
    assert "缺少有效数量" in out["trace"][0].summary


def test_unknown_sku_returns_no_quote(session_factory):
    node = make_node(session_factory, spec=InquirySpec(sku="NOPE", quantity=10))
    out = run(node)
    assert out["quote"] is None
    assert "没有匹配到产品" in out["trace"][0].summary


def test_react_calc_result_is_reused_only_when_it_matches(session_factory):
    spec = InquirySpec(sku="X200", quantity=120, incoterm="CIF", destination="Valencia")
    fallback = {
        "sku": "X200",
        "qty": 120,
        "tiers": [{"min_qty": 100, "max_qty": 499, "unit_price": 364.0}],
        "applicable": {"unit_price": 364.0, "total": 43680.0},
        "floor_price": 338.0,
        "target_matched_price": None,
        "currency": "USD",
        "freight": 8.5,
        "insurance": 3.5,
        "incoterm": "CIF",
        "destination": "Valencia",
        "valid_until": "2026-11-06",
    }
    quote, _products, _inventory, summary = build_quote(
        spec, None, fallback_calc=fallback
    )
    assert quote is not None
    assert quote.unit_price == 364.0
    assert "ReAct" in summary

    # 数量对不上时不采用模型的算价，重新用工具算
    mismatched = dict(fallback, qty=999, applicable={"unit_price": 1.0, "total": 999.0})
    quote2, *_ = build_quote(spec, None, fallback_calc=mismatched)
    assert quote2 is not None
    assert quote2.unit_price == 364.0
