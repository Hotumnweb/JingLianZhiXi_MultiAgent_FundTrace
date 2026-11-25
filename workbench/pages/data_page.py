# -*- coding: utf-8 -*-
"""数据资产页：data/new 大数据集目录、确定性抽样、样本评测与赛场展示路线。

页面只做三件事：
1. 让操作员看清 data/new 里有什么、每套数据在赛场怎么用；
2. 一键生成“可现场建图”的抽样样本（data/prepared）；
3. 在已建好的抽样图谱上复算规则指标（标签只用于事后评测）。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from workbench import services, theme


@st.cache_data(ttl=300, show_spinner=False)
def _load_catalog() -> list[dict]:
    return services.dataset_catalog()


@st.cache_data(ttl=300, show_spinner=False)
def _load_summary() -> dict:
    return services.dataset_summary()


@st.cache_data(ttl=120, show_spinner=False)
def _load_preview(path: str, rows: int = 8) -> dict:
    return services.dataset_preview(path, rows)


@st.cache_data(ttl=60, show_spinner=False)
def _load_prepared_overview(key: str) -> dict:
    return services.prepared_overview(key)


def _goto_orchestration(flow_path: str) -> None:
    """跳到调度页并预选数据源。"""
    st.session_state["pending_flow_source"] = flow_path
    st.session_state["nav_page"] = "元智能体调度"
    st.rerun()


def _generate_sample(key: str, rows: int | None) -> None:
    name = key
    with st.status(f"正在生成 {name} 抽样……", expanded=True) as status:
        st.write("读取 `data/new/` 原始数据 → 确定性抽样 → 写 `data/prepared/`，约 10~20 秒。")
        try:
            meta = services.prepare_dataset_asset(key, rows=rows)
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"生成失败：{type(exc).__name__}", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            return
        status.update(label=f"{name} 抽样完成", state="complete")
        _load_catalog.clear()
        _load_summary.clear()
        st.session_state["data_flash"] = (
            f"{meta.get('name', key)} 抽样完成："
            f"{int(meta.get('rows') or meta.get('nodes') or 0):,} 行/节点，"
            f"{meta.get('elapsed_s', '-')} 秒"
        )
    st.rerun()


def _generate_all(catalog: list[dict]) -> None:
    keys = [row["key"] for row in catalog if row.get("prepared")]
    with st.status(f"正在生成 {len(keys)} 个抽样数据集……", expanded=True) as status:
        for index, key in enumerate(keys, start=1):
            st.write(f"[{index}/{len(keys)}] {key} …")
            try:
                services.prepare_dataset_asset(key)
            except Exception as exc:  # noqa: BLE001
                st.error(f"{key} 生成失败：{type(exc).__name__}: {exc}")
                status.update(label="部分数据集生成失败", state="error")
                return
        status.update(label="全部抽样生成完成", state="complete")
        _load_catalog.clear()
        _load_summary.clear()
        st.session_state["data_flash"] = f"已生成 {len(keys)} 个抽样数据集，可到调度页使用。"
    st.rerun()


def _render_catalog(catalog: list[dict]) -> None:
    theme.section("数据集目录", "data/new 原始数据 · 标签/许可/推荐用途")
    top = st.columns([3, 1, 1])
    top[1].caption("原始数据不进前端扫描，平台只消费抽样文件")
    if top[2].button("一键生成全部抽样", width="stretch"):
        _generate_all(catalog)

    columns = st.columns(2)
    for index, dataset in enumerate(catalog):
        status = dataset.get("prepared_status") or {}
        ready = bool(status.get("ready"))
        kind = dataset.get("kind", "flow")
        with columns[index % 2]:
            with st.container():
                st.markdown(theme.dataset_card(dataset), unsafe_allow_html=True)
                actions = st.columns(2)
                if dataset.get("prepared"):
                    rows_default = dataset.get("prepare_rows")
                    if actions[0].button(
                        "生成/刷新抽样",
                        key=f"prepare_{dataset['key']}",
                        width="stretch",
                        help="从 data/new 原始数据生成确定性抽样（固定随机种子）",
                    ):
                        _generate_sample(dataset["key"], rows_default)
                    if (
                        kind == "flow"
                        and ready
                        and actions[1].button(
                            "在调度页使用",
                            key=f"use_{dataset['key']}",
                            type="primary",
                            width="stretch",
                        )
                    ):
                        _goto_orchestration(status["flow_path"])
                elif kind == "flow" and dataset.get("primary_file"):
                    if actions[0].button(
                        "在调度页使用",
                        key=f"use_{dataset['key']}",
                        type="primary",
                        width="stretch",
                    ):
                        _goto_orchestration(dataset["primary_file"])
                if status.get("generated_at"):
                    st.caption(f"抽样生成时间：{status['generated_at']}")
                elif dataset.get("prepared"):
                    st.caption("尚未生成抽样：点“生成/刷新抽样”后即可现场建图。")


def _render_preview(catalog: list[dict]) -> None:
    theme.section("抽样准备与预览", "统一为中文流水格式，生成后可直接建图")
    ready_rows = [
        row for row in catalog
        if row["kind"] == "flow" and (row.get("prepared_status") or {}).get("ready")
    ]
    if not ready_rows:
        st.info("还没有可预览的抽样数据：先在上方数据集卡片点“生成/刷新抽样”。")
        return

    labels = {
        row["key"]: f"{row['name']} · {int((row['prepared_status']['meta'] or {}).get('rows') or 0):,} 笔"
        for row in ready_rows
    }
    selected_key = st.selectbox(
        "选择抽样样本",
        options=list(labels),
        format_func=lambda key: labels[key],
        key="dataset_preview_select",
    )
    selected = next(row for row in ready_rows if row["key"] == selected_key)
    meta = selected["prepared_status"]["meta"] or {}
    metric_cols = st.columns(4)
    metric_cols[0].metric("样本行数", f"{int(meta.get('rows') or 0):,}", border=True)
    metric_cols[1].metric("账户数", f"{int(meta.get('accounts') or 0):,}", border=True)
    label_rows = int(meta.get("laundering_rows") or meta.get("fraud_rows") or 0)
    label_name = "洗钱交易" if meta.get("laundering_rows") else "诈骗交易"
    metric_cols[2].metric(label_name, f"{label_rows:,}", border=True)
    metric_cols[3].metric("生成耗时", f"{meta.get('elapsed_s', '-')} s", border=True)

    with st.expander("查看样本前 20 行（统一中文流水格式）", expanded=False):
        try:
            preview = _load_preview(selected["prepared_status"]["flow_path"], 20)
            st.dataframe(preview["records"], width="stretch", hide_index=True, height=300)
            st.caption(f"列：{', '.join(preview['columns'])}")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"预览失败：{type(exc).__name__}: {exc}")

    patterns = (meta.get("patterns") or {})
    if patterns.get("available"):
        with st.expander("IBM 官方 8 类洗钱模式（抽样来源标注）", expanded=False):
            st.dataframe(
                [
                    {"模式": name, "尝试次数": count}
                    for name, count in sorted(patterns.get("patterns", {}).items())
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                f"Patterns.txt 共标注 {patterns.get('transactions', 0):,} 笔洗钱交易；"
                "标签只用于事后评测，不进入智能体输入。"
            )


def _render_evaluation(catalog: list[dict]) -> None:
    theme.section("抽样样本规则评测", "标签只用于事后复算，不进入智能体决策")
    ready_rows = [
        row for row in catalog
        if row["kind"] == "flow" and (row.get("prepared_status") or {}).get("ready")
    ]
    if not ready_rows:
        st.info("暂无抽样样本，无法评测。")
        return

    labels = {row["key"]: row["name"] for row in ready_rows}
    eval_key = st.selectbox(
        "评测数据集",
        options=list(labels),
        format_func=lambda key: labels[key],
        key="eval_dataset_select",
    )
    selected = next(row for row in ready_rows if row["key"] == eval_key)
    target_flow = selected["prepared_status"]["flow_path"]

    latest = services.latest_completed_task() or {}
    latest_flow = str(latest.get("flow_file") or "")
    same_source = bool(latest_flow) and Path(latest_flow).name == Path(target_flow).name
    if same_source:
        st.caption(f"当前图谱来自最近任务 `{latest.get('id', '')}`（{Path(latest_flow).name}）")
    elif not latest_flow:
        st.info(
            "还没有已完成的任务：先到“元智能体调度”选择该抽样样本，"
            "执行一次“仅执行图工具分析”，再回来复算指标。"
        )
    else:
        st.warning(
            "当前图谱不一定是用该样本建的。请先到“元智能体调度”选择该抽样样本，"
            "执行一次“仅执行图工具分析”，再回来复算指标。",
            icon=":material/info:",
        )

    if st.button("复算规则指标", type="primary"):
        with st.spinner("正在读取当前图谱并执行三条规则……"):
            try:
                result = services.compute_prepared_metrics(eval_key)
            except Exception as exc:  # noqa: BLE001
                st.error(f"评测失败：{type(exc).__name__}: {exc}")
            else:
                st.session_state["prepared_metrics"] = result

    result = st.session_state.get("prepared_metrics")
    if not result or result.get("dataset_key") != eval_key:
        st.info("点击上方按钮，在**当前图谱**上复算精确率/召回率与模式覆盖。")
        return

    graph = result.get("graph") or {}
    st.caption(
        f"当前图谱 {graph.get('accounts', 0):,} 账户 / {graph.get('transfers', 0):,} 转账 · "
        f"标签 {result['label_kind']} {result['truth']:,} 个"
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
                "命中账户": row["flagged"],
                "真标签命中": row["tp"],
                "精确率": row["precision"],
                "召回率": row["recall"],
                "F1": row["f1"],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
    )
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("强证据精确率", f"{result['strong']['precision']:.3f}", border=True)
    kpi_cols[1].metric("强证据召回率", f"{result['strong']['recall']:.3f}", border=True)
    kpi_cols[2].metric("最终清单精确率", f"{result['all']['precision']:.3f}", border=True)
    kpi_cols[3].metric("最终清单命中", f"{result['all']['tp']:,}", border=True)

    coverage = result.get("pattern_coverage") or {}
    if coverage.get("available"):
        st.markdown(
            f"**IBM 洗钱模式覆盖：{coverage['covered_patterns']}/{coverage['total_patterns']} 类**"
        )
        st.dataframe(
            [
                {
                    "模式": name,
                    "尝试次数": item["attempts"],
                    "涉及账户": item["accounts"],
                    "规则命中": item["flagged"],
                }
                for name, item in coverage["by_type"].items()
            ],
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "说明：演示抽样保留了全部标签交易，真实洗钱/诈骗比例远低于抽样比例；"
        "召回率反映“账户级规则覆盖”，不等于实际侦查召回。"
    )


def _render_graph_and_tabular(catalog: list[dict]) -> None:
    theme.section("图结构与表格数据", "扩展方向：社区发现 / 风险传播 / GNN / 表格对照")
    elliptic = next((row for row in catalog if row["key"] == "elliptic"), None)
    overview = _load_prepared_overview("elliptic")
    if elliptic and overview:
        cols = st.columns(4)
        cols[0].metric("子图节点", f"{int(overview.get('nodes', 0)):,}", border=True)
        cols[1].metric("子图边", f"{int(overview.get('edges', 0)):,}", border=True)
        illicit = int((overview.get("classes") or {}).get("1", 0))
        cols[2].metric("illicit 节点", f"{illicit:,}", border=True)
        cols[3].metric(
            "高连接度节点 illicit 占比",
            f"{overview.get('top_degree_illicit_ratio', 0):.1%}",
            border=True,
        )
        with st.expander("Elliptic 图结构速览（前 20 个时间步子图）", expanded=False):
            st.dataframe(
                [
                    {
                        "节点": row["txId"],
                        "连接度": row["degree"],
                        "标签": {"1": "illicit", "2": "licit"}.get(row["class"], row["class"]),
                    }
                    for row in (overview.get("top_degree_nodes") or [])[:10]
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "高连接度节点以合法/未知为主：说明只靠“度中心性”无法识别涉诈，"
                "需要资金语义特征与 GNN/社区发现，这是后续扩展方向。"
            )
    elif elliptic:
        st.info("Elliptic 抽样尚未生成：在上方数据集卡片点“生成/刷新抽样”。")

    ieee = next((row for row in catalog if row["key"] == "ieee-fraud"), None)
    if ieee:
        with st.container(border=True):
            st.markdown(f"**{ieee['name']}**（表格欺诈检测）")
            st.caption(
                "590,540 笔 / 394 列 / 欺诈 20,663 笔（3.5%）。"
                "缺少“付款账户—收款账户”成对字段，无法构建资金图，"
                "因此作为对照实验：用表格特征模型与图结构规则对比，说明资金穿透为什么需要图。"
            )
            with st.expander("查看表格前 5 行（前 12 列）", expanded=False):
                try:
                    preview = _load_preview("data/new/ieee-fraud/train_transaction.csv", 5)
                    columns = preview["columns"][:12]
                    st.dataframe(
                        [{col: record.get(col) for col in columns} for record in preview["records"]],
                        width="stretch",
                        hide_index=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"预览失败：{type(exc).__name__}: {exc}")


def _render_route() -> None:
    theme.section("赛场展示路线", "这些数据怎么用、怎么讲")
    with st.expander("查看建议演示脚本（8 分钟版）", expanded=True):
        st.markdown(
            """
            1. **开场基线（约 1 分钟）**：调度页选“合成 AML 数据集”跑一次，
               讲“解析 → 建图 → 三条规则 → 报告”，指标页复算精确率/召回率（现成数字）。
            2. **换真实规模数据（约 2 分钟）**：切到“大数据抽样 · IBM HI-Small”，
               展示 5 万笔样本建图（6 万+账户）、规则命中 65 个可疑账户，
               强调 **IBM 官方 8 类洗钱模式全部有命中（8/8）**、强证据命中全部为真实洗钱账户。
            3. **换场景验证（约 1.5 分钟）**：切到 PaySim 抽样，同一套代码不改，30 秒内出结果，
               说明“解析/建图/规则与数据源解耦”，可迁移到移动支付场景。
            4. **能力边界（约 1 分钟）**：打开本页图结构/表格卡片，
               说明 Elliptic（图数据，后续 GNN/社区发现）与 IEEE-CIS（表格对照）为什么暂不接主流程。
            5. **收束（约 1 分钟）**：回到“方法与局限”——规则面向国内银行卡场景调参，
               跨数据集召回受模式覆盖限制；下一步是把工具调用接入主任务队列并支持规则口径配置。
            """
        )
    with st.expander("现场注意事项", expanded=False):
        st.markdown(
            """
            - 原始数据在 `data/new/`（约 2.5 GB），**不上 Git、也不现场扫描**；
              抽样在 `data/prepared/`（已加入 `.gitignore`），比赛前预生成一次即可。
            - 抽样固定随机种子（`20261125`），同一机器重复生成结果一致，可复现。
            - 演示抽样保留了全部标签交易，因此洗钱/诈骗比例高于真实比例；
              讲解时要主动说明“这是为现场可见性做的抽样，不是真实发案率”。
            - 大样本建图前先在调度页确认已选择对应抽样，避免把不同样本的图谱混用。
            """
        )


def render() -> None:
    flash = st.session_state.pop("data_flash", None)
    if flash:
        st.success(flash)

    theme.section("数据资产", "data/new 原始数据集 · 确定性抽样 · 赛场演示路线")

    summary = _load_summary()
    catalog = _load_catalog()
    metric_cols = st.columns(4)
    metric_cols[0].metric("数据集", f"{summary['dataset_count']} 套", border=True)
    metric_cols[1].metric(
        "原始流水总量",
        f"{summary['raw_transactions'] / 10000:.0f} 万笔" if summary["raw_transactions"] else "—",
        border=True,
    )
    metric_cols[2].metric("已生成抽样", f"{summary['prepared_count']} 套", border=True)
    metric_cols[3].metric(
        "可用标签数据集",
        f"{summary['label_count']} 套",
        border=True,
    )

    _render_catalog(catalog)
    _render_preview(catalog)
    _render_evaluation(catalog)
    _render_graph_and_tabular(catalog)
    _render_route()

    st.caption(
        "合规提示：data/new 数据仅用于本地演示与离线评测；"
        "标签（Is Laundering / isFraud / illicit）只在评测脚本读取，不进入智能体输入。"
    )
