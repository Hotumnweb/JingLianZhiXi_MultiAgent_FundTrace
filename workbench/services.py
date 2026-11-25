# -*- coding: utf-8 -*-
"""平台服务层：节点健康检查、数据概览、报告索引、调度日志、指标计算。

页面只调用这一层，不直接写 Cypher / HTTP 细节，便于：
1. 平台展示与业务逻辑解耦；
2. 每个能力都可被单独测试（见 scripts/preflight_check.py）；
3. 后续把第二台/第三台节点接进来时，只改本文件。
"""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import shutil
import socket
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AML_DIR = DATA_DIR / "synthetic_aml"
IMPORTS_DIR = DATA_DIR / "imports"
REPORTS_DIR = PROJECT_ROOT / "reports"
AUDIT_DIR = REPORTS_DIR / "audit"
AUDIT_LOG = AUDIT_DIR / "audit.jsonl"
RUNTIME_DIR = PROJECT_ROOT / "runtime"

DEFAULT_NODE_TARGETS = {
    "node2": "192.168.50.2",
    "node3": "192.168.50.3",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def reset_demo_data(clear_imports: bool = True) -> dict:
    """清空图谱、报告、任务队列；可选清空上传流水。

    只清运行时数据，不删除 data/synthetic_aml 和 data/sample_flow.csv 这类内置测试数据。
    返回实际清理结果，供页面/命令输出使用。
    """
    result = {
        "graph_before": {},
        "graph_after": {},
        "graph_cleared": False,
        "reports_cleared": False,
        "runtime_cleared": False,
        "imports_cleared": False,
        "error": "",
    }
    try:
        from tools.graph_query import clear_graph, close_driver, graph_summary

        result["graph_before"] = graph_summary()
        clear_graph()
        result["graph_after"] = graph_summary()
        close_driver()
        result["graph_cleared"] = not any(
            int(result["graph_after"].get(key) or 0) for key in ("accounts", "transfers")
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"

    for key, path in (
        ("reports_cleared", REPORTS_DIR),
        ("runtime_cleared", RUNTIME_DIR),
        ("imports_cleared", IMPORTS_DIR),
    ):
        if key == "imports_cleared" and not clear_imports:
            continue
        try:
            if path.exists():
                shutil.rmtree(path)
            result[key] = True
        except Exception as exc:  # noqa: BLE001
            result["error"] = (result["error"] + "；" if result["error"] else "") + f"{path.name}: {exc}"

    ensure_dirs()
    if clear_imports:
        IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return result


# ----------------------------------------------------------------------------
# 流水数据源发现与校验（动态读取，不写死 42,175）
# ----------------------------------------------------------------------------
def _read_flow_header(path: Path):
    """读取 CSV 表头，兼容 UTF-8 与 GBK。"""
    import pandas as pd

    try:
        return pd.read_csv(path, nrows=0, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, nrows=0, encoding="gbk")


def _count_csv_rows(path: Path) -> int:
    """只读第一列统计行数，避免为大文件加载全部列。"""
    import pandas as pd

    try:
        return int(pd.read_csv(path, usecols=[0], encoding="utf-8-sig").shape[0])
    except UnicodeDecodeError:
        return int(pd.read_csv(path, usecols=[0], encoding="gbk").shape[0])


def inspect_flow_file(relative_path: str) -> dict:
    """校验单个流水文件，返回实际行数、格式、列名和展示标签。"""
    from tools.parse_flow import detect_flow_format

    raw = Path(str(relative_path))
    path = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"找不到流水文件：{relative_path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("当前只支持 CSV 流水文件（.csv）")

    header = _read_flow_header(path)
    fmt = detect_flow_format(header.columns)
    if not fmt:
        raise ValueError(
            "无法识别的流水格式；需要 AML 标准列（timestamp / sender_account_id / "
            "receiver_account_id / amount_usd）或通用中文列（交易时间 / 金额 / "
            f"付款账号 / 收款账号）。实际列名：{list(header.columns)}"
        )
    rows = _count_csv_rows(path)
    if rows <= 0:
        raise ValueError("流水文件没有数据行")
    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = str(path)
    return {
        "path": rel,
        "abs_path": str(path),
        "rows": rows,
        "format": fmt,
        "columns": [str(col) for col in header.columns],
        "label": f"{rel} · {rows:,} 条",
    }


def scan_flow_files() -> list[dict]:
    """动态扫描 data/ 下可解析的 CSV 流水文件。

    注意：`data/new/` 是原始大数据集（单文件几百 MB），不参与前端扫描；
    平台只消费 `scripts/prepare_datasets.py` 生成到 `data/prepared/` 的抽样文件。
    """
    if not DATA_DIR.exists():
        return []
    raw_dataset_dir = DATA_DIR / "new"
    items: list[dict] = []
    for path in sorted(DATA_DIR.rglob("*.csv")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if raw_dataset_dir in path.parents:
            continue
        try:
            items.append(inspect_flow_file(str(path)))
        except Exception:  # noqa: BLE001 - 扫描阶段跳过非流水 CSV
            continue
    # 上传目录排在最后，其余按路径排序，便于操作员先看到内置数据
    items.sort(key=lambda item: (item["path"].startswith("data/imports/"), item["path"]))
    return items


def save_uploaded_flow(file_name: str, content: bytes) -> dict:
    """把浏览器选择的 CSV 保存到 data/imports/ 并做格式校验。"""
    from tools.parse_flow import detect_flow_format

    safe_name = Path(str(file_name)).name
    if not safe_name.lower().endswith(".csv"):
        raise ValueError("只允许导入 .csv 流水文件")
    if not content:
        raise ValueError("上传文件为空")

    imports_dir = DATA_DIR / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    target = imports_dir / safe_name
    target.write_bytes(content)

    try:
        header = _read_flow_header(target)
        if not detect_flow_format(header.columns):
            raise ValueError(
                "导入的 CSV 不是可识别的流水格式；请检查列名是否包含 "
                "交易时间/金额/付款账号/收款账号，或 AML 标准列。"
                f"实际列名：{list(header.columns)}"
            )
        rows = _count_csv_rows(target)
        if rows <= 0:
            raise ValueError("导入的 CSV 没有数据行")
    except Exception:
        target.unlink(missing_ok=True)
        raise

    rel = target.relative_to(PROJECT_ROOT).as_posix()
    return {
        "path": rel,
        "abs_path": str(target),
        "rows": rows,
        "label": f"{rel} · {rows:,} 条",
    }


# ----------------------------------------------------------------------------
# 数据概览
# ----------------------------------------------------------------------------
def dataset_profile() -> dict:
    """读取数据集 manifest 与团伙清单，返回平台总览用的静态画像。"""
    manifest = _read_json(AML_DIR / "manifest.json")
    rings_path = AML_DIR / "laundering_rings.csv"
    ring_rows: list[dict] = []
    if rings_path.exists():
        try:
            with rings_path.open(encoding="utf-8-sig", newline="") as f:
                ring_rows = list(csv.DictReader(f))
        except Exception:  # noqa: BLE001
            ring_rows = []

    ring_types: dict[str, int] = {}
    for row in ring_rows:
        key = (row.get("pattern_type") or "Unknown").strip()
        ring_types[key] = ring_types.get(key, 0) + 1

    date_range = manifest.get("date_range") or {}
    return {
        "dataset": manifest.get("dataset_name", "未发现数据集"),
        "transactions": int(manifest.get("transaction_count") or 0),
        "accounts": int(manifest.get("account_count") or 0),
        "rings": int(manifest.get("laundering_ring_count") or len(ring_rows)),
        "fraud_transactions": int(manifest.get("fraud_transaction_count") or 0),
        "fraud_rate": manifest.get("fraud_rate_pct", 0),
        "volume_usd": manifest.get("total_volume_usd", 0),
        "date_start": date_range.get("start", ""),
        "date_end": date_range.get("end", ""),
        "ring_types": ring_types,
        "ring_rows": ring_rows,
    }


def graph_stats() -> dict:
    """当前 Neo4j 图谱规模（连接失败时返回空值，不抛异常）。"""
    try:
        from tools.graph_query import graph_summary

        return graph_summary()
    except Exception as exc:  # noqa: BLE001
        return {"accounts": 0, "transfers": 0, "error": f"{type(exc).__name__}: {exc}"}


def neo4j_connection() -> dict:
    """Neo4j 连接配置（IP + 端口写法），供节点状态与 Neo4j 操作台展示。"""
    from tools.neo4j_config import connection_info

    return connection_info()


def latest_evidence() -> dict | None:
    """最近一次运行的证据 JSON。"""
    if not REPORTS_DIR.exists():
        return None
    files = sorted(
        REPORTS_DIR.glob("*_evidence.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not files:
        return None
    return _read_json(files[0])


def evidence_summary(payload: dict | None) -> dict:
    """把证据 JSON 归纳成平台 KPI：强/弱证据、可疑账户、环形账户等。"""
    if not payload:
        return {
            "case_id": "",
            "meta": {},
            "gather": 0,
            "cycles": 0,
            "cycle_accounts": 0,
            "fast_io": 0,
            "strong": 0,
            "weak": 0,
            "suspects": 0,
            "suspect_list": [],
            "evidence": {},
        }

    evidence = payload.get("evidence") or {}
    gather = evidence.get("gather") or []
    cycles = evidence.get("cycles") or []
    fast_io = evidence.get("fast_io") or []
    cycle_accounts = {
        account for item in cycles for account in (item.get("accounts") or [])
    }
    gather_accounts = {item.get("account") for item in gather if item.get("account")}
    fast_accounts = {item.get("account") for item in fast_io if item.get("account")}
    strong = gather_accounts | cycle_accounts
    suspects = sorted(strong | fast_accounts)

    return {
        "case_id": payload.get("case_id", ""),
        "meta": payload.get("meta") or {},
        "gather": len(gather),
        "cycles": len(cycles),
        "cycle_accounts": len(cycle_accounts),
        "fast_io": len(fast_io),
        "strong": len(strong),
        "weak": len(fast_accounts),
        "suspects": len(suspects),
        "suspect_list": suspects,
        "evidence": evidence,
    }


def risk_rows(payload: dict | None) -> list[dict]:
    """按证据强度给可疑账户打分，用于图谱页面和总览排行。"""
    if not payload:
        return []
    evidence = payload.get("evidence") or {}
    scores: dict[str, dict] = {}

    def boost(account: str, points: float, tag: str, detail: str) -> None:
        row = scores.setdefault(
            account, {"account": account, "score": 0.0, "tags": set(), "details": []}
        )
        row["score"] += points
        row["tags"].add(tag)
        row["details"].append(detail)

    for item in evidence.get("gather") or []:
        account = item.get("account")
        if not account:
            continue
        boost(
            account,
            float(item.get("upstream_count") or 0) * 12,
            "归集",
            f"上游 {item.get('upstream_count')} 个，汇入约 {item.get('inflow')} USD",
        )
    for item in evidence.get("cycles") or []:
        for account in item.get("accounts") or []:
            boost(account, 32, "环形", f"{item.get('length')} 跳环，金额约 {item.get('amount')} USD")
    for item in evidence.get("fast_io") or []:
        account = item.get("account")
        if not account:
            continue
        boost(
            account,
            float(item.get("hit_count") or 0) * 9,
            "快进快出",
            f"转出约 {item.get('outflow')} USD",
        )

    rows = []
    for account, row in scores.items():
        rows.append(
            {
                "account": account,
                "score": round(row["score"], 1),
                "tags": " / ".join(sorted(row["tags"])),
                "detail": "；".join(row["details"][:3]),
            }
        )
    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows


def build_graph_payload(
    summary: dict,
    include_weak: bool = True,
    include_neighbors: bool = True,
    limit: int = 900,
) -> dict:
    """从 Neo4j 拉取可疑账户的 1 跳子图，并标注节点类别。"""
    from tools.graph_query import fetch_subgraph

    evidence = summary.get("evidence") or {}
    gather_accounts = [
        item["account"] for item in evidence.get("gather") or [] if item.get("account")
    ]
    cycle_accounts = [
        account
        for item in evidence.get("cycles") or []
        for account in item.get("accounts") or []
    ]
    fast_accounts = [
        item["account"] for item in evidence.get("fast_io") or [] if item.get("account")
    ]

    categories: dict[str, str] = {}
    for account in gather_accounts:
        categories[account] = "gather"
    for account in cycle_accounts:
        categories.setdefault(account, "cycle")
    for account in fast_accounts:
        categories.setdefault(account, "fast_io")

    strong = set(gather_accounts) | set(cycle_accounts)
    target = set(strong) | (set(fast_accounts) if include_weak else set())
    if not target:
        return {"nodes": [], "edges": [], "truncated": False, "categories": categories}

    data = fetch_subgraph(sorted(target), limit=limit)
    nodes = []
    for node in data.get("nodes") or []:
        node["category"] = categories.get(node["id"], "neighbor")
        nodes.append(node)

    edges = data.get("edges") or []
    if not include_neighbors:
        nodes = [node for node in nodes if node["id"] in target]
        edges = [
            edge
            for edge in edges
            if edge["src"] in target and edge["dst"] in target
        ]
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": data.get("truncated", False),
        "categories": categories,
    }


# ----------------------------------------------------------------------------
# 数据资产：data/new 大数据集目录、抽样生成、样本评测
# ----------------------------------------------------------------------------
def dataset_catalog() -> list[dict]:
    """数据资产目录（含抽样准备状态）。"""
    from tools.dataset_catalog import catalog_rows

    return catalog_rows()


def dataset_summary() -> dict:
    from tools.dataset_catalog import summary

    return summary()


def dataset_preview(relative_path: str, rows: int = 8) -> dict:
    """预览一个 CSV 的前 N 行（不加载全文件）。"""
    import pandas as pd

    path = Path(str(relative_path))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{relative_path}")
    try:
        frame = pd.read_csv(path, nrows=max(1, rows), encoding="utf-8-sig")
    except UnicodeDecodeError:
        frame = pd.read_csv(path, nrows=max(1, rows), encoding="gbk")
    return {
        "path": str(path),
        "columns": [str(col) for col in frame.columns],
        "records": frame.to_dict(orient="records"),
        "preview_rows": len(frame),
    }


def _prepared_group_items() -> list[dict]:
    from tools.dataset_catalog import flow_datasets, prepared_source_row

    items = []
    for dataset in flow_datasets():
        row = prepared_source_row(dataset["key"])
        if row:
            items.append(row)
    return items


def prepared_status(key: str) -> dict:
    """抽样准备状态（行数、账户数、标签数、生成时间）。"""
    from tools.dataset_catalog import prepared_status as _status

    return _status(key)


def prepared_label_counts(key: str) -> dict:
    """抽样标签分布（用于页面图表）。"""
    import pandas as pd

    from tools.dataset_catalog import prepared_labels_path

    path = prepared_labels_path(key)
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return {}
    label_col = next((col for col in frame.columns if col != "account"), None)
    if label_col is None:
        return {}
    positives = int(frame[label_col].fillna(0).astype(int).sum())
    return {label_col: {"positive": positives, "total": len(frame)}}


def prepared_overview(key: str) -> dict:
    """图结构数据（Elliptic）的抽样概览。"""
    from tools.dataset_catalog import PREPARED_DIR

    path = PREPARED_DIR / "elliptic_overview.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def flow_source_groups() -> list[dict]:
    """调度页数据源分组：内置演示 / 大数据抽样 / 已上传。"""
    groups: list[dict] = []

    demo_items: list[dict] = []
    aml_path = "data/synthetic_aml/transactions.csv"
    if (PROJECT_ROOT / aml_path).exists():
        demo_items.append(
            {
                "path": aml_path,
                "label": "合成 AML 数据集 · 42,175 笔（内置）",
                "group": "内置演示",
                "rows": 42175,
                "kind": "demo",
                "dataset_key": "demo-aml",
            }
        )
    sample_path = "data/sample_flow.csv"
    if (PROJECT_ROOT / sample_path).exists():
        demo_items.append(
            {
                "path": sample_path,
                "label": "中文演示流水 · 100 笔（内置）",
                "group": "内置演示",
                "rows": 100,
                "kind": "demo",
                "dataset_key": "demo-sample",
            }
        )
    if demo_items:
        groups.append({"group": "内置演示", "items": demo_items})

    prepared_items = _prepared_group_items()
    if prepared_items:
        groups.append({"group": "大数据抽样", "items": prepared_items})

    import_items: list[dict] = []
    imports_dir = DATA_DIR / "imports"
    if imports_dir.exists():
        for path in sorted(imports_dir.glob("*.csv")):
            try:
                info = inspect_flow_file(str(path))
            except Exception:  # noqa: BLE001
                continue
            import_items.append(
                {
                    "path": info["path"],
                    "label": info["label"],
                    "group": "已上传",
                    "rows": info["rows"],
                    "kind": "upload",
                    "dataset_key": "",
                }
            )
    if import_items:
        groups.append({"group": "已上传", "items": import_items})
    return groups


def flatten_flow_sources() -> list[dict]:
    """把分组数据源拍平，便于下拉框与查找。"""
    items: list[dict] = []
    for group in flow_source_groups():
        items.extend(group["items"])
    return items


def prepare_dataset_asset(key: str, rows: int | None = None) -> dict:
    """生成某个大数据集的确定性抽样（页面按钮/CLI 共用）。"""
    import sys

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.prepare_datasets import prepare_dataset

    return prepare_dataset(key, rows=rows)


def latest_completed_task() -> dict | None:
    """最近一次已完成任务（用于判断当前图谱来自哪个数据源）。"""
    from workbench import tasks as task_store

    for task in task_store.list_tasks(limit=100):
        if task.get("status") == task_store.STATUS_COMPLETED:
            return task
    return None


def _pattern_coverage(dataset_key: str, flagged: set[str]) -> dict:
    """IBM AML：把命中账户与 Patterns.txt 的 8 类洗钱模式做覆盖统计。"""
    from tools.dataset_catalog import get_dataset
    from tools.dataset_catalog import PROJECT_ROOT as ROOT

    dataset = get_dataset(dataset_key) or {}
    pattern_path = next(
        (ROOT / rel for rel in dataset.get("raw_paths", []) if str(rel).endswith(".txt")),
        None,
    )
    if pattern_path is None or not pattern_path.exists():
        return {"available": False}

    header = re.compile(r"BEGIN LAUNDERING ATTEMPT\s*-\s*(.+?)(?::|$)")
    attempts: list[tuple[str, set[str]]] = []
    current: str | None = None
    accounts: set[str] = set()

    def normalize(bank, account) -> str:
        try:
            bank_text = str(int(str(bank).strip()))
        except (TypeError, ValueError):
            bank_text = str(bank).strip()
        return f"{bank_text}:{str(account).strip()}"

    for line in pattern_path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        match = header.search(text)
        if match:
            if current is not None:
                attempts.append((current, accounts))
            current = match.group(1).strip().upper()
            accounts = set()
            continue
        if current and re.match(r"^\d{4}/\d{2}/\d{2}", text):
            parts = text.split(",")
            if len(parts) >= 5:
                accounts.add(normalize(parts[1], parts[2]))
                accounts.add(normalize(parts[3], parts[4]))
    if current is not None:
        attempts.append((current, accounts))

    by_type: dict[str, dict] = {}
    for name, members in attempts:
        entry = by_type.setdefault(name, {"attempts": 0, "accounts": set()})
        entry["attempts"] += 1
        entry["accounts"] |= members
    for entry in by_type.values():
        entry["flagged"] = len(flagged & entry["accounts"])

    total = len(by_type)
    covered = sum(1 for entry in by_type.values() if entry["flagged"] > 0)
    return {
        "available": True,
        "total_patterns": total,
        "covered_patterns": covered,
        "by_type": {
            name: {
                "attempts": entry["attempts"],
                "accounts": len(entry["accounts"]),
                "flagged": entry["flagged"],
            }
            for name, entry in sorted(by_type.items())
        },
    }


def compute_prepared_metrics(dataset_key: str) -> dict:
    """在“用抽样数据建好的当前图谱”上复算规则指标（标签只用于事后评测）。"""
    import pandas as pd

    from tools.dataset_catalog import get_dataset, prepared_labels_path
    from tools.graph_query import (
        find_circular_loops,
        find_fan_in,
        find_fast_in_fast_out,
        graph_summary,
    )

    labels_path = prepared_labels_path(dataset_key)
    if not labels_path.exists():
        raise FileNotFoundError(f"没有找到标签文件：{labels_path}，请先生成抽样")
    labels = pd.read_csv(labels_path, dtype={"account": str})
    label_col = next((col for col in labels.columns if col != "account"), "is_laundering")
    truth = set(labels.loc[labels[label_col].fillna(0).astype(int) == 1, "account"].astype(str))
    if not truth:
        raise ValueError("标签文件里没有正样本")

    fast_io = find_fast_in_fast_out()
    gather = find_fan_in()
    cycles = find_circular_loops()
    fast_accounts = {item["account"] for item in fast_io}
    gather_accounts = {item["account"] for item in gather}
    cycle_accounts = {account for item in cycles for account in item["accounts"]}

    def metrics(flagged: set[str]) -> dict:
        tp = flagged & truth
        precision = len(tp) / len(flagged) if flagged else 0.0
        recall = len(tp) / len(truth) if truth else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "flagged": len(flagged),
            "tp": len(tp),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    strong = gather_accounts | cycle_accounts
    all_flagged = strong | fast_accounts
    dataset = get_dataset(dataset_key) or {}
    return {
        "dataset_key": dataset_key,
        "dataset_name": dataset.get("name", dataset_key),
        "label_kind": "洗钱账户" if label_col == "is_laundering" else "诈骗账户",
        "truth": len(truth),
        "fast_io": metrics(fast_accounts),
        "gather": metrics(gather_accounts),
        "cycles": metrics(cycle_accounts),
        "strong": metrics(strong),
        "all": metrics(all_flagged),
        "pattern_coverage": _pattern_coverage(dataset_key, all_flagged),
        "graph": graph_summary(),
    }


# ----------------------------------------------------------------------------
# 报告索引
# ----------------------------------------------------------------------------
_HEADER_PATTERN = re.compile(r"^>\s*([^：]+)：(.*)$")


def parse_report_meta(path: Path) -> dict:
    meta: dict = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[:30]
    except Exception:  # noqa: BLE001
        return meta
    for line in lines:
        match = _HEADER_PATTERN.match(line.strip())
        if match:
            meta[match.group(1).strip()] = match.group(2).strip()
    return meta


def report_index() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []
    items = []
    for path in sorted(
        REPORTS_DIR.glob("*_report.md"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        meta = parse_report_meta(path)
        model_line = meta.get("模型", "")
        elapsed = ""
        tok_s = ""
        elapsed_match = re.search(r"生成耗时：([\d.]+)\s*秒", model_line)
        speed_match = re.search(r"生成速度：([\d.]+)\s*tok/s", model_line)
        if elapsed_match:
            elapsed = elapsed_match.group(1)
        if speed_match:
            tok_s = speed_match.group(1)
        items.append(
            {
                "name": path.name,
                "path": path,
                "case_id": meta.get("案件编号", path.stem),
                "generated_at": meta.get("生成时间", ""),
                "model": model_line.split("；")[0].replace("模型：", "") if model_line else "",
                "elapsed": elapsed,
                "tok_s": tok_s,
                "suspects": meta.get("可疑账户", ""),
                "fallback": "规则模板" in model_line or "大模型调用失败" in meta.get("说明", ""),
                "size_kb": round(path.stat().st_size / 1024, 1),
            }
        )
    return items


def latest_report() -> dict | None:
    items = report_index()
    return items[0] if items else None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"（读取失败：{exc}）"


# ----------------------------------------------------------------------------
# 节点健康检查
# ----------------------------------------------------------------------------
def local_ipv4() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:  # noqa: BLE001
        pass
    return sorted(ips) or ["127.0.0.1"]


def inference_is_remote() -> bool:
    """推理服务是否已配置为远端 Node2（非本机回环）。"""
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip().lower()
    return bool(base_url) and "127.0.0.1" not in base_url and "localhost" not in base_url


def node_status() -> list[dict]:
    """三节点状态：Node1 调度中心 / Node2 GPU 算力 / Node3 工具与图数据。"""
    hostname = socket.gethostname()
    targets = node_targets()
    nodes = [
        {
            "id": "node1",
            "index": "01",
            "name": "调度中心",
            "role": "核心调度与编排",
            "role_en": "Coordinator",
            "endpoint": f"{hostname} / 本机",
            "status": "online",
            "latency_ms": 0,
            "detail": "LangGraph Supervisor · 任务调度 · 调用日志",
        }
    ]

    # 第二台：GPU 算力中心（未配置远端时为占位；配置后做真实健康检查）
    try:
        from llms.remote_llm import check_connection, load_llm_config

        config = load_llm_config()
        if inference_is_remote():
            started = time.perf_counter()
            info = check_connection(timeout=4)
            latency = (time.perf_counter() - started) * 1000
            available = bool(info.get("available"))
            status = "online" if info.get("ok") and available else ("warn" if info.get("ok") else "offline")
            detail = f"模型：{config.model}"
            if info.get("ok") and not available:
                detail = "模型未找到 · 请检查 Node2 模型名"
            elif not info.get("ok"):
                detail = "推理服务未连接 · 请检查 Node2 Ollama"
            nodes.append(
                {
                    "id": "node2",
                    "index": "02",
                    "name": "GPU 算力中心",
                    "role": "GPU 推理与算力",
                    "role_en": "Inference",
                    "endpoint": config.base_url,
                    "status": status,
                    "latency_ms": round(latency, 1),
                    "detail": detail,
                }
            )
        else:
            # Node2 离线时的本地 Ollama 回退：也要显示真实在线状态，不能显示成“等待接入”
            started = time.perf_counter()
            info = check_connection(timeout=4)
            latency = (time.perf_counter() - started) * 1000
            available = bool(info.get("available"))
            ok = bool(info.get("ok"))
            if ok and available:
                status = "online"
                detail = f"本地 Ollama · 模型：{config.model}"
            elif ok:
                status = "warn"
                detail = "本地模型未找到 · 请检查 Ollama models"
            else:
                status = "offline"
                detail = "本地 Ollama 未连接"
            nodes.append(
                {
                    "id": "node2",
                    "index": "02",
                    "name": "GPU 算力中心（本地回退）",
                    "role": "本地推理与算力",
                    "role_en": "Inference",
                    "endpoint": f"{config.base_url}（本机）",
                    "status": status,
                    "latency_ms": round(latency, 1),
                    "detail": detail,
                }
            )
    except Exception as exc:  # noqa: BLE001
        nodes.append(
            {
                "id": "node2",
                "index": "02",
                "name": "GPU 算力中心",
                "role": "GPU 推理与算力",
                "role_en": "Inference",
                "endpoint": os.getenv("OLLAMA_BASE_URL", "未配置"),
                "status": "offline",
                "latency_ms": 0,
                "detail": "推理服务未连接 · 请检查 Node2 Ollama",
            }
        )

    # 第三台：工具与图数据节点（Neo4j 地址来自 .env 的 NEO4J_HOST + NEO4J_PORT）
    neo4j = neo4j_connection()
    neo4j_label = f"{neo4j['endpoint']} · {'本机' if neo4j['local'] else '远程'}"
    try:
        from tools.graph_query import graph_summary

        started = time.perf_counter()
        summary = graph_summary()
        latency = (time.perf_counter() - started) * 1000
        nodes.append(
            {
                "id": "node3",
                "index": "03",
                "name": "工具与图数据节点",
                "role": "工具执行与图数据",
                "role_en": "Tool & Graph",
                "endpoint": neo4j_label,
                "status": "online",
                "latency_ms": latency,
                "detail": (
                    f"Neo4j · pandas 解析 · "
                    f"{summary.get('accounts', 0)} 账户 / {summary.get('transfers', 0)} 转账"
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        nodes.append(
            {
                "id": "node3",
                "index": "03",
                "name": "工具与图数据节点",
                "role": "工具执行与图数据",
                "role_en": "Tool & Graph",
                "endpoint": neo4j_label,
                "status": "offline",
                "latency_ms": 0,
                "detail": "Neo4j 未连接 · 请启动图数据库或检查 NEO4J_HOST/NEO4J_PORT",
            }
        )

    return nodes


def debug_inference_status() -> dict:
    """当前推理服务状态（可能是远端 Node2，也可能是本机调试 Ollama）。"""
    result = {
        "ok": False,
        "remote": inference_is_remote(),
        "base_url": os.getenv("OLLAMA_BASE_URL", ""),
        "model": os.getenv("OLLAMA_MODEL", ""),
        "latency_ms": None,
        "error": "",
    }
    try:
        from llms.remote_llm import check_connection, load_llm_config

        config = load_llm_config()
        started = time.perf_counter()
        info = check_connection(timeout=3)
        result.update(
            {
                "ok": bool(info.get("ok") and info.get("available")),
                "base_url": config.base_url,
                "model": config.model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": info.get("error", ""),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def deployment_mode() -> str:
    """当前运行模式：开发调试 / 三机内网。"""
    if inference_is_remote():
        return "三机内网模式：Node2 推理服务已配置"
    return "开发调试模式：Node2 占位，本机 Ollama 临时推理"


def node_targets() -> dict:
    return {
        "node2": os.getenv("NODE2_TARGET_IP", DEFAULT_NODE_TARGETS["node2"]),
        "node3": os.getenv("NODE3_TARGET_IP", DEFAULT_NODE_TARGETS["node3"]),
    }


# ----------------------------------------------------------------------------
# 系统与安全
# ----------------------------------------------------------------------------
def system_info() -> dict:
    info = {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "local_ips": ", ".join(local_ipv4()),
        "cwd": str(PROJECT_ROOT),
        "memory": "未知",
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        info["memory"] = f"{memory.used / 1024**3:.1f} / {memory.total / 1024**3:.1f} GB（{memory.percent}%）"
        info["cpu_percent"] = f"{psutil.cpu_percent(interval=0.1):.1f}%"
    except Exception:  # noqa: BLE001
        pass
    return info


def external_network_check(timeout: float = 1.5) -> dict:
    """检测是否能访问外网（用于演示“断网自证”）。"""
    started = time.perf_counter()
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=timeout).close()
        return {
            "online": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "target": "1.1.1.1:53",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "online": False,
            "latency_ms": None,
            "target": "1.1.1.1:53",
            "error": type(exc).__name__,
        }


# ----------------------------------------------------------------------------
# 调度日志（Node1 记录任务下发/完成/失败、外网检测等事件）
# ----------------------------------------------------------------------------
def audit_event(kind: str, message: str, extra: dict | None = None) -> None:
    ensure_dirs()
    payload = {"ts": _now(), "kind": kind, "message": message}
    if extra:
        payload["extra"] = extra
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def read_audit(limit: int = 80) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    rows: list[dict] = []
    try:
        with AUDIT_LOG.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return []
    return list(reversed(rows[-limit:]))


# ----------------------------------------------------------------------------
# 评测指标（按需计算，答辩时现场点“重新评测”）
# ----------------------------------------------------------------------------
def compute_metrics() -> dict:
    """在 AML 数据集上复算三条规则与标签的精确率/召回率。"""
    import pandas as pd

    from tools.graph_query import (
        find_circular_loops,
        find_fan_in,
        find_fast_in_fast_out,
        graph_summary,
    )

    accounts = pd.read_csv(AML_DIR / "accounts.csv")
    rings = pd.read_csv(AML_DIR / "laundering_rings.csv")
    truth = set(accounts.loc[accounts["is_synthetic_mule"] == True, "account_id"])  # noqa: E712

    fast_io = find_fast_in_fast_out()
    gather = find_fan_in()
    cycles = find_circular_loops()

    fast_accounts = {item["account"] for item in fast_io}
    gather_accounts = {item["account"] for item in gather}
    cycle_accounts = {account for item in cycles for account in item["accounts"]}

    def metrics(flagged: set[str]) -> dict:
        tp = flagged & truth
        precision = len(tp) / len(flagged) if flagged else 0.0
        recall = len(tp) / len(truth) if truth else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "flagged": len(flagged),
            "tp": len(tp),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    all_flagged = gather_accounts | cycle_accounts | fast_accounts
    strong = gather_accounts | cycle_accounts
    detected_rings = 0
    for _, ring in rings.iterrows():
        members = set(str(ring["member_accounts"]).split(","))
        if members & all_flagged:
            detected_rings += 1

    return {
        "truth": len(truth),
        "rings": len(rings),
        "fast_io": metrics(fast_accounts),
        "gather": metrics(gather_accounts),
        "cycles": metrics(cycle_accounts),
        "strong": metrics(strong),
        "all": metrics(all_flagged),
        "detected_rings": detected_rings,
        "graph": graph_summary(),
    }
