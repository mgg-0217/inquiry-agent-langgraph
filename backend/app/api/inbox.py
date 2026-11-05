"""询盘工作台接口：列表、线程详情、手动同步。"""

from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.db.models import Customer, Message, Thread
from app.db.session import get_db
from app.graph.process import process_thread
from app.mail.factory import build_provider
from app.mail.ingest import sync_inbox

router = APIRouter(prefix="/api", tags=["inbox"])

ARCHIVED_PREFIX = "archived"


def _iso(dt: datetime | None) -> str | None:
    """库里统一存 UTC naive，输出时补 Z，前端 new Date() 才能正确换算本地时间。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds") + "Z"


def _local_day_start_utc() -> datetime:
    """本地时区当天 00:00 对应的 UTC（naive，与库内时间一致）。"""
    now = datetime.now().astimezone()
    start_local = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)


def _threads_to_items(session: Session, threads: list[Thread]) -> list[dict]:
    if not threads:
        return []
    ids = [t.id for t in threads]
    counts = dict(
        session.execute(
            select(Message.thread_id, func.count(Message.id))
            .where(Message.thread_id.in_(ids))
            .group_by(Message.thread_id)
        ).all()
    )
    last: dict[str, Message] = {}
    for msg in session.scalars(
        select(Message).where(Message.thread_id.in_(ids)).order_by(Message.received_at.desc())
    ):
        last.setdefault(msg.thread_id, msg)

    items: list[dict] = []
    for t in threads:
        customer = session.get(Customer, t.customer_id) if t.customer_id else None
        m = last.get(t.id)
        items.append(
            {
                "thread_id": t.id,
                "subject": t.subject,
                "status": t.status,
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
                "message_count": counts.get(t.id, 0),
                "last_message_at": _iso(t.last_message_at),
                "last_from": m.from_email if m else None,
                "last_snippet": (m.body_text or "").strip()[:120] if m else "",
                "created_at": _iso(t.created_at),
            }
        )
    return items


def _kpis(session: Session) -> dict:
    today_inbound = session.scalar(
        select(func.count(Message.id)).where(
            Message.direction == "inbound", Message.received_at >= _local_day_start_utc()
        )
    )
    active_threads = session.scalar(
        select(func.count(Thread.id)).where(~Thread.status.startswith(ARCHIVED_PREFIX))
    )
    waiting_approval = session.scalar(
        select(func.count(Thread.id)).where(Thread.status == "waiting_approval")
    )
    return {
        "today_inbound": today_inbound or 0,
        "active_threads": active_threads or 0,
        "waiting_approval": waiting_approval or 0,
        # 平均首响需要"收到 → 发出"配对，第 1 天还没有外发邮件，先给 null
        "avg_first_response_seconds": None,
    }


@router.get("/inbox")
def list_inbox(
    status: str | None = Query(default=None, description="逗号分隔的状态过滤"),
    q: str | None = Query(default=None, description="搜索主题 / 客户名 / 邮箱"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Thread)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Thread.status.in_(statuses))
    if q:
        like = f"%{q.strip()}%"
        stmt = (
            stmt.outerjoin(Customer, Thread.customer_id == Customer.id)
            .where(
                or_(
                    Thread.subject.ilike(like),
                    Customer.name.ilike(like),
                    Customer.email.ilike(like),
                )
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    threads = list(
        db.scalars(
            stmt.order_by(Thread.last_message_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return ok(
        {
            "items": _threads_to_items(db, threads),
            "total": total,
            "page": page,
            "page_size": page_size,
            "kpis": _kpis(db),
        }
    )


@router.get("/threads/{thread_id}")
def thread_detail(thread_id: str, db: Session = Depends(get_db)):
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread 不存在")
    customer = db.get(Customer, thread.customer_id) if thread.customer_id else None
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.received_at.asc())
        ).all()
    )
    return ok(
        {
            "thread": {
                "id": thread.id,
                "subject": thread.subject,
                "status": thread.status,
                "created_at": _iso(thread.created_at),
                "last_message_at": _iso(thread.last_message_at),
            },
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
            "messages": [
                {
                    "id": m.id,
                    "message_id": m.message_id,
                    "direction": m.direction,
                    "subject": m.subject,
                    "from_email": m.from_email,
                    "from_name": m.from_name,
                    "to_emails": m.to_emails,
                    "cc_emails": m.cc_emails,
                    "body_text": m.body_text,
                    "body_html": m.body_html,
                    "attachments": m.attachments,
                    "in_reply_to": m.in_reply_to,
                    "references": m.references,
                    "received_at": _iso(m.received_at),
                }
                for m in messages
            ],
        }
    )


@router.post("/inbox/sync")
def sync_now(db: Session = Depends(get_db)):
    """手动触发一次拉信（前端"立即同步"按钮 / 调试用）。"""
    report = sync_inbox(db, build_provider())
    db.commit()
    results = []
    for thread_id in report.touched_thread_ids:
        try:
            results.append(process_thread(thread_id))
        except Exception as exc:  # noqa: BLE001
            results.append({"thread_id": thread_id, "ok": False, "error": str(exc)})
    return ok(
        {
            "fetched": report.fetched,
            "created": report.created,
            "duplicated": report.duplicated,
            "errors": report.errors,
            "processed": [
                {"thread_id": r.thread_id, "pending": r.pending}
                for r in results
                if hasattr(r, "thread_id")
            ],
        }
    )
