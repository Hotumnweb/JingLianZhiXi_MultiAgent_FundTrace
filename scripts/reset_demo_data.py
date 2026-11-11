# -*- coding: utf-8 -*-
"""清理演示缓存与运行痕迹。

用途：比赛现场演示前恢复“干净环境”，由队员自己下发任务、生成报告、展示能力。

清理内容：
- reports/ 下的报告、证据 JSON、调度日志、临时日志；
- runtime/tasks/ 下的任务队列与任务记录；
- data/imports/ 下的上传流水（--all）；
- 项目内所有 __pycache__ / *.pyc / .ipynb_checkpoints；
- 可选：清空 Neo4j 图谱（--graph / --all）。

用法：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    python scripts/reset_demo_data.py --all
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
IMPORTS_DIR = DATA_DIR / "imports"


def clean_reports() -> int:
    """清空 reports/ 目录内容（保留目录本身）。"""
    if not REPORTS_DIR.exists():
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for item in REPORTS_DIR.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 无法删除 {item}: {exc}")
    return removed


def clean_caches() -> int:
    """清理 Python / notebook 缓存。"""
    removed = 0
    for directory in PROJECT_ROOT.rglob("__pycache__"):
        if any(part in {".git", ".idea", ".conda"} for part in directory.parts):
            continue
        try:
            shutil.rmtree(directory)
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    for pattern in ("*.pyc", "*.pyo"):
        for file in PROJECT_ROOT.rglob(pattern):
            try:
                file.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                pass
    for directory in PROJECT_ROOT.rglob(".ipynb_checkpoints"):
        try:
            shutil.rmtree(directory)
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def clean_runtime() -> bool:
    """清空 runtime/tasks 下的任务队列与任务记录。"""
    if not RUNTIME_DIR.exists():
        return True
    try:
        shutil.rmtree(RUNTIME_DIR)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] 无法删除 runtime/：{exc}")
        return False


def clean_imports() -> int:
    """清空 data/imports 下的上传流水（保留目录）。"""
    if not IMPORTS_DIR.exists():
        IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for item in IMPORTS_DIR.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 无法删除 {item}: {exc}")
    return removed


def clear_graph() -> bool:
    """清空 Neo4j 图谱（Node3 工具节点），并确认清空后确实为 0。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.graph_query import close_driver, clear_graph as clear_neo4j, graph_summary

        before = graph_summary()
        clear_neo4j()
        after = graph_summary()
        close_driver()
        print(f"  Neo4j 图谱：{before} -> {after}")
        if int(after.get("accounts") or 0) or int(after.get("transfers") or 0):
            print("  [ERROR] Neo4j 仍有数据，请检查连接配置或是否连到了另一个数据库。")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] 清空 Neo4j 失败（可能未启动）：{type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="清理演示缓存与运行痕迹")
    parser.add_argument("--graph", action="store_true", help="同时清空 Neo4j 图谱")
    parser.add_argument(
        "--all",
        action="store_true",
        help="清空 Neo4j 图谱、报告、任务队列和 data/imports 上传流水（推荐现场重置）",
    )
    args = parser.parse_args()

    graph_ok = True
    print("清理演示缓存……")
    if args.graph or args.all:
        graph_ok = clear_graph()
    if args.graph and not args.all:
        print("  [提示] --graph 只清图谱；要连上传流水一起清，请用 --all。")
    removed_reports = clean_reports()
    print(f"  reports/：已清理 {removed_reports} 项")
    clean_runtime()
    print("  runtime/tasks/：已清空任务队列记录")
    if args.all:
        removed_imports = clean_imports()
        print(f"  data/imports/：已清理 {removed_imports} 项（保留 data/synthetic_aml 和 sample_flow.csv）")
    removed_caches = clean_caches()
    print(f"  缓存目录/文件：已清理 {removed_caches} 项")
    print("完成。外部脚本不会让已打开的 Streamlit 页面自动重跑；")
    print("请回到平台点击“刷新状态”或按 F5，再从“元智能体调度”下发任务重新演示。")
    return 0 if graph_ok else 1


if __name__ == "__main__":
    sys.exit(main())
