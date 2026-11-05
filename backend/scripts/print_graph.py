"""打印单 Agent 图的节点、边与 Mermaid 源码（第 2 天自检辅助）。

用法：
    python backend/scripts/print_graph.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.graph.build import build_single_agent  # noqa: E402


def main() -> int:
    graph = build_single_agent()
    drawable = graph.get_graph()

    nodes = sorted(drawable.nodes.keys())
    business_nodes = [n for n in nodes if not n.startswith("__")]
    print(f"节点（{len(business_nodes)} 个业务节点）：")
    print("  " + ", ".join(business_nodes))
    print()

    print("边：")
    for edge in drawable.edges:
        print(f"  {edge.source} -> {edge.target}")
    print()

    print("Mermaid：")
    print(drawable.draw_mermaid())
    print()

    # 机器可读摘要，便于自检脚本断言
    print(
        "JSON: "
        + json.dumps(
            {
                "business_node_count": len(business_nodes),
                "clarify_targets": [
                    e.target for e in drawable.edges if e.source == "clarify"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
