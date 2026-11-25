# -*- coding: utf-8 -*-
"""LangGraph 入口：构建“supervisor + 解析 + 账户关联 + 报告”的图并运行。

用法（必须从项目根目录运行）：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace

    python main.py                          # 默认 AML 数据集 + 本地 Ollama 报告
    python main.py --no-report              # 只跑图分析，不调用大模型（断网/无模型时）
    python main.py data/sample_flow.csv     # 换数据源（第一版 100 条演示数据）
    python main.py --check-llm              # 只检查 Ollama 连通性和模型是否存在
"""

import argparse
import os
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
        "report_path": "",
        "evidence_path": "",
        "llm_status": "",
        "logs": [],
        "next_step": "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="警链智析-元智能体驱动的涉诈资金穿透研判系统（CLI）"
    )
    parser.add_argument(
        "flow_file",
        nargs="?",
        default=DEFAULT_FLOW_FILE,
        help=f"流水 CSV 路径，默认 {DEFAULT_FLOW_FILE}",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="只跑解析 + 建图 + 图分析，不调用大模型（断网/无模型时使用）",
    )
    parser.add_argument(
        "--check-llm",
        action="store_true",
        help="只检查 Ollama 连通性与模型是否存在，然后退出",
    )
    return parser.parse_args()


def check_llm() -> int:
    """检查 Ollama 服务与模型，返回进程退出码。"""
    from llms.remote_llm import check_connection, load_llm_config

    config = load_llm_config()
    print(f"服务地址：{config.base_url}")
    print(f"模型名称：{config.model}")
    print(f"上下文长度：{config.num_ctx}；超时：{config.timeout} 秒")

    info = check_connection()
    if not info["ok"]:
        print(f"[FAIL] Ollama 不可达：{info['error']}")
        return 1

    print(f"[OK] Ollama 可访问，本地模型：{info['models']}")
    if not info["available"]:
        print(f"[WARN] 没有找到模型 {config.model}，请检查 .env 或先 ollama pull")
        return 2
    print("[OK] 目标模型已就绪")
    return 0


def main() -> int:
    """命令行方式跑一次完整图流程。"""
    args = parse_args()

    if args.check_llm:
        return check_llm()

    if args.no_report:
        os.environ["ENABLE_REPORT_AGENT"] = "0"
        print("[提示] --no-report 已生效：本次不调用大模型，只输出图分析结果")

    try:
        result = app.invoke(initial_state(flow_file=args.flow_file))
    except Exception as exc:  # noqa: BLE001 - 第一版把失败原因直接打印出来更方便排查
        print(f"\n[运行失败] {type(exc).__name__}: {exc}")
        print(
            "排查顺序：1) Neo4j 是否已启动、.env 的 NEO4J_HOST/NEO4J_PORT 是否正确"
            "（可运行 python scripts/check_neo4j.py）；"
            "2) 流水文件是否存在；3) .env 中 Neo4j 密码是否正确"
        )
        return 1

    print("\n=== 执行日志 ===")
    for line in result.get("logs", []):
        print(line)

    suspects = result.get("suspicious_accounts") or []
    print(f"\n=== 可疑账户（共 {len(suspects)} 个）===")
    print(suspects if suspects else "（本次未发现可疑账户）")

    print("\n=== 研判报告 ===")
    conclusion = result.get("conclusion") or ""
    if conclusion:
        print(conclusion)
    else:
        print("（报告节点未启用，未生成报告；图分析结果已在上方）")

    if result.get("report_path"):
        print(f"\n报告文件：{result['report_path']}")
        print(f"证据文件：{result.get('evidence_path', '-')}")
        print(f"报告状态：{result.get('llm_status', '-')}（ok = 大模型生成，fallback = 规则模板兜底）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
