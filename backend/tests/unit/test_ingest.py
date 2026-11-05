from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Customer, Message, Thread
from app.mail.base import ParsedMail
from app.mail.ingest import ingest_parsed
from app.mail.parser import normalize_subject


def _mail(
    *,
    message_id: str,
    subject: str,
    body: str = "hello",
    from_email: str = "carlos@acme-import.example",
    from_name: str = "Carlos",
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    received_at: datetime | None = None,
) -> ParsedMail:
    return ParsedMail(
        message_id=message_id,
        subject=subject,
        from_email=from_email,
        from_name=from_name,
        to_emails=["sales@example.com"],
        body_text=body,
        received_at=received_at or datetime.now(timezone.utc),
        in_reply_to=in_reply_to,
        references=references or [],
    )


def test_first_mail_creates_customer_thread_message(session: Session):
    result = ingest_parsed(session, _mail(message_id="<m1@x>", subject="Inquiry X200"))
    session.commit()

    assert result.duplicated is False
    assert result.is_followup is False
    assert session.scalar(select(func.count(Message.id))) == 1
    thread = session.get(Thread, result.thread_id)
    assert thread is not None
    assert thread.subject == "Inquiry X200"
    assert thread.subject_norm == normalize_subject("Inquiry X200")
    customer = session.get(Customer, result.customer_id)
    assert customer is not None and customer.email == "carlos@acme-import.example"


def test_duplicate_message_id_is_idempotent(session: Session):
    first = ingest_parsed(session, _mail(message_id="<dup@x>", subject="Inquiry"))
    second = ingest_parsed(session, _mail(message_id="<dup@x>", subject="Inquiry"))
    session.commit()

    assert second.duplicated is True
    assert second.thread_id == first.thread_id
    assert session.scalar(select(func.count(Message.id))) == 1


def test_reply_joins_same_thread_via_in_reply_to(session: Session):
    root = ingest_parsed(session, _mail(message_id="<root@x>", subject="Inquiry X200"))
    reply = ingest_parsed(
        session,
        _mail(
            message_id="<reply@x>",
            subject="Re: Inquiry X200",
            in_reply_to="<root@x>",
            references=["<root@x>"],
        ),
    )
    session.commit()

    assert reply.thread_id == root.thread_id
    assert reply.is_followup is True
    assert session.scalar(
        select(func.count(Message.id)).where(Message.thread_id == root.thread_id)
    ) == 2


def test_reply_joins_same_thread_via_references_only(session: Session):
    root = ingest_parsed(session, _mail(message_id="<root2@x>", subject="Inquiry Y300"))
    reply = ingest_parsed(
        session,
        _mail(
            message_id="<reply2@x>",
            subject="Re: Inquiry Y300",
            references=["<root2@x>"],
        ),
    )
    session.commit()
    assert reply.thread_id == root.thread_id


def test_subject_and_sender_fallback_merges_without_headers(session: Session):
    root = ingest_parsed(session, _mail(message_id="<a@x>", subject="Inquiry Z400"))
    later = ingest_parsed(
        session,
        _mail(message_id="<b@x>", subject="RE:  Inquiry Z400"),
    )
    session.commit()
    assert later.thread_id == root.thread_id
    assert later.is_followup is True


def test_different_sender_with_same_subject_keeps_threads_apart(session: Session):
    ingest_parsed(session, _mail(message_id="<c1@x>", subject="Inquiry X200"))
    second = ingest_parsed(
        session,
        _mail(
            message_id="<c2@x>",
            subject="Inquiry X200",
            from_email="other@buyer.example",
            from_name="Other",
        ),
    )
    session.commit()
    assert session.scalar(select(func.count(Thread.id))) == 2
    assert second.is_followup is False


def test_mail_without_from_uses_placeholder(session: Session):
    """缺 From 的邮件不能共用空邮箱，否则会给第二个客户建档失败。"""
    result = ingest_parsed(
        session,
        _mail(message_id="<nofrom-1@x>", subject="No from", from_email=""),
    )
    session.commit()

    customer = session.get(Customer, result.customer_id)
    assert customer is not None
    assert customer.email.startswith("unknown-")
    assert customer.email.endswith("@invalid")


def test_concurrent_sync_does_not_duplicate(tmp_path):
    """轮询任务与「立即同步」并发时，唯一约束 + 串行锁保证只入库一次。"""
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base
    from app.mail.ingest import sync_inbox

    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    mail = _mail(message_id="<concurrent@x>", subject="Concurrent inquiry")

    class Provider:
        def fetch_new(self, known_message_ids=None):
            known = known_message_ids or set()
            return [] if mail.message_id in known else [mail]

    provider = Provider()
    errors: list[Exception] = []

    def worker() -> None:
        db = factory()
        try:
            sync_inbox(db, provider)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    check = factory()
    try:
        count = check.scalar(select(func.count(Message.id)))
    finally:
        check.close()
        engine.dispose()

    assert not errors, f"并发同步报错: {errors}"
    assert count == 1
