"""第 5—6 天验收演示：OFAC 命中 + 真实模型报价规划。

用法：
    python backend/scripts/demo_module5_live.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.compliance.disambiguate import SanctionsIndex, screen_name  # noqa: E402
from app.compliance.loader import load_json  # noqa: E402
from app.db.models import Base, Customer  # noqa: E402
from app.db.seed import seed_demo_customers  # noqa: E402
from app.graph.nodes import make_draft_plan_node  # noqa: E402
from app.graph.state import MailInput  # noqa: E402
from app.llm.client import get_chat_llm  # noqa: E402
from app.memory.recall import recall_memory  # noqa: E402

DATA = BACKEND_DIR / "data" / "sanctions" / "entries.json"


def main() -> int:
    print("=" * 72)
    print("1) OFAC 真实名单筛查")
    print("=" * 72)
    if not DATA.exists():
        print("  ⚠️ 缺少 entries.json，先跑 scripts/fetch_sanctions.py")
    else:
        records = load_json(DATA)
        index = SanctionsIndex(records)
        print(f"  名单条目：{len(records):,} 条")
        for query in ("BANCO NACIONAL DE CUBA", "BNC", "Acme Import S.L.", "NewCo Trading"):
            hits = screen_name(query, records, index=index)
            if hits:
                top = hits[0]
                print(f"  {query:<26} → {top.score:.2f}  {top.evidence}")
            else:
                print(f"  {query:<26} → 未命中")

    print()
    print("=" * 72)
    print("2) 真实模型报价规划（老客户 500 台 X200，记忆里 target=350）")
    print("=" * 72)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_demo_customers(session)

    with factory() as session:
        customer = session.scalar(
            select(Customer).where(Customer.email == "carlos@acme-import.example")
        )
        memory = recall_memory(session, customer.id)

    print(f"  召回记忆：{len(memory.facts)} 条")
    for fact in memory.facts:
        print(f"    - {fact.key}={fact.value}")

    mail = MailInput(
        message_id="<demo-500@acme-import.example>",
        subject="Inquiry: X200 500 units, CIF Valencia",
        from_email="carlos@acme-import.example",
        from_name="Carlos Mendoza",
        body_text=(
            "Dear Sales, please quote 500 units of X200 centrifugal pump, "
            "380V/50Hz, CIF Valencia. We target USD 350."
        ),
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    llm = get_chat_llm()
    node = make_draft_plan_node(llm, factory)
    out = node(
        {
            "mail": mail,
            "customer_id": customer.id,
            "memory": memory,
            "thread_id": "thread:demo-500",
            "step": 0,
            "trace": [],
            "round": 2,
        }
    )

    print(f"\n  节点摘要：{out['trace'][0].summary}")
    quote = out.get("quote")
    strategy = out.get("strategy")
    if quote is None:
        print("  ⚠️ 未产出报价")
    else:
        print(f"  报价：{quote.sku} × {quote.qty} {quote.incoterm} {quote.destination}")
        print(f"    单价 USD {quote.unit_price} / 总价 USD {quote.total}")
        print(f"    成本线 USD {quote.floor_price} / 目标价匹配 {quote.target_matched_price}")
        print(f"    有效期 {quote.valid_until}")
    if strategy is not None:
        print(f"  策略：stance={strategy.stance} mention_history={strategy.mention_history} "
              f"adjust={strategy.price_adjustment}")
        print(f"    rationale：{strategy.rationale}")
    if out.get("inventory") is not None:
        print(f"  库存：available={out['inventory'].available} lead_time={out['inventory'].lead_time}")

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
