################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 1:29:21 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 1:40:13 pm                       #
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

# --- Layout of the Web Page ---
app.layout = html.Div(
    [
        html.H1("Dynamic Fat-Tree Generator"),
        html.Div(
            [
                html.Label("Ports per Switch (k): "),
                dcc.Slider(id="k-slider", min=2, max=12, step=2, value=4, marks={i: str(i) for i in range(2, 13, 2)}),
                html.Br(),
                html.Div(id="stats-output", style={"whiteSpace": "pre-line", "fontWeight": "bold", "color": "#2c3e50"}),
            ],
            style={"width": "30%", "display": "inline-block", "verticalAlign": "top", "padding": "20px"},
        ),
        html.Div(
            [dcc.Graph(id="fat-tree-graph", style={"height": "800px"})],
            style={"width": "65%", "display": "inline-block"},
        ),
    ]
)


# --- Logic to Update Graph and Stats ---
@app.callback([Output("fat-tree-graph", "figure"), Output("stats-output", "children")], [Input("k-slider", "value")])
def update_topology(k):
    # 1. Calculations
    num_hosts = (k**3) // 4
    num_switches = (5 * k**2) // 4
    num_cables = (3 * k**3) // 4

    stats_text = (
        f"--- Network Inventory ---\n"
        f"Total Hosts: {num_hosts}\n"
        f"Total Switches: {num_switches}\n"
        f"Total Cables: {num_cables}\n"
        f"Switch Tx Ports: {num_cables * 2 - num_hosts}"
    )

    # 2. Build Graph Logic
    G = nx.Graph()
    pos = {}

    # Core Layer
    n_core = (k // 2) ** 2
    for i in range(n_core):
        node_id = f"C{i}"
        G.add_node(node_id, layer=0)
        pos[node_id] = [i - n_core / 2, 3]

    # Pods
    for p in range(k):
        for i in range(k // 2):
            agg_id = f"P{p}_A{i}"
            edge_id = f"P{p}_E{i}"

            # Aggregation Layer
            G.add_node(agg_id, layer=1)
            pos[agg_id] = [(p * k) + i - (k * k) / 2, 2]

            # Edge Layer
            G.add_node(edge_id, layer=2)
            pos[edge_id] = [(p * k) + i - (k * k) / 2, 1]

            # Connect Edge to Agg
            for j in range(k // 2):
                G.add_edge(edge_id, f"P{p}_A{j}")

            # Connect Agg to Core
            stride = k // 2
            for j in range(stride):
                G.add_edge(agg_id, f"C{(i * stride) + j}")

            # Hosts
            for h in range(k // 2):
                host_id = f"P{p}_E{i}_H{h}"
                G.add_node(host_id, layer=3)
                pos[host_id] = [(p * k * 0.5) + (i * k * 0.2) + h - (k * k) / 2, 0]
                G.add_edge(edge_id, host_id)

    # 3. Create Plotly Figure
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(x=edge_x, y=edge_y, line=dict(width=0.5, color="#888"), hoverinfo="none", mode="lines")

    node_x = [pos[node][0] for node in G.nodes()]
    node_y = [pos[node][1] for node in G.nodes()]

    node_trace = go.Scatter(x=node_x, y=node_y, mode="markers", marker=dict(size=10, color="#3498db", line_width=2))

    fig = go.Figure(
        data=[edge_trace, node_trace],
        layout=go.Layout(
            showlegend=False,
            hovermode="closest",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        ),
    )

    return fig, stats_text


if __name__ == "__main__":
    # Run server - will be available at http://127.0.0.1:8050
    app.run(debug=True, host="0.0.0.0")
