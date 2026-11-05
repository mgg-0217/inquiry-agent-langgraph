"""第 7 天验收演示：超授权挂起 → 人工审批 → 发送。

用法：
    python backend/scripts/demo_approval_live.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.compliance.loader import load_json, save_to_db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.seed import seed_demo_customers  # noqa: E402
from app.graph.build import build_serde, build_single_agent  # noqa: E402
from app.graph.state import MailInput  # noqa: E402

DATA = BACKEND_DIR / "data" / "sanctions" / "entries.json"


def main() -> int:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_demo_customers(session)
        if DATA.exists():
            save_to_db(session, load_json(DATA))
            print(f"制裁名单已导入：{len(load_json(DATA)):,} 条")

    graph = build_single_agent(
        checkpointer=InMemorySaver(serde=build_serde()), session_factory=factory
    )

    mail = MailInput(
        message_id="<demo-approval@acme-import.example>",
        subject="Inquiry: X200 500 units, CIF Valencia",
        from_email="carlos@acme-import.example",
        from_name="Carlos Mendoza",
        body_text=(
            "Dear Sales, please quote 500 units of X200 centrifugal pump, "
            "380V/50Hz, CIF Valencia. We target USD 350."
        ),
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    config = {"configurable": {"thread_id": "demo-approval"}}

    print()
    print("=" * 72)
    print("1) 500 台 X200（总价 175,000 超授权 150,000）→ 应挂起审批")
    print("=" * 72)
    out = graph.invoke(
        {
            "mail": mail,
            "thread_id": "demo-approval",
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config=config,
    )

    for step in out["trace"]:
        print(f"  [{step.node:<10}] {step.summary}")
    print(f"\n  决策：{out['decision'].action} —— {out['decision'].reason}")
    quote = out["quote"]
    if quote:
        print(f"  报价：{quote.sku} × {quote.qty} CIF ${quote.unit_price}，总 ${quote.total}")
    interrupts = out.get("__interrupt__", [])
    print(f"  挂起：{len(interrupts)} 个 interrupt")
    if interrupts:
        payload = interrupts[0].value
        print(f"  审批载荷：type={payload.get('type')} thread={payload.get('thread_id')}")
        print(f"  草稿（前 200 字）：\n    {(payload.get('reply_draft') or '')[:200]}")

    print()
    print("=" * 72)
    print("2) 业务员批准 → dispatch（DRY_RUN）→ persist")
    print("=" * 72)
    resumed = graph.invoke(
        Command(resume={"action": "approve", "comment": "同意按目标价", "approver": "李"}),
        config=config,
    )
    for step in resumed["trace"][-3:]:
        print(f"  [{step.node:<10}] {step.summary}")
    print(f"  人工动作：{resumed['approval'].action}")
    print(f"  是否真发：{resumed['sent']}（DRY_RUN=true 时为 False）")

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
