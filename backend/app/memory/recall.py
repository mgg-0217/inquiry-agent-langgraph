"""记忆召回：按 customer_id 查事实与交互，拼成记忆块（PRD F3.3 / F3.9）。

冲突取值规则（写死，见 PRD F3.3）：
- 只召回 `superseded_by IS NULL` 的事实
- 同 key 多条有效记录：取 `created_at` 最新
- 新记录置信度明显低于旧记录（差 > 0.3）：两条都给模型，标注置信度
- `valid_until < today`：不召回
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import CustomerFact, Interaction
from app.graph.state import Interaction as InteractionView
from app.graph.state import MemoryContext, MemoryFact

CONFIDENCE_GAP = 0.3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def recall_memory(session: Session, customer_id: str | None) -> MemoryContext:
    if not customer_id:
        return MemoryContext(block="")

    now = _utcnow()
    rows = list(
        session.scalars(
            select(CustomerFact)
            .where(
                CustomerFact.customer_id == customer_id,
                CustomerFact.superseded_by.is_(None),
                or_(CustomerFact.valid_until.is_(None), CustomerFact.valid_until >= now),
            )
            .order_by(CustomerFact.created_at.desc())
        ).all()
    )

    grouped: dict[str, list[CustomerFact]] = defaultdict(list)
    for row in rows:
        grouped[row.key].append(row)

    selected: list[CustomerFact] = []
    for items in grouped.values():
        items.sort(key=lambda r: r.created_at, reverse=True)
        latest = items[0]
        selected.append(latest)
        for other in items[1:]:
            # 旧记录的置信度明显更高（差值 > 0.3）时，把两条都给模型自己权衡
            if other.confidence - latest.confidence > CONFIDENCE_GAP:
                selected.append(other)

    facts = [
        MemoryFact(
            key=r.key,
            value=r.value,
            confidence=r.confidence,
            evidence=r.evidence,
            source_msg=r.source_msg,
            valid_until=r.valid_until.date() if r.valid_until else None,
            created_at=r.created_at,
        )
        for r in selected
    ]

    recent_rows = list(
        session.scalars(
            select(Interaction)
            .where(Interaction.customer_id == customer_id)
            .order_by(Interaction.created_at.desc())
            .limit(3)
        ).all()
    )
    recent = [
        InteractionView(
            summary=r.summary,
            outcome=r.outcome,
            lost_reason=r.lost_reason,
            evidence=r.evidence,
            created_at=r.created_at,
        )
        for r in recent_rows
    ]

    block = render_memory_block(facts, recent)
    return MemoryContext(facts=facts, recent=recent, pending=[], block=block)


def render_memory_block(facts: list[MemoryFact], recent: list[InteractionView]) -> str:
    """拼成可直接注入 prompt 的记忆块（结论 + 客户原话，PRD F3.9）。"""
    lines: list[str] = []
    if facts:
        lines.append("【客户记忆】")
        lines.append("稳定事实：")
        for f in facts:
            evidence = f"；证据：“{f.evidence}”" if f.evidence else ""
            lines.append(f"- {f.key}={f.value}（置信度 {f.confidence:.2f}{evidence}）")
    if recent:
        lines.append("最近交互：")
        for r in recent:
            reason = r.lost_reason or "未知"
            lines.append(
                f"- {r.created_at.date()} {r.summary}（结果：{r.outcome}，原因：{reason}）"
            )
            if r.evidence:
                lines.append(f"  客户原话：“{r.evidence}”")
    if not lines:
        return ""
    lines.append("未闭环：无")
    return "\n".join(lines)
