"""模拟投递 API（开发用）：把内置场景注入图，方便前端演示。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import make_msgid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.db.models import Customer, Message, Thread
from app.db.session import get_db
from app.graph.runtime import get_graph
from app.graph.state import MailInput
from app.mail.base import ParsedMail
from app.mail.ingest import ingest_parsed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


SCENARIOS: dict[str, dict] = {
    "A": {
        "subject": "Inquiry: X200 centrifugal pump, 500 units, CIF Valencia",
        "from_email": "carlos@acme-import.example",
        "from_name": "Carlos Mendoza",
        "body": (
            "Dear Sales Team,\n\n"
            "We are Inversiones Valencianas S.L. from Valencia, Spain.\n"
            "Please quote 500 units of X200 centrifugal pump, 380V/50Hz, CIF Valencia.\n"
            "Our target price is USD 350 per unit. Please confirm lead time.\n"
        ),
    },
    "B": {
        "subject": "Hot deal! Click now",
        "from_email": "promo@spam-xyz.example",
        "from_name": "Promo",
        "body": "Check these offers: " + " ".join(
            f"https://spam.example/{i}" for i in range(15)
        ),
    },
    "C": {
        "subject": "price?",
        "from_email": "buyer@newco.example",
        "from_name": "New Buyer",
        "body": "Hi, send me your best price for water pumps.",
    },
    "D": {
        # 用一个真实 SDN 实体名，才能命中真实名单；邮箱独立，避免被 seed 的虚构客户拦截
        "subject": "New inquiry from trading desk",
        "from_email": "desk@bncuba-example.test",
        "from_name": "BANCO NACIONAL DE CUBA",
        "body": (
            "Dear Sales, we are BANCO NACIONAL DE CUBA trading desk. "
            "Please quote 200 units of X200, CIF Valencia."
        ),
    },
}


class InboundRequest(BaseModel):
    scenario: str = "A"
    subject: str | None = None
    body: str | None = None
    from_email: str | None = None
    from_name: str | None = None


class ReplyRequest(BaseModel):
    thread_id: str
    body: str
    from_email: str | None = None
    from_name: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _trace_payload(out: dict) -> list:
    return [step.model_dump(mode="json") for step in out.get("trace", [])]


def _summary(out: dict, thread: Thread | None) -> dict:
    return {
        "thread_id": thread.id if thread else out.get("thread_id"),
        "status": thread.status if thread else None,
        "pending": bool(out.get("__interrupt__")),
        "customer_id": out.get("customer_id"),
        "triage": out["triage"].model_dump(mode="json") if out.get("triage") else None,
        "resolved": (
            out["resolved"].model_dump(mode="json") if out.get("resolved") else None
        ),
        "quote": out["quote"].model_dump(mode="json") if out.get("quote") else None,
        "strategy": (
            out["strategy"].model_dump(mode="json") if out.get("strategy") else None
        ),
        "verdict": out["verdict"].model_dump(mode="json") if out.get("verdict") else None,
        "decision": (
            out["decision"].model_dump(mode="json") if out.get("decision") else None
        ),
        "reply_draft": out.get("reply_draft"),
        "fact_check_ok": out.get("fact_check_ok"),
        "memory_block": (
            out["memory"].block if out.get("memory") is not None else ""
        ),
        "trace": _trace_payload(out),
    }


@router.post("/inbound")
def simulate_inbound(payload: InboundRequest, db: Session = Depends(get_db)):
    scenario = SCENARIOS.get((payload.scenario or "A").upper())
    if scenario is None:
        raise HTTPException(
            status_code=422, detail=f"未知场景 {payload.scenario}，可选 {sorted(SCENARIOS)}"
        )

    parsed = ParsedMail(
        message_id=make_msgid(domain="demo.example"),
        # 加短标记：避免同一客户同主题的模拟单被线程归并到旧 thread、复用旧 checkpoint
        subject=(payload.subject or scenario["subject"])
        + f" [#{make_msgid(domain='demo.example')[1:7]}]",
        from_email=(payload.from_email or scenario["from_email"]).lower(),
        from_name=payload.from_name or scenario["from_name"],
        to_emails=["sales@example.com"],
        body_text=payload.body or scenario["body"],
        received_at=_now(),
    )

    ingested = ingest_parsed(db, parsed)
    db.commit()

    graph = get_graph()
    out = graph.invoke(
        {
            "mail": MailInput.from_parsed(parsed),
            "thread_id": ingested.thread_id,
            "customer_id": ingested.customer_id,
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config={"configurable": {"thread_id": ingested.thread_id}},
    )
    thread = db.get(Thread, ingested.thread_id)
    return ok(_summary(out, thread))


@router.post("/reply")
def simulate_reply(payload: ReplyRequest, db: Session = Depends(get_db)):
    """模拟客户回信：归并到同一 thread，用同一 thread_id 重新 invoke（不是 resume）。"""
    thread = db.get(Thread, payload.thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")

    last = db.scalar(
        select(Message)
        .where(Message.thread_id == thread.id)
        .order_by(Message.received_at.desc())
    )
    customer = db.get(Customer, thread.customer_id) if thread.customer_id else None
    from_email = (payload.from_email or (customer.email if customer else None) or "").lower()
    if not from_email:
        raise HTTPException(status_code=422, detail="无法确定客户邮箱")

    parsed = ParsedMail(
        message_id=make_msgid(domain="demo.example"),
        subject=f"Re: {thread.subject}",
        from_email=from_email,
        from_name=payload.from_name or (customer.name if customer else ""),
        to_emails=["sales@example.com"],
        body_text=payload.body,
        received_at=_now(),
        in_reply_to=last.message_id if last else None,
        references=[last.message_id] if last else [],
    )
    ingested = ingest_parsed(db, parsed)
    db.commit()

    inbound_count = (
        db.scalar(
            select(func.count(Message.id)).where(
                Message.thread_id == thread.id, Message.direction == "inbound"
            )
        )
        or 1
    )
    graph = get_graph()
    out = graph.invoke(
        {
            "mail": MailInput.from_parsed(parsed),
            "thread_id": thread.id,
            "customer_id": thread.customer_id,
            "is_followup": True,
            "round": max(1, inbound_count - 1),
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config={"configurable": {"thread_id": thread.id}},
    )
    return ok(_summary(out, thread))
