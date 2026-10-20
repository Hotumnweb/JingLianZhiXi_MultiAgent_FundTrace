# -*- coding: utf-8 -*-
"""资金网络图与平台图表（Plotly 实现，离线可用）。"""

from __future__ import annotations

import math

import networkx as nx
import plotly.graph_objects as go

CATEGORY_STYLE = {
    "gather": {"color": "#a78bfa", "label": "归集账户"},
    "cycle": {"color": "#fbbf24", "label": "环形转账账户"},
    "fast_io": {"color": "#38bdf8", "label": "快进快出账户"},
    "neighbor": {"color": "#475569", "label": "关联账户"},
}

_LAYOUT = dict(
    template=None,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#cbd5e1", size=12),
    margin=dict(l=10, r=10, t=10, b=10),
    hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#e2e8f0")),
)


def empty_figure(message: str = "暂无图谱数据") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(color="#64748b", size=14),
    )
    fig.update_layout(**_LAYOUT, xaxis=dict(visible=False), yaxis=dict(visible=False), height=520)
    return fig


def build_network_figure(payload: dict | None, height: int = 560) -> go.Figure:
    """根据 {nodes, edges} 生成资金网络关系图。"""
    if not payload or not payload.get("nodes"):
        return empty_figure()

    nodes = payload["nodes"]
    edges = payload.get("edges") or []
    graph = nx.Graph()
    for node in nodes:
        graph.add_node(node["id"])
    for edge in edges:
        graph.add_edge(edge["src"], edge["dst"])

    count = max(graph.number_of_nodes(), 1)
    try:
        if count <= 1500:
            pos = nx.spring_layout(graph, seed=17, k=1.6 / math.sqrt(count), iterations=50)
        else:
            pos = nx.circular_layout(graph)
    except Exception:  # noqa: BLE001
        pos = {node: (0.0, 0.0) for node in graph.nodes()}

    xs = [value[0] for value in pos.values()] or [0.0]
    ys = [value[1] for value in pos.values()] or [0.0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    normalized = {
        node: ((point[0] - min_x) / span_x, (point[1] - min_y) / span_y)
        for node, point in pos.items()
    }

    fig = go.Figure()

    # 边
    edge_x, edge_y = [], []
    for edge in edges:
        if edge["src"] not in normalized or edge["dst"] not in normalized:
            continue
        x0, y0 = normalized[edge["src"]]
        x1, y1 = normalized[edge["dst"]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(color="rgba(148,163,184,0.16)", width=1),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # 节点按类别分层绘制
    grouped: dict[str, list[dict]] = {}
    for node in nodes:
        category = node.get("category") or "neighbor"
        grouped.setdefault(category, []).append(node)

    for category, style in CATEGORY_STYLE.items():
        group = grouped.get(category) or []
        if not group:
            continue
        gx, gy, gtext, ghover, gsize = [], [], [], [], []
        for node in group:
            point = normalized.get(node["id"])
            if not point:
                continue
            gx.append(point[0])
            gy.append(point[1])
            show_label = category != "neighbor"
            gtext.append(node["id"] if show_label else "")
            degree = graph.degree(node["id"]) if node["id"] in graph else 0
            ghover.append(
                f"<b>{node['id']}</b><br>类别：{style['label']}<br>"
                f"关联边：{degree}<br>交易笔数：{node.get('tx_count', 0)}"
            )
            gsize.append(9 + min(degree, 14) * 1.1 if category != "neighbor" else 5.5 + min(degree, 10) * 0.5)
        fig.add_trace(
            go.Scatter(
                x=gx,
                y=gy,
                mode="markers+text" if category != "neighbor" else "markers",
                name=style["label"],
                text=gtext,
                textposition="top center",
                textfont=dict(size=9, color="#e2e8f0"),
                hovertext=ghover,
                hoverinfo="text",
                marker=dict(
                    color=style["color"],
                    size=gsize,
                    line=dict(color="rgba(255,255,255,0.35)", width=1),
                ),
            )
        )

    fig.update_layout(
        **_LAYOUT,
        height=height,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.0,
            x=0.0,
            bgcolor="rgba(15,23,42,0.0)",
            font=dict(size=11, color="#94a3b8"),
        ),
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
        hovermode="closest",
    )
    return fig


def rule_bar_figure(counts: dict, height: int = 300) -> go.Figure:
    labels = ["多层归集", "环形转账链", "快进快出"]
    keys = ["gather", "cycles", "fast_io"]
    values = [counts.get(key, 0) for key in keys]
    colors = ["#a78bfa", "#fbbf24", "#38bdf8"]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            text=[str(value) for value in values],
            textposition="outside",
            marker_color=colors,
            width=0.55,
        )
    )
    fig.update_layout(
        **_LAYOUT,
        height=height,
        yaxis=dict(title="命中数量", gridcolor="rgba(148,163,184,0.10)"),
        xaxis=dict(title=""),
        showlegend=False,
    )
    return fig


def risk_bar_figure(rows: list[dict], top_n: int = 10, height: int = 320) -> go.Figure:
    if not rows:
        return empty_figure("暂无可疑账户排行")
    top = rows[:top_n]
    accounts = [item["account"] for item in top][::-1]
    scores = [item["score"] for item in top][::-1]
    fig = go.Figure(
        go.Bar(
            x=scores,
            y=accounts,
            orientation="h",
            text=[f"{score:.0f}" for score in scores],
            textposition="outside",
            marker=dict(
                color=scores,
                colorscale=[[0, "#1d4ed8"], [0.5, "#7c3aed"], [1, "#ef4444"]],
                showscale=False,
            ),
        )
    )
    fig.update_layout(
        **_LAYOUT,
        height=height,
        xaxis=dict(title="证据强度", gridcolor="rgba(148,163,184,0.10)"),
        yaxis=dict(title=""),
        showlegend=False,
    )
    return fig


def ring_type_figure(ring_types: dict, height: int = 280) -> go.Figure:
    if not ring_types:
        return empty_figure("暂无团伙数据")
    labels = list(ring_types.keys())
    values = list(ring_types.values())
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=["#a78bfa", "#38bdf8", "#34d399", "#fbbf24"]),
            textinfo="label+value",
        )
    )
    fig.update_layout(**_LAYOUT, height=height, showlegend=False)
    return fig
