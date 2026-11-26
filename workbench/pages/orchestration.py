# -*- coding: utf-8 -*-
"""Coordinator 调度台：数据资产 → 侦查指令 → 执行监控 → 结果归档。

页面结构：
1. 顶部：任务队列 KPI + 三节点状态条；
2. 左列：① 选择数据资产（含预览/导入）→ ② 下达侦查指令 → ③ 执行任务；
3. 右列：运行监控（阶段卡、进度、日志、AI 流式输出）+ 最近任务；
4. 底部：任务结果 / 最近任务 / 调度说明 三个页签。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import streamlit as st

from llms.remote_llm import report_agent_enabled
from workbench import coordinator, executor, services, tasks, theme
from workbench.runner import STAGES

INSTRUCTION_TEMPLATES = {
    "自定义任务": "",
    "全量资金穿透分析": "对这批流水做全量资金穿透分析，输出可疑账户和研判报告",
    "重点排查环形转账": "重点排查环形转账链，找出闭环资金网络及其关联账户",
    "重点排查水房归集": "重点排查多层归集账户，分析水房特征与资金去向",
}

_RULE_NOTE = """
- **多层归集（强证据）**：24 小时内 ≥4 个上游账户汇入，金额离散系数 CV ≤ 0.15；
- **环形转账（强证据）**：3~6 跳闭环，时间递增，每跳金额为上一跳的 90%~110%，跨度 ≤7 天；
- **快进快出（辅助证据）**：48 小时内转出 ≥95% 收款金额，且账户交易笔数 ≤8；
- 标签（Is Laundering / isFraud）只用于离线评测，不进入智能体决策。
"""


@st.cache_data(ttl=120, show_spinner=False)
def _load_preview(path: str, rows: int = 8) -> dict:
    return services.dataset_preview(path, rows)


def _apply_instruction_template() -> None:
    """模板只负责快速填入描述，真正执行以“侦查任务描述”为准。"""
    template = st.session_state.get("instruction_template", "自定义任务")
    st.session_state["task_instruction"] = INSTRUCTION_TEMPLATES.get(template, "")


def _stage_states(done: set[str]) -> dict[str, str]:
    return {key: ("done" if key in done else "pending") for key, _, _ in STAGES}


def _load_task_evidence(task: dict) -> tuple[dict, list[str]]:
    """从任务落盘的证据 JSON 中恢复证据与可疑账户，供切页后重新展示。"""
    evidence_path = task.get("evidence_path") or ""
    if not evidence_path or not Path(evidence_path).exists():
        return {}, []
    try:
        payload = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        summary = services.evidence_summary(payload)
        return summary.get("evidence") or {}, summary.get("suspect_list") or []
    except Exception:  # noqa: BLE001
        return {}, []


def _render_task_result(task: dict) -> None:
    """展示一个已完成任务的结果、报告、追加指令与调用记录。"""
    evidence, suspects = _load_task_evidence(task)
    intermediate = task.get("intermediate") or {}
    task_id = task.get("id", "")
    status = task.get("status", "")

    cols = st.columns(5)
    cols[0].metric("可疑账户", task.get("suspicious") or len(suspects), border=True)
    cols[1].metric("归集账户", len(evidence.get("gather") or []), border=True)
    cols[2].metric("环形链", len(evidence.get("cycles") or []), border=True)
    cols[3].metric("快进快出", len(evidence.get("fast_io") or []), border=True)
    cols[4].metric(
        "报告状态",
        {"ok": "AI 生成", "fallback": "规则兜底"}.get(task.get("llm_status", ""), "未启用"),
        border=True,
    )

    if intermediate:
        info_cols = st.columns(4)
        info_cols[0].metric("解析流水", intermediate.get("parsed_count", "—"))
        info_cols[1].metric("图账户", intermediate.get("accounts", "—"))
        info_cols[2].metric("转账边", intermediate.get("transfers", "—"))
        info_cols[3].metric("耗时", f"{task.get('duration_s', '—')} s")

    report_tab, evidence_tab, calls_tab, logs_tab = st.tabs(
        ["研判报告", "可疑账户与证据", "调用记录", "调度日志"]
    )

    with report_tab:
        conclusion = task.get("conclusion") or ""
        if conclusion:
            if task.get("llm_status") == "fallback":
                st.warning("AI 调用失败，已自动降级为规则模板报告。")
            if status == "failed":
                st.error(f"任务失败：{task.get('error', '未知错误')}")
            with st.container(border=True):
                st.markdown(conclusion)
            report_path = task.get("report_path")
            evidence_path = task.get("evidence_path")
            download_cols = st.columns(2)
            if report_path and Path(report_path).exists():
                download_cols[0].download_button(
                    "下载研判报告（Markdown）",
                    data=services.read_text(Path(report_path)),
                    file_name=Path(report_path).name,
                    mime="text/markdown",
                    width="stretch",
                    key=f"dl_task_report_{task_id}",
                )
            if evidence_path and Path(evidence_path).exists():
                download_cols[1].download_button(
                    "下载证据 JSON",
                    data=services.read_text(Path(evidence_path)),
                    file_name=Path(evidence_path).name,
                    mime="application/json",
                    width="stretch",
                    key=f"dl_task_evidence_{task_id}",
                )
            if task.get("enable_report") and task.get("evidence_path"):
                with st.expander("追加侦查指令", expanded=False):
                    st.caption("在已有证据与报告基础上追加分析；Node2 GPU 通常数十秒返回。")
                    follow = st.text_input(
                        "追加指令",
                        placeholder="例如：重点说明环形转账链的资金闭环特征",
                        key=f"follow_input_{task_id}",
                    )
                    if st.button("执行追加分析", key=f"follow_btn_{task_id}"):
                        if not follow.strip():
                            st.warning("请先输入追加指令")
                        else:
                            with st.spinner("正在调用 Node2 AI 分析追加指令……"):
                                try:
                                    answer = coordinator.follow_up(task_id, follow.strip())
                                except Exception as exc:  # noqa: BLE001
                                    st.error(f"追加分析失败：{type(exc).__name__}: {exc}")
                                else:
                                    st.success("追加分析完成")
                                    st.markdown(answer)
                latest = tasks.load_task(task_id) or task
                for item in latest.get("follow_ups") or []:
                    with st.expander(
                        f"历史追加：{item.get('instruction', '')[:40]}", expanded=False
                    ):
                        st.markdown(item.get("answer", ""))
        else:
            st.info("本次未启用 AI 研判报告，仅输出图工具分析结果。")
            if status == "failed":
                st.error(f"任务失败：{task.get('error', '未知错误')}")

    with evidence_tab:
        evidence_cols = st.columns(4)
        evidence_cols[0].metric("强证据账户", evidence.get("strong_count", 0))
        evidence_cols[1].metric("辅助证据账户", evidence.get("weak_count", 0))
        evidence_cols[2].metric("环形链", len(evidence.get("cycles") or []))
        evidence_cols[3].metric("快进快出", len(evidence.get("fast_io") or []))
        if suspects:
            with st.expander(f"可疑账户清单（{len(suspects)} 个）", expanded=False):
                st.write(suspects)
        if evidence.get("gather"):
            st.markdown("**多层归集账户**")
            st.dataframe(evidence["gather"], width="stretch", hide_index=True)
        if evidence.get("cycles"):
            st.markdown("**环形转账链**")
            st.dataframe(
                [
                    {
                        "链路": " → ".join(item["accounts"] + [item["accounts"][0]]),
                        "跳数": item["length"],
                        "涉案金额": item["amount"],
                        "跨度(小时)": item["span_hours"],
                    }
                    for item in evidence["cycles"]
                ],
                width="stretch",
                hide_index=True,
            )
        if evidence.get("fast_io"):
            st.markdown("**快进快出账户（辅助证据）**")
            st.dataframe(evidence["fast_io"], width="stretch", hide_index=True)

    with calls_tab:
        if task.get("node_calls"):
            st.dataframe(task["node_calls"], width="stretch", hide_index=True)
        else:
            st.caption("暂无调用记录。")

    with logs_tab:
        logs = task.get("logs") or []
        if logs:
            st.code("\n".join(str(line) for line in logs), language="text")
        else:
            st.caption("暂无调度日志。")


def _recent_task_rows(items: list[dict]) -> list[dict]:
    return [
        {
            "任务号": task.get("id", ""),
            "状态": tasks.STATUS_LABELS.get(task.get("status", ""), task.get("status", "")),
            "数据源": Path(str(task.get("flow_file", ""))).name,
            "AI 报告": "是" if task.get("enable_report") else "否",
            "可疑账户": task.get("suspicious", 0),
            "耗时(s)": task.get("duration_s", ""),
            "创建时间": task.get("created_at", ""),
        }
        for task in items
    ]


def _source_labels(sources: list[dict]) -> dict[str, str]:
    return {
        item["path"]: f"{item['group']}｜{item['label']}"
        for item in sources
    }


def _source_detail(source: dict) -> None:
    """数据源摘要：行数、格式、标签/抽样说明（窄列用徽标行，避免数值被截断）。"""
    if not source:
        return
    meta = source.get("meta") or {}
    if meta.get("laundering_rows"):
        label_text, label_tone = f"洗钱 {int(meta['laundering_rows']):,} 笔", "ok"
    elif meta.get("fraud_rows"):
        label_text, label_tone = f"诈骗 {int(meta['fraud_rows']):,} 笔", "warn"
    elif source.get("dataset_key"):
        label_text, label_tone = "有离线标签", "info"
    else:
        label_text, label_tone = "无标签", "muted"
    chips = [
        theme.pill(f"{int(source.get('rows') or 0):,} 条", "info"),
        theme.pill(str(source.get("group", "—")), "muted"),
        theme.pill(label_text, label_tone),
    ]
    st.markdown(" ".join(chips), unsafe_allow_html=True)


def _render_bottom(last_task: dict | None) -> None:
    result_tab, recent_tab, help_tab = st.tabs(["任务结果", "最近任务", "调度说明"])
    with result_tab:
        if last_task:
            st.caption(
                f"任务 `{last_task.get('id', '')}` · "
                f"{tasks.STATUS_LABELS.get(last_task.get('status', ''), '')} · "
                f"数据源 `{Path(str(last_task.get('flow_file', ''))).name}`"
            )
            _render_task_result(last_task)
        else:
            st.info("还没有可展示的任务结果：完成一次任务后会在这里显示报告与证据。")
    with recent_tab:
        all_tasks = tasks.list_tasks(limit=12)
        if all_tasks:
            st.dataframe(_recent_task_rows(all_tasks), width="stretch", hide_index=True)
            st.caption("完整队列与重跑入口在左侧“任务队列”页面。")
        else:
            st.caption("暂无任务记录。")
    with help_tab:
        st.markdown(
            """
            **调用链**：Node1 调度中心（本页）→ Node3 工具与图数据（pandas 解析 + Neo4j 建图 + 三条图规则）
            → Node2 GPU 算力中心（Ollama 生成研判报告）→ 结果回传 Node1 归档。

            **数据源**：内置数据可直接使用；`data/new` 大数据集可在“数据资产”页生成抽样、
            或在“数据接入”页清洗后使用，再在“流水数据源”下拉中选择；上传的 CSV 会保存到 `data/imports/`。

            **使用建议**：先用内置数据建立基线，再切换抽样/清洗数据验证不同规模。
            """
        )


def render() -> None:
    theme.section("元智能体调度", "数据资产 → 侦查指令 → 执行监控 → 结果归档")

    queue = tasks.queue_summary()
    kpi_cols = st.columns(4)
    kpi_cards = [
        ("排队中", queue[tasks.STATUS_QUEUED], "等待执行", theme.ACCENT),
        ("执行中", queue[tasks.STATUS_RUNNING], "正在调度", theme.GOLD),
        ("已完成", queue[tasks.STATUS_COMPLETED], "可查看报告", theme.GREEN),
        ("失败", queue[tasks.STATUS_FAILED], "需要排查", theme.RED),
    ]
    for col, (label, value, hint, accent) in zip(kpi_cols, kpi_cards):
        col.markdown(theme.kpi_card(label, value, hint, accent), unsafe_allow_html=True)

    debug = services.debug_inference_status()
    nodes = services.node_status()
    node_pills = []
    for node in nodes:
        tone = {"online": "ok", "warn": "warn", "placeholder": "muted"}.get(
            node.get("status", ""), "danger"
        )
        latency = node.get("latency_ms")
        extra = f" · {latency:.0f} ms" if isinstance(latency, (int, float)) and latency else ""
        node_pills.append(theme.pill(f"NODE {node['index']} {node['name']}{extra}", tone))
    st.markdown(
        " ".join(node_pills) + " " + theme.pill(
            f"推理服务：{'在线 · ' + debug['model'] if debug.get('ok') else '离线 · 报告将降级为规则模板'}",
            "ok" if debug.get("ok") else "warn",
        ),
        unsafe_allow_html=True,
    )

    sources = services.flatten_flow_sources()
    source_paths = [item["path"] for item in sources]
    source_map = {item["path"]: item for item in sources}
    source_labels = _source_labels(sources)
    if not source_labels:
        source_labels = {"": "（暂无可解析的流水数据源）"}

    pending = st.session_state.pop("pending_flow_source", None)
    if pending in source_paths:
        st.session_state["flow_source_select"] = pending
    if st.session_state.get("flow_source_select") not in source_paths and source_paths:
        st.session_state["flow_source_select"] = source_paths[0]

    st.session_state.setdefault("task_instruction", "")
    st.session_state.setdefault("instruction_template", "自定义任务")
    st.session_state.setdefault("loaded_flow_file", "")
    st.session_state.setdefault("loaded_flow_info", {})

    left, right = st.columns([1.08, 1.92])

    with left:
        with st.container(border=True):
            st.subheader("① 选择数据资产")
            st.caption("内置数据可直接使用；“大数据抽样”需先到“数据资产”页生成。")
            if source_paths:
                flow_file = st.selectbox(
                    "流水数据源",
                    options=source_paths,
                    format_func=lambda path: source_labels.get(path, path),
                    key="flow_source_select",
                )
            else:
                flow_file = ""
                st.warning("data/ 下暂未发现可解析的流水 CSV，请用下方“导入 CSV”添加。")

            source = source_map.get(flow_file) or {}
            if source:
                _source_detail(source)

            with st.expander("导入自定义 CSV", expanded=False):
                with st.form("flow_upload_form", clear_on_submit=True):
                    uploaded = st.file_uploader(
                        "选择 CSV 流水",
                        type=["csv"],
                        help="CSV 会保存到 data/imports/，并按表头自动识别格式。",
                    )
                    import_clicked = st.form_submit_button("导入并识别")
                st.caption("支持 AML 标准格式 / 通用中文流水")
                if import_clicked:
                    if uploaded is None:
                        st.warning("请先在文件选择器中选择一个 CSV 文件")
                    else:
                        try:
                            info = services.save_uploaded_flow(uploaded.name, uploaded.getvalue())
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"导入失败：{type(exc).__name__}: {exc}")
                        else:
                            st.session_state["pending_flow_source"] = info["path"]
                            st.success(f"已导入：{info['path']}（{info['rows']:,} 条）")
                            st.rerun()

            load_cols = st.columns([1, 2])
            if load_cols[0].button("加载目标数据", width="stretch", disabled=not flow_file):
                try:
                    info = services.inspect_flow_file(flow_file)
                except Exception as exc:  # noqa: BLE001
                    st.session_state["loaded_flow_file"] = ""
                    st.session_state["loaded_flow_info"] = {}
                    st.error(f"加载失败：{type(exc).__name__}: {exc}")
                else:
                    st.session_state["loaded_flow_file"] = flow_file
                    st.session_state["loaded_flow_info"] = info
                    st.success(f"目标已加载：{info['rows']:,} 条 · {info['format']}")

            loaded_file = st.session_state.get("loaded_flow_file", "")
            loaded_info = st.session_state.get("loaded_flow_info") or {}
            if loaded_info and loaded_file == flow_file:
                load_cols[1].caption(
                    f"已加载 `{loaded_info['path']}`\n\n"
                    f"{loaded_info['rows']:,} 条 · {loaded_info['format']}"
                )
                with st.expander("数据预览（前 8 行）", expanded=False):
                    try:
                        preview = _load_preview(flow_file, 8)
                        st.dataframe(
                            preview["records"], width="stretch", hide_index=True, height=220
                        )
                        st.caption(f"列：{', '.join(preview['columns'])}")
                    except Exception as exc:  # noqa: BLE001
                        st.warning(f"预览失败：{type(exc).__name__}: {exc}")
            else:
                load_cols[1].caption("选择数据源后，先加载目标。")

        with st.container(border=True):
            st.subheader("② 下达侦查指令")
            template = st.selectbox(
                "指令模板（可选）",
                options=list(INSTRUCTION_TEMPLATES.keys()),
                key="instruction_template",
                on_change=_apply_instruction_template,
            )
            instruction = st.text_area(
                "侦查任务描述",
                key="task_instruction",
                placeholder="请输入本次侦查目标，例如：分析这批流水，找出可疑账户并生成研判结论",
                height=110,
            )
            st.caption("模板用于快速填入描述，执行以描述内容为准。")
            enable_report = st.toggle(
                "执行 AI 研判报告",
                value=report_agent_enabled(),
                help="关闭后只执行图工具分析（更快，适合先看图谱）。",
            )
            with st.expander("任务口径说明", expanded=False):
                st.markdown(_RULE_NOTE)

        with st.container(border=True):
            st.subheader("③ 执行任务")
            ready = bool(flow_file and loaded_file == flow_file and instruction.strip())
            if ready:
                st.caption(
                    f"数据源：`{Path(flow_file).name}` · "
                    f"{int(source.get('rows') or 0):,} 条 · "
                    f"AI 报告：{'开' if enable_report else '关'}"
                )
            else:
                st.caption("请先加载目标数据并填写任务描述。")
            run_now = st.button(
                "下发并立即执行",
                type="primary",
                width="stretch",
                disabled=not ready,
            )
            action_cols = st.columns(2)
            submit_queue = action_cols[0].button(
                "下发任务到队列", width="stretch", disabled=not ready
            )
            run_graph_only = action_cols[1].button(
                "仅执行图工具分析", width="stretch", disabled=not ready
            )
            if queue[tasks.STATUS_QUEUED]:
                st.caption(f"队列中有 {queue[tasks.STATUS_QUEUED]} 个任务待执行。")

    with right:
        with st.container(border=True):
            head_cols = st.columns([3, 1])
            head_cols[0].subheader("运行监控")
            badge_slot = head_cols[1].empty()
            badge_slot.markdown(theme.pill("待命", "muted"), unsafe_allow_html=True)
            stage_box = st.empty()
            stage_box.markdown(
                theme.pipeline_stages(STAGES, _stage_states(set())), unsafe_allow_html=True
            )
            progress = st.progress(0.0, text="等待任务")
            status_line = st.empty()
            status_line.caption("加载目标数据并填写任务描述后，点“下发并立即执行”。")
            with st.expander("调度日志", expanded=True):
                log_box = st.empty()
                log_box.code("（等待任务下发）", language="text")
            with st.expander("AI 报告流式输出", expanded=False):
                token_box = st.empty()
                token_box.caption("执行带 AI 报告的任务时，这里会逐 token 显示报告。")

        with st.container(border=True):
            st.subheader("最近任务")
            recent = tasks.list_tasks(limit=6)
            if recent:
                st.dataframe(_recent_task_rows(recent), width="stretch", hide_index=True)
            else:
                st.caption("暂无任务记录。")

    if not (submit_queue or run_now or run_graph_only):
        active = executor.active_ids()
        if active:
            running = tasks.load_task(active[-1]) or {}
            percent = int(float(running.get("progress") or 0) * 100)
            st.info(
                f"任务 `{active[-1]}` 正在后台执行（进度 {percent}%）。"
                "任务不依赖当前页面，切换页面或刷新浏览器不会中断；完成后可在“任务队列”查看。"
            )
            if st.button("刷新执行进度", key="refresh_active_task"):
                st.rerun()
        last_id = st.session_state.get("last_task_id")
        last_task = tasks.load_task(last_id) if last_id else None
        if last_task is None:
            latest = tasks.list_tasks(limit=1)
            last_task = latest[0] if latest else None
        _render_bottom(last_task)
        return

    if run_graph_only:
        enable_report = False

    if not ready:
        st.error("请先加载目标数据并填写侦查任务描述，再下发任务。")
        _render_bottom(None)
        return

    task = tasks.create_task(
        instruction=instruction,
        flow_file=flow_file,
        enable_report=enable_report,
        preset=template,
    )

    if submit_queue:
        services.audit_event(
            "task",
            "enqueue",
            {"task_id": task["id"], "flow_file": flow_file},
        )
        st.success(
            f"任务已加入队列：`{task['id']}`。请到“任务队列”页面执行；"
            f"当前队列共 {tasks.queue_summary()[tasks.STATUS_QUEUED]} 个任务。"
        )
        _render_bottom(tasks.load_task(task["id"]))
        return

    services.audit_event(
        "task",
        "start",
        {"task_id": task["id"], "flow_file": flow_file, "enable_report": enable_report},
    )
    badge_slot.markdown(theme.pill(f"执行中 · {task['id']}", "warn"), unsafe_allow_html=True)

    task_id = task["id"]
    started = time.perf_counter()

    def refresh_stages(done_nodes: set[str], active: str | None = None) -> None:
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(done_nodes), active),
            unsafe_allow_html=True,
        )

    def apply_task_state(current: dict) -> set[str]:
        steps = current.get("steps") or []
        done_nodes = {step.get("node") for step in steps if step.get("node")}
        active_node = steps[-1].get("node") if steps else None
        refresh_stages(done_nodes, active=active_node)
        logs_now = [str(line) for line in current.get("logs") or []]
        log_box.code(
            "\n".join(logs_now[-120:]) if logs_now else "（等待日志）", language="text"
        )
        stream_text = tasks.read_stream(task_id)
        if stream_text:
            token_box.markdown(stream_text)
        progress.progress(
            float(current.get("progress") or 0.0),
            text=f"运行中：{active_node or '准备'} · 已用时 {time.perf_counter() - started:.1f}s",
        )
        status_line.markdown(
            f"任务 `{task_id}` · 运行中：`{active_node or '准备'}` · "
            f"已用时 **{time.perf_counter() - started:.1f}s**"
        )
        return done_nodes

    # 任务在独立线程执行，页面只轮询状态；刷新/切页不会中断任务
    if not executor.start(task_id):
        st.error("已有任务正在执行，请稍后再试。")
        _render_bottom(tasks.load_task(task_id))
        return

    done: set[str] = set()
    while executor.is_running(task_id):
        done = apply_task_state(tasks.load_task(task_id) or task)
        time.sleep(0.4)

    task = tasks.load_task(task_id) or task
    done = apply_task_state(task)
    refresh_stages(done)

    if task.get("status") == tasks.STATUS_FAILED:
        progress.progress(1.0, text="任务失败")
        status_line.error(f"任务失败：{task.get('error', '未知错误')}")
        badge_slot.markdown(theme.pill("失败", "danger"), unsafe_allow_html=True)
        services.audit_event(
            "task",
            "failed",
            {"task_id": task_id, "error": task.get("error", "")},
        )
        _render_bottom(task)
        return

    if task.get("status") != tasks.STATUS_COMPLETED:
        progress.progress(1.0, text="任务状态待确认")
        status_line.warning("后台执行已结束，但任务状态不是完成，请到“任务队列”查看。")
        badge_slot.markdown(theme.pill("待确认", "warn"), unsafe_allow_html=True)
        _render_bottom(task)
        return

    elapsed = time.perf_counter() - started
    st.session_state["last_task_id"] = task_id
    progress.progress(1.0, text="任务完成")
    status_line.success(f"任务完成，用时 {elapsed:.1f} 秒 · 任务号 `{task_id}`")
    badge_slot.markdown(theme.pill("已完成", "ok"), unsafe_allow_html=True)
    token_box.empty()
    services.audit_event(
        "task",
        "finish",
        {
            "task_id": task_id,
            "elapsed_s": round(elapsed, 1),
            "report": task.get("report_path", ""),
            "llm_status": task.get("llm_status", ""),
        },
    )
    _render_bottom(task)
