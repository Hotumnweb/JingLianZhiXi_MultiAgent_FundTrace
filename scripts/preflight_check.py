# -*- coding: utf-8 -*-
"""演示前一键自检：Python 依赖、数据文件、Neo4j、Ollama、报告开关。

用法（项目根目录下）：
    conda activate fraud_agent
    python scripts/preflight_check.py

比赛现场建议每次开场前跑一遍，30 秒内确认环境全部就绪。
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import os  # noqa: E402

DATA_FILE = BASE_DIR / "data" / "synthetic_aml" / "transactions.csv"

results: list[tuple[str, bool, str, bool]] = []  # 名称, 是否通过, 详情, 是否关键


def record(name: str, ok: bool, detail: str, critical: bool = True) -> None:
    results.append((name, ok, detail, critical))


def check_dependencies() -> None:
    missing = []
    for module in (
        "pandas",
        "neo4j",
        "langgraph",
        "requests",
        "streamlit",
        "dotenv",
        "plotly",
        "networkx",
        "psutil",
    ):
        try:
            __import__(module)
        except Exception:  # noqa: BLE001
            missing.append(module)
    record("Python 依赖", not missing, "缺失：" + ", ".join(missing) if missing else "全部可导入")


def check_data() -> None:
    if DATA_FILE.exists():
        size_mb = DATA_FILE.stat().st_size / 1024 / 1024
        record("AML 数据集", True, f"{DATA_FILE.name}（{size_mb:.1f} MB）")
    else:
        record("AML 数据集", False, f"找不到 {DATA_FILE}")


def check_neo4j() -> None:
    try:
        from tools.graph_query import close_driver, graph_summary

        summary = graph_summary()
        detail = f"连接正常；当前图谱 {summary['accounts']} 个账户 / {summary['transfers']} 条转账"
        record("Neo4j", True, detail)
        if summary["transfers"] == 0:
            record("Neo4j 数据", False, "图谱为空，请先运行 python main.py 建图", critical=False)
        close_driver()
    except Exception as exc:  # noqa: BLE001
        record("Neo4j", False, f"{type(exc).__name__}: {exc}")


def check_ollama() -> None:
    try:
        from llms.remote_llm import check_connection, report_agent_enabled

        info = check_connection()
        if not info["ok"]:
            record("Ollama", False, info["error"])
            return
        detail = f"{info['base_url']}；模型：{info['models']}"
        if not info["available"]:
            record("Ollama", False, f"未找到模型 {info['model']}；现有 {info['models']}")
        else:
            record("Ollama", True, detail)
        record(
            "报告节点",
            report_agent_enabled(),
            "已启用（会调用大模型）" if report_agent_enabled() else "已关闭（只跑图分析）",
            critical=False,
        )
    except Exception as exc:  # noqa: BLE001
        record("Ollama", False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    print("=" * 60)
    print("警链智析 · 演示前环境自检")
    print("=" * 60)

    check_dependencies()
    check_data()
    check_neo4j()
    check_ollama()

    failed_critical = False
    for name, ok, detail, critical in results:
        flag = "OK  " if ok else ("FAIL" if critical else "WARN")
        if not ok and critical:
            failed_critical = True
        print(f"[{flag}] {name:<12} {detail}")

    print("=" * 60)
    if failed_critical:
        print("自检未通过：请先解决 FAIL 项。")
        return 1
    print("自检通过，可以开始演示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
