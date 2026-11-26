# -*- coding: utf-8 -*-
"""数据资产目录：描述 data/ 下可用数据集、规模、标签与推荐用途。

平台里“数据资产”页与“元智能体调度”页的数据源下拉都读取本模块，
避免把数据集信息散落在页面代码里。

数据集分三类：
- flow     可解析成资金流水的 CSV（能进 Neo4j 建图、跑三条图规则）
- graph    图结构数据（节点/边，当前用于展示与后续 GNN/社区发现）
- tabular  表格欺诈数据（无收付款双方账户对，适合做对照实验）

`data/new/` 下的原始数据体积很大（合计约 2.5 GB），不直接参与前端扫描；
先用 scripts/prepare_datasets.py 生成确定性抽样到 `data/prepared/`，
平台只消费抽样文件（`<key>_flow.csv` / `<key>_labels.csv` / `<key>_meta.json`）。
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"
DATA_DIR = PROJECT_ROOT / "data"

# 相对路径统一用 posix 风格，方便页面展示和跨平台
DATASETS: list[dict] = [
    {
        "key": "demo-aml",
        "name": "合成 AML 数据集（内置）",
        "group": "内置数据",
        "kind": "flow",
        "raw_paths": ["data/synthetic_aml/transactions.csv"],
        "raw_rows": 42175,
        "raw_accounts": 3500,
        "scale_text": "42,175 笔 / 3,500 账户 / 22 团伙",
        "labels": {
            "available": True,
            "type": "合成标签",
            "detail": "132 个洗钱账户 · 22 个团伙（环形 + 集散）",
        },
        "license": "CC0-1.0（纯虚构合成数据）",
        "source": "项目内置",
        "role": "稳定基线：默认分析数据，三条规则与精确率/召回率复算最快",
        "demo": "42,175 笔建图约 10 秒；建议作为开场默认数据",
        "prepare_note": "无需抽样（直接可用）",
        "prepared": False,
        "primary_file": "data/synthetic_aml/transactions.csv",
    },
    {
        "key": "demo-sample",
        "name": "中文流水样例（100 条）",
        "group": "内置数据",
        "kind": "flow",
        "raw_paths": ["data/sample_flow.csv"],
        "raw_rows": 100,
        "raw_accounts": None,
        "scale_text": "100 笔中文流水",
        "labels": {"available": False, "type": "无标签", "detail": "验证中文列名解析与格式识别"},
        "license": "项目内置（虚构）",
        "source": "项目内置",
        "role": "冒烟测试：验证“交易时间/金额/付款账号/收款账号”中文列映射",
        "demo": "秒级跑通；适合讲“任意中文流水可直接解析”",
        "prepare_note": "无需抽样（直接可用）",
        "prepared": False,
        "primary_file": "data/sample_flow.csv",
    },
    {
        "key": "ibm-hi-small",
        "name": "IBM AML · HI-Small",
        "group": "大规模流水",
        "kind": "flow",
        "raw_paths": ["data/new/one/HI-Small_Trans.csv", "data/new/one/HI-Small_Patterns.txt"],
        "raw_rows": 5078345,
        "raw_accounts": 515000,
        "scale_text": "507.8 万笔 / 51.5 万账户 / 洗钱率 1:981",
        "labels": {
            "available": True,
            "type": "交易级 Is Laundering + 8 类洗钱模式",
            "detail": "洗钱交易 5,177 笔，Patterns.txt 标注 8 种洗钱模式",
        },
        "license": "CDLA-Sharing-1.0",
        "source": "Kaggle · ealtman2019/ibm-transactions-for-anti-money-laundering-aml",
        "role": "主推的“真实规模”验证：银行多币种流水、8 类洗钱模式、规则泛化指标",
        "demo": "支持抽 5 万笔（保留全部标签交易）建图，约 10~20 秒",
        "prepare_note": "按洗钱交易全保留 + 正常交易确定性抽样，生成 5 万笔样本",
        "prepared": True,
        "prepare_rows": 50000,
    },
    {
        "key": "ibm-li-small",
        "name": "IBM AML · LI-Small",
        "group": "大规模流水",
        "kind": "flow",
        "raw_paths": ["data/new/two/LI-Small_Trans.csv", "data/new/two/LI-Small_Patterns.txt"],
        "raw_rows": 6924049,
        "raw_accounts": 705000,
        "scale_text": "692.4 万笔 / 70.5 万账户 / 洗钱率 1:1942",
        "labels": {
            "available": True,
            "type": "交易级 Is Laundering",
            "detail": "洗钱交易 3,565 笔（低洗钱率版本）",
        },
        "license": "CDLA-Sharing-1.0",
        "source": "Kaggle · ealtman2019/ibm-transactions-for-anti-money-laundering-aml",
        "role": "低洗钱率对照：同样规则在 1:1942 样本上的精确率/召回率",
        "demo": "可选：抽 5 万笔做第二组对照，体现“误报控制”",
        "prepare_note": "按洗钱交易全保留 + 正常交易确定性抽样",
        "prepared": True,
        "prepare_rows": 50000,
    },
    {
        "key": "paysim",
        "name": "PaySim 移动支付欺诈",
        "group": "大规模流水",
        "kind": "flow",
        "raw_paths": ["data/new/paysim1/PS_20174392719_1491204439457_log.csv"],
        "raw_rows": 6362620,
        "raw_accounts": None,
        "scale_text": "636.3 万笔 / 诈骗交易 8,213 笔",
        "labels": {
            "available": True,
            "type": "交易级 isFraud",
            "detail": "诈骗交易 8,213 笔（TRANSFER / CASH_OUT 场景）",
        },
        "license": "Kaggle 数据集许可（仅限本地分析使用）",
        "source": "Kaggle · ealaxi/paysim1",
        "role": "跨场景验证：换一套移动支付数据，同一套解析/建图/规则代码不改",
        "demo": "抽 10 万笔（诈骗交易 + 关联资金链全保留）做跨场景验证",
        "prepare_note": "诈骗交易全保留 + 诈骗账户关联交易（补全资金链）+ 正常交易确定性抽样",
        "prepared": True,
        "prepare_rows": 100000,
    },
    {
        "key": "elliptic",
        "name": "Elliptic 比特币交易图",
        "group": "图结构数据",
        "kind": "graph",
        "raw_paths": [
            "data/new/elliptic/elliptic_bitcoin_dataset/elliptic_txs_edgelist.csv",
            "data/new/elliptic/elliptic_bitcoin_dataset/elliptic_txs_classes.csv",
            "data/new/elliptic/elliptic_bitcoin_dataset/elliptic_txs_features.csv",
        ],
        "raw_rows": 234355,
        "raw_accounts": 203769,
        "scale_text": "203,769 节点 / 234,355 边 / illicit 4,545",
        "labels": {
            "available": True,
            "type": "节点级 illicit / licit / unknown",
            "detail": "illicit 4,545 · licit 42,019 · unknown 157,205",
        },
        "license": "Kaggle 数据集许可（仅限本地分析使用）",
        "source": "Kaggle · ellipticco/elliptic-data-set",
        "role": "扩展方向：图结构数据、社区发现、风险传播、GNN；不含金额，不进主规则流水线",
        "demo": "抽样前 20 个时间步展示“同一批数据，图模型能做什么”",
        "prepare_note": "按时间步抽子图 + 统计高连接度节点中的 illicit 占比",
        "prepared": True,
    },
    {
        "key": "ieee-fraud",
        "name": "IEEE-CIS 交易欺诈",
        "group": "表格对照",
        "kind": "tabular",
        "raw_paths": ["data/new/ieee-fraud/train_transaction.csv"],
        "raw_rows": 590540,
        "raw_accounts": None,
        "scale_text": "590,540 笔 / 394 列 / 欺诈 20,663 笔（3.5%）",
        "labels": {
            "available": True,
            "type": "交易级 isFraud + 身份表",
            "detail": "训练集欺诈率约 3.5%；无收付款双方账户列",
        },
        "license": "IEEE-CIS 竞赛数据许可（仅限本地分析使用）",
        "source": "Kaggle 竞赛 ieee-fraud-detection（经 HuggingFace 镜像获取）",
        "role": "对照实验：表格特征模型 vs 图结构规则，解释“为什么资金穿透需要图”",
        "demo": "作为表格模型对照与能力边界说明，不接入主流程",
        "prepare_note": "不生成流水样本（缺少收付款双方账户，无法建资金图）",
        "prepared": False,
    },
]

DATASET_MAP = {item["key"]: item for item in DATASETS}


def list_datasets() -> list[dict]:
    """返回数据集目录（原始顺序）。"""
    return [dict(item) for item in DATASETS]


def get_dataset(key: str) -> dict | None:
    item = DATASET_MAP.get(key)
    return dict(item) if item else None


def flow_datasets() -> list[dict]:
    return [dict(item) for item in DATASETS if item["kind"] == "flow"]


def prepared_flow_path(key: str) -> Path:
    return PREPARED_DIR / f"{key}_flow.csv"


def prepared_labels_path(key: str) -> Path:
    return PREPARED_DIR / f"{key}_labels.csv"


def prepared_meta_path(key: str) -> Path:
    return PREPARED_DIR / f"{key}_meta.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def prepared_status(key: str) -> dict:
    """返回某个数据集的抽样准备状态。

    ready=True 时带上 meta（行数、账户数、标签数、生成时间等）。
    流水数据集要求 flow CSV 存在；图结构数据集只要求 meta/边文件存在。
    """
    dataset = get_dataset(key) or {}
    kind = dataset.get("kind", "flow")
    meta_path = prepared_meta_path(key)
    flow_path = prepared_flow_path(key)
    labels_path = prepared_labels_path(key)
    meta = _read_json(meta_path) if meta_path.exists() else {}
    if kind == "graph":
        edges_path = PREPARED_DIR / "elliptic_edges.csv"
        ready = bool(meta and edges_path.exists())
    else:
        ready = bool(meta and flow_path.exists())
    return {
        "key": key,
        "name": dataset.get("name", key),
        "kind": kind,
        "prepared": bool(dataset.get("prepared")),
        "ready": ready,
        "meta": meta,
        "flow_path": str(flow_path) if (kind != "graph" and flow_path.exists()) else "",
        "labels_path": str(labels_path) if labels_path.exists() else "",
        "meta_path": str(meta_path) if meta_path.exists() else "",
        "generated_at": meta.get("generated_at", ""),
    }


def catalog_rows() -> list[dict]:
    """页面用的目录行：数据集信息 + 抽样状态。"""
    rows = []
    for item in DATASETS:
        row = dict(item)
        row.update(
            {
                "prepared_status": prepared_status(item["key"]),
                "primary_file": item.get("primary_file", ""),
                "kind_label": {
                    "flow": "资金流水",
                    "graph": "图结构",
                    "tabular": "表格数据",
                }.get(item["kind"], item["kind"]),
            }
        )
        rows.append(row)
    return rows


def summary() -> dict:
    """目录汇总：数据集数量、原始规模、可抽样数量、已准备数量。"""
    rows = catalog_rows()
    flow_rows = [row for row in rows if row["kind"] == "flow"]
    prepared_ready = [row for row in rows if row["prepared_status"]["ready"]]
    return {
        "dataset_count": len(rows),
        "flow_count": len(flow_rows),
        "raw_transactions": sum(int(row.get("raw_rows") or 0) for row in flow_rows),
        "prepared_count": len(prepared_ready),
        "prepared_keys": [row["key"] for row in prepared_ready],
        "label_count": sum(1 for row in rows if row["labels"]["available"]),
        "raw_size_mb": round(_raw_size_bytes() / 1024 / 1024, 1),
    }


def _raw_size_bytes() -> int:
    total = 0
    for item in DATASETS:
        for rel in item.get("raw_paths") or []:
            path = PROJECT_ROOT / rel
            if path.exists():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    return total


def prepared_source_row(key: str) -> dict | None:
    """把已准备样本转成“数据源下拉”条目。"""
    status = prepared_status(key)
    if not status["ready"]:
        return None
    dataset = get_dataset(key) or {}
    meta = status["meta"]
    rows = int(meta.get("rows") or 0)
    label = f"{dataset.get('name', key)} · 抽样 {rows:,} 笔"
    return {
        "path": status["flow_path"],
        "label": label,
        "group": "大数据抽样",
        "dataset_key": key,
        "rows": rows,
        "kind": "prepared",
        "meta": meta,
        "dataset": dataset,
    }
