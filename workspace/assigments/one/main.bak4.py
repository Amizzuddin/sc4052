################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 1:45:39 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 1:52:57 pm                       #
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

app.layout = html.Div(
    [
        html.H1(
            "Dynamic Fat-Tree Generator", style={"textAlign": "center", "fontFamily": "sans-serif", "padding": "20px"}
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Ports per Switch (k):", style={"fontWeight": "bold"}),
                        dcc.Input(
                            id="k-input",
                            type="number",
                            value=4,
                            min=2,
                            step=2,
                            style={"width": "100%", "padding": "8px", "marginBottom": "20px"},
                        ),
                        html.Label("Tree Depth (Stages):", style={"fontWeight": "bold"}),
                        dcc.Input(
                            id="depth-input",
                            type="number",
                            value=3,
                            min=2,
                            max=5,
                            style={"width": "100%", "padding": "8px", "marginBottom": "20px"},
                        ),
                        html.Div(
                            id="stats-output",
                            style={
                                "marginTop": "20px",
                                "padding": "20px",
                                "backgroundColor": "#1e272e",
                                "color": "#0be881",
                                "borderRadius": "8px",
                                "fontFamily": "monospace",
                                "fontSize": "14px",
                            },
                        ),
                    ],
                    style={"padding": "20px", "backgroundColor": "#f1f2f6", "borderRadius": "10px"},
                )
            ],
            style={"width": "20%", "display": "inline-block", "padding": "20px", "verticalAlign": "top"},
        ),
        html.Div(
            [dcc.Graph(id="fat-tree-graph", style={"height": "85vh"})],
            style={"width": "70%", "display": "inline-block"},
        ),
    ]
)


@app.callback(
    [Output("fat-tree-graph", "figure"), Output("stats-output", "children")],
    [Input("k-input", "value"), Input("depth-input", "value")],
)
def update_network(k, depth):
    # --- 1. Validation ---
    if k is None or k < 2:
        k = 2
    if depth is None or depth < 2:
        depth = 2
    if depth > 4:
        depth = 4

    G = nx.Graph()
    pos = {}
    half_k = k // 2

    # --- 2. Topology Generation (Standard 3-Tier Example) ---
    if depth == 3:
        n_core = half_k**2
        for i in range(n_core):
            node = f"C{i}"
            G.add_node(node, type="core")
            pos[node] = [i * (k**2 / n_core) - (k**2 / 2), 3]

        for p in range(k):
            for i in range(half_k):
                agg, edge = f"P{p}_A{i}", f"P{p}_E{i}"
                G.add_node(agg, type="agg")
                G.add_node(edge, type="edge")
                pos[agg] = [(p * k) + i - (k * k / 2), 2]
                pos[edge] = [(p * k) + i - (k * k / 2), 1]

                for j in range(half_k):
                    G.add_edge(agg, f"C{(i * half_k) + j}")
                    G.add_edge(agg, f"P{p}_E{j}")

                for h in range(half_k):
                    host = f"P{p}_E{i}_H{h}"
                    G.add_node(host, type="host")
                    pos[host] = [(p * half_k**2) + (i * half_k) + h - (k * half_k**2 / 2), 0]
                    G.add_edge(edge, host)
    else:
        # (2-Tier Logic Placeholder - similar to above but skipping Core)
        for p in range(k):
            for i in range(half_k):
                agg, edge = f"P{p}_A{i}", f"P{p}_E{i}"
                G.add_node(agg, type="agg")
                G.add_node(edge, type="edge")
                pos[agg], pos[edge] = [(p * k) + i, 2], [(p * k) + i, 1]
                for j in range(half_k):
                    G.add_edge(agg, f"P{p}_E{j}")
                for h in range(half_k):
                    host = f"P{p}_E{i}_H{h}"
                    G.add_node(host, type="host")
                    pos[host] = [(p * half_k**2) + (i * half_k) + h, 0]
                    G.add_edge(edge, host)

    # --- 3. Advanced Inventory Calculations ---
    num_cables = G.number_of_edges()
    num_hosts = sum(1 for n, d in G.nodes(data=True) if d.get("type") == "host")
    num_switches = G.number_of_nodes() - num_hosts

    # Logic for requested metrics
    total_transmitters = num_cables * 2
    switch_tx_ports = total_transmitters - num_hosts

    stats = [
        html.Div(
            [
                html.H3("Network Inventory", style={"color": "#0be881", "borderBottom": "1px solid #0be881"}),
                html.P(f"Total Hosts: {num_hosts}"),
                html.P(f"Total Switches: {num_switches}"),
                html.P(f"Total Cables: {num_cables}"),
                html.Hr(style={"borderColor": "#444"}),
                html.P(f"Transmitters: {total_transmitters}", style={"fontWeight": "bold"}),
                html.P(f"Switch Tx's: {switch_tx_ports}", style={"fontWeight": "bold", "color": "#ffdd59"}),
            ]
        )
    ]

    # --- 4. Plotly Figure Construction ---
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    fig = go.Figure(
        data=[
            go.Scatter(x=edge_x, y=edge_y, line=dict(width=0.5, color="#bdc3c7"), hoverinfo="none", mode="lines"),
            go.Scatter(
                x=[pos[n][0] for n in G.nodes()],
                y=[pos[n][1] for n in G.nodes()],
                mode="markers",
                marker=dict(size=10, color="#3498db", line_width=1, line_color="white"),
                text=list(G.nodes()),
                hoverinfo="text",
            ),
        ],
        layout=go.Layout(
            showlegend=False, margin=dict(t=0, b=0, l=0, r=0), xaxis=dict(visible=False), yaxis=dict(visible=False)
        ),
    )

    return fig, stats


if __name__ == "__main__":
    # Run server - will be available at http://127.0.0.1:8050
    app.run(debug=True, host="0.0.0.0")
