"""用真实 DeepSeek 验证策略判断（第 3 天的"决定性"检查）。

这条不是必过测试：模型输出受服务端影响，可能偶发不稳定。
它用来证明 **prompt + 结构化输出 + guard 这条链路在真模型上是通的**。

用法：
    python backend/scripts/demo_strategy_live.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from langchain_openai import ChatOpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.graph.state import Quote  # noqa: E402
from app.strategy.node import assess_and_guard  # noqa: E402
from app.strategy.resolve import resolve_price  # noqa: E402
from app.strategy.schema import StrategyContext  # noqa: E402


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
    )


def print_strategy(title: str, strategy, quote: Quote) -> None:
    print(f"\n{title}")
    print(f"  stance           : {strategy.stance}")
    print(f"  mention_history  : {strategy.mention_history}")
    print(f"  price_adjustment : {strategy.price_adjustment}")
    print(f"  final_price      : USD {resolve_price(strategy, quote)}（floor {quote.floor_price}）")
    print(f"  key_points       : {strategy.key_points}")
    print(f"  rationale        : {strategy.rationale}")


def main() -> int:
    if not settings.llm_api_key:
        print("未配置 LLM_API_KEY，跳过")
        return 0

    llm = make_llm()

    # 场景 1：老客户，上次因价格流失，本次目标价达标（300 台 × $350 = $105,000，未超授权）
    quote = Quote(
        sku="X200",
        qty=300,
        unit_price=350.0,
        floor_price=338.0,
        target_matched_price=350.0,
        total=105000.0,
        incoterm="CIF",
        destination="Valencia",
        valid_until=date.today() + timedelta(days=7),
    )
    context = StrategyContext(
        inquiry="We need 300 units of X200, 380V/50Hz, CIF Valencia.",
        memory_block=(
            "- target_price=350（证据：Competitor offers USD 350）\n"
            "- lost_reason=price_high（证据：USD 364 is above our budget）"
        ),
        is_new_customer=False,
        lost_reason="price_high",
        target_price=350.0,
        round=2,
        quote=quote.model_dump(mode="json"),
    )
    strategy = assess_and_guard(llm, context, quote, {"is_new": False})
    print_strategy("场景 1：老客户 · 目标价达标（期望 re_engage + 提历史）", strategy, quote)

    # 场景 2：新客户
    quote2 = Quote(
        sku="X200",
        qty=120,
        unit_price=364.0,
        floor_price=338.0,
        total=43680.0,
        incoterm="CIF",
        destination="Hamburg",
        valid_until=date.today() + timedelta(days=7),
    )
    context2 = StrategyContext(
        inquiry="Please quote 120 units of X200, CIF Hamburg.",
        memory_block="",
        is_new_customer=True,
        round=1,
        quote=quote2.model_dump(mode="json"),
    )
    strategy2 = assess_and_guard(llm, context2, quote2, {"is_new": True})
    print_strategy("场景 2：新客户（期望 standard + 不提历史）", strategy2, quote2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
