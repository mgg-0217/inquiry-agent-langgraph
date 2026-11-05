from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Customer
from app.graph.resolve import resolve_customer
from app.graph.state import MailInput


def make_mail(**kwargs) -> MailInput:
    data = dict(
        message_id="<resolve-1@acme-import.example>",
        subject="Inquiry",
        from_email="buyer@acme-import.example",
        from_name="Buyer",
        body_text="Please quote.",
    )
    data.update(kwargs)
    return MailInput(**data)


def test_l1_email_exact_match(session: Session):
    customer = Customer(email="buyer@acme-import.example", name="Acme", is_new=False)
    session.add(customer)
    session.commit()

    resolved = resolve_customer(session, make_mail())

    assert resolved.method == "email_exact"
    assert resolved.confidence == 1.0
    assert resolved.customer_id == customer.id
    assert resolved.need_confirm is False


def test_l4_creates_new_customer(session: Session):
    resolved = resolve_customer(session, make_mail(from_email="new@newco.example"))

    assert resolved.method == "new"
    assert resolved.need_confirm is False
    row = session.get(Customer, resolved.customer_id)
    assert row is not None
    assert row.email == "new@newco.example"
    assert row.is_new is True
    assert row.domain == "newco.example"


def test_missing_from_uses_placeholder_email(session: Session):
    resolved = resolve_customer(session, make_mail(from_email=""))
    row = session.get(Customer, resolved.customer_id)
    assert row is not None
    assert row.email.startswith("unknown-")
    assert row.email.endswith("@invalid")


def test_email_is_normalized_to_lowercase(session: Session):
    resolved = resolve_customer(session, make_mail(from_email="Buyer@Acme-Import.Example"))
    row = session.get(Customer, resolved.customer_id)
    assert row is not None
    assert row.email == "buyer@acme-import.example"
