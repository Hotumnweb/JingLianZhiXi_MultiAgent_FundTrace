# -*- coding: utf-8 -*-
"""后台任务执行器：任务放在独立线程执行，页面刷新/切换页面不会中断。

背景：
- 旧实现把 `coordinator.iter_task` 直接写在 Streamlit 脚本线程里，
  用户切换页面、刷新浏览器或点击任何触发 rerun 的控件时，脚本线程被终止，
  任务停在“执行中”但实际已死（本次 4 万条任务卡 6 分钟即此原因）。
- 现在任务交给 daemon 线程执行，页面只轮询任务 JSON/流式文本，
  页面关掉或跳转都不影响任务继续跑完。

对外接口：
    start(task_id)           启动单任务（返回是否成功启动）
    start_queue(task_ids)    后台顺序执行队列（返回是否成功启动）
    is_running(task_id)      单任务是否在跑
    active_ids()             当前正在跑的任务 id
    queue_active()           队列线程是否在跑
"""

from __future__ import annotations

import threading
import time

from workbench import coordinator, tasks

_active: dict[str, bool] = {}
_queue_active = False
_lock = threading.Lock()


def is_running(task_id: str) -> bool:
    with _lock:
        return task_id in _active


def active_ids() -> list[str]:
    with _lock:
        return list(_active)


def queue_active() -> bool:
    with _lock:
        return _queue_active


def _mark_active(task_id: str) -> None:
    with _lock:
        _active[task_id] = True


def _mark_done(task_id: str) -> None:
    with _lock:
        _active.pop(task_id, None)


def _run_task(task_id: str) -> None:
    """同步执行一个任务（供线程/队列线程调用），执行过程持续落盘。"""
    task = tasks.load_task(task_id)
    if task is None:
        return
    try:
        tasks.clear_stream(task_id)
        for kind, _node, payload in coordinator.iter_task(task):
            if kind == "custom" and isinstance(payload, dict):
                if payload.get("type") == "token":
                    text = str(payload.get("text") or "")
                    if text:
                        tasks.append_stream(task_id, text)
    except Exception as exc:  # noqa: BLE001 - 线程内异常也要落盘
        current = tasks.load_task(task_id) or {}
        if current.get("status") == tasks.STATUS_RUNNING:
            try:
                tasks.update_task(
                    task_id,
                    status=tasks.STATUS_FAILED,
                    error=f"后台执行异常：{type(exc).__name__}: {exc}",
                    finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    progress=1.0,
                )
            except Exception:  # noqa: BLE001
                pass
    finally:
        _mark_done(task_id)


def start(task_id: str) -> bool:
    """启动单任务；已在执行中返回 False。"""
    with _lock:
        if task_id in _active or _queue_active:
            return False
        _active[task_id] = True
    threading.Thread(
        target=_run_task,
        args=(task_id,),
        daemon=True,
        name=f"jz-task-{task_id}",
    ).start()
    return True


def _queue_worker(task_ids: list[str]) -> None:
    global _queue_active
    try:
        for task_id in task_ids:
            if tasks.load_task(task_id) is None:
                continue
            _mark_active(task_id)
            _run_task(task_id)
    finally:
        with _lock:
            _queue_active = False


def start_queue(task_ids: list[str]) -> bool:
    """后台顺序执行队列；已有任务/队列在跑时返回 False。"""
    global _queue_active
    with _lock:
        if _active or _queue_active:
            return False
        _queue_active = True
    threading.Thread(
        target=_queue_worker,
        args=(list(task_ids),),
        daemon=True,
        name="jz-task-queue",
    ).start()
    return True
