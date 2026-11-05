"""
LLM API Key 验证脚本（零依赖，只用 Python 标准库）

用法：
    python scripts/verify_llm_key.py sk-xxxxxxxx
    python scripts/verify_llm_key.py                    # 从 backend/.env 读取

测三项能力，全过才可用于本项目：
    1. 基础对话         —— 网络与鉴权
    2. Function Calling —— Agent 的 8 个工具全靠它
    3. JSON 输出 + temperature=0 一致性 —— 策略判断能否复现

不需要安装任何第三方包。
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request


def load_from_env_file():
    """从 backend/.env 读取配置（不依赖 python-dotenv）"""
    candidates = [
        os.path.join("backend", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "backend", ".env"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        cfg = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
        return cfg.get("LLM_API_KEY"), cfg.get("LLM_BASE_URL", "https://api.deepseek.com"), cfg.get("LLM_MODEL", "deepseek-chat")
    return None, "https://api.deepseek.com", "deepseek-chat"


def main():
    if len(sys.argv) >= 2:
        api_key = sys.argv[1].strip()
        base = sys.argv[2] if len(sys.argv) > 2 else "https://api.deepseek.com"
        model = sys.argv[3] if len(sys.argv) > 3 else "deepseek-chat"
    else:
        api_key, base, model = load_from_env_file()

    if not api_key or not api_key.startswith("sk-"):
        print("❌ 未提供有效 API Key")
        print("   用法: python scripts/verify_llm_key.py sk-xxxxxxxx")
        return 2

    base = base.rstrip("/")
    ctx = ssl.create_default_context()

    def call(payload, timeout=60):
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    print(f"BASE  : {base}")
    print(f"MODEL : {model}")
    print(f"KEY   : {api_key[:8]}...{api_key[-4:]}")
    passed = 0

    # ---- 1. 基础对话 ----
    print("\n" + "=" * 54)
    print("测试 1/3：基础对话")
    print("=" * 54)
    t0 = time.time()
    try:
        d = call({"model": model,
                  "messages": [{"role": "user", "content": "只回复两个字：通了"}],
                  "temperature": 0, "max_tokens": 20})
        print("回复 :", d["choices"][0]["message"]["content"])
        print(f"耗时 : {time.time() - t0:.1f}s")
        print("用量 :", d.get("usage"))
        print("✅ 通过")
        passed += 1
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ HTTP {e.code}: {body[:300]}")
        if e.code == 401:
            print("   → Key 无效：去 platform.deepseek.com 的 API Keys 页面重新生成")
        return 1
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return 1

    # ---- 2. Function Calling ----
    print("\n" + "=" * 54)
    print("测试 2/3：Function Calling（Agent 命脉）")
    print("=" * 54)
    tools = [{
        "type": "function",
        "function": {
            "name": "calc_price",
            "description": "计算产品报价",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "qty": {"type": "integer"},
                    "incoterm": {"type": "string", "enum": ["FOB", "CIF", "EXW"]},
                },
                "required": ["sku", "qty"],
            },
        },
    }]
    try:
        d = call({"model": model,
                  "messages": [{"role": "user", "content": "帮我算 X200 泵 500 台 CIF 价"}],
                  "tools": tools, "temperature": 0})
        msg = d["choices"][0]["message"]
        if msg.get("tool_calls"):
            tc = msg["tool_calls"][0]
            print("工具 :", tc["function"]["name"])
            print("参数 :", tc["function"]["arguments"])
            print("✅ 通过")
            passed += 1
        else:
            print("回复 :", msg.get("content"))
            print("❌ 未触发工具调用 → 该模型可能不支持 function calling")
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")

    # ---- 3. JSON 输出 + 一致性 ----
    print("\n" + "=" * 54)
    print("测试 3/3：JSON 输出 + temperature=0 一致性")
    print("=" * 54)
    prompt = (
        "你是外贸销售策略分析师。客户是老客户，上次因价格未成交，"
        "本次算价已满足目标价。只输出 JSON，不要其他文字："
        '{"stance":"re_engage|standard|defensive|escalate",'
        '"mention_history":true|false,"rationale":"一句话理由"}'
    )
    results = []
    for i in range(3):
        try:
            d = call({"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0,
                      "response_format": {"type": "json_object"},
                      "max_tokens": 200})
            obj = json.loads(d["choices"][0]["message"]["content"])
            results.append(obj["stance"])
            print(f"  第{i + 1}次 : stance={obj['stance']!r}  mention_history={obj['mention_history']}")
        except Exception as e:
            print(f"  第{i + 1}次失败 : {type(e).__name__}: {e}")

    if results and len(set(results)) == 1:
        print(f"✅ 三次一致（{results[0]}）—— temperature=0 生效，评测可复现")
        passed += 1
    elif results:
        print(f"⚠️  三次不一致：{results} → 判断类任务会不稳定")

    # ---- 汇总 ----
    print("\n" + "=" * 54)
    print(f"结果：{passed}/3 通过")
    print("=" * 54)
    if passed == 3:
        print("✅ 全部通过，可以用于本项目")
        return 0
    print("⚠️  有项目未通过，请检查上面的输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
