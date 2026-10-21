# -*- coding: utf-8 -*-
"""“警链智析”元智能体调度中枢（第一台电脑：Coordinator Node）。

职责边界（与三机架构一致）：
- 本机只做任务下发、调度决策、状态管理、日志与结果汇总；
- 不运行大模型、不运行图数据库；
- 大模型能力调用 Node2（GPU 算力中心，当前占位）；
- 图数据与重工具调用 Node3（工具与图数据节点，当前部署在本机调试）。

启动：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    streamlit run app.py
"""

import streamlit as st

from workbench import services, theme
from workbench.pages import graph_page, metrics, orchestration, overview, reports_page, system_page

# 目录名不能叫 platform（与 Python 标准库冲突），所以平台包命名为 workbench
st.set_page_config(
    page_title="警链智析 · 元智能体调度中枢",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_theme()

PAGES = {
    "调度总览": overview.render,
    "元智能体调度": orchestration.render,
    "图数据与工具": graph_page.render,
    "规则与指标": metrics.render,
    "研判报告": reports_page.render,
    "节点与工具": system_page.render,
}

with st.sidebar:
    st.markdown(
        "<div style='font-size:19px;font-weight:800;color:#7dd3fc;letter-spacing:1px;'>"
        "警链智析</div>"
        "<div style='font-size:11px;color:#64748b;margin-bottom:6px;'>"
        "元智能体调度中枢 · Node1</div>",
        unsafe_allow_html=True,
    )
    page = st.radio(
        "平台导航",
        list(PAGES.keys()),
        key="nav_page",
        label_visibility="collapsed",
    )
    st.divider()

    for node in services.node_status():
        tone = {
            "online": "ok",
            "warn": "warn",
            "placeholder": "muted",
        }.get(node["status"], "danger")
        st.markdown(
            theme.pill(f"NODE {node['index']} · {node['role']}", tone),
            unsafe_allow_html=True,
        )
    st.caption("Node2：Qwen3-4B 微调 + Qwen-Agent 待接入")
    if st.button("刷新节点状态", width="stretch"):
        st.rerun()

theme.hero(title="警链智析 · 元智能体调度中枢")

PAGES[page]()
