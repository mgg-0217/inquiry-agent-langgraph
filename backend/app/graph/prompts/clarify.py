"""追问 prompt（PRD：信息不全时生成追问，发出后本轮 END）。"""

from __future__ import annotations

from app.graph.state import MailInput, Triage

SYSTEM_PROMPT = """你是外贸销售助理。客户的询盘信息不完整，请写一封简短的英文追问邮件。

要求：
- 只问缺失的信息，不要报价、不要编造价格或交期
- 语气礼貌、专业，3~5 句话
- 直接给出邮件正文，不要加主题行、不要加“Subject:”
- 可以用项目符号列出需要确认的点
"""


def build_clarify_messages(mail: MailInput, triage: Triage) -> list[dict]:
    missing = "、".join(triage.missing) or "关键信息"
    questions = "\n".join(f"- {q}" for q in triage.clarify_questions) or "- 请补充具体需求"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"客户邮件主题：{mail.subject}\n"
                f"客户正文：\n{mail.body_text or mail.body_html}\n\n"
                f"缺失项：{missing}\n"
                f"建议追问：\n{questions}\n\n"
                f"客户联系人：{mail.from_name or mail.from_email}"
            ),
        },
    ]
