# -*- coding: utf-8 -*-
"""调度总览：集群状态、数据分析结果、最近一次研判。"""

import streamlit as st

from pathlib import Path

from workbench import graph_view, services, tasks, theme


def render() -> None:
    payload = services.latest_evidence()
    summary = services.evidence_summary(payload)
    graph = services.graph_stats()
    report = services.latest_report()
    nodes = services.node_status()
    risk = services.risk_rows(payload)
    queue = tasks.queue_summary()
    latest_task = queue.get("latest")

    theme.section("调度总览", "运行态势 · 三节点集群 · 研判结果")

    tx_count = int(graph.get("transfers") or 0)
    if graph.get("error"):
        tx_hint = "Node3 未连接"
    elif tx_count and latest_task and latest_task.get("flow_file"):
        tx_hint = f"当前图谱 · {Path(str(latest_task['flow_file'])).name}"
    elif tx_count:
        tx_hint = "当前图谱内转账"
    else:
        tx_hint = "等待任务执行"

    kpis = [
        ("交易流水", f"{tx_count:,}", tx_hint, theme.ACCENT),
        ("图账户节点", f"{graph.get('accounts', 0):,}", "Node3 · Neo4j", theme.PURPLE),
        ("可疑账户", summary["suspects"] if payload else "—", "等待任务执行" if not payload else "强证据优先", theme.RED),
        ("归集账户", summary["gather"] if payload else "—", "多层归集", theme.GOLD),
        ("环形转账链", summary["cycles"] if payload else "—", "闭环资金链", theme.GREEN),
        ("快进快出", summary["fast_io"] if payload else "—", "卡农过渡账户", theme.ACCENT),
    ]
    cols = st.columns(6)
    for col, (label, value, hint, accent) in zip(cols, kpis):
        col.markdown(theme.kpi_card(label, value, hint, accent), unsafe_allow_html=True)

    theme.section("任务队列状态", "任务进度与调度记录")
    queue_cols = st.columns(5)
    queue_cols[0].metric("排队中", queue[tasks.STATUS_QUEUED])
    queue_cols[1].metric("执行中", queue[tasks.STATUS_RUNNING])
    queue_cols[2].metric("已完成", queue[tasks.STATUS_COMPLETED])
    queue_cols[3].metric("失败", queue[tasks.STATUS_FAILED])
    latest_task = queue.get("latest")
    if latest_task:
        queue_cols[4].metric(
            "最近任务",
            tasks.STATUS_LABELS.get(latest_task.get("status", ""), latest_task.get("status", "")),
        )
        st.caption(
            f"最近任务 `{latest_task['id']}` · "
            f"{(latest_task.get('instruction') or '')[:50]}"
        )
    else:
        queue_cols[4].metric("最近任务", "—")

    theme.section("三节点集群", "Node1 调度 · Node2 推理 · Node3 图数据")
    node_cols = st.columns(3)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        theme.section("图规则命中分布")
        st.plotly_chart(graph_view.rule_bar_figure(summary), width="stretch")
    with right:
        theme.section("证据强度排行")
        st.plotly_chart(graph_view.risk_bar_figure(risk), width="stretch")

    theme.section("最近一次研判")
    if not report:
        st.markdown(
            '<div class="jz-note">暂无研判报告。下发任务后，报告与证据会自动汇总到这里。</div>',
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
