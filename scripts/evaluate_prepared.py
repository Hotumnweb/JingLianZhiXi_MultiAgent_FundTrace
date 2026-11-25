# -*- coding: utf-8 -*-
"""在“抽样大数据集”上复算三条图规则的账户级指标。

用法（项目根目录）：
    conda activate fraud_agent
    python scripts/evaluate_prepared.py --dataset ibm-hi-small

前置条件：
1. 已生成抽样：`python scripts/prepare_datasets.py --all`
2. 已用该抽样建好当前 Neo4j 图谱，例如：
   python main.py --no-report data/prepared/ibm-hi-small_flow.csv

说明：标签（Is Laundering / isFraud）只在评测脚本中读取，
智能体运行时只看到交易结构，避免标签泄漏。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from workbench import services  # noqa: E402


def _print_metrics(name: str, row: dict) -> None:
    print(
        f"{name:<22} 账户={row['flagged']:>6}  命中={row['tp']:>6}  "
        f"精确率={row['precision']:.3f}  召回率={row['recall']:.3f}  F1={row['f1']:.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="在抽样数据集上复算图规则指标")
    parser.add_argument(
        "--dataset",
        required=True,
        help="抽样数据集 key：ibm-hi-small / ibm-li-small / paysim",
    )
    args = parser.parse_args()

    print("=" * 66)
    print(f"警链智析 · 抽样样本规则评测：{args.dataset}")
    print("=" * 66)
    try:
        result = services.compute_prepared_metrics(args.dataset)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        print("排查：1) 是否已生成抽样；2) 是否已用该抽样建图；3) Neo4j 是否在线")
        return 1

    graph = result.get("graph") or {}
    print(
        f"当前图谱：{graph.get('accounts', 0):,} 个账户 / "
        f"{graph.get('transfers', 0):,} 条转账（须与抽样数据一致）"
    )
    print(f"标签：{result['label_kind']} {result['truth']:,} 个（只用于事后评测）")
    print("-" * 66)
    _print_metrics("快进快出（辅助）", result["fast_io"])
    _print_metrics("多层归集（强）", result["gather"])
    _print_metrics("环形转账（强）", result["cycles"])
    _print_metrics("强证据合并", result["strong"])
    _print_metrics("最终可疑清单", result["all"])
    print("-" * 66)

    coverage = result.get("pattern_coverage") or {}
    if coverage.get("available"):
        print(
            f"IBM 洗钱模式覆盖：{coverage['covered_patterns']}/{coverage['total_patterns']} 类"
        )
        for name, item in coverage["by_type"].items():
            print(
                f"  {name:<18} 尝试 {item['attempts']:>3} 次 · "
                f"涉及账户 {item['accounts']:>5} · 规则命中 {item['flagged']:>4}"
            )
        print("-" * 66)

    print("说明：演示抽样保留了全部标签交易，真实洗钱/诈骗比例远低于抽样比例；")
    print("      召回率口径仅反映“账户级规则覆盖”，不代表实际侦查召回。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
