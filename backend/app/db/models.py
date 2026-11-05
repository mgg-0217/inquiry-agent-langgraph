"""SQLAlchemy 2.0 数据模型。

第 1 天只落 3 张表（customers / threads / messages），后续模块按 PRD 第 8 章逐步补齐。
所有业务表带 tenant_id，默认 "default"（首版不校验，Phase 3 启用）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """统一存 UTC naive 时间，避免 sqlite 丢时区后语义混乱。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(String(32), default="default", index=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(TenantMixin, TimestampMixin, Base):
    """客户主数据。第 1 天先按发件邮箱自动建档，实体解析在 resolve 节点（第 4 天）增强。"""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    credit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    credit_grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # L4 自动建档的客户标记为新客户；后续人工补全信息后可置 false
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)

    threads: Mapped[list["Thread"]] = relationship(back_populates="customer")


class Thread(TenantMixin, TimestampMixin, Base):
    """一封询盘对话（邮件串）。

    status 取值见 PRD 8 章：
    received / triaging / waiting_clarify / processing / waiting_approval /
    replied / archived_spam / archived_compliance / archived_rejected
    """

    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("customers.id"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(512), default="")
    # 去 Re:/Fwd:/中文回复前缀、压缩空白、转小写后的主题，用于线程归并兜底
    subject_norm: Mapped[str] = mapped_column(String(512), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    customer: Mapped[Customer | None] = relationship(back_populates="threads")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", order_by="Message.received_at"
    )


class Message(TimestampMixin, Base):
    """单封邮件。message_id 是幂等唯一键。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("threads.id"), index=True
    )
    message_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(16), default="inbound")  # inbound | outbound
    subject: Mapped[str] = mapped_column(String(512), default="")
    from_email: Mapped[str] = mapped_column(String(255), default="")
    from_name: Mapped[str] = mapped_column(String(255), default="")
    to_emails: Mapped[list] = mapped_column(JSON, default=list)
    cc_emails: Mapped[list] = mapped_column(JSON, default=list)
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    references: Mapped[list] = mapped_column(JSON, default=list)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    thread: Mapped[Thread] = relationship(back_populates="messages")


class CustomerAlias(TenantMixin, TimestampMixin, Base):
    """客户别名（公司名 / 关联邮箱），供 L2/L3 实体解析使用（PRD F2）。"""

    __tablename__ = "customer_aliases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id"), index=True
    )
    alias_type: Mapped[str] = mapped_column(String(32), default="email")  # email | company | phone
    alias_value: Mapped[str] = mapped_column(String(512), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class CustomerFact(TenantMixin, TimestampMixin, Base):
    """长期记忆：结论 + 证据（PRD F3.3 / F3.4）。

    - 价格类事实带 `valid_until`
    - 冲突不删除旧记录，用 `superseded_by` 指向新记录
    """

    __tablename__ = "customer_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id"), index=True
    )
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.85)
    evidence: Mapped[str] = mapped_column(Text, default="")
    source_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Interaction(TenantMixin, TimestampMixin, Base):
    """情节型记忆：某次发生了什么（PRD F3.2）。"""

    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id"), index=True
    )
    thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="unknown")
    lost_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SanctionEntry(TimestampMixin, Base):
    """制裁名单条目（PRD 8 / F6 L1）。参考数据，不带 tenant_id。"""

    __tablename__ = "sanctions_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    list_name: Mapped[str] = mapped_column(String(64), default="OFAC SDN", index=True)
    entry_no: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    name_norm: Mapped[str] = mapped_column(String(512), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    program: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    addresses: Mapped[list] = mapped_column(JSON, default=list)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(TenantMixin, TimestampMixin, Base):
    """审计日志（PRD 8 / 11.4）：人工动作与自动发送都要留痕。"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AppState(Base):
    """应用级键值状态（如 IMAP 拉取基线），不带 tenant_id。"""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
