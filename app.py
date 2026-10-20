"""Streamlit 前端：一个输入框 + 一个按钮 + 日志/结果展示区。

启动（项目根目录下）：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    streamlit run app.py
"""

import streamlit as st

from llms.remote_llm import report_agent_enabled
from main import app, initial_state

st.set_page_config(
    page_title="警链智析——电诈资金穿透研判（第一版）",
    page_icon="🔎",
    layout="wide",
)

st.title("“警链智析”——面向电诈资金图谱的自主协同智能体")
st.caption("第一版最小闭环：流水解析 → 写入 Neo4j → 图规则查询 → 远程大模型研判 → 结论展示")

with st.sidebar:
    st.header("运行配置")
    flow_file = st.text_input(
        "流水文件路径",
        value="data/synthetic_aml/transactions.csv",
        help="默认使用合成 AML 数据集；可改成 data/sample_flow.csv 跑第一版 100 条演示数据",
    )
    instruction = st.text_area(
        "侦查指令",
        value="分析这批流水，找出可疑账户并生成研判结论",
        height=100,
    )
    if report_agent_enabled():
        st.success("报告节点：已启用（会调用第二台 Ollama）")
    else:
        st.warning("报告节点：已禁用（第二台 GPU 节点未就绪）")
    st.caption("切换方式：修改项目根目录 .env 中的 ENABLE_REPORT_AGENT")

if st.button("开始分析", type="primary"):
    with st.spinner("智能体运行中……"):
        try:
            result = app.invoke(initial_state(instruction=instruction, flow_file=flow_file))
        except Exception as exc:  # noqa: BLE001 - 前端直接把错误展示给使用者
            st.error(f"运行失败：{type(exc).__name__}: {exc}")
            st.info("排查顺序：1) Neo4j 是否已启动；2) 流水文件是否存在；3) .env 配置是否正确")
            st.stop()

    log_col, result_col = st.columns([1, 1])

    with log_col:
        st.subheader("执行日志")
        logs = result.get("logs", [])
        st.code("\n".join(logs) if logs else "（无日志）", language="text")

    with result_col:
        st.subheader("可疑账户")
        accounts = result.get("suspicious_accounts") or []
        evidence = result.get("evidence") or {}
        if evidence:
            st.caption(
                f"图规则：归集 {len(evidence.get('gather', []))} 个 · "
                f"环形链 {len(evidence.get('cycles', []))} 条 · "
                f"快进快出 {len(evidence.get('fast_io', []))} 个"
            )
        if accounts:
            for account in accounts:
                st.markdown(f"- `{account}`")
        else:
            st.caption("（本次未发现可疑账户）")

        st.subheader("研判结论")
        st.write(result.get("conclusion") or "（本次未执行报告节点）")
