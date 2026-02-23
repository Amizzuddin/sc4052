################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, February 21st 2026, 1:18:33 pm                     #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday February 21st 2026 1:27:29 pm                       #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

import os
import webbrowser

import networkx as nx
from pyvis.network import Network

from workspace.utilities.logger import logger


def generate_fat_tree_tool(k):
    # --- 1. Calculations (The "Outputs") ---
    num_pods = k
    core_switches = (k // 2) ** 2
    agg_switches = (k * k) // 2
    edge_switches = (k * k) // 2
    total_switches = core_switches + agg_switches + edge_switches

    num_hosts = (k**3) // 4

    # Cables: (Host-to-Edge) + (Edge-to-Agg) + (Agg-to-Core)
    cables_h_e = num_hosts
    cables_e_a = (k * k * k) // 4
    cables_a_c = (k * k * k) // 4
    total_cables = cables_h_e + cables_e_a + cables_a_c

    # Transmitters: Every cable end has a Tx
    # (Excluding Hosts, usually we count Switch Ports/Tx)
    switch_txs = total_cables * 2 - num_hosts

    # Print Summary
    logger.info(f"\n--- Topology Stats (k={k}) ---")
    logger.info(f"Hosts: {num_hosts}")
    logger.info(f"Switches: {total_switches} ({core_switches} Core, {agg_switches//2} Agg, {edge_switches//2} Edge)")
    logger.info(f"Cables: {total_cables}")
    logger.info(f"Switch Tx Ports: {switch_txs}")
    logger.info("------------------------------\n")

    # --- 2. Graph Generation ---
    G = nx.Graph()
    net = Network(height="800px", width="100%", bgcolor="#ffffff", font_color="black")

    # Add Core
    for i in range(core_switches):
        G.add_node(f"Core_{i}", label=f"C{i}", color="#FF4B2B", size=25)

    for p in range(num_pods):
        # Add Agg and Edge
        for i in range(k // 2):
            agg_id = f"P{p}_A{i}"
            edge_id = f"P{p}_E{i}"
            G.add_node(agg_id, label=f"A{i}", color="#12c2e9", size=20)
            G.add_node(edge_id, label=f"E{i}", color="#c471ed", size=20)

            # Connect Agg to Core
            stride = k // 2
            for j in range(stride):
                G.add_edge(agg_id, f"Core_{(i * stride) + j}")

            # Connect Edge to all Agg in same pod
            for j in range(k // 2):
                G.add_edge(edge_id, f"P{p}_A{j}")

            # Add Hosts
            for h in range(k // 2):
                host_id = f"P{p}_E{i}_H{h}"
                G.add_node(host_id, label="H", color="#f64f59", size=10)
                G.add_edge(edge_id, host_id)

    # --- 3. Rendering ---
    net.from_nx(G)
    net.toggle_physics(True)

    # Save and auto-open
    file_path = "fat_tree.html"
    net.write_html(file_path)
    logger.debug((f"Success! Visualization saved to: {os.path.abspath(file_path)}"))

    # Force open in browser (some environments need this)
    webbrowser.open("file://" + os.path.realpath(file_path))


# --- User Input ---
try:
    k_val = int(input("Enter number of ports per switch (k, must be even): "))
    if k_val % 2 != 0:
        print("k must be an even number. Setting k=4.")
        k_val = 4
    generate_fat_tree_tool(k_val)
except ValueError:
    print("Invalid input. Please enter an integer.")
