from __future__ import annotations

from app.graph.fact_check import check_reply

FACTS = {
    "unit_price": 350.0,
    "total": 175000.0,
    "lead_time_days": 35,
    "valid_days": 7,
}


def test_matching_numbers_pass():
    reply = (
        "Dear Carlos, our price is USD 350 per unit, total USD 175,000, "
        "CIF Valencia. Lead time is 35 days and the offer is valid for 7 days."
    )
    result = check_reply(reply, FACTS)
    assert result.ok is True
    assert result.violations == []


def test_tampered_price_is_caught():
    reply = "Our best price is USD 305 per unit, total USD 152,500."
    result = check_reply(reply, FACTS)
    assert result.ok is False
    assert any("305" in v for v in result.violations)


def test_floor_price_leak_is_caught():
    """成本线不该出现在回复里，出现即视为事实错误。"""
    reply = "Our cost is USD 338, we quote USD 350."
    result = check_reply(reply, FACTS)
    assert result.ok is False
    assert any("338" in v for v in result.violations)


def test_wrong_lead_time_is_caught():
    reply = "USD 350 per unit, total USD 175,000, lead time 20 days."
    result = check_reply(reply, FACTS)
    assert result.ok is False
    assert any("20" in v for v in result.violations)


def test_unknown_percentage_is_caught():
    reply = "USD 350 per unit, we can offer 15% discount."
    result = check_reply(reply, FACTS)
    assert result.ok is False
    assert any("15" in v for v in result.violations)


def test_generic_percentage_is_allowed():
    reply = "USD 350 per unit, 100% new and original."
    result = check_reply(reply, FACTS)
    assert result.ok is True


def test_plain_dollar_format_without_usd_word():
    reply = "Price: $350/unit, total $175,000."
    assert check_reply(reply, FACTS).ok is True


def test_empty_reply_has_no_violations_but_is_still_suspicious():
    result = check_reply("", FACTS)
    assert result.ok is True  # 空文本没有数字冲突，空回复由上层判断


def test_number_before_currency_is_caught():
    """漏检过的格式：305 USD / 152500 USD。"""
    result = check_reply("Our price is 305 USD per unit, total 152500 USD.", FACTS)
    assert result.ok is False
    assert any("305" in v for v in result.violations)


def test_tier_prices_are_allowed():
    """阶梯价是工具算出来的合法数字，提"500 台可进 $350 档"不该被拦。"""
    facts = dict(FACTS, tier_prices=[380.0, 364.0, 350.0])
    reply = "For 100-499 units it is USD 364; at 500+ it drops to USD 350."
    assert check_reply(reply, facts).ok is True


def test_non_tier_price_is_still_caught():
    facts = dict(FACTS, tier_prices=[380.0, 364.0, 350.0])
    reply = "We can do USD 340 for you."
    assert check_reply(reply, facts).ok is False
