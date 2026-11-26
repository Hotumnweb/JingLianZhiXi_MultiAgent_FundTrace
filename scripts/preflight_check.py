# -*- coding: utf-8 -*-
"""演示前一键自检：依赖、内置数据、数据资产、平台端口、Neo4j、Ollama、报告开关。

用法（项目根目录下）：
    conda activate fraud_agent
    python scripts/preflight_check.py

比赛现场建议每次开场前跑一遍，30 秒内确认环境全部就绪。
非关键项（数据资产、平台端口、报告开关）不通过只提示，不阻断演示。
"""

import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import os  # noqa: E402

DATA_FILE = BASE_DIR / "data" / "synthetic_aml" / "transactions.csv"
PREPARED_DIR = BASE_DIR / "data" / "prepared"
CLEANED_DIR = BASE_DIR / "data" / "cleaned"
RAW_DIR = BASE_DIR / "data" / "new"

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
        "openpyxl",
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


def check_data_assets() -> None:
    """检查大数据抽样、清洗产物、格式样例与原始数据集。"""
    prepared = list(PREPARED_DIR.glob("*_flow.csv")) if PREPARED_DIR.exists() else []
    cleaned = list(CLEANED_DIR.glob("*.csv")) if CLEANED_DIR.exists() else []
    messy = BASE_DIR / "data" / "samples" / "bank_flow_format_sample.csv"
    raw_ibm = RAW_DIR / "one" / "HI-Small_Trans.csv"
    raw_paysim = RAW_DIR / "paysim1" / "PS_20174392719_1491204439457_log.csv"

    record(
        "数据资产抽样",
        bool(prepared),
        f"data/prepared 抽样 {len(prepared)} 个"
        + ("" if prepared else "；现场可在“数据资产”页生成"),
        critical=False,
    )
    record(
        "清洗产物",
        bool(cleaned),
        f"data/cleaned 清洗数据 {len(cleaned)} 个"
        + ("" if cleaned else "；现场可在“数据接入”页清洗生成"),
        critical=False,
    )
    record(
        "格式样例",
        messy.exists(),
        "data/samples/bank_flow_format_sample.csv 可用" if messy.exists() else "缺少脏数据样例",
        critical=False,
    )
    record(
        "原始大数据",
        raw_ibm.exists() or raw_paysim.exists(),
        "data/new 原始流水可用（现场可演示清洗）" if (raw_ibm.exists() or raw_paysim.exists()) else "缺少 data/new 原始数据",
        critical=False,
    )


def check_platform() -> None:
    """平台是否已启动（可在自检时尚未启动，只提示）。"""
    try:
        with socket.create_connection(("127.0.0.1", 8501), timeout=2):
            record("平台端口", True, "http://localhost:8501 已在监听", critical=False)
    except OSError:
        record(
            "平台端口",
            False,
            "8501 未监听：启动 streamlit run app.py 后再跑一次自检",
            critical=False,
        )


def check_neo4j() -> None:
    try:
        from tools.graph_query import close_driver, graph_summary
        from tools.neo4j_config import connection_info

        info = connection_info()
        summary = graph_summary()
        detail = (
            f"{info['endpoint']} 连接正常；"
            f"当前图谱 {summary['accounts']} 个账户 / {summary['transfers']} 条转账"
        )
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
    check_data_assets()
    check_platform()
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
    print("自检通过，可以开始演示。完整演示步骤见 docs/DEMO_SCRIPT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
