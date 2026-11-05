"""测试用 fake LLM：可编程返回结构化结果，也可抛错模拟模型故障。"""

from __future__ import annotations

from typing import Any


class _StructuredRunner:
    def __init__(self, result: Any):
        self.result = result

    def invoke(self, messages):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _TextRunner:
    def __init__(self, text: str):
        self.text = text

    def invoke(self, messages):
        class _Response:
            content = self.text

        return _Response()


class FakeLLM:
    """`responses` 按 schema 类型给返回值；未指定的 schema 返回空构造。"""

    def __init__(self, responses: dict[type, Any] | None = None, text: str = "Fake reply"):
        self.responses = responses or {}
        self.text = text

    def with_structured_output(self, schema, method=None):
        result = self.responses.get(schema)
        if result is None:
            result = schema()
        return _StructuredRunner(result)

    def invoke(self, messages):
        return _TextRunner(self.text).invoke(messages)


class ScriptedTextLLM:
    """按顺序返回不同文本，用于测试 compose 的失败重写。"""

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.calls = 0

    def invoke(self, messages):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return _TextRunner(text).invoke(messages)
