# -*- coding: utf-8 -*-
"""元智能体自主分析页：Qwen3.5 工具调用 → Node1/Node3 执行 → 汇总。"""

from __future__ import annotations

import json

import streamlit as st

from workbench import meta_agent, services, theme

DEFAULT_QUESTION = (
    "请分析当前资金图谱中的归集和快进快出风险，给出证据和下一步侦查建议。"
)


def _render_trace(result: dict) -> None:
    events = result.get("events") or []
    final = result.get("final") or {}

    theme.section("决策轨迹", "模型自主选择工具，Node1/Node3 执行并回传结果")
    ai_rounds = [event for event in events if event["type"] == "ai_result"]
    tool_results = [event for event in events if event["type"] == "tool_result"]

    cols = st.columns(4)
    cols[0].metric("决策轮次", final.get("rounds", 0))
    cols[1].metric("工具调用", final.get("tool_calls", 0))
    cols[2].metric("总耗时", f"{final.get('elapsed', 0)} s")
    cols[3].metric(
        "AI tokens",
        sum(item.get("tokens", 0) for item in (final.get("ai_evals") or [])),
    )

    for item in ai_rounds:
        title = f"第 {item['round']} 轮 · AI 决策"
        with st.expander(title, expanded=True):
            content = item.get("content") or ""
            if content:
                st.markdown(content)
            else:
                st.caption("模型本轮没有输出文字，直接选择了工具调用。")
            calls = item.get("tool_calls") or []
            if calls:
                st.caption(f"本轮选择 {len(calls)} 个工具：")
                st.dataframe(
                    [
                        {
                            "工具": (call.get("function") or {}).get("name", ""),
                            "参数": json.dumps(
                                (call.get("function") or {}).get("arguments", {}),
                                ensure_ascii=False,
                            ),
                        }
                        for call in calls
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.caption("本轮未调用工具，直接进入最终回答。")

    if tool_results:
        with st.expander("工具执行结果（Node1 / Node3 侧）", expanded=False):
            for index, item in enumerate(tool_results, start=1):
                st.markdown(f"**{index}. `{item['name']}`**")
                st.caption(
                    "参数："
                    + json.dumps(item.get("arguments") or {}, ensure_ascii=False)
                )
                st.code(
                    json.dumps(item.get("result"), ensure_ascii=False, indent=2, default=str),
                    language="json",
                )

    theme.section("元智能体最终研判")
    answer = final.get("answer") or ""
    if answer:
        with st.container(border=True):
            st.markdown(answer)
    else:
        st.warning("模型未返回最终答案，请检查 Node2 推理服务。")

    if final.get("tool_calls", 0) == 0:
        st.warning(
            "本次模型没有调用工具。可以换一个更明确要求“先查图谱/先调工具”的问题，"
            "或在模型支持 tool calling 的情况下重试。"
        )


def render() -> None:
    theme.section("元智能体自主分析", "自主选择工具 · 执行回传 · 研判总结")

    debug = services.debug_inference_status()
    if debug.get("ok"):
        st.markdown(
            theme.pill(f"工具调用模型在线 · {debug['model']}", "ok"),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            theme.pill("推理服务不可用", "warn"),
            unsafe_allow_html=True,
        )

    st.caption("模型自主选择工具，Node1 / Node3 执行并回传结果，最终生成研判。")

    with st.expander("可调用工具", expanded=False):
        st.dataframe(
            [
                {
                    "工具": tool["function"]["name"],
                    "作用": tool["function"]["description"],
                }
                for tool in meta_agent.TOOLS
            ],
            width="stretch",
            hide_index=True,
        )

    question = st.text_area(
        "给元智能体的任务",
        value=DEFAULT_QUESTION,
        height=100,
        key="meta_agent_question",
        persist_state="session",
    )

    action_cols = st.columns([1, 1, 3])
    run_clicked = action_cols[0].button(
        "启动元智能体", type="primary", width="stretch"
    )
    clear_clicked = action_cols[1].button("清空结果", width="stretch")

    if clear_clicked:
        st.session_state.pop("meta_agent_result", None)

    if run_clicked:
        if not question.strip():
            st.warning("请先输入任务")
            return
        events: list[dict] = []
        with st.spinner("Node2 正在自主决策并调用工具……"):
            try:
                for event in meta_agent.iter_meta_agent(question.strip()):
                    events.append(event)
                    if event["type"] == "error":
                        st.error(f"元智能体执行失败：{event.get('message', '')}")
                        return
            except Exception as exc:  # noqa: BLE001
                st.error(f"元智能体执行失败：{type(exc).__name__}: {exc}")
                return
        final = next((item for item in events if item["type"] == "final"), None)
        if not final:
            st.error("元智能体没有返回最终结果")
            return
        st.session_state["meta_agent_result"] = {"events": events, "final": final}

    stored = st.session_state.get("meta_agent_result")
    if not stored:
        st.info("输入任务后启动；模型将自主决定查询顺序。")
        return

    _render_trace(stored)
