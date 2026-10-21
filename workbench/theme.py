# -*- coding: utf-8 -*-
"""平台主题与通用 UI 组件。

设计原则：
1. 纯 CSS + HTML，不依赖外部 CDN（断网演示时样式不会丢）；
2. 深色大屏风格，适合投影/答辩现场；
3. 组件函数只返回 HTML 字符串，方便页面组合与单测。
"""

from __future__ import annotations

import html
from datetime import datetime

ACCENT = "#38bdf8"
GOLD = "#fbbf24"
RED = "#f87171"
GREEN = "#34d399"
PURPLE = "#a78bfa"
MUTED = "#94a3b8"

_CSS = """
<style>
:root {
  --jz-bg: #070b14;
  --jz-panel: rgba(15, 23, 42, 0.72);
  --jz-border: rgba(148, 163, 184, 0.16);
  --jz-text: #e2e8f0;
  --jz-muted: #94a3b8;
  --jz-accent: #38bdf8;
}
.stApp {
  background:
    radial-gradient(900px 480px at 12% -8%, rgba(56, 189, 248, 0.12), transparent 60%),
    radial-gradient(800px 420px at 88% 0%, rgba(167, 139, 250, 0.10), transparent 55%),
    linear-gradient(180deg, #070b14 0%, #050810 100%);
  color: var(--jz-text);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] {
  background: rgba(8, 13, 24, 0.96);
  border-right: 1px solid var(--jz-border);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.0rem; }
.block-container { padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 1560px; }
h1, h2, h3, h4 { color: var(--jz-text); }
p, li, label, span { color: var(--jz-text); }
a { color: var(--jz-accent); }

/* 顶部标题 */
.jz-hero {
  border: 1px solid var(--jz-border);
  background: linear-gradient(120deg, rgba(15, 23, 42, .92), rgba(8, 13, 24, .75));
  border-radius: 18px;
  padding: 20px 24px;
  margin-bottom: 18px;
  box-shadow: 0 18px 45px rgba(0, 0, 0, .35);
}
.jz-hero-title {
  font-size: 25px; font-weight: 800; letter-spacing: .5px;
  background: linear-gradient(90deg, #7dd3fc, #a78bfa, #fbbf24);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.jz-hero-sub { color: var(--jz-muted); font-size: 13px; margin-top: 6px; }
.jz-hero-badges { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }

/* 徽标 */
.jz-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; border-radius: 999px;
  font-size: 12px; letter-spacing: .3px;
  border: 1px solid var(--jz-border);
  background: rgba(148, 163, 184, .08);
}

/* 分区标题 */
.jz-section { margin: 16px 0 10px 0; }
.jz-section-title {
  font-size: 16px; font-weight: 700; color: #f1f5f9;
  border-left: 3px solid var(--jz-accent); padding-left: 10px;
}
.jz-section-sub { color: var(--jz-muted); font-size: 12px; margin-top: 4px; padding-left: 13px; }

/* KPI 卡 */
.jz-kpi {
  border: 1px solid var(--jz-border);
  border-top: 3px solid var(--accent, #38bdf8);
  background: var(--jz-panel);
  border-radius: 14px;
  padding: 14px 16px;
  min-height: 108px;
  box-shadow: 0 10px 26px rgba(0,0,0,.25);
}
.jz-kpi-label { color: var(--jz-muted); font-size: 12px; letter-spacing: .5px; }
.jz-kpi-value { color: var(--accent, #38bdf8); font-size: 28px; font-weight: 800; line-height: 1.25; margin-top: 4px; }
.jz-kpi-hint { color: #64748b; font-size: 11px; margin-top: 4px; }

/* 节点卡 */
.jz-node {
  border: 1px solid var(--jz-border);
  background: var(--jz-panel);
  border-radius: 14px;
  padding: 14px 15px;
  min-height: 150px;
}
.jz-node-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.jz-node-role { color: var(--jz-muted); font-size: 11px; letter-spacing: .4px; }
.jz-node-name { color: #f8fafc; font-weight: 700; font-size: 14px; margin: 7px 0 4px 0; }
.jz-node-detail { color: var(--jz-muted); font-size: 12px; line-height: 1.55; }
.jz-node-endpoint { color: #64748b; font-size: 11px; margin-top: 5px; word-break: break-all; }

/* 流水线阶段 */
.jz-stages { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 6px 0 12px 0; }
.jz-stage {
  border: 1px solid var(--jz-border);
  border-radius: 12px; padding: 11px 13px;
  background: rgba(15, 23, 42, .55);
}
.jz-stage.pending { opacity: .55; }
.jz-stage.done { border-color: rgba(52, 211, 153, .45); background: rgba(52, 211, 153, .07); }
.jz-stage.active { border-color: rgba(56, 189, 248, .65); background: rgba(56, 189, 248, .08); box-shadow: 0 0 22px rgba(56, 189, 248, .12); }
.jz-stage-idx { color: var(--jz-muted); font-size: 11px; }
.jz-stage-name { color: #f1f5f9; font-size: 14px; font-weight: 700; margin-top: 3px; }
.jz-stage-desc { color: var(--jz-muted); font-size: 11px; margin-top: 3px; }

/* 其它 */
.jz-note {
  border: 1px dashed var(--jz-border);
  background: rgba(15, 23, 42, .45);
  border-radius: 12px; padding: 12px 14px;
  color: var(--jz-muted); font-size: 12px; line-height: 1.7;
}
.jz-code {
  font-family: Consolas, "Courier New", monospace;
  font-size: 12px;
}
.jz-report-box {
  border: 1px solid var(--jz-border);
  background: rgba(15, 23, 42, .62);
  border-radius: 16px;
  padding: 18px 22px;
  max-height: 720px; overflow-y: auto;
}
.jz-report-box h2 { font-size: 17px; margin-top: 16px; }
.jz-report-box h3 { font-size: 15px; margin-top: 12px; }

div[data-testid="stMetric"] {
  background: var(--jz-panel);
  border: 1px solid var(--jz-border);
  border-radius: 12px; padding: 8px 12px;
}
.stButton > button, .stDownloadButton > button {
  border-radius: 10px;
  border: 1px solid rgba(56, 189, 248, .35);
  background: linear-gradient(180deg, rgba(56, 189, 248, .18), rgba(56, 189, 248, .06));
  color: #e0f2fe;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: rgba(56, 189, 248, .75);
  box-shadow: 0 0 18px rgba(56, 189, 248, .18);
}
[data-testid="stExpander"] {
  background: rgba(15, 23, 42, .35);
  border: 1px solid var(--jz-border);
  border-radius: 12px;
}
[data-testid="stDataFrame"] { border: 1px solid var(--jz-border); border-radius: 10px; }
#MainMenu, footer { visibility: hidden; }
</style>
"""


def inject_theme() -> None:
    """注入全局深色主题（每个 Streamlit 页面首行调用一次即可）。"""
    import streamlit as st

    st.markdown(_CSS, unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value))


def pill(text: str, tone: str = "info") -> str:
    """状态徽标：ok / warn / danger / info。"""
    palette = {
        "ok": ("rgba(52, 211, 153, .14)", GREEN),
        "warn": ("rgba(251, 191, 36, .14)", GOLD),
        "danger": ("rgba(248, 113, 113, .14)", RED),
        "info": ("rgba(56, 189, 248, .14)", ACCENT),
        "muted": ("rgba(148, 163, 184, .10)", MUTED),
    }
    bg, color = palette.get(tone, palette["info"])
    return f'<span class="jz-pill" style="background:{bg};color:{color};">{esc(text)}</span>'


def hero(title: str, subtitle: str = "", badges: list[str] | None = None) -> None:
    """顶部标题区（只保留必要信息，不堆营销文案）。"""
    import streamlit as st

    subtitle_html = f'<div class="jz-hero-sub">{esc(subtitle)}</div>' if subtitle else ""
    badge_html = "".join(pill(badge, "info") for badge in (badges or []))
    badges_html = f'<div class="jz-hero-badges">{badge_html}</div>' if badge_html else ""
    st.markdown(
        f"""
        <div class="jz-hero">
          <div class="jz-hero-title">{esc(title)}</div>
          {subtitle_html}
          {badges_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str, subtitle: str = "") -> None:
    import streamlit as st

    st.markdown(
        f"""
        <div class="jz-section">
          <div class="jz-section-title">{esc(title)}</div>
          <div class="jz-section-sub">{esc(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value, hint: str = "", accent: str = ACCENT) -> str:
    return f"""
    <div class="jz-kpi" style="--accent:{accent};">
      <div class="jz-kpi-label">{esc(label)}</div>
      <div class="jz-kpi-value">{esc(value)}</div>
      <div class="jz-kpi-hint">{esc(hint)}</div>
    </div>
    """


def node_card(node: dict) -> str:
    status = node.get("status", "offline")
    tone = {"online": "ok", "warn": "warn", "placeholder": "muted"}.get(status, "danger")
    status_text = {
        "online": "在线",
        "warn": "告警",
        "placeholder": "占位",
        "offline": "离线",
    }.get(status, "未知")
    latency = node.get("latency_ms")
    if status == "placeholder":
        latency_text = "待接入"
    elif isinstance(latency, (int, float)) and latency > 0:
        latency_text = f"{latency:.0f} ms"
    else:
        latency_text = "本机"
    return f"""
    <div class="jz-node">
      <div class="jz-node-head">
        <span class="jz-node-role">NODE {esc(node.get('index', ''))} · {esc(node.get('role_en', ''))}</span>
        {pill(f"{status_text} · {latency_text}", tone)}
      </div>
      <div class="jz-node-name">{esc(node.get('name', ''))}</div>
      <div class="jz-node-detail">{esc(node.get('detail', ''))}</div>
      <div class="jz-node-endpoint">{esc(node.get('endpoint', ''))}</div>
    </div>
    """


def _stage_class(state: str) -> str:
    return {"pending": "pending", "active": "active", "done": "done"}.get(state, "pending")


def pipeline_stages(stages: list[tuple], states: dict[str, str], current: str | None = None) -> str:
    """渲染流水线阶段卡片。

    stages: [(key, 名称, 描述), ...]
    states: {key: pending/active/done}
    """
    cards = []
    for index, (key, name, desc) in enumerate(stages, start=1):
        state = "done" if states.get(key) == "done" else ("active" if key == current else "pending")
        cards.append(
            f"""
            <div class="jz-stage {_stage_class(state)}">
              <div class="jz-stage-idx">STAGE {index:02d}</div>
              <div class="jz-stage-name">{esc(name)}</div>
              <div class="jz-stage-desc">{esc(desc)}</div>
            </div>
            """
        )
    return f'<div class="jz-stages">{"".join(cards)}</div>'


def report_box(markdown_text: str) -> str:
    """报告展示框（客户端只渲染 markdown 文本，外层滚动）。"""
    return f'<div class="jz-report-box">{markdown_text}</div>'


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
