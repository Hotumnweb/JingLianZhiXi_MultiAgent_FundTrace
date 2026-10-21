# -*- coding: utf-8 -*-
"""节点与工具页：三节点状态、工具能力、Node2 接入计划、调度日志。"""

import streamlit as st

from workbench import services, theme


def render() -> None:
    theme.section("节点与工具", "Node1 调度 · Node2 算力（占位） · Node3 工具与图数据")

    top_cols = st.columns([1, 1, 4])
    with top_cols[0]:
        if st.button("刷新节点状态", width="stretch"):
            st.rerun()
    with top_cols[1]:
        st.markdown(theme.pill(services.deployment_mode(), "info"), unsafe_allow_html=True)

    nodes = services.node_status()
    node_cols = st.columns(3)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)

    targets = services.node_targets()
    theme.section("三机网络规划", "比赛现场内网地址（当前为开发调试环境）")
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
                "当前状态": "占位（Qwen3-4B + Qwen-Agent 待接入）",
            },
            {
                "节点": "Node3",
                "角色": "工具执行与图数据（Tool & Graph）",
                "目标地址": targets["node3"],
                "当前状态": "开发调试部署于本机",
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
                {"项目": "主机名", "值": info["hostname"]},
                {"项目": "操作系统", "值": info["os"]},
                {"项目": "Python", "值": info["python"]},
                {"项目": "CPU 核数", "值": info["cpu_count"]},
                {"项目": "内存占用", "值": info["memory"]},
                {"项目": "内网地址", "值": info["local_ips"]},
            ],
            width="stretch",
            hide_index=True,
        )

        if st.button("外网隔离检测（断网自证）", type="primary"):
            result = services.external_network_check()
            services.audit_event("network_check", f"target={result['target']}", result)
            if result["online"]:
                st.warning("当前可访问外网（开发环境正常）。现场演示前请断开外网，再点击验证。")
            else:
                st.success(f"外网不可达（探测 {result['target']} 超时 / 拒绝），符合内网演示要求。")

    with right:
        theme.section("接口与工具清单", "Node1 统一调度，Node2/Node3 提供能力")
        st.dataframe(
            [
                {"能力": "任务调度", "提供方": "Node1 · LangGraph Supervisor", "接口/协议": "进程内 StateGraph"},
                {"能力": "大模型推理", "提供方": "Node2 · Qwen3-4B + Qwen-Agent + Ollama", "接口/协议": "HTTP /api/chat（待接入）"},
                {"能力": "图数据库", "提供方": "Node3 · Neo4j", "接口/协议": "Bolt 7687"},
                {"能力": "图规则与子图查询", "提供方": "Node3 · Cypher", "接口/协议": "Bolt / Cypher"},
                {"能力": "流水解析", "提供方": "Node3 · pandas / pdfplumber", "接口/协议": "本地工具"},
                {"能力": "报告归档", "提供方": "Node1 · reports/", "接口/协议": "Markdown + JSON"},
                {"能力": "调度日志", "提供方": "Node1 · 本地 JSONL", "接口/协议": "reports/audit/audit.jsonl"},
            ],
            width="stretch",
            hide_index=True,
        )

    theme.section("Node2 接入计划", "GPU 算力中心（当前占位）")
    st.markdown(
        """
        1. 在第二台电脑部署 Ollama，拉取/训练 **Qwen3-4B** 模型，完成资金分析数据微调；
        2. 使用 **Qwen-Agent + Ollama** 在该节点运行元智能体，接收 Node1 下发的任务；
        3. 配置静态 IP、防火墙 11434 端口，Node1 通过 `http://192.168.50.2:11434` 多轮调用；
        4. 修改 `.env` 的 `OLLAMA_BASE_URL` 与 `OLLAMA_MODEL`，平台 Node2 状态自动切换为在线；
        5. 接入后，任务拆解、工具调用决策、结果汇总由 Node2 元智能体执行，Node1 负责调用与状态管理。
        """
    )

    theme.section("Node3 工具与图数据", "当前部署在本机调试")
    st.markdown(
        """
        - **Neo4j 图数据库**：存储账户节点与转账边，执行快进快出 / 多层归集 / 环形转账规则；
        - **文件解析**：pandas 解析 CSV/Excel 流水，后续可加 pdfplumber / OCR；
        - **可选嵌入模型**：CPU 有余量时运行轻量嵌入模型，为 RAG 检索提供支持；
        - 接入方式：修改 `.env` 的 `NEO4J_URI` 为第三台地址，平台无需改代码。
        """
    )

    theme.section("调度日志", "Node1 记录任务下发、完成、失败与外网检测事件")
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

    theme.section("现场检查清单", "答辩前 60 秒自检")
    checklist = [
        ("Node1 调度中心", "平台正常打开、任务可下发"),
        ("Node2 算力节点", "占位阶段可先用本机 Ollama 调试；正式演示前接入 Qwen3-4B"),
        ("Node3 工具与图数据", "Neo4j 已启动，图谱可查询"),
        ("外网隔离", "点击“外网隔离检测”确认外网不可达"),
        ("研判报告", "任务完成后报告与证据已归档"),
    ]
    for text, detail in checklist:
        st.markdown(
            f"{theme.pill('✓', 'ok')} **{text}** — {detail}",
            unsafe_allow_html=True,
        )
