"""事实校验（PRD F7 / F8）。

原则：**事实来自工具，语言来自模型。**
回复里出现的金额、百分比、交期必须能在 facts 里找到出处；
人工改稿后也要再跑一次（PRD 明确：不允许跳过）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MONEY_RES = (
    re.compile(r"\$\s?([\d][\d,]*(?:\.\d+)?)"),
    re.compile(r"(?:USD|US\$)\s?([\d][\d,]*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"([\d][\d,]*(?:\.\d+)?)\s?(?:USD|US\$)", re.IGNORECASE),
)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
DAYS_RE = re.compile(r"(\d+)\s*(?:calendar\s+|working\s+)?days?", re.IGNORECASE)
# 这些百分比是通用表达（如 100% 保证），不需要报价依据
GENERIC_PERCENTS = {100.0, 0.0}


@dataclass
class FactCheckResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    checked_numbers: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        return "；".join(self.violations)


def _to_float(value: str) -> float:
    return float(value.replace(",", ""))


def allowed_facts(facts: dict) -> dict:
    """从 state 里提取允许出现在回复中的数字。"""
    allowed_money: set[float] = set()
    for key in ("unit_price", "total"):
        value = facts.get(key)
        if value is not None:
            allowed_money.add(round(float(value), 2))
    # 阶梯价是工具算出来的合法数字，回复里提"500 台可进 $350 档"不该被拦
    for price in facts.get("tier_prices", []) or []:
        allowed_money.add(round(float(price), 2))
    allowed_days: set[int] = set()
    if facts.get("lead_time_days"):
        allowed_days.add(int(facts["lead_time_days"]))
    if facts.get("valid_days"):
        allowed_days.add(int(facts["valid_days"]))
    return {"money": allowed_money, "days": allowed_days}


def check_reply(reply: str, facts: dict) -> FactCheckResult:
    allowed = allowed_facts(facts)
    violations: list[str] = []
    seen: list[str] = []

    for pattern in MONEY_RES:
        for match in pattern.finditer(reply or ""):
            raw = match.group(1)
            seen.append(raw)
            value = round(_to_float(raw), 2)
            if value not in allowed["money"]:
                violations.append(f"金额 ${value:g} 不在报价单内")

    for match in PERCENT_RE.finditer(reply or ""):
        value = _to_float(match.group(1))
        if value not in GENERIC_PERCENTS:
            violations.append(f"百分比 {value:g}% 没有报价依据")

    for match in DAYS_RE.finditer(reply or ""):
        value = int(match.group(1))
        if allowed["days"] and value not in allowed["days"]:
            violations.append(f"交期 {value} 天与库存/有效期不一致")

    return FactCheckResult(
        ok=not violations, violations=violations, checked_numbers=seen
    )
