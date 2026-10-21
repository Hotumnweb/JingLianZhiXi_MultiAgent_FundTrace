# -*- coding: utf-8 -*-
"""元智能体调度台：任务下发、阶段进度、调度日志、流式报告。"""

import time
from pathlib import Path

import streamlit as st

from llms.remote_llm import report_agent_enabled
from workbench import services, theme
from workbench.runner import STAGES, iter_pipeline

DATASETS = {
    "data/synthetic_aml/transactions.csv": "合成 AML 数据集（42,175 条）",
    "data/sample_flow.csv": "第一版演示数据（100 条）",
}


def _stage_states(done: set[str]) -> dict[str, str]:
    return {key: ("done" if key in done else "pending") for key, _, _ in STAGES}


def render() -> None:
    theme.section("元智能体调度", "任务下发 → 调度决策 → 工具调用 → 结果汇总")

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
        instruction = st.text_area(
            "侦查任务描述",
            value="分析这批流水，找出可疑账户并生成研判结论",
            height=90,
        )
        enable_report = st.toggle(
            "启用 AI 研判报告",
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

        run_full = st.button("下发任务并执行", type="primary", width="stretch")
        run_graph_only = st.button("仅执行图工具分析（不调用 AI）", width="stretch")

    with right:
        stage_box = st.empty()
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(set())), unsafe_allow_html=True
        )
        progress = st.progress(0.0, text="等待任务")
        status_line = st.empty()
        log_box = st.empty()
        token_box = st.empty()

    if not (run_full or run_graph_only):
        st.markdown(
            '<div class="jz-note">下发任务后，这里会实时显示调度阶段、工具调用日志和 AI 输出。</div>',
            unsafe_allow_html=True,
        )
        return

    if run_graph_only:
        enable_report = False

    done: set[str] = set()
    logs: list[str] = []
    tokens: list[str] = []
    final_state: dict = {}
    started = time.perf_counter()
    services.audit_event(
        "task",
        "start",
        {"flow_file": flow_file, "enable_report": enable_report},
    )

    def refresh_stages(active: str | None = None) -> None:
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(done), active),
            unsafe_allow_html=True,
        )

    try:
        for kind, node, payload in iter_pipeline(
            flow_file=flow_file,
            instruction=instruction,
            enable_report=enable_report,
            accumulate=final_state,
        ):
            if kind == "update":
                if node in {key for key, _, _ in STAGES}:
                    done.add(node)
                refresh_stages(active=node)
                if isinstance(payload, dict) and payload.get("logs"):
                    logs = list(payload["logs"])
                progress_value = min(0.95, 0.10 + 0.28 * len(done))
                if "report_agent" in done:
                    progress_value = 0.97
                progress.progress(
                    progress_value,
                    text=f"运行中：{node} · 已用时 {time.perf_counter() - started:.1f}s",
                )
                status_line.markdown(
                    f"运行中：`{node}` · 已用时 **{time.perf_counter() - started:.1f}s**"
                )
                log_box.code("\n".join(logs[-120:]) if logs else "（等待日志）", language="text")
            elif kind == "custom":
                if isinstance(payload, dict) and payload.get("type") == "token":
                    tokens.append(str(payload.get("text") or ""))
                    if tokens and len(tokens) % 4 == 0:
                        token_box.markdown("".join(tokens))
            elif kind == "final":
                final_state = payload

        refresh_stages()
        progress.progress(1.0, text="任务完成")
        elapsed = time.perf_counter() - started
        status_line.success(f"任务完成，用时 {elapsed:.1f} 秒")
        log_box.code("\n".join(logs[-120:]) if logs else "（无日志）", language="text")
        token_box.empty()
        services.audit_event(
            "task",
            "finish",
            {
                "flow_file": flow_file,
                "elapsed_s": round(elapsed, 1),
                "report": final_state.get("report_path", ""),
                "llm_status": final_state.get("llm_status", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 前端展示错误，同时写入调度日志
        progress.progress(1.0, text="任务失败")
        status_line.error(f"任务失败：{type(exc).__name__}: {exc}")
        services.audit_event(
            "task",
            "failed",
            {"flow_file": flow_file, "error": f"{type(exc).__name__}: {exc}"},
        )
        return

    evidence = final_state.get("evidence") or {}
    suspects = final_state.get("suspicious_accounts") or []
    st.session_state["last_pipeline"] = {
        "suspicious_accounts": suspects,
        "conclusion": final_state.get("conclusion", ""),
        "report_path": final_state.get("report_path", ""),
        "evidence_path": final_state.get("evidence_path", ""),
        "llm_status": final_state.get("llm_status", ""),
        "evidence": evidence,
    }

    theme.section("任务结果", "可疑账户 · 证据构成 · 研判报告")
    cols = st.columns(5)
    cols[0].metric("可疑账户", len(suspects))
    cols[1].metric("归集账户", len(evidence.get("gather") or []))
    cols[2].metric("环形链", len(evidence.get("cycles") or []))
    cols[3].metric("快进快出", len(evidence.get("fast_io") or []))
    cols[4].metric(
        "报告状态",
        {"ok": "AI 生成", "fallback": "规则兜底"}.get(final_state.get("llm_status", ""), "未启用"),
    )

    conclusion = final_state.get("conclusion") or ""
    if conclusion:
        if final_state.get("llm_status") == "fallback":
            st.warning("AI 调用失败，已自动降级为规则模板报告。")
        with st.container(border=True):
            st.markdown(conclusion)
        report_path = final_state.get("report_path")
        evidence_path = final_state.get("evidence_path")
        download_cols = st.columns(2)
        if report_path:
            download_cols[0].download_button(
                "下载研判报告（Markdown）",
                data=services.read_text(Path(report_path)),
                file_name=Path(report_path).name,
                mime="text/markdown",
                width="stretch",
            )
        if evidence_path:
            download_cols[1].download_button(
                "下载证据 JSON",
                data=services.read_text(Path(evidence_path)),
                file_name=Path(evidence_path).name,
                mime="application/json",
                width="stretch",
            )
        st.caption(f"报告：{report_path} ｜ 证据：{evidence_path}")
    else:
        st.info("本次未启用 AI 研判报告，仅输出图工具分析结果。")

    with st.expander(f"可疑账户清单（{len(suspects)} 个）", expanded=False):
        st.write(suspects)

    with st.expander("调度日志（完整）", expanded=False):
        st.code("\n".join(logs), language="text")
