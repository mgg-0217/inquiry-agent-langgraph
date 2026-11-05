from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerFact, Interaction
from app.db.seed import seed_demo_customers


def test_seed_fixes_contact_name_to_company_name(session: Session):
    """自动建档时 name 可能是联系人名，seed 必须修正为公司名（合规筛查要用）。"""
    customer = Customer(
        email="carlos@acme-import.example", name="Carlos Mendoza", is_new=True
    )
    session.add(customer)
    session.commit()

    seed_demo_customers(session)
    session.refresh(customer)

    assert customer.name == "Acme Import S.L."
    assert customer.is_new is False


def test_seed_is_idempotent(session: Session):
    seed_demo_customers(session)
    facts_1 = session.scalar(select(func.count(CustomerFact.id)))
    interactions_1 = session.scalar(select(func.count(Interaction.id)))

    seed_demo_customers(session)
    facts_2 = session.scalar(select(func.count(CustomerFact.id)))
    interactions_2 = session.scalar(select(func.count(Interaction.id)))

    assert facts_2 == facts_1
    assert interactions_2 == interactions_1
    assert facts_1 >= 3  # Acme 的 target_price / CIF / 电压


def test_seed_writes_target_price_with_validity(session: Session):
    seed_demo_customers(session)
    fact = session.scalar(
        select(CustomerFact).where(CustomerFact.key == "target_price")
    )
    assert fact is not None
    assert fact.value == "350"
    assert fact.valid_until is not None
