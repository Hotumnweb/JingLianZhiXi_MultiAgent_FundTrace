# -*- coding: utf-8 -*-
"""智能体编排控制台：实时阶段进度、调度日志、流式报告。"""

import time
from pathlib import Path

import streamlit as st

from llms.remote_llm import load_llm_config, report_agent_enabled
from workbench import services, theme
from workbench.runner import STAGES, iter_pipeline

DATASETS = {
    "data/synthetic_aml/transactions.csv": "合成 AML 数据集（42,175 条）",
    "data/sample_flow.csv": "第一版演示数据（100 条）",
}


def _stage_states(done: set[str]) -> dict[str, str]:
    return {key: ("done" if key in done else "pending") for key, _, _ in STAGES}


def render() -> None:
    config = load_llm_config()
    theme.section(
        "智能体编排控制台",
        "Supervisor 调度 → 流水解析 → 账户关联 → 研判报告，全过程实时可视化",
    )

    left, right = st.columns([1.05, 1.95])

    with left:
        st.markdown("#### 任务输入")
        dataset = st.selectbox(
            "数据源",
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
            "侦查指令",
            value="分析这批流水，找出可疑账户并生成研判结论",
            height=90,
        )
        enable_report = st.toggle(
            "启用大模型研判报告（Ollama）",
            value=report_agent_enabled(),
            help="关闭后只跑解析 + 图分析，适合断网/无模型时快速演示",
        )
        is_local = "127.0.0.1" in config.base_url or "localhost" in config.base_url
        st.markdown(
            f"""
            <div class="jz-note">
              模型：<b>{theme.esc(config.model)}</b><br>
              服务：{theme.esc(config.base_url)}<br>
              {"本地 CPU 推理：报告生成约 2~4 分钟" if is_local else "GPU 节点推理：报告生成约数十秒"}
            </div>
            """,
            unsafe_allow_html=True,
        )
        run_full = st.button("🚀 启动全链路分析", type="primary", width="stretch")
        run_graph_only = st.button("仅跑图分析（不调大模型）", width="stretch")

    with right:
        stage_box = st.empty()
        stage_box.markdown(
            theme.pipeline_stages(STAGES, _stage_states(set())), unsafe_allow_html=True
        )
        progress = st.progress(0.0, text="等待启动")
        status_line = st.empty()
        log_box = st.empty()
        token_box = st.empty()

    if not (run_full or run_graph_only):
        st.markdown(
            '<div class="jz-note">点击左侧按钮启动分析。想快速看效果，用“仅跑图分析”。</div>',
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
        "pipeline",
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
        progress.progress(1.0, text="全链路完成")
        elapsed = time.perf_counter() - started
        status_line.success(f"分析完成，用时 {elapsed:.1f} 秒")
        log_box.code("\n".join(logs[-120:]) if logs else "（无日志）", language="text")
        token_box.empty()
        services.audit_event(
            "pipeline",
            "finish",
            {
                "flow_file": flow_file,
                "elapsed_s": round(elapsed, 1),
                "report": final_state.get("report_path", ""),
                "llm_status": final_state.get("llm_status", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 前端展示错误，同时写入审计日志
        progress.progress(1.0, text="运行失败")
        status_line.error(f"运行失败：{type(exc).__name__}: {exc}")
        services.audit_event(
            "pipeline",
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

    theme.section("本次运行结果", "可疑账户 · 证据构成 · 研判报告")
    cols = st.columns(5)
    cols[0].metric("可疑账户", len(suspects))
    cols[1].metric("归集账户", len(evidence.get("gather") or []))
    cols[2].metric("环形链", len(evidence.get("cycles") or []))
    cols[3].metric("快进快出", len(evidence.get("fast_io") or []))
    cols[4].metric(
        "报告状态",
        {"ok": "大模型", "fallback": "规则兜底"}.get(final_state.get("llm_status", ""), "未启用"),
    )

    conclusion = final_state.get("conclusion") or ""
    if conclusion:
        if final_state.get("llm_status") == "fallback":
            st.warning("大模型调用失败，已自动降级为规则模板报告。")
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
        st.info("本次未启用报告节点，仅输出图分析结果（可疑账户见下）。")

    with st.expander(f"可疑账户清单（{len(suspects)} 个，强证据优先）", expanded=False):
        st.write(suspects)

    with st.expander("执行日志（完整）", expanded=False):
        st.code("\n".join(logs), language="text")
