"""第 7 天集成测试：完整流程 + 审批挂起/恢复 + 议价强制人工。

全部用 fake LLM + 内存库，不依赖外部服务。
"""

from __future__ import annotations

import sqlite3

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.config import settings
from app.graph.build import build_serde, build_single_agent
from app.graph.state import (
    Decision,
    InquirySpec,
    MailInput,
    ReplyStrategy,
    Triage,
)
from tests.fakes import FakeLLM

GOOD_REPLY = (
    "Dear Carlos, our price is USD 350 per unit, total USD 175,000, CIF Valencia. "
    "Lead time is 35 days and the offer is valid for 7 days."
)
BAD_REPLY = "Dear Carlos, our best price is USD 305 per unit."


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


def make_mail(**kwargs) -> MailInput:
    data = dict(
        message_id="<full-500@acme-import.example>",
        subject="Inquiry: X200 500 units CIF Valencia",
        from_email="carlos@acme-import.example",
        from_name="Carlos Mendoza",
        body_text="Please quote 500 units of X200, 380V/50Hz, CIF Valencia.",
    )
    data.update(kwargs)
    return MailInput(**data)


def spec_500() -> InquirySpec:
    return InquirySpec(sku="X200", quantity=500, incoterm="CIF", destination="Valencia")


def build_graph(session_factory, monkeypatch, *, text: str = GOOD_REPLY, triage=None, spec=None, checkpointer=None):
    _pass_compliance(monkeypatch)
    llm = FakeLLM(
        {
            Triage: triage or Triage(complete=True, confidence=0.95),
            InquirySpec: spec or spec_500(),
            ReplyStrategy: ReplyStrategy(
                stance="escalate",
                mention_history=True,
                price_adjustment="volume_tier",
                key_points=["price", "lead_time", "validity"],
                rationale="目标价达标但超授权",
            ),
            Decision: Decision(action="auto_reply", reason="授权内"),
        },
        text=text,
    )
    return build_single_agent(
        checkpointer=checkpointer or InMemorySaver(serde=build_serde()),
        llm=llm,
        session_factory=session_factory,
    )


def initial_state(**kwargs):
    state = {
        "mail": make_mail(),
        "thread_id": "thread:full-500",
        "step": 0,
        "trace": [],
        "errors": [],
        "clarify_count": 0,
    }
    state.update(kwargs)
    return state


def test_over_authorization_hangs_at_approval(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    out = graph.invoke(initial_state(), config={"configurable": {"thread_id": "full-1"}})

    # 500 × 350 = 175,000 > 150,000
    assert out["quote"].total == 175000.0
    assert out["quote"].total > settings.auto_reply_limit
    assert out["decision"].action == "escalate"
    assert "超授权" in out["decision"].reason
    assert "__interrupt__" in out
    nodes = [s.node for s in out["trace"]]
    assert nodes[-1] == "compose"
    assert "dispatch" not in nodes


def test_approve_resumes_and_dispatches(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-2"}}
    graph.invoke(initial_state(), config=config)

    resumed = graph.invoke(
        Command(resume={"action": "approve", "comment": "同意", "approver": "李"}),
        config=config,
    )

    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-3:] == ["approval", "dispatch", "persist"]
    assert resumed["approval"].action == "approve"
    assert resumed["sent"] is False  # DRY_RUN=true
    # checkpoint 恢复后策略对象必须还在（曾因白名单模块路径错误被丢）
    assert resumed["strategy"] is not None
    assert resumed["strategy"].stance == "escalate"


def test_reject_archives_and_writes_memory(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-3"}}
    graph.invoke(initial_state(), config=config)

    resumed = graph.invoke(
        Command(resume={"action": "reject", "comment": "价格太低", "approver": "李"}),
        config=config,
    )

    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-2:] == ["archive", "persist"]
    assert resumed["approval"].action == "reject"


def test_negotiation_round_forces_approval(session_factory, monkeypatch):
    triage = Triage(complete=True, confidence=0.95, is_negotiation=True, client_offered_price=350.0)
    graph = build_graph(session_factory, monkeypatch, triage=triage)
    out = graph.invoke(
        initial_state(
            mail=make_mail(
                message_id="<neg@acme-import.example>",
                in_reply_to="<root@acme-import.example>",
                body_text="USD 364 is above our budget. Competitor offers USD 350 CIF Valencia.",
                is_price_negotiation=True,
                client_offered_price=350.0,
            ),
            is_followup=True,
            round=1,
        ),
        config={"configurable": {"thread_id": "full-4"}},
    )

    assert out["round"] == 2
    assert out["decision"].action == "escalate"
    # 500 台总价 175,000 超授权 → escalate；客户目标价 350 等于报价，不算“要求让价”
    assert "超授权" in out["decision"].reason or "低于" in out["decision"].reason
    assert "__interrupt__" in out


def test_fact_check_failure_blocks_auto_reply(session_factory, monkeypatch):
    # 120 台 = 43,680 在授权内 → 模型会给 auto_reply，但回复被篡改 → 必须转审批
    graph = build_graph(
        session_factory,
        monkeypatch,
        text=BAD_REPLY,
        spec=InquirySpec(sku="X200", quantity=120, incoterm="CIF", destination="Valencia"),
    )
    out = graph.invoke(initial_state(), config={"configurable": {"thread_id": "full-5"}})

    assert out["decision"].action == "auto_reply"
    assert out["fact_check_ok"] is False
    assert "__interrupt__" in out


def test_approval_survives_new_graph_instance(tmp_path, session_factory, monkeypatch):
    db = tmp_path / "cp.db"
    config = {"configurable": {"thread_id": "full-restart"}}

    conn1 = sqlite3.connect(str(db), check_same_thread=False)
    graph1 = build_graph(
        session_factory,
        monkeypatch,
        checkpointer=SqliteSaver(conn1, serde=build_serde()),
    )
    suspended = graph1.invoke(initial_state(), config=config)
    assert "__interrupt__" in suspended
    conn1.close()

    conn2 = sqlite3.connect(str(db), check_same_thread=False)
    graph2 = build_graph(
        session_factory,
        monkeypatch,
        checkpointer=SqliteSaver(conn2, serde=build_serde()),
    )
    resumed = graph2.invoke(
        Command(resume={"action": "approve", "comment": "重启后审批"}),
        config=config,
    )
    conn2.close()

    assert resumed["approval"].action == "approve"
    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-2:] == ["dispatch", "persist"]


# ---------------------------------------------------------------- 审批动作细节


def _make_thread(session_factory) -> tuple[str, str]:
    from app.db.models import Customer, Thread

    with session_factory() as session:
        customer = Customer(email="audit@acme-import.example", name="Audit Co")
        session.add(customer)
        session.flush()
        thread = Thread(
            customer_id=customer.id,
            subject="Inquiry: X200 500 units",
            subject_norm="inquiry x200 500 units",
            status="processing",
        )
        session.add(thread)
        session.commit()
        return customer.id, thread.id


def test_approval_marks_thread_waiting_and_audits(session_factory, monkeypatch):
    from app.db.models import AuditLog, Thread

    customer_id, thread_id = _make_thread(session_factory)
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-audit"}}
    graph.invoke(
        initial_state(thread_id=thread_id, customer_id=customer_id, mail=make_mail()),
        config=config,
    )

    with session_factory() as session:
        thread = session.get(Thread, thread_id)
        assert thread.status == "waiting_approval"

    graph.invoke(
        Command(resume={"action": "approve", "comment": "ok", "approver": "李"}),
        config=config,
    )

    with session_factory() as session:
        actions = [
            row.action for row in session.query(AuditLog).order_by(AuditLog.created_at)
        ]
    assert "approval" in actions
    assert "dispatch" in actions


def test_edited_reply_is_sent_after_fact_check(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-edit"}}
    graph.invoke(initial_state(), config=config)

    edited = (
        "Dear Carlos, for 500 units we confirm USD 350 per unit, total USD 175,000, "
        "CIF Valencia. Lead time 35 days, offer valid 7 days."
    )
    resumed = graph.invoke(
        Command(resume={"action": "approve", "comment": "改了下措辞", "edited_reply": edited}),
        config=config,
    )

    assert resumed["approval"].action == "approve"
    assert resumed["approval"].edited_reply == edited
    assert resumed["reply_final"] == edited
    nodes = [s.node for s in resumed["trace"]]
    assert nodes[-2:] == ["dispatch", "persist"]


def test_tampered_edited_reply_is_not_sent(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-edit-bad"}}
    graph.invoke(initial_state(), config=config)

    resumed = graph.invoke(
        Command(
            resume={
                "action": "approve",
                "comment": "手滑改成 305",
                "edited_reply": "Our price is USD 305 per unit.",
            }
        ),
        config=config,
    )

    # 改错价不发送、也不直接归档：退回重写后再挂起
    assert resumed["approval"].action == "modify"
    assert "事实校验失败" in resumed["approval"].comment
    assert "__interrupt__" in resumed
    nodes = [s.node for s in resumed["trace"]]
    assert "dispatch" not in nodes


def test_empty_reply_never_auto_sends(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch, text="")
    out = graph.invoke(initial_state(), config={"configurable": {"thread_id": "full-empty"}})
    assert out["fact_check_ok"] is False
    assert "__interrupt__" in out


def test_invalid_action_defaults_to_reject(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-invalid"}}
    graph.invoke(initial_state(), config=config)

    resumed = graph.invoke(Command(resume={"action": "hack"}), config=config)
    assert resumed["approval"].action == "reject"
    nodes = [s.node for s in resumed["trace"]]
    assert "dispatch" not in nodes


def test_reassign_keeps_waiting(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-reassign"}}
    graph.invoke(initial_state(), config=config)

    reassigned = graph.invoke(
        Command(resume={"action": "reassign", "comment": "转给主管", "approver": "李"}),
        config=config,
    )
    assert "__interrupt__" in reassigned
    assert reassigned["approval"].action == "reassign"

    approved = graph.invoke(
        Command(resume={"action": "approve", "comment": "主管同意", "approver": "王"}),
        config=config,
    )
    nodes = [s.node for s in approved["trace"]]
    assert nodes[-2:] == ["dispatch", "persist"]


def test_modify_rewrites_and_hangs_again(session_factory, monkeypatch):
    graph = build_graph(session_factory, monkeypatch)
    config = {"configurable": {"thread_id": "full-modify"}}
    graph.invoke(initial_state(), config=config)

    modified = graph.invoke(
        Command(resume={"action": "modify", "comment": "语气再客气一点", "approver": "李"}),
        config=config,
    )
    # 重写后仍然是 escalate 路径 → 再次挂起
    assert "__interrupt__" in modified
    nodes = [s.node for s in modified["trace"]]
    assert nodes[-1] == "compose"
