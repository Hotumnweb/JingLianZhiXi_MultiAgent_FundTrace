# -*- coding: utf-8 -*-
"""平台服务层：节点健康检查、数据概览、报告索引、审计日志、指标计算。

页面只调用这一层，不直接写 Cypher / HTTP 细节，便于：
1. 平台展示与业务逻辑解耦；
2. 每个能力都可被单独测试（见 scripts/platform_selfcheck.py）；
3. 后续把第三台/第四台节点接进来时，只改本文件。
"""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import socket
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AML_DIR = DATA_DIR / "synthetic_aml"
REPORTS_DIR = PROJECT_ROOT / "reports"
AUDIT_DIR = REPORTS_DIR / "audit"
AUDIT_LOG = AUDIT_DIR / "audit.jsonl"

DEFAULT_NODE_TARGETS = {
    "node2": "192.168.50.2",
    "node3": "192.168.50.3",
    "node4": "192.168.50.4",
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
        "dataset": manifest.get("dataset_name", "synthetic-aml"),
        "transactions": int(manifest.get("transaction_count") or 42175),
        "accounts": int(manifest.get("account_count") or 3500),
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


def node_status() -> list[dict]:
    """四节点健康状态（第一台本机 / 第二台推理 / 第三台图库审计 / 第四台演示）。"""
    hostname = socket.gethostname()
    nodes = [
        {
            "id": "node1",
            "index": "01",
            "name": "核心调度与编排工作台",
            "role": "核心调度与编排",
            "role_en": "Controller",
            "endpoint": f"{hostname} / 本机",
            "status": "online",
            "latency_ms": 0,
            "detail": "LangGraph · Streamlit · pandas · 平台服务层",
        }
    ]

    # 第二台：Ollama 推理节点（当前可能是本地 CPU 模拟）
    try:
        from llms.remote_llm import check_connection, load_llm_config

        config = load_llm_config()
        started = time.perf_counter()
        info = check_connection(timeout=3)
        latency = (time.perf_counter() - started) * 1000
        is_local = "127.0.0.1" in config.base_url or "localhost" in config.base_url
        status = "online" if info.get("ok") and info.get("available") else ("warn" if info.get("ok") else "offline")
        nodes.append(
            {
                "id": "node2",
                "index": "02",
                "name": "GPU 推理与算力节点",
                "role": "GPU 推理与算力",
                "role_en": "Inference",
                "endpoint": config.base_url + ("（本地 CPU 调试）" if is_local else "（内网 GPU 节点）"),
                "status": status,
                "latency_ms": latency,
                "detail": f"模型：{config.model}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        nodes.append(
            {
                "id": "node2",
                "index": "02",
                "name": "GPU 推理与算力节点",
                "role": "GPU 推理与算力",
                "role_en": "Inference",
                "endpoint": os.getenv("OLLAMA_BASE_URL", "未配置"),
                "status": "offline",
                "latency_ms": 0,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    # 第三台：Neo4j 图数据引擎与审计节点
    try:
        from tools.graph_query import graph_summary

        started = time.perf_counter()
        summary = graph_summary()
        latency = (time.perf_counter() - started) * 1000
        nodes.append(
            {
                "id": "node3",
                "index": "03",
                "name": "图数据引擎与审计节点",
                "role": "图数据与安全审计",
                "role_en": "Database & Audit",
                "endpoint": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                "status": "online",
                "latency_ms": latency,
                "detail": f"{summary.get('accounts', 0)} 个账户 / {summary.get('transfers', 0)} 条转账",
            }
        )
    except Exception as exc:  # noqa: BLE001
        nodes.append(
            {
                "id": "node3",
                "index": "03",
                "name": "图数据引擎与审计节点",
                "role": "图数据与安全审计",
                "role_en": "Database & Audit",
                "endpoint": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                "status": "offline",
                "latency_ms": 0,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    # 第四台：演示汇报终端
    nodes.append(
        {
            "id": "node4",
            "index": "04",
            "name": "演示汇报与终端控制",
            "role": "演示与终端控制",
            "role_en": "Presentation",
            "endpoint": "浏览器客户端 / HDMI 大屏",
            "status": "online",
            "latency_ms": 0,
            "detail": "当前访问终端 · Streamlit 前端",
        }
    )
    return nodes


def deployment_mode() -> str:
    """当前是单机联调还是双机部署。"""
    base_url = os.getenv("OLLAMA_BASE_URL", "")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return "单机联调模式（本地 Ollama 模拟 GPU 节点）"
    return "双机内网模式（GPU 推理节点已接入）"


def node_targets() -> dict:
    return {
        "node2": os.getenv("NODE2_TARGET_IP", DEFAULT_NODE_TARGETS["node2"]),
        "node3": os.getenv("NODE3_TARGET_IP", DEFAULT_NODE_TARGETS["node3"]),
        "node4": os.getenv("NODE4_TARGET_IP", DEFAULT_NODE_TARGETS["node4"]),
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
# 审计日志（第三台节点的本地替身，接入 Wireshark 后可替换）
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
