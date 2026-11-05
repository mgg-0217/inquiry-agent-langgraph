"""采购需求抽取 prompt（draft_plan 第一步）。"""

from __future__ import annotations

from app.graph.state import MailInput

SYSTEM_PROMPT = """从这封外贸询盘里抽取结构化采购需求。只抽邮件明确写出的内容，不要猜。

- sku：产品型号（如 X200 / Y300 / Z400）
- product_keyword：没有型号时给产品关键词（如 centrifugal pump / valve）
- quantity：数量（整数），没写就 null
- incoterm：FOB / CFR / CIF，没写就 null
- destination：目的港/目的地，没写就 null

注意：只输出结构化结果。"""


def build_inquiry_messages(mail: MailInput) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"主题：{mail.subject}\n正文：\n{mail.body_text or mail.body_html}",
        },
    ]
