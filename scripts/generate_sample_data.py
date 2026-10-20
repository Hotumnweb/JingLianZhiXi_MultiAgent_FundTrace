# -*- coding: utf-8 -*-
"""生成第一版测试流水：data/sample_flow.csv（100 条）。

数据说明（重要）：
- 本文件生成的是纯虚构仿真数据，不包含任何真实公民信息与真实账户，
  可安全用于开发、演示和比赛答辩；
- 内置 5 类典型电诈资金流模式，便于验证 tools/graph_query.py 的规则是否命中；
- 使用固定随机种子（SEED），重复运行结果完全一致，便于复现和现场演示。

内置模式与对应账户：
1. 快进快出 + 多层归集（水房）：
   V001-V008 -> K001-K008（卡农）-> S001（水房）-> L2_001 / L2_002 -> L3_001
2. 刷单返利：
   W001-W009 -> F001-F003 -> S002
3. 虚假投资：
   IV001-IV006 -> X001 -> S003 -> L2_003
4. 冒充公检法：
   QV001-QV004 -> Q001（安全账户）-> S004 -> L2_004
5. 正常噪声：N001-N020 之间的工资、消费、转账等日常流水

用法（项目根目录下）：
    conda activate fraud_agent
    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 20251019
TARGET_ROWS = 100
DATE = "2025-01-01"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "sample_flow.csv"

rng = random.Random(SEED)
rows: list[dict] = []
scenario_counts: dict[str, int] = {}


def clock(hour: int, minute: int, second: int = 0) -> str:
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def plus(clock_text: str, minutes: int, seconds: int = 0) -> str:
    """在某个时刻上增加分钟/秒，返回新的 HH:MM:SS。"""
    base = datetime.strptime(f"{DATE} {clock_text}", "%Y-%m-%d %H:%M:%S")
    return (base + timedelta(minutes=minutes, seconds=seconds)).strftime("%H:%M:%S")


def add(clock_text: str, amount: float, src: str, dst: str, summary: str) -> None:
    """追加一条流水记录。"""
    rows.append(
        {
            "交易时间": f"{DATE} {clock_text}",
            "金额": f"{amount:.2f}",
            "付款账号": src,
            "收款账号": dst,
            "摘要": summary,
        }
    )


def scenario_fast_io_and_gather() -> int:
    """模式 1：8 个受害人 -> 8 张卡农 -> 水房 S001 -> 二/三层归集。"""
    victims = [f"V{i:03d}" for i in range(1, 9)]
    mules = [f"K{i:03d}" for i in range(1, 9)]
    amounts = [6800, 12000, 9500, 25000, 15000, 8200, 18000, 30000]
    summaries = [
        "转账",
        "刷单返利",
        "投资理财",
        "冒充公检法",
        "转账",
        "垫付刷单",
        "平台充值",
        "安全账户",
    ]

    received_total = 0.0
    for i, (victim, mule, amount, summary) in enumerate(
        zip(victims, mules, amounts, summaries)
    ):
        in_clock = plus(clock(10, 0), 0, i * 40)
        add(in_clock, amount, victim, mule, summary)

        # 卡农在 6 分钟内把 90%~95% 的金额转给水房（快进快出）
        out_clock = plus(in_clock, 6, i)
        out_amount = round(amount * rng.uniform(0.90, 0.95), 2)
        add(out_clock, out_amount, mule, "S001", "转账")
        received_total += out_amount

    # 水房 S001 再往下拆分到第二层，第二层再往第三层（多层归集/穿透）
    add(plus(clock(10, 10), 7), round(received_total * 0.7, 2), "S001", "L2_001", "转账")
    add(plus(clock(10, 10), 7, 30), round(received_total * 0.3, 2), "S001", "L2_002", "转账")
    add(
        plus(clock(10, 17), 8),
        round(received_total * 0.7 * 0.95, 2),
        "L2_001",
        "L3_001",
        "转账",
    )
    return len(rows)


def scenario_shuadan() -> int:
    """模式 2：刷单返利，9 个受害人 -> 3 张卡农 -> 归集账户 S002。"""
    start = len(rows)
    victims = [f"W{i:03d}" for i in range(1, 10)]
    mules = ["F001", "F002", "F003", "F001", "F002", "F003", "F001", "F002", "F003"]
    summaries = [
        "刷单返利",
        "垫付刷单",
        "任务佣金",
        "兼职刷单",
        "刷单返利",
        "垫付刷单",
        "任务佣金",
        "兼职刷单",
        "刷单返利",
    ]
    totals = {mule: 0.0 for mule in ("F001", "F002", "F003")}

    for idx, (victim, mule, summary) in enumerate(zip(victims, mules, summaries)):
        in_clock = plus(clock(11, 0), 0, idx * 90)
        amount = rng.choice([500, 800, 1000, 1500, 2000, 3000])
        add(in_clock, amount, victim, mule, summary)
        totals[mule] += amount

    for idx, mule in enumerate(("F001", "F002", "F003")):
        add(plus(clock(11, 15), 3 + idx), round(totals[mule] * 0.92, 2), mule, "S002", "转账")
    return len(rows) - start


def scenario_investment() -> int:
    """模式 3：虚假投资，6 个受害人 -> 平台账户 X001 -> S003 -> L2_003。"""
    start = len(rows)
    victims = [f"IV{i:03d}" for i in range(1, 7)]
    amounts = [20000, 35000, 50000, 28000, 60000, 42000]
    total = 0.0

    for i, (victim, amount) in enumerate(zip(victims, amounts)):
        add(plus(clock(12, 0), 0, i * 120), amount, victim, "X001", "投资理财")
        total += amount

    sent_total = 0.0
    for i, ratio in enumerate([0.5, 0.3, 0.1]):
        amount = round(total * ratio, 2)
        add(plus(clock(12, 12), i, i * 10), amount, "X001", "S003", "平台充值")
        sent_total += amount

    add(plus(clock(12, 15), 5), round(sent_total * 0.95, 2), "S003", "L2_003", "转账")
    return len(rows) - start


def scenario_impersonation() -> int:
    """模式 4：冒充公检法，4 个受害人 -> 安全账户 Q001 -> S004 -> L2_004。"""
    start = len(rows)
    victims = [f"QV{i:03d}" for i in range(1, 5)]
    amounts = [3000, 6000, 9000, 12000]
    total = 0.0

    for i, (victim, amount) in enumerate(zip(victims, amounts)):
        add(plus(clock(14, 0), 0, i * 180), amount, victim, "Q001", "冒充公检法")
        total += amount

    add(plus(clock(14, 12), 2), round(total * 0.7, 2), "Q001", "S004", "安全账户")
    add(plus(clock(14, 12), 3), round(total * 0.2, 2), "Q001", "S004", "安全账户")
    add(plus(clock(14, 14), 4), round(total * 0.9 * 0.95, 2), "S004", "L2_004", "转账")
    return len(rows) - start


def add_noise() -> None:
    """模式 5：正常日常流水，作为干扰项，避免数据"一眼假"。"""
    accounts = [f"N{i:03d}" for i in range(1, 21)]
    summaries = ["工资", "消费", "转账", "还款", "房租", "水电费", "购物"]
    src, dst = rng.sample(accounts, 2)
    add(
        clock(rng.randint(9, 17), rng.randint(0, 59), rng.randint(0, 59)),
        round(rng.uniform(50, 5000), 2),
        src,
        dst,
        rng.choice(summaries),
    )


def main() -> None:
    scenario_counts["fast_io_gather"] = scenario_fast_io_and_gather()
    scenario_counts["shuadan"] = scenario_shuadan()
    scenario_counts["investment"] = scenario_investment()
    scenario_counts["impersonation"] = scenario_impersonation()

    noise = 0
    while len(rows) < TARGET_ROWS:
        add_noise()
        noise += 1
    scenario_counts["noise"] = noise

    rows[:] = rows[:TARGET_ROWS]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["交易时间", "金额", "付款账号", "收款账号", "摘要"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"output file : {OUTPUT}")
    print(f"total rows  : {len(rows)}")
    for name, count in scenario_counts.items():
        print(f"  {name:<16}: {count}")
    print("done")


if __name__ == "__main__":
    main()
