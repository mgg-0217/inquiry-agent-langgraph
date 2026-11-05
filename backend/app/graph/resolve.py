"""实体解析（PRD F2）：第 4 天只做 L1 邮箱精确 + L4 新建。

L2 域名 / L3 公司名模糊匹配在第 4 天之后补（需要 customer_aliases 数据）。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer
from app.graph.state import MailInput, Resolved

logger = logging.getLogger(__name__)


def resolve_customer(session: Session, mail: MailInput) -> Resolved:
    email = (mail.from_email or "").strip().lower()
    if not email:
        email = f"unknown-{mail.message_id.strip('<>')[:12]}@invalid"

    row = session.scalar(select(Customer).where(Customer.email == email))
    if row is not None:
        return Resolved(
            customer_id=row.id,
            method="email_exact",
            confidence=1.0,
            need_confirm=False,
        )

    domain = email.split("@", 1)[-1]
    customer = Customer(
        email=email,
        name=mail.from_name or email,
        domain=domain,
        is_new=True,
    )
    session.add(customer)
    session.flush()
    logger.info("新建客户档案 email=%s customer_id=%s", email, customer.id)
    return Resolved(
        customer_id=customer.id,
        method="new",
        confidence=1.0,
        need_confirm=False,
    )
