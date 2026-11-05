from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerFact, Interaction
from app.graph.state import MailInput
from app.memory.recall import recall_memory
from app.memory.schema import ExtractedFact, ExtractedMemory
from app.memory.store import write_memory


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_customer(session: Session, email: str = "buyer@acme-import.example") -> Customer:
    customer = Customer(email=email, name="Acme Import", is_new=False)
    session.add(customer)
    session.commit()
    return customer


def make_mail(body: str, message_id: str = "<m1@x>") -> MailInput:
    return MailInput(
        message_id=message_id,
        subject="Inquiry: X200",
        from_email="buyer@acme-import.example",
        body_text=body,
    )


# ---------------------------------------------------------------- 证据校验


def test_evidence_not_in_body_is_dropped(session: Session, caplog):
    """验收项：结论有、证据不在原文 → 丢弃并记日志。"""
    customer = make_customer(session)
    mail = make_mail("USD 364 is above our budget.")
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(
                key="target_price",
                value="350",
                evidence="Competitor offers USD 350",  # 原文里没有这句话
            )
        ],
        summary="客户嫌贵",
        outcome="lost",
        lost_reason="price_high",
    )

    with caplog.at_level(logging.WARNING):
        report = write_memory(session, customer.id, mail, extract)
    session.commit()

    assert report.written == []
    assert ("target_price", "evidence_not_in_body") in report.dropped
    assert "证据不在原文" in caplog.text


def test_valid_evidence_is_written(session: Session):
    customer = make_customer(session)
    body = "We need 380V/50Hz and CE certification for the pump."
    mail = make_mail(body)
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(key="voltage_spec", value="380V/50Hz", evidence="380V/50Hz"),
            ExtractedFact(key="certification_req", value="CE", evidence="CE certification"),
        ],
        summary="客户要求电压与认证",
        outcome="open",
    )

    report = write_memory(session, customer.id, mail, extract)
    session.commit()

    assert set(report.written) == {"voltage_spec", "certification_req"}
    rows = session.scalars(
        select(CustomerFact).where(CustomerFact.customer_id == customer.id)
    ).all()
    assert len(rows) == 2
    # 规格类事实永久有效
    assert all(r.valid_until is None for r in rows)


def test_price_fact_value_is_normalized_to_number(session: Session):
    """价格类 fact 的 value 必须能被下游当成数字用。"""
    customer = make_customer(session)
    mail = make_mail("Our target is USD 350 CIF Valencia.")
    report = write_memory(
        session,
        customer.id,
        mail,
        ExtractedMemory(
            facts=[
                ExtractedFact(
                    key="target_price",
                    value="USD 350 CIF Valencia（竞品报价）",
                    evidence="USD 350",
                )
            ],
            summary="客户给出目标价",
            outcome="open",
        ),
    )
    session.commit()

    assert report.written == ["target_price"]
    fact = session.scalar(
        select(CustomerFact).where(CustomerFact.key == "target_price")
    )
    assert fact.value == "350"


def test_price_fact_without_number_is_dropped(session: Session):
    customer = make_customer(session)
    mail = make_mail("We want the same price as the competitor offer.")
    report = write_memory(
        session,
        customer.id,
        mail,
        ExtractedMemory(
            facts=[
                ExtractedFact(
                    key="target_price",
                    value="same as competitor",
                    evidence="same price as the competitor offer",
                )
            ],
            summary="没给具体数字",
            outcome="open",
        ),
    )
    session.commit()

    assert report.written == []
    assert ("target_price", "invalid_price_value") in report.dropped


def test_price_fact_gets_valid_until(session: Session):
    customer = make_customer(session)
    mail = make_mail("Our target price is USD 350 CIF.")
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(
                key="target_price", value="350", evidence="Our target price is USD 350"
            )
        ],
        summary="客户给出目标价",
        outcome="open",
        lost_reason=None,
    )

    write_memory(session, customer.id, mail, extract)
    session.commit()

    fact = session.scalar(
        select(CustomerFact).where(CustomerFact.key == "target_price")
    )
    assert fact is not None
    assert fact.valid_until is not None
    assert fact.valid_until > _now()


# ---------------------------------------------------------------- no_response


def test_no_response_never_writes_price_facts(session: Session):
    """验收项：no_response 不许归因成嫌贵。"""
    customer = make_customer(session)
    mail = make_mail("Thanks, will revert.")
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(
                key="target_price",
                value="350",
                evidence="Thanks, will revert.",  # 证据有效，但 no_response 下不许写价格类
            )
        ],
        summary="客户说会再回复",
        outcome="lost",
        lost_reason="no_response",
    )

    report = write_memory(session, customer.id, mail, extract)
    session.commit()

    assert report.written == []
    assert ("target_price", "no_response_price_guess") in report.dropped

    interaction = session.scalar(
        select(Interaction).where(Interaction.customer_id == customer.id)
    )
    assert interaction is not None
    assert interaction.lost_reason == "no_response"


def test_no_response_still_allows_non_price_facts(session: Session):
    """no_response 只禁价格类，稳定规格仍然可以记。"""
    customer = make_customer(session)
    mail = make_mail("We use 440V/60Hz in our plant. Will revert later.")
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(key="voltage_spec", value="440V/60Hz", evidence="440V/60Hz")
        ],
        summary="客户未回，但提到电压",
        outcome="lost",
        lost_reason="no_response",
    )

    report = write_memory(session, customer.id, mail, extract)
    session.commit()
    assert report.written == ["voltage_spec"]


# ---------------------------------------------------------------- 冲突与召回


def test_recall_ignores_superseded_and_expired(session: Session):
    customer = make_customer(session)
    now = _now()
    old = CustomerFact(
        customer_id=customer.id,
        key="target_price",
        value="360",
        confidence=0.9,
        evidence="USD 360 is our target",
        created_at=now - timedelta(days=3),
    )
    new = CustomerFact(
        customer_id=customer.id,
        key="target_price",
        value="350",
        confidence=0.95,
        evidence="USD 350 CIF",
        created_at=now,
    )
    expired = CustomerFact(
        customer_id=customer.id,
        key="historic_price",
        value="380",
        confidence=0.9,
        evidence="quoted 380",
        valid_until=now - timedelta(days=1),
        created_at=now - timedelta(days=10),
    )
    session.add_all([old, new, expired])
    session.commit()

    # 两条都“有效”（superseded_by 为空）→ 只取最新
    memory = recall_memory(session, customer.id)
    target = [f for f in memory.facts if f.key == "target_price"]
    assert [f.value for f in target] == ["350"]

    # 标记 superseded 后，旧记录永不召回
    old.superseded_by = new.id
    session.commit()
    memory2 = recall_memory(session, customer.id)
    assert [f.value for f in memory2.facts if f.key == "target_price"] == ["350"]

    # 过期的历史价格不召回
    assert all(f.key != "historic_price" for f in memory2.facts)


def test_recall_keeps_two_when_older_confidence_is_much_higher(session: Session):
    """新记录置信度明显低于旧记录（差 > 0.3）时，两条都给模型。"""
    customer = make_customer(session)
    now = _now()
    high = CustomerFact(
        customer_id=customer.id,
        key="target_price",
        value="360",
        confidence=0.95,
        evidence="USD 360",
        created_at=now - timedelta(days=1),
    )
    low = CustomerFact(
        customer_id=customer.id,
        key="target_price",
        value="350",
        confidence=0.55,
        evidence="USD 350",
        created_at=now,
    )
    session.add_all([high, low])
    session.commit()

    memory = recall_memory(session, customer.id)
    values = {f.value for f in memory.facts if f.key == "target_price"}
    assert values == {"350", "360"}


def test_recall_block_contains_evidence_and_interactions(session: Session):
    customer = make_customer(session)
    mail = make_mail("USD 364 is above our budget. Competitor offers USD 350.")
    extract = ExtractedMemory(
        facts=[
            ExtractedFact(
                key="target_price",
                value="350",
                evidence="Competitor offers USD 350",
            )
        ],
        summary="询 X200 200 台，报价 364，客户嫌贵",
        outcome="lost",
        lost_reason="price_high",
        evidence="USD 364 is above our budget",
    )
    write_memory(session, customer.id, mail, extract)
    session.commit()

    memory = recall_memory(session, customer.id)
    assert "target_price=350" in memory.block
    assert "Competitor offers USD 350" in memory.block
    assert "price_high" in memory.block
    assert "客户原话" in memory.block
    assert len(memory.recent) == 1


def test_recall_returns_empty_for_unknown_customer(session: Session):
    memory = recall_memory(session, "no-such-customer")
    assert memory.facts == []
    assert memory.recent == []
    assert memory.block == ""


# ---------------------------------------------------------------- 写入幂等与冲突标记


def test_duplicate_fact_is_not_written_twice(session: Session):
    customer = make_customer(session)
    mail = make_mail("380V/50Hz please.")
    extract = ExtractedMemory(
        facts=[ExtractedFact(key="voltage_spec", value="380V/50Hz", evidence="380V/50Hz")],
        summary="规格",
        outcome="open",
    )

    write_memory(session, customer.id, mail, extract)
    write_memory(session, customer.id, mail, extract)
    session.commit()

    rows = session.scalars(
        select(CustomerFact).where(CustomerFact.customer_id == customer.id)
    ).all()
    assert len(rows) == 1


def test_new_fact_supersedes_old_one(session: Session):
    customer = make_customer(session)
    mail1 = make_mail("Our target is USD 360.", message_id="<m1@x>")
    mail2 = make_mail("Actually our target is USD 350.", message_id="<m2@x>")

    write_memory(
        session,
        customer.id,
        mail1,
        ExtractedMemory(
            facts=[ExtractedFact(key="target_price", value="360", evidence="USD 360")],
            summary="目标价 360",
            outcome="open",
        ),
    )
    write_memory(
        session,
        customer.id,
        mail2,
        ExtractedMemory(
            facts=[ExtractedFact(key="target_price", value="350", evidence="USD 350")],
            summary="目标价改为 350",
            outcome="open",
        ),
    )
    session.commit()

    rows = session.scalars(
        select(CustomerFact)
        .where(CustomerFact.customer_id == customer.id)
        .order_by(CustomerFact.created_at)
    ).all()
    assert len(rows) == 2
    assert rows[0].value == "360"
    assert rows[0].superseded_by == rows[1].id
    assert rows[1].superseded_by is None

    memory = recall_memory(session, customer.id)
    assert [f.value for f in memory.facts if f.key == "target_price"] == ["350"]
