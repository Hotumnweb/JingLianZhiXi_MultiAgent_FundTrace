"""账户关联智能体：执行三类图规则，产出可疑账户与证据。

职责边界：
1. 只做“确定性图分析”（Cypher 查询 + Python 环检测），不调用大模型；
2. 输出结构化证据，供报告智能体写研判结论；
3. 即使第二台 GPU 节点未就绪、报告节点关闭，这一步也能独立跑出结果。

三类规则：
- 多层归集（强证据）
- 环形转账（强证据）
- 快进快出（辅助证据）
"""

from tools.graph_query import (
    find_circular_loops,
    find_fan_in,
    find_fast_in_fast_out,
    graph_summary,
)


def graph_agent_node(state: dict) -> dict:
    logs = list(state.get("logs", []))

    logs.append("[GraphAgent] 开始图规则分析：多层归集 / 环形转账 / 快进快出")
    fast_io = find_fast_in_fast_out()
    gather = find_fan_in()
    cycles = find_circular_loops()

    cycle_accounts = {account for item in cycles for account in item["accounts"]}
    strong = {item["account"] for item in gather} | cycle_accounts
    weak = {item["account"] for item in fast_io}
    suspects = sorted(strong | weak)

    summary = graph_summary()
    evidence = {
        "fast_io": fast_io,
        "gather": gather,
        "cycles": cycles,
        "strong_count": len(strong),
        "weak_count": len(weak),
        "summary": summary,
    }

    logs.append(
        f"[GraphAgent] 图分析完成：归集账户 {len(gather)} 个，"
        f"环形转账链 {len(cycles)} 条（覆盖 {len(cycle_accounts)} 个账户），"
        f"快进快出账户 {len(fast_io)} 个；"
        f"强证据账户 {len(strong)} 个，辅助证据账户 {len(weak)} 个，"
        f"去重后可疑账户 {len(suspects)} 个"
    )

    return {
        "suspicious_accounts": suspects,
        "evidence": evidence,
        "logs": logs,
    }
