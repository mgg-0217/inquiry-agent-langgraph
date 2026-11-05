"""工作台 KPI。"""

from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.db.models import Message, Thread
from app.db.session import get_db

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _local_day_start_utc():
    now = datetime.now().astimezone()
    start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("")
def get_metrics(db: Session = Depends(get_db)):
    day_start = _local_day_start_utc()
    today_inbound = db.scalar(
        select(func.count(Message.id)).where(
            Message.direction == "inbound", Message.received_at >= day_start
        )
    ) or 0
    today_outbound = db.scalar(
        select(func.count(Message.id)).where(
            Message.direction == "outbound", Message.received_at >= day_start
        )
    ) or 0
    waiting_approval = db.scalar(
        select(func.count(Thread.id)).where(Thread.status == "waiting_approval")
    ) or 0
    total_threads = db.scalar(select(func.count(Thread.id))) or 0
    archived = db.scalar(
        select(func.count(Thread.id)).where(Thread.status.like("archived%"))
    ) or 0

    return ok(
        {
            "today_inbound": today_inbound,
            "today_outbound": today_outbound,
            "waiting_approval": waiting_approval,
            "total_threads": total_threads,
            "archived": archived,
            # 首响需要 outbound 与 inbound 配对，第 7 天起才写 outbound
            "avg_first_response_seconds": None,
        }
    )
