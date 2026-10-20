# -*- coding: utf-8 -*-
"""在合成 AML 数据集上评测图规则的检测效果（答辩指标用）。

前置条件：
1. Neo4j 已启动；
2. 已运行 `python main.py` 把 `data/synthetic_aml/transactions.csv` 写入图数据库。

用法：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    python scripts/evaluate_on_synthetic_aml.py

说明：
真实办案场景没有标签，本脚本只用于验证算法效果、量化答辩指标。
数据集标签（is_synthetic_mule / laundering_rings）只在这里读取，
智能体运行时完全看不到，避免 label leakage。
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from tools.graph_query import (  # noqa: E402
    close_driver,
    find_circular_loops,
    find_fan_in,
    find_fast_in_fast_out,
)

DATA_DIR = BASE_DIR / "data" / "synthetic_aml"


def load_ground_truth() -> tuple[set[str], pd.DataFrame]:
    """读取数据集标签：哪些账户是洗钱账户、有哪些洗钱团伙。"""
    accounts = pd.read_csv(DATA_DIR / "accounts.csv")
    rings = pd.read_csv(DATA_DIR / "laundering_rings.csv")
    mule_accounts = set(accounts.loc[accounts["is_synthetic_mule"] == True, "account_id"])  # noqa: E712
    return mule_accounts, rings


def report_metrics(name: str, flagged: set[str], truth: set[str]) -> None:
    """打印账户级 precision / recall / F1。"""
    tp = flagged & truth
    precision = len(tp) / len(flagged) if flagged else 0.0
    recall = len(tp) / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(
        f"{name:<26} 账户={len(flagged):>4}  命中={len(tp):>3}  "
        f"精确率={precision:.3f}  召回率={recall:.3f}  F1={f1:.3f}"
    )


def main() -> int:
    mule_accounts, rings = load_ground_truth()
    print(f"数据集标签：洗钱账户 {len(mule_accounts)} 个，洗钱团伙 {len(rings)} 个")

    fast_io = find_fast_in_fast_out()
    gather = find_fan_in()
    cycles = find_circular_loops()

    fast_io_accounts = {item["account"] for item in fast_io}
    gather_accounts = {item["account"] for item in gather}
    cycle_accounts = {account for item in cycles for account in item["accounts"]}

    print("\n=== 图规则检测结果 ===")
    print(f"快进快出账户：{len(fast_io)} 个（48h 窗口、≥95% 转出、低活跃过滤）")
    print(f"多层归集账户：{len(gather)} 个（24h 窗口、≥4 上游、金额 CV≤0.15）")
    print(f"环形转账链  ：{len(cycles)} 条，覆盖 {len(cycle_accounts)} 个账户")

    print("\n=== 账户级检测指标 ===")
    report_metrics("快进快出（辅助）", fast_io_accounts, mule_accounts)
    report_metrics("多层归集（强）", gather_accounts, mule_accounts)
    report_metrics("环形转账（强）", cycle_accounts, mule_accounts)

    strong = gather_accounts | cycle_accounts
    report_metrics("强证据合并", strong, mule_accounts)

    all_flagged = strong | fast_io_accounts
    report_metrics("强证据+辅助证据", all_flagged, mule_accounts)

    detected_rings = 0
    for _, ring in rings.iterrows():
        members = set(str(ring["member_accounts"]).split(","))
        if members & all_flagged:
            detected_rings += 1
    print(f"\n=== 团伙级召回 ===\n{detected_rings}/{len(rings)} 个洗钱团伙至少命中 1 个账户")

    close_driver()
    return 0


if __name__ == "__main__":
    sys.exit(main())
