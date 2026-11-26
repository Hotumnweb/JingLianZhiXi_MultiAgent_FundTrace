# -*- coding: utf-8 -*-
"""命令行版本的数据清洗（与平台“数据接入与清洗”页共用同一引擎）。

适用：赛前批量准备、服务器无界面时清洗、复现平台上的清洗结果。

用法（项目根目录）：
    conda activate fraud_agent
    # 自动识别编码/分隔符/列名，清洗前 10 万行（快，适合现场）
    python scripts/clean_data.py --input data/new/one/HI-Small_Trans.csv --rows 100000

    # 均匀抽样（跨全时段，稍慢但更有代表性）
    python scripts/clean_data.py --input data/new/one/HI-Small_Trans.csv --rows 100000 --uniform

    # 自定义编码/分隔符/输出名
    python scripts/clean_data.py --input data/samples/messy_bank_flow.csv \
        --encoding gb18030 --delimiter ";" --output messy_demo

输出：data/cleaned/<name>.csv 与 <name>_stats.json（原始文件只读）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.data_cleaning import (  # noqa: E402
    CleanOptions,
    clean_file,
    profile_file,
)

TIME_MODES = {
    "auto": "auto",
    "datetime": "datetime",
    "epoch_s": "epoch_s",
    "epoch_ms": "epoch_ms",
    "step_hours": "step_hours",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="数据接入与清洗（命令行）")
    parser.add_argument("--input", required=True, help="原始文件路径（相对项目根目录或绝对路径）")
    parser.add_argument("--output", default="", help="输出数据集名称（默认 <文件名>_clean）")
    parser.add_argument("--rows", type=int, default=100_000, help="清洗行数上限，0=全部，默认 100000")
    parser.add_argument("--uniform", action="store_true", help="均匀抽样（跨全时段），默认前 N 行")
    parser.add_argument("--encoding", default=None, help="编码（默认自动识别）")
    parser.add_argument("--delimiter", default=None, help="分隔符（默认自动识别）")
    parser.add_argument("--no-header", action="store_true", help="文件没有表头")
    parser.add_argument("--time-mode", default=None, choices=list(TIME_MODES), help="时间解析方式")
    parser.add_argument("--time-base", default="2017-01-01 00:00:00", help="步长模式基准时间")
    parser.add_argument("--keep-self", action="store_true", help="保留付款=收款的自转账（默认剔除）")
    parser.add_argument("--no-dedupe", action="store_true", help="不做块内去重")
    parser.add_argument("--time-start", default="", help="时间过滤起始，例如 2022-09-01")
    parser.add_argument("--time-end", default="", help="时间过滤结束")
    parser.add_argument("--json", action="store_true", help="最后输出完整清洗报告 JSON")
    args = parser.parse_args()

    print("=" * 64)
    print("警链智析 · 数据接入与清洗（命令行）")
    print("=" * 64)
    try:
        profile = profile_file(
            args.input,
            encoding=args.encoding,
            delimiter=args.delimiter,
            has_header=False if args.no_header else None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 文件画像失败：{type(exc).__name__}: {exc}")
        return 1

    print(
        f"文件：{profile['path']}（{profile['size_mb']} MB，约 {profile['estimated_rows'] or '?'} 行）"
    )
    print(
        f"识别：编码 {profile['encoding']} · 分隔符 {profile['delimiter']!r} · "
        f"表头 {'有' if profile['has_header'] else '无'} · {profile['column_count']} 列"
    )
    print(f"类型：{profile['dataset_hint_text']}")
    mapping = profile["suggested_mapping"]
    print(
        "映射：时间=%s 金额=%s 付款=%s 收款=%s 摘要=%s"
        % (
            mapping.get("time_columns"),
            mapping.get("amount_columns"),
            mapping.get("from_columns"),
            mapping.get("to_columns"),
            mapping.get("summary_columns"),
        )
    )
    if mapping.get("missing"):
        print(f"[FAIL] 自动映射缺少字段：{mapping['missing']}；如需手工映射请在平台页面调整")
        return 2

    options = CleanOptions(
        time_mode=args.time_mode or mapping.get("time_mode", "auto"),
        time_base=args.time_base,
        drop_self_transfer=not args.keep_self,
        drop_duplicates=not args.no_dedupe,
        row_limit=args.rows,
        sample_mode="uniform" if args.uniform else "head",
        time_start=args.time_start,
        time_end=args.time_end,
        output_name=args.output,
    )

    last_percent = -1

    def _progress(fraction: float, message: str) -> None:
        nonlocal last_percent
        percent = int(fraction * 100)
        if percent >= last_percent + 5:
            last_percent = percent
            print(f"  [{percent:>3}%] {message}")

    try:
        stats = clean_file(args.input, profile, mapping, options, progress_callback=_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 清洗失败：{type(exc).__name__}: {exc}")
        return 1

    counters = stats["counters"]
    print("-" * 64)
    print(
        f"[OK] 写出 {counters['written_rows']:,} 行 → {stats['output']}（{stats['elapsed_s']} 秒）"
    )
    print(
        f"     读入 {counters['read_rows']:,} 行；剔除：时间 {counters['dropped_time']:,} / "
        f"金额 {counters['dropped_amount']:,} / 账号 {counters['dropped_account']:,} / "
        f"自转账 {counters['dropped_self_transfer']:,} / 重复 {counters['dropped_duplicates']:,}"
    )
    print(
        f"     时间范围：{stats['time_min'] or '—'} ~ {stats['time_max'] or '—'}；"
        f"账号 {stats['unique_accounts']:,}；清洗报告 {stats.get('stats_file', '')}"
    )
    print("下一步：python main.py --no-report " + stats["output"])
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
