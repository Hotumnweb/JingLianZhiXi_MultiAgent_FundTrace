# -*- coding: utf-8 -*-
"""总览大屏：KPI、四节点拓扑、图规则命中、最近研判。"""

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

    theme.section("作战总览", "四节点拓扑 · 数据画像 · 图规则命中 · 最近一次研判")

    speed = f"{report['tok_s']} tok/s" if report and report.get("tok_s") else "—"
    kpis = [
        ("交易流水", f"{profile['transactions']:,}", "合成 AML 数据集（USD）", theme.ACCENT),
        ("图账户节点", f"{graph.get('accounts', 0):,}", "Neo4j :Account", theme.PURPLE),
        ("可疑账户", summary["suspects"] if payload else "—", f"强证据 {summary['strong']} / 辅助 {summary['weak']}", theme.RED),
        ("洗钱团伙命中", "22/22", "离线评测 · 团伙级召回", theme.GOLD),
        ("强证据精确率", "100%", "61/61 命中（评测）", theme.GREEN),
        ("本地推理速度", speed, "qwen2.5:7b-instruct（CPU 调试）" if "本地" in services.deployment_mode() else "GPU 节点", theme.ACCENT),
    ]
    cols = st.columns(6)
    for col, (label, value, hint, accent) in zip(cols, kpis):
        col.markdown(theme.kpi_card(label, value, hint, accent), unsafe_allow_html=True)

    theme.section("四节点部署拓扑", services.deployment_mode())
    node_cols = st.columns(4)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)
    targets = services.node_targets()
    st.markdown(
        theme.pill(
            f"规划内网地址：Node2 {targets['node2']} · Node3 {targets['node3']} · Node4 {targets['node4']}",
            "muted",
        ),
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        theme.section("图规则命中分布", "强证据：多层归集 + 环形转账；辅助证据：快进快出")
        st.plotly_chart(graph_view.rule_bar_figure(summary), width="stretch")
    with right:
        theme.section("证据强度排行", "按归集上游数 / 环形参与 / 快进快出命中综合打分")
        st.plotly_chart(graph_view.risk_bar_figure(risk), width="stretch")

    theme.section("最近一次研判", "报告与证据自动落盘到 reports/，可在“报告中心”下载")
    if not report:
        st.markdown(
            '<div class="jz-note">暂无研判报告。请到“智能体编排”执行一次完整分析。</div>',
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
