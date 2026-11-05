"""线程级 API：轨迹、审批恢复、捞回、改绑、确认实体解析。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.db.models import AuditLog, Customer, Message, Thread
from app.db.session import get_db
from app.graph.runtime import get_graph
from app.graph.state import MailInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["threads"])


class ResumeRequest(BaseModel):
    action: Literal["approve", "modify", "reject", "reassign"] = Field(
        description="审批动作"
    )
    comment: str = ""
    edited_reply: str | None = None
    approver: str = ""


class ThreadPatch(BaseModel):
    customer_id: str | None = None


class ConfirmCustomer(BaseModel):
    customer_id: str
    is_correct: bool = True


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _mail_input_from_message(msg: Message) -> MailInput:
    return MailInput(
        message_id=msg.message_id,
        subject=msg.subject,
        from_email=msg.from_email,
        from_name=msg.from_name,
        to_emails=list(msg.to_emails or []),
        cc_emails=list(msg.cc_emails or []),
        body_text=msg.body_text,
        body_html=msg.body_html,
        attachments=list(msg.attachments or []),
        received_at=msg.received_at,
        in_reply_to=msg.in_reply_to,
        references=list(msg.references or []),
    )


def _last_inbound(db: Session, thread_id: str) -> Message | None:
    return db.scalar(
        select(Message)
        .where(Message.thread_id == thread_id, Message.direction == "inbound")
        .order_by(Message.received_at.desc())
    )


def _step_payload(step) -> dict:
    return step.model_dump(mode="json") if hasattr(step, "model_dump") else step


@router.get("/{thread_id}/trace")
def get_trace(thread_id: str, db: Session = Depends(get_db)):
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")

    graph = get_graph()
    snapshot = graph.get_state(_config(thread_id))
    values = snapshot.values or {}
    customer = db.get(Customer, thread.customer_id) if thread.customer_id else None
    return ok(
        {
            "thread_id": thread_id,
            "status": thread.status,
            "subject": thread.subject,
            "pending": list(snapshot.next or []),
            "steps": [_step_payload(step) for step in values.get("trace", [])],
            "memory_block": (
                values["memory"].block if values.get("memory") is not None else ""
            ),
            "decision": (
                values["decision"].model_dump(mode="json")
                if values.get("decision") is not None
                else None
            ),
            "approval": (
                values["approval"].model_dump(mode="json")
                if values.get("approval") is not None
                else None
            ),
            "quote": (
                values["quote"].model_dump(mode="json")
                if values.get("quote") is not None
                else None
            ),
            "strategy": (
                values["strategy"].model_dump(mode="json")
                if values.get("strategy") is not None
                else None
            ),
            "verdict": (
                values["verdict"].model_dump(mode="json")
                if values.get("verdict") is not None
                else None
            ),
            "triage": (
                values["triage"].model_dump(mode="json")
                if values.get("triage") is not None
                else None
            ),
            "reply_draft": values.get("reply_draft"),
            "fact_check_ok": values.get("fact_check_ok"),
            "customer": (
                {
                    "id": customer.id,
                    "name": customer.name,
                    "email": customer.email,
                    "country": customer.country,
                }
                if customer
                else None
            ),
        }
    )


@router.post("/{thread_id}/close")
def close_thread(thread_id: str, db: Session = Depends(get_db)):
    """人工关闭线程（无意义/骚扰/不再跟进）。"""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    if thread.status.startswith("archived"):
        raise HTTPException(status_code=400, detail="已经归档了")
    old = thread.status
    thread.status = "archived_rejected"
    db.add(
        AuditLog(
            thread_id=thread_id,
            actor="manual",
            action="close",
            payload={"from": old},
        )
    )
    db.commit()
    return ok({"thread_id": thread_id, "status": thread.status})


@router.post("/{thread_id}/process")
def process_thread_api(thread_id: str, db: Session = Depends(get_db)):
    """手动让 Agent 处理一封「待处理」的询盘（历史邮件 / 重跑用）。"""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    if thread.status not in ("received", "processing", "waiting_clarify"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态是 {thread.status}，只有待处理/处理中/待补充可以触发",
        )

    from app.graph.process import process_thread

    result = process_thread(thread_id)
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.error or "处理失败")
    db.refresh(thread)
    return ok(
        {
            "thread_id": thread_id,
            "status": thread.status,
            "pending": result.pending,
        }
    )


@router.post("/{thread_id}/resume")
def resume_thread(
    thread_id: str, payload: ResumeRequest, db: Session = Depends(get_db)
):
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")

    graph = get_graph()
    config = _config(thread_id)
    snapshot = graph.get_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=400, detail="该线程当前没有挂起的审批")

    result = graph.invoke(
        Command(resume=payload.model_dump()),
        config=config,
    )
    approval = result.get("approval")
    return ok(
        {
            "thread_id": thread_id,
            "action": approval.action if approval else None,
            "comment": approval.comment if approval else "",
            "sent": bool(result.get("sent")),
            "pending": bool(result.get("__interrupt__")),
            "reply_final": result.get("reply_final"),
            "decision": (
                result["decision"].model_dump(mode="json")
                if result.get("decision") is not None
                else None
            ),
        }
    )


@router.post("/{thread_id}/restore")
def restore_thread(thread_id: str, db: Session = Depends(get_db)):
    """把误判为垃圾的 thread 恢复为询盘，并重新跑一遍（跳过 spam 判定）。"""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    if thread.status not in ("archived_spam", "archived_compliance", "archived_rejected"):
        raise HTTPException(status_code=400, detail="只有已归档的线程可以捞回")

    thread.status = "received"
    db.commit()

    msg = _last_inbound(db, thread_id)
    if msg is None:
        raise HTTPException(status_code=400, detail="线程里没有客户来信，无法重跑")

    graph = get_graph()
    config = _config(thread_id)
    mail = _mail_input_from_message(msg)
    # 清掉旧的 triage 结果：手动捞回跳过垃圾判定
    result = graph.invoke(
        {
            "mail": mail,
            "thread_id": thread_id,
            "customer_id": thread.customer_id,
            "manual_restore": True,
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config=config,
    )
    return ok(
        {
            "thread_id": thread_id,
            "status": db.get(Thread, thread_id).status,
            "pending": bool(result.get("__interrupt__")),
        }
    )


@router.patch("/{thread_id}")
def rebind_customer(
    thread_id: str, payload: ThreadPatch, db: Session = Depends(get_db)
):
    """人工改绑客户（PRD F2 纠错流程）。"""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    if payload.customer_id is not None:
        customer = db.get(Customer, payload.customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户不存在")
    thread.customer_id = payload.customer_id
    db.commit()
    return ok({"thread_id": thread_id, "customer_id": thread.customer_id})


@router.post("/{thread_id}/confirm-customer")
def confirm_customer(
    thread_id: str, payload: ConfirmCustomer, db: Session = Depends(get_db)
):
    """确认/否认实体解析结果（PRD F2）。"""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    if payload.is_correct:
        thread.customer_id = payload.customer_id
        db.commit()
        return ok({"confirmed": True, "customer_id": thread.customer_id})

    # 否认：解绑，等人工改绑或下次解析新建
    thread.customer_id = None
    db.commit()
    return ok({"confirmed": False, "customer_id": None})
