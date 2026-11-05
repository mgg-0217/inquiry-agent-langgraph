"""记忆抽取的输出契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# PRD F3.6 的 20 个 key（模型只能从这里选）
FACT_KEYS: set[str] = {
    "contact_name",
    "decision_maker",
    "language",
    "timezone",
    "preferred_incoterm",
    "preferred_dest_port",
    "payment_terms",
    "currency",
    "packaging_req",
    "certification_req",
    "voltage_spec",
    "frequency_spec",
    "target_price",
    "historic_price",
    "lost_reason",
    "bargain_style",
    "payment_punctuality",
    "pending_quote",
    "last_contact",
    "lifecycle_stage",
}

# 价格类事实必须带有效期（PRD F3.6）
PRICE_VALID_DAYS: dict[str, int] = {
    "target_price": 180,
    "historic_price": 90,
    "pending_quote": 30,
}

PRICE_KEYS: set[str] = set(PRICE_VALID_DAYS)


class ExtractedFact(BaseModel):
    key: str = Field(description="fact key，必须来自给定清单")
    value: str = Field(description="结论值")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    evidence: str = Field(default="", description="客户原话片段，必须逐字出现在邮件正文中")


class ExtractedMemory(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)
    summary: str = Field(default="", description="本次交互的一句话摘要")
    outcome: Literal["replied", "lost", "open", "unknown"] = "unknown"
    lost_reason: Literal[
        "price_high", "lead_time", "no_response", "quality", "unknown"
    ] | None = None
    evidence: str = Field(default="", description="最能代表本次交互的客户原话")
