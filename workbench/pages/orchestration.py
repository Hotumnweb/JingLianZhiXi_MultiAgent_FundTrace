# -*- coding: utf-8 -*-
"""Coordinator 调度台：任务入队/执行、阶段进度、调用日志、流式报告与追加指令。"""

import json
import time
from pathlib import Path

import streamlit as st

from llms.remote_llm import report_agent_enabled
from workbench import coordinator, services, tasks, theme
from workbench.runner import STAGES

INSTRUCTION_TEMPLATES = {
    "自定义任务": "",
    "全量资金穿透分析": "对这批流水做全量资金穿透分析，输出可疑账户和研判报告",
    "重点排查环形转账": "重点排查环形转账链，找出闭环资金网络及其关联账户",
    "重点排查水房归集": "重点排查多层归集账户，分析水房特征与资金去向",
}


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
    """展示一个已完成任务的结果、报告、追加指令与调用记录。

    从任务 JSON + 证据 JSON 恢复全部内容，因此切换页面/刷新后仍可复用。
    """
    evidence, suspects = _load_task_evidence(task)
    intermediate = task.get("intermediate") or {}
    task_id = task.get("id", "")

    theme.section("任务结果", f"任务号 {task_id}")
    cols = st.columns(5)
    cols[0].metric("可疑账户", task.get("suspicious") or len(suspects))
    cols[1].metric("归集账户", len(evidence.get("gather") or []))
    cols[2].metric("环形链", len(evidence.get("cycles") or []))
    cols[3].metric("快进快出", len(evidence.get("fast_io") or []))
    cols[4].metric(
        "报告状态",
        {"ok": "AI 生成", "fallback": "规则兜底"}.get(task.get("llm_status", ""), "未启用"),
    )

    if intermediate:
        cols = st.columns(4)
        cols[0].metric("解析流水", intermediate.get("parsed_count", "—"))
        cols[1].metric("图账户", intermediate.get("accounts", "—"))
        cols[2].metric("转账边", intermediate.get("transfers", "—"))
        cols[3].metric("耗时", f"{task.get('duration_s', '—')} s")

    conclusion = task.get("conclusion") or ""
    if conclusion:
        if task.get("llm_status") == "fallback":
            st.warning("AI 调用失败，已自动降级为规则模板报告。")
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
    else:
        st.info("本次未启用 AI 研判报告，仅输出图工具分析结果。")

    if task.get("enable_report") and task.get("evidence_path"):
        with st.expander("追加侦查指令", expanded=False):
            st.caption("在已有证据与报告基础上追加分析；Node2 GPU 通常数十秒返回。")
            follow = st.text_input(
                "追加指令",
                placeholder="例如：重点说明环形转账链的资金闭环特征",
                key=f"follow_input_{task_id}",
                persist_state="session",
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
            with st.expander(f"历史追加：{item.get('instruction', '')[:40]}", expanded=False):
                st.markdown(item.get("answer", ""))

    if suspects:
        with st.expander(f"可疑账户清单（{len(suspects)} 个）", expanded=False):
            st.write(suspects)

    if task.get("node_calls"):
        with st.expander("子智能体调用记录", expanded=False):
            st.dataframe(task["node_calls"], width="stretch", hide_index=True)

    logs = task.get("logs") or []
    with st.expander("调度日志（完整）", expanded=False):
        st.code("\n".join(str(line) for line in logs), language="text")


def render() -> None:
    theme.section("元智能体调度", "任务下发 · 队列执行 · 调用追踪")

    queue = tasks.queue_summary()
    st.markdown(
        " ".join(
            [
                theme.pill(f"排队 {queue[tasks.STATUS_QUEUED]}", "info"),
                theme.pill(f"执行中 {queue[tasks.STATUS_RUNNING]}", "warn"),
                theme.pill(f"已完成 {queue[tasks.STATUS_COMPLETED]}", "ok"),
                theme.pill(f"失败 {queue[tasks.STATUS_FAILED]}", "danger"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.caption("Node1 调度中心 · Node2 GPU 推理 · Node3 图数据与工具")

    debug = services.debug_inference_status()
    left, right = st.columns([1.05, 1.95])

    st.session_state.setdefault("task_instruction", "")
    st.session_state.setdefault("instruction_template", "自定义任务")
    st.session_state.setdefault("loaded_flow_file", "")
    st.session_state.setdefault("loaded_flow_info", {})

    sources = services.scan_flow_files()
    source_paths = [item["path"] for item in sources]
    source_labels = {item["path"]: item["label"] for item in sources}

    with left:
        st.markdown("#### 任务下发")
        st.caption("加载目标数据 → 下达侦查指令 → 下发执行")

        pending_select = st.session_state.pop("pending_select_flow", None)
        if pending_select in source_paths:
            st.session_state["flow_source_select"] = pending_select

        if source_paths:
            flow_file = st.selectbox(
                "流水数据源",
                options=source_paths,
                format_func=lambda path: source_labels.get(path, path),
                key="flow_source_select",
                persist_state="session",
            )
        else:
            flow_file = ""
            st.warning("data/ 下暂未发现可解析的流水 CSV，请用下方“导入 CSV”添加。")

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
                        st.session_state["pending_select_flow"] = info["path"]
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
        else:
            load_cols[1].caption("选择数据源后，先加载目标。")

        template = st.selectbox(
            "指令模板（可选）",
            options=list(INSTRUCTION_TEMPLATES.keys()),
            key="instruction_template",
            on_change=_apply_instruction_template,
            persist_state="session",
        )
        instruction = st.text_area(
            "侦查任务描述",
            key="task_instruction",
            placeholder="请输入本次侦查目标，例如：分析这批流水，找出可疑账户并生成研判结论",
            height=100,
            persist_state="session",
        )
        st.caption("模板用于快速填入描述，执行以描述内容为准。")

        enable_report = st.toggle(
            "执行 AI 研判报告",
            value=report_agent_enabled(),
            help="关闭后只执行图工具分析",
        )

        ready = bool(flow_file and loaded_file == flow_file and instruction.strip())
        if not ready:
            st.caption("请先加载目标数据并填写任务描述。")

        if debug["ok"]:
            st.markdown(
                theme.pill(f"推理服务在线 · {debug['model']}", "ok"),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                theme.pill("推理服务离线 · 报告将降级为规则模板", "warn"),
                unsafe_allow_html=True,
            )
            st.caption("请检查 Node2 的 Ollama 服务和 11434 端口。")

        if queue[tasks.STATUS_QUEUED]:
            st.caption(f"队列中有 {queue[tasks.STATUS_QUEUED]} 个任务待执行。")

        submit_queue = st.button(
            "下发任务到队列", width="stretch", disabled=not ready
        )
        run_now = st.button(
            "下发并立即执行", type="primary", width="stretch", disabled=not ready
        )
        run_graph_only = st.button(
            "仅执行图工具分析（立即运行）", width="stretch", disabled=not ready
        )

    with right:
        stage_box = st.empty()
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(set())), unsafe_allow_html=True
        )
        progress = st.progress(0.0, text="等待任务")
        status_line = st.empty()
        log_box = st.empty()
        token_box = st.empty()

    if not (submit_queue or run_now or run_graph_only):
        last_id = st.session_state.get("last_task_id")
        last_task = tasks.load_task(last_id) if last_id else None
        if last_task:
            _render_task_result(last_task)
        else:
            st.caption("从左侧加载目标并填写任务描述，然后下发任务。")
        return

    if run_graph_only:
        enable_report = False

    if not ready:
        st.error("请先加载目标数据并填写侦查任务描述，再下发任务。")
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
        return

    services.audit_event(
        "task",
        "start",
        {"task_id": task["id"], "flow_file": flow_file, "enable_report": enable_report},
    )

    done: set[str] = set()
    logs: list[str] = []
    tokens: list[str] = []
    final_state: dict = {}
    started = time.perf_counter()

    def refresh_stages(active: str | None = None) -> None:
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(done), active),
            unsafe_allow_html=True,
        )

    status_line.markdown(f"任务 `{task['id']}` 已启动……")
    failed = False
    try:
        for kind, node, payload in coordinator.iter_task(task):
            if kind == "update":
                if node in {key for key, _, _ in STAGES}:
                    done.add(node)
                refresh_stages(active=node)
                if isinstance(payload, dict) and payload.get("logs"):
                    logs = [str(line) for line in payload["logs"]]
                progress.progress(
                    min(0.97, 0.10 + 0.28 * len(done)),
                    text=f"运行中：{node} · 已用时 {time.perf_counter() - started:.1f}s",
                )
                status_line.markdown(
                    f"任务 `{task['id']}` · 运行中：`{node}` · "
                    f"已用时 **{time.perf_counter() - started:.1f}s**"
                )
                log_box.code("\n".join(logs[-120:]) if logs else "（等待日志）", language="text")
            elif kind == "custom":
                if isinstance(payload, dict) and payload.get("type") == "token":
                    tokens.append(str(payload.get("text") or ""))
                    if tokens and len(tokens) % 4 == 0:
                        token_box.markdown("".join(tokens))
            elif kind == "final":
                final_state = payload
            elif kind == "task_done":
                task = tasks.load_task(task["id"]) or task
            elif kind == "task_failed":
                task = payload or tasks.load_task(task["id"]) or task
                failed = True

        if failed:
            progress.progress(1.0, text="任务失败")
            status_line.error(f"任务失败：{task.get('error', '未知错误')}")
            return

        refresh_stages()
        progress.progress(1.0, text="任务完成")
        elapsed = time.perf_counter() - started
        task = tasks.load_task(task["id"]) or task
        st.session_state["last_task_id"] = task["id"]
        status_line.success(f"任务完成，用时 {elapsed:.1f} 秒 · 任务号 `{task['id']}`")
        token_box.empty()
        services.audit_event(
            "task",
            "finish",
            {
                "task_id": task["id"],
                "elapsed_s": round(elapsed, 1),
                "report": task.get("report_path", ""),
                "llm_status": task.get("llm_status", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 前端兜底展示
        progress.progress(1.0, text="任务失败")
        status_line.error(f"任务失败：{type(exc).__name__}: {exc}")
        services.audit_event(
            "task",
            "failed",
            {"task_id": task["id"], "error": f"{type(exc).__name__}: {exc}"},
        )
        return

    _render_task_result(task)
