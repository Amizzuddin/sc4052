################################################################################
#  Filename:      two/app.py                                                   #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, February 27th 2026, 3:12:58 am                       #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Tuesday March 10th 2026 3:10:15 am                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
PageRank Explorer — Unified Dash Web Application
=================================================
Integrates three modules into one interactive dashboard:

  Tab 1 · PageRank Engine
          Load web-Google_10k.txt (or any edge-list), run power-method
          PageRank, vary the teleportation probability p, see top-k ranked
          nodes, and compare against the closed-form solution.

  Tab 2 · AI Crawler Prioritisation
          Enter a small web graph (URLs + outlinks) and PageRank scores,
          then visualise which pages a GPTBot-style crawler should visit
          first, respecting robots.txt rules.

  Tab 3 · GraphRAG Knowledge Retrieval (Disable)
          Build a knowledge graph from entity–relation–entity triples,
          set seed query entities, run Personalised PageRank, and see
          which nodes are most relevant to a multi-hop query.

Installation (one-time):
    pip install dash dash-cytoscape plotly pandas numpy scipy

Run:
    python app.py
    Open http://127.0.0.1:8050 in your browser.
"""

import base64

# ─── Standard library ────────────────────────────────────────────────────────
from collections import defaultdict
from typing import Any

# ─── Dash ────────────────────────────────────────────────────────────────────
import dash
import dash_cytoscape as cyto
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import scipy.sparse as sp
from dash import Input, Output, State, ctx, dash_table, dcc, html

# ─── Scientific stack ────────────────────────────────────────────────────────
from exceptiongroup import suppress

cyto.load_extra_layouts()

# ═════════════════════════════════════════════════════════════════════════════
# CORE ALGORITHMS  (self-contained, no external files required for tabs 2 & 3)
# ═════════════════════════════════════════════════════════════════════════════

# ── Shared graph loader ──────────────────────────────────────────────────────


def load_edge_list(text: str) -> tuple[list[tuple[int, int]], list[int], dict[int, int]]:
    """Parse tab/space-separated edge list, skip # comments."""
    edges, nodes = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                u, v = int(parts[0]), int(parts[1])
                edges.append((u, v))
                nodes.update([u, v])
            except ValueError:
                pass
    node_ids = sorted(nodes)
    id2idx = {nid: i for i, nid in enumerate(node_ids)}
    return edges, node_ids, id2idx


def build_sparse_H(
    edges: list[tuple[int, int]], node_ids: list[int], id2idx: dict[int, int]
) -> tuple[sp.csc_matrix, np.ndarray]:
    n = len(node_ids)
    out_deg: dict[int, int] = defaultdict(int)
    for u, _ in edges:
        out_deg[id2idx[u]] += 1
    rows, cols, data = [], [], []
    for u, v in edges:
        ui, vi = id2idx[u], id2idx[v]
        if out_deg[ui] > 0:
            rows.append(vi)
            cols.append(ui)
            data.append(1.0 / out_deg[ui])
    H = sp.csc_matrix((data, (rows, cols)), shape=(n, n))
    dangling = np.array([out_deg[i] == 0 for i in range(n)])
    return H, dangling


def pagerank_power(
    H: sp.csc_matrix, dangling: np.ndarray, p: float = 0.15, tol: float = 1e-10, max_iter: int = 500
) -> tuple[np.ndarray, int, list[float]]:
    n = H.shape[0]
    rank = np.full(n, 1.0 / n)
    teleport = np.full(n, p / n)
    history = []
    for _it in range(1, max_iter + 1):
        dm = rank[dangling].sum()
        new_rank = (1 - p) * H.dot(rank) + (1 - p) * dm / n + teleport
        delta = np.abs(new_rank - rank).sum()
        history.append(delta)
        rank = new_rank
        if delta < tol:
            break
    return rank, _it, history


def pagerank_closed_form(M_dense: np.ndarray, p: float = 0.15) -> np.ndarray:
    n = M_dense.shape[0]
    A = np.eye(n) - (1 - p) * M_dense
    pi = np.linalg.solve(A, np.ones(n)) * (p / n)
    return pi / pi.sum()


# ── Personalised PageRank (GraphRAG) ─────────────────────────────────────────


def build_dense_M(nodes: list[str], adj: dict[str, list[str]]) -> np.ndarray:
    n = len(nodes)
    idx = {nd: i for i, nd in enumerate(nodes)}
    M = np.zeros((n, n))
    for nd in nodes:
        outs = adj.get(nd, [])
        if outs:
            for t in outs:
                if t in idx:
                    M[idx[t], idx[nd]] += 1.0 / len(outs)
        else:
            M[:, idx[nd]] = 1.0 / n
    return M


def ppr(M: np.ndarray, nodes: list[str], seeds: list[str], p: float = 0.25) -> dict[str, float]:
    n = len(nodes)
    idx = {nd: i for i, nd in enumerate(nodes)}
    v = np.zeros(n)
    ok = [s for s in seeds if s in idx]
    if ok:
        for s in ok:
            v[idx[s]] = 1.0 / len(ok)
    else:
        v = np.full(n, 1.0 / n)
    A = np.eye(n) - (1 - p) * M
    pi = np.linalg.solve(A, p * v)
    pi = np.maximum(pi, 0)
    pi /= pi.sum()
    return {nd: float(pi[i]) for i, nd in enumerate(nodes)}


# ═════════════════════════════════════════════════════════════════════════════
# DEMO DATA
# ═════════════════════════════════════════════════════════════════════════════

DEMO_CRAWLER_GRAPH = """\
https://ai.example.com -> https://research.example.com, https://docs.example.com
https://news.example.com -> https://ai.example.com, https://social.example.com
https://shop.example.com -> https://news.example.com
https://blog.example.com -> https://ai.example.com, https://research.example.com
https://docs.example.com -> https://ai.example.com
https://social.example.com -> https://news.example.com, https://shop.example.com
https://research.example.com -> https://ai.example.com, https://docs.example.com, https://blog.example.com
https://forum.example.com -> https://ai.example.com, https://blog.example.com
"""

DEMO_CRAWLER_PR = """\
https://ai.example.com = 0.312
https://news.example.com = 0.095
https://shop.example.com = 0.041
https://blog.example.com = 0.098
https://docs.example.com = 0.145
https://social.example.com = 0.062
https://research.example.com = 0.198
https://forum.example.com = 0.049
"""

DEMO_CRAWLER_ROBOTS = """\
https://shop.example.com = deny
https://social.example.com = deny
"""

DEMO_KG_TRIPLES = """\
Marie Curie | discovered | polonium
Marie Curie | discovered | radium
Marie Curie | pioneered | radioactivity research
radium | emits | ionizing radiation
polonium | emits | ionizing radiation
ionizing radiation | used in | radiotherapy
ionizing radiation | enables | X-ray imaging
radioactivity research | led to | nuclear medicine
nuclear medicine | branch of | medical imaging
radiotherapy | treats | cancer
radiotherapy | part of | medical imaging
X-ray imaging | type of | medical imaging
nuclear medicine | uses | radioactive tracers
radioactive tracers | derived from | radium
radioactive tracers | used in | PET scan
PET scan | type of | medical imaging
CT scan | type of | medical imaging
CT scan | uses | X-ray imaging
medical imaging | revolutionised | diagnostics
diagnostics | improves | cancer treatment
cancer treatment | includes | radiotherapy
"""

DEMO_KG_SEEDS = "Marie Curie, medical imaging"

# ═════════════════════════════════════════════════════════════════════════════
# COLOUR PALETTE & SHARED STYLES
# ═════════════════════════════════════════════════════════════════════════════

C = {
    "bg": "#0D1117",
    "surface": "#161B22",
    "card": "#1C2128",
    "border": "#30363D",
    "accent": "#58A6FF",
    "accent2": "#3FB950",
    "accent3": "#FF7B72",
    "accent4": "#D2A8FF",
    "text": "#E6EDF3",
    "muted": "#8B949E",
    "highlight": "#F0883E",
}

FONT = "'JetBrains Mono', 'Fira Code', monospace"
BODY_FONT = "'Inter', 'Segoe UI', sans-serif"


def card(children: list[html.Div], style: dict | None = None) -> html.Div:
    base = {
        "background": C["card"],
        "border": f"1px solid {C['border']}",
        "borderRadius": "12px",
        "padding": "24px",
        "marginBottom": "20px",
    }
    if style:
        base.update(style)
    return html.Div(children, style=base)


def label(text: str) -> html.Label:
    return html.Label(
        text,
        style={
            "color": C["muted"],
            "fontSize": "11px",
            "fontWeight": "600",
            "letterSpacing": "0.08em",
            "textTransform": "uppercase",
            "fontFamily": BODY_FONT,
            "marginBottom": "6px",
            "display": "block",
        },
    )


def stat_box(title: str, value: str, color: str | None = None) -> html.Div:
    return html.Div(
        [
            html.Div(
                value,
                style={
                    "fontSize": "28px",
                    "fontWeight": "700",
                    "fontFamily": FONT,
                    "color": color or C["accent"],
                    "lineHeight": "1",
                },
            ),
            html.Div(
                title,
                style={
                    "fontSize": "11px",
                    "color": C["muted"],
                    "marginTop": "4px",
                    "fontFamily": BODY_FONT,
                    "textTransform": "uppercase",
                    "letterSpacing": "0.06em",
                },
            ),
        ],
        style={
            "background": C["surface"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "8px",
            "padding": "16px 20px",
            "flex": "1",
            "minWidth": "120px",
        },
    )


INPUT_STYLE = {
    "width": "100%",
    "background": C["surface"],
    "border": f"1px solid {C['border']}",
    "borderRadius": "8px",
    "color": C["text"],
    "fontFamily": FONT,
    "fontSize": "13px",
    "padding": "8px 12px",
    "boxSizing": "border-box",
    "outline": "none",
}

TEXTAREA_STYLE = {**INPUT_STYLE, "resize": "vertical", "minHeight": "120px"}

BUTTON_STYLE = {
    "background": C["accent"],
    "color": "#0D1117",
    "border": "none",
    "borderRadius": "8px",
    "padding": "10px 24px",
    "fontWeight": "700",
    "fontFamily": BODY_FONT,
    "fontSize": "13px",
    "cursor": "pointer",
    "letterSpacing": "0.04em",
}

TABLE_STYLE = {
    "style_table": {"overflowX": "auto", "borderRadius": "8px", "border": f"1px solid {C['border']}"},
    "style_header": {
        "backgroundColor": C["surface"],
        "color": C["accent"],
        "fontFamily": BODY_FONT,
        "fontWeight": "600",
        "fontSize": "12px",
        "borderBottom": f"1px solid {C['border']}",
        "textTransform": "uppercase",
        "letterSpacing": "0.06em",
    },
    "style_cell": {
        "backgroundColor": C["card"],
        "color": C["text"],
        "fontFamily": FONT,
        "fontSize": "12px",
        "border": f"1px solid {C['border']}",
        "padding": "10px 14px",
    },
    "style_data_conditional": [
        {"if": {"row_index": "odd"}, "backgroundColor": C["surface"]},
        {"if": {"row_index": 0}, "color": C["highlight"], "fontWeight": "700"},
    ],
}

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — PageRank Engine
# ═════════════════════════════════════════════════════════════════════════════


def _upload_zone(
    zone_id: str, status_id: str, btn_id: str, card_id: str, title: str, subtitle: str, icon: str
) -> html.Div:
    """Reusable drop zone card for a single dataset."""
    return html.Div(
        [
            # Title row
            html.Div(
                [
                    html.Span(icon + "  ", style={"fontSize": "18px"}),
                    html.Div(
                        [
                            html.Div(
                                title,
                                style={
                                    "color": C["text"],
                                    "fontFamily": BODY_FONT,
                                    "fontWeight": "600",
                                    "fontSize": "14px",
                                },
                            ),
                            html.Div(
                                subtitle,
                                style={
                                    "color": C["muted"],
                                    "fontFamily": BODY_FONT,
                                    "fontSize": "11px",
                                    "marginTop": "2px",
                                },
                            ),
                        ]
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "4px", "marginBottom": "10px"},
            ),
            # Drop zone
            dcc.Upload(
                id=zone_id,
                multiple=False,
                children=html.Div(
                    [
                        html.Div("📂", style={"fontSize": "28px", "marginBottom": "6px"}),
                        html.Div(
                            [
                                html.Span("Drag & drop  ", style={"color": C["muted"], "fontSize": "12px"}),
                                html.Span(
                                    "or click to browse",
                                    style={"color": C["accent"], "fontSize": "12px", "cursor": "pointer"},
                                ),
                            ]
                        ),
                        html.Div(
                            "Accepts .txt or .gz",
                            style={
                                "color": C["muted"],
                                "fontSize": "10px",
                                "marginTop": "4px",
                                "fontFamily": FONT,
                            },
                        ),
                    ],
                    style={"textAlign": "center", "fontFamily": BODY_FONT},
                ),
                style={
                    "border": f"2px dashed {C['border']}",
                    "borderRadius": "10px",
                    "padding": "24px 16px",
                    "cursor": "pointer",
                    "background": C["surface"],
                    "transition": "all 0.2s",
                },
            ),
            # Status badge + Set-as-Active button row
            html.Div(
                [
                    html.Div(id=status_id, style={"flex": "1", "minHeight": "34px"}),
                    html.Button(
                        "☑  Set as Active",
                        id=btn_id,
                        n_clicks=0,
                        style={
                            "display": "none",
                            "background": "transparent",
                            "border": f"1px solid {C['accent']}",
                            "color": C["accent"],
                            "borderRadius": "6px",
                            "padding": "5px 12px",
                            "fontFamily": BODY_FONT,
                            "fontSize": "11px",
                            "fontWeight": "600",
                            "cursor": "pointer",
                            "marginLeft": "8px",
                            "whiteSpace": "nowrap",
                            "flexShrink": "0",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "marginTop": "8px"},
            ),
        ],
        id=card_id,
        style={
            "flex": "1",
            "border": f"1px solid {C['border']}",
            "borderRadius": "12px",
            "padding": "18px",
            "background": C["card"],
            "transition": "border-color 0.2s",
        },
    )


tab1_layout = html.Div(
    [
        # ── Dataset upload row ──
        html.Div(
            [
                label("Step 1 — Drop a dataset file  (only the most recently loaded file will be analysed)"),
            ],
            style={"marginBottom": "10px"},
        ),
        html.Div(
            [
                _upload_zone(
                    zone_id="t1-upload-10k",
                    status_id="t1-status-10k",
                    btn_id="t1-set-10k",
                    card_id="t1-card-10k",
                    title="web-Google_10k.txt",
                    subtitle="10,000 nodes · 78,323 edges · fast (~0.1 s)",
                    icon="⚡",
                ),
                html.Div(style={"width": "16px"}),
                _upload_zone(
                    zone_id="t1-upload-full",
                    status_id="t1-status-full",
                    btn_id="t1-set-full",
                    card_id="t1-card-full",
                    title="web-Google.txt  /  web-Google.txt.gz",
                    subtitle="875,713 nodes · 5,105,039 edges · ~30–60 s",
                    icon="🌐",
                ),
            ],
            style={"display": "flex", "marginBottom": "16px"},
        ),
        # ── Active-file banner ──
        html.Div(id="t1-active-banner", style={"marginBottom": "16px"}),
        # ── Sliders + run ──
        card(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                label("Teleportation probability p"),
                                dcc.Slider(
                                    id="t1-p",
                                    min=0.01,
                                    max=0.99,
                                    step=0.01,
                                    value=0.15,
                                    marks={
                                        v: {"label": str(v), "style": {"color": C["muted"], "fontSize": "10px"}}
                                        for v in [0.01, 0.15, 0.30, 0.50, 0.85, 0.99]
                                    },
                                    tooltip={"placement": "bottom", "always_visible": True},
                                ),
                            ],
                            style={"flex": "1", "marginRight": "32px"},
                        ),
                        html.Div(
                            [
                                label("Top-k nodes to display"),
                                dcc.Slider(
                                    id="t1-k",
                                    min=5,
                                    max=50,
                                    step=5,
                                    value=20,
                                    marks={
                                        v: {"label": str(v), "style": {"color": C["muted"], "fontSize": "10px"}}
                                        for v in [5, 10, 20, 30, 50]
                                    },
                                    tooltip={"placement": "bottom", "always_visible": True},
                                ),
                            ],
                            style={"flex": "1", "marginRight": "32px"},
                        ),
                        html.Div(
                            [
                                html.Div(style={"height": "20px"}),
                                html.Button("▶  Run PageRank", id="t1-run", style=BUTTON_STYLE),
                            ],
                            style={"flexShrink": "0"},
                        ),
                    ],
                    style={"display": "flex", "alignItems": "flex-end", "gap": "0"},
                ),
            ]
        ),
        # ── Loading wrapper covers all results below ──
        dcc.Loading(
            id="t1-loading",
            type="circle",
            color=C["accent"],
            # Custom overlay so we can show the filename being processed
            overlay_style={"visibility": "visible", "filter": "blur(1px)"},
            children=[
                # Processing message (shown by run callback before results arrive)
                html.Div(id="t1-processing-msg", style={"marginBottom": "8px"}),
                # ── Stats row ──
                html.Div(
                    id="t1-stats", style={"display": "flex", "gap": "12px", "marginBottom": "20px", "flexWrap": "wrap"}
                ),
                # ── Charts ──
                html.Div(
                    [
                        html.Div(
                            [
                                card(
                                    [
                                        html.H4(
                                            "Top-k PageRank Scores",
                                            style={
                                                "color": C["text"],
                                                "fontFamily": BODY_FONT,
                                                "marginBottom": "12px",
                                                "marginTop": "0",
                                            },
                                        ),
                                        dcc.Graph(
                                            id="t1-bar", style={"height": "340px"}, config={"displayModeBar": False}
                                        ),
                                    ],
                                    style={"flex": "1", "marginRight": "10px"},
                                ),
                            ],
                            style={"flex": "1"},
                        ),
                        html.Div(
                            [
                                card(
                                    [
                                        html.H4(
                                            "Convergence (L1 delta per iteration)",
                                            style={
                                                "color": C["text"],
                                                "fontFamily": BODY_FONT,
                                                "marginBottom": "12px",
                                                "marginTop": "0",
                                            },
                                        ),
                                        dcc.Graph(
                                            id="t1-conv", style={"height": "340px"}, config={"displayModeBar": False}
                                        ),
                                    ]
                                ),
                            ],
                            style={"flex": "1"},
                        ),
                    ],
                    style={"display": "flex", "gap": "0"},
                ),
                # ── Closed-form comparison ──
                card(
                    [
                        html.H4(
                            "Iterative vs Closed-Form Comparison (sampled subgraph)",
                            style={
                                "color": C["text"],
                                "fontFamily": BODY_FONT,
                                "marginBottom": "12px",
                                "marginTop": "0",
                            },
                        ),
                        html.Div(id="t1-cf-stats", style={"display": "flex", "gap": "12px", "marginBottom": "16px"}),
                        dcc.Graph(id="t1-scatter", style={"height": "300px"}, config={"displayModeBar": False}),
                    ]
                ),
                # ── Data table ──
                card(
                    [
                        html.H4(
                            "Full Rankings Table",
                            style={
                                "color": C["text"],
                                "fontFamily": BODY_FONT,
                                "marginBottom": "12px",
                                "marginTop": "0",
                            },
                        ),
                        html.Div(id="t1-table"),
                    ]
                ),
            ],
        ),
        dcc.Store(id="t1-store"),
        dcc.Store(id="t1-active-file"),  # holds {source, contents, filename}
    ]
)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — AI Crawler Prioritisation
# ═════════════════════════════════════════════════════════════════════════════

tab2_layout = html.Div(
    [
        html.Div(
            [
                # ── Left: inputs ──
                html.Div(
                    [
                        card(
                            [
                                html.H4(
                                    "Web Graph (URL → outlinks)",
                                    style={
                                        "color": C["text"],
                                        "fontFamily": BODY_FONT,
                                        "marginBottom": "8px",
                                        "marginTop": "0",
                                    },
                                ),
                                label("Format: url -> target1, target2  (one per line)"),
                                dcc.Textarea(id="t2-graph", value=DEMO_CRAWLER_GRAPH, style=TEXTAREA_STYLE),
                            ]
                        ),
                        card(
                            [
                                html.H4(
                                    "PageRank Scores",
                                    style={
                                        "color": C["text"],
                                        "fontFamily": BODY_FONT,
                                        "marginBottom": "8px",
                                        "marginTop": "0",
                                    },
                                ),
                                label("Format: url = score  (one per line)"),
                                dcc.Textarea(
                                    id="t2-pr", value=DEMO_CRAWLER_PR, style={**TEXTAREA_STYLE, "minHeight": "80px"}
                                ),
                            ]
                        ),
                        card(
                            [
                                html.H4(
                                    "Robots.txt Deny List",
                                    style={
                                        "color": C["text"],
                                        "fontFamily": BODY_FONT,
                                        "marginBottom": "8px",
                                        "marginTop": "0",
                                    },
                                ),
                                label("Format: url = deny  (one per line)"),
                                dcc.Textarea(
                                    id="t2-robots",
                                    value=DEMO_CRAWLER_ROBOTS,
                                    style={**TEXTAREA_STYLE, "minHeight": "60px"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        label("α — Own PageRank weight"),
                                        dcc.Slider(
                                            id="t2-alpha",
                                            min=0,
                                            max=1,
                                            step=0.05,
                                            value=0.70,
                                            tooltip={"placement": "bottom", "always_visible": True},
                                        ),
                                    ],
                                    style={"flex": "1", "marginRight": "16px"},
                                ),
                                html.Div(
                                    [
                                        label("β — Neighbour PR weight"),
                                        dcc.Slider(
                                            id="t2-beta",
                                            min=0,
                                            max=1,
                                            step=0.05,
                                            value=0.20,
                                            tooltip={"placement": "bottom", "always_visible": True},
                                        ),
                                    ],
                                    style={"flex": "1"},
                                ),
                            ],
                            style={"display": "flex", "gap": "0", "marginBottom": "16px"},
                        ),
                        html.Button("▶  Compute Crawl Priority", id="t2-run", style=BUTTON_STYLE),
                    ],
                    style={"flex": "1", "marginRight": "20px"},
                ),
                # ── Right: outputs ──
                html.Div(
                    [
                        card(
                            [
                                html.H4(
                                    "Crawl-Quality Score Ranking",
                                    style={
                                        "color": C["text"],
                                        "fontFamily": BODY_FONT,
                                        "marginBottom": "12px",
                                        "marginTop": "0",
                                    },
                                ),
                                dcc.Graph(id="t2-bar", style={"height": "320px"}, config={"displayModeBar": False}),
                            ]
                        ),
                        card(
                            [
                                html.H4(
                                    "Graph Visualisation",
                                    style={
                                        "color": C["text"],
                                        "fontFamily": BODY_FONT,
                                        "marginBottom": "8px",
                                        "marginTop": "0",
                                    },
                                ),
                                html.Div(
                                    "Node size = PageRank · colour = crawl status",
                                    style={
                                        "color": C["muted"],
                                        "fontSize": "11px",
                                        "marginBottom": "8px",
                                        "fontFamily": BODY_FONT,
                                    },
                                ),
                                cyto.Cytoscape(
                                    id="t2-cyto",
                                    layout={"name": "cose", "randomize": False, "nodeRepulsion": 8000},
                                    style={"width": "100%", "height": "360px"},
                                    stylesheet=[
                                        {
                                            "selector": "node",
                                            "style": {
                                                "label": "data(label)",
                                                "font-size": "10px",
                                                "color": C["text"],
                                                "text-wrap": "wrap",
                                                "text-max-width": "80px",
                                                "font-family": BODY_FONT,
                                                "background-color": "data(color)",
                                                "width": "data(size)",
                                                "height": "data(size)",
                                                "border-width": "2px",
                                                "border-color": C["border"],
                                            },
                                        },
                                        {
                                            "selector": "edge",
                                            "style": {
                                                "curve-style": "bezier",
                                                "target-arrow-shape": "triangle",
                                                "arrow-scale": 1.2,
                                                "line-color": C["border"],
                                                "target-arrow-color": C["border"],
                                                "width": 1.5,
                                                "opacity": 0.7,
                                            },
                                        },
                                    ],
                                ),
                                html.Div(id="t2-node-info", style={"marginTop": "8px", "minHeight": "32px"}),
                            ]
                        ),
                        html.Div(id="t2-table"),
                    ],
                    style={"flex": "1.4"},
                ),
            ],
            style={"display": "flex", "alignItems": "flex-start"},
        ),
    ]
)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — GraphRAG Knowledge Retrieval (Disable)
# ═════════════════════════════════════════════════════════════════════════════

# tab3_layout = html.Div(
#     [
#         html.Div(
#             [
#                 # ── Left: inputs ──
#                 html.Div(
#                     [
#                         card(
#                             [
#                                 html.H4(
#                                     "Knowledge Graph Triples",
#                                     style={
#                                         "color": C["text"],
#                                         "fontFamily": BODY_FONT,
#                                         "marginBottom": "8px",
#                                         "marginTop": "0",
#                                     },
#                                 ),
#                                 label("Format: entity | relation | entity  (one per line)"),
#                                 dcc.Textarea(
#                                     id="t3-triples",
#                                     value=DEMO_KG_TRIPLES,
#                                     style={**TEXTAREA_STYLE, "minHeight": "260px"},
#                                 ),
#                             ]
#                         ),
#                         card(
#                             [
#                                 html.H4(
#                                     "Query",
#                                     style={
#                                         "color": C["text"],
#                                         "fontFamily": BODY_FONT,
#                                         "marginBottom": "8px",
#                                         "marginTop": "0",
#                                     },
#                                 ),
#                                 label("Seed entities (comma-separated)"),
#                                 dcc.Input(id="t3-seeds", value=DEMO_KG_SEEDS, style=INPUT_STYLE),
#                                 html.Div(style={"height": "14px"}),
#                                 label("Teleportation probability p (query focus)"),
#                                 dcc.Slider(
#                                     id="t3-p",
#                                     min=0.05,
#                                     max=0.95,
#                                     step=0.05,
#                                     value=0.25,
#                                     marks={
#                                         v: {"label": str(v), "style": {"color": C["muted"], "fontSize": "10px"}}
#                                         for v in [0.05, 0.25, 0.50, 0.75, 0.95]
#                                     },
#                                     tooltip={"placement": "bottom", "always_visible": True},
#                                 ),
#                                 html.Div(style={"height": "14px"}),
#                                 label("Top-k nodes to retrieve"),
#                                 dcc.Slider(
#                                     id="t3-k",
#                                     min=3,
#                                     max=15,
#                                     step=1,
#                                     value=8,
#                                     marks={
#                                         v: {"label": str(v), "style": {"color": C["muted"], "fontSize": "10px"}}
#                                         for v in [3, 5, 8, 10, 15]
#                                     },
#                                     tooltip={"placement": "bottom", "always_visible": True},
#                                 ),
#                                 html.Div(style={"height": "14px"}),
#                                 html.Button("▶  Retrieve", id="t3-run", style=BUTTON_STYLE),
#                             ]
#                         ),
#                     ],
#                     style={"flex": "1", "marginRight": "20px"},
#                 ),
#                 # ── Right: outputs ──
#                 html.Div(
#                     [
#                         card(
#                             [
#                                 html.H4(
#                                     "Personalised PageRank Scores",
#                                     style={
#                                         "color": C["text"],
#                                         "fontFamily": BODY_FONT,
#                                         "marginBottom": "12px",
#                                         "marginTop": "0",
#                                     },
#                                 ),
#                                 dcc.Graph(id="t3-bar", style={"height": "280px"}, config={"displayModeBar": False}),
#                             ]
#                         ),
#                         card(
#                             [
#                                 html.H4(
#                                     "Knowledge Graph (hover node for relations)",
#                                     style={
#                                         "color": C["text"],
#                                         "fontFamily": BODY_FONT,
#                                         "marginBottom": "8px",
#                                         "marginTop": "0",
#                                     },
#                                 ),
#                                 cyto.Cytoscape(
#                                     id="t3-cyto",
#                                     layout={
#                                         "name": "cose",
#                                         "randomize": False,
#                                         "nodeRepulsion": 12000,
#                                         "idealEdgeLength": 80,
#                                     },
#                                     style={"width": "100%", "height": "380px"},
#                                     stylesheet=[
#                                         {
#                                             "selector": "node",
#                                             "style": {
#                                                 "label": "data(label)",
#                                                 "font-size": "9px",
#                                                 "color": C["text"],
#                                                 "text-wrap": "wrap",
#                                                 "text-max-width": "90px",
#                                                 "font-family": BODY_FONT,
#                                                 "background-color": "data(color)",
#                                                 "width": "data(size)",
#                                                 "height": "data(size)",
#                                                 "border-width": "2px",
#                                                 "border-color": C["border"],
#                                             },
#                                         },
#                                         {
#                                             "selector": "edge",
#                                             "style": {
#                                                 "label": "data(label)",
#                                                 "font-size": "8px",
#                                                 "color": C["muted"],
#                                                 "font-family": BODY_FONT,
#                                                 "curve-style": "bezier",
#                                                 "target-arrow-shape": "triangle",
#                                                 "arrow-scale": 1.0,
#                                                 "line-color": C["border"],
#                                                 "target-arrow-color": C["border"],
#                                                 "width": 1.2,
#                                                 "text-rotation": "autorotate",
#                                                 "opacity": 0.8,
#                                             },
#                                         },
#                                         {
#                                             "selector": ".seed",
#                                             "style": {
#                                                 "border-color": C["highlight"],
#                                                 "border-width": "3px",
#                                             },
#                                         },
#                                         {
#                                             "selector": ".top",
#                                             "style": {
#                                                 "border-color": C["accent2"],
#                                                 "border-width": "2px",
#                                             },
#                                         },
#                                     ],
#                                 ),
#                                 html.Div(id="t3-node-info", style={"marginTop": "8px", "minHeight": "32px"}),
#                             ]
#                         ),
#                         card(
#                             [
#                                 html.H4(
#                                     "Retrieved Context (for LLM)",
#                                     style={
#                                         "color": C["text"],
#                                         "fontFamily": BODY_FONT,
#                                         "marginBottom": "8px",
#                                         "marginTop": "0",
#                                     },
#                                 ),
#                                 html.Div(id="t3-context"),
#                             ]
#                         ),
#                     ],
#                     style={"flex": "1.4"},
#                 ),
#             ],
#             style={"display": "flex", "alignItems": "flex-start"},
#         ),
#     ]
# )


# ═════════════════════════════════════════════════════════════════════════════
# APP LAYOUT
# ═════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    title="PageRank Explorer",
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;500;600;700&display=swap"
    ],
    suppress_callback_exceptions=True,
)

TAB_STYLE = {
    "backgroundColor": C["surface"],
    "color": C["muted"],
    "border": "none",
    "fontFamily": BODY_FONT,
    "fontWeight": "500",
    "padding": "12px 28px",
    "fontSize": "13px",
}
TAB_SELECTED = {
    **TAB_STYLE,
    "color": C["accent"],
    "borderBottom": f"2px solid {C['accent']}",
    "backgroundColor": C["bg"],
}

app.layout = html.Div(
    [
        # ── Header ──
        html.Div(
            [
                html.Div(
                    [
                        html.Span("◈ ", style={"color": C["accent"], "fontSize": "28px"}),
                        html.Span(
                            "PageRank Explorer",
                            style={
                                "color": C["text"],
                                "fontSize": "22px",
                                "fontWeight": "700",
                                "fontFamily": BODY_FONT,
                                "letterSpacing": "-0.02em",
                            },
                        ),
                    ]
                ),
                html.Div(
                    # "Power method · Closed form · AI Crawling · GraphRAG",
                    "Power method · Closed form · AI Crawling",
                    style={
                        "color": C["muted"],
                        "fontSize": "12px",
                        "fontFamily": BODY_FONT,
                        "letterSpacing": "0.04em",
                    },
                ),
            ],
            style={
                "background": C["surface"],
                "borderBottom": f"1px solid {C['border']}",
                "padding": "16px 32px",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
            },
        ),
        # ── Tabs ──
        dcc.Tabs(
            id="tabs",
            value="t1",
            children=[
                dcc.Tab(label="⚙  PageRank Engine", value="t1", style=TAB_STYLE, selected_style=TAB_SELECTED),
                dcc.Tab(label="🤖  AI Crawler", value="t2", style=TAB_STYLE, selected_style=TAB_SELECTED),
                # dcc.Tab(label="🕸  GraphRAG Retrieval", value="t3", style=TAB_STYLE, selected_style=TAB_SELECTED),
            ],
            style={"backgroundColor": C["surface"], "borderBottom": f"1px solid {C['border']}"},
        ),
        # ── Tab content ──
        html.Div(
            id="tab-content",
            style={
                "padding": "28px 32px",
                "background": C["bg"],
                "minHeight": "calc(100vh - 110px)",
            },
        ),
    ],
    style={"background": C["bg"], "minHeight": "100vh", "fontFamily": BODY_FONT},
)


# ═════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═════════════════════════════════════════════════════════════════════════════


@app.callback(Output("tab-content", "children"), Input("tabs", "value"))
def render_tab(tab: str) -> html.Div:
    if tab == "t1":
        return tab1_layout
    if tab == "t2":
        return tab2_layout
    # if tab == "t3":
    #     return tab3_layout
    return html.Div()  # fallback for unknown tab


# ── TAB 1 CALLBACKS ──────────────────────────────────────────────────────────


def _size_str(b64_contents: str) -> str:
    """Estimate human-readable size from base64 content string."""
    b64_data = b64_contents.split(",", 1)[1] if "," in b64_contents else b64_contents
    n = len(b64_data) * 3 // 4
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.1f} MB"


def _status_badge(filename: str, size_str: str, active: bool = False) -> html.Div:
    """Loaded badge — orange border + ACTIVE label when this is the selected file."""
    border_color = C["highlight"] if active else C["accent2"]
    bg_color = "rgba(240,136,62,0.10)" if active else "rgba(63,185,80,0.08)"
    return html.Div(
        [
            html.Span("✔  ", style={"color": C["accent2"], "fontWeight": "700", "fontSize": "14px"}),
            html.Span(
                filename,
                style={
                    "color": C["text"],
                    "fontFamily": FONT,
                    "fontSize": "12px",
                    "fontWeight": "600",
                },
            ),
            html.Span(
                f"  ·  {size_str}",
                style={
                    "color": C["muted"],
                    "fontFamily": BODY_FONT,
                    "fontSize": "11px",
                },
            ),
            *(
                [
                    html.Span(
                        "  ▶ ACTIVE",
                        style={
                            "color": C["highlight"],
                            "fontFamily": BODY_FONT,
                            "fontSize": "11px",
                            "fontWeight": "700",
                            "marginLeft": "6px",
                        },
                    )
                ]
                if active
                else []
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "background": bg_color,
            "border": f"1px solid {border_color}",
            "borderRadius": "6px",
            "padding": "6px 12px",
        },
    )


# ── 1a. Unified callback — upload drops + Set-as-Active button clicks ───────
#   Outputs:
#     • status badges for both zones
#     • active-file banner
#     • t1-active-file store
#     • visibility of "Set as Active" buttons (show only when file loaded & NOT active)
#     • card border highlight (orange = active, normal = idle)
@app.callback(
    Output("t1-status-10k", "children"),
    Output("t1-status-full", "children"),
    Output("t1-active-banner", "children"),
    Output("t1-active-file", "data"),
    Output("t1-set-10k", "style"),
    Output("t1-set-full", "style"),
    Output("t1-card-10k", "style"),
    Output("t1-card-full", "style"),
    Input("t1-upload-10k", "contents"),
    Input("t1-upload-full", "contents"),
    Input("t1-set-10k", "n_clicks"),
    Input("t1-set-full", "n_clicks"),
    State("t1-upload-10k", "filename"),
    State("t1-upload-full", "filename"),
    State("t1-active-file", "data"),
    prevent_initial_call=True,
)
def on_upload_or_select(
    c10k: str, cfull: str, _btn10k: Any, _btnfull: Any, f10k: str, ffull: str, current_active: dict
) -> tuple:
    triggered = ctx.triggered_id

    # ── Determine new active based on what fired ──────────────────────────────
    if triggered == "t1-upload-10k" and c10k:
        new_active = {"source": "10k", "contents": c10k, "filename": f10k or "web-Google_10k.txt"}
    elif triggered == "t1-upload-full" and cfull:
        new_active = {"source": "full", "contents": cfull, "filename": ffull or "web-Google.txt"}
    elif triggered == "t1-set-10k" and c10k:
        # User clicked "Set as Active" on the 10k card
        new_active = {"source": "10k", "contents": c10k, "filename": f10k or "web-Google_10k.txt"}
    elif triggered == "t1-set-full" and cfull:
        # User clicked "Set as Active" on the full card
        new_active = {"source": "full", "contents": cfull, "filename": ffull or "web-Google.txt"}
    else:
        new_active = current_active

    active_src = (new_active or {}).get("source")

    # ── Status badges ─────────────────────────────────────────────────────────
    badge_10k = (
        _status_badge(f10k or "web-Google_10k.txt", _size_str(c10k), active=(active_src == "10k")) if c10k else ""
    )
    badge_full = (
        _status_badge(ffull or "web-Google.txt", _size_str(cfull), active=(active_src == "full")) if cfull else ""
    )

    # ── "Set as Active" button visibility ─────────────────────────────────────
    # Show ONLY when: file is loaded AND it is NOT currently active
    btn_base = {
        "background": "transparent",
        "border": f"1px solid {C['accent']}",
        "color": C["accent"],
        "borderRadius": "6px",
        "padding": "5px 12px",
        "fontFamily": BODY_FONT,
        "fontSize": "11px",
        "fontWeight": "600",
        "cursor": "pointer",
        "marginLeft": "8px",
        "whiteSpace": "nowrap",
        "flexShrink": "0",
    }
    btn10k_style = (
        {**btn_base, "display": "inline-block"} if (c10k and active_src != "10k") else {**btn_base, "display": "none"}
    )
    btnfull_style = (
        {**btn_base, "display": "inline-block"} if (cfull and active_src != "full") else {**btn_base, "display": "none"}
    )

    # ── Card border highlight ─────────────────────────────────────────────────
    card_base = {
        "flex": "1",
        "borderRadius": "12px",
        "padding": "18px",
        "background": C["card"],
        "transition": "border-color 0.2s",
    }
    card_10k_style = {
        **card_base,
        "border": f"2px solid {C['highlight']}" if active_src == "10k" else f"1px solid {C['border']}",
    }
    card_full_style = {
        **card_base,
        "border": f"2px solid {C['highlight']}" if active_src == "full" else f"1px solid {C['border']}",
    }

    # ── Active-file banner ────────────────────────────────────────────────────
    if not new_active:
        banner = html.Div(
            "⬆  Drop a file on either zone above to begin",
            style={
                "color": C["muted"],
                "fontFamily": BODY_FONT,
                "fontSize": "12px",
                "padding": "10px 0",
                "textAlign": "center",
            },
        )
    else:
        fn = new_active.get("filename", "")
        banner = html.Div(
            [
                html.Span("▶  Active dataset: ", style={"color": C["muted"], "fontSize": "12px"}),
                html.Span(
                    fn,
                    style={
                        "color": C["highlight"],
                        "fontFamily": FONT,
                        "fontSize": "13px",
                        "fontWeight": "700",
                    },
                ),
                html.Span("  —  click  ", style={"color": C["muted"], "fontSize": "12px"}),
                html.Span(
                    "Run PageRank",
                    style={
                        "color": C["accent"],
                        "fontSize": "12px",
                        "fontWeight": "600",
                    },
                ),
                html.Span("  to analyse", style={"color": C["muted"], "fontSize": "12px"}),
            ],
            style={
                "fontFamily": BODY_FONT,
                "padding": "10px 16px",
                "background": "rgba(240,136,62,0.07)",
                "border": f"1px solid {C['highlight']}",
                "borderRadius": "8px",
            },
        )

    return (badge_10k, badge_full, banner, new_active, btn10k_style, btnfull_style, card_10k_style, card_full_style)


# ── 1b. Main PageRank computation ────────────────────────────────────────────
@app.callback(
    Output("t1-store", "data"),
    Output("t1-processing-msg", "children"),
    Output("t1-stats", "children"),
    Output("t1-bar", "figure"),
    Output("t1-conv", "figure"),
    Output("t1-scatter", "figure"),
    Output("t1-cf-stats", "children"),
    Output("t1-table", "children"),
    Input("t1-run", "n_clicks"),
    State("t1-active-file", "data"),
    State("t1-p", "value"),
    State("t1-k", "value"),
    running=[
        (Output("t1-run", "disabled"), True, False),
        (Output("t1-run", "style"), {**BUTTON_STYLE, "opacity": "0.45", "cursor": "not-allowed"}, BUTTON_STYLE),
    ],
    prevent_initial_call=True,
)
def run_pagerank(
    _: Any, active_file: dict, p: float, k: int
) -> tuple[dict, html.Div, list, go.Figure, go.Figure, go.Figure, list, html.Div]:
    import gzip as _gzip
    import time as _time

    def _empty(msg: str) -> tuple[dict, html.Div, list, go.Figure, go.Figure, go.Figure, list, html.Div]:
        empty = go.Figure()
        empty.update_layout(**_dark_layout())
        err = html.Div(
            msg, style={"color": C["highlight"], "fontFamily": BODY_FONT, "fontSize": "13px", "padding": "16px"}
        )
        return ({}, err, [], empty, empty, empty, [], html.Div())

    if not active_file:
        return _empty("⚠  No file loaded — drop a dataset file above then click Run.")

    contents = active_file.get("contents", "")
    filename = active_file.get("filename", "file")

    if not contents:
        return _empty("⚠  File content is empty. Please re-upload.")

    # Decode — handle gzip transparently
    _, b64 = contents.split(",", 1)
    raw = base64.b64decode(b64)
    try:
        text = _gzip.decompress(raw).decode("utf-8", errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    t0 = _time.time()
    edges, node_ids, id2idx = load_edge_list(text)
    n = len(node_ids)

    H, dangling = build_sparse_H(edges, node_ids, id2idx)
    ranks, iters, history = pagerank_power(H, dangling, p=p)
    elapsed = _time.time() - t0

    # Processing banner is shown by dcc.Loading spinner automatically.
    # Once callback returns, this empty string clears it.
    processing_msg = ""

    # ── Stats row ──
    stats = [
        html.Div(
            [
                html.Span("📄  ", style={"fontSize": "14px"}),
                html.Span(
                    filename,
                    style={
                        "color": C["accent"],
                        "fontFamily": FONT,
                        "fontSize": "12px",
                        "fontWeight": "600",
                    },
                ),
            ],
            style={
                "background": C["surface"],
                "border": f"1px solid {C['accent']}",
                "borderRadius": "8px",
                "padding": "12px 16px",
                "display": "flex",
                "alignItems": "center",
                "gap": "4px",
            },
        ),
        stat_box("Nodes", f"{n:,}"),
        stat_box("Edges", f"{len(edges):,}"),
        stat_box("Iterations", str(iters), C["accent2"]),
        stat_box("Max PageRank", f"{ranks.max():.5f}", C["highlight"]),
        stat_box("Rank sum", f"{ranks.sum():.8f}", C["accent4"]),
        stat_box("p (teleport)", str(p)),
        stat_box("Elapsed", f"{elapsed:.1f}s", C["muted"]),
    ]

    # ── Bar chart ──
    top_idx = np.argsort(ranks)[::-1][:k]
    top_nodes = [str(node_ids[i]) for i in top_idx]
    top_vals = [ranks[i] for i in top_idx]
    colors = [C["accent"]] + [C["accent4"]] * (k - 1)
    bar_fig = go.Figure(
        go.Bar(
            x=top_vals[::-1],
            y=top_nodes[::-1],
            orientation="h",
            marker_color=colors[::-1],
            hovertemplate="Node %{y}<br>PageRank = %{x:.6f}<extra></extra>",
        )
    )
    bar_fig.update_layout(**_dark_layout(xlabel="PageRank Score", ylabel="Node ID"))

    # ── Convergence chart ──
    conv_fig = go.Figure(
        go.Scatter(
            x=list(range(1, len(history) + 1)),
            y=history,
            mode="lines",
            line={"color": f"{C['accent2']}", "width": 2},
            fill="tozeroy",
            fillcolor="rgba(63,185,80,0.1)",
            hovertemplate="Iter %{x}: δ = %{y:.2e}<extra></extra>",
        )
    )
    conv_fig.update_layout(**_dark_layout(xlabel="Iteration", ylabel="L1 Δ (log scale)"), yaxis_type="log")

    # ── Closed-form comparison (sample up to 200 nodes) ──
    sample_size = min(200, n)
    sub_ids = node_ids[:sample_size]
    sub_idx = {nid: i for i, nid in enumerate(sub_ids)}
    sub_edges = [(u, v) for u, v in edges if u in sub_idx and v in sub_idx]
    sub_n = len(sub_ids)

    out_d: dict[int, int] = defaultdict(int)
    for u, _ in sub_edges:
        out_d[sub_idx[u]] += 1
    M_d = np.zeros((sub_n, sub_n))
    for u, v in sub_edges:
        ui, vi = sub_idx[u], sub_idx[v]
        M_d[vi, ui] += 1.0 / out_d[ui]
    for j in range(sub_n):
        if out_d[j] == 0:
            M_d[:, j] = 1.0 / sub_n

    pi_iter_sub = ranks[[id2idx[nid] for nid in sub_ids]]
    pi_cf = pagerank_closed_form(M_d, p)

    l1 = float(np.abs(pi_iter_sub - pi_cf).sum())
    corr = float(np.corrcoef(pi_iter_sub, pi_cf)[0, 1]) if sub_n > 1 else 1.0

    cf_stats = [
        stat_box("Subgraph nodes", str(sample_size)),
        stat_box("L1 error", f"{l1:.2e}", C["accent2"]),
        stat_box("Pearson r", f"{corr:.8f}", C["accent4"]),
    ]

    scat_fig = go.Figure(
        go.Scatter(
            x=pi_iter_sub,
            y=pi_cf,
            mode="markers",
            marker={"color": C["accent"], "size": 6, "opacity": 0.7, "line": {"width": 0.5, "color": C["bg"]}},
            hovertemplate="Iterative: %{x:.6f}<br>Closed-form: %{y:.6f}<extra></extra>",
        )
    )
    mn, mx = min(pi_iter_sub.min(), pi_cf.min()), max(pi_iter_sub.max(), pi_cf.max())
    scat_fig.add_trace(
        go.Scatter(x=[mn, mx], y=[mn, mx], mode="lines", line={"color": C["accent3"], "dash": "dash", "width": 1})
    )
    scat_fig.update_layout(**_dark_layout(xlabel="Iterative PageRank", ylabel="Closed-Form PageRank"))

    # ── Table ──
    df = pd.DataFrame(
        {
            "Rank": range(1, k + 1),
            "Node ID": top_nodes,
            "PageRank": [f"{v:.8f}" for v in top_vals],
            "× uniform (1/n)": [f"{v * n:.2f}×" for v in top_vals],
        }
    )
    table = dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        page_size=15,
        **TABLE_STYLE,
    )

    store = {"n": n, "edges": len(edges), "iters": iters}
    return store, processing_msg, stats, bar_fig, conv_fig, scat_fig, cf_stats, table


# ── TAB 2 CALLBACKS ──────────────────────────────────────────────────────────


@app.callback(
    Output("t2-bar", "figure"),
    Output("t2-cyto", "elements"),
    Output("t2-table", "children"),
    Input("t2-run", "n_clicks"),
    State("t2-graph", "value"),
    State("t2-pr", "value"),
    State("t2-robots", "value"),
    State("t2-alpha", "value"),
    State("t2-beta", "value"),
    prevent_initial_call=True,
)
def run_crawler(
    _: Any, graph_txt: str, pr_txt: str, robots_txt: str, alpha: float, beta: float
) -> tuple[go.Figure, list, html.Div]:
    gamma = max(0, 1 - alpha - beta)

    # Parse graph
    web_graph = {}
    for line in (graph_txt or "").splitlines():
        if "->" in line:
            src, _, targets = line.partition("->")
            web_graph[src.strip()] = [t.strip() for t in targets.split(",") if t.strip()]

    # Parse PR
    pr = {}
    for line in (pr_txt or "").splitlines():
        if "=" in line:
            url, _, val = line.partition("=")
            with suppress(ValueError):
                pr[url.strip()] = float(val.strip())

    # Parse robots
    denied = set()
    for line in (robots_txt or "").splitlines():
        if "deny" in line.lower() and "=" in line:
            url, _, _ = line.partition("=")
            denied.add(url.strip())

    if not web_graph or not pr:
        empty = go.Figure()
        empty.update_layout(**_dark_layout())
        return empty, [], html.Div("No data.", style={"color": C["muted"]})

    max_pr = max(pr.values()) or 1

    rows: list[dict[str, Any]] = []
    for url, outs in web_graph.items():
        own = pr.get(url, 0) / max_pr
        nbr = (sum(pr.get(u, 0) for u in outs) / len(outs) / max_pr) if outs else 0
        allowed = url not in denied
        cqs = alpha * own + beta * nbr + gamma * (1 if allowed else 0)
        rows.append({"url": url, "pr": pr.get(url, 0), "cqs": cqs, "allowed": allowed, "outs": outs})

    rows.sort(key=lambda r: -r["cqs"])

    # Bar
    bar_fig = go.Figure()
    for row in rows:
        bar_fig.add_trace(
            go.Bar(
                x=[row["url"].replace("https://", "")],
                y=[row["cqs"]],
                name=row["url"],
                marker_color=C["accent2"] if row["allowed"] else C["accent3"],
                showlegend=False,
                hovertemplate=f"<b>{row['url']}</b><br>CQS={row['cqs']:.3f}<br>PR={row['pr']:.3f}<br>Crawl: {'✓' if row['allowed'] else '✗'}<extra></extra>",
            )
        )
    bar_fig.update_layout(**_dark_layout(xlabel="URL", ylabel="Crawl-Quality Score (CQS)"))
    bar_fig.add_hline(y=0, line_color=C["border"])

    # Cytoscape
    size_scale = 60
    elements = []
    for row in rows:
        size = 20 + (row["pr"] / max_pr) * size_scale
        color = C["accent2"] if row["allowed"] else C["accent3"]
        short = row["url"].replace("https://", "").replace(".example.com", "")
        elements.append({"data": {"id": row["url"], "label": short, "color": color, "size": size, "pr": row["pr"]}})
    for row in rows:
        for tgt in row["outs"]:
            if tgt in web_graph:
                elements.append({"data": {"source": row["url"], "target": tgt}})

    # Table
    df = pd.DataFrame(
        [
            {
                "Rank": i + 1,
                "URL": r["url"].replace("https://", ""),
                "PageRank": f"{r['pr']:.4f}",
                "CQS": f"{r['cqs']:.4f}",
                "Crawl OK?": "✓" if r["allowed"] else "✗ blocked",
            }
            for i, r in enumerate(rows)
        ]
    )
    tbl = dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": C["surface"]},
            {"if": {"filter_query": '{Crawl OK?} = "✗ blocked"'}, "color": C["accent3"]},
            {"if": {"row_index": 0}, "color": C["highlight"], "fontWeight": "700"},
        ],
        **{k: v for k, v in TABLE_STYLE.items() if k != "style_data_conditional"},
    )
    return bar_fig, elements, card([tbl])


@app.callback(
    Output("t2-node-info", "children"),
    Input("t2-cyto", "tapNodeData"),
    prevent_initial_call=True,
)
def t2_node_click(data: dict) -> html.Span | str:
    if not data:
        return ""
    return html.Span(
        f"Selected: {data['id']}  ·  PR = {data['pr']:.4f}",
        style={"color": C["accent"], "fontFamily": FONT, "fontSize": "12px"},
    )


# ── TAB 3 CALLBACKS ──────────────────────────────────────────────────────────


@app.callback(
    Output("t3-bar", "figure"),
    Output("t3-cyto", "elements"),
    Output("t3-context", "children"),
    Input("t3-run", "n_clicks"),
    State("t3-triples", "value"),
    State("t3-seeds", "value"),
    State("t3-p", "value"),
    State("t3-k", "value"),
    prevent_initial_call=True,
)
def run_graphrag(_: Any, triples_txt: str, seeds_txt: str, p: float, k: int) -> tuple[go.Figure, list, html.Div]:
    triples, adj, all_nodes = [], defaultdict(list), set()
    for line in (triples_txt or "").splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) == 3:
            h, r, t = parts
            triples.append((h, r, t))
            adj[h].append(t)
            all_nodes.update([h, t])

    if not all_nodes:
        empty = go.Figure()
        empty.update_layout(**_dark_layout())
        return empty, [], html.Div("No triples.", style={"color": C["muted"]})

    nodes = sorted(all_nodes)
    seeds = [s.strip() for s in (seeds_txt or "").split(",") if s.strip()]
    M = build_dense_M(nodes, adj)
    scores = ppr(M, nodes, seeds, p)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_k = ranked[:k]
    top_set = {nd for nd, _ in top_k}

    # Bar
    bar_names = [nd for nd, _ in ranked[:15]]
    bar_vals = [sc for _, sc in ranked[:15]]
    bar_colors = []
    for nd in bar_names:
        if nd in seeds:
            bar_colors.append(C["highlight"])
        elif nd in top_set:
            bar_colors.append(C["accent"])
        else:
            bar_colors.append(C["muted"])

    bar_fig = go.Figure(
        go.Bar(
            x=bar_vals[::-1],
            y=bar_names[::-1],
            orientation="h",
            marker_color=bar_colors[::-1],
            hovertemplate="%{y}: %{x:.5f}<extra></extra>",
        )
    )
    bar_fig.update_layout(**_dark_layout(xlabel="PPR Score", ylabel="Entity"))

    # Cytoscape
    max_sc = max(scores.values()) or 1
    elements = []
    for nd in nodes:
        sc = scores[nd]
        size = 18 + (sc / max_sc) * 55
        if nd in seeds:
            color = C["highlight"]
        elif nd in top_set:
            color = C["accent"]
        else:
            color = C["surface"]
        cls = "seed" if nd in seeds else ("top" if nd in top_set else "")
        elements.append({"data": {"id": nd, "label": nd, "color": color, "size": size, "score": sc}, "classes": cls})
    for h, r, t in triples:
        elements.append({"data": {"source": h, "target": t, "label": r}})

    # Context panel
    context_items = []
    for nd, sc in top_k:
        related = [(h, r, t) for h, r, t in triples if h == nd or t == nd]
        context_items.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                nd,
                                style={
                                    "color": C["accent"] if nd not in seeds else C["highlight"],
                                    "fontWeight": "700",
                                    "fontFamily": FONT,
                                    "fontSize": "13px",
                                },
                            ),
                            html.Span(
                                f"  PPR = {sc:.5f}", style={"color": C["muted"], "fontSize": "11px", "fontFamily": FONT}
                            ),
                        ],
                        style={"marginBottom": "4px"},
                    ),
                    html.Div(
                        [
                            html.Span(
                                f"{h} → [{r}] → {t}",
                                style={
                                    "color": C["text"],
                                    "fontSize": "11px",
                                    "fontFamily": FONT,
                                    "display": "block",
                                    "paddingLeft": "12px",
                                    "lineHeight": "1.8",
                                },
                            )
                            for h, r, t in related[:4]
                        ]
                    ),
                ],
                style={
                    "background": C["surface"],
                    "borderRadius": "6px",
                    "padding": "10px 14px",
                    "marginBottom": "8px",
                    "borderLeft": f"3px solid {C['accent'] if nd not in seeds else C['highlight']}",
                },
            )
        )

    return bar_fig, elements, html.Div(context_items)


@app.callback(
    Output("t3-node-info", "children"),
    Input("t3-cyto", "tapNodeData"),
    prevent_initial_call=True,
)
def t3_node_click(data: dict) -> html.Span | str:
    if not data:
        return ""
    return html.Span(
        f"Selected: {data['id']}  ·  PPR = {data['score']:.5f}",
        style={"color": C["accent"], "fontFamily": FONT, "fontSize": "12px"},
    )


# ═════════════════════════════════════════════════════════════════════════════
# DARK PLOT THEME HELPER
# ═════════════════════════════════════════════════════════════════════════════


def _dark_layout(xlabel: str = "", ylabel: str = "") -> dict:
    return {
        "paper_bgcolor": C["card"],
        "plot_bgcolor": C["card"],
        "font": {"color": C["muted"], "family": BODY_FONT, "size": 11},
        "xaxis": {
            "title": xlabel,
            "gridcolor": C["border"],
            "zerolinecolor": C["border"],
            "title_font": {"color": C["muted"]},
        },
        "yaxis": {
            "title": ylabel,
            "gridcolor": C["border"],
            "zerolinecolor": C["border"],
            "title_font": {"color": C["muted"]},
        },
        "margin": {"l": 60, "r": 20, "t": 20, "b": 60},
        "hoverlabel": {"bgcolor": C["surface"], "font_color": C["text"], "font_family": BODY_FONT},
    }


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(
        """
 ◈  PageRank Explorer
 Open in browser → http://127.0.0.1:8050
 ─────────────────────────────────────────────
    """
    )
    app.run(debug=True, host="0.0.0.0", port=8050)
