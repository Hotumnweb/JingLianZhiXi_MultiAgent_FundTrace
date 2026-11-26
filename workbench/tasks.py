# -*- coding: utf-8 -*-
"""任务队列与任务记录（Coordinator Node 的集群状态）。

职责：
1. 任务入队、排队、执行状态跟踪；
2. 每个任务的指令、数据源、步骤、子智能体调用日志、中间结果、报告路径落盘；
3. 为调度中枢、任务队列页、总览页提供统一数据源。

存储位置：runtime/tasks/<task_id>.json（本地 JSON，git 忽略）。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = PROJECT_ROOT / "runtime" / "tasks"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

STATUS_LABELS = {
    STATUS_QUEUED: "排队中",
    STATUS_RUNNING: "执行中",
    STATUS_COMPLETED: "已完成",
    STATUS_FAILED: "失败",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dir() -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)


def _task_path(task_id: str) -> Path:
    return TASK_DIR / f"{task_id}.json"


def _new_task_id() -> str:
    return "T" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]


def create_task(
    instruction: str,
    flow_file: str,
    enable_report: bool,
    preset: str = "",
) -> dict:
    """创建一个排队中的任务。"""
    ensure_dir()
    now = _now()
    task = {
        "id": _new_task_id(),
        "created_at": now,
        "updated_at": now,
        "instruction": instruction,
        "flow_file": flow_file,
        "preset": preset,
        "enable_report": bool(enable_report),
        "status": STATUS_QUEUED,
        "progress": 0.0,
        "started_at": "",
        "finished_at": "",
        "duration_s": None,
        "steps": [],
        "node_calls": [],
        "intermediate": {},
        "logs": [],
        "suspicious": 0,
        "report_path": "",
        "evidence_path": "",
        "llm_status": "",
        "case_id": "",
        "conclusion": "",
        "error": "",
        "follow_ups": [],
    }
    save_task(task)
    return task


def save_task(task: dict) -> None:
    ensure_dir()
    task["updated_at"] = _now()
    path = _task_path(task["id"])
    # 先写临时文件再原子替换，避免页面读到写了一半的 JSON
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def update_task(task_id: str, **fields) -> dict:
    task = load_task(task_id)
    if task is None:
        raise FileNotFoundError(f"任务不存在：{task_id}")
    task.update(fields)
    save_task(task)
    return task


def load_task(task_id: str) -> dict | None:
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _stream_path(task_id: str) -> Path:
    return TASK_DIR / f"{task_id}.stream"


def append_stream(task_id: str, text: str) -> None:
    """追加 AI 流式输出（独立文件，避免和任务 JSON 的频繁写入互相覆盖）。"""
    if not text:
        return
    ensure_dir()
    with _stream_path(task_id).open("a", encoding="utf-8") as handle:
        handle.write(text)


def read_stream(task_id: str, max_chars: int = 20000) -> str:
    path = _stream_path(task_id)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""
    return text[-max_chars:]


def clear_stream(task_id: str) -> None:
    path = _stream_path(task_id)
    if path.exists():
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            pass


def list_tasks(limit: int = 200) -> list[dict]:
    ensure_dir()
    tasks: list[dict] = []
    for path in TASK_DIR.glob("*.json"):
        try:
            tasks.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    tasks.sort(key=lambda task: task.get("created_at", ""), reverse=True)
    return tasks[:limit]


def pending_tasks() -> list[dict]:
    """按创建时间从早到晚返回排队中的任务。"""
    queued = [task for task in list_tasks(limit=500) if task.get("status") == STATUS_QUEUED]
    queued.sort(key=lambda task: task.get("created_at", ""))
    return queued


def queue_summary() -> dict:
    all_tasks = list_tasks(limit=500)
    counts = {
        STATUS_QUEUED: 0,
        STATUS_RUNNING: 0,
        STATUS_COMPLETED: 0,
        STATUS_FAILED: 0,
    }
    for task in all_tasks:
        status = task.get("status", STATUS_FAILED)
        counts[status] = counts.get(status, 0) + 1
    return {
        **counts,
        "total": len(all_tasks),
        "latest": all_tasks[0] if all_tasks else None,
    }


def clear_tasks() -> int:
    """清空全部任务记录（演示前恢复干净环境用）。"""
    ensure_dir()
    removed = 0
    for path in TASK_DIR.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def append_follow_up(task_id: str, instruction: str, answer: str) -> dict:
    task = load_task(task_id)
    if task is None:
        raise FileNotFoundError(f"任务不存在：{task_id}")
    task.setdefault("follow_ups", []).append(
        {
            "time": _now(),
            "instruction": instruction,
            "answer": answer,
        }
    )
    save_task(task)
    return task
