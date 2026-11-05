"""记忆抽取 prompt（PRD F3.3 / F3.4 / F3.7）。

原则：只抽“下次询盘还用得上”的结论；每条必须附客户原话；不记一次性信息。
"""

from __future__ import annotations

from app.graph.state import MailInput

SYSTEM_PROMPT = """你负责从一封外贸询盘邮件里抽取**长期记忆**。只记下次询盘还用得上的结论。

可用的 fact key（只能从这些里选）：
contact_name, decision_maker, language, timezone, preferred_incoterm,
preferred_dest_port, payment_terms, currency, packaging_req, certification_req,
voltage_spec, frequency_spec, target_price, historic_price, lost_reason,
bargain_style, payment_punctuality, pending_quote, last_contact, lifecycle_stage

该记：
- 稳定规格：380V/50Hz、CE 认证、DN150
- 稳定偏好：CIF、Valencia、T/T 30/70
- 谈判信息：客户目标价（必须有原话）、上次为什么不成交

不该记：
- 本次数量（500 台）
- 本次交期、本次情绪词（urgent）
- 任何客户没说过的话

硬规则：
- 每条 fact 的 evidence 必须是**正文**里的原话，不要用主题行、发件人或日期
- 客户没明确说的价格，不要生成 target_price
- 如果客户没回复 / 没有价格表述，lost_reason 只能给 no_response 或 null，**不得**猜成 price_high

value 的写法（很重要，后续要拿它做数值比较）：
- 价格类（target_price / historic_price）只填数字，如 "350"；币种写进 currency
- 规格类写标准形式，如 "380V/50Hz"、"DN150"、"CE"
- 不要写整句、不要带解释；解释放在 summary 里
- 不要写客户没说的数字（例如原文只说了 364，就不要写出 350 之外的推断价）

单封邮件不要抽这几类（需要多次交互或人工确认）：
- bargain_style、decision_maker、payment_punctuality

同时给出：
- summary：这次交互一句话摘要（中文）
- outcome：replied / lost / open / unknown
- lost_reason：price_high / lead_time / no_response / quality / unknown / null
- evidence：最能代表这次交互的客户原话（可空）
"""


def build_persist_messages(mail: MailInput) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"发件人：{mail.from_name} <{mail.from_email}>\n"
                f"主题：{mail.subject}\n"
                f"时间：{mail.received_at.isoformat()}\n"
                f"正文：\n{mail.body_text or mail.body_html}"
            ),
        },
    ]
