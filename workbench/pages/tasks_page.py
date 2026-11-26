# -*- coding: utf-8 -*-
"""任务队列页：排队任务、执行队列、任务详情、调用记录与重跑。"""

from pathlib import Path
import time

import streamlit as st

from workbench import coordinator, executor, services, tasks, theme

_STATUS_TONE = {
    tasks.STATUS_QUEUED: "info",
    tasks.STATUS_RUNNING: "warn",
    tasks.STATUS_COMPLETED: "ok",
    tasks.STATUS_FAILED: "danger",
}


def _status_pill(status: str) -> str:
    return theme.pill(
        tasks.STATUS_LABELS.get(status, status),
        _STATUS_TONE.get(status, "muted"),
    )


def _task_rows(items: list[dict]) -> list[dict]:
    rows = []
    for task in items:
        rows.append(
            {
                "任务号": task.get("id", ""),
                "状态": tasks.STATUS_LABELS.get(task.get("status", ""), task.get("status", "")),
                "创建时间": task.get("created_at", ""),
                "数据源": task.get("flow_file", ""),
                "AI 报告": "是" if task.get("enable_report") else "否",
                "可疑账户": task.get("suspicious", 0),
                "耗时(s)": task.get("duration_s", ""),
                "指令": (task.get("instruction") or "")[:36],
            }
        )
    return rows


def _render_detail(task: dict) -> None:
    st.session_state["last_task_id"] = task["id"]
    st.markdown(
        f"### 任务 `{task['id']}` {_status_pill(task.get('status', ''))}",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="jz-note"><b>任务指令：</b>{theme.esc(task.get("instruction", ""))}<br>'
        f'<b>数据源：</b>{theme.esc(task.get("flow_file", ""))} · '
        f'<b>创建：</b>{theme.esc(task.get("created_at", ""))} · '
        f'<b>完成：</b>{theme.esc(task.get("finished_at") or "—")}</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    cols[0].metric("状态", tasks.STATUS_LABELS.get(task.get("status", ""), task.get("status", "")))
    cols[1].metric("可疑账户", task.get("suspicious", 0))
    cols[2].metric("耗时", f"{task.get('duration_s', '—')} s")
    cols[3].metric("AI 报告", "启用" if task.get("enable_report") else "未启用")

    intermediate = task.get("intermediate") or {}
    if intermediate:
        theme.section("中间结果汇总", "Coordinator 汇总的解析/图谱/证据结果")
        cols = st.columns(4)
        cols[0].metric("解析流水", intermediate.get("parsed_count", "—"))
        cols[1].metric("图账户", intermediate.get("accounts", "—"))
        cols[2].metric("转账边", intermediate.get("transfers", "—"))
        cols[3].metric("强/弱证据", f"{intermediate.get('strong', 0)} / {intermediate.get('weak', 0)}")

    steps = task.get("steps") or []
    if steps:
        theme.section("调度步骤", "Supervisor 与子智能体的执行记录")
        st.dataframe(
            [
                {
                    "目标节点": step.get("target", ""),
                    "动作": step.get("service", ""),
                    "状态": step.get("status", ""),
                    "完成时间": step.get("finished_at", ""),
                    "耗时(s)": step.get("duration_s", ""),
                    "摘要": (step.get("detail") or "")[:80],
                }
                for step in steps
            ],
            width="stretch",
            hide_index=True,
        )

    calls = task.get("node_calls") or []
    if calls:
        theme.section("子智能体调用记录", "Node1 调度 / Node2 AI / Node3 工具")
        st.dataframe(
            [
                {
                    "目标节点": call.get("target", ""),
                    "调用服务": call.get("service", ""),
                    "状态": call.get("status", ""),
                    "耗时(s)": call.get("duration_s", ""),
                    "摘要": (call.get("detail") or "")[:80],
                }
                for call in calls
            ],
            width="stretch",
            hide_index=True,
        )

    if (
        task.get("enable_report")
        and task.get("evidence_path")
        and task.get("status") == tasks.STATUS_COMPLETED
    ):
        with st.expander("追加侦查指令", expanded=False):
            st.caption("在已有证据与报告基础上追加分析；Node2 GPU 通常数十秒返回。")
            follow = st.text_input(
                "追加指令",
                placeholder="例如：重点说明环形转账链的资金闭环特征",
                key=f"queue_follow_input_{task['id']}",
                persist_state="session",
            )
            if st.button("执行追加分析", key=f"queue_follow_btn_{task['id']}"):
                if not follow.strip():
                    st.warning("请先输入追加指令")
                else:
                    with st.spinner("正在调用 Node2 AI 分析追加指令……"):
                        try:
                            answer = coordinator.follow_up(task["id"], follow.strip())
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"追加分析失败：{type(exc).__name__}: {exc}")
                        else:
                            st.success("追加分析完成")
                            st.markdown(answer)
                            task = tasks.load_task(task["id"]) or task

    follow_ups = task.get("follow_ups") or []
    if follow_ups:
        theme.section("追加指令记录", "同一任务上的补充研判")
        for item in follow_ups:
            with st.expander(f"追加：{item.get('instruction', '')[:50]}", expanded=False):
                st.caption(item.get("time", ""))
                st.markdown(item.get("answer", ""))

    report_path = task.get("report_path")
    if report_path and Path(report_path).exists():
        theme.section("研判报告", "可用于复核与归档")
        report_text = services.read_text(Path(report_path))
        with st.container(border=True):
            st.markdown(report_text)
        st.download_button(
            "下载研判报告（Markdown）",
            data=report_text,
            file_name=Path(report_path).name,
            mime="text/markdown",
            key=f"queue_dl_report_{task['id']}",
            width="stretch",
        )

    if task.get("logs"):
        with st.expander("调度日志（节选）", expanded=False):
            st.code("\n".join(task["logs"][-120:]), language="text")

    if st.button("加入队列重跑", key=f"rerun_{task['id']}"):
        new_task = tasks.create_task(
            instruction=task.get("instruction", ""),
            flow_file=task.get("flow_file", ""),
            enable_report=bool(task.get("enable_report")),
            preset=task.get("preset", ""),
        )
        st.session_state["queue_flash"] = f"已创建重跑任务 {new_task['id']}，状态：排队中"
        st.rerun()


def _execute_queue(pending: list[dict]) -> None:
    pending_ids = [task["id"] for task in pending]
    if not executor.start_queue(pending_ids):
        st.error("已有任务/队列在后台执行，请等待完成后再试。")
        return
    progress = st.progress(0.0, text=f"队列共 {len(pending)} 个任务（后台执行）")
    status_box = st.empty()
    while executor.queue_active() or executor.active_ids():
        summary = tasks.queue_summary()
        finished = summary[tasks.STATUS_COMPLETED] + summary[tasks.STATUS_FAILED]
        status_box.markdown(
            f"后台执行中：已完成/失败 {finished} 个，排队 {summary[tasks.STATUS_QUEUED]} 个；"
            "切换页面或刷新不会中断队列。"
        )
        progress.progress(
            min(0.99, finished / max(len(pending), 1)),
            text=f"已完成 {finished}/{len(pending)}",
        )
        time.sleep(0.5)
    success = sum(
        1
        for task_id in pending_ids
        if (tasks.load_task(task_id) or {}).get("status") == tasks.STATUS_COMPLETED
    )
    st.session_state["queue_flash"] = f"队列执行完成：{success}/{len(pending_ids)} 个任务成功"
    st.rerun()


def render() -> None:
    theme.section("任务队列", "排队、执行与调用记录")

    flash = st.session_state.pop("queue_flash", None)
    if flash:
        st.success(flash)

    summary = tasks.queue_summary()
    cols = st.columns(4)
    cols[0].metric("排队中", summary[tasks.STATUS_QUEUED])
    cols[1].metric("执行中", summary[tasks.STATUS_RUNNING])
    cols[2].metric("已完成", summary[tasks.STATUS_COMPLETED])
    cols[3].metric("失败", summary[tasks.STATUS_FAILED])

    pending = tasks.pending_tasks()
    action_cols = st.columns([1, 1, 2])
    with action_cols[0]:
        execute = st.button(
            f"执行队列（{len(pending)}）",
            type="primary",
            width="stretch",
            disabled=not pending,
        )
    with action_cols[1]:
        confirm_clear = st.checkbox("确认清空任务记录", key="confirm_clear_tasks")
    with action_cols[2]:
        clear = st.button("清空任务记录", width="stretch", disabled=not confirm_clear)

    if clear:
        removed = tasks.clear_tasks()
        st.session_state["queue_flash"] = f"已清空 {removed} 条任务记录"
        st.rerun()

    if execute and pending:
        _execute_queue(pending)
        return

    all_tasks = tasks.list_tasks(limit=100)
    if not all_tasks:
        st.markdown(
            '<div class="jz-note">暂无任务。到“元智能体调度”提交任务后，会在这里排队并记录执行状态。</div>',
            unsafe_allow_html=True,
        )
        return

    st.dataframe(_task_rows(all_tasks), width="stretch", hide_index=True)

    selected = st.selectbox(
        "查看任务详情",
        options=[task["id"] for task in all_tasks],
        format_func=lambda task_id: task_id,
    )
    task = next((item for item in all_tasks if item["id"] == selected), None)
    if task:
        _render_detail(task)
