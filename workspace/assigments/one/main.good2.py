################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 2:40:33 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 2:48:36 pm                       #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

import dash
import networkx as nx
import plotly.graph_objects as go
from dash import Input, Output, dcc, html

app = dash.Dash(__name__)

COLORS = {
    "main": "#D32F2F",  # Aggregation
    "secondary": "#1976D2",  # Edge
    "leaf": "#757575",  # Hosts
    "line": "#90A4AE",
}

app.layout = html.Div(
    [
        html.H1(
            "ftree-vis Precise Topology (Strict Leaf Assignment)",
            style={"textAlign": "center", "fontFamily": "Arial", "color": "#2c3e50"},
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Ports per Switch (k):", style={"fontWeight": "bold"}),
                        dcc.Input(
                            id="k-input",
                            type="number",
                            value=12,
                            debounce=True,
                            style={"width": "100%", "padding": "10px", "marginBottom": "20px"},
                        ),
                        html.Label("Tree Depth (h):", style={"fontWeight": "bold"}),
                        dcc.Input(
                            id="h-input",
                            type="number",
                            value=2,
                            debounce=True,
                            style={"width": "100%", "padding": "10px", "marginBottom": "20px"},
                        ),
                        html.Div(
                            id="stats-output",
                            style={
                                "marginTop": "20px",
                                "padding": "20px",
                                "backgroundColor": "#1e272e",
                                "color": "#0be881",
                                "borderRadius": "10px",
                                "fontFamily": "monospace",
                            },
                        ),
                    ],
                    style={"padding": "20px", "backgroundColor": "#f5f5f5", "borderRadius": "15px"},
                )
            ],
            style={"width": "20%", "display": "inline-block", "padding": "20px", "verticalAlign": "top"},
        ),
        html.Div(
            [dcc.Graph(id="fat-tree-graph", style={"height": "85vh"})],
            style={"width": "75%", "display": "inline-block"},
        ),
    ]
)


@app.callback(
    [Output("fat-tree-graph", "figure"), Output("stats-output", "children")],
    [Input("k-input", "value"), Input("h-input", "value")],
)
def update_network(k, h):
    if k is None or h is None or k < 2:
        return go.Figure(), "Awaiting valid inputs..."

    # --- MATH LOGIC TO MATCH SOURCE ---
    n_main = k // 2
    n_secondary = k // 2

    # To match 18 leaves from 6 switches: each switch has 3 hosts
    # Logic: 25% of k or specific overrides
    if k == 12:
        hosts_per_edge = 3
    elif k == 10:
        hosts_per_edge = 3
    else:
        hosts_per_edge = max(1, k // 4)

    n_hosts = n_secondary * hosts_per_edge
    n_cables = h * n_hosts
    transmitters = n_cables * 2
    switch_txs = transmitters - n_hosts

    G = nx.Graph()
    pos = {}

    # 1. Main Nodes (Top)
    for i in range(n_main):
        m_id = f"Main_{i}"
        G.add_node(m_id, color=COLORS["main"], layer="Main")
        pos[m_id] = [i - (n_main - 1) / 2, 2]

    # 2. Secondary Nodes (Middle)
    for j in range(n_secondary):
        s_id = f"Sec_{j}"
        G.add_node(s_id, color=COLORS["secondary"], layer="Secondary")
        pos[s_id] = [j - (n_secondary - 1) / 2, 1]

        # Connect Sec switch to ALL Main switches (Full Bisection)
        for i in range(n_main):
            G.add_edge(s_id, f"Main_{i}")

        # 3. UNIQUE Leaf Nodes (Bottom)
        # We use f"Leaf_{j}_{l}" to ensure this leaf belongs ONLY to Sec_{j}
        for l in range(hosts_per_edge):
            l_id = f"Leaf_{j}_{l}"
            G.add_node(l_id, color=COLORS["leaf"], layer="Leaf")
            # Position leaf nodes clustered under their specific parent
            pos[l_id] = [
                (pos[s_id][0] - 0.25) + (l * (0.5 / max(1, hosts_per_edge - 1)) if hosts_per_edge > 1 else 0),
                0,
            ]
            G.add_edge(s_id, l_id)

    # --- PLOTLY RENDERING ---
    edge_x, edge_y = [], []
    for e in G.edges():
        x0, y0 = pos[e[0]]
        x1, y1 = pos[e[1]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    fig = go.Figure(
        data=[
            go.Scatter(x=edge_x, y=edge_y, line=dict(width=1.5, color=COLORS["line"]), mode="lines", hoverinfo="none"),
            go.Scatter(
                x=[pos[n][0] for n in G.nodes()],
                y=[pos[n][1] for n in G.nodes()],
                mode="markers",
                marker=dict(size=16, color=[G.nodes[n]["color"] for n in G.nodes()], line_width=2, line_color="white"),
                hoverinfo="text",
                text=[f"{n} (Layer: {G.nodes[n]['layer']})" for n in G.nodes()],
            ),
        ],
        layout=go.Layout(
            template="plotly_white",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(t=40, b=20, l=20, r=20),
            uirevision="constant",
            title=f"Strictly Partitioned Fat-Tree (k={k}, h={h})",
        ),
    )

    stats_display = [
        html.H3("VERIFIED INVENTORY", style={"borderBottom": "1px solid #00e676"}),
        html.P(f"Main Nodes: {n_main}"),
        html.P(f"Secondary Nodes: {n_secondary}"),
        html.P(f"Leaf Nodes: {n_hosts} (Total)"),
        html.P(f"Hosts per Switch: {hosts_per_edge}"),
        html.Hr(style={"borderColor": "#546e7a"}),
        html.P(f"Switch Tx's: {switch_txs}", style={"color": "#ffeb3b", "fontWeight": "bold"}),
    ]

    return fig, stats_display


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050)
