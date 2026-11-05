"""第 2 天验收演示：跑一条 happy path + 一条议价挂起/恢复。

用法：
    python backend/scripts/demo_happy_path.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.graph.build import build_serde, build_single_agent  # noqa: E402
from app.graph.state import MailInput  # noqa: E402


def mail(**kw) -> MailInput:
    data = dict(
        message_id="<demo-001@acme-import.example>",
        subject="Inquiry: X200 120 units, CIF Valencia",
        from_email="carlos@acme-import.example",
        from_name="Carlos Mendoza",
        body_text="Please quote 120 units of X200, CIF Valencia.",
    )
    data.update(kw)
    return MailInput(**data)


def main() -> int:
    graph = build_single_agent(checkpointer=InMemorySaver(serde=build_serde()))

    print("=" * 68)
    print("1) happy path：授权内自动回复")
    print("=" * 68)
    out = graph.invoke(
        {
            "mail": mail(),
            "thread_id": "thread:demo-001",
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
        },
        config={"configurable": {"thread_id": "demo-happy"}},
    )
    for step in out["trace"]:
        print(f"  [{step.node:<10}] {step.summary}")
    print(f"\n  round={out['round']} followup={out['is_followup']} step={out['step']}")
    quote = out["quote"]
    print(f"  报价：{quote.sku} × {quote.qty} → USD {quote.unit_price}/台，总 USD {quote.total}")
    print(f"  决策：{out['decision'].action} / 合规：{out['verdict'].result}")

    print()
    print("=" * 68)
    print("2) 议价轮：强制转人工，挂起在 approval")
    print("=" * 68)
    config = {"configurable": {"thread_id": "demo-negotiation"}}
    suspended = graph.invoke(
        {
            "mail": mail(
                message_id="<demo-002@acme-import.example>",
                in_reply_to="<demo-001@acme-import.example>",
                body_text="USD 364 is above our budget. Competitor offers USD 350.",
                is_price_negotiation=True,
                client_offered_price=350.0,
            ),
            "thread_id": "thread:demo-001",
            "step": 0,
            "trace": [],
            "errors": [],
            "clarify_count": 0,
            "is_followup": True,
            "round": 1,
        },
        config=config,
    )
    interrupts = suspended.get("__interrupt__", [])
    print(f"  挂起：{len(interrupts)} 个 interrupt")
    if interrupts:
        payload = interrupts[0].value
        print(f"  挂起载荷：type={payload.get('type')} draft={payload.get('reply_draft')}")

    resumed = graph.invoke(
        Command(resume={"action": "approve", "comment": "同意按目标价", "approver": "李"}),
        config=config,
    )
    print(f"  人工动作：{resumed['approval'].action}")
    print(f"  恢复后节点：{' → '.join(s.node for s in resumed['trace'][-4:])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
