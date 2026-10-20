# -*- coding: utf-8 -*-
"""节点与安全页：四节点健康、断网自证、接口清单、审计事件。"""

import streamlit as st

from workbench import services, theme


def render() -> None:
    theme.section("节点与安全", "四节点健康状态 · 网络隔离自证 · 接口集成清单 · 审计事件流")

    top_cols = st.columns([1, 1, 4])
    with top_cols[0]:
        if st.button("刷新节点状态", width="stretch"):
            st.rerun()
    with top_cols[1]:
        st.markdown(theme.pill(services.deployment_mode(), "info"), unsafe_allow_html=True)

    nodes = services.node_status()
    node_cols = st.columns(4)
    for col, node in zip(node_cols, nodes):
        col.markdown(theme.node_card(node), unsafe_allow_html=True)

    targets = services.node_targets()
    theme.section("网络规划", "目标四机部署地址（当前单机联调时以实际服务地址为准）")
    st.dataframe(
        [
            {"节点": "Node1", "角色": "核心调度与编排", "目标地址": "本机 / 127.0.0.1", "当前状态": "在线"},
            {"节点": "Node2", "角色": "GPU 推理与算力", "目标地址": targets["node2"], "当前状态": nodes[1]["status"]},
            {"节点": "Node3", "角色": "图数据与审计", "目标地址": targets["node3"], "当前状态": nodes[2]["status"]},
            {"节点": "Node4", "角色": "演示汇报与终端", "目标地址": targets["node4"], "当前状态": nodes[3]["status"]},
        ],
        width="stretch",
        hide_index=True,
    )

    left, right = st.columns([1, 1])
    with left:
        theme.section("本机运行环境", "第一台电脑 · Coordinator Node")
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

        if st.button("检测外网连通性（断网自证）", type="primary"):
            result = services.external_network_check()
            services.audit_event("network_check", f"target={result['target']}", result)
            if result["online"]:
                st.warning(
                    "当前可以访问外网（开发环境正常）。现场演示前请断开 Wi-Fi / 外网，"
                    "再点此按钮验证“断网自证”。"
                )
            else:
                st.success(
                    f"外网不可达（探测 {result['target']} 超时 / 拒绝）："
                    "符合“数据不出局、算力本地闭环”的演示要求。"
                )

    with right:
        theme.section("接口集成清单", "平台已集成的内部能力与协议")
        st.dataframe(
            [
                {"能力": "智能体编排", "接口/协议": "LangGraph StateGraph", "说明": "supervisor / parsing / graph / report"},
                {"能力": "图数据库", "接口/协议": "Bolt 7687", "说明": "Neo4j 读写与 Cypher 规则"},
                {"能力": "大模型推理", "接口/协议": "HTTP 11434 /api/chat", "说明": "Ollama 原生 API（本地/GPU 节点通用）"},
                {"能力": "流水解析", "接口/协议": "pandas CSV", "说明": "自动识别中文流水 / AML 数据集"},
                {"能力": "报告归档", "接口/协议": "本地文件", "说明": "reports/*_report.md + *_evidence.json"},
                {"能力": "审计事件", "接口/协议": "JSONL", "说明": "reports/audit/audit.jsonl"},
                {"能力": "展示前端", "接口/协议": "Streamlit", "说明": "本平台，离线可用"},
            ],
            width="stretch",
            hide_index=True,
        )

    theme.section("安全审计事件流", "第三台审计节点接入 Wireshark 前的软件侧审计记录")
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
        st.info("暂无审计事件。运行一次“智能体编排”或外网检测后会生成。")

    theme.section("第三台节点（图数据与审计）接入说明", "对应比赛分工中的 Database & Audit")
    st.markdown(
        """
        - **图数据库**：Neo4j Community 部署在第三台，调整 JVM 堆内存（建议 4GB），
          第一台通过 `bolt://第三台IP:7687` 访问，本平台只改 `.env` 的 `NEO4J_URI`；
        - **网络审计**：交换机镜像端口 → Wireshark 监听，过滤 `tcp.port == 11434`，
          展示第一台与第二台之间只有内网 HTTP 调用、无外网流量；
        - **软件侧审计**：本平台已生成 `reports/audit/audit.jsonl`，记录每次分析的开始/结束/失败、
          报告路径、外网检测结果，可作为审计节点的补充证据。
        """
    )

    theme.section("现场检查清单", "答辩前 60 秒自检")
    checklist = [
        ("Neo4j 已启动", "node3 状态为在线"),
        ("Ollama 已启动", "node2 状态为在线且模型可用"),
        ("报告节点开关", "按需开启 ENABLE_REPORT_AGENT"),
        ("断网自证", "点击上方按钮确认外网不可达"),
        ("报告已生成", "报告中心存在最新报告"),
        ("证据已归档", "reports/ 下有对应 evidence.json"),
    ]
    for text, detail in checklist:
        st.markdown(
            f"{theme.pill('✓', 'ok')} **{text}** — {detail}",
            unsafe_allow_html=True,
        )
