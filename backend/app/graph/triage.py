"""分诊：L1 规则预过滤 + L2 LLM 判定（PRD F4）。

业务权衡：**宁可漏判 spam，不可误杀真询盘**。
- 规则层只拦“极确定”的邮件
- LLM 判 spam 也只在 confidence ≥ 0.85 时才自动归档（阈值在 edges 里）
- LLM 失败时放行但标记 need_review
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from app.graph.prompts.triage import build_triage_messages
from app.graph.state import MailInput, Triage
from app.llm.structured import structured_output

logger = logging.getLogger(__name__)

# 演示用的虚构黑名单域名（真实名单不在这里）
BLACKLIST_DOMAINS = {"spam-xyz.example", "bulk-mail.example"}
LINK_RE = re.compile(r"https?://", re.IGNORECASE)
MAX_LINKS = 10


class PrefilterResult(BaseModel):
    is_spam: bool = True
    spam_reason: str = ""
    confidence: float = 0.99


def rule_prefilter(mail: MailInput) -> PrefilterResult | None:
    """L1：只做极确定的拦截。"""
    body = mail.body_text or mail.body_html or ""
    domain = mail.from_email.split("@", 1)[-1].lower() if "@" in mail.from_email else ""

    if not body.strip():
        return PrefilterResult(is_spam=True, spam_reason="无正文", confidence=0.99)
    if domain in BLACKLIST_DOMAINS:
        return PrefilterResult(
            is_spam=True, spam_reason=f"黑名单域名 {domain}", confidence=0.99
        )
    links = LINK_RE.findall(body)
    if len(links) > MAX_LINKS:
        return PrefilterResult(
            is_spam=True, spam_reason=f"外链 {len(links)} 个", confidence=0.95
        )
    return None


def triage_mail(llm, mail: MailInput) -> Triage:
    """返回 Triage。规则命中不再调 LLM；LLM 失败保守放行并标记复核。"""
    pre = rule_prefilter(mail)
    if pre is not None:
        return Triage(
            is_spam=pre.is_spam,
            spam_reason=pre.spam_reason,
            confidence=pre.confidence,
            complete=True,
        )

    try:
        structured = structured_output(llm, Triage)
        raw = structured.invoke(build_triage_messages(mail))
        result = raw if isinstance(raw, Triage) else Triage.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("分诊 LLM 失败，保守放行并标记复核：%s", exc)
        return Triage(
            is_spam=False,
            confidence=0.0,
            complete=True,
            need_review=True,
            spam_reason=f"分诊失败：{exc}",
        )

    # 模型自己也可能给出低置信度：标记复核，但不自动归档
    if result.is_spam and result.confidence < 0.6:
        result.need_review = True
    return result
