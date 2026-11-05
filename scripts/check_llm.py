"""
LLM 连通性与能力验证脚本（支持任意 OpenAI 兼容服务）

用法：
    python scripts/check_llm.py

前置：backend/.env 里配好
    LLM_BASE_URL=...
    LLM_MODEL=...
    LLM_API_KEY=...

本脚本测三项能力，全部通过才能用于本项目：
    1. 基础对话        —— 网络与鉴权是否正常
    2. Function Calling —— Agent 的 8 个工具全靠它，不支持就没法做 Agent
    3. 结构化输出       —— 策略判断用 with_structured_output，不稳定会频繁解析失败

如果第 2 或第 3 项失败，建议换回 DeepSeek（本项目默认）。
"""

import os
import sys
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class ReplyStrategy(BaseModel):
    """模拟项目里的策略输出结构"""
    stance: Literal["re_engage", "standard", "defensive", "escalate"] = Field(
        description="回复策略"
    )
    mention_history: bool = Field(description="是否提及历史沟通")
    rationale: str = Field(description="判断理由")


CALC_PRICE_TOOL = {
    "type": "function",
    "function": {
        "name": "calc_price",
        "description": "计算产品报价，返回单价和总价",
        "parameters": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "产品型号，如 X200"},
                "qty": {"type": "integer", "description": "数量"},
                "incoterm": {
                    "type": "string",
                    "enum": ["FOB", "CIF", "EXW"],
                    "description": "贸易术语",
                },
            },
            "required": ["sku", "qty"],
        },
    },
}


def section(title):
    print(f"\n{'=' * 52}")
    print(title)
    print("=" * 52)


def main() -> int:
    load_dotenv("backend/.env")
    load_dotenv()

    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    api_key = os.getenv("LLM_API_KEY")

    section("配置")
    print(f"BASE_URL : {base_url}")
    print(f"MODEL    : {model}")
    print(f"API_KEY  : {'已配置 (' + api_key[:8] + '...)' if api_key else '缺失'}")

    if not all([base_url, model, api_key]):
        print("\n❌ 配置不完整。请在 backend/.env 里设置：")
        print("   LLM_BASE_URL=https://api.deepseek.com")
        print("   LLM_MODEL=deepseek-chat")
        print("   LLM_API_KEY=sk-xxx")
        return 2

    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        timeout=60,
        max_retries=1,
    )

    passed = 0
    total = 3

    # ---------- 1. 基础对话 ----------
    section("测试 1/3：基础对话")
    try:
        r = llm.invoke("只回复两个字：通了")
        print(f"回复: {r.content!r}")
        print("✅ 通过")
        passed += 1
    except Exception as e:
        print(f"❌ 失败: {type(e).__name__}: {e}")
        print("   → 检查 BASE_URL / MODEL / API_KEY / 网络")

    # ---------- 2. Function Calling ----------
    section("测试 2/3：Function Calling（工具调用）")
    print("⚠️  这是本项目最关键的能力，8 个工具全靠它")
    try:
        r = llm.bind_tools([CALC_PRICE_TOOL]).invoke(
            "帮我算一下型号 X200 的泵，数量 500 台，报 CIF 价"
        )
        if r.tool_calls:
            tc = r.tool_calls[0]
            print(f"工具名: {tc['name']}")
            print(f"参数  : {tc['args']}")
            print("✅ 通过")
            passed += 1
        else:
            print(f"回复内容: {r.content!r}")
            print("❌ 失败：模型没有发起工具调用")
            print("   → 该模型可能不支持 function calling，或支持不稳定")
    except Exception as e:
        print(f"❌ 失败: {type(e).__name__}: {e}")
        print("   → 该模型可能不支持 function calling")

    # ---------- 3. 结构化输出 ----------
    section("测试 3/3：结构化输出（Pydantic）")
    try:
        r = llm.with_structured_output(ReplyStrategy).invoke(
            "客户是老客户，上次因价格未成交，本次算价已满足其目标价。"
            "请输出应答策略。"
        )
        print(f"stance          : {r.stance}")
        print(f"mention_history : {r.mention_history}")
        print(f"rationale       : {r.rationale[:60]}...")
        if r.stance == "re_engage" and r.mention_history:
            print("✅ 通过（判断也合理）")
        else:
            print("✅ 通过（结构正确，但判断结果与预期不同，可接受）")
        passed += 1
    except Exception as e:
        print(f"❌ 失败: {type(e).__name__}: {e}")
        print("   → 结构化输出不稳定，会导致策略节点频繁失败")

    # ---------- 汇总 ----------
    section("结果")
    print(f"通过 {passed}/{total}")
    if passed == total:
        print("✅ 三项全过，可以用于本项目")
        return 0
    if passed >= 2:
        print("⚠️  部分能力不足，建议谨慎使用或换回 DeepSeek")
        return 1
    print("❌ 能力不足，建议换回 DeepSeek")
    return 1


if __name__ == "__main__":
    sys.exit(main())
