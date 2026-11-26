# -*- coding: utf-8 -*-
"""把 data/new 下的大规模数据集生成“确定性抽样”，供平台现场演示使用。

为什么不直接读原始文件：
- IBM HI/LI、PaySim 原始 CSV 各 450~650 MB、数百万行，前端扫描与全量建图都会拖慢现场演示；
- 原始数据格式也不统一（IBM 有 From Bank/Account 两列账户、PaySim 有 step 偏移时间），
  直接接入会污染主流程。

抽样策略（固定随机种子，可复现）：
- 流水类（IBM HI/LI、PaySim）：标签交易（Is Laundering / isFraud）**全部保留**，
  正常交易按固定种子确定性抽样，凑满目标行数；这样现场建图时标签结构可见，
  便于演示与指标复算（meta 中注明“演示抽样，非真实洗钱比例”）。
- 图结构（Elliptic）：按时间步抽取子图，统计高连接度节点的 illicit 占比，
  输出 edges / labels / overview，供“数据资产”页展示与后续 GNN 扩展。

输出目录：data/prepared/（已加入 .gitignore，运行下面命令生成）
    data/prepared/<key>_flow.csv    统一中文流水（交易时间,金额,付款账号,收款账号,摘要）
    data/prepared/<key>_labels.csv  账户级标签（account,is_laundering / account,class）
    data/prepared/<key>_meta.json   抽样元数据（行数、账户数、标签数、模式统计）

用法（项目根目录）：
    conda activate fraud_agent
    python scripts/prepare_datasets.py --all                 # 生成全部（约 20~40 秒）
    python scripts/prepare_datasets.py --dataset ibm-hi-small
    python scripts/prepare_datasets.py --dataset paysim --rows 30000
    python scripts/prepare_datasets.py --dataset elliptic --steps 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.dataset_catalog import (  # noqa: E402
    PREPARED_DIR,
    get_dataset,
    prepared_flow_path,
    prepared_labels_path,
    prepared_meta_path,
)

FLOW_COLUMNS = ["交易时间", "金额", "付款账号", "收款账号", "摘要"]
DEFAULT_ROWS = 50000
PAYSIM_DEFAULT_ROWS = 100000
DEFAULT_SEED = 20261125
IBM_CHUNK = 500000
PAYSIM_START = datetime(2017, 1, 1, 0, 0, 0)

IBM_USECOLS = [
    "Timestamp",
    "From Bank",
    "Account",
    "To Bank",
    "Account.1",
    "Amount Paid",
    "Payment Currency",
    "Payment Format",
    "Is Laundering",
]
PAYSIM_USECOLS = ["step", "type", "amount", "nameOrig", "nameDest", "isFraud"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_prepared_dir() -> None:
    PREPARED_DIR.mkdir(parents=True, exist_ok=True)


def _write_flow(records: list[dict], path: Path) -> None:
    df = pd.DataFrame(records, columns=FLOW_COLUMNS)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_labels(rows: list[dict], columns: list[str], path: Path) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def _write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_chunks(path: Path, usecols: list[str], dtype: dict | None = None):
    return pd.read_csv(
        path,
        usecols=usecols,
        chunksize=IBM_CHUNK,
        dtype=dtype,
        low_memory=False,
    )


# ---------------------------------------------------------------------------
# 通用：按固定种子抽样正常交易
# ---------------------------------------------------------------------------
def _sample_normals(
    path: Path,
    usecols: list[str],
    normal_mask_fn,
    target: int,
    seed: int,
    dtype: dict | None = None,
    total: int | None = None,
) -> pd.DataFrame:
    """对“正常交易”做确定性抽样，返回最多 target 行。

    normal_mask_fn(chunk) -> 布尔 Series（True 表示正常交易）。
    total 可传入已知的正常交易总数，避免多扫一遍文件。
    用多轮随机阈值补齐，保证结果可复现且接近目标行数。
    """
    if target <= 0:
        return pd.DataFrame(columns=usecols)

    if total is None:
        total = 0
        for chunk in _read_chunks(path, usecols, dtype):
            total += int(normal_mask_fn(chunk).sum())
    if total <= 0:
        return pd.DataFrame(columns=usecols)
    if target >= total:
        parts = [chunk[normal_mask_fn(chunk)] for chunk in _read_chunks(path, usecols, dtype)]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=usecols)

    rng = np.random.default_rng(seed)
    picked: list[pd.DataFrame] = []
    remaining = target
    for pass_index in range(4):
        if remaining <= 0:
            break
        p = remaining / total
        got = 0
        for chunk in _read_chunks(path, usecols, dtype):
            normals = chunk[normal_mask_fn(chunk)]
            if normals.empty:
                continue
            mask = rng.random(len(normals)) < p
            take = normals[mask]
            if len(take) > remaining - got:
                take = take.iloc[: remaining - got]
            if not take.empty:
                picked.append(take)
                got += len(take)
            if got >= remaining:
                break
        remaining -= got
        if got == 0:
            break
        # 每轮换一个种子，避免重复抽到同一批行
        rng = np.random.default_rng(seed + pass_index + 1)

    if not picked:
        return pd.DataFrame(columns=usecols)
    return pd.concat(picked, ignore_index=True).head(target)


# ---------------------------------------------------------------------------
# IBM AML（HI-Small / LI-Small）
# ---------------------------------------------------------------------------
def _parse_patterns(path: Path) -> dict:
    """解析 Patterns.txt：统计 8 类洗钱模式的尝试次数与交易条数。"""
    if not path.exists():
        return {"available": False}
    counts: dict[str, int] = {}
    transactions = 0
    current: str | None = None
    header = re.compile(r"BEGIN LAUNDERING ATTEMPT\s*-\s*(.+?)(?::|$)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        match = header.search(text)
        if match:
            current = match.group(1).strip().upper()
            counts[current] = counts.get(current, 0) + 1
            continue
        if current and re.match(r"^\d{4}/\d{2}/\d{2}", text):
            transactions += 1
    return {"available": True, "patterns": counts, "transactions": transactions}


def _ibm_account(bank, account) -> str:
    return f"{str(bank).strip()}:{str(account).strip()}"


def _ibm_records(df: pd.DataFrame) -> list[dict]:
    """把一批 IBM 交易转成统一中文流水字段（跳过付款=收款的无效自转账）。"""
    times = pd.to_datetime(df["Timestamp"], format="%Y/%m/%d %H:%M", errors="coerce")
    amounts = pd.to_numeric(df["Amount Paid"], errors="coerce")
    records: list[dict] = []
    for index in range(len(df)):
        trade_time = times.iloc[index]
        amount = amounts.iloc[index]
        if pd.isna(trade_time) or pd.isna(amount):
            continue
        payer = _ibm_account(df["From Bank"].iloc[index], df["Account"].iloc[index])
        payee = _ibm_account(df["To Bank"].iloc[index], df["Account.1"].iloc[index])
        if payer == payee:
            continue
        records.append(
            {
                "交易时间": trade_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "金额": round(float(amount), 2),
                "付款账号": payer,
                "收款账号": payee,
                "摘要": str(df["Payment Format"].iloc[index] or "转账"),
            }
        )
    return records


def _prepare_ibm(key: str, rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> dict:
    dataset = get_dataset(key) or {}
    trans_paths = [BASE_DIR / rel for rel in dataset.get("raw_paths", [])]
    trans_path = next((p for p in trans_paths if p.suffix.lower() == ".csv"), None)
    pattern_path = next((p for p in trans_paths if p.suffix.lower() == ".txt"), None)
    if trans_path is None or not trans_path.exists():
        raise FileNotFoundError(f"找不到 {key} 的原始流水：{trans_paths}")

    started = time.perf_counter()
    laundering_frames: list[pd.DataFrame] = []
    laundering_count = 0
    normal_total = 0
    currency_counter: dict[str, int] = {}

    for chunk in _read_chunks(trans_path, IBM_USECOLS, dtype={"Account": str, "Account.1": str}):
        labels = pd.to_numeric(chunk["Is Laundering"], errors="coerce").fillna(0).astype(int)
        mask = labels == 1
        laundering_count += int(mask.sum())
        normal_total += int((~mask).sum())
        if mask.any():
            laundering_frames.append(chunk[mask].copy())
            for currency, count in chunk.loc[mask, "Payment Currency"].value_counts().items():
                currency_counter[str(currency)] = currency_counter.get(str(currency), 0) + int(count)

    if not laundering_frames:
        raise ValueError(f"{key} 中没有找到 Is Laundering=1 的交易，请检查原始文件")

    laundering = pd.concat(laundering_frames, ignore_index=True)
    # 极端情况：洗钱交易比目标行数还多，则均匀抽一部分
    if len(laundering) > rows:
        laundering = laundering.sample(n=rows, random_state=seed).reset_index(drop=True)
    normal_target = max(0, rows - len(laundering))

    normals = _sample_normals(
        trans_path,
        IBM_USECOLS,
        lambda chunk: pd.to_numeric(chunk["Is Laundering"], errors="coerce").fillna(0).astype(int) != 1,
        normal_target,
        seed,
        dtype={"Account": str, "Account.1": str},
        total=normal_total,
    )

    sample = pd.concat([laundering, normals], ignore_index=True)
    sample = sample.sample(frac=1.0, random_state=seed).reset_index(drop=True)

    records = _ibm_records(sample)
    accounts: set[str] = set()
    for record in records:
        accounts.add(record["付款账号"])
        accounts.add(record["收款账号"])
    laundering_records = _ibm_records(laundering)
    laundering_accounts = sorted(
        {
            account
            for record in laundering_records
            for account in (record["付款账号"], record["收款账号"])
        }
    )

    _ensure_prepared_dir()
    flow_path = prepared_flow_path(key)
    labels_path = prepared_labels_path(key)
    meta_path = prepared_meta_path(key)
    _write_flow(records, flow_path)
    _write_labels(
        [{"account": account, "is_laundering": 1} for account in laundering_accounts],
        ["account", "is_laundering"],
        labels_path,
    )

    elapsed = round(time.perf_counter() - started, 1)
    meta = {
        "key": key,
        "name": dataset.get("name", key),
        "kind": "flow",
        "source": str(trans_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "license": dataset.get("license", ""),
        "generated_at": _now(),
        "seed": seed,
        "target_rows": rows,
        "rows": len(records),
        "accounts": len(accounts),
        "laundering_rows": len(laundering_records),
        "laundering_accounts": len(laundering_accounts),
        "raw_rows": dataset.get("raw_rows"),
        "raw_normal_rows": normal_total,
        "raw_laundering_rows": laundering_count,
        "sampling_method": "洗钱交易全保留 + 正常交易固定种子确定性抽样",
        "currency_note": "金额取 Amount Paid 原值，多币种未换算；用于结构规则分析",
        "laundering_currency_top": sorted(currency_counter.items(), key=lambda kv: kv[1], reverse=True)[:5],
        "patterns": _parse_patterns(pattern_path) if pattern_path else {"available": False},
        "flow_file": str(flow_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "labels_file": str(labels_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "elapsed_s": elapsed,
        "dropped_self_transfers": len(sample) - len(records),
    }
    _write_json(meta, meta_path)
    return meta


# ---------------------------------------------------------------------------
# PaySim
# ---------------------------------------------------------------------------
def _paysim_records(df: pd.DataFrame) -> list[dict]:
    """PaySim 交易转统一中文流水（跳过付款=收款的自转账）。"""
    records: list[dict] = []
    steps = pd.to_numeric(df["step"], errors="coerce")
    amounts = pd.to_numeric(df["amount"], errors="coerce")
    for index in range(len(df)):
        step = steps.iloc[index]
        amount = amounts.iloc[index]
        if pd.isna(step) or pd.isna(amount):
            continue
        payer = str(df["nameOrig"].iloc[index]).strip()
        payee = str(df["nameDest"].iloc[index]).strip()
        if payer == payee:
            continue
        trade_time = PAYSIM_START + timedelta(hours=int(step))
        records.append(
            {
                "交易时间": trade_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "金额": round(float(amount), 2),
                "付款账号": payer,
                "收款账号": payee,
                "摘要": str(df["type"].iloc[index] or "转账"),
            }
        )
    return records


def _prepare_paysim(rows: int = PAYSIM_DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> dict:
    """PaySim 抽样：诈骗交易全保留 + 诈骗账户关联交易（补全资金链）+ 正常交易抽样。"""
    key = "paysim"
    dataset = get_dataset(key) or {}
    trans_path = BASE_DIR / (dataset.get("raw_paths") or [""])[0]
    if not trans_path.exists():
        raise FileNotFoundError(f"找不到 PaySim 原始流水：{trans_path}")

    started = time.perf_counter()

    # 第一遍：诈骗交易与诈骗账户
    fraud_frames: list[pd.DataFrame] = []
    fraud_accounts_raw: set[str] = set()
    fraud_count = 0
    type_counter: dict[str, int] = {}
    for chunk in _read_chunks(trans_path, PAYSIM_USECOLS):
        mask = pd.to_numeric(chunk["isFraud"], errors="coerce").fillna(0).astype(int) == 1
        fraud_count += int(mask.sum())
        if mask.any():
            fraud_rows = chunk[mask].copy()
            fraud_frames.append(fraud_rows)
            fraud_accounts_raw.update(fraud_rows["nameOrig"].astype(str).str.strip())
            fraud_accounts_raw.update(fraud_rows["nameDest"].astype(str).str.strip())
            for tx_type, count in fraud_rows["type"].value_counts().items():
                type_counter[str(tx_type)] = type_counter.get(str(tx_type), 0) + int(count)
    if not fraud_frames:
        raise ValueError("PaySim 中没有找到 isFraud=1 的交易")
    fraud = pd.concat(fraud_frames, ignore_index=True)

    # 第二遍：与诈骗账户相关的正常交易（补全“受害人→过渡账户→取现”链路），并统计普通正常交易
    touch_frames: list[pd.DataFrame] = []
    touch_count = 0
    normal_total = 0
    for chunk in _read_chunks(trans_path, PAYSIM_USECOLS):
        is_fraud = pd.to_numeric(chunk["isFraud"], errors="coerce").fillna(0).astype(int) == 1
        touches = (
            chunk["nameOrig"].astype(str).str.strip().isin(fraud_accounts_raw)
            | chunk["nameDest"].astype(str).str.strip().isin(fraud_accounts_raw)
        ) & ~is_fraud
        if touches.any():
            touch = chunk[touches]
            touch_frames.append(touch)
            touch_count += len(touch)
        normal_total += int((~is_fraud & ~touches).sum())

    target = max(int(rows), len(fraud) + 1)
    touch = (
        pd.concat(touch_frames, ignore_index=True)
        if touch_frames
        else pd.DataFrame(columns=PAYSIM_USECOLS)
    )
    touch_budget = max(0, target - len(fraud))
    if len(touch) > touch_budget:
        touch = touch.sample(n=touch_budget, random_state=seed).reset_index(drop=True)
    normal_target = max(0, target - len(fraud) - len(touch))

    def _normal_mask(chunk: pd.DataFrame):
        is_fraud = pd.to_numeric(chunk["isFraud"], errors="coerce").fillna(0).astype(int) == 1
        touches = (
            chunk["nameOrig"].astype(str).str.strip().isin(fraud_accounts_raw)
            | chunk["nameDest"].astype(str).str.strip().isin(fraud_accounts_raw)
        )
        return ~is_fraud & ~touches

    normals = _sample_normals(
        trans_path,
        PAYSIM_USECOLS,
        _normal_mask,
        normal_target,
        seed,
        total=normal_total,
    )
    sample = pd.concat([fraud, touch, normals], ignore_index=True)
    sample = sample.sample(frac=1.0, random_state=seed).reset_index(drop=True)

    records = _paysim_records(sample)
    accounts: set[str] = set()
    for record in records:
        accounts.add(record["付款账号"])
        accounts.add(record["收款账号"])
    fraud_records = _paysim_records(fraud)
    fraud_accounts = sorted(
        {
            account
            for record in fraud_records
            for account in (record["付款账号"], record["收款账号"])
        }
    )

    _ensure_prepared_dir()
    flow_path = prepared_flow_path(key)
    labels_path = prepared_labels_path(key)
    meta_path = prepared_meta_path(key)
    _write_flow(records, flow_path)
    _write_labels(
        [{"account": account, "is_fraud": 1} for account in fraud_accounts],
        ["account", "is_fraud"],
        labels_path,
    )
    elapsed = round(time.perf_counter() - started, 1)
    meta = {
        "key": key,
        "name": dataset.get("name", key),
        "kind": "flow",
        "source": str(trans_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "license": dataset.get("license", ""),
        "generated_at": _now(),
        "seed": seed,
        "target_rows": target,
        "rows": len(records),
        "accounts": len(accounts),
        "fraud_rows": len(fraud_records),
        "fraud_accounts": len(fraud_accounts),
        "neighborhood_rows": int(len(touch)),
        "raw_rows": dataset.get("raw_rows"),
        "raw_normal_rows": normal_total,
        "raw_fraud_rows": fraud_count,
        "fraud_types": sorted(type_counter.items(), key=lambda kv: kv[1], reverse=True),
        "sampling_method": (
            "诈骗交易全保留 + 诈骗账户关联交易（补全资金链）+ 正常交易固定种子确定性抽样"
        ),
        "time_note": "step 为小时序号，映射到 2017-01-01 起算的时间；用于时间窗口规则分析",
        "flow_file": str(flow_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "labels_file": str(labels_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "elapsed_s": elapsed,
        "dropped_self_transfers": len(sample) - len(records),
    }
    _write_json(meta, meta_path)
    return meta


# ---------------------------------------------------------------------------
# Elliptic 图结构子集
# ---------------------------------------------------------------------------
def _prepare_elliptic(steps: int = 20, seed: int = DEFAULT_SEED) -> dict:
    key = "elliptic"
    dataset = get_dataset(key) or {}
    paths = [BASE_DIR / rel for rel in dataset.get("raw_paths", [])]
    edges_path = next((p for p in paths if "edgelist" in p.name), None)
    classes_path = next((p for p in paths if "classes" in p.name), None)
    features_path = next((p for p in paths if "features" in p.name), None)
    for path in (edges_path, classes_path, features_path):
        if path is None or not path.exists():
            raise FileNotFoundError(f"Elliptic 数据缺少文件：{path}")

    started = time.perf_counter()
    features = pd.read_csv(
        features_path, header=None, usecols=[0, 1], names=["txId", "step"]
    )
    edges = pd.read_csv(edges_path)
    classes = pd.read_csv(classes_path)

    node_subset = features[features["step"] <= steps]
    node_ids = set(node_subset["txId"].astype(int))
    sub_edges = edges[
        edges["txId1"].astype(int).isin(node_ids) & edges["txId2"].astype(int).isin(node_ids)
    ].copy()
    sub_labels = classes[classes["txId"].astype(int).isin(node_ids)].copy()
    sub_labels["class"] = sub_labels["class"].astype(str).str.strip()

    class_counts = sub_labels["class"].value_counts().to_dict()
    degree = pd.concat([sub_edges["txId1"], sub_edges["txId2"]]).value_counts()
    top_nodes = degree.head(50)
    top_label_map = dict(zip(sub_labels["txId"].astype(int), sub_labels["class"]))
    top_rows = [
        {
            "txId": int(tx_id),
            "degree": int(count),
            "class": top_label_map.get(int(tx_id), "unknown"),
        }
        for tx_id, count in top_nodes.items()
    ]
    top_illicit = sum(1 for row in top_rows if row["class"] == "1")
    illicit_total = int(class_counts.get("1", 0))
    node_total = len(sub_labels)

    _ensure_prepared_dir()
    edges_out = PREPARED_DIR / "elliptic_edges.csv"
    labels_out = PREPARED_DIR / "elliptic_labels.csv"
    overview_path = PREPARED_DIR / "elliptic_overview.json"
    meta_path = prepared_meta_path(key)
    sub_edges.to_csv(edges_out, index=False, encoding="utf-8-sig")
    sub_labels.to_csv(labels_out, index=False, encoding="utf-8-sig")
    overview = {
        "steps": steps,
        "nodes": int(node_total),
        "edges": int(len(sub_edges)),
        "classes": {str(key_): int(value) for key_, value in class_counts.items()},
        "illicit_ratio": round(illicit_total / node_total, 4) if node_total else 0.0,
        "top_degree_nodes": top_rows,
        "top_degree_illicit": top_illicit,
        "top_degree_illicit_ratio": round(top_illicit / len(top_rows), 4) if top_rows else 0.0,
        "class_map": {"1": "illicit（涉诈/非法）", "2": "licit（合法）", "unknown": "unknown（未知）"},
    }
    _write_json(overview, overview_path)

    elapsed = round(time.perf_counter() - started, 1)
    meta = {
        "key": key,
        "name": dataset.get("name", key),
        "kind": "graph",
        "source": "data/new/elliptic/elliptic_bitcoin_dataset",
        "license": dataset.get("license", ""),
        "generated_at": _now(),
        "seed": seed,
        "steps": steps,
        "nodes": int(node_total),
        "edges": int(len(sub_edges)),
        "class_counts": {str(key_): int(value) for key_, value in class_counts.items()},
        "raw_nodes": 203769,
        "raw_edges": 234355,
        "edges_file": "data/prepared/elliptic_edges.csv",
        "labels_file": "data/prepared/elliptic_labels.csv",
        "overview_file": "data/prepared/elliptic_overview.json",
        "sampling_method": f"按时间步 <= {steps} 抽取子图（官方时间步 1~49）",
        "note": "Elliptic 没有交易金额，不能进入资金流水规则主流程；用于图结构、社区发现、GNN 扩展",
        "elapsed_s": elapsed,
    }
    _write_json(meta, meta_path)
    return meta


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
PREPARERS = {
    "ibm-hi-small": lambda rows, seed: _prepare_ibm("ibm-hi-small", rows, seed),
    "ibm-li-small": lambda rows, seed: _prepare_ibm("ibm-li-small", rows, seed),
    "paysim": lambda rows, seed: _prepare_paysim(rows, seed),
    "elliptic": lambda rows, seed: _prepare_elliptic(steps=20, seed=seed),
}

# 每个数据集的默认抽样行数（PaySim 需要更多行才能保留完整诈骗资金链）
DEFAULT_ROWS_BY_KEY = {
    "ibm-hi-small": DEFAULT_ROWS,
    "ibm-li-small": DEFAULT_ROWS,
    "paysim": PAYSIM_DEFAULT_ROWS,
    "elliptic": 0,
}


def prepare_dataset(key: str, rows: int | None = None, seed: int = DEFAULT_SEED) -> dict:
    """页面/脚本共用入口：生成指定数据集的抽样，返回 meta。"""
    preparer = PREPARERS.get(key)
    if preparer is None:
        raise ValueError(f"不支持的数据集：{key}（可选：{', '.join(PREPARERS)}）")
    if rows is None:
        rows = DEFAULT_ROWS_BY_KEY.get(key, DEFAULT_ROWS)
    return preparer(rows, seed)


def prepare_all(rows: int | None = None, seed: int = DEFAULT_SEED) -> list[dict]:
    results = []
    for key in PREPARERS:
        results.append(prepare_dataset(key, rows=rows, seed=seed))
    return results


def _print_meta(meta: dict) -> None:
    print(f"  [OK] {meta['key']:<14} rows={meta.get('rows', '-'):>7} "
          f"accounts={meta.get('accounts', '-'):>7} "
          f"labels={meta.get('laundering_accounts', meta.get('fraud_accounts', meta.get('nodes', '-')))}"
          f"  {meta.get('elapsed_s', '?')}s")
    print(f"       flow: {meta.get('flow_file', meta.get('edges_file', ''))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成大数据集抽样（data/prepared）")
    parser.add_argument(
        "--dataset",
        default=None,
        help=f"要生成的数据集：{', '.join(PREPARERS)}；不填则配合 --all",
    )
    parser.add_argument("--all", action="store_true", help="生成全部抽样数据集")
    parser.add_argument(
        "--rows",
        type=int,
        default=None,
        help=f"流水目标行数；不填用各数据集默认值（IBM {DEFAULT_ROWS}，PaySim {PAYSIM_DEFAULT_ROWS}）",
    )
    parser.add_argument("--steps", type=int, default=20, help="Elliptic 时间步上限，默认 20")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子（保证可复现）")
    args = parser.parse_args()

    if not args.all and not args.dataset:
        parser.print_help()
        return 2

    # Elliptic 用 steps 参数
    if args.dataset == "elliptic" or args.all:
        PREPARERS["elliptic"] = lambda rows, seed: _prepare_elliptic(steps=args.steps, seed=seed)

    t0 = time.perf_counter()
    print("=" * 60)
    print("生成 data/prepared 抽样数据")
    print("=" * 60)
    try:
        if args.all:
            metas = prepare_all(rows=args.rows, seed=args.seed)
        else:
            metas = [prepare_dataset(args.dataset, rows=args.rows, seed=args.seed)]
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1
    for meta in metas:
        _print_meta(meta)
    print("=" * 60)
    print(f"完成：{len(metas)} 个抽样，耗时 {round(time.perf_counter() - t0, 1)} 秒")
    print("下一步：到平台“数据资产”页查看，或在“元智能体调度”页选择“大数据抽样”数据源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
