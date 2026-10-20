"""流水解析智能体：把原始流水变成 Neo4j 里的资金网络。

职责边界（第一版刻意保持简单）：
1. 调用 tools/parse_flow.py 做确定性解析（不过大模型）；
2. 调用 tools/graph_query.py 批量写入 Neo4j；
3. 不做任何大模型调用——大模型只出现在 report_agent 里。
"""

from tools.graph_query import graph_summary, write_transactions
from tools.parse_flow import parse_flow_file


def parsing_agent_node(state: dict) -> dict:
    logs = list(state.get("logs", []))
    file_path = state.get("flow_file") or "data/synthetic_aml/transactions.csv"

    logs.append(f"[ParsingAgent] 开始解析流水：{file_path}")
    records = parse_flow_file(file_path)
    logs.append(f"[ParsingAgent] 解析完成，共 {len(records)} 条交易")

    written = write_transactions(records)
    summary = graph_summary()
    logs.append(
        f"[ParsingAgent] 已写入 Neo4j：{written} 条转账边；"
        f"当前图谱共 {summary['accounts']} 个账户、{summary['transfers']} 条边"
    )

    return {"parsed_records": records, "logs": logs}
