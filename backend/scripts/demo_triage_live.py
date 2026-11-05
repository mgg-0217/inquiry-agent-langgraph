"""第 4 天验收演示：真实 DeepSeek 跑分诊 + 记忆抽取/召回。

用法：
    python backend/scripts/demo_triage_live.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Customer
from app.graph.clarify import compose_clarify
from app.graph.state import MailInput
from app.graph.triage import triage_mail
from app.llm.client import get_chat_llm
from app.memory.extractor import extract_memory
from app.memory.recall import recall_memory
from app.memory.store import write_memory


def mail(body: str, subject: str, from_name: str = "Carlos Mendoza") -> MailInput:
    return MailInput(
        message_id=f"<demo-{abs(hash(body)) % 10**8}@acme-import.example>",
        subject=subject,
        from_email="carlos@acme-import.example",
        from_name=from_name,
        body_text=body,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


def main() -> int:
    llm = get_chat_llm()

    print("=" * 70)
    print("1) 分诊：完整询盘")
    print("=" * 70)
    complete_mail = mail(
        "Dear Sales, please quote 500 units of X200 centrifugal pump, 380V/50Hz, "
        "CIF Valencia. Please confirm lead time.",
        "Inquiry: X200 500 units CIF Valencia",
    )
    triage = triage_mail(llm, complete_mail)
    print(f"  is_spam={triage.is_spam} complete={triage.complete} confidence={triage.confidence}")
    print(f"  missing={triage.missing} negotiation={triage.is_negotiation}")

    print()
    print("=" * 70)
    print("2) 分诊：信息不全 → 追问")
    print("=" * 70)
    vague_mail = mail(
        "Hi, send me your best price for water pumps.",
        "price?",
        from_name="New Buyer",
    )
    vague_triage = triage_mail(llm, vague_mail)
    print(f"  is_spam={vague_triage.is_spam} complete={vague_triage.complete}")
    print(f"  missing={vague_triage.missing}")
    print(f"  questions={vague_triage.clarify_questions}")
    print("  --- 生成的追问草稿 ---")
    draft = compose_clarify(llm, vague_mail, vague_triage)
    for line in draft.splitlines():
        print(f"  {line}")

    print()
    print("=" * 70)
    print("3) 分诊：垃圾邮件（规则命中，不调模型）")
    print("=" * 70)
    spam_mail = mail(" ".join(f"https://spam.example/{i}" for i in range(12)), "Promo")
    spam_triage = triage_mail(llm, spam_mail)
    print(f"  is_spam={spam_triage.is_spam} reason={spam_triage.spam_reason} confidence={spam_triage.confidence}")

    print()
    print("=" * 70)
    print("4) 记忆：从客户原话抽取 → 证据校验 → 召回")
    print("=" * 70)
    memory_mail = mail(
        "USD 364 is above our budget. Competitor offers USD 350 CIF Valencia. "
        "We need 380V/50Hz. We will wait for your revised offer.",
        "Re: Inquiry X200",
    )
    extract = extract_memory(llm, memory_mail)
    print(f"  抽到 {len(extract.facts)} 条事实，lost_reason={extract.lost_reason}")
    for fact in extract.facts:
        print(f"   - {fact.key}={fact.value}（证据：“{fact.evidence}”）")

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        customer = Customer(email="carlos@acme-import.example", name="Acme Import", is_new=False)
        session.add(customer)
        session.flush()
        report = write_memory(session, customer.id, memory_mail, extract)
        session.commit()
        print(f"\n  写入 {report.written}，丢弃 {report.dropped}")

        memory = recall_memory(session, customer.id)
        print("  --- 召回的记忆块 ---")
        for line in memory.block.splitlines() or ["（空）"]:
            print(f"  {line}")

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
