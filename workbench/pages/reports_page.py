# -*- coding: utf-8 -*-
"""报告中心：历史研判报告预览、下载与证据明细。"""

import json

import streamlit as st

from workbench import services, theme


def render() -> None:
    theme.section("研判报告", "报告与证据归档")

    items = services.report_index()
    if not items:
        st.info("暂无报告。请到“元智能体调度”下发一次完整任务。")
        return

    selected_name = st.selectbox(
        "选择报告",
        options=[item["name"] for item in items],
        index=0,
    )
    item = next(entry for entry in items if entry["name"] == selected_name)

    cols = st.columns(5)
    cols[0].metric("案件编号", item["case_id"])
    cols[1].metric("可疑账户", item["suspects"] or "—")
    cols[2].metric("生成耗时", (item["elapsed"] + " s") if item["elapsed"] else "—")
    cols[3].metric("推理速度", (item["tok_s"] + " tok/s") if item["tok_s"] else "—")
    cols[4].metric("文件大小", f"{item['size_kb']} KB")

    if item["fallback"]:
        st.warning("该报告为大模型不可用时的规则模板兜底报告。")

    text = services.read_text(item["path"])
    with st.container(border=True):
        st.markdown(text)

    st.download_button(
        "下载研判报告（Markdown）",
        data=text,
        file_name=item["name"],
        mime="text/markdown",
        key=f"download_report_{item['name']}",
        width="stretch",
    )

    evidence_path = item["path"].with_name(item["name"].replace("_report.md", "_evidence.json"))
    if evidence_path.exists():
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            summary = services.evidence_summary(payload)
        except Exception as exc:  # noqa: BLE001
            st.error(f"读取证据 JSON 失败：{exc}")
            payload = None
            summary = services.evidence_summary(None)

        with st.expander("查看证据明细（结构化）", expanded=False):
            sub_cols = st.columns(4)
            sub_cols[0].metric("归集账户", summary["gather"])
            sub_cols[1].metric("环形链", summary["cycles"])
            sub_cols[2].metric("环形账户", summary["cycle_accounts"])
            sub_cols[3].metric("快进快出", summary["fast_io"])

            evidence = summary.get("evidence") or {}
            if evidence.get("gather"):
                st.markdown("**多层归集账户**")
                st.dataframe(evidence["gather"], width="stretch", hide_index=True)
            if evidence.get("cycles"):
                st.markdown("**环形转账链**")
                rows = [
                    {
                        "链路": " → ".join(cycle["accounts"] + [cycle["accounts"][0]]),
                        "跳数": cycle["length"],
                        "涉案金额(USD)": cycle["amount"],
                        "跨度(小时)": cycle["span_hours"],
                    }
                    for cycle in evidence["cycles"]
                ]
                st.dataframe(rows, width="stretch", hide_index=True)
            if evidence.get("fast_io"):
                st.markdown("**快进快出账户（辅助证据）**")
                st.dataframe(evidence["fast_io"], width="stretch", hide_index=True)

        st.download_button(
            "下载证据 JSON",
            data=evidence_path.read_text(encoding="utf-8"),
            file_name=evidence_path.name,
            mime="application/json",
            key=f"download_evidence_{item['name']}",
            width="stretch",
        )

    theme.section("全部报告", f"共 {len(items)} 份")
    st.dataframe(
        [
            {
                "报告文件": entry["name"],
                "案件编号": entry["case_id"],
                "生成时间": entry["generated_at"],
                "可疑账户": entry["suspects"],
                "耗时(s)": entry["elapsed"],
                "速度(tok/s)": entry["tok_s"],
                "类型": "规则兜底" if entry["fallback"] else "大模型",
            }
            for entry in items
        ],
        width="stretch",
        hide_index=True,
    )
