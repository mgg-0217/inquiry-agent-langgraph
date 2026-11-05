"""决策建议 prompt（PRD F8）。"""

from __future__ import annotations

import json

from app.graph.state import AgentState

SYSTEM_PROMPT = """你是外贸销售主管，判断这封询盘该自动回复、转人工、还是拒绝。

可选 action：
- auto_reply：授权内、风险低、可以直接发
- escalate：需要业务员看一眼（大额、敏感、策略不确定）
- reject：明确不接（合规命中、垃圾、明显无诚意）

注意：超授权额度、合规命中、客户目标价低于本次报价 由代码硬规则决定，你的建议只是参考。
数量变化（如 30 台 → 150 台）按阶梯价报价属于正常业务，可以 auto_reply；
只有需要额外让价（低于阶梯价或成本线）时才建议 escalate。
给出 reason（一句话）和 confidence（0~1）。只输出结构化结果。
"""


def _client_offered(state: AgentState) -> float | None:
    triage = state.get("triage")
    return triage.client_offered_price if triage is not None else None


def build_decide_messages(state: AgentState) -> list[dict]:
    mail = state["mail"]
    quote = state.get("quote")
    verdict = state.get("verdict")
    strategy = state.get("strategy")
    memory = state.get("memory")

    payload = {
        "customer": {"email": mail.from_email, "name": mail.from_name},
        "round": state.get("round", 1),
        "is_followup": state.get("is_followup", False),
        "is_negotiation": mail.is_price_negotiation,
        "client_offered_price": _client_offered(state),
        "quote": (
            {
                "sku": quote.sku,
                "qty": quote.qty,
                "unit_price": quote.unit_price,
                "total": quote.total,
                "incoterm": quote.incoterm,
            }
            if quote is not None
            else None
        ),
        "compliance": (
            {"result": verdict.result, "score": verdict.score} if verdict else None
        ),
        "strategy": strategy.model_dump() if strategy else None,
        "memory_summary": memory.block if memory else "",
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请给出决策：\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        },
    ]
