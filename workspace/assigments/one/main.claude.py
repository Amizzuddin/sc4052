################################################################################
#  Filename:      one/main.claude.py                                           #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 4:24:11 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 4:44:22 pm                       #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

#!/usr/bin/env python3
"""
Fat Tree Visualizer — Dash + Plotly edition
============================================
An interactive web app that lets you explore k-ary fat tree network topologies.

Features
--------
• Slider to pick k (2 – 12, even values only)
• Click any node to highlight all of its links and neighbours
• Hover tooltips on every node and edge
• Toggle visibility of each layer (core / aggregation / edge / hosts)
• Dark-themed, fully responsive layout

Run
---
    pip install dash plotly
    python ftree_dash.py
Then open http://127.0.0.1:8050 in your browser.
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import json

# ── third-party ───────────────────────────────────────────────────────────────
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update

# ═════════════════════════════════════════════════════════════════════════════
#  TOPOLOGY
# ═════════════════════════════════════════════════════════════════════════════

Y_CORE = 9.0
Y_AGG = 6.0
Y_EDGE = 3.0
Y_HOST = 0.5

COLORS = {
    "core": "#3B82F6",
    "aggregation": "#22C55E",
    "edge": "#F59E0B",
    "host": "#A855F7",
    "link_ca": "#64748B",
    "link_ae": "#475569",
    "link_eh": "#334155",
    "bg": "#0F172A",
    "panel": "#1E293B",
    "text": "#F1F5F9",
    "subtext": "#94A3B8",
    "border": "#334155",
    "highlight": "#F97316",
    "highlight_edge": "#FB923C",
}

LAYER_COLORS = {
    "core": COLORS["core"],
    "agg": COLORS["aggregation"],
    "edge": COLORS["edge"],
    "host": COLORS["host"],
}

NODE_SIZES = {
    "core": 28,
    "agg": 24,
    "edge": 22,
    "host": 14,
}


class FatTree:
    """k-ary fat tree (Al-Fares et al., 2008)."""

    def __init__(self, k: int):
        assert k >= 2 and k % 2 == 0, "k must be a positive even integer"
        self.k = k
        self.h = k // 2

        self.num_core = self.h * self.h
        self.num_agg = self.h * k
        self.num_edge = self.h * k
        self.num_hosts = self.h * self.h * k

        # (x, y, label, id)  — id = "layer:index"
        self.nodes: list[dict] = []
        # (src_id, dst_id, layer_pair)
        self.edges: list[dict] = []

        self._layout()
        self._connect()

    # ── layout ────────────────────────────────────────────────────────────────

    def _layout(self):
        k, h = self.k, self.h
        total_hosts = self.num_hosts
        W = float(total_hosts + 1)

        # hosts
        self._host_x = []
        for i in range(total_hosts):
            x = (i + 0.5) * W / total_hosts
            self._host_x.append(x)
            self.nodes.append(
                dict(
                    id=f"host:{i}",
                    layer="host",
                    x=x,
                    y=Y_HOST,
                    label=f"H{i // (h*h)},{i % (h*h)}",
                    title=f"Host {i}<br>Pod {i // (h*h)}",
                )
            )

        # edge switches
        self._edge_x = []
        hosts_per_pod = h * h
        for pod in range(k):
            base = pod * hosts_per_pod
            for e in range(h):
                start = base + e * h
                x = sum(self._host_x[start + s] for s in range(h)) / h
                self._edge_x.append(x)
                idx = pod * h + e
                self.nodes.append(
                    dict(
                        id=f"edge:{idx}",
                        layer="edge",
                        x=x,
                        y=Y_EDGE,
                        label=f"E{pod},{e}",
                        title=f"Edge switch {idx}<br>Pod {pod}, switch {e}",
                    )
                )

        # aggregation switches
        self._agg_x = []
        for pod in range(k):
            ex = self._edge_x[pod * h : pod * h + h]
            left, right = ex[0], ex[-1]
            for a in range(h):
                frac = (a + 0.5) / h
                x = left + frac * (right - left)
                self._agg_x.append(x)
                idx = pod * h + a
                self.nodes.append(
                    dict(
                        id=f"agg:{idx}",
                        layer="agg",
                        x=x,
                        y=Y_AGG,
                        label=f"A{pod},{a}",
                        title=f"Aggregation switch {idx}<br>Pod {pod}, switch {a}",
                    )
                )

        # core switches
        self._core_x = []
        for c in range(self.num_core):
            x = (c + 0.5) * (self.num_hosts + 1) / self.num_core
            self._core_x.append(x)
            row, col = c // h, c % h
            self.nodes.append(
                dict(
                    id=f"core:{c}",
                    layer="core",
                    x=x,
                    y=Y_CORE,
                    label=f"C{row},{col}",
                    title=f"Core switch {c}<br>Row {row}, Col {col}",
                )
            )

    def _connect(self):
        k, h = self.k, self.h

        # edge → host
        for pod in range(k):
            for e in range(h):
                ei = pod * h + e
                base = pod * h * h + e * h
                for s in range(h):
                    self.edges.append(dict(src=f"edge:{ei}", dst=f"host:{base+s}", pair="edge-host"))

        # agg → edge (full bipartite per pod)
        for pod in range(k):
            for a in range(h):
                ai = pod * h + a
                for e in range(h):
                    ei = pod * h + e
                    self.edges.append(dict(src=f"agg:{ai}", dst=f"edge:{ei}", pair="agg-edge"))

        # core → agg
        for i in range(h):
            for j in range(h):
                ci = i * h + j
                for pod in range(k):
                    ai = pod * h + i
                    self.edges.append(dict(src=f"core:{ci}", dst=f"agg:{ai}", pair="core-agg"))


# ═════════════════════════════════════════════════════════════════════════════
#  PLOTLY FIGURE BUILDER
# ═════════════════════════════════════════════════════════════════════════════


def build_figure(k: int, selected_node: str | None = None, hidden_layers: list[str] | None = None) -> go.Figure:
    hidden_layers = set(hidden_layers or [])
    ft = FatTree(k)

    # index nodes for quick lookup
    node_map: dict[str, dict] = {n["id"]: n for n in ft.nodes}

    # neighbours of selected node
    selected_nbrs: set[str] = set()
    selected_edges: set[tuple] = set()
    if selected_node and selected_node in node_map:
        for e in ft.edges:
            if e["src"] == selected_node:
                selected_nbrs.add(e["dst"])
                selected_edges.add((e["src"], e["dst"]))
            elif e["dst"] == selected_node:
                selected_nbrs.add(e["src"])
                selected_edges.add((e["src"], e["dst"]))

    fig = go.Figure()

    # ── Pod background rectangles ─────────────────────────────────────────────
    h = ft.h
    for pod in range(k):
        hosts_in_pod = [ft.nodes[i] for i in range(pod * h * h, pod * h * h + h * h)]
        x0 = hosts_in_pod[0]["x"] - 0.6
        x1 = hosts_in_pod[-1]["x"] + 0.6
        fig.add_shape(
            type="rect",
            x0=x0,
            y0=Y_HOST - 0.55,
            x1=x1,
            y1=Y_AGG + 0.45,
            line=dict(color="#334155", width=1),
            fillcolor="#1E293B",
            opacity=0.4,
            layer="below",
        )
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=Y_HOST - 0.42,
            text=f"Pod {pod}",
            showarrow=False,
            font=dict(size=10, color="#64748B"),
            xanchor="center",
            yanchor="top",
        )

    # ── Layer label annotations ───────────────────────────────────────────────
    total_width = ft.num_hosts + 1
    for y, lbl, col in [
        (Y_CORE, "Core", COLORS["core"]),
        (Y_AGG, "Aggregation", COLORS["aggregation"]),
        (Y_EDGE, "Edge", COLORS["edge"]),
        (Y_HOST, "Hosts", COLORS["host"]),
    ]:
        fig.add_annotation(
            x=-0.3,
            y=y,
            text=f"<b>{lbl}</b>",
            showarrow=False,
            xanchor="right",
            font=dict(size=12, color=col),
            xref="x",
            yref="y",
        )

    # ── Edges ─────────────────────────────────────────────────────────────────
    edge_groups = {
        "core-agg": dict(color=COLORS["link_ca"], width=1.2, dash="solid", opacity=0.5),
        "agg-edge": dict(color=COLORS["link_ae"], width=0.9, dash="solid", opacity=0.45),
        "edge-host": dict(color=COLORS["link_eh"], width=0.7, dash="solid", opacity=0.35),
    }

    # build one scatter per edge group (for legend) + highlighted edges on top
    pair_map: dict[str, list] = {p: [] for p in edge_groups}
    highlight_edge_xs, highlight_edge_ys = [], []

    for e in ft.edges:
        src, dst = node_map[e["src"]], node_map[e["dst"]]
        pair = e["pair"]
        is_sel = (e["src"], e["dst"]) in selected_edges or (e["dst"], e["src"]) in selected_edges

        if is_sel:
            highlight_edge_xs += [src["x"], dst["x"], None]
            highlight_edge_ys += [src["y"], dst["y"], None]
        else:
            pair_map[pair].append((src["x"], src["y"], dst["x"], dst["y"]))

    pair_labels = {
        "core-agg": "Core↔Agg links",
        "agg-edge": "Agg↔Edge links",
        "edge-host": "Edge↔Host links",
    }

    for pair, segs in pair_map.items():
        style = edge_groups[pair]
        xs, ys = [], []
        for x0, y0, x1, y1 in segs:
            xs += [x0, x1, None]
            ys += [y0, y1, None]
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    line=dict(color=style["color"], width=style["width"], dash=style["dash"]),
                    opacity=style["opacity"],
                    name=pair_labels[pair],
                    legendgroup=pair,
                    hoverinfo="skip",
                )
            )

    # highlighted edges
    if highlight_edge_xs:
        fig.add_trace(
            go.Scatter(
                x=highlight_edge_xs,
                y=highlight_edge_ys,
                mode="lines",
                line=dict(color=COLORS["highlight_edge"], width=2.5),
                opacity=0.9,
                name="Selected links",
                hoverinfo="skip",
                showlegend=bool(selected_node),
            )
        )

    # ── Nodes ─────────────────────────────────────────────────────────────────
    layer_order = ["host", "edge", "agg", "core"]
    layer_full = {"host": "Hosts", "edge": "Edge switches", "agg": "Aggregation switches", "core": "Core switches"}

    for layer in layer_order:
        nodes = [n for n in ft.nodes if n["layer"] == layer]
        if not nodes:
            continue

        visible = True if layer not in hidden_layers else "legendonly"

        xs = [n["x"] for n in nodes]
        ys = [n["y"] for n in nodes]
        ids = [n["id"] for n in nodes]
        labels = [n["label"] for n in nodes]
        titles = [n["title"] for n in nodes]

        marker_colors, marker_sizes, border_colors, border_widths = [], [], [], []
        for n in nodes:
            nid = n["id"]
            if nid == selected_node:
                marker_colors.append(COLORS["highlight"])
                marker_sizes.append(NODE_SIZES[layer] + 8)
                border_colors.append("rgba(255,255,255,1)")
                border_widths.append(2.5)
            elif nid in selected_nbrs:
                marker_colors.append(COLORS["highlight_edge"])
                marker_sizes.append(NODE_SIZES[layer] + 4)
                border_colors.append("rgba(255,255,255,0.9)")
                border_widths.append(1.5)
            else:
                marker_colors.append(LAYER_COLORS[layer])
                marker_sizes.append(NODE_SIZES[layer])
                border_colors.append("rgba(255,255,255,0.25)")
                border_widths.append(1.0)

        # text size: smaller for hosts when k is large
        txt_size = 7 if layer == "host" and k >= 6 else 9
        show_text = layer != "host" or k <= 4

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text" if show_text else "markers",
                marker=dict(
                    size=marker_sizes,
                    color=marker_colors,
                    line=dict(color=border_colors, width=border_widths),
                    symbol="circle",
                ),
                text=labels if show_text else None,
                textfont=dict(size=txt_size, color="#FFFFFF"),
                textposition="middle center",
                customdata=list(zip(ids, titles)),
                hovertemplate="<b>%{customdata[1]}</b><extra></extra>",
                name=f"{layer_full[layer]} ({len(nodes)})",
                legendgroup=layer,
                visible=visible,
            )
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=(
                f"<b>{k}-ary Fat Tree</b>  "
                f"<span style='font-size:13px;color:{COLORS['subtext']}'>"
                f"{ft.num_core} core · {ft.num_agg} agg · "
                f"{ft.num_edge} edge · {ft.num_hosts} hosts</span>"
            ),
            font=dict(size=18, color=COLORS["text"]),
            x=0.5,
            xanchor="center",
        ),
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        font=dict(color=COLORS["text"]),
        xaxis=dict(
            visible=False,
            range=[-1.5, ft.num_hosts + 1.5],
            fixedrange=False,
        ),
        yaxis=dict(
            visible=False,
            range=[-0.9, Y_CORE + 1.2],
            fixedrange=False,
            scaleanchor=None,
        ),
        legend=dict(
            bgcolor=COLORS["panel"],
            bordercolor=COLORS["border"],
            borderwidth=1,
            font=dict(size=11, color=COLORS["text"]),
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            orientation="v",
            x=1.01,
            y=1,
            xanchor="left",
            yanchor="top",
        ),
        margin=dict(l=60, r=180, t=70, b=40),
        hovermode="closest",
        dragmode="pan",
        uirevision=k,  # keep zoom/pan between updates with same k
    )

    return fig, ft


# ═════════════════════════════════════════════════════════════════════════════
#  DASH APP
# ═════════════════════════════════════════════════════════════════════════════

app = Dash(
    __name__,
    title="Fat Tree Visualizer",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ── Styles ────────────────────────────────────────────────────────────────────
BTN_BASE = dict(
    border=f"1px solid {COLORS['border']}",
    borderRadius="6px",
    padding="6px 14px",
    cursor="pointer",
    fontSize="13px",
    fontWeight="600",
    transition="all 0.15s",
)
BTN_PRIMARY = {**BTN_BASE, "background": COLORS["core"], "color": "#fff"}
BTN_SECONDARY = {**BTN_BASE, "background": COLORS["panel"], "color": COLORS["text"]}

CARD_STYLE = dict(
    background=COLORS["panel"],
    border=f"1px solid {COLORS['border']}",
    borderRadius="10px",
    padding="16px 20px",
    marginBottom="12px",
)

LABEL_STYLE = dict(
    color=COLORS["subtext"],
    fontSize="12px",
    fontWeight="600",
    letterSpacing="0.05em",
    textTransform="uppercase",
    marginBottom="8px",
)

# ── Sidebar stats helper ──────────────────────────────────────────────────────


def stat_row(label: str, value, color: str = COLORS["text"]):
    return html.Div(
        [
            html.Span(label, style=dict(color=COLORS["subtext"], fontSize="12px")),
            html.Span(str(value), style=dict(color=color, fontWeight="700", fontSize="15px", float="right")),
        ],
        style=dict(display="block", padding="3px 0", borderBottom=f"1px solid {COLORS['border']}"),
    )


def sidebar_stats(ft: FatTree) -> list:
    total_edges = len(ft.edges_core_agg) if hasattr(ft, "edges_core_agg") else 0
    # recompute from edges list
    ca = sum(1 for e in ft.edges if e["pair"] == "core-agg")
    ae = sum(1 for e in ft.edges if e["pair"] == "agg-edge")
    eh = sum(1 for e in ft.edges if e["pair"] == "edge-host")
    return [
        stat_row("k (arity)", ft.k, COLORS["core"]),
        stat_row("Pods", ft.k, COLORS["text"]),
        stat_row("Core switches", ft.num_core, COLORS["core"]),
        stat_row("Agg switches", ft.num_agg, COLORS["aggregation"]),
        stat_row("Edge switches", ft.num_edge, COLORS["edge"]),
        stat_row("Hosts", ft.num_hosts, COLORS["host"]),
        stat_row("Core↔Agg links", ca, COLORS["link_ca"]),
        stat_row("Agg↔Edge links", ae, COLORS["link_ae"]),
        stat_row("Edge↔Host links", eh, COLORS["link_eh"]),
        stat_row("Total links", ca + ae + eh, COLORS["text"]),
        stat_row("Oversubscription", "1:1", COLORS["text"]),
    ]


# ── Layout ────────────────────────────────────────────────────────────────────

app.layout = html.Div(
    style=dict(
        display="flex",
        flexDirection="column",
        height="100vh",
        fontFamily="'Inter', 'Segoe UI', sans-serif",
        background=COLORS["bg"],
        color=COLORS["text"],
        overflow="hidden",
    ),
    children=[
        # ── Top bar ───────────────────────────────────────────────────────────
        html.Div(
            style=dict(
                display="flex",
                alignItems="center",
                justifyContent="space-between",
                padding="10px 24px",
                borderBottom=f"1px solid {COLORS['border']}",
                background=COLORS["panel"],
                flexShrink=0,
            ),
            children=[
                html.Div(
                    [
                        html.Span("⬡ ", style=dict(color=COLORS["core"], fontSize="22px")),
                        html.Span("Fat Tree Visualizer", style=dict(fontSize="18px", fontWeight="700")),
                        html.Span(
                            "  Dash + Plotly", style=dict(fontSize="12px", color=COLORS["subtext"], marginLeft="8px")
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Span("k =", style=dict(marginRight="8px", fontSize="14px", color=COLORS["subtext"])),
                        dcc.Slider(
                            id="k-slider",
                            min=2,
                            max=12,
                            step=2,
                            value=4,
                            marks={i: dict(label=str(i), style=dict(color=COLORS["subtext"])) for i in range(2, 13, 2)},
                            tooltip=dict(placement="bottom", always_visible=False),
                            updatemode="drag",
                            className="k-slider",
                        ),
                    ],
                    style=dict(display="flex", alignItems="center", width="340px"),
                ),
                html.Button("Reset View", id="reset-btn", style=BTN_SECONDARY, n_clicks=0),
            ],
        ),
        # ── Main area ─────────────────────────────────────────────────────────
        html.Div(
            style=dict(display="flex", flex="1", overflow="hidden"),
            children=[
                # Graph
                html.Div(
                    style=dict(flex="1", minWidth=0),
                    children=[
                        dcc.Graph(
                            id="ftree-graph",
                            style=dict(width="100%", height="100%"),
                            config=dict(
                                scrollZoom=True,
                                displayModeBar=True,
                                modeBarButtonsToRemove=[
                                    "select2d",
                                    "lasso2d",
                                    "autoScale2d",
                                    "resetScale2d",
                                ],
                                displaylogo=False,
                                toImageButtonOptions=dict(
                                    format="png",
                                    filename="fattree",
                                    scale=2,
                                ),
                            ),
                            clear_on_unhover=True,
                        ),
                    ],
                ),
                # Sidebar
                html.Div(
                    id="sidebar",
                    style=dict(
                        width="240px",
                        flexShrink=0,
                        overflowY="auto",
                        padding="16px",
                        borderLeft=f"1px solid {COLORS['border']}",
                        background=COLORS["bg"],
                    ),
                    children=[
                        # Stats
                        html.Div(
                            style=CARD_STYLE,
                            children=[
                                html.Div("Topology Stats", style=LABEL_STYLE),
                                html.Div(id="stats-panel"),
                            ],
                        ),
                        # Selected node
                        html.Div(
                            style=CARD_STYLE,
                            children=[
                                html.Div("Selected Node", style=LABEL_STYLE),
                                html.Div(id="node-info", style=dict(fontSize="13px", color=COLORS["subtext"])),
                            ],
                        ),
                        # Tips
                        html.Div(
                            style={**CARD_STYLE, "background": "#0F172A", "border": "1px solid #1E3A5F"},
                            children=[
                                html.Div("Tips", style=LABEL_STYLE),
                                html.Ul(
                                    [
                                        html.Li("Click a node to highlight its links"),
                                        html.Li("Scroll to zoom, drag to pan"),
                                        html.Li("Click legend items to toggle layers"),
                                        html.Li("Double-click legend to isolate a layer"),
                                        html.Li("Use the camera button to export PNG"),
                                    ],
                                    style=dict(
                                        fontSize="12px", color=COLORS["subtext"], paddingLeft="16px", lineHeight="1.8"
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        # Hidden state stores
        dcc.Store(id="selected-node-store", data=None),
        dcc.Store(id="hidden-layers-store", data=[]),
    ],
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { overflow: hidden; }
            ::-webkit-scrollbar { width: 6px; }
            ::-webkit-scrollbar-track { background: #0F172A; }
            ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
            .k-slider { width: 260px !important; }
            .rc-slider-track { background-color: #3B82F6 !important; }
            .rc-slider-handle { border-color: #3B82F6 !important; }
            .modebar { background: #1E293B !important; }
            .modebar-btn svg { fill: #94A3B8 !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


# ═════════════════════════════════════════════════════════════════════════════
#  CALLBACKS
# ═════════════════════════════════════════════════════════════════════════════


@app.callback(
    Output("ftree-graph", "figure"),
    Output("stats-panel", "children"),
    Output("selected-node-store", "data"),
    Output("node-info", "children"),
    Input("k-slider", "value"),
    Input("ftree-graph", "clickData"),
    Input("reset-btn", "n_clicks"),
    State("selected-node-store", "data"),
    prevent_initial_call=False,
)
def update_graph(k, click_data, reset_clicks, current_selected):
    ctx = callback_context
    triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

    selected_node = current_selected

    # Reset selection on k-change or reset button
    if "k-slider" in triggered or "reset-btn" in triggered:
        selected_node = None

    # Handle node click
    if "clickData" in triggered and click_data:
        pts = click_data.get("points", [])
        if pts:
            cd = pts[0].get("customdata")
            if cd:
                nid = cd[0]
                # toggle: clicking same node deselects
                selected_node = None if nid == current_selected else nid

    fig, ft = build_figure(k, selected_node)

    # Node info panel
    if selected_node:
        n = next((x for x in ft.nodes if x["id"] == selected_node), None)
        if n:
            neighbours = []
            for e in ft.edges:
                if e["src"] == selected_node:
                    neighbours.append(e["dst"])
                elif e["dst"] == selected_node:
                    neighbours.append(e["src"])
            layer_label = {"core": "Core switch", "agg": "Aggregation switch", "edge": "Edge switch", "host": "Host"}[
                n["layer"]
            ]
            node_info = html.Div(
                [
                    html.Div(
                        n["label"],
                        style=dict(
                            fontSize="16px", fontWeight="700", color=LAYER_COLORS[n["layer"]], marginBottom="6px"
                        ),
                    ),
                    html.Div(layer_label, style=dict(color=COLORS["subtext"], fontSize="12px", marginBottom="8px")),
                    html.Div(f"Connections: {len(neighbours)}", style=dict(fontSize="13px")),
                    html.Div(
                        "Click again to deselect", style=dict(color=COLORS["subtext"], fontSize="11px", marginTop="6px")
                    ),
                ]
            )
        else:
            node_info = html.Div("Unknown node", style=dict(color=COLORS["subtext"]))
    else:
        node_info = html.Div("Click any node to inspect it", style=dict(color=COLORS["subtext"], fontSize="13px"))

    return fig, sidebar_stats(ft), selected_node, node_info


# ── suppress plotly relayout uirevision errors ───────────────────────────────
app.clientside_callback(
    """
    function(relayoutData) {
        return window.dash_clientside.no_update;
    }
    """,
    Output("hidden-layers-store", "data"),
    Input("ftree-graph", "relayoutData"),
    prevent_initial_call=True,
)


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║         Fat Tree Visualizer  — Dash + Plotly    ║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  Open your browser at  http://127.0.0.1:8050    ║")
    print("╚══════════════════════════════════════════════════╝")
    app.run(debug=False, host="127.0.0.1", port=8050)
