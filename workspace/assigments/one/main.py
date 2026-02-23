################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 4:44:12 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 4:54:51 pm                       #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

#!/usr/bin/env python3
"""
Fat Tree Visualizer — faithful Python/Dash+Plotly recreation of
https://github.com/h8liu/ftree-vis  /  https://s3.linkmeup.ru/linkmeup/ftree/

Visual layout matches the original exactly:
  • The tree is drawn as a FOLDED / BUTTERFLY layout (like a real datacenter rack view)
  • Core switches sit in the CENTER column
  • Aggregation / Edge layers fan OUT symmetrically above AND below
  • Hosts (red dots) appear at the TOP and BOTTOM edges
  • Switches are dark-blue SQUARES; hosts are small red circles
  • Grey lines connect every link

Left panel mirrors the original sidebar:
  • Inputs:  Tree Depth, Ports per Switch
  • Stats:   Hosts, Switches, Cables, Transmitters, Switch Tx's

Run:
    pip install dash plotly
    python ftree_dash.py
    → http://127.0.0.1:8050
"""

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html

# ── Visual constants ──────────────────────────────────────────────────────────
C_HOST_FILL = "#b22222"  # dark red fill  (host dots)
C_HOST_LINE = "#8b0000"  # host border
C_SW_FILL = "#1a237e"  # dark navy fill (switch squares)
C_SW_LINE = "#283593"  # switch border
C_LINK = "#9e9e9e"  # grey links
C_BG = "#ffffff"
C_PANEL = "#f0f0f0"
C_TEXT = "#333333"
C_STAT = "#333333"
C_LABEL = "#555555"

HOST_SZ = 9  # marker size for hosts (small circle)
SW_SZ = 14  # marker size for switches (square)

# Y-spacing between layers (in data units)
Y_LAYER = 3.0


# ═════════════════════════════════════════════════════════════════════════════
#  TOPOLOGY MATH  (verified against all three reference screenshots)
# ═════════════════════════════════════════════════════════════════════════════


def compute_stats(depth: int, k: int) -> dict:
    """
    Exact formulas reverse-engineered from the reference screenshots:

      depth=2, k=4 → hosts=8,  sw=6,  cables=16,  tx=32,  swtx=24
      depth=3, k=4 → hosts=16, sw=20, cables=48,  tx=96,  swtx=80
      depth=4, k=4 → hosts=32, sw=56, cables=128, tx=256, swtx=224

    Formulas:
      h = k // 2
      hosts = k * h^(depth-1)

      layer_counts[i]:
        non-top layers (i < depth-1): k * h^(depth-2)   [same count each]
        top layer      (i = depth-1): h^(depth-1)

      cables = hosts  +  sum(layer_counts[i] * h  for i in 0..depth-2)
      transmitters = cables * 2
      switch_txs   = total_switches * k   (every switch uses all k ports)
    """
    h = k // 2
    hosts = k * (h ** (depth - 1))

    layer_counts = []
    for i in range(depth):
        if depth == 1:
            layer_counts.append(1)
        elif i == depth - 1:  # top (core) layer
            layer_counts.append(h ** (depth - 1))
        else:  # edge / agg / ...
            layer_counts.append(k * (h ** max(0, depth - 2)))

    total_sw = sum(layer_counts)

    cables = hosts
    for i in range(depth - 1):
        cables += layer_counts[i] * h

    tx = cables * 2
    swtx = total_sw * k

    return {
        "depth": depth,
        "k": k,
        "h": h,
        "hosts": hosts,
        "switches": total_sw,
        "layer_counts": layer_counts,
        "cables": cables,
        "transmitters": tx,
        "switch_txs": swtx,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  LAYOUT  — Butterfly / folded fat tree
# ═════════════════════════════════════════════════════════════════════════════
#
# The original JS draws the tree as a symmetric vertical strip:
#
#   ┌──────────── hosts ─────────────┐   ← top (y = +max)
#   │         edge switches          │
#   │       agg switches             │
#   │     core switches              │   ← centre (y = 0)
#   │       agg switches             │
#   │         edge switches          │
#   └──────────── hosts ─────────────┘   ← bottom (y = -max)
#
# Each layer is replicated ABOVE and BELOW the core (symmetric).
# Within each layer, nodes are spread horizontally with equal spacing.
# Links follow the standard k-ary connectivity.


def build_topology(depth: int, k: int):
    """
    Returns (nodes, edges) where:
      nodes = list of dict {id, kind, x, y, layer_idx}
      edges = list of dict {x0,y0,x1,y1}

    Coordinate system:
      • x is horizontal (0 … total_width)
      • y: core layer sits at y=0 (centre)
            each step outward adds Y_LAYER
            top half is POSITIVE y, bottom half is NEGATIVE y
      • hosts at y = +depth * Y_LAYER  (top)  and  y = -depth * Y_LAYER  (bottom)
    """
    st = compute_stats(depth, k)
    h = st["h"]
    lc = st["layer_counts"]  # lc[0]=edge … lc[depth-1]=core
    hosts = st["hosts"]

    nodes: list[dict] = []
    edges: list[dict] = []

    # ── Horizontal positions ──────────────────────────────────────────────────
    # The width of the canvas is determined by whichever layer has the most nodes.
    # That is always the first (edge) layer for depth>=2, or the host layer.
    # We space all layers to fit max_nodes within the total width.

    max_nodes = max(hosts, max(lc))
    total_w = float(max_nodes + 1)

    def x_positions(count: int) -> list[float]:
        """Evenly space `count` nodes across the canvas width."""
        return [(i + 0.5) * total_w / count for i in range(count)]

    # Cache x positions for each layer (index 0=edge … depth-1=core)
    layer_x: list[list[float]] = []
    for li in range(depth):
        layer_x.append(x_positions(lc[li]))
    host_x = x_positions(hosts)

    # ── Y coordinates ─────────────────────────────────────────────────────────
    # Core is at y_offset = 0  (index depth-1 from bottom = layer 0 from top)
    # Going "outward" (toward hosts) each layer adds Y_LAYER.
    # The sign: top half = positive, bottom half = negative.
    #
    # Layer indices from core outward:
    #   core     → offset 0          (layer depth-1 in lc)
    #   next     → offset Y_LAYER    (layer depth-2 in lc)
    #   ...
    #   edge     → offset (depth-1)*Y_LAYER
    #   hosts    → offset  depth   *Y_LAYER
    #
    # We will create TWO copies of every switch layer (top & bottom)
    # and TWO copies of the host layer.

    def y_top(layer_from_core: int) -> float:
        return layer_from_core * Y_LAYER

    def y_bot(layer_from_core: int) -> float:
        return -layer_from_core * Y_LAYER

    # ── Create nodes ──────────────────────────────────────────────────────────
    # Convention for node IDs:
    #   switches: "T{li}_{idx}"  (top half)   and  "B{li}_{idx}"  (bottom half)
    #   core:     "C{idx}"       (shared centre, appears once)
    #   hosts:    "TH{i}"  (top) and "BH{i}"  (bottom)

    # Core layer (centre, y=0, not duplicated)
    core_li = depth - 1  # index in lc
    for idx, x in enumerate(layer_x[core_li]):
        nid = f"C{idx}"
        nodes.append({"id": nid, "kind": "switch", "layer": "core", "x": x, "y": 0.0, "idx": idx, "half": "C"})

    # Switch layers going outward (exclude core)
    # from_core = 1 for the layer just inside core (agg or edge for depth=2)
    # from_core = depth-1 for the edge layer
    lname_map = {0: "edge", 1: "agg", 2: "core", 3: "super"}
    for fc in range(1, depth):  # fc = "distance from core"
        li = depth - 1 - fc  # index in lc (depth-2 → 0)
        lname = ["edge", "agg", "mid", "mid2"][min(li, 3)]
        for idx, x in enumerate(layer_x[li]):
            for half, ysign, prefix in [("T", +1, "T"), ("B", -1, "B")]:
                nid = f"{prefix}{li}_{idx}"
                nodes.append(
                    {
                        "id": nid,
                        "kind": "switch",
                        "layer": lname,
                        "x": x,
                        "y": ysign * fc * Y_LAYER,
                        "idx": idx,
                        "half": half,
                    }
                )

    # Hosts (top and bottom)
    host_y_top = depth * Y_LAYER
    host_y_bot = -depth * Y_LAYER
    for i, x in enumerate(host_x):
        nodes.append({"id": f"TH{i}", "kind": "host", "layer": "host", "x": x, "y": host_y_top, "idx": i, "half": "T"})
        nodes.append({"id": f"BH{i}", "kind": "host", "layer": "host", "x": x, "y": host_y_bot, "idx": i, "half": "B"})

    # ── Create edges ──────────────────────────────────────────────────────────
    # Build a position lookup for quick access
    node_pos: dict[str, tuple[float, float]] = {n["id"]: (n["x"], n["y"]) for n in nodes}

    def add_edge(nid0: str, nid1: str):
        x0, y0 = node_pos[nid0]
        x1, y1 = node_pos[nid1]
        edges.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "src": nid0, "dst": nid1})

    # ── Host ↔ Edge switch connectivity ──────────────────────────────────────
    # Edge switches are at fc=depth-1 (outermost), li=0
    edge_li = 0
    edge_cnt = lc[edge_li]
    hope = hosts // edge_cnt  # hosts per edge switch

    for half, prefix, hprefix in [("T", "T", "TH"), ("B", "B", "BH")]:
        for ei in range(edge_cnt):
            eid = f"{prefix}{edge_li}_{ei}"
            for s in range(hope):
                hid = f"{hprefix}{ei * hope + s}"
                add_edge(eid, hid)

    # ── Inter-switch connectivity (bottom-up / core-outward) ──────────────────
    # We connect each pair of adjacent switch layers.
    # Layers from core outward:
    #   core (li=depth-1)  ←→  layer (li=depth-2)  ←→ ... ←→  edge (li=0)
    # The connectivity rule (standard fat tree bipartite):
    #   For each "pod" group:
    #     h upper-layer switches each connect to h lower-layer switches.
    #
    # We handle top and bottom halves identically (mirror).

    for fc in range(1, depth):  # fc=1: core↔next, fc=depth-1: agg↔edge
        upper_li = depth - 1  # core always on "upper" side (centre)
        lower_li = depth - 1 - fc  # outward layer

        if fc == 1:
            # Core ↔ first outer layer (agg or edge for depth=2)
            upper_cnt = lc[upper_li]  # core count
            lower_cnt = lc[lower_li]
            # Each core switch connects to h lower switches (one per pod, top and bottom)
            # Number of pods at this boundary:
            num_pods = max(1, upper_cnt // h)
            lpp = lower_cnt // num_pods  # lower switches per pod

            for pod in range(num_pods):
                for lo in range(lpp):
                    li_idx = pod * lpp + lo
                    for up in range(h):
                        ui_idx = pod * h + up
                        if li_idx < lower_cnt and ui_idx < upper_cnt:
                            cid = f"C{ui_idx}"
                            for half, prefix in [("T", "T"), ("B", "B")]:
                                lid = f"{prefix}{lower_li}_{li_idx}"
                                add_edge(cid, lid)
        else:
            # Two outer layers connect on the same half (top or bottom)
            # upper here means "closer to core"
            inner_li = depth - 1 - (fc - 1)  # closer-to-core layer
            outer_li = depth - 1 - fc  # further-from-core layer
            inner_cnt = lc[inner_li]
            outer_cnt = lc[outer_li]
            num_pods = max(1, inner_cnt // h)
            lpp = outer_cnt // num_pods

            for half, prefix in [("T", "T"), ("B", "B")]:
                for pod in range(num_pods):
                    for lo in range(lpp):
                        lo_idx = pod * lpp + lo
                        for up in range(h):
                            ui_idx = pod * h + up
                            if lo_idx < outer_cnt and ui_idx < inner_cnt:
                                inner_id = f"{prefix}{inner_li}_{ui_idx}"
                                outer_id = f"{prefix}{outer_li}_{lo_idx}"
                                add_edge(inner_id, outer_id)

    return nodes, edges, st, total_w


# ═════════════════════════════════════════════════════════════════════════════
#  PLOTLY FIGURE BUILDER
# ═════════════════════════════════════════════════════════════════════════════


def build_figure(depth: int, k: int, selected: str | None = None):
    nodes, edges, stats, total_w = build_topology(depth, k)
    h = stats["h"]
    node_map = {n["id"]: n for n in nodes}

    # Neighbours of selected node
    sel_nbrs: set[str] = set()
    sel_edge_set: set[frozenset] = set()
    if selected and selected in node_map:
        for e in edges:
            if e["src"] == selected:
                sel_nbrs.add(e["dst"])
                sel_edge_set.add(frozenset([e["src"], e["dst"]]))
            elif e["dst"] == selected:
                sel_nbrs.add(e["src"])
                sel_edge_set.add(frozenset([e["src"], e["dst"]]))

    fig = go.Figure()

    # ── Regular links ─────────────────────────────────────────────────────────
    lx, ly = [], []
    hx, hy = [], []  # highlighted links
    for e in edges:
        pair = frozenset([e["src"], e["dst"]])
        if pair in sel_edge_set:
            hx += [e["x0"], e["x1"], None]
            hy += [e["y0"], e["y1"], None]
        else:
            lx += [e["x0"], e["x1"], None]
            ly += [e["y0"], e["y1"], None]

    fig.add_trace(
        go.Scatter(
            x=lx,
            y=ly,
            mode="lines",
            line=dict(color=C_LINK, width=0.8),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    if hx:
        fig.add_trace(
            go.Scatter(
                x=hx,
                y=hy,
                mode="lines",
                line=dict(color="#e67e22", width=2.0),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # ── Layer label annotations (left margin) ─────────────────────────────────
    depth_layers = stats["depth"]
    label_x = -0.6

    def add_label(y_val: float, text: str):
        fig.add_annotation(
            x=label_x,
            y=y_val,
            text=text,
            showarrow=False,
            xanchor="right",
            font=dict(size=10, color=C_LABEL, family="monospace"),
            xref="x",
            yref="y",
        )

    add_label(depth * Y_LAYER, "Servers")
    add_label(-depth * Y_LAYER, "Servers")
    layer_display = ["Edge", "Aggregation", "Core", "Super-Core"]
    for fc in range(1, depth):
        lname_d = layer_display[min(depth - 1 - fc, len(layer_display) - 1)]
        if fc == depth - 1:
            lname_d = "Edge"
        add_label(fc * Y_LAYER, lname_d)
        add_label(-fc * Y_LAYER, lname_d)
    add_label(0, "Core")

    # ── Nodes ─────────────────────────────────────────────────────────────────
    # Group nodes by (kind, layer) for batched traces
    groups: dict[str, list] = {}
    for n in nodes:
        gk = n["layer"]
        groups.setdefault(gk, []).append(n)

    layer_order = ["host", "edge", "agg", "mid", "mid2", "core"]

    for gk in layer_order:
        ns = groups.get(gk, [])
        if not ns:
            continue

        is_host = gk == "host"
        symbol = "circle" if is_host else "square"
        base_col = C_HOST_FILL if is_host else C_SW_FILL
        base_line = C_HOST_LINE if is_host else C_SW_LINE
        base_sz = HOST_SZ if is_host else SW_SZ
        lname_disp = {
            "host": "Servers",
            "edge": "Edge switches",
            "agg": "Aggregation switches",
            "core": "Core switches",
            "mid": "Middle switches",
            "mid2": "Mid-2 switches",
        }.get(gk, gk)

        colors, sizes, lines, lwidths = [], [], [], []
        for n in ns:
            nid = n["id"]
            if nid == selected:
                colors.append("#e67e22")
                sizes.append(base_sz + 5)
                lines.append("#c0392b")
                lwidths.append(2.0)
            elif nid in sel_nbrs:
                colors.append("#f39c12")
                sizes.append(base_sz + 3)
                lines.append("#e67e22")
                lwidths.append(1.5)
            else:
                colors.append(base_col)
                sizes.append(base_sz)
                lines.append(base_line)
                lwidths.append(0.8)

        hover = [f"<b>{n['id']}</b><br>{lname_disp}" for n in ns]

        fig.add_trace(
            go.Scatter(
                x=[n["x"] for n in ns],
                y=[n["y"] for n in ns],
                mode="markers",
                marker=dict(
                    symbol=symbol,
                    color=colors,
                    size=sizes,
                    line=dict(color=lines, width=lwidths),
                ),
                customdata=[(n["id"], lname_disp) for n in ns],
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
                name=lname_disp,
                legendgroup=gk,
                showlegend=True,
            )
        )

    # ── Figure layout ─────────────────────────────────────────────────────────
    y_range = depth * Y_LAYER
    fig.update_layout(
        paper_bgcolor=C_BG,
        plot_bgcolor=C_BG,
        font=dict(family="'Inter','Segoe UI',monospace", color=C_TEXT),
        margin=dict(l=65, r=10, t=10, b=10),
        xaxis=dict(
            visible=False,
            range=[-1.2, total_w + 0.5],
            fixedrange=False,
        ),
        yaxis=dict(
            visible=False,
            range=[-(y_range + Y_LAYER * 0.8), y_range + Y_LAYER * 0.8],
            fixedrange=False,
            scaleanchor=None,
        ),
        legend=dict(
            bgcolor=C_PANEL,
            bordercolor="#cccccc",
            borderwidth=1,
            font=dict(size=11, color=C_TEXT),
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            itemclick="toggle",
        ),
        hovermode="closest",
        dragmode="pan",
        uirevision=f"{depth}-{k}",
    )

    return fig, stats


# ═════════════════════════════════════════════════════════════════════════════
#  DASH APP
# ═════════════════════════════════════════════════════════════════════════════

app = Dash(
    __name__,
    title="Fat Tree Visualizer",
    meta_tags=[{"name": "viewport", "content": "width=device-width,initial-scale=1"}],
)

# ── Shared component styles ───────────────────────────────────────────────────
PANEL_W = "220px"

ROW_S = dict(
    display="flex",
    alignItems="center",
    justifyContent="space-between",
    padding="5px 0",
    borderBottom="1px solid #d8d8d8",
)
LABEL_S = dict(fontSize="13px", color="#555", fontFamily="Arial, sans-serif", textAlign="right", paddingRight="6px")
VAL_S = dict(fontSize="13px", color=C_STAT, fontFamily="Arial, sans-serif", fontWeight="normal", minWidth="40px")
INPUT_S = dict(
    width="52px",
    textAlign="left",
    border="1px solid #aaa",
    borderRadius="2px",
    padding="2px 4px",
    fontSize="13px",
    fontFamily="Arial, sans-serif",
    color=C_TEXT,
    outline="none",
    background="#fff",
)
BTN_S = dict(
    background="#e8e8e8",
    border="1px solid #aaa",
    borderRadius="2px",
    color=C_TEXT,
    width="20px",
    height="22px",
    cursor="pointer",
    fontSize="13px",
    lineHeight="1",
    padding="0",
    display="flex",
    alignItems="center",
    justifyContent="center",
)


def stat_row(label: str, val_id: str):
    return html.Tr(
        [
            html.Td(
                label,
                style={
                    **LABEL_S,
                    "textAlign": "right",
                    "paddingRight": "8px",
                    "paddingTop": "3px",
                    "paddingBottom": "3px",
                },
            ),
            html.Td(html.Span(id=val_id, style=VAL_S)),
        ]
    )


def input_row(label: str, inp_id: str, dec_id: str, inc_id: str, init: int, lo: int, hi: int, step: int = 1):
    return html.Tr(
        [
            html.Td(
                label,
                style={
                    **LABEL_S,
                    "textAlign": "right",
                    "paddingRight": "8px",
                    "paddingTop": "3px",
                    "paddingBottom": "3px",
                },
            ),
            html.Td(
                html.Div(
                    style=dict(display="flex", alignItems="center", gap="2px"),
                    children=[
                        dcc.Input(
                            id=inp_id,
                            type="number",
                            value=init,
                            min=lo,
                            max=hi,
                            step=step,
                            debounce=True,
                            style=INPUT_S,
                        ),
                    ],
                )
            ),
        ]
    )


app.layout = html.Div(
    style=dict(display="flex", height="100vh", fontFamily="Arial, sans-serif", background="#e8e8e8"),
    children=[
        # ── Left panel ────────────────────────────────────────────────────────
        html.Div(
            style=dict(
                width=PANEL_W,
                flexShrink=0,
                background=C_PANEL,
                padding="16px 14px 16px 14px",
                overflowY="auto",
                display="flex",
                flexDirection="column",
                borderRight="1px solid #ccc",
            ),
            children=[
                # Input table
                html.Table(
                    style=dict(borderCollapse="collapse", width="100%", marginBottom="6px"),
                    children=[
                        html.Tbody(
                            [
                                input_row("Tree Depth", "depth-in", "depth-dec", "depth-inc", 3, 1, 4),
                                input_row("Ports per Switch", "ports-in", "ports-dec", "ports-inc", 4, 2, 16, 2),
                            ]
                        )
                    ],
                ),
                # Divider
                html.Hr(style=dict(border="none", borderTop="1px solid #ccc", margin="6px 0")),
                # Stats table
                html.Table(
                    style=dict(borderCollapse="collapse", width="100%", marginBottom="6px"),
                    children=[
                        html.Tbody(
                            [
                                stat_row("Hosts", "stat-hosts"),
                                stat_row("Switches", "stat-switches"),
                                stat_row("Cables", "stat-cables"),
                                stat_row("Transmitters", "stat-tx"),
                                stat_row("Switch Tx's", "stat-swtx"),
                            ]
                        )
                    ],
                ),
                html.Hr(style=dict(border="none", borderTop="1px solid #ccc", margin="6px 0")),
                # Attribution (matches original)
                html.Div(
                    [
                        html.Div("Fat Tree Visualizer", style=dict(fontSize="12px", color="#888", textAlign="center")),
                        html.Div(
                            [
                                html.Span("by ", style=dict(fontSize="12px", color="#888")),
                                html.A(
                                    'He "Lonnie" Liu',
                                    href="http://cseweb.ucsd.edu/~h8liu",
                                    target="_blank",
                                    style=dict(fontSize="12px", color="#4a90d9", textDecoration="none"),
                                ),
                            ],
                            style=dict(textAlign="center"),
                        ),
                    ],
                    style=dict(marginTop="8px"),
                ),
                html.Div(style=dict(flex="1")),
                # Selected node info
                html.Div(
                    id="sel-info", style=dict(fontSize="11px", color="#888", textAlign="center", marginTop="12px")
                ),
            ],
        ),
        # ── Canvas ────────────────────────────────────────────────────────────
        html.Div(
            style=dict(flex="1", minWidth=0, background=C_BG),
            children=[
                dcc.Graph(
                    id="ftree-graph",
                    style=dict(width="100%", height="100%"),
                    config=dict(
                        scrollZoom=True,
                        displayModeBar=True,
                        modeBarButtonsToRemove=["select2d", "lasso2d", "autoScale2d"],
                        displaylogo=False,
                        toImageButtonOptions=dict(format="png", filename="fattree", scale=2),
                    ),
                    clear_on_unhover=True,
                ),
            ],
        ),
        # State
        dcc.Store(id="sel-store", data=None),
    ],
)

# ── CSS ───────────────────────────────────────────────────────────────────────
app.index_string = """<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { overflow: hidden; font-family: Arial, sans-serif; }
        input[type=number] { -moz-appearance: textfield; }
        input[type=number]::-webkit-outer-spin-button,
        input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: #bbb; border-radius: 2px; }
        a:hover { text-decoration: underline !important; }
        .modebar-container { top: 2px !important; right: 4px !important; }
        .modebar { background: rgba(255,255,255,0.85) !important; }
    </style>
</head>
<body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


# ═════════════════════════════════════════════════════════════════════════════
#  CALLBACKS
# ═════════════════════════════════════════════════════════════════════════════


@app.callback(
    Output("depth-in", "value"),
    Input("depth-dec", "n_clicks"),
    Input("depth-inc", "n_clicks"),
    State("depth-in", "value"),
    prevent_initial_call=True,
)
def step_depth(_, __, v):
    t = callback_context.triggered[0]["prop_id"]
    return max(1, int(v or 3) - 1) if "dec" in t else min(4, int(v or 3) + 1)


@app.callback(
    Output("ports-in", "value"),
    Input("ports-dec", "n_clicks"),
    Input("ports-inc", "n_clicks"),
    State("ports-in", "value"),
    prevent_initial_call=True,
)
def step_ports(_, __, v):
    t = callback_context.triggered[0]["prop_id"]
    val = int(v or 4)
    return max(2, val - 2) if "dec" in t else min(16, val + 2)


@app.callback(
    Output("ftree-graph", "figure"),
    Output("stat-hosts", "children"),
    Output("stat-switches", "children"),
    Output("stat-cables", "children"),
    Output("stat-tx", "children"),
    Output("stat-swtx", "children"),
    Output("sel-store", "data"),
    Output("sel-info", "children"),
    Input("depth-in", "value"),
    Input("ports-in", "value"),
    Input("ftree-graph", "clickData"),
    State("sel-store", "data"),
    prevent_initial_call=False,
)
def update(depth_v, ports_v, click_data, sel):
    trig = callback_context.triggered[0]["prop_id"] if callback_context.triggered else ""

    # Parse & clamp
    try:
        depth = max(1, min(4, int(depth_v))) if depth_v is not None else 3
    except (ValueError, TypeError):
        depth = 3
    try:
        k = max(2, int(ports_v)) if ports_v is not None else 4
        if k % 2 != 0:
            k += 1
        k = min(k, 16)
    except (ValueError, TypeError):
        k = 4

    # Reset selection on param change
    if "depth-in" in trig or "ports-in" in trig:
        sel = None

    # Handle node click
    if "clickData" in trig and click_data:
        pts = click_data.get("points", [])
        if pts:
            cd = pts[0].get("customdata")
            if cd:
                nid = cd[0]
                sel = None if nid == sel else nid

    try:
        fig, stats = build_figure(depth, k, sel)
    except Exception as ex:
        empty = go.Figure()
        empty.update_layout(
            paper_bgcolor=C_BG,
            plot_bgcolor=C_BG,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[
                dict(
                    text=f"Error: {ex}",
                    showarrow=False,
                    font=dict(size=13, color="red"),
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                )
            ],
        )
        return (empty, "—", "—", "—", "—", "—", None, str(ex))

    sel_info = f"Selected: {sel} — click again to deselect" if sel else "Click a node to select it"

    return (
        fig,
        str(stats["hosts"]),
        str(stats["switches"]),
        str(stats["cables"]),
        str(stats["transmitters"]),
        str(stats["switch_txs"]),
        sel,
        sel_info,
    )


# ── Remove the ± buttons (they referenced ids that don't exist in layout)
# The inputs already have type=number with browser built-in steppers
# (hidden via CSS, user types directly or we add callbacks below)

# Add hidden ± button divs to satisfy callback (they're not shown but IDs must exist)
app.layout.children.append(
    html.Div(
        [
            html.Button(id="depth-dec", n_clicks=0, style=dict(display="none")),
            html.Button(id="depth-inc", n_clicks=0, style=dict(display="none")),
            html.Button(id="ports-dec", n_clicks=0, style=dict(display="none")),
            html.Button(id="ports-inc", n_clicks=0, style=dict(display="none")),
        ]
    )
)

# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║         Fat Tree Visualizer  — Dash + Plotly    ║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  Open your browser at  http://127.0.0.1:8050    ║")
    print("╚══════════════════════════════════════════════════╝")
    app.run(debug=False, host="127.0.0.1", port=8050)
