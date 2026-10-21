# -*- coding: utf-8 -*-
"""规则与指标页：规则口径、当前命中、离线评测指标。"""

import streamlit as st

from workbench import graph_view, services, theme


def render() -> None:
    theme.section("规则与指标", "Node3 工具执行的图规则 · 离线评测（标签不进入智能体输入）")

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

    summary = services.evidence_summary(services.latest_evidence())
    cols = st.columns(3)
    cols[0].metric("当前归集命中", summary["gather"])
    cols[1].metric("当前环形链命中", summary["cycles"])
    cols[2].metric("当前快进快出命中", summary["fast_io"])

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
    if not result:
        st.info("点击上方按钮现场复算；也可以直接运行 `python scripts/evaluate_on_synthetic_aml.py`。")
    else:
        graph = result.get("graph") or {}
        if graph.get("transfers") and graph["transfers"] != 42175:
            st.warning(
                f"当前图谱有 {graph['transfers']} 条边（不是 AML 完整数据集 42,175 条），"
                "评测前请先运行 `python main.py` 重建完整图谱。"
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

    theme.section("数据集画像", "合成 AML 数据集（CC0-1.0，纯虚构）")
    profile = services.dataset_profile()
    cols = st.columns(4)
    cols[0].metric("交易流水", f"{profile['transactions']:,}")
    cols[1].metric("账户", f"{profile['accounts']:,}")
    cols[2].metric("洗钱团伙", profile["rings"])
    cols[3].metric("欺诈交易占比", f"{profile['fraud_rate']}%")
    left, right = st.columns([1, 1])
    with left:
        st.plotly_chart(graph_view.ring_type_figure(profile.get("ring_types")), width="stretch")
    with right:
        st.markdown(
            f"""
            <div class="jz-note">
            时间范围：{theme.esc(profile.get('date_start', ''))} ~ {theme.esc(profile.get('date_end', ''))}<br>
            交易金额单位：USD<br>
            团伙类型：{theme.esc(' / '.join(f'{k} × {v}' for k, v in (profile.get('ring_types') or {}).items()))}<br>
            金额总规模：约 {profile.get('volume_usd', 0):,.0f} USD
            </div>
            """,
            unsafe_allow_html=True,
        )
