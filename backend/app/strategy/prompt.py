"""策略判断的 prompt（PRD 7.8.3 Layer 2）。

这一层是「原则」不是「分支」：写清什么时候倾向哪个，但不在 prompt 里替模型做决定。
"""

from __future__ import annotations

import json

from app.strategy.schema import StrategyContext

SYSTEM_PROMPT = """你是外贸工业品公司的资深销售策略顾问。你的任务不是写邮件，而是判断"这一单该用什么姿态回复"。

请综合以下输入做判断：
- 本次询盘内容（产品、数量、条款、客户诉求）
- 客户记忆档案（历史目标价、流失原因、偏好、未闭环报价）
- 本次算价结果（档位表、适用单价、总价、成本线、目标价匹配值）
- 当前是第几轮沟通

判断原则（原则不是分支，请自己权衡）：
1. 上次因价格流失，本次价格已满足其目标价 → re_engage，主动点明"价格已到位"。
2. 上次因价格流失，本次价格仍高于目标价 → defensive，说明成本构成，不硬降。
3. 上次为 no_response（客户未回复）→ 不得假设价格原因，主动询问上次顾虑。
4. 新客户（无历史）→ standard，mention_history 必须为 false。
5. 客户要求账期时，如果无法判断其资信（本版未接入资信系统），倾向 escalate，不要自行承诺账期。
6. 任何情况下不得建议低于 floor_price 的价格。
7. 议价轮（round ≥ 2 且客户在还价）→ 只给建议价与理由，最终由人决定（可倾向 escalate）。

输出约束：
- stance 只能是 re_engage / standard / defensive / escalate
- price_adjustment 只能是 none / match_target / volume_tier
- key_points 给 3—5 条，必须覆盖报价、交期、有效期等关键事实
- rationale 用一句话说明为什么，便于审计
"""


def build_messages(context: StrategyContext) -> list[dict]:
    """拼 messages。quote 只给必要字段，不给成本明细（信息隔离即约束）。"""
    quote = {
        k: context.quote.get(k)
        for k in (
            "sku",
            "qty",
            "incoterm",
            "destination",
            "unit_price",
            "total",
            "floor_price",
            "target_matched_price",
            "valid_until",
            "tiers",
        )
    }
    user_payload = {
        "inquiry": context.inquiry,
        "memory": context.memory_block or "（无历史记忆，按新客户处理）",
        "is_new_customer": context.is_new_customer,
        "lost_reason": context.lost_reason,
        "target_price": context.target_price,
        "round": context.round,
        "quote": quote,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请输出 ReplyStrategy。\n\n输入：\n"
            + json.dumps(user_payload, ensure_ascii=False, indent=2),
        },
    ]
