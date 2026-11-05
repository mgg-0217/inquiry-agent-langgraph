"""图运行时：进程内复用同一个编译后的图实例。"""

from __future__ import annotations

from functools import lru_cache

from app.graph.build import build_single_agent


@lru_cache(maxsize=1)
def get_graph():
    """默认 sqlite checkpointer（单例）+ 真实 LLM。"""
    return build_single_agent()


def reset_graph() -> None:
    """测试/配置变更后重建。"""
    get_graph.cache_clear()
