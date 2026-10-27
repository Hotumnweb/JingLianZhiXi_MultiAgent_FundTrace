# -*- coding: utf-8 -*-
"""流水解析工具：把不同来源的流水 CSV 解析成统一字段的结构化记录。

自动识别两种格式，不需要改代码：

1. 通用中文流水（第一版 `data/sample_flow.csv`）：
       交易时间,金额,付款账号,收款账号,摘要

2. 合成 AML 数据集（`data/synthetic_aml/transactions.csv`）：
       transaction_id,timestamp,sender_account_id,receiver_account_id,amount_usd,
       payment_method,is_laundering,laundering_pattern,ring_id

统一输出字段：
    trade_time     交易时间（ISO 格式字符串：2025-01-01T00:14:12）
    amount         金额（float）
    from_account   付款账号（str）
    to_account     收款账号（str）
    summary        摘要（str）

安全/合规说明（重要）：
AML 数据集里的 `is_laundering`（是否洗钱）、`laundering_pattern`（洗钱模式）、
`ring_id`（团伙编号）是**数据集提供的答案标签**。解析时一律丢弃，不进入智能体输入。
否则就变成"拿着答案破案"（label leakage），比赛答辩会被直接质疑。
标签只在 `scripts/evaluate_on_synthetic_aml.py` 里单独读取，用于事后评测。
"""

from __future__ import annotations

import os

import pandas as pd

# 通用中文流水的列名别名：实际列名 -> 统一字段
COLUMN_ALIASES = {
    "trade_time": ["交易时间", "交易日期", "时间", "trade_time", "time"],
    "amount": ["金额", "交易金额", "发生额", "amount"],
    "from_account": ["付款账号", "付款账户", "付方账号", "付款人账号", "from_account"],
    "to_account": ["收款账号", "收款账户", "收方账号", "对方账号", "to_account"],
    "summary": ["摘要", "附言", "备注", "交易摘要", "用途", "summary"],
}

# summary 允许缺失，其余字段必须有
REQUIRED_FIELDS = ["trade_time", "amount", "from_account", "to_account"]

# AML 数据集列 -> 统一字段
AML_COLUMN_MAP = {
    "timestamp": "trade_time",
    "amount_usd": "amount",
    "sender_account_id": "from_account",
    "receiver_account_id": "to_account",
}

OUTPUT_FIELDS = ["trade_time", "amount", "from_account", "to_account", "summary"]


def _read_csv(file_path: str) -> pd.DataFrame:
    """优先按 UTF-8 读，失败再按 GBK 读（Windows 导出的 CSV 常见编码）。"""
    try:
        return pd.read_csv(file_path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(file_path, encoding="gbk")


def _is_aml_dataset(df: pd.DataFrame) -> bool:
    """通过特征列判断是否为合成 AML 数据集。"""
    return {"timestamp", "sender_account_id", "receiver_account_id", "amount_usd"} <= set(df.columns)


def detect_flow_format(columns) -> str | None:
    """根据表头判断是否是可解析的流水文件，并返回格式名称。

    支持两种格式：
    - AML 标准格式（timestamp / sender_account_id / receiver_account_id / amount_usd）
    - 通用中文流水（交易时间 / 金额 / 付款账号 / 收款账号）
    """
    cols = {str(col).strip() for col in columns}
    if {"timestamp", "sender_account_id", "receiver_account_id", "amount_usd"} <= cols:
        return "AML 标准格式"

    mapped: set[str] = set()
    for target, aliases in COLUMN_ALIASES.items():
        if any(col in aliases for col in cols):
            mapped.add(target)
    if all(field in mapped for field in REQUIRED_FIELDS):
        return "通用中文流水"
    return None


def _parse_aml(df: pd.DataFrame) -> pd.DataFrame:
    """AML 数据集：只保留交易结构字段，丢弃答案标签。"""
    df = df.rename(columns=AML_COLUMN_MAP)
    # 摘要只用支付渠道，不包含 laundering_pattern / ring_id 等标签
    if "payment_method" in df.columns:
        df["summary"] = df["payment_method"].fillna("未知").astype(str) + "渠道交易"
    else:
        df["summary"] = "转账"
    return df


def _parse_generic(df: pd.DataFrame) -> pd.DataFrame:
    """通用中文流水：按别名映射列名，缺字段时给出可读报错。"""
    rename_map = {}
    for target, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if str(col).strip() in aliases:
                rename_map[col] = target
                break
    df = df.rename(columns=rename_map)

    missing = [name for name in REQUIRED_FIELDS if name not in df.columns]
    if missing:
        raise ValueError(
            f"流水缺少必要字段：{missing}；实际列名：{list(df.columns)}。"
            f"请在 tools/parse_flow.py 的 COLUMN_ALIASES 里补充映射，"
            f"或检查是否下错了数据集文件。"
        )
    if "summary" not in df.columns:
        df["summary"] = "转账"
    return df


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """统一清洗：金额转数字、账号转字符串、时间转 ISO、剔除脏数据。"""
    df = df.copy()

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["from_account"] = df["from_account"].astype(str).str.strip()
    df["to_account"] = df["to_account"].astype(str).str.strip()
    df["summary"] = df["summary"].fillna("").astype(str)

    # 时间统一成 ISO 格式，Neo4j 的 datetime() 可以直接解析
    trade_time = pd.to_datetime(df["trade_time"], errors="coerce")
    df["trade_time"] = trade_time.dt.strftime("%Y-%m-%dT%H:%M:%S")

    # 剔除时间/账号无效的脏数据
    invalid_accounts = {"", "nan", "none", "null"}
    df = df[~df["from_account"].str.lower().isin(invalid_accounts)]
    df = df[~df["to_account"].str.lower().isin(invalid_accounts)]
    df = df[df["trade_time"].notna()]
    df = df[df["from_account"] != df["to_account"]]  # 自转账没有侦查意义

    return df[OUTPUT_FIELDS]


def parse_flow_file(file_path: str) -> list[dict]:
    """读取 CSV 流水，返回统一字段的结构化交易记录列表。"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"找不到流水文件：{file_path}（请在项目根目录下运行，并确认数据文件路径）"
        )

    df = _read_csv(file_path)
    if _is_aml_dataset(df):
        df = _parse_aml(df)
    else:
        df = _parse_generic(df)

    df = _clean(df)
    return df.to_dict(orient="records")
