"""主控调度节点（第一版）。

第一版刻意使用确定性的 if-else 路由，不做“让模型决定下一步”，
目的是先把链路跑通、把变量降到最少；第二版再替换成模型驱动的路由。

路由规则：
1. 还没有解析流水 -> parsing_agent
2. 已解析、还没有图分析结果 -> graph_agent
3. 已有图分析结果、还没有结论：
   - ENABLE_REPORT_AGENT=1 -> report_agent
   - ENABLE_REPORT_AGENT=0 -> END（第二台 GPU 节点未就绪，跳过报告节点）
4. 已有结论 -> END
"""

from llms.remote_llm import report_agent_enabled


def supervisor_node(state: dict) -> dict:
    logs = list(state.get("logs", []))

    if not state.get("parsed_records"):
        logs.append("[Supervisor] 尚未解析流水 -> 路由到 parsing_agent")
        return {"logs": logs, "next_step": "parsing_agent"}

    if not state.get("evidence"):
        logs.append("[Supervisor] 已解析，尚未做图分析 -> 路由到 graph_agent")
        return {"logs": logs, "next_step": "graph_agent"}

    if not state.get("conclusion"):
        if report_agent_enabled():
            logs.append("[Supervisor] 图分析完成，报告节点已启用 -> 路由到 report_agent")
            return {"logs": logs, "next_step": "report_agent"}
        logs.append(
            "[Supervisor] 图分析完成；ENABLE_REPORT_AGENT=0（第二台 GPU 节点未就绪），"
            "跳过报告节点 -> END"
        )
        return {"logs": logs, "next_step": "END"}

    logs.append("[Supervisor] 全部节点完成 -> END")
    return {"logs": logs, "next_step": "END"}
