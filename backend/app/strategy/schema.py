"""策略判断的输入输出契约（PRD 7.8.2 Layer 1）。

`ReplyStrategy` 是模型输出的唯一形状：`Literal` 把可选空间压死，
模型不能发明代码里没有的选项。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReplyStrategy(BaseModel):
    stance: Literal["re_engage", "standard", "defensive", "escalate"] = Field(
        default="standard",
        description="re_engage=老客户再激活, standard=常规, defensive=防风险, escalate=升级人工",
    )
    mention_history: bool = Field(
        default=False,
        description="是否在回复中提及历史沟通（新客户必须为 false）",
    )
    price_adjustment: Literal["none", "match_target", "volume_tier"] = Field(
        default="none",
        description="none=不调整, match_target=对齐客户目标价, volume_tier=按数量进阶梯价",
    )
    key_points: list[str] = Field(
        default_factory=list, description="回复中必须覆盖的 3—5 个要点"
    )
    rationale: str = Field(default="", description="一句话说明为什么这样判断，用于审计")


class StrategyContext(BaseModel):
    """喂给策略模型的三样输入：本次询盘、记忆块、算价结果快照。

    刻意不直接持有 `Quote` 对象：strategy 层要能脱离图/数据库单独测试。
    """

    inquiry: str = ""
    memory_block: str = ""
    is_new_customer: bool = True
    lost_reason: str | None = None
    target_price: float | None = None
    round: int = 1
    quote: dict = Field(default_factory=dict)
