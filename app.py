# -*- coding: utf-8 -*-
"""警链智析-多智能体驱动的涉诈资金穿透研判系统（第一台电脑：Coordinator Node）。

职责边界（与三机架构一致）：
- 本机只做任务下发、调度决策、状态管理、日志与结果汇总；
- 不运行大模型、不运行图数据库；
- 大模型能力调用 Node2（GPU 算力中心）；
- 图数据与重工具调用 Node3（工具与图数据节点）。

启动：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    streamlit run app.py
"""

import streamlit as st

from workbench import services, theme
from workbench.pages import (
    graph_page,
    meta_agent_page,
    metrics,
    neo4j_console,
    orchestration,
    overview,
    reports_page,
    system_page,
    tasks_page,
)

# 目录名不能叫 platform（与 Python 标准库冲突），所以平台包命名为 workbench
APP_NAME = "警链智析-多智能体驱动的涉诈资金穿透研判系统"
APP_SHORT = "警链智析"
APP_SUB = "多智能体驱动的涉诈资金穿透研判系统"

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_theme()

PAGES = {
    "调度总览": overview.render,
    "元智能体调度": orchestration.render,
    "元智能体自主分析": meta_agent_page.render,
    "任务队列": tasks_page.render,
    "图数据与工具": graph_page.render,
    "Neo4j 操作台": neo4j_console.render,
    "规则与指标": metrics.render,
    "研判报告": reports_page.render,
    "节点与工具": system_page.render,
}


def _default_page_index() -> int:
    """支持 ?page=元智能体调度 直接打开指定页面（演示/截图方便）。"""
    try:
        requested = st.query_params.get("page", "")
        if isinstance(requested, list):
            requested = requested[0] if requested else ""
        if requested in PAGES:
            return list(PAGES.keys()).index(requested)
    except Exception:  # noqa: BLE001
        pass
    return 0

with st.sidebar:
    st.markdown(
        '<div class="jz-brand">'
        '<div class="jz-brand-mark">警</div>'
        '<div class="jz-brand-copy">'
        f'<div class="jz-brand-name">{APP_SHORT}</div>'
        f'<div class="jz-brand-sub">{APP_SUB}</div>'
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    page = st.radio(
        "平台导航",
        list(PAGES.keys()),
        index=_default_page_index(),
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
    if st.button("刷新状态", width="stretch"):
        st.rerun()

theme.hero(title=APP_NAME)

PAGES[page]()
