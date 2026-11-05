"""报价规划（PRD 7.2 节点 6 / F5 / 7.8）。

流程：
1. 从邮件抽结构化采购需求（InquirySpec）
2. 真实模型可用时先跑一轮 ReAct（模型自主调 search_product / check_inventory / calc_price）
3. 但**最终报价一律由代码调用 `calc_price` 重新生成**，只信工具返回值（硬约束 B）
4. 策略判断走 `assess_and_guard`（模型判断 + guard 硬规则）

这样既有 Agent 的工具自主性，又保证数字可审计、可复现。
"""

from __future__ import annotations

import json
import logging
from datetime import date

from app.graph.prompts.inquiry import build_inquiry_messages
from app.graph.state import (
    Inventory,
    InquirySpec,
    MailInput,
    MemoryContext,
    PriceTier,
    Product,
    Quote,
    ReplyStrategy,
)
from app.llm.structured import structured_output
from app.strategy.node import assess_and_guard
from app.strategy.schema import StrategyContext
from app.tools.pricing import calc_price
from app.tools.product import check_inventory, search_product
from app.tools.registry import build_read_tools

logger = logging.getLogger(__name__)

REACT_PROMPT = """你是外贸销售助理。先查产品、查库存、算价，再回答。
规则：
- 价格只能来自 calc_price 的返回值，不得自己计算
- 如果客户给了目标价，把它传给 calc_price 的 target_price
- 信息不足时如实说明，不要编造
"""


def extract_inquiry_spec(llm, mail: MailInput) -> InquirySpec | None:
    try:
        raw = structured_output(llm, InquirySpec).invoke(build_inquiry_messages(mail))
        return raw if isinstance(raw, InquirySpec) else InquirySpec.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("采购需求抽取失败：%s", exc)
        return None


def target_price_from_memory(memory: MemoryContext | None) -> float | None:
    if memory is None:
        return None
    for fact in memory.facts:
        if fact.key == "target_price":
            try:
                return float(str(fact.value).replace(",", "").strip())
            except (TypeError, ValueError):
                return None
    return None


def quote_from_data(data: dict) -> Quote:
    return Quote(
        sku=data["sku"],
        qty=int(data["qty"]),
        tiers=[
            PriceTier(
                min_qty=int(t["min_qty"]),
                max_qty=t.get("max_qty"),
                unit_price=float(t["unit_price"]),
            )
            for t in data["tiers"]
        ],
        unit_price=float(data["applicable"]["unit_price"]),
        floor_price=float(data["floor_price"]),
        target_matched_price=data.get("target_matched_price"),
        total=float(data["applicable"]["total"]),
        currency=data.get("currency", "USD"),
        freight=float(data.get("freight", 0.0)),
        insurance=float(data.get("insurance", 0.0)),
        incoterm=data.get("incoterm", "FOB"),
        destination=data.get("destination", ""),
        valid_until=date.fromisoformat(data["valid_until"]) if data.get("valid_until") else None,
    )


def run_react(llm, mail: MailInput) -> list[dict]:
    """真实模型可用时跑一轮工具循环；返回每次调用的参数/结果。"""
    if not hasattr(llm, "bind_tools"):
        return []
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    tools = build_read_tools()
    tool_map = {tool.name: tool for tool in tools}
    messages = [
        SystemMessage(content=REACT_PROMPT),
        HumanMessage(
            content=f"主题：{mail.subject}\n正文：\n{mail.body_text or mail.body_html}"
        ),
    ]
    calls: list[dict] = []
    try:
        bound = llm.bind_tools(tools)
        for _ in range(6):
            ai = bound.invoke(messages)
            messages.append(ai)
            tool_calls = getattr(ai, "tool_calls", None) or []
            if not tool_calls:
                break
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args") or {}
                tool = tool_map.get(name)
                result = tool.invoke(args) if tool else {"ok": False, "code": "UNKNOWN_TOOL"}
                calls.append({"tool": name, "args": args, "result": result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False, default=str),
                        tool_call_id=call.get("id", ""),
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ReAct 工具循环失败，走确定性兜底：%s", exc)
    return calls


def build_quote(
    spec: InquirySpec,
    target_price: float | None,
    *,
    fallback_calc: dict | None = None,
) -> tuple[Quote | None, list[Product], Inventory | None, str]:
    """确定性算价：search → inventory → calc_price。返回 (quote, products, inventory, summary)。"""
    quantity = spec.quantity
    if not quantity or quantity <= 0:
        return None, [], None, "缺少有效数量"

    sku = (spec.sku or "").strip().upper()
    products: list[Product] = []
    searched = search_product(sku or (spec.product_keyword or ""))
    if not searched["ok"]:
        return None, [], None, "没有匹配到产品"
    products = [
        Product(
            sku=c["sku"],
            name=c.get("name", ""),
            specs=c.get("specs", {}),
            moq=int(c.get("moq", 1)),
        )
        for c in searched["data"]["candidates"]
    ]
    if not sku:
        sku = products[0].sku if products else ""
    if not sku:
        return None, [], None, "没有匹配到产品"

    inventory: Inventory | None = None
    inv = check_inventory(sku, quantity)
    if inv["ok"]:
        inventory = Inventory(
            available=bool(inv["data"]["available"]),
            lead_time=str(inv["data"]["lead_time"]),
            can_expedite=bool(inv["data"]["can_expedite"]),
        )

    # 模型在 ReAct 里可能自己算过价；只有 SKU 和数量都对得上才采用，否则重算
    if (
        fallback_calc
        and fallback_calc.get("sku") == sku
        and int(fallback_calc.get("qty") or -1) == quantity
    ):
        return quote_from_data(fallback_calc), products, inventory, "采用 ReAct 算价结果"

    priced = calc_price(sku, quantity, spec.incoterm, spec.destination or "", target_price)
    if not priced["ok"]:
        return None, products, inventory, f"算价失败：{priced['message']}"
    return quote_from_data(priced["data"]), products, inventory, "代码算价"


def build_strategy(
    llm,
    mail: MailInput,
    memory: MemoryContext | None,
    quote: Quote,
    customer: dict,
    round_no: int,
) -> ReplyStrategy:
    lost_reason = next(
        (i.lost_reason for i in (memory.recent if memory else []) if i.lost_reason), None
    )
    context = StrategyContext(
        inquiry=f"{mail.subject}\n{mail.body_text}",
        memory_block=memory.block if memory else "",
        is_new_customer=bool(customer.get("is_new", True)),
        lost_reason=lost_reason,
        target_price=target_price_from_memory(memory),
        round=round_no,
        quote=quote.model_dump(mode="json"),
    )
    return assess_and_guard(llm, context, quote, customer)
