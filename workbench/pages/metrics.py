# -*- coding: utf-8 -*-
"""规则与指标页：规则口径、当前命中、离线评测指标。"""

import streamlit as st

from workbench import graph_view, services, tasks, theme


def render() -> None:
    theme.section("规则与指标", "Node3 工具执行的图规则 · 离线评测（标签不进入智能体输入）")

    graph = services.graph_stats()
    has_graph = bool(graph.get("transfers"))
    latest_task = tasks.queue_summary().get("latest")
    latest_source = (latest_task or {}).get("flow_file", "")
    labels_available = has_graph and "synthetic_aml" in str(latest_source)

    rules = [
        ("多层归集", "强证据", "24 小时内 ≥4 个不同上游账户汇入，金额离散系数 CV ≤ 0.15", theme.PURPLE),
        ("环形转账", "强证据", "3~6 跳闭环，时间严格递增，每跳金额为上一跳的 90%~110%，跨度 ≤7 天", theme.GOLD),
        ("快进快出", "辅助证据", "48 小时内转出 ≥95% 收款金额，且账户总交易笔数 ≤8（卡农特征）", theme.ACCENT),
    ]
    cols = st.columns(3)
    for col, (name, tag, desc, color) in zip(cols, rules):
        col.markdown(
            f"""
            <div class="jz-node" style="border-top:3px solid {color};">
              <div class="jz-node-head"><span class="jz-node-role">{tag}</span></div>
              <div class="jz-node-name">{name}</div>
              <div class="jz-node-detail">{desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    payload = services.latest_evidence()
    summary = services.evidence_summary(payload)
    cols = st.columns(3)
    cols[0].metric("当前归集命中", summary["gather"] if payload else "—")
    cols[1].metric("当前环形链命中", summary["cycles"] if payload else "—")
    cols[2].metric("当前快进快出命中", summary["fast_io"] if payload else "—")
    if not payload:
        st.caption("当前没有任务证据；先到“元智能体调度”加载目标并下发任务。")

    theme.section("离线评测指标", "用数据集标签事后评测（标签不会进入智能体输入）")
    st.markdown(
        """
        <div class="jz-note">
        真实办案场景没有标签，本页仅用于验证算法效果、量化答辩指标。
        点击下方按钮会重新执行三条图规则，并读取 <code>accounts.csv / laundering_rings.csv</code>
        中的标签计算精确率、召回率与团伙级召回。
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not has_graph:
        st.session_state.pop("metrics_result", None)
        st.info("当前图谱为空，暂不能做规则评测。请先在“元智能体调度”加载目标数据并下发任务建图。")
    elif not labels_available:
        st.session_state.pop("metrics_result", None)
        st.info(
            "当前图谱不是由合成 AML 数据集建成的，没有可用的离线标签。"
            "如需评测精确率/召回率，请使用 data/synthetic_aml/transactions.csv 跑一次任务。"
        )
    else:
        if st.button("重新计算检测指标（约 10 秒）", type="primary"):
            with st.spinner("正在执行图规则与标签比对……"):
                try:
                    result = services.compute_metrics()
                    st.session_state["metrics_result"] = result
                    services.audit_event(
                        "evaluation",
                        "metrics_computed",
                        {"strong_precision": result["strong"]["precision"]},
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"评测失败：{type(exc).__name__}: {exc}")

        result = st.session_state.get("metrics_result")
        if result:
            result_graph = result.get("graph") or {}
            if int(result_graph.get("transfers") or 0) != int(graph.get("transfers") or 0):
                st.warning("评测结果对应的图谱规模已经变化，请重新计算。")
                st.session_state.pop("metrics_result", None)
                result = None

        if not result:
            st.info("点击上方按钮现场复算；也可以直接运行 `python scripts/evaluate_on_synthetic_aml.py`。")
        else:
            graph_result = result.get("graph") or {}
            if graph_result.get("transfers") and graph_result["transfers"] != 42175:
                st.warning(
                    f"当前图谱有 {graph_result['transfers']} 条边（不是 AML 完整数据集 42,175 条），"
                    "评测前请先运行完整数据集任务重建图谱。"
                )

            rows = [
                {"规则": "快进快出（辅助）", **result["fast_io"]},
                {"规则": "多层归集（强）", **result["gather"]},
                {"规则": "环形转账（强）", **result["cycles"]},
                {"规则": "强证据合并", **result["strong"]},
                {"规则": "最终可疑清单", **result["all"]},
            ]
            st.dataframe(
                [
                    {
                        "规则": row["规则"],
                        "账户数": row["flagged"],
                        "命中": row["tp"],
                        "精确率": row["precision"],
                        "召回率": row["recall"],
                        "F1": row["f1"],
                    }
                    for row in rows
                ],
                width="stretch",
                hide_index=True,
            )

            cols = st.columns(4)
            cols[0].metric("强证据精确率", f"{result['strong']['precision']:.3f}")
            cols[1].metric("强证据召回率", f"{result['strong']['recall']:.3f}")
            cols[2].metric("最终清单精确率", f"{result['all']['precision']:.3f}")
            cols[3].metric("团伙级召回", f"{result['detected_rings']}/{result['rings']}")
            if result["detected_rings"] == result["rings"]:
                st.success(f"全部 {result['rings']} 个洗钱团伙至少命中 1 个账户（团伙级召回 100%）。")

            st.plotly_chart(
                graph_view.rule_bar_figure(
                    {
                        "gather": result["gather"]["tp"],
                        "cycles": result["cycles"]["tp"],
                        "fast_io": result["fast_io"]["tp"],
                    }
                ),
                width="stretch",
            )

    theme.section("数据集画像", "当前图谱规模 + 离线标签（仅合成 AML 数据集有标签）")
    if not has_graph:
        st.info("当前图谱为空，没有可展示的数据画像。下发任务建图后，这里会显示当前图谱规模。")
        return

    profile = services.dataset_profile() if labels_available else None
    cols = st.columns(4)
    cols[0].metric("交易流水", f"{int(graph.get('transfers') or 0):,}")
    cols[1].metric("账户", f"{int(graph.get('accounts') or 0):,}")
    cols[2].metric("洗钱团伙", profile["rings"] if profile else "—")
    cols[3].metric("欺诈交易占比", f"{profile['fraud_rate']}%" if profile else "—")

    left, right = st.columns([1, 1])
    with left:
        if profile and profile.get("ring_types"):
            st.plotly_chart(graph_view.ring_type_figure(profile.get("ring_types")), width="stretch")
        else:
            st.info("当前数据没有离线标签画像，仅展示图谱规模。")
    with right:
        source_text = latest_source or "未记录任务数据源"
        if profile:
            st.markdown(
                f"""
                <div class="jz-note">
                当前数据源：{theme.esc(source_text)}<br>
                时间范围：{theme.esc(profile.get('date_start', ''))} ~ {theme.esc(profile.get('date_end', ''))}<br>
                交易金额单位：USD<br>
                团伙类型：{theme.esc(' / '.join(f'{k} × {v}' for k, v in (profile.get('ring_types') or {}).items()))}<br>
                金额总规模：约 {profile.get('volume_usd', 0):,.0f} USD
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="jz-note">
                当前数据源：{theme.esc(source_text)}<br>
                当前图谱：{int(graph.get('accounts') or 0):,} 个账户 / {int(graph.get('transfers') or 0):,} 条转账<br>
                该数据没有合成 AML 标签，因此不显示团伙数、欺诈占比和离线评测。
                </div>
                """,
                unsafe_allow_html=True,
            )
