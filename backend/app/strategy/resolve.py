"""Layer 3：结果校验（PRD 7.8.4）。

**红线由代码说了算**：模型可以判断策略，但最终价格与几条硬规则由这里决定。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import Settings, settings as default_settings
from app.strategy.schema import ReplyStrategy

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from app.graph.state import Quote


def resolve_price(strategy: ReplyStrategy, quote: "Quote") -> float:
    """根据模型的选档结果确定最终报价单价。

    - match_target：用工具预计算的 target_matched_price（工具已保证 ≥ floor）
    - none / volume_tier：按本次实际数量报 applicable
      （volume_tier 的差异体现在邮件里"额外告知更高档位价格"，不改变本次报价）
    """
    if strategy.price_adjustment == "match_target":
        if quote.target_matched_price is not None:
            return float(quote.target_matched_price)
        # 目标价低于成本线时工具返回 null；这里退回适用价，由 guard 升级人工
    return float(quote.unit_price)


def _append_note(strategy: ReplyStrategy, note: str) -> None:
    """幂等追加审计说明：同一策略重复过 guard（如审批改稿后重校验）不会重复拼接。"""
    if note not in strategy.rationale:
        strategy.rationale += note


def guard(
    strategy: ReplyStrategy,
    quote: "Quote",
    customer: dict | None,
    settings: Settings | None = None,
) -> ReplyStrategy:
    """硬规则校验，返回修正后的策略（不修改入参）。"""
    cfg = settings or default_settings
    result = strategy.model_copy(deep=True)
    customer = customer or {}

    # 硬规则 0：选了 match_target 但工具给不出目标价 → 必须升级
    if result.price_adjustment == "match_target" and quote.target_matched_price is None:
        result.stance = "escalate"
        _append_note(result, "（目标价低于成本线，无法对齐，强制升级）")

    # 硬规则 1：最终采用价不得低于成本线（校验最终价，不是 applicable）
    final_price = resolve_price(result, quote)
    if final_price < quote.floor_price:
        result.stance = "escalate"
        _append_note(result, "（触达成本线，强制升级）")

    # 硬规则 2：新客户禁止提历史
    is_new = bool(customer.get("is_new", True))
    if is_new and result.mention_history:
        result.mention_history = False
        _append_note(result, "（新客户禁止提及历史，已修正）")

    # 硬规则 3：超授权必须审批（额度是全局配置，不是按客户设置）
    if quote.total > cfg.auto_reply_limit:
        result.stance = "escalate"
        _append_note(result, "（超授权额度，强制升级）")

    return result
