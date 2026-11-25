# -*- coding: utf-8 -*-
"""检查 Neo4j 图数据工具连接（IP + 端口写法）。

用法（项目根目录下）：
    conda activate fraud_agent
    python scripts/check_neo4j.py

临时指定地址做联调（不改 .env）：
    python scripts/check_neo4j.py --host 10.20.30.30 --port 7687

脚本会依次检查：
1. 打印 .env 解析出的连接配置（NEO4J_HOST + NEO4J_PORT，兼容旧 NEO4J_URI）；
2. 连接 Neo4j 并执行 `RETURN 1`，确认 Bolt 可达；
3. 读取当前图谱规模（账户 / 转账边），确认建图结果；
4. 打印排查建议（连接失败时）。

只读检查，不会写图谱、不改 .env。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Neo4j 图数据工具连接（IP + 端口）")
    parser.add_argument("--host", default=None, help="临时覆盖 NEO4J_HOST，例如 127.0.0.1 或 10.20.30.30")
    parser.add_argument("--port", type=int, default=None, help="临时覆盖 NEO4J_PORT，默认 7687")
    args = parser.parse_args()

    if args.host:
        os.environ["NEO4J_HOST"] = args.host
        os.environ.pop("NEO4J_URI", None)  # 显式 host 优先，避免旧 URI 干扰
    if args.port:
        os.environ["NEO4J_PORT"] = str(args.port)

    from tools.graph_query import close_driver, graph_summary, run_readonly_cypher
    from tools.neo4j_config import connection_info

    info = connection_info()
    print("=" * 60)
    print("警链智析 · Neo4j 图数据工具连接检查（IP + 端口）")
    print("=" * 60)
    print(f"[1/3] 配置：NEO4J_HOST={info['host']}  NEO4J_PORT={info['port']}")
    print(f"      驱动 URI：{info['uri']}")
    print(
        f"      用户：{info['user']}；数据库：{info['database'] or '（服务端默认库）'}；"
        f"位置：{'本机回环' if info['local'] else '远程节点'}"
    )

    started = time.perf_counter()
    try:
        result = run_readonly_cypher("RETURN 1 AS ok", limit=1)
        ping_ms = round((time.perf_counter() - started) * 1000, 1)
    except Exception as exc:  # noqa: BLE001
        print(f"[2/3] [FAIL] 连接失败：{type(exc).__name__}: {exc}")
        print("      排查顺序：")
        print("        1) Neo4j 是否已启动（neo4j.bat console / start-neo4j.bat）；")
        print("        2) .env 的 NEO4J_HOST / NEO4J_PORT 是否与实际监听地址一致；")
        print("        3) 远程节点时检查网络、防火墙是否放行 7687；")
        print("        4) NEO4J_USER / NEO4J_PASSWORD 是否正确。")
        return 1
    print(f"[2/3] [OK] Bolt 可达，`RETURN 1` 耗时 {ping_ms} ms（返回 {result['row_count']} 行）")

    try:
        summary = graph_summary()
    except Exception as exc:  # noqa: BLE001
        print(f"[3/3] [WARN] 图谱规模读取失败：{type(exc).__name__}: {exc}")
        close_driver()
        return 1
    print(
        f"[3/3] [OK] 当前图谱：{summary['accounts']} 个账户 / "
        f"{summary['transfers']} 条转账"
    )
    if not summary["transfers"]:
        print("      [提示] 图谱为空：运行 python main.py 或到平台下发一次任务建图。")

    close_driver()
    print("=" * 60)
    print("Neo4j 连接正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
