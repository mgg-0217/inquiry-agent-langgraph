"""把解析后的邮件落库：幂等、线程归并、客户建档。

第 1 天的实体解析先用"发件邮箱精确匹配"（PRD F2 的 L1），
四级解析与客户确认流程在第 4 天模块里补。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Customer, Message, Thread
from app.mail.base import MailProvider, ParsedMail
from app.mail.parser import normalize_subject

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    message_id: str
    thread_id: str
    customer_id: str
    duplicated: bool = False
    is_followup: bool = False


@dataclass
class SyncReport:
    fetched: int = 0
    created: int = 0
    duplicated: int = 0
    errors: list[str] = field(default_factory=list)
    # 本次有新邮件的 thread，供轮询任务触发 Agent 处理
    touched_thread_ids: list[str] = field(default_factory=list)


def _find_thread(session: Session, mail: ParsedMail) -> Thread | None:
    # 1) In-Reply-To / References：从最近一级父邮件往上找
    parents = [*mail.references]
    if mail.in_reply_to:
        parents.append(mail.in_reply_to)
    for parent_id in reversed(parents):
        row = session.scalar(select(Message).where(Message.message_id == parent_id))
        if row is not None:
            return session.get(Thread, row.thread_id)

    # 2) 主题归一化 + 发件人兜底（90 天内）
    norm = normalize_subject(mail.subject)
    if not norm:
        return None
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    stmt = (
        select(Thread)
        .join(Customer, Thread.customer_id == Customer.id)
        .where(
            Customer.email == mail.from_email,
            Thread.subject_norm == norm,
            Thread.last_message_at >= since,
        )
        .order_by(Thread.last_message_at.desc())
    )
    return session.scalars(stmt).first()


def _get_or_create_customer(session: Session, mail: ParsedMail) -> Customer:
    customer = session.scalar(select(Customer).where(Customer.email == mail.from_email))
    if customer is not None:
        if not customer.name and mail.from_name:
            customer.name = mail.from_name
        return customer
    domain = mail.from_email.split("@", 1)[-1] if "@" in mail.from_email else None
    customer = Customer(
        email=mail.from_email,
        name=mail.from_name or mail.from_email,
        domain=domain,
        is_new=True,  # 自动建档：等人工补全信息后才转为老客户
    )
    session.add(customer)
    session.flush()
    return customer


def _naive_utc(dt: datetime) -> datetime:
    """统一成 UTC naive，与 sqlite 列语义一致。"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def ingest_parsed(session: Session, mail: ParsedMail) -> IngestResult:
    """单封邮件入库。同一 Message-ID 重复调用直接返回已有记录（幂等）。"""
    if not mail.message_id:
        raise ValueError("mail.message_id 为空，无法保证幂等")

    if not mail.from_email:
        # 极少数邮件缺 From：用 Message-ID 派生占位地址，避免所有此类邮件共用空邮箱
        token = mail.message_id.strip("<>")[:12]
        logger.warning("邮件缺少 From，使用占位发件人 message_id=%s", mail.message_id)
        mail = replace(mail, from_email=f"unknown-{token}@invalid")

    existing = session.scalar(
        select(Message).where(Message.message_id == mail.message_id)
    )
    if existing is not None:
        thread = session.get(Thread, existing.thread_id)
        return IngestResult(
            message_id=mail.message_id,
            thread_id=existing.thread_id,
            customer_id=thread.customer_id if thread else "",
            duplicated=True,
            is_followup=True,
        )

    thread = _find_thread(session, mail)
    is_followup = thread is not None
    customer: Customer | None = thread.customer if thread else None
    if customer is None:
        customer = _get_or_create_customer(session, mail)

    received_at = _naive_utc(mail.received_at or datetime.now(timezone.utc))
    if thread is None:
        thread = Thread(
            customer_id=customer.id,
            subject=mail.subject,
            subject_norm=normalize_subject(mail.subject),
            status="received",
            last_message_at=received_at,
        )
        session.add(thread)
        session.flush()
    elif received_at > thread.last_message_at:
        thread.last_message_at = received_at

    msg = Message(
        thread_id=thread.id,
        message_id=mail.message_id,
        direction="inbound",
        subject=mail.subject,
        from_email=mail.from_email,
        from_name=mail.from_name,
        to_emails=list(mail.to_emails),
        cc_emails=list(mail.cc_emails),
        body_text=mail.body_text,
        body_html=mail.body_html,
        attachments=list(mail.attachments),
        in_reply_to=mail.in_reply_to,
        references=list(mail.references),
        received_at=received_at,
    )
    session.add(msg)
    session.flush()

    return IngestResult(
        message_id=mail.message_id,
        thread_id=thread.id,
        customer_id=customer.id,
        duplicated=False,
        is_followup=is_followup,
    )


# 轮询任务与"立即同步"可能同时触发：串行化，避免同一封邮件被重复拉取。
# 锁只保证进程内；跨进程/跨 worker 的最终保障是 messages.message_id 唯一约束。
_SYNC_LOCK = threading.Lock()


def sync_inbox(session: Session, provider: MailProvider) -> SyncReport:
    """从 provider 拉一次新邮件并入库（串行执行）。"""
    with _SYNC_LOCK:
        return _sync_inbox_locked(session, provider)


def _sync_inbox_locked(session: Session, provider: MailProvider) -> SyncReport:
    report = SyncReport()
    known = set(session.scalars(select(Message.message_id)).all())
    mails = provider.fetch_new(known)
    report.fetched = len(mails)
    for mail in mails:
        try:
            with session.begin_nested():
                result = ingest_parsed(session, mail)
        except IntegrityError:
            existing = session.scalar(
                select(Message).where(Message.message_id == mail.message_id)
            )
            if existing is not None:
                # 并发下另一个执行者刚写入同一 Message-ID：按重复处理
                logger.info("邮件已被并发写入，视为重复 message_id=%s", mail.message_id)
                report.duplicated += 1
                continue
            # 否则可能是并发创建了同一 customer（email 唯一约束）：重试一次
            try:
                with session.begin_nested():
                    result = ingest_parsed(session, mail)
                report.created += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("邮件入库重试失败 message_id=%s", mail.message_id)
                report.errors.append(f"{mail.message_id}: {exc}")
            continue
        except Exception as exc:  # 单封失败不影响整批
            logger.exception("邮件入库失败 message_id=%s", mail.message_id)
            report.errors.append(f"{mail.message_id}: {exc}")
            continue
        if result.duplicated:
            report.duplicated += 1
        else:
            report.created += 1
            if result.thread_id not in report.touched_thread_ids:
                report.touched_thread_ids.append(result.thread_id)
    logger.info(
        "同步完成 fetched=%d created=%d duplicated=%d errors=%d",
        report.fetched, report.created, report.duplicated, len(report.errors),
    )
    # 全部成功才推进 IMAP 基线，避免因解析失败漏拉
    if not report.errors and hasattr(provider, "advance_baseline"):
        try:
            provider.advance_baseline()
        except Exception:  # noqa: BLE001
            logger.warning("推进 IMAP 基线失败（不影响本次入库）", exc_info=True)
    return report
