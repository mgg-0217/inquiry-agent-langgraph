"""第 4 天端到端演示：真实 LLM 跑完整图（内存库，不污染开发库）。

用法：
    python backend/scripts/demo_graph_live.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.models import Base  # noqa: E402
from app.db.seed import seed_demo_customers  # noqa: E402
from app.graph.build import build_serde, build_single_agent  # noqa: E402
from app.graph.state import MailInput  # noqa: E402


def mail(body: str, subject: str, from_email: str, from_name: str, **kw) -> MailInput:
    return MailInput(
        message_id=f"<demo-{abs(hash(body)) % 10**8}@example.com>",
        subject=subject,
        from_email=from_email,
        from_name=from_name,
        body_text=body,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
        **kw,
    )


def main() -> int:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_demo_customers(session)

    graph = build_single_agent(
        checkpointer=InMemorySaver(serde=build_serde()), session_factory=factory
    )

    print("=" * 70)
    print("1) 新客户 · 完整询盘")
    print("=" * 70)
    out = graph.invoke(
        {
            "mail": mail(
                "Dear Sales, please quote 120 units of X200 pump, 380V/50Hz, CIF Hamburg.",
                "Inquiry: X200 120 units",
                "buyer@newco.example",
                "New Buyer",
            ),
            "thread_id": "thread:demo-new",
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config={"configurable": {"thread_id": "demo-new"}},
    )
    for step in out["trace"]:
        print(f"  [{step.node:<10}] {step.summary}")
    print(f"\n  实体解析：{out['resolved'].method}  customer={out['customer_id'][:8]}…")
    print(f"  召回（执行前）：{len(out['memory'].facts)} 条事实")
    print(f"  决策：{out['decision'].action}（第 5 天起报价来自工具）")

    # persist 在 dispatch 之后执行，所以本次抽取的记忆要再查一次才看得到
    from sqlalchemy import select

    from app.db.models import Customer
    from app.memory.recall import recall_memory

    with factory() as session:
        customer = session.scalar(
            select(Customer).where(Customer.email == "buyer@newco.example")
        )
        memory = recall_memory(session, customer.id) if customer else None
    print(f"  persist 后记忆：{len(memory.facts) if memory else 0} 条事实")
    if memory:
        for fact in memory.facts:
            print(f"    - {fact.key}={fact.value}（证据：“{fact.evidence}”）")

    print()
    print("=" * 70)
    print("2) 老客户 · 还价回信（应召回记忆并强制转人工）")
    print("=" * 70)
    suspended = graph.invoke(
        {
            "mail": mail(
                "Re: X200 500 units. USD 364 is above our budget. "
                "Competitor offers USD 350 CIF Valencia. "
                "If you can match USD 350, we can place the order.",
                "Re: Inquiry X200",
                "carlos@acme-import.example",
                "Carlos Mendoza",
                in_reply_to="<root@acme-import.example>",
            ),
            "thread_id": "thread:demo-old",
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
            "is_followup": True,
            "round": 1,
        },
        config={"configurable": {"thread_id": "demo-old"}},
    )

    nodes = [s.node for s in suspended["trace"]]
    print(f"  执行节点：{' → '.join(nodes)}")
    memory = suspended.get("memory")
    if memory is not None:
        print(f"  召回记忆（{len(memory.facts)} 条事实）：")
        for line in memory.block.splitlines():
            print(f"    {line}")
    else:
        print("  （本次未走到 recall）")
    interrupts = suspended.get("__interrupt__", [])
    print(f"\n  挂起：{len(interrupts)} 个 interrupt（议价强制转人工）")

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
