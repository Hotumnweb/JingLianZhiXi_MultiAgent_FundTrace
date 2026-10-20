# -*- coding: utf-8 -*-
"""LangGraph 入口：构建“supervisor + 解析 + 账户关联 + 报告”的图并运行。

用法（必须从项目根目录运行）：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    python main.py                          # 默认跑合成 AML 数据集（4.2 万条）
    python main.py data/sample_flow.csv     # 跑第一版 100 条演示数据
"""

import sys

from langgraph.graph import END, StateGraph

from agents.graph_agent import graph_agent_node
from agents.parsing_agent import parsing_agent_node
from agents.report_agent import report_agent_node
from state import CaseState
from supervisor.supervisor_node import supervisor_node

# 默认数据源：合成 AML 数据集（比赛/答辩演示用）
DEFAULT_FLOW_FILE = "data/synthetic_aml/transactions.csv"


def route(state: CaseState) -> str:
    """条件边：读取 supervisor 写入的 next_step。"""
    return state.get("next_step", "END")


def build_app():
    """构建并编译 LangGraph 状态图。"""
    builder = StateGraph(CaseState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("parsing_agent", parsing_agent_node)
    builder.add_node("graph_agent", graph_agent_node)
    builder.add_node("report_agent", report_agent_node)

    builder.set_entry_point("supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route,
        {
            "parsing_agent": "parsing_agent",
            "graph_agent": "graph_agent",
            "report_agent": "report_agent",
            "END": END,
        },
    )
    builder.add_edge("parsing_agent", "supervisor")
    builder.add_edge("graph_agent", "supervisor")
    builder.add_edge("report_agent", "supervisor")

    return builder.compile()


app = build_app()


def initial_state(
    instruction: str = "分析这批流水，找出可疑账户并生成研判结论",
    flow_file: str = DEFAULT_FLOW_FILE,
) -> dict:
    """构造一次运行的初始状态，字段必须与 CaseState 对齐。"""
    return {
        "instruction": instruction,
        "flow_file": flow_file,
        "parsed_records": [],
        "suspicious_accounts": [],
        "evidence": {},
        "conclusion": "",
        "logs": [],
        "next_step": "",
    }


def main() -> int:
    """命令行方式跑一次完整图流程。"""
    flow_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FLOW_FILE

    try:
        result = app.invoke(initial_state(flow_file=flow_file))
    except Exception as exc:  # noqa: BLE001 - 第一版把失败原因直接打印出来更方便排查
        print(f"\n[运行失败] {type(exc).__name__}: {exc}")
        print(
            "排查顺序：1) Neo4j 是否已启动（localhost:7687）；"
            "2) 流水文件是否存在；3) .env 中 Neo4j 密码是否正确"
        )
        return 1

    print("\n=== 执行日志 ===")
    for line in result.get("logs", []):
        print(line)

    print("\n=== 可疑账户 ===")
    print(result.get("suspicious_accounts") or "（本次未发现可疑账户）")

    print("\n=== 研判结论 ===")
    print(result.get("conclusion") or "（报告节点未启用，未生成大模型结论；图分析结果已在上方）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
