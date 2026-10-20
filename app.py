# -*- coding: utf-8 -*-
"""“警链智析”集成展示平台入口（第一台电脑：核心调度与编排工作台）。

启动：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    streamlit run app.py
"""

import streamlit as st

from workbench import services, theme

# 目录名不能叫 platform（与 Python 标准库冲突），所以平台包命名为 workbench
from workbench.pages import graph_page, metrics, orchestration, overview, reports_page, system_page

st.set_page_config(
    page_title="警链智析 · 多智能体电诈资金穿透研判平台",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_theme()

PAGES = {
    "作战总览": overview.render,
    "智能体编排": orchestration.render,
    "资金图谱": graph_page.render,
    "规则与指标": metrics.render,
    "报告中心": reports_page.render,
    "节点与安全": system_page.render,
}

with st.sidebar:
    st.markdown(
        "<div style='font-size:19px;font-weight:800;color:#7dd3fc;letter-spacing:1px;'>"
        "警链智析</div>"
        "<div style='font-size:11px;color:#64748b;margin-bottom:6px;'>"
        "多智能体电诈资金图谱研判平台</div>",
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
        tone = "ok" if node["status"] == "online" else ("warn" if node["status"] == "warn" else "danger")
        st.markdown(
            theme.pill(f"NODE {node['index']} · {node['role']}", tone),
            unsafe_allow_html=True,
        )

    st.divider()
    st.caption(f"部署模式：{services.deployment_mode()}")
    st.caption("平台版本：v0.4 集成展示平台")
    st.caption(f"当前时间：{theme.now_text()}")
    if st.button("刷新状态", width="stretch"):
        st.rerun()

theme.hero(
    title="“警链智析”——面向电诈资金图谱的自主协同智能体",
    subtitle="第一台电脑 · 核心调度与编排工作台 | 多智能体编排 · 图计算 · 本地大模型 · 全离线部署",
    badges=[
        "全离线部署",
        "多智能体协同",
        "Neo4j 图计算",
        "本地大模型",
        "实时编排可视化",
        "审计与断网自证",
    ],
)

PAGES[page]()
