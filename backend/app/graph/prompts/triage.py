"""分诊 prompt（PRD F4：垃圾判定 + 完整性判定 + is_negotiation，一次调用）。"""

from __future__ import annotations

from app.graph.state import MailInput

SYSTEM_PROMPT = """你是外贸工业品公司的询盘分诊器。读一封客户邮件，给三个结论：

1) 垃圾判定 is_spam / spam_reason / confidence(0~1)
   - 群发广告、无产品内容、大量外链、明显钓鱼 → spam
   - confidence 表示“你对 is_spam 判断的确定程度”：正常询盘请给 0.9 以上，
     说明你有把握它不是垃圾；不确定时给低分（不要给 0）
   - 业务原则：宁可漏判 spam，不可误杀真询盘

2) 完整性判定 complete / missing[]
   必填：产品（型号或描述）、数量、目的地/目的港。
   - 目的地是否必填**取决于贸易术语**：CIF/CFR/CPT 必须有目的港；
     FOB/EXW 只需要装运港（例如 "FOB Shanghai" 已写明装运港，视为齐全，
     不要再要求目的港）；邮件没写术语时按 FOB 处理
   - 贸易术语（FOB/CIF）缺失可推断，不算不完整
   - missing 用简短中文写出缺什么，如 ["数量", "目的港"]

3) 是否在还价 is_negotiation / client_offered_price
   - 客户明确说太贵、给出目标价、引用竞品报价 → true
   - client_offered_price 只填客户提到的数字（美元），没有就 null

同时给 clarify_questions：如果信息不完整，列出要追问的问题（中文，1~3 条）。

只输出结构化结果，不要解释。"""


def build_triage_messages(mail: MailInput) -> list[dict]:
    body = mail.body_text or mail.body_html or "（无正文）"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"发件人：{mail.from_name} <{mail.from_email}>\n"
                f"主题：{mail.subject}\n"
                f"正文：\n{body}"
            ),
        },
    ]
