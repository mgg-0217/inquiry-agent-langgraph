"""把一封已入库的客户邮件送进图处理。

轮询收到新邮件后调用，让 Agent 自动走 triage → resolve → recall → draft_plan …
（原先只有 `/api/simulate/*` 会触发，真实 IMAP 收信不会）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select

from app.db.models import Customer, Message, Thread
from app.db.session import SessionLocal
from app.graph.runtime import get_graph
from app.graph.state import MailInput

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    thread_id: str
    ok: bool
    pending: bool = False
    error: str | None = None


def mail_input_from_message(msg: Message) -> MailInput:
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


def process_thread(thread_id: str) -> ProcessResult:
    """对 thread 的最新客户来信跑一次图；已归档的不重复处理。"""
    with SessionLocal() as session:
        thread = session.get(Thread, thread_id)
        if thread is None:
            return ProcessResult(thread_id=thread_id, ok=False, error="thread 不存在")
        if thread.status.startswith("archived"):
            return ProcessResult(thread_id=thread_id, ok=False, error="已归档")

        last = session.scalar(
            select(Message)
            .where(Message.thread_id == thread_id, Message.direction == "inbound")
            .order_by(Message.received_at.desc())
        )
        if last is None:
            return ProcessResult(thread_id=thread_id, ok=False, error="没有客户来信")

        # 立刻标「处理中」，避免前端看起来像没反应（LLM 全流程要 30~60s）
        if thread.status in ("received", "processing"):
            thread.status = "processing"
            session.commit()

        inbound_count = (
            session.scalar(
                select(func.count(Message.id)).where(
                    Message.thread_id == thread_id, Message.direction == "inbound"
                )
            )
            or 1
        )
        is_followup = inbound_count > 1
        round_no = max(1, inbound_count - 1) if is_followup else 1

        mail = mail_input_from_message(last)
        customer_id = thread.customer_id
        customer = session.get(Customer, customer_id) if customer_id else None
        customer_id = customer.id if customer else None

    graph = get_graph()
    # 重跑前清掉旧 checkpoint：否则 invoke 会复用上一次已经结束的状态，直接什么都不跑
    try:
        checkpointer = getattr(graph, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(thread_id)
    except Exception:  # noqa: BLE001
        logger.warning("清理旧 checkpoint 失败 thread_id=%s", thread_id, exc_info=True)

    try:
        out = graph.invoke(
            {
                "mail": mail,
                "thread_id": thread_id,
                "customer_id": customer_id,
                "is_followup": is_followup,
                "round": round_no,
                "step": 0,
                "trace": [],
                "errors": [],
                "clarify_count": 0,
            },
            config={"configurable": {"thread_id": thread_id}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("线程处理失败 thread_id=%s", thread_id)
        return ProcessResult(thread_id=thread_id, ok=False, error=str(exc))

    pending = bool(out.get("__interrupt__"))
    logger.info(
        "线程处理完成 thread_id=%s pending=%s nodes=%s",
        thread_id,
        pending,
        len(out.get("trace", [])),
    )
    return ProcessResult(thread_id=thread_id, ok=True, pending=pending)
