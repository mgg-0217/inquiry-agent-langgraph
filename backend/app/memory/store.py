"""记忆写入：证据校验 + 冲突处理（PRD F3.3 / F3.4）。

三条硬规则：
1. 没有客户原话证据的 fact，整条丢弃；
2. 证据必须是邮件正文的子串（归一化后比对），否则视为编造，丢弃并记警告；
3. `lost_reason=no_response` 时，不允许写入任何价格类 fact。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CustomerFact, Interaction
from app.graph.state import MailInput
from app.memory.schema import (
    FACT_KEYS,
    PRICE_KEYS,
    PRICE_VALID_DAYS,
    ExtractedMemory,
)

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
MIN_EVIDENCE_LEN = 3

# value 必须是数字的价格类 key（否则下游没法做数值比较）
NUMERIC_VALUE_KEYS = {"target_price", "historic_price"}


@dataclass
class WriteReport:
    written: list[str] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    superseded: int = 0
    interaction_id: str | None = None


def normalize_text(text: str | None) -> str:
    return _WS_RE.sub(" ", (text or "").strip()).lower()


def evidence_in_body(evidence: str, body: str) -> bool:
    ev = normalize_text(evidence)
    if len(ev) < MIN_EVIDENCE_LEN:
        return False
    return ev in normalize_text(body)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def write_memory(
    session: Session,
    customer_id: str | None,
    mail: MailInput,
    extract: ExtractedMemory,
    thread_id: str | None = None,
) -> WriteReport:
    """把抽取结果写入 facts + interactions，返回审计报告。"""
    report = WriteReport()
    if not customer_id:
        return report

    body = mail.body_text or mail.body_html or ""
    now = _utcnow()
    touched: set[str] = set()

    for fact in extract.facts:
        key = fact.key.strip()

        # 规则 0：只允许白名单 key
        if key not in FACT_KEYS:
            report.dropped.append((key, "unknown_key"))
            logger.warning("记忆 key 不在清单内，丢弃：%s", key)
            continue

        # 规则 1：必须有证据
        if not fact.evidence.strip():
            report.dropped.append((key, "no_evidence"))
            logger.warning("fact 无证据，丢弃：%s", key)
            continue

        # 规则 2：证据必须是原文子串（防伪造）
        if not evidence_in_body(fact.evidence, body):
            report.dropped.append((key, "evidence_not_in_body"))
            logger.warning("证据不在原文，疑似编造，丢弃：%s（evidence=%r）", key, fact.evidence)
            continue

        # 规则 3：no_response 不得写价格类事实（客户没回，不可能有价格证据）
        if extract.lost_reason == "no_response" and key in PRICE_KEYS:
            report.dropped.append((key, "no_response_price_guess"))
            logger.warning("lost_reason=no_response 时禁止写价格类 fact，丢弃：%s", key)
            continue

        # 同一批抽取里重复 key，只认第一条
        if key in touched:
            continue
        touched.add(key)

        value = fact.value.strip()
        if key in NUMERIC_VALUE_KEYS:
            # 价格类只留数字：模型常把整句塞进来，下游无法比较
            match = _NUM_RE.search(value)
            if match is None:
                report.dropped.append((key, "invalid_price_value"))
                logger.warning("价格类 fact 的 value 不含数字，丢弃：%s=%r", key, value)
                continue
            value = match.group(0)

        existing = list(
            session.scalars(
                select(CustomerFact).where(
                    CustomerFact.customer_id == customer_id,
                    CustomerFact.key == key,
                    CustomerFact.superseded_by.is_(None),
                )
            ).all()
        )
        # 完全重复：不新增（幂等）
        if any(old.value == value and old.evidence == fact.evidence for old in existing):
            continue

        valid_days = PRICE_VALID_DAYS.get(key)
        new_fact = CustomerFact(
            customer_id=customer_id,
            key=key,
            value=value,
            confidence=float(fact.confidence),
            evidence=fact.evidence,
            source_msg=mail.message_id,
            valid_until=(now + timedelta(days=valid_days)) if valid_days else None,
            created_at=now,
        )
        session.add(new_fact)
        session.flush()

        for old in existing:
            old.superseded_by = new_fact.id
            report.superseded += 1
        report.written.append(key)

    if extract.summary or extract.lost_reason:
        interaction = Interaction(
            customer_id=customer_id,
            thread_id=thread_id,
            summary=extract.summary or "（无摘要）",
            outcome=extract.outcome,
            lost_reason=extract.lost_reason,
            evidence=extract.evidence,
            created_at=now,
        )
        session.add(interaction)
        session.flush()
        report.interaction_id = interaction.id

    return report
