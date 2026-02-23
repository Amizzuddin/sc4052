################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 1:45:39 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 1:47:05 pm                       #
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
        html.H1("Multi-Tier Fat-Tree Generator", style={"textAlign": "center", "fontFamily": "sans-serif"}),
        html.Div(
            [
                html.Label("Ports per Switch (k):", style={"fontWeight": "bold"}),
                dcc.Input(
                    id="k-input", type="number", value=4, min=2, step=2, style={"width": "100%", "marginBottom": "20px"}
                ),
                html.Label("Tree Depth (Switch Stages):", style={"fontWeight": "bold"}),
                dcc.Slider(id="depth-slider", min=2, max=3, step=1, value=3, marks={2: "2-Tier", 3: "3-Tier"}),
                html.Div(
                    id="stats-output",
                    style={
                        "marginTop": "30px",
                        "padding": "20px",
                        "backgroundColor": "#2c3e50",
                        "color": "white",
                        "borderRadius": "10px",
                        "fontFamily": "monospace",
                    },
                ),
            ],
            style={"width": "20%", "display": "inline-block", "padding": "20px", "verticalAlign": "top"},
        ),
        html.Div(
            [dcc.Graph(id="fat-tree-graph", style={"height": "90vh"})],
            style={"width": "75%", "display": "inline-block"},
        ),
    ]
)


@app.callback(
    [Output("fat-tree-graph", "figure"), Output("stats-output", "children")],
    [Input("k-input", "value"), Input("depth-slider", "value")],
)
def update_network(k, depth):
    # Default fallback values
    if not k or k < 2:
        k = 2

    G = nx.Graph()
    pos = {}
    half_k = k // 2

    # Create Layers
    # Layer IDs for coordinate mapping
    CORE, AGG, EDGE, HOST = 3, 2, 1, 0

    # 3-Tier adds Core
    if depth == 3:
        n_core = half_k**2
        for i in range(n_core):
            G.add_node(f"C{i}", layer="core")
            pos[f"C{i}"] = [i * (k / n_core) - k / 2, CORE]

    for p in range(k):
        for i in range(half_k):
            agg, edge = f"P{p}_A{i}", f"P{p}_E{i}"
            G.add_node(agg, layer="agg")
            G.add_node(edge, layer="edge")
            pos[agg] = [(p * k) + i - (k * k / 2), AGG]
            pos[edge] = [(p * k) + i - (k * k / 2), EDGE]

            # Connectivity
            if depth == 3:
                for j in range(half_k):
                    G.add_edge(agg, f"C{(i * half_k) + j}")

            for j in range(half_k):
                G.add_edge(agg, f"P{p}_E{j}")

            for h in range(half_k):
                host = f"P{p}_E{i}_H{h}"
                G.add_node(host, layer="host")
                pos[host] = [(p * half_k**2) + (i * half_k) + h - (k * k * 0.25), HOST]
                G.add_edge(edge, host)

    # Prepare Visuals
    edge_trace = go.Scatter(x=[], y=[], line=dict(width=0.5, color="#888"), mode="lines")
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_trace["x"] += (x0, x1, None)
        edge_trace["y"] += (y0, y1, None)

    node_trace = go.Scatter(
        x=[pos[n][0] for n in G.nodes()],
        y=[pos[n][1] for n in G.nodes()],
        mode="markers",
        marker=dict(size=10, color="#3498db"),
    )

    fig = go.Figure(data=[edge_trace, node_trace], layout=go.Layout(showlegend=False))

    # Calculate Stats for the second output
    cables = G.number_of_edges()
    hosts = sum(1 for n, d in G.nodes(data=True) if d.get("layer") == "host")
    stats = [html.P(f"Cables: {cables}"), html.P(f"Hosts: {hosts}")]

    return fig, stats  # Correctly returning two items


if __name__ == "__main__":
    # Run server - will be available at http://127.0.0.1:8050
    app.run(debug=True, host="0.0.0.0")
