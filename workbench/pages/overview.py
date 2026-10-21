# -*- coding: utf-8 -*-
"""调度总览：集群状态、数据分析结果、最近一次研判。"""

import streamlit as st

from workbench import graph_view, services, theme


def render() -> None:
    profile = services.dataset_profile()
    payload = services.latest_evidence()
    summary = services.evidence_summary(payload)
    graph = services.graph_stats()
    report = services.latest_report()
    nodes = services.node_status()
    risk = services.risk_rows(payload)

    theme.section("调度总览", "元智能体运行状态 · 三节点集群 · 数据分析结果")

    kpis = [
        ("交易流水", f"{profile['transactions']:,}", "合成 AML 数据集（USD）", theme.ACCENT),
        ("图账户节点", f"{graph.get('accounts', 0):,}", "Node3 · Neo4j", theme.PURPLE),
        ("可疑账户", summary["suspects"] if payload else "—", "等待任务执行" if not payload else "强证据优先", theme.RED),
        ("归集账户", summary["gather"] if payload else "—", "多层归集", theme.GOLD),
        ("环形转账链", summary["cycles"] if payload else "—", "闭环资金链", theme.GREEN),
        ("快进快出", summary["fast_io"] if payload else "—", "卡农过渡账户", theme.ACCENT),
    ]
    cols = st.columns(6)
    for col, (label, value, hint, accent) in zip(cols, kpis):
        col.markdown(theme.kpi_card(label, value, hint, accent), unsafe_allow_html=True)

    theme.section("三节点集群", "Node1 调度 · Node2 算力（占位） · Node3 工具与图数据")
    node_cols = st.columns(3)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)
    targets = services.node_targets()
    st.markdown(
        theme.pill(
            f"内网规划：Node2 {targets['node2']} · Node3 {targets['node3']}",
            "muted",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="jz-note">Node2 接入前，第一台使用内置 LangGraph 调度器和本机 Ollama 完成开发联调；'
        "Node2 接入后，任务拆解、多轮 AI 调用由 Qwen3-4B + Qwen-Agent 元智能体执行。</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        theme.section("图规则命中分布", "Node3 工具执行结果")
        st.plotly_chart(graph_view.rule_bar_figure(summary), width="stretch")
    with right:
        theme.section("证据强度排行", "归集上游数 / 环形参与 / 快进快出综合评分")
        st.plotly_chart(graph_view.risk_bar_figure(risk), width="stretch")

    theme.section("最近一次研判")
    if not report:
        st.markdown(
            '<div class="jz-note">暂无研判报告。到“元智能体调度”下发一次任务后，'
            "报告与证据会自动汇总到这里。</div>",
            unsafe_allow_html=True,
        )
        return

    cols = st.columns(4)
    cols[0].metric("案件编号", report["case_id"])
    cols[1].metric("可疑账户", report["suspects"] or "—")
    cols[2].metric("生成耗时", (report["elapsed"] + " s") if report["elapsed"] else "—")
    cols[3].metric("推理速度", (report["tok_s"] + " tok/s") if report["tok_s"] else "—")

    preview = services.read_text(report["path"])
    st.markdown(preview[:1600] + ("\n\n……" if len(preview) > 1600 else ""))
    st.caption(f"完整报告：{report['path']}")
