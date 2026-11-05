"""追问生成（不报价，只问缺失信息）。"""

from __future__ import annotations

import logging

from app.graph.prompts.clarify import build_clarify_messages
from app.graph.state import MailInput, Triage

logger = logging.getLogger(__name__)


def compose_clarify(llm, mail: MailInput, triage: Triage) -> str:
    try:
        response = llm.invoke(build_clarify_messages(mail, triage))
        text = getattr(response, "content", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("追问生成失败，使用模板兜底：%s", exc)

    return _template_clarify(mail, triage)


def _template_clarify(mail: MailInput, triage: Triage) -> str:
    missing = "、".join(triage.missing) or "关键信息"
    questions = triage.clarify_questions or [f"请补充{missing}"]
    lines = [
        f"Dear {mail.from_name or 'Sir/Madam'},",
        "",
        "Thank you for your inquiry. To prepare an accurate quotation, could you please confirm:",
        "",
    ]
    lines.extend(f"- {q}" for q in questions)
    lines.extend(
        [
            "",
            "We will send the quotation as soon as we receive these details.",
            "",
            "Best regards,",
            "Sales Team",
        ]
    )
    return "\n".join(lines)
