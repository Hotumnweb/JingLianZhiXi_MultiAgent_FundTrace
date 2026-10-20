# -*- coding: utf-8 -*-
"""平台流式编排器：把 LangGraph 的执行过程转成“阶段事件 + 自定义 token 事件”。

Streamlit 页面通过迭代本生成器，可以实现：
- 智能体调度日志实时滚动；
- 流水线阶段卡片实时点亮；
- 大模型报告逐 token 流式展示。
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from main import app as graph_app
from main import initial_state

STAGES = [
    ("supervisor", "主控调度", "任务拆解 · 路由分发"),
    ("parsing_agent", "流水解析", "pandas → Neo4j 建图"),
    ("graph_agent", "账户关联", "归集 / 环形 / 快进快出"),
    ("report_agent", "研判报告", "Ollama 生成 + 归档"),
]


def _set_report_enabled(enable_report: bool) -> None:
    os.environ["ENABLE_REPORT_AGENT"] = "1" if enable_report else "0"


def iter_pipeline(
    flow_file: str,
    instruction: str,
    enable_report: bool = True,
    accumulate: dict | None = None,
) -> Iterator[tuple[str, str | None, Any]]:
    """迭代执行一次完整链路。

    产出事件：
        ("update", node_name, partial_update)  —— 某个节点执行完成
        ("custom", None, payload)               —— report_agent 推送的 token/阶段事件
        ("final", None, final_state)            —— 全流程结束后的最终状态

    参数 accumulate 若传入 dict，会把每个节点的增量更新合并进去（方便页面拿结果）。
    """
    _set_report_enabled(enable_report)
    state = initial_state(instruction=instruction, flow_file=flow_file)
    final_state = dict(state)
    if accumulate is not None:
        accumulate.clear()
        accumulate.update(state)

    for mode, chunk in graph_app.stream(state, stream_mode=["updates", "custom"]):
        if mode == "updates":
            if not isinstance(chunk, dict):
                continue
            for node, update in chunk.items():
                if isinstance(update, dict):
                    final_state.update(update)
                    if accumulate is not None:
                        accumulate.update(update)
                yield ("update", node, update)
        else:
            yield ("custom", None, chunk)

    if accumulate is not None:
        accumulate.clear()
        accumulate.update(final_state)
    yield ("final", None, final_state)
