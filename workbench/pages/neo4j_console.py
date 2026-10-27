# -*- coding: utf-8 -*-
"""Neo4j 操作台：现场执行只读 Cypher，验证图谱结构与规则结果。"""

from __future__ import annotations

import csv
import io

import streamlit as st

from tools.graph_query import run_readonly_cypher
from workbench import services, theme

PRESETS = {
    "图谱规模（账户数）": "MATCH (n:Account) RETURN count(n) AS accounts",
    "图谱规模（转账边数）": "MATCH ()-[r:TRANSFER]->() RETURN count(r) AS transfers",
    "Top 入度账户（上游≥4）": """
        MATCH (up:Account)-[r:TRANSFER]->(hub:Account)
        WITH hub, count(DISTINCT up) AS upstream, sum(r.amount) AS inflow
        WHERE upstream >= 4
        RETURN hub.id AS account,
               upstream,
               round(inflow, 2) AS inflow_usd
        ORDER BY upstream DESC, inflow_usd DESC
        LIMIT 20
    """,
    "快进快出（48h / 95%）": """
        MATCH (a:Account)-[r1:TRANSFER]->(b:Account)-[r2:TRANSFER]->(c:Account)
        WHERE a <> c
          AND datetime(r2.time) >= datetime(r1.time)
          AND datetime(r2.time) <= datetime(r1.time) + duration({hours: 48})
          AND r2.amount >= r1.amount * 0.95
        RETURN b.id AS account,
               count(*) AS hits,
               round(sum(r2.amount), 2) AS outflow_usd
        ORDER BY hits DESC, outflow_usd DESC
        LIMIT 20
    """,
    "账户资金往来（ACC_01978）": """
        MATCH (a:Account {id: 'ACC_01978'})-[r:TRANSFER]->(b:Account)
        RETURN b.id AS receiver,
               r.amount AS amount_usd,
               r.time AS time
        ORDER BY r.time
        LIMIT 30
    """,
    "约束与索引": "SHOW CONSTRAINTS",
}


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _clear_console_result() -> None:
    """查询条件变化时清掉上一次结果，避免把旧表当成新查询结果。"""
    st.session_state.pop("neo4j_console_result", None)


def render() -> None:
    theme.section("Neo4j 操作台", "只读 Cypher · 图谱与规则复核")

    stats = services.graph_stats()
    cols = st.columns(4)
    cols[0].metric("账户节点", f"{stats.get('accounts', 0):,}")
    cols[1].metric("转账关系", f"{stats.get('transfers', 0):,}")
    cols[2].metric("数据库端", stats.get("error") and "离线" or "在线")
    cols[3].metric("操作模式", "只读查询")

    st.caption("只读查询，用于复核图谱结构与规则结果。")

    mode = st.radio(
        "查询方式",
        ["预设查询", "自定义 Cypher"],
        horizontal=True,
        on_change=_clear_console_result,
    )

    if mode == "预设查询":
        preset_name = st.selectbox(
            "选择查询",
            list(PRESETS.keys()),
            on_change=_clear_console_result,
        )
        query = PRESETS[preset_name].strip()
    else:
        query = st.text_area(
            "输入只读 Cypher",
            value="MATCH (n:Account) RETURN n.id AS account LIMIT 10",
            height=180,
            on_change=_clear_console_result,
        )

    st.code(query, language="cypher")

    action_cols = st.columns([1, 1, 3])
    run_clicked = action_cols[0].button("执行查询", type="primary", width="stretch")
    clear_clicked = action_cols[1].button("清除结果", width="stretch")

    if clear_clicked:
        st.session_state.pop("neo4j_console_result", None)

    if run_clicked:
        with st.spinner("Node3 正在执行 Cypher……"):
            try:
                result = run_readonly_cypher(query)
                st.session_state["neo4j_console_result"] = {
                    "query": query,
                    "result": result,
                }
                services.audit_event(
                    "neo4j_console",
                    "run_readonly_cypher",
                    {"rows": result["row_count"], "ms": result["elapsed_ms"]},
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state.pop("neo4j_console_result", None)
                st.error(f"查询失败：{type(exc).__name__}: {exc}")

    stored = st.session_state.get("neo4j_console_result")
    if not stored:
        st.info("选择预设或输入只读 Cypher，点击“执行查询”查看结果。")
        return

    result = stored["result"]
    executed_query = (stored.get("query") or "").strip()
    if executed_query != query.strip():
        st.warning(
            "当前显示的查询条件已经改变，下面是**上一次**执行的结果；"
            "请点击“执行查询”刷新，避免把旧结果当成新查询结果。"
        )
    st.caption(
        f"当前结果对应查询：`{executed_query[:100]}`"
    )
    st.caption(
        f"查询耗时 **{result['elapsed_ms']} ms** · 返回 **{result['row_count']}** 行"
        + ("（已截断到 200 行）" if result.get("truncated") else "")
    )
    if result["rows"]:
        st.dataframe(result["rows"], width="stretch", hide_index=True)
        st.download_button(
            "下载查询结果 CSV",
            data=_to_csv(result["rows"]),
            file_name="neo4j_query_result.csv",
            mime="text/csv",
            key="neo4j_result_csv",
        )
    else:
        st.warning("查询没有返回行；请确认图谱已建好，或查询条件是否过严。")

    with st.expander("现场可讲的 Neo4j 操作点", expanded=False):
        st.markdown(
            """
            - **图谱规模**：证明 3,492 个账户 / 42,175 条转账关系已落库；
            - **Top 入度**：现场展示“多上游汇入”的归集结构；
            - **快进快出**：用 Cypher 直接复算 Python 规则，证明规则可解释、可复核；
            - **账户资金往来**：点开单个可疑账户，展示其真实交易链路；
            - **约束**：说明 `Account(id)` 唯一约束保证建图与查询效率。
            """
        )
