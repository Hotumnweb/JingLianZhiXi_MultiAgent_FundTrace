# -*- coding: utf-8 -*-
"""清理运行痕迹与生成数据，恢复干净的演示环境。

清理内容：
- reports/：报告、证据 JSON、调度日志；
- runtime/tasks/：任务队列与任务记录；
- data/imports/：上传的流水（--all）；
- data/prepared/、data/cleaned/：抽样与清洗产物（--all；加 --keep-assets 可保留）；
- 项目内 __pycache__ / *.pyc / .ipynb_checkpoints；
- Neo4j 图谱（--graph / --all）。

原始数据（data/new、data/synthetic_aml、data/sample_flow.csv、data/samples/）始终保留。

用法：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace

    # 完全恢复干净环境（推荐现场演示前；现场重新生成抽样/清洗）
    python scripts/reset_demo_data.py --all

    # 只清运行痕迹，保留已生成的抽样/清洗数据（作为现场兜底）
    python scripts/reset_demo_data.py --all --keep-assets

    # 只清 Neo4j 图谱（其余不动）
    python scripts/reset_demo_data.py --graph
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
PREPARED_DIR = DATA_DIR / "prepared"
CLEANED_DIR = DATA_DIR / "cleaned"


def _clean_dir_contents(directory: Path) -> int:
    """清空目录内容（保留目录本身）。"""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for item in directory.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] 无法删除 {item}: {exc}")
    return removed


def clean_reports() -> int:
    """清空 reports/ 目录内容（保留目录本身）。"""
    return _clean_dir_contents(REPORTS_DIR)


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
    return _clean_dir_contents(IMPORTS_DIR)


def clean_generated_assets() -> tuple[int, int]:
    """清空抽样（data/prepared）与清洗（data/cleaned）生成物。"""
    return _clean_dir_contents(PREPARED_DIR), _clean_dir_contents(CLEANED_DIR)


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
    parser = argparse.ArgumentParser(description="清理运行痕迹与生成数据")
    parser.add_argument("--graph", action="store_true", help="同时清空 Neo4j 图谱")
    parser.add_argument(
        "--all",
        action="store_true",
        help="清空图谱、报告、任务、上传流水、抽样与清洗产物（推荐现场重置）",
    )
    parser.add_argument(
        "--keep-assets",
        action="store_true",
        help="配合 --all：保留 data/prepared 与 data/cleaned（作为现场兜底）",
    )
    args = parser.parse_args()

    graph_ok = True
    print("清理运行数据……")
    if args.graph or args.all:
        graph_ok = clear_graph()
    if args.graph and not args.all:
        print("  [提示] --graph 只清图谱；要连报告/任务/上传/生成物一起清，请用 --all。")
    removed_reports = clean_reports()
    print(f"  reports/：已清理 {removed_reports} 项")
    clean_runtime()
    print("  runtime/tasks/：已清空任务记录")

    if args.all:
        removed_imports = clean_imports()
        print(f"  data/imports/：已清理 {removed_imports} 项")
        if args.keep_assets:
            print("  data/prepared、data/cleaned：已保留（--keep-assets）")
        else:
            removed_prepared, removed_cleaned = clean_generated_assets()
            print(
                f"  data/prepared/：已清理 {removed_prepared} 项；"
                f"data/cleaned/：已清理 {removed_cleaned} 项"
            )

    removed_caches = clean_caches()
    print(f"  缓存目录/文件：已清理 {removed_caches} 项")
    print("完成。外部脚本不会让已打开的 Streamlit 页面自动重跑；")
    print("请回到平台按 F5 刷新，再在“数据资产/数据接入”页现场生成数据并下发任务。")
    return 0 if graph_ok else 1


if __name__ == "__main__":
    sys.exit(main())
