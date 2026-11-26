# -*- coding: utf-8 -*-
"""数据接入与清洗页：真实世界里“混乱 + 很大”的一手流水怎么进平台。

流程：选择数据源（服务器文件/上传）→ 自动画像（编码/分隔符/表头/列名）
→ 字段映射（可手工修正）→ 流式清洗（大文件分块，不整表进内存）
→ 输出统一流水 + 清洗报告 → 在调度页建图。

页面还内置 pandas 分析台：对清洗后的数据做分布/趋势/Top 账户分析与受限表达式查询。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from workbench import services, theme

ENCODING_OPTIONS = ["自动", "utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin1"]
DELIMITER_OPTIONS = {
    "自动": None,
    "逗号 ,": ",",
    "分号 ;": ";",
    "Tab 制表符": "\t",
    "竖线 |": "|",
}
HEADER_OPTIONS = ["自动", "有表头", "无表头"]
TIME_MODES = {
    "自动识别": "auto",
    "字符串日期": "datetime",
    "Unix 秒": "epoch_s",
    "Unix 毫秒": "epoch_ms",
    "步长（小时）": "step_hours",
}
ROW_LIMIT_OPTIONS = {
    "1 万行（最快）": 10000,
    "5 万行": 50000,
    "10 万行（推荐）": 100000,
    "50 万行": 500000,
    "100 万行": 1000000,
    "全部（慢，谨慎）": 0,
}
SAMPLE_MODE_OPTIONS = {
    "前 N 行（最快）": "head",
    "均匀抽样（跨全时段，推荐大数据）": "uniform",
}
ANALYSIS_LIMITS = {"5 千行": 5000, "2 万行": 20000, "5 万行": 50000}

PANDAS_EXAMPLES = [
    'df.groupby("摘要")["金额"].sum().sort_values(ascending=False).head(10)',
    'df[df["金额"] > 100000][["交易时间", "金额", "付款账号", "收款账号"]].head(20)',
    'df["付款账号"].value_counts().head(10)',
    'df["金额"].describe()',
]


@st.cache_data(ttl=60, show_spinner=False)
def _catalog() -> list[dict]:
    return services.data_file_catalog()


@st.cache_data(ttl=300, show_spinner=False)
def _profile(path: str, mtime: float, encoding: str | None, delimiter: str | None,
             has_header: bool | None) -> dict:
    return services.profile_data_file(path, encoding=encoding, delimiter=delimiter, has_header=has_header)


@st.cache_data(ttl=60, show_spinner=False)
def _cleaned() -> list[dict]:
    return services.cleaned_datasets()


def _short_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _goto_orchestration(flow_path: str) -> None:
    st.session_state["pending_flow_source"] = flow_path
    st.session_state["nav_page"] = "元智能体调度"
    st.rerun()


def _index_or_zero(values: list[str], target: list[str]) -> int:
    for candidate in target or []:
        if candidate in values:
            return values.index(candidate)
    return 0


def _render_upload() -> None:
    with st.expander("上传本地文件（小文件）", expanded=False):
        st.caption("上传文件会保存到 `data/imports/`，可继续做画像与清洗。")
        with st.form("ingest_upload_form", clear_on_submit=True):
            uploaded = st.file_uploader(
                "选择 CSV / TSV / TXT / Excel",
                type=["csv", "tsv", "txt", "xlsx", "xls"],
            )
            submitted = st.form_submit_button("上传并加入数据源")
        if submitted:
            if uploaded is None:
                st.warning("请先选择文件")
            else:
                try:
                    info = services.save_uploaded_data_file(uploaded.name, uploaded.getvalue())
                except Exception as exc:  # noqa: BLE001
                    st.error(f"上传失败：{type(exc).__name__}: {exc}")
                else:
                    _catalog.clear()
                    st.session_state["ingest_source_path"] = info["path"]
                    st.success(f"已保存：{info['path']}（{info['size_mb']} MB）")
                    st.rerun()


def _mapping_inputs(profile: dict, path_key: str) -> dict:
    """字段映射控件，返回映射 dict。"""
    columns = [str(column) for column in profile.get("columns") or []]
    suggestion = profile.get("suggested_mapping") or {}
    if not columns:
        st.error("文件没有识别到任何列，请在“识别参数”里调整编码/分隔符/表头。")
        return {}

    mapping_key = f"{path_key}_{_short_key('|'.join(columns))}"
    left, right = st.columns(2)
    with left:
        time_col = st.selectbox(
            "时间列",
            columns,
            index=_index_or_zero(columns, suggestion.get("time_columns") or []),
            key=f"ing_time_{mapping_key}",
        )
        time_mode_label = st.selectbox(
            "时间解析方式",
            list(TIME_MODES.keys()),
            index=(
                list(TIME_MODES.values()).index(suggestion.get("time_mode"))
                if suggestion.get("time_mode") in TIME_MODES.values()
                else 0
            ),
            key=f"ing_tmode_{mapping_key}",
            help="字符串日期/Unix 秒/Unix 毫秒/步长（如 PaySim 的 step）",
        )
        amount_col = st.selectbox(
            "金额列",
            columns,
            index=_index_or_zero(columns, suggestion.get("amount_columns") or []),
            key=f"ing_amount_{mapping_key}",
        )
        summary_options = ["—（默认：转账）"] + columns
        summary_default = (suggestion.get("summary_columns") or [""])[0]
        summary_index = (
            summary_options.index(summary_default)
            if summary_default in summary_options
            else 0
        )
        summary_label = st.selectbox(
            "摘要列（可选）",
            summary_options,
            index=summary_index,
            key=f"ing_summary_{mapping_key}",
        )
        time_base = st.text_input(
            "步长基准时间（步长模式使用）",
            value="2017-01-01 00:00:00",
            key=f"ing_tbase_{mapping_key}",
        )
    with right:
        from_defaults = [c for c in (suggestion.get("from_columns") or []) if c in columns]
        to_defaults = [c for c in (suggestion.get("to_columns") or []) if c in columns]
        from_cols = st.multiselect(
            "付款账号列（可多选，如 银行+账号）",
            columns,
            default=from_defaults,
            max_selections=2,
            key=f"ing_from_{mapping_key}",
        )
        from_separator = st.text_input(
            "付款账号拼接符",
            value=(suggestion.get("from_separator") or ":" if len(from_cols) > 1 else ""),
            key=f"ing_fsep_{mapping_key}",
        )
        to_cols = st.multiselect(
            "收款账号列（可多选）",
            columns,
            default=to_defaults,
            max_selections=2,
            key=f"ing_to_{mapping_key}",
        )
        to_separator = st.text_input(
            "收款账号拼接符",
            value=(suggestion.get("to_separator") or ":" if len(to_cols) > 1 else ""),
            key=f"ing_tsep_{mapping_key}",
        )

    mapping = {
        "time_columns": [time_col],
        "time_mode": TIME_MODES[time_mode_label],
        "time_base": time_base,
        "amount_columns": [amount_col],
        "from_columns": from_cols,
        "from_separator": from_separator,
        "to_columns": to_cols,
        "to_separator": to_separator,
        "summary_columns": [] if summary_label.startswith("—") else [summary_label],
    }
    return mapping


def _preview_options(mapping: dict) -> dict:
    return {
        "time_mode": mapping.get("time_mode", "auto"),
        "time_base": mapping.get("time_base", "2017-01-01T00:00:00"),
        "drop_self_transfer": True,
        "drop_duplicates": True,
        "row_limit": 0,
        "sample_mode": "head",
        "time_start": "",
        "time_end": "",
        "output_name": "",
    }


def _render_clean_result(stats: dict) -> None:
    counters = stats.get("counters") or {}
    st.success(
        f"清洗完成：写出 **{counters.get('written_rows', 0):,}** 行 → `{stats.get('output', '')}`"
    )
    metric_cols = st.columns(5)
    metric_cols[0].metric("读入行数", f"{counters.get('read_rows', 0):,}", border=True)
    metric_cols[1].metric("有效行数", f"{counters.get('valid_rows', 0):,}", border=True)
    metric_cols[2].metric("账号数", f"{stats.get('unique_accounts', 0):,}", border=True)
    metric_cols[3].metric("耗时", f"{stats.get('elapsed_s', '-')} s", border=True)
    metric_cols[4].metric("数据时间跨度", f"{stats.get('time_min', '—')[:10]} ~ {stats.get('time_max', '—')[:10]}", border=True)

    with st.expander("清洗剔除明细（可追溯）", expanded=False):
        dropped = {
            "时间无法解析": counters.get("dropped_time", 0),
            "金额无法解析": counters.get("dropped_amount", 0),
            "账号为空": counters.get("dropped_account", 0),
            "自转账": counters.get("dropped_self_transfer", 0),
            "重复行（块内）": counters.get("dropped_duplicates", 0),
            "时间范围不符": counters.get("dropped_time_range", 0),
            "均匀抽样跳过": counters.get("sampled_by_stride", 0),
            "超出本次行数上限": counters.get("limited", 0),
        }
        st.dataframe(
            [{"原因": key, "行数": value} for key, value in dropped.items()],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"金额范围：{stats.get('amount_min')} ~ {stats.get('amount_max')}；"
            f"合计 {stats.get('amount_sum')}；"
            f"编码 {stats.get('encoding')}；分隔符 {stats.get('delimiter')!r}"
        )

    preview = stats.get("preview") or []
    if preview:
        st.markdown("**清洗后预览（前 10 行）**")
        st.dataframe(preview, width="stretch", hide_index=True)

    output = stats.get("output", "")
    csv_path = services.PROJECT_ROOT / output if output else None
    download_cols = st.columns(3)
    if csv_path and csv_path.exists():
        size_mb = csv_path.stat().st_size / 1024 / 1024
        if size_mb <= 200:
            try:
                csv_text = services.read_text(csv_path)
            except Exception:  # noqa: BLE001
                csv_text = ""
            if csv_text:
                download_cols[0].download_button(
                    "下载清洗后 CSV",
                    data=csv_text.encode("utf-8-sig"),
                    file_name=Path(output).name,
                    mime="text/csv",
                    width="stretch",
                )
        else:
            download_cols[0].caption(f"CSV 较大（{size_mb:.0f} MB），请直接从 `{output}` 取用")
    stats_file = stats.get("stats_file", "")
    try:
        stats_text = services.read_text(Path(services.PROJECT_ROOT / stats_file)) if stats_file else ""
    except Exception:  # noqa: BLE001
        stats_text = ""
    if stats_text:
        download_cols[1].download_button(
            "下载清洗报告 JSON",
            data=stats_text.encode("utf-8"),
            file_name=Path(stats_file).name,
            mime="application/json",
            width="stretch",
        )
    if download_cols[2].button("在调度页用这份数据建图", type="primary", width="stretch"):
        _goto_orchestration(output)


def _render_cleaned_list() -> None:
    cleaned = _cleaned()
    if not cleaned:
        st.caption("执行一次清洗后，这里会显示可复用的数据集。")
        return
    st.dataframe(
        [
            {
                "数据集": item["name"],
                "行数": item["rows"],
                "账号数": item["unique_accounts"],
                "来源": item["source"],
                "数据时间": f"{item['time_min'][:10]} ~ {item['time_max'][:10]}",
                "生成时间": item["generated_at"],
            }
            for item in cleaned
        ],
        width="stretch",
        hide_index=True,
    )
    names = [item["name"] for item in cleaned]
    selected = st.selectbox("选择已清洗数据集", names, key="ingest_cleaned_select")
    item = next(entry for entry in cleaned if entry["name"] == selected)
    action_cols = st.columns([1, 1, 2])
    if action_cols[0].button("在调度页使用", key=f"use_clean_{selected}", type="primary", width="stretch"):
        _goto_orchestration(item["csv_path"])
    with action_cols[1]:
        try:
            stats_text = Path(item["stats_path"]).read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            stats_text = ""
        if stats_text:
            st.download_button(
                "下载清洗报告",
                data=stats_text.encode("utf-8"),
                file_name=Path(item["stats_path"]).name,
                mime="application/json",
                width="stretch",
                key=f"dl_stats_{selected}",
            )
    action_cols[2].caption(f"数据文件：`{item['csv_path']}`")


def _render_pandas_lab() -> None:
    cleaned = _cleaned()
    if not cleaned:
        return
    names = [item["name"] for item in cleaned]
    controls = st.columns([2, 1, 1])
    dataset_name = controls[0].selectbox("分析数据集", names, key="ana_dataset")
    limit_label = controls[1].selectbox("载入行数", list(ANALYSIS_LIMITS.keys()), index=1, key="ana_limit")
    load_clicked = controls[2].button("加载到 pandas", width="stretch")
    item = next(entry for entry in cleaned if entry["name"] == dataset_name)
    if load_clicked:
        try:
            frame = services.load_cleaned_frame(item["csv_path"], limit=ANALYSIS_LIMITS[limit_label])
        except Exception as exc:  # noqa: BLE001
            st.error(f"加载失败：{type(exc).__name__}: {exc}")
        else:
            st.session_state["ana_frame"] = frame
            st.session_state["ana_frame_name"] = dataset_name
    frame = st.session_state.get("ana_frame")
    if frame is None or st.session_state.get("ana_frame_name") != dataset_name:
        st.caption("选择数据集和行数后，点“加载到 pandas”开始分析。")
        return

    amount = pd.to_numeric(frame.get("金额"), errors="coerce")
    times = pd.to_datetime(frame.get("交易时间"), errors="coerce")
    metric_cols = st.columns(4)
    metric_cols[0].metric("行数", f"{len(frame):,}", border=True)
    metric_cols[1].metric("金额合计", f"{amount.sum():,.2f}", border=True)
    metric_cols[2].metric("金额均值", f"{amount.mean():,.2f}", border=True)
    metric_cols[3].metric("时间跨度", f"{times.min()} ~ {times.max()}", border=True)

    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.markdown("**金额分布（对数分箱）**")
        positive = amount[amount > 0]
        if not positive.empty:
            bins = pd.cut(positive, bins=10)
            counts = bins.value_counts().sort_index()
            chart_data = pd.DataFrame(
                {"金额区间": [str(interval) for interval in counts.index], "笔数": counts.values}
            )
            st.bar_chart(chart_data, x="金额区间", y="笔数", height=260)
        else:
            st.caption("没有有效金额")
    with chart_cols[1]:
        st.markdown("**按日交易量**")
        if times.notna().any():
            by_day = times.dt.strftime("%Y-%m-%d").value_counts().sort_index()
            st.bar_chart(
                pd.DataFrame({"日期": by_day.index, "笔数": by_day.values}),
                x="日期",
                y="笔数",
                height=260,
            )
        else:
            st.caption("没有有效时间")

    top_cols = st.columns(2)
    with top_cols[0]:
        st.markdown("**付款账号 Top 10**")
        st.dataframe(
            frame["付款账号"].astype(str).value_counts().head(10).rename_axis("账号").reset_index(name="笔数"),
            width="stretch",
            hide_index=True,
        )
    with top_cols[1]:
        st.markdown("**收款账号 Top 10**")
        st.dataframe(
            frame["收款账号"].astype(str).value_counts().head(10).rename_axis("账号").reset_index(name="笔数"),
            width="stretch",
            hide_index=True,
        )

    st.markdown("**pandas 表达式分析（本地沙箱：仅允许 df / pd，禁止导入与文件/系统调用）**")
    expression = st.text_area(
        "pandas 表达式",
        value=PANDAS_EXAMPLES[0],
        height=90,
        key="ana_expression",
    )
    st.caption("示例：" + " ｜ ".join(PANDAS_EXAMPLES[1:]))
    if st.button("执行 pandas 分析", type="primary"):
        try:
            result = services.run_pandas_expression(item["csv_path"], expression, limit=ANALYSIS_LIMITS[limit_label])
        except Exception as exc:  # noqa: BLE001
            st.error(f"执行失败：{exc}")
        else:
            if isinstance(result, pd.DataFrame):
                st.dataframe(result, width="stretch", hide_index=True)
            elif isinstance(result, pd.Series):
                st.dataframe(result.rename("值").reset_index(), width="stretch", hide_index=True)
            else:
                st.metric("结果", str(result))


def render() -> None:
    flash = st.session_state.pop("ingest_flash", None)
    if flash:
        st.success(flash)

    theme.section("数据接入与清洗", "真实一手流水：自动识别 → 字段映射 → 流式清洗 → 建图")

    catalog = _catalog()
    cleaned = _cleaned()
    total_mb = sum(item["size_mb"] for item in catalog)
    metric_cols = st.columns(4)
    metric_cols[0].metric("可接入文件", f"{len(catalog)} 个", border=True)
    metric_cols[1].metric("可清洗数据量", f"{total_mb / 1024:.2f} GB", border=True)
    metric_cols[2].metric("已清洗数据集", f"{len(cleaned)} 个", border=True)
    metric_cols[3].metric("支持格式", "CSV/TSV/TXT/Excel", border=True)

    if not catalog:
        st.warning("data/ 下没有可接入文件，请先上传或把数据文件放进 data/ 目录。")
        return

    # ① 选择数据源
    with st.container(border=True):
        st.subheader("① 选择数据源")
        st.caption("支持服务器文件直读与上传；大文件无需上传。")
        labels = {item["path"]: item["label"] for item in catalog}
        paths = [item["path"] for item in catalog]
        if st.session_state.get("ingest_source_path") not in paths:
            st.session_state["ingest_source_path"] = paths[0]
        source_cols = st.columns([3, 1])
        selected_path = source_cols[0].selectbox(
            "服务器数据文件",
            options=paths,
            format_func=lambda path: labels.get(path, path),
            key="ingest_source_path",
        )
        if source_cols[1].button("刷新文件列表", width="stretch"):
            _catalog.clear()
            st.rerun()
        _render_upload()

    source_item = next(item for item in catalog if item["path"] == selected_path)
    path_key = _short_key(selected_path + str(source_item.get("mtime")))

    # ② 文件画像
    with st.container(border=True):
        st.subheader("② 文件画像与识别参数")
        override_cols = st.columns([1, 1, 1, 2])
        encoding_label = override_cols[0].selectbox(
            "编码", ENCODING_OPTIONS, key=f"ing_enc_{path_key}"
        )
        delimiter_label = override_cols[1].selectbox(
            "分隔符", list(DELIMITER_OPTIONS.keys()), key=f"ing_delim_{path_key}"
        )
        header_label = override_cols[2].selectbox(
            "表头", HEADER_OPTIONS, key=f"ing_header_{path_key}"
        )
        override_cols[3].caption("识别有误时可手工修正。")
        encoding = None if encoding_label == "自动" else encoding_label
        delimiter = DELIMITER_OPTIONS[delimiter_label]
        has_header = None if header_label == "自动" else header_label == "有表头"

        try:
            profile = _profile(selected_path, source_item.get("mtime", 0.0), encoding, delimiter, has_header)
        except Exception as exc:  # noqa: BLE001
            st.error(f"文件画像失败：{type(exc).__name__}: {exc}")
            profile = None
        if profile:
            profile_cols = st.columns(4)
            profile_cols[0].metric("文件大小", f"{profile['size_mb']} MB", border=True)
            profile_cols[1].metric(
                "估计行数",
                f"{profile['estimated_rows']:,}" if profile.get("estimated_rows") else "—",
                border=True,
            )
            profile_cols[2].metric(
                "编码 / 分隔符",
                f"{profile['encoding']} / {profile['delimiter_label']}",
                border=True,
            )
            profile_cols[3].metric(
                "列数 / 表头",
                f"{profile['column_count']} 列 / {'有' if profile['has_header'] else '无'}表头",
                border=True,
            )
            st.markdown(
                theme.pill(profile.get("dataset_hint_text") or "通用数据", "info"),
                unsafe_allow_html=True,
            )
            for warning in profile.get("warnings") or []:
                st.warning(warning, icon=":material/info:")
            with st.expander("原始预览与列画像", expanded=False):
                st.dataframe(profile.get("preview") or [], width="stretch", hide_index=True)
                st.dataframe(
                    [
                        {
                            "列名": item["name"],
                            "样例值": " | ".join(item["samples"][:3]),
                            "空值率": item["empty_ratio"],
                            "数值占比": item["numeric_ratio"],
                        }
                        for item in profile.get("column_profiles") or []
                    ],
                    width="stretch",
                    hide_index=True,
                )

    if not profile:
        return

    # ③ 字段映射
    with st.container(border=True):
        st.subheader("③ 字段映射（自动建议，可手工调整）")
        mapping = _mapping_inputs(profile, path_key)
        if not mapping:
            return
        missing = [
            label
            for label, value in (
                ("时间列", mapping["time_columns"]),
                ("金额列", mapping["amount_columns"]),
                ("付款账号列", mapping["from_columns"]),
                ("收款账号列", mapping["to_columns"]),
            )
            if not value
        ]
        if missing:
            st.warning(f"还缺少必填映射：{'、'.join(missing)}")
        preview_key = f"ing_preview_{path_key}"
        if st.button("预览清洗结果（前 200 行）", key=f"ing_preview_btn_{path_key}"):
            try:
                result = services.preview_clean_file(
                    selected_path, profile, mapping, _preview_options(mapping), limit=200
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"预览失败：{type(exc).__name__}: {exc}")
            else:
                st.session_state[preview_key] = result
        stored_preview = st.session_state.get(preview_key)
        if stored_preview:
            counters = stored_preview.get("counters") or {}
            count_cols = st.columns(4)
            count_cols[0].metric("读取行数", f"{counters.get('read_rows', 0):,}", border=True)
            count_cols[1].metric("有效行数", f"{counters.get('valid_rows', 0):,}", border=True)
            count_cols[2].metric("账号为空", f"{counters.get('dropped_account', 0):,}", border=True)
            count_cols[3].metric("自转账", f"{counters.get('dropped_self_transfer', 0):,}", border=True)
            st.dataframe(
                stored_preview.get("preview") or [], width="stretch", hide_index=True, height=240
            )

    # ④ 执行清洗
    with st.container(border=True):
        st.subheader("④ 执行清洗（大文件分块流式处理）")
        option_cols = st.columns([1, 1, 1])
        row_limit_label = option_cols[0].selectbox(
            "本次清洗行数上限", list(ROW_LIMIT_OPTIONS.keys()), index=2, key=f"ing_limit_{path_key}"
        )
        sample_mode_label = option_cols[1].selectbox(
            "抽样方式",
            list(SAMPLE_MODE_OPTIONS.keys()),
            index=0,
            key=f"ing_sample_{path_key}",
            help="均匀抽样覆盖整个文件时间范围；前 N 行最快。",
        )
        drop_self = option_cols[2].toggle("剔除自转账", value=True, key=f"ing_self_{path_key}")
        drop_duplicates = st.toggle("块内去重", value=True, key=f"ing_dup_{path_key}")
        time_cols = st.columns(2)
        time_start = time_cols[0].text_input(
            "时间过滤（起始，可空）", value="", placeholder="2025-01-01 00:00:00",
            key=f"ing_tstart_{path_key}",
        )
        time_end = time_cols[1].text_input(
            "时间过滤（结束，可空）", value="", placeholder="2025-02-01 00:00:00",
            key=f"ing_tend_{path_key}",
        )
        output_name = st.text_input(
            "输出数据集名称",
            value=f"{Path(selected_path).stem}_clean",
            key=f"ing_outname_{path_key}",
        )
        run_clicked = st.button("执行清洗", type="primary", key=f"ing_run_{path_key}")
        if run_clicked:
            options = {
                **_preview_options(mapping),
                "row_limit": ROW_LIMIT_OPTIONS[row_limit_label],
                "sample_mode": SAMPLE_MODE_OPTIONS[sample_mode_label],
                "drop_self_transfer": drop_self,
                "drop_duplicates": drop_duplicates,
                "time_start": time_start.strip(),
                "time_end": time_end.strip(),
                "output_name": output_name.strip(),
            }
            progress = st.progress(0.0, text="准备清洗……")
            status_line = st.empty()

            def _progress(fraction: float, message: str) -> None:
                progress.progress(min(max(fraction, 0.0), 1.0), text="清洗中……")
                status_line.caption(message)

            try:
                stats = services.clean_data_file(
                    selected_path, profile, mapping, options, progress_callback=_progress
                )
            except Exception as exc:  # noqa: BLE001
                progress.empty()
                status_line.empty()
                st.error(f"清洗失败：{type(exc).__name__}: {exc}")
            else:
                progress.progress(1.0, text="清洗完成")
                status_line.empty()
                st.session_state[f"ing_result_{path_key}"] = stats
                _cleaned.clear()
                _catalog.clear()
                st.session_state["ingest_flash"] = "清洗完成，已加入调度页“已清洗数据”分组。"
        stored_stats = st.session_state.get(f"ing_result_{path_key}")
        if stored_stats:
            _render_clean_result(stored_stats)

    # ⑤ 已清洗数据集
    with st.container(border=True):
        st.subheader("⑤ 已清洗数据集")
        _render_cleaned_list()

    # ⑥ 数据探查（有清洗产物时才显示）
    if cleaned:
        with st.container(border=True):
            st.subheader("⑥ 数据探查（pandas）")
            _render_pandas_lab()
