# -*- coding: utf-8 -*-
"""Coordinator Node 的调度执行层。

第一台电脑只做调度，不运行大模型、不运行图数据库：
- 任务状态：排队/执行/完成/失败，写入 runtime/tasks；
- 调用记录：记录每次是 Node1 调度、Node3 工具调用还是 Node2 AI 调用；
- 中间结果：解析条数、图谱规模、三类证据数量；
- 当前开发调试阶段：Node2 由本机 Ollama 临时替代、Node3 部署在本机；
  接入真实节点后只改 .env，本模块逻辑不变。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from workbench import tasks
from workbench.runner import iter_pipeline

# 节点/动作映射
_STEP_INFO = {
    "supervisor": ("Node1", "Supervisor 调度决策"),
    "parsing_agent": ("Node3", "流水解析与建图"),
    "graph_agent": ("Node3", "图规则查询"),
    "report_agent": ("Node2", "AI 研判报告"),
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def inference_node_label() -> str:
    """Node2 的显示名称（占位/调试/远程）。"""
    base_url = os.getenv("OLLAMA_BASE_URL", "")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return "Node2（占位：本机 Ollama 调试）"
    return "Node2（GPU 算力节点）"


def tool_node_label() -> str:
    """Node3 的显示名称。"""
    uri = os.getenv("NEO4J_URI", "")
    if "127.0.0.1" in uri or "localhost" in uri:
        return "Node3（本机调试）"
    return "Node3（工具与图数据节点）"


def _step_label(node: str) -> tuple[str, str]:
    return _STEP_INFO.get(node, ("Node1", node))


def start_task(task: dict) -> dict:
    """把任务置为执行中，重置执行过程字段。"""
    return tasks.update_task(
        task["id"],
        status=tasks.STATUS_RUNNING,
        progress=0.05,
        started_at=_now(),
        finished_at="",
        duration_s=None,
        steps=[],
        node_calls=[],
        logs=[],
        intermediate={},
        suspicious=0,
        report_path="",
        evidence_path="",
        llm_status="",
        case_id="",
        conclusion="",
        error="",
        follow_ups=[],
    )


def iter_task(task: dict):
    """执行一个任务，边执行边维护任务记录，供页面流式展示。

    yield 事件：
        ("update", node, payload)  节点完成
        ("custom", None, payload)  report_agent 的 token/阶段事件
        ("final", None, final_state)
        ("task_done", None, final_state)
        ("task_failed", None, task)
    """
    task = start_task(task)
    task_id = task["id"]
    final_state: dict = {}
    step_started = time.perf_counter()
    run_started = time.perf_counter()

    try:
        for kind, node, payload in iter_pipeline(
            flow_file=task["flow_file"],
            instruction=task["instruction"],
            enable_report=task["enable_report"],
            accumulate=final_state,
        ):
            if kind == "update":
                duration = round(time.perf_counter() - step_started, 2)
                step_started = time.perf_counter()
                target, service = _step_label(node)
                detail = ""
                if isinstance(payload, dict):
                    logs = payload.get("logs") or []
                    if logs:
                        detail = str(logs[-1])[:220]
                    task["logs"] = [str(line) for line in logs][-200:]
                    _collect_intermediate(task, node, payload)

                task["steps"].append(
                    {
                        "node": node,
                        "target": target,
                        "service": service,
                        "status": "done",
                        "finished_at": _now(),
                        "duration_s": duration,
                        "detail": detail,
                    }
                )
                if node != "supervisor":
                    task["node_calls"].append(
                        {
                            "target": target,
                            "service": service,
                            "duration_s": duration,
                            "finished_at": _now(),
                            "status": "done",
                            "detail": detail[:160],
                        }
                    )
                task["progress"] = min(0.95, 0.08 + len(task["steps"]) * 0.22)
                tasks.save_task(task)
                yield kind, node, payload

            elif kind == "custom":
                yield kind, node, payload

            elif kind == "final":
                final_state = payload
                _finalize_task(task, final_state, time.perf_counter() - run_started)
                yield "final", None, final_state
                yield "task_done", None, final_state
                return

    except Exception as exc:  # noqa: BLE001 - 任务失败也要落盘，供页面展示
        duration = round(time.perf_counter() - run_started, 2)
        task["status"] = tasks.STATUS_FAILED
        task["error"] = f"{type(exc).__name__}: {exc}"
        task["finished_at"] = _now()
        task["duration_s"] = duration
        task["progress"] = 1.0
        tasks.save_task(task)
        yield "task_failed", None, task


def _collect_intermediate(task: dict, node: str, payload: dict) -> None:
    """把节点返回的中间结果压缩后写入任务记录。"""
    intermediate = task.setdefault("intermediate", {})
    if node == "parsing_agent":
        records = payload.get("parsed_records")
        if isinstance(records, list):
            intermediate["parsed_count"] = len(records)

    if node == "graph_agent":
        evidence = payload.get("evidence") or {}
        summary = evidence.get("summary") or {}
        intermediate.update(
            {
                "accounts": summary.get("accounts", 0),
                "transfers": summary.get("transfers", 0),
                "gather": len(evidence.get("gather") or []),
                "cycles": len(evidence.get("cycles") or []),
                "fast_io": len(evidence.get("fast_io") or []),
                "strong": evidence.get("strong_count", 0),
                "weak": evidence.get("weak_count", 0),
            }
        )

    if node == "report_agent":
        intermediate["report"] = "已生成"
        task["report_path"] = payload.get("report_path", "")
        task["evidence_path"] = payload.get("evidence_path", "")
        task["llm_status"] = payload.get("llm_status", "")


def _finalize_task(task: dict, final_state: dict, duration: float) -> None:
    evidence = final_state.get("evidence") or {}
    summary = evidence.get("summary") or {}
    suspects = final_state.get("suspicious_accounts") or []

    intermediate = task.setdefault("intermediate", {})
    intermediate.update(
        {
            "parsed_count": len(final_state.get("parsed_records") or []),
            "accounts": summary.get("accounts", 0),
            "transfers": summary.get("transfers", 0),
            "gather": len(evidence.get("gather") or []),
            "cycles": len(evidence.get("cycles") or []),
            "fast_io": len(evidence.get("fast_io") or []),
            "strong": evidence.get("strong_count", 0),
            "weak": evidence.get("weak_count", 0),
            "suspects": len(suspects),
        }
    )
    task["suspicious"] = len(suspects)
    task["report_path"] = final_state.get("report_path", "")
    task["evidence_path"] = final_state.get("evidence_path", "")
    task["llm_status"] = final_state.get("llm_status", "")
    task["conclusion"] = (final_state.get("conclusion") or "")[:8000]
    task["status"] = tasks.STATUS_COMPLETED
    task["finished_at"] = _now()
    task["duration_s"] = round(duration, 1)
    task["progress"] = 1.0
    tasks.save_task(task)


def follow_up(task_id: str, instruction: str) -> str:
    """对已有任务执行“追加指令”：把当前证据与报告交给 AI 做补充研判。"""
    from llms.remote_llm import generate

    task = tasks.load_task(task_id)
    if task is None:
        raise ValueError(f"任务不存在：{task_id}")
    if not task.get("evidence_path") or not os.path.exists(task["evidence_path"]):
        raise ValueError("该任务没有证据文件，请先执行一次带 AI 报告的任务后再追加指令")

    payload = json.loads(Path(task["evidence_path"]).read_text(encoding="utf-8"))
    evidence = payload.get("evidence") or {}
    gather = evidence.get("gather") or []
    cycles = evidence.get("cycles") or []
    fast_io = evidence.get("fast_io") or []

    evidence_text = []
    if gather:
        evidence_text.append("【归集账户】")
        for item in gather[:5]:
            evidence_text.append(
                f"- {item['account']}：上游 {item['upstream_count']} 个，汇入约 {item['inflow']} USD"
            )
    if cycles:
        evidence_text.append("【环形转账链】")
        for item in cycles[:3]:
            chain = " -> ".join(item["accounts"] + [item["accounts"][0]])
            evidence_text.append(f"- {chain}（{item['length']} 跳，金额约 {item['amount']} USD）")
    if fast_io:
        evidence_text.append("【快进快出账户】")
        for item in fast_io[:5]:
            evidence_text.append(f"- {item['account']}：转出约 {item['outflow']} USD")

    report = task.get("conclusion") or ""
    prompt = f"""你是一名公安反诈资金研判专家。以下是一次已完成任务的研判报告与结构化证据。

## 已有研判报告（节选）
{report[:3000]}

## 结构化证据
{chr(10).join(evidence_text)}

## 追加侦查指令
{instruction}

请基于以上事实，用 300 字以内回答追加指令；只能引用给出的账户和金额，不得编造。
"""
    result = generate(prompt, max_tokens=500)
    answer = result.get("content", "").strip()
    if not answer:
        raise ValueError("AI 返回内容为空")
    tasks.append_follow_up(task_id, instruction, answer)
    return answer
