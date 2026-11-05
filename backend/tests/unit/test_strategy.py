from __future__ import annotations

from app.graph.state import Quote
from app.strategy.node import assess_and_guard, assess_strategy
from app.strategy.prompt import build_messages
from app.strategy.resolve import guard, resolve_price
from app.strategy.schema import ReplyStrategy, StrategyContext


class _Structured:
    """模拟 with_structured_output 返回的 runnable。"""

    def __init__(self, outputs: list):
        self.outputs = outputs
        self.calls = 0

    def invoke(self, messages):
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        if isinstance(out, Exception):
            raise out
        return out


class ScriptedLLM:
    def __init__(self, outputs: list):
        self.outputs = outputs

    def with_structured_output(self, schema, method=None):
        assert schema is ReplyStrategy
        assert method == "function_calling"
        return _Structured(self.outputs)


def make_quote(
    *,
    unit_price: float = 350.0,
    qty: int = 300,
    floor_price: float = 338.0,
    target_matched_price: float | None = None,
    total: float | None = None,
) -> Quote:
    return Quote(
        sku="X200",
        qty=qty,
        unit_price=unit_price,
        floor_price=floor_price,
        target_matched_price=target_matched_price,
        total=total if total is not None else round(unit_price * qty, 2),
        currency="USD",
        incoterm="CIF",
        destination="Valencia",
    )


def make_context(**kwargs) -> StrategyContext:
    data = dict(
        inquiry="We need 300 units of X200, CIF Valencia.",
        memory_block="",
        is_new_customer=True,
        quote={"unit_price": 350.0, "total": 105000.0, "floor_price": 338.0},
    )
    data.update(kwargs)
    return StrategyContext(**data)


# ---------------------------------------------------------------- 三个必过用例


def test_case1_returning_customer_target_reached():
    """老客户 + 目标价达标 → re_engage，且允许提历史。"""
    context = make_context(
        memory_block=(
            "- target_price=350（证据：Competitor offers USD 350）\n"
            "- lost_reason=price_high（证据：above our budget）"
        ),
        is_new_customer=False,
        lost_reason="price_high",
        target_price=350.0,
        round=2,
    )
    quote = make_quote(unit_price=350.0, qty=300, target_matched_price=350.0)
    llm = ScriptedLLM(
        [
            ReplyStrategy(
                stance="re_engage",
                mention_history=True,
                price_adjustment="match_target",
                key_points=["matches your target price", "CIF Valencia", "valid 7 days"],
                rationale="上次因价格流失，本次已对齐目标价",
            )
        ]
    )

    strategy = assess_and_guard(llm, context, quote, {"is_new": False})

    assert strategy.stance == "re_engage"
    assert strategy.mention_history is True
    assert strategy.price_adjustment == "match_target"
    assert resolve_price(strategy, quote) == 350.0


def test_case2_new_customer_cannot_mention_history():
    """新客户：模型想装熟也会被 guard 强制修正。"""
    context = make_context(is_new_customer=True, memory_block="")
    quote = make_quote(unit_price=364.0, qty=120)
    llm = ScriptedLLM(
        [
            ReplyStrategy(
                stance="standard",
                mention_history=True,  # 模型犯错：新客户却想提历史
                price_adjustment="none",
                key_points=["price", "lead time", "validity"],
                rationale="常规报价",
            )
        ]
    )

    strategy = assess_and_guard(llm, context, quote, {"is_new": True})

    assert strategy.mention_history is False
    assert "新客户禁止提及历史" in strategy.rationale


def test_case3_price_below_floor_forces_escalate():
    """算价 330 < 成本线 338 → 强制 escalate。"""
    context = make_context(is_new_customer=False)
    quote = make_quote(unit_price=330.0, qty=100, floor_price=338.0)
    llm = ScriptedLLM(
        [
            ReplyStrategy(
                stance="standard",
                mention_history=False,
                price_adjustment="none",
                key_points=["price"],
                rationale="常规报价",
            )
        ]
    )

    strategy = assess_and_guard(llm, context, quote, {"is_new": False})

    assert strategy.stance == "escalate"
    assert "触达成本线" in strategy.rationale


# ---------------------------------------------------------------- Layer 3 细节


def test_resolve_price_uses_applicable_for_none():
    quote = make_quote(unit_price=364.0, qty=120, target_matched_price=350.0)
    strategy = ReplyStrategy(price_adjustment="none")
    assert resolve_price(strategy, quote) == 364.0


def test_resolve_price_uses_target_for_match_target():
    quote = make_quote(unit_price=364.0, qty=120, target_matched_price=350.0)
    strategy = ReplyStrategy(price_adjustment="match_target")
    assert resolve_price(strategy, quote) == 350.0


def test_match_target_without_target_escalates():
    quote = make_quote(unit_price=364.0, qty=120, target_matched_price=None)
    strategy = ReplyStrategy(price_adjustment="match_target")
    guarded = guard(strategy, quote, {"is_new": False})
    assert guarded.stance == "escalate"
    assert "无法对齐" in guarded.rationale


def test_over_authorization_limit_escalates():
    quote = make_quote(unit_price=350.0, qty=500)  # total = 175000 > 150000
    strategy = ReplyStrategy(stance="standard", price_adjustment="none")
    guarded = guard(strategy, quote, {"is_new": False})
    assert guarded.stance == "escalate"
    assert "超授权额度" in guarded.rationale


def test_guard_does_not_mutate_input():
    quote = make_quote(unit_price=330.0, floor_price=338.0)
    original = ReplyStrategy(stance="standard", rationale="原本")
    guard(original, quote, {"is_new": True})
    assert original.stance == "standard"
    assert original.rationale == "原本"


def test_guard_is_idempotent_when_run_twice():
    """审批改稿后会再跑一次 fact_check/guard，审计说明不能重复堆叠。"""
    quote = make_quote(unit_price=330.0, floor_price=338.0)
    strategy = ReplyStrategy(stance="standard", rationale="原本")
    once = guard(strategy, quote, {"is_new": True})
    twice = guard(once, quote, {"is_new": True})
    assert twice.stance == "escalate"
    assert twice.rationale.count("触达成本线") == 1


# ---------------------------------------------------------------- 调用封装与兜底


def test_assess_retries_once_then_succeeds():
    llm = ScriptedLLM(
        [
            RuntimeError("timeout"),
            ReplyStrategy(stance="standard", key_points=["ok"], rationale="第二次成功"),
        ]
    )
    strategy = assess_strategy(llm, make_context(), retries=1)
    assert strategy.rationale == "第二次成功"


def test_assess_falls_back_to_escalate_after_failures():
    llm = ScriptedLLM([RuntimeError("boom"), RuntimeError("boom again")])
    strategy = assess_strategy(llm, make_context(), retries=1)
    assert strategy.stance == "escalate"
    assert "兜底转人工" in strategy.rationale
    assert strategy.mention_history is False


def test_prompt_contains_memory_and_price_but_not_cost_breakdown():
    context = make_context(
        memory_block="target_price=350",
        quote={
            "unit_price": 350.0,
            "total": 105000.0,
            "floor_price": 338.0,
            "breakdown": {"cost": 300.0},
        },
    )
    messages = build_messages(context)
    text = "\n".join(m["content"] for m in messages)
    assert "target_price=350" in text
    assert "floor_price" in text
    assert "breakdown" not in text
