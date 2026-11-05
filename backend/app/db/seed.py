"""种子数据：写入 PRD F2 的预置演示客户（全部虚构）。

- 老客户 Acme：8 年、偏好 CIF、2026-07 询 X200 未成（price_high）、目标价 350
- 新客户 NewCo
- 受制裁演示客户（用于第 5—6 天合规拦截）

幂等：按 email 找客户、按 key 找事实、按 summary 找交互，重复执行不重复插入。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerFact, Interaction
from app.memory.schema import PRICE_VALID_DAYS
from app.tools.fixtures import CUSTOMER_PROFILES

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_demo_customers(session: Session) -> dict:
    now = _utcnow()
    created = 0
    updated = 0

    for email, profile in CUSTOMER_PROFILES.items():
        customer = session.scalar(select(Customer).where(Customer.email == email))
        if customer is None:
            customer = Customer(
                email=email,
                name=profile.get("name", email),
                country=profile.get("country"),
                domain=email.split("@", 1)[-1],
                is_new=bool(profile.get("is_new", False)),
            )
            session.add(customer)
            session.flush()
            created += 1
        else:
            # 演示数据以 profile 为准：自动建档时 name 可能是联系人名（Carlos Mendoza），
            # 但合规筛查必须用公司名（Acme Import S.L.）
            if profile.get("name"):
                customer.name = profile["name"]
            if profile.get("country") and not customer.country:
                customer.country = profile["country"]
            customer.is_new = bool(profile.get("is_new", customer.is_new))
            updated += 1

        for fact in profile.get("facts", []):
            exists = session.scalar(
                select(CustomerFact).where(
                    CustomerFact.customer_id == customer.id,
                    CustomerFact.key == fact["key"],
                    CustomerFact.superseded_by.is_(None),
                )
            )
            if exists is not None:
                continue
            valid_days = PRICE_VALID_DAYS.get(fact["key"])
            session.add(
                CustomerFact(
                    customer_id=customer.id,
                    key=fact["key"],
                    value=str(fact["value"]),
                    confidence=float(fact.get("confidence", 0.85)),
                    evidence=fact.get("evidence", ""),
                    valid_until=(now + timedelta(days=valid_days)) if valid_days else None,
                    created_at=now,
                )
            )

        for order in profile.get("orders", []):
            summary = (
                f"{order['date']} 询 {order['sku']} {order['qty']} 台，"
                f"报价 {order['incoterm']} USD {order['unit_price']}"
            )
            exists = session.scalar(
                select(Interaction).where(
                    Interaction.customer_id == customer.id,
                    Interaction.summary == summary,
                )
            )
            if exists is not None:
                continue
            session.add(
                Interaction(
                    customer_id=customer.id,
                    thread_id=None,
                    summary=summary,
                    outcome=order.get("outcome", "unknown"),
                    lost_reason=order.get("lost_reason"),
                    evidence=order.get("evidence", ""),
                    created_at=now,
                )
            )

    session.commit()
    report = {"created": created, "updated": updated}
    logger.info("种子客户写入完成：%s", report)
    return report
