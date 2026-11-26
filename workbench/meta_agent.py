# -*- coding: utf-8 -*-
"""元智能体（工具调用）实验层。

与固定 LangGraph 流水线的区别：
1. 由 Node2 的 Qwen3.5-9B-tools 自主选择“调用哪个工具”；
2. Node1/Node3 执行工具并把结果回传；
3. 模型看到工具结果后继续决策或给出最终研判；
4. 整个决策轨迹会返回给平台展示。

当前工具全部是只读操作，避免误改 Neo4j 数据。
"""

from __future__ import annotations

import json
import re
import time

from llms.remote_llm import chat_with_tools
from tools.graph_query import run_readonly_cypher
from workbench import services

SYSTEM_PROMPT = """你是“警链智析”的元智能体，负责电诈资金图谱分析。
你可以调用工具获取事实，但必须遵守：
1. 先调用工具，再下结论；至少调用一个工具，不要凭想象回答。
2. 不要编造账户、金额、图谱规模；每个数字必须来自工具结果。
3. 你可以多轮调用工具，先提出侦查假设，再找证据验证。
4. 最终用中文回答，按三段组织：发现了什么 / 证据是什么 / 建议下一步。
5. 工具均为只读；不要尝试写图谱或修改数据。
6. 回答要面向业务人员，结论清晰，避免空话套话。
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_graph_stats",
            "description": "查询当前 Neo4j 图谱的账户节点数和转账关系数",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_top_fan_in",
            "description": "查询上游账户数最多的账户（多层归集/水房特征）",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，1~20，默认 10"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_fast_io",
            "description": "查询快进快出账户：48 小时内转出金额达到入账 95% 以上",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，1~20，默认 10"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_account_flow",
            "description": "查看指定账户的资金流出明细（下游账户、金额、时间）",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "账户 ID，例如 ACC_01978"},
                    "limit": {"type": "integer", "description": "返回条数，1~50，默认 20"},
                },
                "required": ["account"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_suspect_evidence",
            "description": "读取最近一次图分析产生的可疑账户证据摘要（强/弱证据、可疑账户数）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rule_metrics",
            "description": "在 AML 数据集上复算三条图规则的精确率、召回率、F1 和团伙召回",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _execute_tool(name: str, arguments: dict) -> dict:
    """在 Node1/Node3 侧执行工具；返回可 JSON 化的结果。"""
    try:
        if name == "get_graph_stats":
            return {"ok": True, "tool": name, "data": services.graph_stats()}

        if name == "query_top_fan_in":
            limit = _clamp(arguments.get("limit"), 1, 20, 10)
            query = f"""
                MATCH (up:Account)-[r:TRANSFER]->(hub:Account)
                WITH hub, count(DISTINCT up) AS upstream, sum(r.amount) AS inflow
                WHERE upstream >= 4
                RETURN hub.id AS account,
                       upstream,
                       round(inflow, 2) AS inflow_usd
                ORDER BY upstream DESC, inflow_usd DESC
                LIMIT {limit}
            """
            result = run_readonly_cypher(query)
            return {"ok": True, "tool": name, "data": result["rows"]}

        if name == "query_fast_io":
            limit = _clamp(arguments.get("limit"), 1, 20, 10)
            query = f"""
                MATCH (a:Account)-[r1:TRANSFER]->(b:Account)-[r2:TRANSFER]->(c:Account)
                WHERE a <> c
                  AND datetime(r2.time) >= datetime(r1.time)
                  AND datetime(r2.time) <= datetime(r1.time) + duration({{hours: 48}})
                  AND r2.amount >= r1.amount * 0.95
                RETURN b.id AS account,
                       count(*) AS hits,
                       round(sum(r2.amount), 2) AS outflow_usd
                ORDER BY hits DESC, outflow_usd DESC
                LIMIT {limit}
            """
            result = run_readonly_cypher(query)
            return {"ok": True, "tool": name, "data": result["rows"]}

        if name == "query_account_flow":
            account = str(arguments.get("account") or "").strip()
            if not re.fullmatch(r"ACC_[0-9]{1,8}", account):
                return {"ok": False, "tool": name, "error": "账户 ID 格式不合法，应为 ACC_数字"}
            limit = _clamp(arguments.get("limit"), 1, 50, 20)
            # 账户 ID 已在上面做白名单校验，避免 Cypher 注入
            query = f"""
                MATCH (a:Account {{id: '{account}'}})-[r:TRANSFER]->(b:Account)
                RETURN b.id AS receiver, r.amount AS amount_usd, r.time AS time
                ORDER BY r.time
                LIMIT {limit}
            """
            result = run_readonly_cypher(query)
            return {"ok": True, "tool": name, "data": result["rows"]}

        if name == "get_suspect_evidence":
            payload = services.latest_evidence()
            summary = services.evidence_summary(payload)
            return {
                "ok": True,
                "tool": name,
                "data": {
                    "case_id": summary["case_id"],
                    "suspects": summary["suspects"],
                    "strong": summary["strong"],
                    "weak": summary["weak"],
                    "gather": summary["gather"],
                    "cycles": summary["cycles"],
                    "fast_io": summary["fast_io"],
                    "top_suspects": summary["suspect_list"][:10],
                },
            }

        if name == "get_rule_metrics":
            return {"ok": True, "tool": name, "data": services.compute_metrics()}

        return {"ok": False, "tool": name, "error": f"未知工具：{name}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def iter_meta_agent(question: str, max_rounds: int = 4):
    """生成元智能体决策事件流。

    yield 事件类型：
      start / ai_start / ai_result / tool_result / final / error
    """
    started = time.perf_counter()
    yield {"type": "start", "question": question}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question.strip()},
    ]
    answer = ""
    tool_call_count = 0
    rounds = 0
    ai_evals: list[dict] = []

    for round_index in range(1, max_rounds + 1):
        rounds = round_index
        yield {"type": "ai_start", "round": round_index}
        try:
            response = chat_with_tools(messages, TOOLS, temperature=0.1, max_tokens=800)
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
            return

        tool_calls = response["tool_calls"]
        ai_evals.append(
            {
                "round": round_index,
                "elapsed": response["elapsed"],
                "tokens": response["eval_count"],
            }
        )
        yield {
            "type": "ai_result",
            "round": round_index,
            "content": response["content"],
            "tool_calls": tool_calls,
            "elapsed": response["elapsed"],
            "tokens": response["eval_count"],
        }

        if not tool_calls:
            answer = response["content"]
            break

        messages.append(
            {
                "role": "assistant",
                "content": response["content"],
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name") or "unknown"
            arguments = _parse_arguments(function.get("arguments"))
            tool_call_count += 1
            result = _execute_tool(name, arguments)
            yield {
                "type": "tool_result",
                "round": round_index,
                "name": name,
                "arguments": arguments,
                "result": result,
            }
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    if not answer:
        # 轮次用尽仍有工具调用，强制做一次无工具的收尾总结
        messages.append(
            {
                "role": "user",
                "content": "请基于以上工具结果，用中文给出最终研判，按“发现/证据/建议”三段，不要编造数据。",
            }
        )
        try:
            final_response = chat_with_tools(messages, [], temperature=0.1, max_tokens=900)
            answer = final_response["content"]
            ai_evals.append(
                {
                    "round": rounds + 1,
                    "elapsed": final_response["elapsed"],
                    "tokens": final_response["eval_count"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "message": f"收尾总结失败：{type(exc).__name__}: {exc}"}
            answer = "元智能体未能在限定轮次内完成回答。"

    elapsed = round(time.perf_counter() - started, 2)
    services.audit_event(
        "meta_agent",
        "run",
        {
            "question": question[:120],
            "rounds": rounds,
            "tool_calls": tool_call_count,
            "elapsed_s": elapsed,
        },
    )
    yield {
        "type": "final",
        "answer": answer,
        "rounds": rounds,
        "tool_calls": tool_call_count,
        "elapsed": elapsed,
        "ai_evals": ai_evals,
    }
