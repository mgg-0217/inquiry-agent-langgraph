"""回复生成 prompt（PRD F7）。"""

from __future__ import annotations

from app.graph.state import AgentState

SYSTEM_PROMPT = """你是外贸工业品公司的销售，负责写一封英文回复。

硬规则：
- 所有价格、总价、交期、有效期只能引用下面给出的 facts，禁止自行计算或修改
- 不要在回复里出现成本线（floor price）或内部利润信息
- 提及历史只有 allowed_history 为 true 时才可以，否则禁止装熟
- 不要编造客户没说过的话
- 语气专业、简洁，5~10 句
- 直接输出邮件正文，不要加 "Subject:" 或主题行

如果客户在还价（is_negotiation 为 true），只回应价格与理由，不要重复完整产品规格。
"""


def build_compose_messages(state: AgentState) -> list[dict]:
    mail = state["mail"]
    quote = state.get("quote")
    inventory = state.get("inventory")
    strategy = state.get("strategy")
    memory = state.get("memory")

    facts = {}
    if quote is not None:
        facts = {
            "sku": quote.sku,
            "qty": quote.qty,
            "unit_price": quote.unit_price,
            "total": quote.total,
            "currency": quote.currency,
            "incoterm": quote.incoterm,
            "destination": quote.destination,
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "floor_price_do_not_mention": quote.floor_price,
        }
    lead_time = inventory.lead_time if inventory is not None else None
    history_allowed = bool(strategy and strategy.mention_history)

    payload = {
        "customer_email": mail.from_email,
        "customer_name": mail.from_name,
        "inquiry_subject": mail.subject,
        "inquiry_body": mail.body_text,
        "facts": facts,
        "lead_time": lead_time,
        "strategy": {
            "stance": strategy.stance if strategy else None,
            "key_points": strategy.key_points if strategy else [],
            "price_adjustment": strategy.price_adjustment if strategy else None,
        },
        "allowed_history": history_allowed,
        "memory_block": memory.block if (memory is not None and history_allowed) else "",
        "is_negotiation": mail.is_price_negotiation,
        "round": state.get("round", 1),
        # 审批人「修改后重写」时带上反馈
        "review_comment": (
            state["approval"].comment if state.get("approval") is not None else ""
        ),
    }

    import json

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请根据以下信息写回复：\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2),
        },
    ]


def build_rewrite_messages(original: list[dict], reply: str, feedback: str) -> list[dict]:
    return [
        *original,
        {"role": "assistant", "content": reply},
        {
            "role": "user",
            "content": (
                "上面的回复有事实错误："
                f"{feedback}。\n请重写，所有数字必须来自 facts，不要新增或修改任何数字。"
            ),
        },
    ]
