# -*- coding: utf-8 -*-
"""清理演示缓存与运行痕迹。

用途：比赛现场演示前恢复“干净环境”，由队员自己下发任务、生成报告、展示能力。

清理内容：
- reports/ 下的报告、证据 JSON、调度日志、临时日志；
- runtime/tasks/ 下的任务队列与任务记录；
- 项目内所有 __pycache__ / *.pyc / .ipynb_checkpoints；
- 可选：清空 Neo4j 图谱（--graph），让现场从“解析流水 → 建图”开始演示。

用法：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    python scripts/reset_demo_data.py --graph
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
RUNTIME_DIR = PROJECT_ROOT / "runtime"


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


def clear_graph() -> bool:
    """清空 Neo4j 图谱（Node3 工具节点）。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.graph_query import close_driver, clear_graph as clear_neo4j, graph_summary

        before = graph_summary()
        clear_neo4j()
        after = graph_summary()
        close_driver()
        print(f"  Neo4j 图谱：{before} -> {after}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] 清空 Neo4j 失败（可能未启动）：{type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="清理演示缓存与运行痕迹")
    parser.add_argument("--graph", action="store_true", help="同时清空 Neo4j 图谱")
    args = parser.parse_args()

    print("清理演示缓存……")
    if args.graph:
        clear_graph()
    removed_reports = clean_reports()
    print(f"  reports/：已清理 {removed_reports} 项")
    clean_runtime()
    print("  runtime/tasks/：已清空任务队列记录")
    removed_caches = clean_caches()
    print(f"  缓存目录/文件：已清理 {removed_caches} 项")
    print("完成。现场打开平台后，从“元智能体调度”下发任务即可重新演示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
