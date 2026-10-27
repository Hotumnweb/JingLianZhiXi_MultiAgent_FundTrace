# -*- coding: utf-8 -*-
"""节点与工具页：三节点状态、工具能力、Node2 接入计划、调度日志。"""

import streamlit as st

from workbench import services, theme


def render() -> None:
    theme.section("节点与工具", "三节点状态 · 运行环境 · 接口清单")

    top_cols = st.columns([1, 1, 4])
    with top_cols[0]:
        if st.button("刷新状态", width="stretch"):
            st.rerun()
    with top_cols[1]:
        mode = "三机内网协同" if services.inference_is_remote() else "开发调试模式"
        st.markdown(theme.pill(mode, "info"), unsafe_allow_html=True)

    nodes = services.node_status()
    node_cols = st.columns(3)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)

    targets = services.node_targets()
    theme.section("三机网络", "节点角色与内网地址")
    st.dataframe(
        [
            {
                "节点": "Node1",
                "角色": "核心调度与编排（Coordinator）",
                "目标地址": "本机",
                "当前状态": "在线",
            },
            {
                "节点": "Node2",
                "角色": "GPU 推理与算力（Inference）",
                "目标地址": targets["node2"],
                "当前状态": "已接入" if services.inference_is_remote() else "待接入",
            },
            {
                "节点": "Node3",
                "角色": "工具执行与图数据（Tool & Graph）",
                "目标地址": targets["node3"],
                "当前状态": "本机部署",
            },
        ],
        width="stretch",
        hide_index=True,
    )

    left, right = st.columns([1, 1])
    with left:
        theme.section("本机环境", "Node1 · Coordinator")
        info = services.system_info()
        st.dataframe(
            [
                {"项目": "主机名", "值": str(info["hostname"])},
                {"项目": "操作系统", "值": str(info["os"])},
                {"项目": "Python", "值": str(info["python"])},
                {"项目": "CPU 核数", "值": str(info["cpu_count"])},
                {"项目": "内存占用", "值": str(info["memory"])},
                {"项目": "内网地址", "值": str(info["local_ips"])},
            ],
            width="stretch",
            hide_index=True,
        )

        if st.button("断网自检", type="primary"):
            result = services.external_network_check()
            services.audit_event("network_check", f"target={result['target']}", result)
            if result["online"]:
                st.warning("当前仍可访问外网；现场演示前请断开外网后重试。")
            else:
                st.success("外网不可达，符合内网演示要求。")

    with right:
        theme.section("接口与工具清单", "Node1 统一调度，Node2/Node3 提供能力")
        st.dataframe(
            [
                {"能力": "任务调度", "提供方": "Node1 · LangGraph Supervisor", "接口/协议": "进程内 StateGraph"},
                {"能力": "任务队列/状态", "提供方": "Node1 · Coordinator", "接口/协议": "runtime/tasks/*.json"},
                {"能力": "大模型推理", "提供方": "Node2 · Qwen3.5-9B-tools + Ollama", "接口/协议": "/api/chat + tools"},
                {"能力": "图数据库", "提供方": "Node3 · Neo4j", "接口/协议": "Bolt 7687"},
                {"能力": "图规则与子图查询", "提供方": "Node3 · Cypher", "接口/协议": "Bolt / Cypher"},
                {"能力": "流水解析", "提供方": "Node3 · pandas / pdfplumber", "接口/协议": "本地工具"},
                {"能力": "报告归档", "提供方": "Node1 · reports/", "接口/协议": "Markdown + JSON"},
                {"能力": "调度日志", "提供方": "Node1 · 本地 JSONL", "接口/协议": "reports/audit/audit.jsonl"},
            ],
            width="stretch",
            hide_index=True,
        )

    theme.section("Node2 推理服务", "GPU 算力中心")
    st.markdown(
        f"""
        - 模型：**qwen3.5-9b-tools:q4km**（Q4_K_M，带 tools）
        - 调用方式：`http://{targets['node2']}:11434` · `/api/chat` + tools
        - Qwen3.5 需关闭 thinking（`LLM_THINK=false`）
        - Qwen-Agent 8010 服务暂未接入，当前直接使用 Ollama 原生接口
        """
    )

    theme.section("Node3 工具与图数据", "本机部署")
    st.markdown(
        """
        - **Neo4j 图数据库**：账户节点、TRANSFER 关系、Cypher 查询
        - **文件解析**：pandas 解析 CSV 流水
        - **图规则**：快进快出 / 多层归集 / 环形转账
        """
    )

    theme.section("调度日志", "任务与检测事件")
    audit = services.read_audit(60)
    if audit:
        st.dataframe(
            [
                {
                    "时间": entry.get("ts", ""),
                    "类型": entry.get("kind", ""),
                    "内容": entry.get("message", ""),
                    "附加": str(entry.get("extra", ""))[:90],
                }
                for entry in audit
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("暂无调度日志。下发一次任务或执行外网检测后会自动记录。")

    with st.expander("赛前检查清单", expanded=False):
        checklist = [
            ("Node1 调度中心", "平台正常打开、任务可下发"),
            ("Node2 算力节点", "Ollama 在线、模型已加载、11434 可达"),
            ("Node3 工具与图数据", "Neo4j 已启动，图谱可查询"),
            ("外网隔离", "断网自检确认外网不可达"),
            ("研判报告", "任务完成后报告与证据已归档"),
        ]
        for text, detail in checklist:
            st.markdown(
                f"{theme.pill('✓', 'ok')} **{text}** — {detail}",
                unsafe_allow_html=True,
            )
