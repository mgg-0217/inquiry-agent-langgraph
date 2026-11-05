from __future__ import annotations

from app.graph.compose import compose_reply, facts_from_state
from app.graph.state import AgentState, Inventory, MailInput, MemoryContext, Quote, ReplyStrategy
from tests.fakes import ScriptedTextLLM

GOOD_REPLY = (
    "Dear Carlos, our price is USD 350 per unit, total USD 175,000, CIF Valencia. "
    "Lead time is 35 days and the offer is valid for 7 days."
)
BAD_REPLY = "Dear Carlos, our best price is USD 305 per unit, total USD 152,500."


def make_state(**kwargs) -> AgentState:
    state: AgentState = {
        "mail": MailInput(
            message_id="<compose-1@acme-import.example>",
            subject="Inquiry: X200",
            from_email="carlos@acme-import.example",
            from_name="Carlos",
            body_text="Please quote 500 units of X200, CIF Valencia.",
        ),
        "quote": Quote(
            sku="X200",
            qty=500,
            unit_price=350.0,
            floor_price=338.0,
            total=175000.0,
            incoterm="CIF",
            destination="Valencia",
        ),
        "inventory": Inventory(available=True, lead_time="35 days"),
        "strategy": ReplyStrategy(
            stance="escalate",
            mention_history=True,
            price_adjustment="volume_tier",
            key_points=["price", "lead_time", "validity"],
        ),
        "memory": MemoryContext(block="target_price=350", facts=[], recent=[], pending=[]),
        "round": 2,
        "is_followup": True,
    }
    state.update(kwargs)
    return state


def test_facts_from_state_extracts_numbers():
    facts = facts_from_state(make_state())
    assert facts["unit_price"] == 350.0
    assert facts["total"] == 175000.0
    assert facts["lead_time_days"] == 35
    assert facts["valid_days"] > 0


def test_good_reply_passes_fact_check():
    llm = ScriptedTextLLM([GOOD_REPLY])
    reply, result = compose_reply(llm, make_state())
    assert reply == GOOD_REPLY
    assert result.ok is True


def test_bad_reply_is_rewritten_once():
    llm = ScriptedTextLLM([BAD_REPLY, GOOD_REPLY])
    reply, result = compose_reply(llm, make_state())
    assert reply == GOOD_REPLY
    assert result.ok is True
    assert llm.calls == 2


def test_rewrite_still_bad_returns_failed_flag():
    llm = ScriptedTextLLM([BAD_REPLY, BAD_REPLY])
    reply, result = compose_reply(llm, make_state())
    assert reply == BAD_REPLY
    assert result.ok is False
    assert result.violations
    assert llm.calls == 2
