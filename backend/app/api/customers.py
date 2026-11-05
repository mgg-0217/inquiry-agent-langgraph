"""客户级 API：列表、详情、记忆、人工纠正事实。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.db.models import Customer, CustomerFact, Interaction, Thread
from app.db.session import get_db
from app.memory.recall import recall_memory

router = APIRouter(prefix="/api/customers", tags=["customers"])


class FactCorrection(BaseModel):
    action: str = Field(default="invalidate", description="invalidate | update")
    value: str | None = None


def _fact_payload(row: CustomerFact) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "value": row.value,
        "confidence": row.confidence,
        "evidence": row.evidence,
        "source_msg": row.source_msg,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "superseded_by": row.superseded_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_customers(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Customer)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.email.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Customer.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )

    thread_counts = dict(
        db.execute(
            select(Thread.customer_id, func.count(Thread.id))
            .where(Thread.customer_id.in_([r.id for r in rows]))
            .group_by(Thread.customer_id)
        ).all()
    ) if rows else {}

    return ok(
        {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "email": row.email,
                    "country": row.country,
                    "is_new": row.is_new,
                    "thread_count": thread_counts.get(row.id, 0),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{customer_id}")
def customer_detail(customer_id: str, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在")

    facts = list(
        db.scalars(
            select(CustomerFact)
            .where(CustomerFact.customer_id == customer_id)
            .order_by(CustomerFact.created_at.desc())
        ).all()
    )
    interactions = list(
        db.scalars(
            select(Interaction)
            .where(Interaction.customer_id == customer_id)
            .order_by(Interaction.created_at.desc())
            .limit(20)
        ).all()
    )
    threads = list(
        db.scalars(
            select(Thread)
            .where(Thread.customer_id == customer_id)
            .order_by(Thread.last_message_at.desc())
        ).all()
    )
    return ok(
        {
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "country": customer.country,
                "domain": customer.domain,
                "is_new": customer.is_new,
                "created_at": customer.created_at.isoformat()
                if customer.created_at
                else None,
            },
            "facts": [_fact_payload(f) for f in facts],
            "interactions": [
                {
                    "id": i.id,
                    "summary": i.summary,
                    "outcome": i.outcome,
                    "lost_reason": i.lost_reason,
                    "evidence": i.evidence,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in interactions
            ],
            "threads": [
                {
                    "id": t.id,
                    "subject": t.subject,
                    "status": t.status,
                    "last_message_at": t.last_message_at.isoformat()
                    if t.last_message_at
                    else None,
                }
                for t in threads
            ],
        }
    )


@router.get("/{customer_id}/memory")
def customer_memory(customer_id: str, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    memory = recall_memory(db, customer_id)
    return ok(
        {
            "customer": {"id": customer.id, "name": customer.name, "email": customer.email},
            "facts": [f.model_dump(mode="json") for f in memory.facts],
            "recent": [i.model_dump(mode="json") for i in memory.recent],
            "block": memory.block,
        }
    )


@router.patch("/{customer_id}/facts/{fact_id}")
def correct_fact(
    customer_id: str,
    fact_id: str,
    payload: FactCorrection,
    db: Session = Depends(get_db),
):
    """人工纠正记忆事实（PRD F3：可标记失效/改值，保留可审计）。"""
    fact = db.get(CustomerFact, fact_id)
    if fact is None or fact.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="事实不存在")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if payload.action == "invalidate":
        fact.superseded_by = "manual"
        db.commit()
        return ok({"fact_id": fact.id, "action": "invalidate"})

    if payload.action == "update":
        if not payload.value:
            raise HTTPException(status_code=422, detail="update 需要提供 value")
        new_fact = CustomerFact(
            customer_id=customer_id,
            key=fact.key,
            value=payload.value,
            confidence=1.0,
            evidence="人工纠正",
            valid_until=fact.valid_until,
            created_at=now,
        )
        db.add(new_fact)
        db.flush()
        fact.superseded_by = new_fact.id
        db.commit()
        return ok({"fact_id": new_fact.id, "action": "update", "value": new_fact.value})

    raise HTTPException(status_code=422, detail="action 只能是 invalidate 或 update")
