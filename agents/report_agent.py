# -*- coding: utf-8 -*-
"""报告智能体：把 graph_agent 的图分析证据交给远程大模型，生成研判结论。

关键约束：账号、金额、时间等关键信息全部来自图查询的结构化结果，
大模型只负责“写叙述性文字”，不允许编造数据。

证据分级（避免"全员可疑"）：
- 强证据：多层归集（fan-in）、环形转账（circular loop）；
- 辅助证据：快进快出（pass-through，单独使用误报多）。
可疑账户 = 强证据账户 ∪ 辅助证据账户，报告中优先列强证据。
"""

from llms.remote_llm import get_remote_llm
from tools.graph_query import (
    find_circular_loops,
    find_fan_in,
    find_fast_in_fast_out,
)


def _build_evidence(fast_io: list[dict], gather: list[dict], cycles: list[dict]) -> str:
    """把三类图规则结果整理成给模型看的事实清单。"""
    lines = []
    if gather:
        lines.append("【强证据 · 多层归集】24 小时内 ≥4 个上游账户汇入、金额高度接近：")
        for item in gather[:10]:
            lines.append(
                f"- {item['account']}：上游 {item['upstream_count']} 个，"
                f"汇入约 {item['inflow']}，金额离散系数 {item['amount_cv']}"
            )
    if cycles:
        lines.append("【强证据 · 环形转账】时间递增、金额逐跳递减的闭环资金链：")
        for item in cycles[:8]:
            chain = " -> ".join(item["accounts"] + [item["accounts"][0]])
            lines.append(
                f"- {chain}（{item['length']} 跳，涉案金额约 {item['amount']}，"
                f"跨度约 {item['span_hours']} 小时）"
            )
    if fast_io:
        lines.append("【辅助证据 · 快进快出】48 小时内转出 ≥95% 收款金额且交易笔数较少：")
        for item in fast_io[:10]:
            lines.append(
                f"- {item['account']}：命中 {item['hit_count']} 次，转出约 {item['outflow']}"
            )
    return "\n".join(lines) if lines else "本次图查询未命中明显可疑模式。"


def report_agent_node(state: dict) -> dict:
    logs = list(state.get("logs", []))

    evidence = state.get("evidence") or {}
    if evidence:
        fast_io = evidence.get("fast_io", [])
        gather = evidence.get("gather", [])
        cycles = evidence.get("cycles", [])
        suspects = list(state.get("suspicious_accounts", []))
        logs.append("[ReportAgent] 复用 GraphAgent 的图分析证据，不再重复查询")
    else:
        # 正常情况下 supervisor 会先路由到 graph_agent，这里只是兜底
        logs.append("[ReportAgent] 未发现图分析证据，直接执行图查询")
        fast_io = find_fast_in_fast_out()
        gather = find_fan_in()
        cycles = find_circular_loops()
        strong = {item["account"] for item in gather}
        strong |= {account for item in cycles for account in item["accounts"]}
        suspects = sorted(strong | {item["account"] for item in fast_io})

    prompt = f"""你是一名反诈资金流研判助手。请严格依据下面图数据库查询出的结构化事实写研判结论。

## 结构化事实
{_build_evidence(fast_io, gather, cycles)}

## 案件信息
- 本批流水共 {len(state.get("parsed_records", []))} 条交易
- 侦查指令：{state.get("instruction", "分析这批流水，找出可疑账户")}

## 输出要求
用中文输出一段 250 字以内的研判结论，包含：
1. 这批资金流呈现的主要可疑特征（区分强证据与辅助证据）；
2. 优先核查的账户及原因（只能引用上面给出的账户，禁止编造账号、金额、时间）；
3. 下一步侦查建议。
"""

    logs.append("[ReportAgent] 正在调用远程 Ollama 生成研判结论……")
    llm = get_remote_llm()
    conclusion = llm.invoke(prompt).content
    logs.append("[ReportAgent] 模型返回研判结论")

    return {
        "suspicious_accounts": suspects,
        "conclusion": conclusion,
        "logs": logs,
    }
