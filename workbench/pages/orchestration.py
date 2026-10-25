# -*- coding: utf-8 -*-
"""Coordinator 调度台：任务入队/执行、阶段进度、调用日志、流式报告与追加指令。"""

import time
from pathlib import Path

import streamlit as st

from llms.remote_llm import report_agent_enabled
from workbench import coordinator, services, tasks, theme
from workbench.runner import STAGES

DATASETS = {
    "data/synthetic_aml/transactions.csv": "合成 AML 数据集（42,175 条）",
    "data/sample_flow.csv": "第一版演示数据（100 条）",
}


def _stage_states(done: set[str]) -> dict[str, str]:
    return {key: ("done" if key in done else "pending") for key, _, _ in STAGES}


def render() -> None:
    theme.section("元智能体调度", "任务下发 → 排队/执行 → 子智能体调用 → 结果汇总")

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
    st.markdown(
        '<div class="jz-note"><b>调用链：</b>Node1 调度中心 → Node2 GPU 算力中心'
        "（Qwen3-4B 微调 + Qwen-Agent，待接入）↔ Node3 工具与图数据节点"
        "（Neo4j / pandas）。Node2 接入前，本机 Ollama 仅作为开发调试的临时推理服务。</div>",
        unsafe_allow_html=True,
    )

    debug = services.debug_inference_status()
    left, right = st.columns([1.05, 1.95])

    with left:
        st.markdown("#### 任务下发")
        preset = st.selectbox(
            "任务模板",
            options=[
                "自定义任务",
                "全量资金穿透分析",
                "重点排查环形转账",
                "重点排查水房归集",
            ],
        )
        dataset = st.selectbox(
            "数据源（Node3 工具读取）",
            options=list(DATASETS.keys()),
            format_func=lambda path: DATASETS.get(path, path),
        )
        custom_path = st.text_input(
            "或输入自定义 CSV 路径",
            value="",
            placeholder="例如 data/my_flow.csv",
        )
        flow_file = custom_path.strip() or dataset

        default_instruction = {
            "自定义任务": "分析这批流水，找出可疑账户并生成研判结论",
            "全量资金穿透分析": "对这批流水做全量资金穿透分析，输出可疑账户和研判报告",
            "重点排查环形转账": "重点排查环形转账链，找出闭环资金网络及其关联账户",
            "重点排查水房归集": "重点排查多层归集账户，分析水房特征与资金去向",
        }.get(preset, "分析这批流水，找出可疑账户并生成研判结论")
        instruction = st.text_area("侦查任务描述", value=default_instruction, height=90)
        enable_report = st.toggle(
            "执行 AI 研判报告",
            value=report_agent_enabled(),
            help="Node2 接入前由本机 Ollama 承担；关闭后只执行图工具分析",
        )

        if debug["ok"]:
            st.markdown(
                theme.pill(f"调试推理可用：{debug['model']}", "ok"),
                unsafe_allow_html=True,
            )
            st.caption(f"{debug['base_url']} · Node2 接入后自动切换")
        else:
            st.markdown(
                theme.pill("调试推理不可用：报告将降级为规则模板", "warn"),
                unsafe_allow_html=True,
            )
            st.caption(debug.get("error", ""))

        if queue[tasks.STATUS_QUEUED]:
            st.caption(f"当前有 {queue[tasks.STATUS_QUEUED]} 个任务在队列中，建议先执行队列。")

        submit_queue = st.button("提交到任务队列", width="stretch")
        run_now = st.button("立即执行任务", type="primary", width="stretch")
        run_graph_only = st.button("仅执行图工具分析（立即运行）", width="stretch")

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
        st.markdown(
            '<div class="jz-note">提交到队列后可到“任务队列”统一执行；也可以立即执行当前任务。</div>',
            unsafe_allow_html=True,
        )
        return

    if run_graph_only:
        enable_report = False

    task = tasks.create_task(
        instruction=instruction,
        flow_file=flow_file,
        enable_report=enable_report,
        preset=preset,
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

    evidence = final_state.get("evidence") or {}
    suspects = final_state.get("suspicious_accounts") or []
    intermediate = task.get("intermediate") or {}

    theme.section("任务结果", f"任务号 {task['id']} · 已写入任务队列与调用日志")
    cols = st.columns(5)
    cols[0].metric("可疑账户", len(suspects))
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

    conclusion = final_state.get("conclusion") or task.get("conclusion") or ""
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
                key=f"dl_task_report_{task['id']}",
            )
        if evidence_path and Path(evidence_path).exists():
            download_cols[1].download_button(
                "下载证据 JSON",
                data=services.read_text(Path(evidence_path)),
                file_name=Path(evidence_path).name,
                mime="application/json",
                width="stretch",
                key=f"dl_task_evidence_{task['id']}",
            )
    else:
        st.info("本次未启用 AI 研判报告，仅输出图工具分析结果。")

    if task.get("enable_report") and task.get("evidence_path"):
        with st.expander("追加侦查指令", expanded=False):
            st.caption("在已有证据与报告基础上追加分析；调试模式约需几十秒到 2 分钟。")
            follow = st.text_input(
                "追加指令",
                placeholder="例如：重点说明环形转账链的资金闭环特征",
                key=f"follow_input_{task['id']}",
            )
            if st.button("执行追加分析", key=f"follow_btn_{task['id']}"):
                if not follow.strip():
                    st.warning("请先输入追加指令")
                else:
                    with st.spinner("正在调用 AI 分析追加指令……"):
                        try:
                            answer = coordinator.follow_up(task["id"], follow.strip())
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"追加分析失败：{type(exc).__name__}: {exc}")
                        else:
                            st.markdown(answer)
        follow_ups = tasks.load_task(task["id"]).get("follow_ups") or []
        for item in follow_ups:
            with st.expander(f"历史追加：{item.get('instruction', '')[:40]}", expanded=False):
                st.markdown(item.get("answer", ""))

    with st.expander(f"可疑账户清单（{len(suspects)} 个）", expanded=False):
        st.write(suspects)

    if task.get("node_calls"):
        with st.expander("子智能体调用记录", expanded=False):
            st.dataframe(task["node_calls"], width="stretch", hide_index=True)

    with st.expander("调度日志（完整）", expanded=False):
        st.code("\n".join(logs) if logs else "\n".join(task.get("logs") or []), language="text")
