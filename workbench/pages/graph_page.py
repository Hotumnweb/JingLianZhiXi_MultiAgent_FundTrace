# -*- coding: utf-8 -*-
"""资金图谱页：可疑账户关系网络 + 环形链 / 归集账户明细。"""

import streamlit as st

from workbench import graph_view, services, theme


def render() -> None:
    theme.section("图数据与工具", "Node3 · Neo4j 图数据库 + Cypher 查询")

    payload = services.latest_evidence()
    summary = services.evidence_summary(payload)
    if not payload:
        st.info("还没有图分析结果，请先到“元智能体调度”下发一次任务。")
        return

    control_cols = st.columns([2, 1, 1, 1])
    with control_cols[0]:
        scope = st.radio(
            "子图范围",
            ["强证据账户（归集 + 环形）", "强证据 + 快进快出"],
            horizontal=True,
        )
    with control_cols[1]:
        include_neighbors = st.toggle("显示关联邻居", value=True)
    with control_cols[2]:
        risk = services.risk_rows(payload)
        st.metric("可疑账户", summary["suspects"])
    with control_cols[3]:
        st.metric("证据强度 Top", risk[0]["account"] if risk else "—")

    include_weak = "快进快出" in scope
    try:
        graph_payload = services.build_graph_payload(
            summary, include_weak=include_weak, include_neighbors=include_neighbors
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取 Neo4j 子图失败：{type(exc).__name__}: {exc}")
        return

    if not graph_payload.get("nodes"):
        st.warning("没有可展示的节点，请确认 Neo4j 中已有 AML 数据集图谱。")
        return

    chart_col, side_col = st.columns([2.25, 1])
    with chart_col:
        st.plotly_chart(
            graph_view.build_network_figure(graph_payload),
            width="stretch",
        )
        caption = (
            f"节点 {len(graph_payload['nodes'])} 个 · 边 {len(graph_payload['edges'])} 条"
            f" · 布局：spring（离线计算）"
        )
        if graph_payload.get("truncated"):
            caption += " · 边数达到上限，仅展示部分"
        st.caption(caption)
    with side_col:
        theme.section("环形转账链", "时间递增 + 金额逐跳递减的闭环")
        cycles = (summary["evidence"].get("cycles") or [])[:6]
        if cycles:
            for item in cycles:
                chain = " → ".join(item["accounts"] + [item["accounts"][0]])
                st.markdown(
                    f"- `{item['length']} 跳` · {item['amount']} USD\n\n  {chain}"
                )
        else:
            st.caption("未命中环形转账")

        theme.section("归集账户", "24 小时内多上游汇入")
        gather = (summary["evidence"].get("gather") or [])[:6]
        if gather:
            for item in gather:
                st.markdown(
                    f"- `{item['account']}`：上游 {item['upstream_count']} 个，"
                    f"汇入 {item['inflow']} USD"
                )
        else:
            st.caption("未命中归集账户")

    theme.section("可疑账户证据强度排行", "按归集上游数 / 环形参与 / 快进快出命中综合评分")
    st.dataframe(risk[:20], width="stretch", hide_index=True)
    st.caption(
        "评分口径：归集上游数 ×12 + 环形参与 ×32 + 快进快出命中次数 ×9；"
        "仅用于排序展示，不参与规则判定。明细来自当前证据 JSON。"
    )

    with st.expander("Neo4j 复核查询", expanded=False):
        st.markdown("**① 图谱规模：账户数**")
        st.code("MATCH (n:Account) RETURN count(n) AS accounts;", language="cypher")
        st.markdown("**② 图谱规模：转账边数**")
        st.code("MATCH ()-[r:TRANSFER]->() RETURN count(r) AS transfers;", language="cypher")
        st.markdown("**③ 某个可疑账户的资金往来（示例，入账 + 出账）**")
        st.code(
            "MATCH p=(a:Account {id: 'ACC_01978'})-[r:TRANSFER]-(b:Account)\n"
            "RETURN p LIMIT 50;",
            language="cypher",
        )
        st.caption(
            "以上三条均已用 Neo4j 5.26.25 实测通过；在 Neo4j Browser 中请逐条执行，"
            "平台“Neo4j 操作台”支持一键执行。"
        )
