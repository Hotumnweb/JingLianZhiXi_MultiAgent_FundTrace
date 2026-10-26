# -*- coding: utf-8 -*-
"""Neo4j 图查询工具：账户是节点，转账是边。

图模型：
    节点  (:Account {id, tx_count})
    关系  (:Account)-[:TRANSFER {amount, time, summary}]->(:Account)

三条图规则（对应电诈/洗钱资金流侦查中的典型结构）：

1. 快进快出（pass-through）：账户收款后 N 小时内转出 ≥95% 的金额，
   且账户整体交易笔数较少（卡农账户特征）。单独使用时误报较多，
   在研判中作为**辅助证据**。

2. 多层归集（fan-in aggregation）：24 小时内 ≥4 个不同上游账户
   向同一账户汇入，且各笔金额高度接近（离散系数 CV ≤ 0.15）。
   对应数据集里的 Fan-In Aggregation（水房归集）。**强证据**。

3. 环形转账（circular loop）：3~6 跳的闭环，时间严格递增、
   每一跳金额递减 0~10%。对应数据集里的 Circular Loop。**强证据**。

阈值来自对 data/synthetic_aml 数据集的离线评测，
见 scripts/evaluate_on_synthetic_aml.py。
"""

import os
import re
import time
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_USER = os.getenv("NEO4J_USER", "neo4j")
_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# 惰性创建：import 本模块不会立刻连接数据库，便于先做代码校验
_driver = None

_SCHEMA_QUERY = (
    "CREATE CONSTRAINT account_id_unique IF NOT EXISTS "
    "FOR (a:Account) REQUIRE a.id IS UNIQUE"
)

_WRITE_QUERY = """
UNWIND $batch AS row
MERGE (a:Account {id: row.from_account})
MERGE (b:Account {id: row.to_account})
CREATE (a)-[:TRANSFER {amount: row.amount, time: row.time, summary: row.summary}]->(b)
"""

_INVALID_ACCOUNTS = {"", "nan", "none", "null"}


def get_driver():
    """惰性创建并复用 Neo4j 驱动。"""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(_URI, auth=(_USER, _PASSWORD))
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def ensure_schema() -> None:
    """建立 :Account(id) 唯一约束（MERGE 写入 4 万条边时必须，否则会 O(n²) 扫表）。"""
    with get_driver().session() as session:
        session.run(_SCHEMA_QUERY)


def clear_graph() -> None:
    """清空整个图谱（第一版每次重新建图，保证结果可复现）。"""
    with get_driver().session() as session:
        session.run("MATCH (n) DETACH DELETE n")


def _write_batch(tx, rows: list[dict]) -> None:
    tx.run(_WRITE_QUERY, {"batch": rows})


def _update_tx_counts(tx, counts: list[dict]) -> None:
    tx.run(
        "UNWIND $counts AS c MATCH (a:Account {id: c.id}) SET a.tx_count = c.count",
        {"counts": counts},
    )


def _prepare_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        from_account = str(record.get("from_account", "")).strip()
        to_account = str(record.get("to_account", "")).strip()
        if from_account.lower() in _INVALID_ACCOUNTS or not from_account:
            continue
        if to_account.lower() in _INVALID_ACCOUNTS or not to_account:
            continue
        try:
            amount = float(record.get("amount"))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "from_account": from_account,
                "to_account": to_account,
                "amount": amount,
                "time": str(record.get("trade_time", "")),
                "summary": str(record.get("summary", "")),
            }
        )
    return rows


def write_transactions(
    records: list[dict],
    replace: bool = True,
    batch_size: int = 5000,
) -> int:
    """把交易记录批量写入 Neo4j，返回实际写入的转账边数量。

    replace=True 时先清空图谱；每条转账都是 TRANSFER 边，
    并在 Account 节点上记录 tx_count（总交易笔数），供"快进快出"规则过滤低活跃账户。
    """
    rows = _prepare_rows(records)
    if not rows:
        return 0

    ensure_schema()
    if replace:
        clear_graph()

    counts = defaultdict(int)
    for row in rows:
        counts[row["from_account"]] += 1
        counts[row["to_account"]] += 1
    count_rows = [{"id": account, "count": count} for account, count in counts.items()]

    with get_driver().session() as session:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            session.execute_write(_write_batch, chunk)
        session.execute_write(_update_tx_counts, count_rows)

    return len(rows)


def graph_summary() -> dict:
    """获取当前图谱的账户数和边数，供 Agent 打印日志用。"""
    with get_driver().session() as session:
        accounts = session.run("MATCH (n:Account) RETURN count(n) AS c").single()["c"]
        transfers = session.run("MATCH ()-[r:TRANSFER]->() RETURN count(r) AS c").single()["c"]
    return {"accounts": accounts, "transfers": transfers}


def find_fast_in_fast_out(
    window_hours: int = 48,
    ratio: float = 0.95,
    max_account_tx: int = 8,
    limit: int = 50,
) -> list[dict]:
    """快进快出：收款后 N 小时内转出 ≥ratio 的金额，且账户交易笔数较少。

    返回 [{"account": ..., "hit_count": ..., "outflow": ...}]，
    按命中次数、转出金额降序。
    """
    with get_driver().session() as session:
        result = session.run(
            """
            MATCH (a:Account)-[r1:TRANSFER]->(b:Account)-[r2:TRANSFER]->(c:Account)
            WHERE a <> c
              AND datetime(r2.time) >= datetime(r1.time)
              AND datetime(r2.time) <= datetime(r1.time) + duration({hours: $window_hours})
              AND r2.amount >= r1.amount * $ratio
              AND coalesce(b.tx_count, 0) <= $max_account_tx
            RETURN b.id AS account,
                   count(*) AS hit_count,
                   round(sum(r2.amount), 2) AS outflow
            ORDER BY hit_count DESC, outflow DESC
            LIMIT $limit
            """,
            {
                "window_hours": window_hours,
                "ratio": ratio,
                "max_account_tx": max_account_tx,
                "limit": limit,
            },
        )
        return [dict(record) for record in result]


def find_fan_in(
    window_hours: int = 24,
    min_upstream: int = 4,
    max_cv: float = 0.15,
    limit: int = 50,
) -> list[dict]:
    """多层归集：窗口内 ≥min_upstream 个上游账户汇入，且金额离散度 ≤max_cv。

    返回 [{"account", "window_start", "upstream_count", "inflow", "amount_cv"}]，
    同一个账户可能命中多个滑动窗口，取上游账户数最多的那个窗口。
    """
    query = """
    MATCH (up:Account)-[r:TRANSFER]->(hub:Account)
    WITH hub, collect({sender: up.id, t: datetime(r.time), amount: r.amount}) AS transfers
    WHERE size(transfers) >= $min_upstream
    UNWIND transfers AS anchor
    WITH hub, anchor,
         [x IN transfers
          WHERE x.t >= anchor.t
            AND x.t <= anchor.t + duration({hours: $window_hours})] AS window_rows
    WHERE size(window_rows) >= $min_upstream
    UNWIND window_rows AS row
    WITH hub,
         anchor.t AS window_start,
         count(DISTINCT row.sender) AS upstream_count,
         sum(row.amount) AS inflow,
         avg(row.amount) AS mean_amount,
         stDev(row.amount) AS sd_amount
    WHERE upstream_count >= $min_upstream
      AND mean_amount > 0
      AND sd_amount / mean_amount <= $max_cv
    RETURN hub.id AS account,
           window_start,
           upstream_count,
           round(inflow, 2) AS inflow,
           round(sd_amount / mean_amount, 4) AS amount_cv
    ORDER BY upstream_count DESC, inflow DESC
    LIMIT 1000
    """
    best: dict[str, dict] = {}
    with get_driver().session() as session:
        for record in session.run(
            query,
            {
                "window_hours": window_hours,
                "min_upstream": min_upstream,
                "max_cv": max_cv,
            },
        ):
            item = dict(record)
            item["window_start"] = str(item.get("window_start", ""))
            account = item["account"]
            current = best.get(account)
            if current is None or item["upstream_count"] > current["upstream_count"]:
                best[account] = item

    ordered = sorted(
        best.values(),
        key=lambda item: (item["upstream_count"], item["inflow"]),
        reverse=True,
    )
    return ordered[:limit]


def _load_edges() -> list[tuple[str, str, float, str]]:
    """从 Neo4j 读取全部转账边，供环形转账检测使用。"""
    with get_driver().session() as session:
        result = session.run(
            """
            MATCH (a:Account)-[r:TRANSFER]->(b:Account)
            RETURN a.id AS src, b.id AS dst, r.amount AS amount, r.time AS time
            """
        )
        return [
            (record["src"], record["dst"], float(record["amount"]), record["time"])
            for record in result
        ]


def _cycle_details(adj: dict, nodes: list[str]) -> dict | None:
    """按时间顺序沿环取每一跳的 (时间, 金额)，返回环的金额与时间跨度。"""
    hops = []
    last_time = None
    for index, node in enumerate(nodes):
        next_node = nodes[(index + 1) % len(nodes)]
        edge = None
        for timestamp, dst, amount in adj.get(node, ()):
            if dst == next_node and (last_time is None or timestamp > last_time):
                edge = (timestamp, amount)
                break
        if edge is None:
            return None
        hops.append(edge)
        last_time = edge[0]
    return {
        "amount": round(max(amount for _, amount in hops), 2),
        "span_hours": round((hops[-1][0] - hops[0][0]) / 3600, 2),
    }


def find_circular_loops(
    min_length: int = 3,
    max_length: int = 6,
    span_days: int = 7,
    ratio_lo: float = 0.90,
    ratio_hi: float = 1.10,
    limit: int = 20,
) -> list[dict]:
    """环形转账：检测时间递增、金额逐跳衰减的闭环资金链。

    返回 [{"accounts": [...], "length": 4, "amount": ..., "span_hours": ...}]
    按涉案金额降序。
    """
    adj: dict[str, list] = defaultdict(list)
    for src, dst, amount, time_text in _load_edges():
        try:
            timestamp = int(datetime.fromisoformat(time_text).timestamp())
        except (TypeError, ValueError):
            continue
        adj[src].append((timestamp, dst, amount))
    for edges in adj.values():
        edges.sort()

    span_seconds = span_days * 24 * 3600
    found: dict[tuple, list[str]] = {}

    def canonical(path: list[str]) -> tuple:
        rotations = [tuple(path[i:] + path[:i]) for i in range(len(path))]
        return min(rotations)

    for start in list(adj):
        path = [start]
        path_set = {start}

        def dfs(node: str, last_amount: float, last_time: int, first_time: int) -> None:
            for timestamp, nxt, amount in adj.get(node, ()):
                if timestamp <= last_time:
                    continue
                if timestamp - first_time > span_seconds:
                    break
                if not (ratio_lo * last_amount <= amount <= ratio_hi * last_amount):
                    continue
                if nxt == start:
                    if len(path) >= min_length:
                        found.setdefault(canonical(path), list(path))
                    continue
                if nxt in path_set or len(path) >= max_length:
                    continue
                path.append(nxt)
                path_set.add(nxt)
                dfs(nxt, amount, timestamp, first_time)
                path.pop()
                path_set.remove(nxt)

        for timestamp, nxt, amount in adj[start]:
            if nxt == start:
                continue
            path.append(nxt)
            path_set.add(nxt)
            dfs(nxt, amount, timestamp, timestamp)
            path.pop()
            path_set.remove(nxt)

    cycles = []
    for nodes in found.values():
        detail = _cycle_details(adj, nodes)
        if detail is None:
            continue
        cycles.append(
            {
                "accounts": nodes,
                "length": len(nodes),
                "amount": detail["amount"],
                "span_hours": detail["span_hours"],
            }
        )

    cycles.sort(key=lambda item: item["amount"], reverse=True)
    return cycles[:limit]


def fetch_subgraph(account_ids: list[str], limit: int = 900) -> dict:
    """拉取一批账户的 1 跳交易子图，用于平台资金网络可视化。

    返回 {"nodes": [{"id", "tx_count"}], "edges": [{"src", "dst", "amount", "time"}], "truncated": bool}
    """
    ids = [str(account) for account in account_ids if account]
    if not ids:
        return {"nodes": [], "edges": [], "truncated": False}

    with get_driver().session() as session:
        result = session.run(
            """
            MATCH (a:Account)-[r:TRANSFER]->(b:Account)
            WHERE a.id IN $ids OR b.id IN $ids
            RETURN a.id AS src, b.id AS dst,
                   r.amount AS amount, r.time AS time,
                   a.tx_count AS src_tx, b.tx_count AS dst_tx
            LIMIT $limit
            """,
            {"ids": ids, "limit": limit},
        )
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        for record in result:
            src = record["src"]
            dst = record["dst"]
            nodes.setdefault(src, {"id": src, "tx_count": record["src_tx"] or 0})
            nodes.setdefault(dst, {"id": dst, "tx_count": record["dst_tx"] or 0})
            edges.append(
                {
                    "src": src,
                    "dst": dst,
                    "amount": round(float(record["amount"] or 0), 2),
                    "time": str(record["time"] or ""),
                }
            )

    return {"nodes": list(nodes.values()), "edges": edges, "truncated": len(edges) >= limit}


# 只允许现场执行“读查询”；写操作必须走任务流程或 Neo4j Browser
_READONLY_PREFIXES = ("MATCH", "RETURN", "WITH", "UNWIND", "SHOW")
_FORBIDDEN_KEYWORDS = {
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "DROP",
    "LOAD",
    "FOREACH",
    "CALL",
    "ALTER",
    "RENAME",
    "GRANT",
    "DENY",
    "REVOKE",
}


def _json_value(value):
    """把 Neo4j 的 Node/Relationship/Path 等对象转成可展示的值。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def run_readonly_cypher(query: str, limit: int = 200) -> dict:
    """执行只读 Cypher，返回列名、行数据、行数和耗时。

    UI 的“Neo4j 操作台”使用本函数；用于现场验证图查询与规则结果。
    禁止写操作，避免误改演示数据。
    """
    text = (query or "").strip().rstrip(";").strip()
    if not text:
        raise ValueError("Cypher 不能为空")
    upper = text.upper()
    if not upper.startswith(_READONLY_PREFIXES):
        raise ValueError("只允许 MATCH / RETURN / WITH / UNWIND / SHOW 开头的只读查询")
    tokens = set(re.findall(r"\b[A-Z_]+\b", upper))
    blocked = tokens & _FORBIDDEN_KEYWORDS
    if blocked:
        raise ValueError(f"检测到写操作关键字：{', '.join(sorted(blocked))}；操作台仅允许只读查询")

    started = time.perf_counter()
    with get_driver().session() as session:
        result = session.run(text)
        columns = list(result.keys())
        rows: list[dict] = []
        truncated = False
        for index, record in enumerate(result):
            if index >= limit:
                truncated = True
                break
            rows.append({key: _json_value(value) for key, value in record.items()})
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
    }
