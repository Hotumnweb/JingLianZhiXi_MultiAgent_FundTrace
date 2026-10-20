# -*- coding: utf-8 -*-
"""Streamlit 前端：运行配置、证据展示、研判报告与下载。

启动（项目根目录下）：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    streamlit run app.py
"""

import json
import os
from pathlib import Path

import streamlit as st

from llms.remote_llm import check_connection, load_llm_config
from main import DEFAULT_FLOW_FILE, app, initial_state

st.set_page_config(
    page_title="警链智析——电诈资金穿透研判",
    page_icon="🔎",
    layout="wide",
)

st.title("“警链智析”——面向电诈资金图谱的自主协同智能体")
st.caption(
    "完整链路：流水解析 → Neo4j 建图 → 图规则分析（归集/环形/快进快出）→ 大模型研判报告"
)

llm_config = load_llm_config()

with st.sidebar:
    st.header("运行配置")
    flow_file = st.text_input(
        "流水文件路径",
        value=DEFAULT_FLOW_FILE,
        help="默认使用合成 AML 数据集；可改成 data/sample_flow.csv 跑 100 条演示数据",
    )
    instruction = st.text_area(
        "侦查指令",
        value="分析这批流水，找出可疑账户并生成研判结论",
        height=100,
    )

    st.divider()
    st.subheader("大模型")
    st.caption(f"服务：`{llm_config.base_url}`")
    st.caption(f"模型：`{llm_config.model}`")
    st.caption(f"上下文：{llm_config.num_ctx}；超时：{llm_config.timeout} 秒")

    use_llm = st.checkbox(
        "启用报告节点（调用 Ollama 生成研判报告）",
        value=os.getenv("ENABLE_REPORT_AGENT", "0").strip() in {"1", "true", "yes", "on"},
    )

    if st.button("测试大模型连接", use_container_width=True):
        with st.spinner("正在检查 Ollama……"):
            info = check_connection()
        if info["ok"]:
            if info.get("available"):
                st.success(f"Ollama 可访问，模型已就绪：{info['models']}")
            else:
                st.warning(f"Ollama 可访问，但未找到模型 {info['model']}。现有：{info['models']}")
        else:
            st.error(f"Ollama 不可达：{info['error']}")

    st.caption("本地 CPU 推理较慢：7B 模型生成报告约需 2~4 分钟，请耐心等待。")

start = st.button("开始分析", type="primary", use_container_width=True)

if start:
    os.environ["ENABLE_REPORT_AGENT"] = "1" if use_llm else "0"
    wait_text = (
        "智能体运行中：解析 4.2 万条流水 + 图规则分析 + 本地 CPU 大模型生成报告，约需 2~4 分钟……"
        if use_llm
        else "智能体运行中：解析流水 + 图规则分析……"
    )
    with st.spinner(wait_text):
        try:
            result = app.invoke(
                initial_state(instruction=instruction, flow_file=flow_file)
            )
        except Exception as exc:  # noqa: BLE001 - 前端直接把错误展示给使用者
            st.error(f"运行失败：{type(exc).__name__}: {exc}")
            st.info("排查顺序：1) Neo4j 是否已启动；2) 流水文件是否存在；3) .env 配置是否正确")
            st.stop()

    evidence = result.get("evidence") or {}
    suspects = result.get("suspicious_accounts") or []

    metric_cols = st.columns(5)
    metric_cols[0].metric("可疑账户", len(suspects))
    metric_cols[1].metric("归集账户", len(evidence.get("gather", [])))
    metric_cols[2].metric("环形链", len(evidence.get("cycles", [])))
    metric_cols[3].metric("快进快出", len(evidence.get("fast_io", [])))
    metric_cols[4].metric(
        "报告状态",
        {"ok": "大模型", "fallback": "规则兜底"}.get(result.get("llm_status", ""), "-"),
    )

    if result.get("llm_status") == "fallback":
        st.warning("大模型调用失败，已自动降级为规则模板报告。请检查 Ollama 是否启动、模型是否存在。")

    left, right = st.columns([3, 2])

    with left:
        st.subheader("研判报告")
        st.markdown(result.get("conclusion") or "（未生成报告）")

        report_path = result.get("report_path")
        if report_path and Path(report_path).exists():
            report_text = Path(report_path).read_text(encoding="utf-8")
            st.download_button(
                "下载研判报告（Markdown）",
                data=report_text,
                file_name=Path(report_path).name,
                mime="text/markdown",
                use_container_width=True,
            )

    with right:
        st.subheader("可疑账户")
        if suspects:
            with st.expander(f"展开全部 {len(suspects)} 个账户（强证据优先）", expanded=False):
                for account in suspects:
                    st.markdown(f"- `{account}`")
        else:
            st.caption("（本次未发现可疑账户）")

        evidence_path = result.get("evidence_path")
        if evidence_path and Path(evidence_path).exists():
            evidence_text = Path(evidence_path).read_text(encoding="utf-8")
            st.download_button(
                "下载证据 JSON",
                data=evidence_text,
                file_name=Path(evidence_path).name,
                mime="application/json",
                use_container_width=True,
            )

    with st.expander("图规则证据明细", expanded=False):
        if evidence.get("gather"):
            st.markdown("**多层归集账户**")
            st.dataframe(evidence["gather"], use_container_width=True)
        if evidence.get("cycles"):
            st.markdown("**环形转账链**")
            cycle_rows = [
                {
                    "链路": " → ".join(item["accounts"] + [item["accounts"][0]]),
                    "跳数": item["length"],
                    "涉案金额": item["amount"],
                    "跨度(小时)": item["span_hours"],
                }
                for item in evidence["cycles"]
            ]
            st.dataframe(cycle_rows, use_container_width=True)
        if evidence.get("fast_io"):
            st.markdown("**快进快出账户（辅助证据）**")
            st.dataframe(evidence["fast_io"], use_container_width=True)

    with st.expander("执行日志", expanded=False):
        st.code("\n".join(result.get("logs", [])) or "（无日志）", language="text")
