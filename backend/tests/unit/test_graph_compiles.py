"""图测试：结构、happy path、分支、挂起恢复。

第 4 天起 triage / resolve / recall / persist 都是真实实现，
因此测试注入 `FakeLLM` + 内存 `session_factory`，完全脱库脱 API。
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph.build import BUSINESS_NODES, build_serde, build_single_agent
from app.graph.edges import after_approval, after_compliance, after_decide, after_triage
from app.graph.state import (
    AgentState,
    Approval,
    Decision,
    InquirySpec,
    MailInput,
    ReplyStrategy,
    Triage,
    Verdict,
)
from tests.fakes import FakeLLM


def make_mail(**kwargs: Any) -> MailInput:
    data = dict(
        message_id="<fixture-001@acme-import.example>",
        subject="Inquiry: X200 120 units",
        from_email="carlos@acme-import.example",
        from_name="Carlos",
        body_text="Please quote 120 units of X200, CIF Valencia.",
    )
    data.update(kwargs)
    return MailInput(**data)


def make_graph(session_factory, triage: Triage | None = None):
    llm = FakeLLM(
        {
            Triage: triage or Triage(complete=True, confidence=0.95),
            InquirySpec: InquirySpec(
                sku="X200", quantity=120, incoterm="CIF", destination="Valencia"
            ),
            ReplyStrategy: ReplyStrategy(
                stance="standard",
                mention_history=False,
                price_adjustment="none",
                key_points=["price", "lead_time", "validity"],
                rationale="常规报价",
            ),
        }
    )
    return build_single_agent(
        checkpointer=InMemorySaver(serde=build_serde()),
        llm=llm,
        session_factory=session_factory,
    )


def edge_targets(graph: Any, source: str) -> list[str]:
    out: list[str] = []
    for e in graph.edges:
        s = e[0] if isinstance(e, tuple) else e.source
        t = e[1] if isinstance(e, tuple) else e.target
        if s == source:
            out.append(t)
    return out


def base_state(mail: MailInput | None = None, **overrides) -> AgentState:
    state: AgentState = {
        "mail": mail or make_mail(),
        "thread_id": "thread:fixture-001",
        "step": 0,
        "trace": [],
        "errors": [],
        "clarify_count": 0,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------- 结构


def test_all_13_business_nodes_registered(session_factory):
    graph = make_graph(session_factory)
    names = set(graph.get_graph().nodes.keys())
    for node in BUSINESS_NODES:
        assert node in names, f"缺少节点 {node}"
    assert len(names - {"__start__", "__end__"}) == 13


def test_clarify_goes_to_end_not_receive(session_factory):
    graph = make_graph(session_factory)
    targets = edge_targets(graph.get_graph(), "clarify")
    assert targets == ["__end__"], f"clarify 出边错误: {targets}"
    assert "receive" not in targets


def test_graph_has_single_entry(session_factory):
    graph = make_graph(session_factory)
    assert edge_targets(graph.get_graph(), "__start__") == ["receive"]


def test_default_checkpointer_is_cached():
    """默认 sqlite checkpointer 必须进程内复用，否则每次建图泄漏一个连接。"""
    from app.graph.build import close_default_checkpointer, get_default_checkpointer

    try:
        assert get_default_checkpointer() is get_default_checkpointer()
    finally:
        close_default_checkpointer()


# ---------------------------------------------------------------- happy path


def _pass_compliance(monkeypatch):
    import app.graph.nodes as nodes_mod

    monkeypatch.setattr(
        nodes_mod,
        "screen_compliance",
        lambda *a, **k: {
            "ok": True,
            "data": {"list_loaded": True, "score": 0.0, "hits": [], "evidence": []},
        },
    )


def test_happy_path_runs_to_persist(session_factory, monkeypatch):
    _pass_compliance(monkeypatch)
    graph = make_graph(session_factory)
    out = graph.invoke(base_state(), config={"configurable": {"thread_id": "happy-1"}})

    nodes = [s.node for s in out["trace"]]
    assert nodes == [
        "receive",
        "triage",
        "resolve",
        "recall",
        "draft_plan",
        "compliance",
        "decide",
        "compose",
        "dispatch",
        "persist",
    ]
    assert out["step"] == 10
    assert out["round"] == 1
    assert out["is_followup"] is False
    assert out["quote"] is not None and out["quote"].total == 43680.0
    assert out["resolved"] is not None and out["resolved"].method == "new"
    assert out["memory"] is not None and out["memory"].facts == []


def test_missing_sanctions_list_escalates_to_approval(session_factory):
    """名单未加载时宁可误杀：合规转人工，图挂起在 approval。"""
    graph = make_graph(session_factory)
    out = graph.invoke(base_state(), config={"configurable": {"thread_id": "no-list"}})

    assert "__interrupt__" in out
    assert out["decision"].action == "escalate"
    assert "合规需人工复核" in out["decision"].reason


def test_followup_mail_increments_round(session_factory):
    graph = make_graph(session_factory)
    initial = base_state(
        mail=make_mail(
            message_id="<fixture-002@acme-import.example>",
            in_reply_to="<fixture-001@x>",
        ),
        is_followup=True,
        round=1,
    )
    out = graph.invoke(initial, config={"configurable": {"thread_id": "followup-1"}})
    assert out["round"] == 2
    assert out["is_followup"] is True


def test_incomplete_inquiry_stops_at_clarify(session_factory):
    triage = Triage(
        complete=False,
        missing=["数量"],
        clarify_questions=["How many units do you need?"],
        confidence=0.9,
    )
    graph = make_graph(session_factory, triage=triage)
    out = graph.invoke(
        base_state(mail=make_mail(body_text="Please send your best price for water pumps.")),
        config={"configurable": {"thread_id": "clarify-1"}},
    )

    nodes = [s.node for s in out["trace"]]
    assert nodes == ["receive", "triage", "clarify"]
    assert out["clarify_count"] == 1
    assert out["reply_draft"]


# ---------------------------------------------------------------- 分诊分支


def test_spam_high_confidence_archives():
    state: AgentState = {"triage": Triage(is_spam=True, confidence=0.95, complete=True)}
    assert after_triage(state) == "archive"


def test_spam_low_confidence_does_not_archive():
    state: AgentState = {"triage": Triage(is_spam=True, confidence=0.5, complete=True)}
    assert after_triage(state) == "resolve"


def test_incomplete_clarifies_and_stops_after_two_rounds():
    triage = Triage(complete=False, missing=["quantity"], clarify_questions=["How many?"])
    assert after_triage({"triage": triage, "clarify_count": 0}) == "clarify"
    assert after_triage({"triage": triage, "clarify_count": 1}) == "clarify"
    assert after_triage({"triage": triage, "clarify_count": 2}) == "resolve"


# ---------------------------------------------------------------- 合规分支


def test_compliance_reject_archives():
    assert after_compliance({"verdict": Verdict(result="reject", score=0.99)}) == "archive"


def test_compliance_need_review_goes_to_decide():
    assert after_compliance({"verdict": Verdict(result="need_review", score=0.8)}) == "decide"


# ---------------------------------------------------------------- 决策分支


def test_decide_reject_archives():
    assert after_decide({"decision": Decision(action="reject")}) == "archive"


def test_decide_escalate_goes_to_compose():
    assert after_decide({"decision": Decision(action="escalate")}) == "compose"


def test_decide_auto_reply_goes_to_compose_first():
    """自动回复也必须先生成并过 fact_check，不能直接发空邮件。"""
    assert after_decide({"decision": Decision(action="auto_reply")}) == "compose"


def test_price_negotiation_forces_compose_even_if_model_says_auto():
    state: AgentState = {
        "is_followup": True,
        "round": 2,
        "mail": make_mail(is_price_negotiation=True, client_offered_price=350.0),
        "decision": Decision(action="auto_reply"),
    }
    assert after_decide(state) == "compose"


def test_round_one_negotiation_is_not_forced_to_approval():
    """首轮还不算议价轮：策略上仍走自动流程（具体由 fact_check/授权再决定）。"""
    state: AgentState = {
        "is_followup": False,
        "round": 1,
        "mail": make_mail(is_price_negotiation=True),
        "decision": Decision(action="auto_reply"),
    }
    assert after_decide(state) == "compose"


# ---------------------------------------------------------------- 审批分支


def test_approval_actions():
    assert after_approval({"approval": Approval(action="approve")}) == "dispatch"
    assert after_approval({"approval": Approval(action="modify")}) == "compose"
    assert after_approval({"approval": Approval(action="reject")}) == "archive"


# ---------------------------------------------------------------- 挂起与恢复


def _negotiation_initial() -> AgentState:
    return {
        "mail": make_mail(
            message_id="<neg-1@acme-import.example>",
            in_reply_to="<root@acme-import.example>",
            body_text="USD 364 is above our budget. Competitor offers USD 350.",
            is_price_negotiation=True,
            client_offered_price=350.0,
        ),
        "thread_id": "thread:neg-1",
        "step": 0,
        "trace": [],
        "errors": [],
        "clarify_count": 0,
        "is_followup": True,
        "round": 1,
    }


def test_price_negotiation_hangs_at_approval_then_resumes(session_factory):
    graph = make_graph(
        session_factory,
        triage=Triage(complete=True, is_negotiation=True, client_offered_price=350.0),
    )
    config = {"configurable": {"thread_id": "neg-inmemory"}}

    suspended = graph.invoke(_negotiation_initial(), config=config)
    assert "__interrupt__" in suspended, "议价轮必须挂起在 approval"

    resumed = graph.invoke(
        Command(resume={"action": "approve", "comment": "同意", "approver": "李"}),
        config=config,
    )
    assert resumed["approval"].action == "approve"
    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-3:] == ["approval", "dispatch", "persist"]


def test_approval_survives_new_graph_instance(tmp_path, session_factory):
    """模拟进程重启：换一个图实例 + 新的 sqlite 连接，仍能从挂起点继续。"""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    db = tmp_path / "checkpoints.db"
    config = {"configurable": {"thread_id": "neg-restart"}}
    triage = Triage(complete=True, is_negotiation=True, client_offered_price=350.0)

    conn1 = sqlite3.connect(str(db), check_same_thread=False)
    graph1 = build_single_agent(
        checkpointer=SqliteSaver(conn1, serde=build_serde()),
        llm=FakeLLM({Triage: triage}),
        session_factory=session_factory,
    )
    suspended = graph1.invoke(_negotiation_initial(), config=config)
    assert "__interrupt__" in suspended
    conn1.close()

    conn2 = sqlite3.connect(str(db), check_same_thread=False)
    graph2 = build_single_agent(
        checkpointer=SqliteSaver(conn2, serde=build_serde()),
        llm=FakeLLM({Triage: triage}),
        session_factory=session_factory,
    )
    resumed = graph2.invoke(
        Command(resume={"action": "approve", "comment": "重启后审批"}),
        config=config,
    )
    conn2.close()

    assert resumed["approval"].action == "approve"
    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-2:] == ["dispatch", "persist"]
