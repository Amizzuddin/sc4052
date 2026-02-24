################################################################################
#  Filename:      one/main.py                                                  #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Monday, February 23rd 2026, 3:24:56 am                       #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   Help of claude.ai to generate Fat Tree Visualizer            #
#  --------------------------------------------------------------------------- #
#  Last Modified: Tuesday February 24th 2026 12:33:28 pm                       #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
Fat Tree Network Topology Visualizer — Interactive Edition
Python 3.10 port of https://github.com/h8liu/ftree-vis
Uses Dash + Plotly for interactive visualization.

NEW: Click any two host nodes to highlight ALL possible paths between them.

Run:
    pip install dash plotly
    python app.py
Then open http://127.0.0.1:8050
"""

from __future__ import annotations

import colorsys
import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html


# ============================================================================
# [NEW] Hardware node metadata & DC profiles
# ============================================================================
@dataclass
class HardwareNode:
    """Describes the compute hardware in a single host/rack slot."""

    hw_type: str = "cpu"  # 'cpu' | 'gpu' | 'tpu' | 'storage' | 'mixed'
    gpu_count: int = 0  # accelerators per rack (0 = CPU-only)
    gpu_model: str = ""  # e.g. 'H100-80G', 'A100-40G'
    cpu_cores: int = 64  # logical cores
    memory_tb: float = 0.5  # host RAM in TB
    interconnect: str = "ethernet"  # 'ethernet' | 'infiniband' | 'roce-v2'
    rack_power_kw: float = 7.0  # rated rack power
    pod_role: str = "general"  # 'training' | 'inference' | 'storage' | 'control'
    utilisation: float = 0.0  # 0.0–1.0 for colour encoding


@dataclass
class DatacenterProfile:
    """Pre-baked topology + fabric parameters for well-known data centers."""

    name: str
    k: int
    depth: int
    port_speed_gbps: float
    oversubscription: float  # 1.0 = non-blocking
    fabric_gen: str
    interconnect: str
    notes: str
    hw_mix: dict = field(default_factory=dict)  # % breakdown: {'gpu':0.7,'cpu':0.3}


# ── Built-in DC profiles ──────────────────────────────────────────────────────
PRESET_PROFILES: dict[str, DatacenterProfile] = {
    "custom": DatacenterProfile(
        "Custom",
        4,
        3,
        10.0,
        2.0,
        "Generic fat-tree",
        "ethernet",
        "Manually configure k and depth with the sliders.",
        {},
    ),
    "jupiter_2015": DatacenterProfile(
        "Google Jupiter 2015",
        48,
        3,
        10.0,
        1.0,
        "Jupiter Gen-1",
        "ethernet",
        "First-gen Jupiter: 48-port Close, non-blocking, 10 GbE inter-block.",
        {"gpu": 0.0, "cpu": 1.0},
    ),
    "jupiter_2023": DatacenterProfile(
        "Google Jupiter 2023",
        64,
        3,
        100.0,
        1.0,
        "Jupiter Optical",
        "ethernet",
        "Optical circuit switching, 100 GbE, 64-port spine, ~petabit BW.",
        {"gpu": 0.4, "cpu": 0.6},
    ),
    "meta_fabric_v2": DatacenterProfile(
        "Meta Fabric v2",
        32,
        2,
        400.0,
        1.5,
        "Meta Fabric v2",
        "ethernet",
        "Spine-leaf Close, 400 GbE per spine port, 1.5:1 oversubscription.",
        {"gpu": 0.3, "cpu": 0.7},
    ),
    "ai_cluster": DatacenterProfile(
        "Generic AI Cluster",
        8,
        3,
        400.0,
        1.0,
        "GPU Cluster",
        "roce-v2",
        "Dense GPU racks (H100), RoCE-v2, non-blocking for all-reduce.",
        {"gpu": 0.8, "cpu": 0.2},
    ),
    "futuristic_hpc": DatacenterProfile(
        "Futuristic HPC DC",
        16,
        3,
        800.0,
        1.0,
        "800 GbE Optical",
        "infiniband",
        "800 GbE / NDR InfiniBand, optical switching. Mix: GPU (H200), TPU, CPU control.",
        {"gpu": 0.6, "tpu": 0.3, "cpu": 0.1},
    ),
    # ── Dummy profile: every hw_type represented equally ─────────────────────
    "all_types_demo": DatacenterProfile(
        "★ Demo — All Host Types",
        8,
        3,
        100.0,
        1.0,
        "Demo Fabric",
        "roce-v2",
        "Dummy profile showing all hardware types: CPU, GPU, TPU, Storage (25% each).",
        {"cpu": 0.25, "gpu": 0.25, "tpu": 0.25, "storage": 0.25},
    ),
}

# ── Hardware color & shape encoding ──────────────────────────────────────────
HW_COLORS = {
    "cpu": "#a8b5c1",  # steel grey  (matches existing host colour)
    "gpu": "#f7dc6f",  # yellow
    "tpu": "#bb8fce",  # purple
    "storage": "#45b7d1",  # blue
    "mixed": "#4ecdc4",  # teal
}
HW_SHAPES = {
    "cpu": "circle",
    "gpu": "square",
    "tpu": "diamond",
    "storage": "triangle-up",
    "mixed": "circle",
}


# ============================================================================
# [NEW] Analytics helpers
# ============================================================================
def compute_analytics(nodes: list[dict], edges: list[tuple], profile: DatacenterProfile) -> dict:
    """Derive key data-center metrics from the current topology."""
    n_hosts = sum(1 for n in nodes if n["type"] == "host")
    n_sw = sum(1 for n in nodes if n["type"] != "host")
    n_cables = len(edges)
    half_k = profile.k // 2

    # Bisection bandwidth (theoretical, non-blocking Close)
    bisection_tbps = round((n_hosts / 2) * profile.port_speed_gbps / 1000, 2)

    # Average paths between pods (k/2 for depth-3 fat-tree)
    avg_paths = half_k if profile.depth == 3 else 1

    # Estimated cluster power
    hw_mix = profile.hw_mix or {"cpu": 1.0}
    gpu_frac = hw_mix.get("gpu", 0.0)
    avg_power = 7.0 + gpu_frac * 23.0  # CPU rack ~7 kW, GPU rack ~30 kW
    total_power_mw = round(n_hosts * avg_power / 1000, 2)

    # Switch latency estimate (per hop, ns)
    switch_latency_ns = 200 if profile.interconnect == "infiniband" else 800

    return {
        "hosts": n_hosts,
        "switches": n_sw,
        "cables": n_cables,
        "bisection_tbps": bisection_tbps,
        "oversubscription": profile.oversubscription,
        "avg_gpu_paths": avg_paths,
        "total_power_mw": total_power_mw,
        "switch_lat_ns": switch_latency_ns,
        "interconnect": profile.interconnect.upper(),
        "port_speed_gbps": profile.port_speed_gbps,
    }


# ============================================================================
# [NEW] Profile overrides — apply user-edited interconnect + hw_mix at runtime
# ============================================================================
def apply_overrides(profile: Any, overrides: dict) -> Any:
    """Return a shallow copy of profile with user overrides applied."""
    if not overrides:
        return profile
    p = copy.copy(profile)
    ic = overrides.get("interconnect")
    if ic:
        p.interconnect = ic
    gf_raw = overrides.get("gpu_frac")
    if gf_raw is not None:
        gf = max(0.0, min(1.0, float(gf_raw)))
        orig = profile.hw_mix or {"cpu": 1.0}
        tpu_f = orig.get("tpu", 0.0)
        storage_f = orig.get("storage", 0.0)
        other_f = tpu_f + storage_f
        if 0 < other_f < 1.0:
            scale = 1.0 - other_f
            gf2 = round(gf * scale, 4)
            cf2 = round(scale - gf2, 4)
            new_mix = {}
            if gf2 > 0:
                new_mix["gpu"] = gf2
            if cf2 > 0:
                new_mix["cpu"] = cf2
            if tpu_f > 0:
                new_mix["tpu"] = tpu_f
            if storage_f > 0:
                new_mix["storage"] = storage_f
        else:
            cf = round(1.0 - gf, 4)
            new_mix = {}
            if gf > 0:
                new_mix["gpu"] = gf
            if cf > 0:
                new_mix["cpu"] = cf
        p.hw_mix = new_mix
    return p


# ============================================================================
# [NEW] GPU-affinity weighted routing
# ============================================================================
def gpu_affinity_weight(node_map: dict, a: str, b: str) -> float:
    """Cost of traversing edge a→b; penalises cross-pod (core) hops."""
    na, nb = node_map.get(a, {}), node_map.get(b, {})
    pod_a = na.get("pod", -1)
    pod_b = nb.get("pod", -2)
    # Crossing into a core switch costs 10x; same-pod hop costs 1
    if a.startswith("core_") or b.startswith("core_"):
        return 10.0
    if pod_a != pod_b:
        return 5.0
    return 1.0


def find_paths_weighted(
    adj: dict,
    node_map: dict,
    src: str,
    dst: str,
    max_hops: int = 10,
    gpu_affinity: bool = False,
    cheapest_only: bool = True,
) -> tuple[list[list[str]], int, list[float]]:
    """
    Weighted DFS path finder.
    When gpu_affinity=True, paths are ranked by weighted cost (lower = GPU-preferred).
    When cheapest_only=True (default), only the minimum-cost paths are returned
    for display — analogous to shortest_only in find_all_paths.
    Returns (display_paths, total_count, display_costs).
    """
    all_results: list[tuple[float, list[str]]] = []
    stack = [(src, [src], {src}, 0.0)]
    while stack:
        node, path, visited, cost = stack.pop()
        if len(path) - 1 >= max_hops:
            continue
        for nb in adj.get(node, []):
            edge_cost = gpu_affinity_weight(node_map, node, nb) if gpu_affinity else 1.0
            new_cost = cost + edge_cost
            if nb == dst:
                all_results.append((new_cost, path + [dst]))
            elif nb not in visited:
                stack.append((nb, path + [nb], visited | {nb}, new_cost))

    all_results.sort(key=lambda x: (x[0], len(x[1]), x[1]))
    total = len(all_results)

    if cheapest_only and all_results:
        min_cost = all_results[0][0]
        display = [(c, p) for c, p in all_results if c == min_cost]
    else:
        display = all_results

    paths = [p for _, p in display]
    costs = [c for c, _ in display]
    return paths, total, costs


# ============================================================================
# [NEW] Assign hardware types to host nodes from DC profile hw_mix
# ============================================================================
def assign_hw_types(nodes: list[dict], profile: "DatacenterProfile | None") -> None:
    """
    Stamp each host node with hw_type, hw_color and hw_shape in-place.
    Uses count-based allocation so every hw_type in hw_mix is guaranteed
    to appear at least once, even with very small weights or few hosts.
    """
    hw_mix = profile.hw_mix if profile and profile.hw_mix else {"cpu": 1.0}
    # Normalise weights so they sum to 1.0
    total_w = sum(hw_mix.values()) or 1.0
    norm = {t: w / total_w for t, w in hw_mix.items() if w > 0}

    host_nodes = [n for n in nodes if n["type"] == "host"]
    n_hosts = len(host_nodes)

    if n_hosts == 0:
        return

    # ── Count-based floor allocation ─────────────────────────────────────────
    # Each type gets at least 1 host (if n_hosts allows), then proportional
    # allocation of the remainder.
    types = list(norm.keys())
    guaranteed = min(len(types), n_hosts)  # how many types we can guarantee
    floor_counts = dict.fromkeys(types, 0)
    for t in types[:guaranteed]:
        floor_counts[t] = 1
    remainder = n_hosts - guaranteed

    # Distribute remainder proportionally (largest-remainder method)
    exact = {t: norm[t] * remainder for t in types}
    floored = {t: int(exact[t]) for t in types}
    leftover = remainder - sum(floored.values())
    fracs = sorted(types, key=lambda t: -(exact[t] - floored[t]))
    for t in fracs[:leftover]:
        floored[t] += 1

    # Final per-type counts
    counts = {t: floor_counts[t] + floored[t] for t in types}

    # Build the label list in sorted order so layout is spatially consistent:
    # cpu → left pods, gpu → middle, tpu → right, storage → far right
    TYPE_ORDER = ["cpu", "storage", "tpu", "gpu", "mixed"]
    ordered = sorted(types, key=lambda t: TYPE_ORDER.index(t) if t in TYPE_ORDER else 99)
    label_seq: list[str] = []
    for t in ordered:
        label_seq.extend([t] * counts[t])
    # Pad/trim in case of rounding edge cases
    while len(label_seq) < n_hosts:
        label_seq.append(ordered[-1])
    label_seq = label_seq[:n_hosts]

    for n, hw in zip(host_nodes, label_seq):
        n["hw_type"] = hw
        n["hw_color"] = HW_COLORS.get(hw, "#a8b5c1")
        n["hw_shape"] = HW_SHAPES.get(hw, "circle")

    # Non-host nodes keep their original type colours
    for n in nodes:
        if n["type"] != "host":
            n.setdefault("hw_type", n["type"])
            n["hw_color"] = NODE_COLORS.get(n["type"], "#a8b5c1")
            n["hw_shape"] = "circle"


# ============================================================================
# Fat-tree topology builder
# ============================================================================
def build_fat_tree(k: int, depth: int) -> tuple[list[dict], list[tuple[str, str]]]:
    k = max(2, k - (k % 2))
    depth = max(1, min(depth, 3))
    half_k = k // 2
    nodes: list[dict[str, Any]] = []
    edges: list[tuple[str, str]] = []

    if depth == 1:
        nodes.append({"id": "sw_0", "type": "edge", "x": (k - 1) / 2.0, "y": 1})
        for h in range(k):
            nodes.append({"id": f"h_0_{h}", "type": "host", "x": float(h), "y": 0})
            edges.append(("sw_0", f"h_0_{h}"))
        return nodes, edges

    if depth == 2:
        n_edge = k
        n_hosts_per_edge = half_k
        for e in range(n_edge):
            for h in range(n_hosts_per_edge):
                hid = e * n_hosts_per_edge + h
                nodes.append({"id": f"h_{e}_{h}", "type": "host", "x": float(hid), "y": 0.0})
        for e in range(n_edge):
            xc = e * n_hosts_per_edge + (n_hosts_per_edge - 1) / 2.0
            nodes.append({"id": f"edge_{e}", "type": "edge", "x": xc, "y": 1.0})
            for h in range(n_hosts_per_edge):
                edges.append((f"edge_{e}", f"h_{e}_{h}"))
        total_w = n_edge * n_hosts_per_edge - 1
        for c in range(half_k):
            x = c * total_w / max(half_k - 1, 1)
            nodes.append({"id": f"core_{c}", "type": "core", "x": x, "y": 2.0})
            for e in range(n_edge):
                edges.append((f"core_{c}", f"edge_{e}"))
        return nodes, edges

    # depth == 3
    n_pods = k
    n_agg_per_pod = half_k
    n_edge_per_pod = half_k
    n_hosts_per_edge = half_k

    for pod in range(n_pods):
        for e in range(n_edge_per_pod):
            for h in range(n_hosts_per_edge):
                global_idx = (pod * n_edge_per_pod + e) * n_hosts_per_edge + h
                nodes.append({"id": f"h_{pod}_{e}_{h}", "type": "host", "x": float(global_idx), "y": 0.0, "pod": pod})

    def host_x(pod: int, e: int, h: int) -> float:
        return float((pod * n_edge_per_pod + e) * n_hosts_per_edge + h)

    def edge_x(pod: int, e: int) -> float:
        xs = [host_x(pod, e, h) for h in range(n_hosts_per_edge)]
        return sum(xs) / len(xs)

    for pod in range(n_pods):
        for e in range(n_edge_per_pod):
            nodes.append({"id": f"edge_{pod}_{e}", "type": "edge", "x": edge_x(pod, e), "y": 1.0, "pod": pod})
            for h in range(n_hosts_per_edge):
                edges.append((f"edge_{pod}_{e}", f"h_{pod}_{e}_{h}"))

    for pod in range(n_pods):
        pod_edge_xs = [edge_x(pod, e) for e in range(n_edge_per_pod)]
        x_min, x_max = min(pod_edge_xs), max(pod_edge_xs)
        for a in range(n_agg_per_pod):
            x = x_min + a * (x_max - x_min) / max(n_agg_per_pod - 1, 1)
            nodes.append({"id": f"agg_{pod}_{a}", "type": "aggregation", "x": x, "y": 2.0, "pod": pod})
            for e in range(n_edge_per_pod):
                edges.append((f"agg_{pod}_{a}", f"edge_{pod}_{e}"))

    n_core = half_k * half_k
    total_hosts = n_pods * n_edge_per_pod * n_hosts_per_edge
    total_w = total_hosts - 1
    for c in range(n_core):
        x = c * total_w / max(n_core - 1, 1)
        nodes.append({"id": f"core_{c}", "type": "core", "x": x, "y": 3.0})

    for m in range(half_k):
        for n in range(half_k):
            c = m * half_k + n
            for pod in range(n_pods):
                edges.append((f"core_{c}", f"agg_{pod}_{m}"))

    return nodes, edges


# ============================================================================
# Statistics
# ============================================================================
def compute_stats(k: int, depth: int) -> dict[str, int]:
    k = max(2, k - (k % 2))
    depth = max(1, min(depth, 3))
    half_k = k // 2

    if depth == 1:
        cables = k
        result = {"hosts": k, "switches": 1, "cables": cables, "transmitters": cables * 2, "switch_txs": k}

    elif depth == 2:
        c_sw_sw = half_k * k
        c_edge_h = k * half_k
        cables = c_sw_sw + c_edge_h
        result = {
            "hosts": k * half_k,
            "switches": half_k + k,
            "cables": cables,
            "transmitters": cables * 2,
            "switch_txs": c_sw_sw * 2 + c_edge_h,
        }

    else:
        n_core = half_k * half_k
        c_ca = n_core * k
        c_ae = k * half_k * half_k
        c_eh = k * half_k * half_k
        cables = c_ca + c_ae + c_eh
        result = {
            "hosts": k**3 // 4,
            "switches": n_core + k * half_k + k * half_k,
            "cables": cables,
            "transmitters": cables * 2,
            "switch_txs": (c_ca + c_ae) * 2 + c_eh,
        }

    return result


# ============================================================================
# Graph + path utilities
# ============================================================================
def build_adjacency(edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    return dict(adj)


def build_adjacency_with_failures(edges: list[tuple[str, str]], failed_nodes: list[str]) -> dict[str, list[str]]:
    """Build adjacency table excluding any edge that touches a failed node."""
    failed = set(failed_nodes or [])
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        if a not in failed and b not in failed:
            adj[a].append(b)
            adj[b].append(a)
    return dict(adj)


def find_all_paths(
    adj: dict[str, list[str]], src: str, dst: str, max_hops: int = 8, shortest_only: bool = True
) -> tuple[list[list[str]], int]:
    """
    Iterative DFS — finds all simple paths within max_hops edges.
    Returns (display_paths, total_count).
    When shortest_only=True, only minimum-hop paths are returned for display,
    but total_count reflects ALL simple paths found up to max_hops.
    """
    all_results: list[list[str]] = []
    stack = [(src, [src], {src})]
    while stack:
        node, path, visited = stack.pop()
        if len(path) - 1 >= max_hops:
            continue
        for nb in adj.get(node, []):
            if nb == dst:
                all_results.append(path + [dst])
            elif nb not in visited:
                stack.append((nb, path + [nb], visited | {nb}))
    all_results.sort(key=lambda p: (len(p), p))
    total = len(all_results)

    if shortest_only and all_results:
        min_hops = len(all_results[0]) - 1
        display = [p for p in all_results if len(p) - 1 == min_hops]
    else:
        display = all_results

    return display, total


def classify_path_type(src: str, dst: str) -> str:
    ps = src.split("_")
    pd = dst.split("_")
    if src == dst:
        return "SAME HOST"
    if len(ps) == 3 and ps[0] == "h" and ps[1] == "0":
        return "SAME SWITCH"
    if len(ps) == 3 and ps[0] == "h":
        return "SAME EDGE SWITCH" if ps[1] == pd[1] else "DIFFERENT EDGE SWITCH"
    if len(ps) == 4 and ps[0] == "h":
        if ps[1] == pd[1] and ps[2] == pd[2]:
            return "SAME EDGE SWITCH"
        if ps[1] == pd[1]:
            return "SAME POD"
        return "CROSS-POD"
    return "CONNECTED"


def fmt_node(nid: str) -> str:
    """Short human-readable node label."""
    p = nid.split("_")
    match p[0]:
        case "h":
            return "H[" + ".".join(p[1:]) + "]"
        case "edge":
            return "E[" + ".".join(p[1:]) + "]"
        case "agg":
            return "A[" + ".".join(p[1:]) + "]"
        case "core":
            return "C[" + ".".join(p[1:]) + "]"
        case "sw":
            return "SW[" + ".".join(p[1:]) + "]"
        case _:
            return nid


def path_colors(n: int) -> list[str]:
    """n visually distinct vibrant colors via golden-ratio HSV stepping."""
    golden = 0.618033988749895
    colors, hue = [], 0.08
    for _ in range(n):
        r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.80, 0.98)
        colors.append(f"rgb({int(r*255)},{int(g*255)},{int(b*255)})")
        hue += golden
    return colors


# ============================================================================
# Visual constants
# ============================================================================
NODE_COLORS = {
    "core": "#ff6b6b",
    "aggregation": "#4ecdc4",
    "edge": "#45b7d1",
    "host": "#a8b5c1",
}
NODE_SIZES = {"core": 18, "aggregation": 14, "edge": 12, "host": 7}
NODE_LABELS = {"core": "Core Switch", "aggregation": "Aggregation Switch", "edge": "Edge Switch", "host": "Host"}
LAYER_LABELS = {
    3: {0: "Hosts", 1: "Edge", 2: "Aggregation", 3: "Core"},
    2: {0: "Hosts", 1: "Edge", 2: "Core"},
    1: {0: "Hosts", 1: "Switch"},
}
PATH_BADGE = {
    "SAME SWITCH": ("#1a3a1a", "#4caf50"),
    "SAME EDGE SWITCH": ("#1a3a1a", "#4caf50"),
    "DIFFERENT EDGE SWITCH": ("#1e2a10", "#8bc34a"),
    "SAME POD": ("#2a2a10", "#ffc107"),
    "CROSS-POD": ("#3a1515", "#ef5350"),
    "CONNECTED": ("#102030", "#4ecdc4"),
}
NODE_TYPE_COLORS = {
    "h": "#a8b5c1",
    "edge": "#45b7d1",
    "agg": "#4ecdc4",
    "core": "#ff6b6b",
    "sw": "#45b7d1",
}


# ============================================================================
# Plotly figure builder
# ============================================================================
def util_to_color(util: float) -> str:
    """Map 0–100 utilisation to a CSS rgb string: green → amber → red."""
    u = max(0.0, min(1.0, util / 100.0))
    if u < 0.5:
        # green (0,200,100) → amber (255,165,0)
        r = int(u * 2 * 255)
        g = int(200 - u * 2 * (200 - 165))
        b = int(100 - u * 2 * 100)
    else:
        # amber (255,165,0) → red (220,50,50)
        t = (u - 0.5) * 2
        r = int(255 - t * 35)
        g = int(165 - t * 165)
        b = int(t * 50)
    return f"rgb({r},{g},{b})"


def make_figure(
    k: int,
    depth: int,
    selected: list[str] | None = None,
    paths: list[list[str]] | None = None,
    profile: "DatacenterProfile | None" = None,
    failed_nodes: list[str] | None = None,
    link_util: float = 0.0,
) -> go.Figure:

    nodes, edges = build_fat_tree(k, depth)
    # [NEW] Stamp hw_type / hw_color / hw_shape on every node
    assign_hw_types(nodes, profile)
    node_map = {n["id"]: n for n in nodes}
    selected = selected or []
    paths = paths or []
    failed_set = set(failed_nodes or [])
    selected_set = set(selected)
    colors = path_colors(len(paths))

    all_path_nodes: set[str] = {n for p in paths for n in p}

    has_paths = len(paths) > 0

    # ---- pod background bands (depth 3) ------------------------------------
    shapes = []
    if depth == 3:
        half_k = k // 2
        for pod in range(k):
            n_hpod = half_k * half_k
            x0, x1 = pod * n_hpod - 0.5, (pod + 1) * n_hpod - 0.5
            fill = "rgba(255,255,255,0.025)" if pod % 2 == 0 else "rgba(200,220,255,0.055)"
            shapes.append(
                {
                    "type": "rect",
                    "xref": "x",
                    "yref": "paper",
                    "x0": x0,
                    "x1": x1,
                    "y0": 0,
                    "y1": 1,
                    "fillcolor": fill,
                    "line_width": 0,
                    "layer": "below",
                }
            )

    # ---- edge traces: split into normal / congested / failed-adjacent --------
    normal_ex, normal_ey = [], []
    failed_ex, failed_ey = [], []

    edge_color = util_to_color(link_util) if link_util > 0 else None
    is_congested = link_util >= 80

    for a, b in edges:
        n1, n2 = node_map[a], node_map[b]
        seg_x = [n1["x"], n2["x"], None]
        seg_y = [n1["y"], n2["y"], None]
        if a in failed_set or b in failed_set:
            failed_ex += seg_x
            failed_ey += seg_y
        else:
            normal_ex += seg_x
            normal_ey += seg_y

    # Normal / utilisation-coloured cables
    normal_opacity = 0.10 if has_paths else 0.32
    if link_util > 0 and not has_paths:
        normal_opacity = 0.65  # make utilisation colour visible
    base_trace = go.Scatter(
        x=normal_ex,
        y=normal_ey,
        mode="lines",
        line={
            "color": edge_color if (link_util > 0 and not has_paths) else f"rgba(130,160,190,{normal_opacity})",
            "width": 1.1 if link_util > 0 else 0.7,
        },
        opacity=normal_opacity if not (link_util > 0 and not has_paths) else 1.0,
        hoverinfo="none",
        showlegend=False,
        name="",
    )
    # Failed-adjacent cables — dashed dark-red
    failed_edge_trace = go.Scatter(
        x=failed_ex,
        y=failed_ey,
        mode="lines",
        line={"color": "rgba(200,40,40,0.55)", "width": 0.9, "dash": "dot"},
        hoverinfo="none",
        showlegend=False,
        name="",
    )

    # ---- colored path edge traces (one per path) ---------------------------
    path_traces = []
    for _i, (path, color) in enumerate(zip(paths, colors)):
        px, py = [], []
        for j in range(len(path) - 1):
            n1, n2 = node_map[path[j]], node_map[path[j + 1]]
            px += [n1["x"], n2["x"], None]
            py += [n1["y"], n2["y"], None]
        path_traces.append(
            go.Scatter(
                x=px,
                y=py,
                mode="lines",
                line={"color": color, "width": 2.6},
                opacity=0.88,
                hoverinfo="none",
                showlegend=False,
            )
        )

    # ---- node traces — one trace per (type × hw_type) so shapes can differ --
    # Group host nodes by hw_type for separate Plotly traces (each trace has
    # one symbol). Switch-type nodes always use "circle".
    from collections import defaultdict as _dd

    node_traces = []

    # Separate hosts by hw_type; keep switches in their own groups
    hw_groups: dict[tuple, list[dict]] = _dd(list)
    for n in nodes:
        if n["type"] == "host":
            hw_groups[(n["type"], n.get("hw_type", "cpu"))].append(n)
        else:
            hw_groups[(n["type"], n["type"])].append(n)

    for (ntype, hw_key), grp in hw_groups.items():
        if not grp:
            continue

        # Legend label: switches use node type label; hosts show hw_type
        if ntype == "host":
            legend_label = f"Host · {hw_key.upper()}"
        else:
            legend_label = NODE_LABELS.get(ntype, ntype.capitalize())

        # Shape and base color for this group
        base_shape = HW_SHAPES.get(hw_key, "circle") if ntype == "host" else "circle"

        xs, ys, texts, hovers = [], [], [], []
        mcolors, msizes, mopacities, border_colors, border_widths, msymbols = [], [], [], [], [], []

        for n in grp:
            nid = n["id"]
            is_sel = nid in selected_set
            is_path = nid in all_path_nodes

            # [NEW] Use per-node hw_color for the base colour
            base_col = n.get("hw_color", NODE_COLORS.get(ntype, "#a8b5c1"))

            is_failed = nid in failed_set

            if is_failed:
                # Failed node: dark body, bright red border, X symbol
                col = "rgba(30,10,10,0.9)"
                sz = NODE_SIZES[ntype] * 1.6
                op = 0.95
                bc = "rgba(220,50,50,0.95)"
                bw = 2.8
                symbol = "x"
            elif is_sel:
                # [FIX] Keep hw_color so GPU stays yellow, TPU stays purple, etc.
                # Show selection via enlarged size + bright white border, NOT white fill.
                col = base_col
                sz = NODE_SIZES[ntype] * 2.4
                op = 1.0
                bc = "#ffffff"
                bw = 3.2
                symbol = base_shape  # hw_shape preserved
            elif is_path:
                col = next((colors[i] for i, p in enumerate(paths) if nid in p), base_col)
                sz = NODE_SIZES[ntype] * 1.55
                op = 1.0
                bc = "rgba(255,255,255,0.7)"
                bw = 1.8
                symbol = base_shape
            elif has_paths:
                col = "rgba(60,80,100,0.4)"
                sz = NODE_SIZES[ntype] * (0.8 if ntype == "host" else 0.9)
                op = 0.35
                bc = "rgba(80,100,120,0.3)"
                bw = 0.8
                symbol = base_shape
            else:
                col = base_col
                sz = NODE_SIZES[ntype]
                op = 1.0
                bc = "rgba(255,255,255,0.45)"
                bw = 1.1
                symbol = base_shape

            # Hover: show hw metadata for hosts; failure/selection flags
            failed_tag = "<br><b style='color:#f55'>⚠ FAILED</b>" if is_failed else ""
            sel_tag = "<br><b style='color:#ffe082'>● SELECTED</b>" if is_sel else ""
            if ntype == "host":
                hw = n.get("hw_type", "cpu")
                hw_color = n.get("hw_color", "#a8b5c1")
                hover_txt = (
                    f"<b>{nid}</b><br>"
                    f"<span style='color:{hw_color}'>▪ {hw.upper()}</span>"
                    f"  shape: {base_shape}"
                    f"{sel_tag}{failed_tag}"
                )
            else:
                hover_txt = f"<b>{nid}</b>{failed_tag}"
                if not is_failed:
                    hover_txt += "<br><i style='color:#4ecdc4'>Click to fail (sim mode)</i>"

            xs.append(n["x"])
            ys.append(n["y"])
            texts.append(nid)
            hovers.append(hover_txt)
            mcolors.append(col)
            msizes.append(sz)
            mopacities.append(op)
            border_colors.append(bc)
            border_widths.append(bw)
            msymbols.append(symbol)

        node_traces.append(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                name=legend_label,
                marker={
                    "color": mcolors,
                    "size": msizes,
                    "opacity": mopacities,
                    "symbol": msymbols,  # ← per-node shape list
                    "line": {"color": border_colors, "width": border_widths},
                },
                text=texts,
                customdata=hovers,
                hovertemplate="%{customdata}<extra></extra>",
            )
        )

    # ---- selection pulse rings around selected hosts -----------------------
    pulse_traces = []
    for sel_id in selected:
        temp_n = node_map.get(sel_id)
        if temp_n:
            n = temp_n
            # [FIX] pulse ring uses the node's own hw_shape so a GPU square
            # gets a square ring, a TPU diamond gets a diamond ring, etc.
            pulse_shape = n.get("hw_shape", "circle")
            pulse_traces.append(
                go.Scatter(
                    x=[n["x"]],
                    y=[n["y"]],
                    mode="markers",
                    marker={
                        "color": "rgba(0,0,0,0)",
                        "size": NODE_SIZES["host"] * 4.2,
                        "symbol": pulse_shape,
                        "line": {"color": "rgba(255,224,130,0.65)", "width": 1.8},
                    },
                    hoverinfo="none",
                    showlegend=False,
                    name="",
                )
            )

    # ---- annotations -------------------------------------------------------
    annotations = []
    all_xs = [n["x"] for n in nodes]
    left_x = (min(all_xs) - 1.8) if all_xs else -1.8

    for y_val, label in LAYER_LABELS.get(depth, {}).items():
        annotations.append(
            {
                "x": left_x,
                "y": float(y_val),
                "text": f"<b>{label}</b>",
                "showarrow": False,
                "font": {"size": 11, "color": "#8ba3b8", "family": "'IBM Plex Mono', monospace"},
                "xanchor": "right",
                "yanchor": "middle",
            }
        )

    if depth == 3:
        half_k = k // 2
        n_hpod = half_k * half_k
        for pod in range(k):
            cx = pod * n_hpod + (n_hpod - 1) / 2.0
            annotations.append(
                {
                    "x": cx,
                    "y": -0.35,
                    "text": f"Pod {pod}",
                    "showarrow": False,
                    "font": {"size": 9, "color": "rgba(160,180,210,0.55)", "family": "'IBM Plex Mono', monospace"},
                    "xanchor": "center",
                }
            )

    if len(selected) == 1:
        temp_n = node_map.get(selected[0])
        if temp_n:
            n = temp_n
            annotations.append(
                {
                    "x": n["x"],
                    "y": n["y"] + 0.28,
                    "text": f"<b>{fmt_node(selected[0])}</b><br>select destination",
                    "showarrow": True,
                    "arrowhead": 0,
                    "arrowcolor": "rgba(255,224,130,0.45)",
                    "ax": 0,
                    "ay": -30,
                    "font": {"size": 10, "color": "#ffe082", "family": "'IBM Plex Mono', monospace"},
                    "bgcolor": "rgba(18,28,42,0.88)",
                    "bordercolor": "rgba(255,224,130,0.4)",
                    "borderwidth": 1,
                    "borderpad": 4,
                }
            )

    # ---- congestion warning annotation (util >= 80%) -----------------------
    if is_congested:
        annotations.append(
            {
                "x": 0.5,
                "y": 1.05,
                "xref": "paper",
                "yref": "paper",
                "text": f"⚠  CONGESTION ALERT — Link utilisation at {link_util:.0f}%",
                "showarrow": False,
                "font": {"size": 11, "color": "#ff6b6b", "family": "'IBM Plex Mono', monospace"},
                "bgcolor": "rgba(80,10,10,0.7)",
                "bordercolor": "#ff6b6b",
                "borderwidth": 1,
                "borderpad": 6,
                "xanchor": "center",
            }
        )

    # ---- failed nodes counter annotation -----------------------------------
    if failed_set:
        annotations.append(
            {
                "x": 1.0,
                "y": 1.05,
                "xref": "paper",
                "yref": "paper",
                "text": f"✕  {len(failed_set)} node(s) failed",
                "showarrow": False,
                "font": {"size": 10, "color": "rgba(220,50,50,0.9)", "family": "'IBM Plex Mono', monospace"},
                "bgcolor": "rgba(40,5,5,0.75)",
                "bordercolor": "rgba(200,40,40,0.6)",
                "borderwidth": 1,
                "borderpad": 5,
                "xanchor": "right",
            }
        )

    y_range = [-0.55, depth + 0.55]
    fig = go.Figure(data=[base_trace, failed_edge_trace] + path_traces + pulse_traces + node_traces)
    fig.update_layout(
        annotations=annotations,
        shapes=shapes,
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 11, "color": "#c0d0e0", "family": "'IBM Plex Mono', monospace"},
            "bgcolor": "rgba(0,0,0,0)",
        },
        xaxis={"showgrid": False, "zeroline": False, "showticklabels": False, "showline": False},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False, "showline": False, "range": y_range},
        plot_bgcolor="#0d1117",
        paper_bgcolor="#0d1117",
        margin={"l": 110, "r": 30, "t": 40, "b": 50},
        height=520,
        hoverlabel={
            "bgcolor": "#1a2332",
            "bordercolor": "#4ecdc4",
            "font": {"color": "#e0f0ff", "family": "'IBM Plex Mono', monospace"},
        },
        dragmode="pan",
        uirevision=f"{k}-{depth}",  # preserve zoom across path selections
    )
    return fig


# ============================================================================
# Path analysis panel builder
# ============================================================================
def mono(txt: str, color: str = "#c9d9e8", size: str = "12px", weight: str = "400") -> html.Span:
    return html.Span(
        txt,
        style={
            "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": size,
            "color": color,
            "fontWeight": weight,
        },
    )


def build_path_panel(
    selected: list[str],
    paths: list[list[str]],
    total_paths: int = 0,
    shortest_only: bool = True,
    routing_mode: str = "shortest",
    path_costs: list[float] | None = None,
) -> html.Div:

    # ---- No selection -------------------------------------------------------
    if len(selected) == 0:
        return html.Div(
            [
                html.Div("◈", style={"fontSize": "40px", "color": "#1a2d42", "marginBottom": "14px"}),
                html.Div(
                    "CLICK ANY TWO HOST NODES",
                    style={
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "fontSize": "10px",
                        "letterSpacing": "0.18em",
                        "color": "#2d4a66",
                        "marginBottom": "10px",
                    },
                ),
                html.Div(
                    "All available routing paths between the selected "
                    "hosts will be traced and highlighted on the topology.",
                    style={
                        "color": "#3d5870",
                        "fontSize": "12px",
                        "maxWidth": "300px",
                        "lineHeight": "1.7",
                        "textAlign": "center",
                    },
                ),
            ],
            style={
                "display": "flex",
                "flexDirection": "column",
                "alignItems": "center",
                "justifyContent": "center",
                "padding": "48px 24px",
                "flex": "1",
            },
        )

    # ---- One host selected --------------------------------------------------
    if len(selected) == 1:
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            "SOURCE",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "letterSpacing": "0.18em",
                                "color": "#4e6880",
                                "marginBottom": "6px",
                            },
                        ),
                        html.Div(
                            fmt_node(selected[0]),
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "22px",
                                "fontWeight": "600",
                                "color": "#ffe082",
                            },
                        ),
                        html.Div("↓", style={"fontSize": "22px", "color": "#1e3350", "margin": "10px 0"}),
                        html.Div(
                            "SELECT DESTINATION",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "letterSpacing": "0.18em",
                                "color": "#2d4a66",
                            },
                        ),
                    ],
                    style={"textAlign": "center"},
                ),
            ],
            style={
                "display": "flex",
                "flexDirection": "column",
                "alignItems": "center",
                "justifyContent": "center",
                "padding": "48px 24px",
                "flex": "1",
            },
        )

    # ---- Two hosts selected: show paths ------------------------------------
    src, dst = selected[0], selected[1]
    ptype = classify_path_type(src, dst)
    badge_bg, badge_fg = PATH_BADGE.get(ptype, ("#102030", "#4ecdc4"))
    colors = path_colors(len(paths))
    hops = (len(paths[0]) - 1) if paths else 0

    # Build path rows
    path_costs = path_costs or []
    path_rows = []
    is_gpu_mode = routing_mode == "gpu_affinity"

    for i, (path, color) in enumerate(zip(paths, colors)):
        # Count core hops to explain the GPU-affinity cost
        n_core_hops = sum(1 for nid in path if nid.startswith("core_"))
        path_hops = len(path) - 1
        cost_val = path_costs[i] if i < len(path_costs) else None

        # Arrow-separated node labels with type-appropriate colors
        # Highlight core switches in red when gpu_affinity mode is active
        parts: list[Any] = []
        for j, nid in enumerate(path):
            ntype_key = nid.split("_")[0]
            nc = NODE_TYPE_COLORS.get(ntype_key, "#c9d9e8")
            # In GPU-affinity mode, highlight cross-pod core hops as expensive
            if is_gpu_mode and nid.startswith("core_"):
                nc = "#ff6b6b"
            parts.append(mono(fmt_node(nid), nc, "10px"))
            if j < len(path) - 1:
                parts.append(mono(" → ", "#1e3a52", "10px"))

        # Badge: show cost in GPU-affinity mode, hop count in normal mode
        if is_gpu_mode and cost_val is not None:
            badge_text = f"cost {int(cost_val)}"
            badge_color = "#ff6b6b" if n_core_hops > 0 else "#4ecdc4"
            badge_title = f"{path_hops}h · {n_core_hops} core hop{'s' if n_core_hops!=1 else ''}"
        else:
            badge_text = f"{path_hops}h"
            badge_color = "#2d4a66"
            badge_title = badge_text

        path_rows.append(
            html.Div(
                [
                    # ① Color dot + index
                    html.Div(
                        [
                            html.Div(
                                style={
                                    "width": "9px",
                                    "height": "9px",
                                    "borderRadius": "50%",
                                    "background": color,
                                    "flexShrink": "0",
                                    "marginTop": "1px",
                                }
                            ),
                            html.Span(
                                f"{i + 1:02d}",
                                style={
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "10px",
                                    "color": "#3d5870",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "flex-start",
                            "gap": "6px",
                            "minWidth": "34px",
                            "flexShrink": "0",
                        },
                    ),
                    # ② Node sequence (core hops red in GPU mode)
                    html.Div(
                        parts,
                        style={
                            "display": "flex",
                            "flexWrap": "wrap",
                            "alignItems": "center",
                            "lineHeight": "1.9",
                            "flex": "1",
                        },
                    ),
                    # ③ Cost / hop badge
                    html.Div(
                        [
                            html.Div(
                                badge_text,
                                style={
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "9px",
                                    "color": badge_color,
                                    "background": "#080d12",
                                    "borderRadius": "3px",
                                    "padding": "2px 5px",
                                },
                            ),
                            html.Div(
                                badge_title if is_gpu_mode else "",
                                style={
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "8px",
                                    "color": "#2d4a66",
                                    "background": "#080d12",
                                    "borderRadius": "3px",
                                    "padding": "1px 4px",
                                    "marginTop": "2px",
                                    "display": "block" if is_gpu_mode else "none",
                                },
                            ),
                        ],
                        style={
                            "flexShrink": "0",
                            "alignSelf": "flex-start",
                            "marginTop": "2px",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "flex-end",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "flex-start",
                    "gap": "10px",
                    "padding": "7px 12px",
                    "borderBottom": "1px solid #0c1520",
                },
            )
        )

    return html.Div(
        [
            # ── Summary header ─────────────────────────────────────────────────
            html.Div(
                [
                    # src / dst labels
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        "SRC",
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "8px",
                                            "letterSpacing": "0.15em",
                                            "color": "#4e6880",
                                        },
                                    ),
                                    html.Div(
                                        fmt_node(src),
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "15px",
                                            "fontWeight": "600",
                                            "color": "#ffe082",
                                            "marginTop": "1px",
                                        },
                                    ),
                                ]
                            ),
                            html.Div(
                                "⟶",
                                style={
                                    "color": "#1e3a52",
                                    "fontSize": "16px",
                                    "padding": "0 10px",
                                    "paddingTop": "14px",
                                },
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        "DST",
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "8px",
                                            "letterSpacing": "0.15em",
                                            "color": "#4e6880",
                                        },
                                    ),
                                    html.Div(
                                        fmt_node(dst),
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "15px",
                                            "fontWeight": "600",
                                            "color": "#80cbc4",
                                            "marginTop": "1px",
                                        },
                                    ),
                                ]
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center", "flex": "1"},
                    ),
                    # Stat chips
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        str(len(paths)),
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "28px",
                                            "fontWeight": "700",
                                            "color": "#4ecdc4",
                                            "lineHeight": "1",
                                        },
                                    ),
                                    html.Div(
                                        "paths",
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "8px",
                                            "letterSpacing": "0.1em",
                                            "color": "#4e6880",
                                            "marginTop": "2px",
                                        },
                                    ),
                                ],
                                style={"textAlign": "center"},
                            ),
                            html.Div(
                                style={"width": "1px", "height": "32px", "background": "#1a2840", "margin": "0 14px"}
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        str(hops),
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "28px",
                                            "fontWeight": "700",
                                            "color": "#45b7d1",
                                            "lineHeight": "1",
                                        },
                                    ),
                                    html.Div(
                                        "hops",
                                        style={
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "8px",
                                            "letterSpacing": "0.1em",
                                            "color": "#4e6880",
                                            "marginTop": "2px",
                                        },
                                    ),
                                ],
                                style={"textAlign": "center"},
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                    "padding": "12px 14px 10px",
                    "borderBottom": "1px solid #0f1c2a",
                    "gap": "10px",
                    "flexWrap": "wrap",
                },
            ),
            # ── Type badge + routing mode badge + reset hint ──────────────────
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                ptype,
                                style={
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "9px",
                                    "letterSpacing": "0.12em",
                                    "fontWeight": "600",
                                    "color": badge_fg,
                                    "background": badge_bg,
                                    "borderRadius": "3px",
                                    "padding": "3px 8px",
                                    "border": f"1px solid {badge_fg}40",
                                },
                            ),
                            # [NEW] Routing mode pill — changes appearance per mode
                            html.Div(
                                "⚡ GPU-AFFINITY" if routing_mode == "gpu_affinity" else "SHORTEST-HOP",
                                style={
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "9px",
                                    "letterSpacing": "0.1em",
                                    "fontWeight": "600",
                                    "color": "#f7dc6f" if routing_mode == "gpu_affinity" else "#4e6880",
                                    "background": "#1a1500" if routing_mode == "gpu_affinity" else "#0d1117",
                                    "borderRadius": "3px",
                                    "padding": "3px 8px",
                                    "border": (
                                        "1px solid #f7dc6f40" if routing_mode == "gpu_affinity" else "1px solid #1a2840"
                                    ),
                                },
                            ),
                        ],
                        style={"display": "flex", "gap": "6px", "alignItems": "center"},
                    ),
                    html.Div(
                        "click any host to reset",
                        style={
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "fontSize": "9px",
                            "color": "#1e3a52",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "padding": "5px 14px",
                    "background": "#090e15",
                    "borderBottom": "1px solid #0c1520",
                },
            ),
            # ── Path count info bar ─────────────────────────────────────────────
            html.Div(
                [
                    html.Span(
                        (
                            (
                                f"Showing {len(paths)} {'cheapest' if routing_mode == 'gpu_affinity' else 'shortest'} path{'s' if len(paths) != 1 else ''}"
                                + (
                                    f"  ·  {total_paths - len(paths)} {'costlier' if routing_mode == 'gpu_affinity' else 'longer'} hidden"
                                    if shortest_only and total_paths > len(paths)
                                    else ""
                                )
                            )
                            if shortest_only
                            else f"Showing all {total_paths} path{'s' if total_paths != 1 else ''}"
                        ),
                        style={"fontFamily": "'IBM Plex Mono', monospace", "fontSize": "9px", "color": "#2d4a66"},
                    ),
                ],
                style={"padding": "4px 12px", "background": "#080d12", "borderBottom": "1px solid #0c1520"},
            ),
            # ── Column headers ──────────────────────────────────────────────────
            html.Div(
                [
                    mono("#   ", "#1e3a52", "9px"),
                    mono("NODE SEQUENCE", "#1e3a52", "9px"),
                    mono("HOP", "#1e3a52", "9px"),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "padding": "5px 12px",
                    "background": "#090e15",
                    "borderBottom": "1px solid #0c1520",
                },
            ),
            # ── Scrollable path list ────────────────────────────────────────────
            html.Div(
                path_rows,
                style={
                    "maxHeight": "260px",
                    "overflowY": "auto",
                    "overflowX": "hidden",
                },
            ),
            # ── Node key ───────────────────────────────────────────────────────
            html.Div(
                [
                    mono("KEY  ", "#1e3a52", "9px"),
                    mono("H[pod.edge.host]  ", "#a8b5c1", "9px"),
                    mono("E[pod.edge]  ", "#45b7d1", "9px"),
                    mono("A[pod.agg]  ", "#4ecdc4", "9px"),
                    mono("C[core]", "#ff6b6b", "9px"),
                ],
                style={
                    "padding": "6px 14px",
                    "background": "#090e15",
                    "borderTop": "1px solid #0c1520",
                    "display": "flex",
                    "flexWrap": "wrap",
                },
            ),
        ],
        style={"display": "flex", "flexDirection": "column", "flex": "1"},
    )


# ============================================================================
# Dash app
# ============================================================================
app = dash.Dash(
    __name__,
    title="Fat Tree Visualizer",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

app.index_string = """<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;600&family=Space+Grotesk:wght@300;500;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #080d12;
            color: #c9d9e8;
            font-family: 'Space Grotesk', sans-serif;
            min-height: 100vh;
        }
        .rc-slider-track  { background-color: #4ecdc4 !important; }
        .rc-slider-handle { border-color: #4ecdc4 !important; background: #4ecdc4 !important; }
        .rc-slider-rail   { background-color: #1e2d3d !important; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #080d12; }
        ::-webkit-scrollbar-thumb { background: #1e2d3d; border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: #2a3f55; }
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
</html>"""


def stat_card(label: str, value: int, color: str = "#4ecdc4") -> html.Div:
    return html.Div(
        [
            html.Div(
                f"{value:,}",
                style={
                    "fontSize": "22px",
                    "fontWeight": "700",
                    "color": color,
                    "lineHeight": "1",
                    "fontFamily": "'IBM Plex Mono', monospace",
                },
            ),
            html.Div(
                label,
                style={
                    "fontSize": "9px",
                    "letterSpacing": "0.12em",
                    "textTransform": "uppercase",
                    "color": "#4e6880",
                    "marginTop": "3px",
                },
            ),
        ],
        style={
            "background": "#0d1821",
            "border": "1px solid #1a2840",
            "borderRadius": "6px",
            "padding": "8px 12px",
            "minWidth": "80px",
            "textAlign": "center",
        },
    )


CTRL_LABEL = {
    "color": "#8ba3b8",
    "fontSize": "11px",
    "letterSpacing": "0.1em",
    "textTransform": "uppercase",
    "marginBottom": "6px",
    "fontFamily": "'IBM Plex Mono', monospace",
}

app.layout = html.Div(
    [
        # ── Header ──────────────────────────────────────────────────────────────
        html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            "FAT TREE",
                            style={
                                "fontSize": "22px",
                                "fontWeight": "700",
                                "color": "#4ecdc4",
                                "letterSpacing": "0.08em",
                                "fontFamily": "'IBM Plex Mono', monospace",
                            },
                        ),
                        html.Span(
                            " VISUALIZER",
                            style={
                                "fontSize": "22px",
                                "fontWeight": "300",
                                "color": "#8ba3b8",
                                "letterSpacing": "0.08em",
                                "fontFamily": "'IBM Plex Mono', monospace",
                            },
                        ),
                    ]
                ),
                html.Div(
                    "Python 3.10 · Dash · Plotly  ·  port of h8liu/ftree-vis  ·  "
                    "click two host nodes to trace all paths",
                    style={
                        "fontSize": "10px",
                        "color": "#2d4a66",
                        "marginTop": "4px",
                        "fontFamily": "'IBM Plex Mono', monospace",
                    },
                ),
            ],
            style={"padding": "16px 24px 12px", "borderBottom": "1px solid #0f1c2a"},
        ),
        # ── Controls + Stats ────────────────────────────────────────────────────
        html.Div(
            [
                # [NEW] DC Profile Selector
                html.Div(
                    [
                        html.Div("Data Center Profile", style=CTRL_LABEL),
                        dcc.Dropdown(
                            id="dc-profile",
                            options=[{"label": p.name, "value": k} for k, p in PRESET_PROFILES.items()],
                            value="custom",
                            clearable=False,
                            style={
                                "background": "#090e15",
                                "color": "#4ecdc4",
                                "border": "1px solid #1a2840",
                                "borderRadius": "4px",
                                "fontSize": "11px",
                            },
                        ),
                    ],
                    style={"flex": "0 0 220px"},
                ),
                # [NEW] Routing Mode
                html.Div(
                    [
                        html.Div("Routing Mode", style=CTRL_LABEL),
                        dcc.RadioItems(
                            id="routing-mode",
                            options=[
                                {"label": "Shortest Hop", "value": "shortest"},
                                {"label": "GPU-Affinity", "value": "gpu_affinity"},
                            ],
                            value="shortest",
                            inline=True,
                            inputStyle={"marginRight": "4px"},
                            labelStyle={
                                "color": "#8ba3b8",
                                "fontSize": "10px",
                                "marginRight": "12px",
                                "fontFamily": "'IBM Plex Mono', monospace",
                            },
                        ),
                    ],
                    style={"flex": "0 0 260px"},
                ),
                html.Div(
                    [
                        html.Div("Ports per Switch  (k)", style=CTRL_LABEL),
                        dcc.Slider(
                            id="k-slider",
                            min=2,
                            max=12,
                            step=2,
                            value=4,
                            marks={
                                i: {"label": str(i), "style": {"color": "#8ba3b8", "fontSize": "11px"}}
                                for i in range(2, 14, 2)
                            },
                            tooltip={"placement": "top", "always_visible": False},
                        ),
                    ],
                    style={"flex": "1 1 180px", "minWidth": "150px"},
                ),
                html.Div(
                    [
                        html.Div("Tree Depth", style=CTRL_LABEL),
                        dcc.Slider(
                            id="depth-slider",
                            min=1,
                            max=3,
                            step=1,
                            value=3,
                            marks={
                                1: {"label": "1 — Star", "style": {"color": "#8ba3b8", "fontSize": "11px"}},
                                2: {"label": "2 — 2-Tier", "style": {"color": "#8ba3b8", "fontSize": "11px"}},
                                3: {"label": "3 — Fat Tree", "style": {"color": "#8ba3b8", "fontSize": "11px"}},
                            },
                            tooltip={"placement": "top", "always_visible": False},
                        ),
                    ],
                    style={"flex": "0 0 240px", "minWidth": "190px"},
                ),
                html.Div(
                    id="stats-row",
                    style={
                        "display": "flex",
                        "gap": "7px",
                        "flexWrap": "wrap",
                        "alignItems": "center",
                        "flex": "0 0 auto",
                    },
                ),
            ],
            style={
                "display": "flex",
                "alignItems": "flex-end",
                "gap": "26px",
                "flexWrap": "wrap",
                "padding": "14px 24px",
                "background": "#080d12",
                "borderBottom": "1px solid #0f1c2a",
            },
        ),
        # [NEW] ── Analytics Strip ────────────────────────────────────────────────
        html.Div(
            id="analytics-strip",
            style={
                "display": "flex",
                "gap": "10px",
                "flexWrap": "wrap",
                "padding": "8px 24px",
                "background": "#060b10",
                "borderBottom": "1px solid #0f1c2a",
                "fontSize": "10px",
                "fontFamily": "'IBM Plex Mono', monospace",
                "color": "#8ba3b8",
            },
        ),
        # [OVERRIDE] ── Profile Overrides Bar ────────────────────────────────────────
        html.Div(
            [
                # Label
                html.Div(
                    "PROFILE OVERRIDES",
                    style={
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "fontSize": "9px",
                        "letterSpacing": "0.14em",
                        "color": "#2d4a66",
                        "marginRight": "18px",
                        "whiteSpace": "nowrap",
                    },
                ),
                # Interconnect selector
                html.Div(
                    [
                        html.Div(
                            "INTERCONNECT",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "8px",
                                "letterSpacing": "0.1em",
                                "color": "#2d4a66",
                                "marginBottom": "4px",
                            },
                        ),
                        dcc.RadioItems(
                            id="interconnect-override",
                            options=[
                                {"label": "Ethernet", "value": "ethernet"},
                                {"label": "RoCE-v2", "value": "roce-v2"},
                                {"label": "InfiniBand", "value": "infiniband"},
                            ],
                            value="ethernet",
                            inline=True,
                            inputStyle={"marginRight": "4px"},
                            labelStyle={
                                "color": "#8ba3b8",
                                "fontSize": "10px",
                                "marginRight": "14px",
                                "fontFamily": "'IBM Plex Mono', monospace",
                            },
                        ),
                    ],
                    style={"flex": "0 0 auto"},
                ),
                # Separator
                html.Div(
                    style={
                        "width": "1px",
                        "height": "28px",
                        "background": "#1a2840",
                        "margin": "0 18px",
                    }
                ),
                # GPU fraction slider
                html.Div(
                    [
                        html.Div(
                            id="gpu-mix-label",
                            children="GPU MIX: GPU 0%  CPU 100%",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "letterSpacing": "0.08em",
                                "color": "#2d4a66",
                                "marginBottom": "4px",
                                "minWidth": "220px",
                            },
                        ),
                        dcc.Slider(
                            id="gpu-frac-slider",
                            min=0,
                            max=100,
                            step=5,
                            value=0,
                            marks={
                                0: {"label": "0%", "style": {"color": "#a8b5c1", "fontSize": "9px"}},
                                25: {"label": "25%", "style": {"color": "#a8b5c1", "fontSize": "9px"}},
                                50: {"label": "50%", "style": {"color": "#f7dc6f", "fontSize": "9px"}},
                                75: {"label": "75%", "style": {"color": "#f7dc6f", "fontSize": "9px"}},
                                100: {"label": "100%", "style": {"color": "#f7dc6f", "fontSize": "9px"}},
                            },
                            tooltip={"placement": "top", "always_visible": False},
                        ),
                    ],
                    style={"flex": "0 0 300px"},
                ),
                # Separator
                html.Div(
                    style={
                        "width": "1px",
                        "height": "28px",
                        "background": "#1a2840",
                        "margin": "0 18px",
                    }
                ),
                # Reset button
                html.Button(
                    "↺  Reset to Profile",
                    id="reset-overrides-btn",
                    n_clicks=0,
                    style={
                        "background": "#0d1821",
                        "color": "#4e6880",
                        "border": "1px solid #1a2840",
                        "borderRadius": "4px",
                        "padding": "3px 14px",
                        "fontSize": "10px",
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "cursor": "pointer",
                        "letterSpacing": "0.06em",
                    },
                ),
                # Live effect hint
                html.Div(
                    "→ affects  Switch Lat. · Power (est.) · node colours",
                    style={
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "fontSize": "9px",
                        "color": "#1e3a52",
                        "marginLeft": "auto",
                        "fontStyle": "italic",
                        "whiteSpace": "nowrap",
                    },
                ),
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "padding": "7px 24px",
                "background": "#030609",
                "borderBottom": "1px solid #0a1520",
                "flexWrap": "wrap",
                "gap": "4px",
                "minHeight": "44px",
            },
        ),
        # [SIM] ── Simulation Controls Bar ─────────────────────────────────────────
        html.Div(
            [
                # Mode toggle button
                html.Div(
                    [
                        html.Div(
                            "SIMULATION MODE",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "letterSpacing": "0.12em",
                                "color": "#2d4a66",
                                "marginRight": "10px",
                            },
                        ),
                        html.Button(
                            "OFF",
                            id="sim-toggle-btn",
                            n_clicks=0,
                            style={
                                "background": "#0d1821",
                                "color": "#4e6880",
                                "border": "1px solid #1a2840",
                                "borderRadius": "4px",
                                "padding": "3px 12px",
                                "fontSize": "10px",
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "cursor": "pointer",
                                "letterSpacing": "0.1em",
                            },
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center"},
                ),
                # Separator
                html.Div(
                    style={
                        "width": "1px",
                        "height": "28px",
                        "background": "#1a2840",
                        "margin": "0 18px",
                    }
                ),
                # Link utilisation label + slider
                html.Div(
                    [
                        html.Div(
                            id="util-label",
                            children="LINK UTIL: 0%",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "letterSpacing": "0.1em",
                                "color": "#2d4a66",
                                "marginBottom": "4px",
                                "minWidth": "130px",
                            },
                        ),
                        dcc.Slider(
                            id="util-slider",
                            min=0,
                            max=100,
                            step=5,
                            value=0,
                            marks={
                                0: {"label": "0%", "style": {"color": "#2d4a66", "fontSize": "9px"}},
                                50: {"label": "50%", "style": {"color": "#f7dc6f", "fontSize": "9px"}},
                                80: {"label": "80%", "style": {"color": "#ff6b6b", "fontSize": "9px"}},
                                100: {"label": "100%", "style": {"color": "#ff4444", "fontSize": "9px"}},
                            },
                            tooltip={"placement": "top", "always_visible": False},
                        ),
                    ],
                    style={"flex": "0 0 260px"},
                ),
                # Separator
                html.Div(
                    style={
                        "width": "1px",
                        "height": "28px",
                        "background": "#1a2840",
                        "margin": "0 18px",
                    }
                ),
                # Failed nodes counter + clear button
                html.Div(
                    [
                        html.Div(
                            id="failed-counter",
                            children="0 NODES FAILED",
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "10px",
                                "color": "#4e6880",
                                "marginRight": "12px",
                            },
                        ),
                        html.Button(
                            "CLEAR FAILURES",
                            id="clear-failures-btn",
                            n_clicks=0,
                            style={
                                "background": "#0d1821",
                                "color": "#4e6880",
                                "border": "1px solid #1a2840",
                                "borderRadius": "4px",
                                "padding": "3px 12px",
                                "fontSize": "10px",
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "cursor": "pointer",
                                "letterSpacing": "0.08em",
                            },
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center"},
                ),
                # Instructions (shown when sim mode is on)
                html.Div(
                    id="sim-instructions",
                    children="",
                    style={
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "fontSize": "9px",
                        "color": "#2d4a66",
                        "marginLeft": "auto",
                        "fontStyle": "italic",
                    },
                ),
            ],
            id="sim-controls-bar",
            style={
                "display": "flex",
                "alignItems": "center",
                "padding": "7px 24px",
                "background": "#04080d",
                "borderBottom": "1px solid #0a1520",
                "flexWrap": "wrap",
                "gap": "4px",
                "minHeight": "44px",
            },
        ),
        # [NEW] ── HW Type Legend ────────────────────────────────────────────────
        html.Div(
            [
                html.Span(
                    "HW TYPE LEGEND",
                    style={
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "fontSize": "8px",
                        "letterSpacing": "0.12em",
                        "color": "#2d4a66",
                        "marginRight": "14px",
                    },
                ),
            ]
            + [
                html.Div(
                    [
                        # SVG mini-icon matching Plotly shape
                        html.Div(
                            style={
                                "width": "10px",
                                "height": "10px",
                                "background": color,
                                "borderRadius": "2px" if shape == "square" else "50%" if shape == "circle" else "0",
                                "transform": (
                                    "rotate(45deg)"
                                    if shape == "diamond"
                                    else "none" if shape != "triangle-up" else "none"
                                ),
                                "clipPath": "polygon(50% 0%, 0% 100%, 100% 100%)" if shape == "triangle-up" else "none",
                                "flexShrink": "0",
                            }
                        ),
                        html.Span(
                            label,
                            style={
                                "fontFamily": "'IBM Plex Mono', monospace",
                                "fontSize": "9px",
                                "color": color,
                                "marginLeft": "5px",
                            },
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "marginRight": "16px"},
                )
                for label, color, shape in [
                    ("CPU  ●", "#a8b5c1", "circle"),
                    ("GPU  ■", "#f7dc6f", "square"),
                    ("TPU  ◆", "#bb8fce", "diamond"),
                    ("STORAGE  ▲", "#45b7d1", "triangle-up"),
                ]
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "padding": "5px 24px",
                "background": "#04080d",
                "borderBottom": "1px solid #0a1520",
                "flexWrap": "wrap",
                "gap": "4px",
            },
        ),
        # ── Main: graph left, path panel right ──────────────────────────────────
        html.Div(
            [
                # Graph
                html.Div(
                    dcc.Graph(
                        id="fat-tree-graph",
                        config={
                            "scrollZoom": True,
                            "displayModeBar": True,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                            "toImageButtonOptions": {"format": "svg", "filename": "fat_tree"},
                        },
                        style={"height": "530px"},
                    ),
                    style={"flex": "1 1 0", "minWidth": "0"},
                ),
                # Path panel
                html.Div(
                    [
                        # Panel header
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Span(
                                            "PATH",
                                            style={
                                                "fontFamily": "'IBM Plex Mono', monospace",
                                                "fontSize": "12px",
                                                "fontWeight": "600",
                                                "color": "#4ecdc4",
                                                "letterSpacing": "0.08em",
                                            },
                                        ),
                                        html.Span(
                                            " ANALYSIS",
                                            style={
                                                "fontFamily": "'IBM Plex Mono', monospace",
                                                "fontSize": "12px",
                                                "fontWeight": "300",
                                                "color": "#8ba3b8",
                                                "letterSpacing": "0.08em",
                                            },
                                        ),
                                    ]
                                ),
                                html.Div(
                                    [
                                        html.Span(
                                            "ALL",
                                            id="toggle-all-label",
                                            style={
                                                "fontFamily": "'IBM Plex Mono', monospace",
                                                "fontSize": "9px",
                                                "letterSpacing": "0.1em",
                                                "color": "#2d4a66",
                                            },
                                        ),
                                        html.Div(
                                            [
                                                html.Div(
                                                    id="toggle-knob",
                                                    style={
                                                        "width": "12px",
                                                        "height": "12px",
                                                        "borderRadius": "50%",
                                                        "background": "#4ecdc4",
                                                        "transition": "transform 0.2s",
                                                        "transform": "translateX(12px)",
                                                    },
                                                ),
                                            ],
                                            id="toggle-track",
                                            n_clicks=0,
                                            style={
                                                "width": "28px",
                                                "height": "16px",
                                                "borderRadius": "8px",
                                                "background": "#1a4a3a",
                                                "cursor": "pointer",
                                                "display": "flex",
                                                "alignItems": "center",
                                                "padding": "2px",
                                            },
                                        ),
                                        html.Span(
                                            "SHORTEST",
                                            id="toggle-short-label",
                                            style={
                                                "fontFamily": "'IBM Plex Mono', monospace",
                                                "fontSize": "9px",
                                                "letterSpacing": "0.1em",
                                                "color": "#4ecdc4",
                                            },
                                        ),
                                    ],
                                    style={"display": "flex", "alignItems": "center", "gap": "6px"},
                                ),
                            ],
                            style={
                                "padding": "9px 14px",
                                "background": "#090e15",
                                "borderBottom": "1px solid #0f1c2a",
                                "display": "flex",
                                "justifyContent": "space-between",
                                "alignItems": "center",
                            },
                        ),
                        # Dynamic body
                        html.Div(
                            id="path-panel",
                            style={"flex": "1", "overflowY": "auto", "display": "flex", "flexDirection": "column"},
                        ),
                    ],
                    style={
                        "width": "400px",
                        "flexShrink": "0",
                        "background": "#0d1117",
                        "border": "1px solid #131e2b",
                        "borderRadius": "6px",
                        "display": "flex",
                        "flexDirection": "column",
                        "margin": "10px 10px 10px 0",
                        "maxHeight": "550px",
                        "overflowY": "hidden",
                    },
                ),
            ],
            style={"display": "flex", "alignItems": "stretch", "padding": "10px 14px 0 14px", "gap": "0"},
        ),
        # ── Footer ──────────────────────────────────────────────────────────────
        html.Div(
            [
                html.Span(
                    "Al-Fares, Loukissas & Vahdat — A Scalable, Commodity Data Center "
                    "Network Architecture, SIGCOMM 2008",
                    style={"color": "#14243a", "fontSize": "10px"},
                ),
            ],
            style={"textAlign": "center", "padding": "12px 24px 16px"},
        ),
        # ── State stores ────────────────────────────────────────────────────────
        dcc.Store(
            id="selection-store",
            data={
                "hosts": [],
                "k": 4,
                "depth": 3,
                "shortest_only": True,
                "total_paths": 0,
                "dc_profile": "custom",
                "routing_mode": "shortest",
            },
        ),
        # [SIM] Simulation state store
        dcc.Store(id="sim-store", data={"sim_mode": False, "failed_nodes": [], "link_util": 0}),
        # [OVERRIDE] Live profile overrides store
        dcc.Store(id="overrides-store", data={"interconnect": "ethernet", "gpu_frac": 0.0}),
    ],
    style={"maxWidth": "1520px", "margin": "0 auto"},
)


# ============================================================================
# Callbacks
# ============================================================================
@callback(
    Output("selection-store", "data"),
    Output("toggle-knob", "style"),
    Output("toggle-track", "style"),
    Output("toggle-all-label", "style"),
    Output("toggle-short-label", "style"),
    Input("fat-tree-graph", "clickData"),
    Input("k-slider", "value"),
    Input("depth-slider", "value"),
    Input("toggle-track", "n_clicks"),
    Input("routing-mode", "value"),  # [NEW]
    State("selection-store", "data"),
)
def update_selection(
    click_data: Any, k: int, depth: int, n_clicks: Any, routing_mode: str, store: dict
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from dash import ctx

    triggered = ctx.triggered_id

    shortest_only = store.get("shortest_only", True)
    tp = store.get("total_paths", 0)

    if triggered == "toggle-track":
        shortest_only = not shortest_only
        store = {**store, "shortest_only": shortest_only}
    elif triggered == "routing-mode":
        # [FIX] Write the new routing mode into the store so render() picks it up
        store = {**store, "routing_mode": routing_mode}
    elif triggered in ("k-slider", "depth-slider"):
        store = {
            "hosts": [],
            "k": k,
            "depth": depth,
            "shortest_only": shortest_only,
            "total_paths": 0,
            "routing_mode": routing_mode,
            "dc_profile": store.get("dc_profile", "custom"),
        }
    elif triggered == "fat-tree-graph" and click_data:
        nid: str = click_data["points"][0].get("text", "")
        if nid.startswith("h_"):
            current: list[str] = store.get("hosts", [])
            if len(current) >= 2:
                store = {
                    "hosts": [nid],
                    "k": k,
                    "depth": depth,
                    "shortest_only": shortest_only,
                    "total_paths": 0,
                    "dc_profile": store.get("dc_profile", "custom"),
                    "routing_mode": store.get("routing_mode", "shortest"),
                }
            elif nid in current:
                # [FIX] preserve dc_profile + routing_mode so hw icons survive deselect
                store = {
                    "hosts": [h for h in current if h != nid],
                    "k": k,
                    "depth": depth,
                    "shortest_only": shortest_only,
                    "total_paths": tp,
                    "dc_profile": store.get("dc_profile", "custom"),
                    "routing_mode": store.get("routing_mode", "shortest"),
                }
            else:
                # [FIX] preserve dc_profile + routing_mode so hw icons survive selection
                store = {
                    "hosts": current + [nid],
                    "k": k,
                    "depth": depth,
                    "shortest_only": shortest_only,
                    "total_paths": tp,
                    "dc_profile": store.get("dc_profile", "custom"),
                    "routing_mode": store.get("routing_mode", "shortest"),
                }

    # Visual toggle state
    knob_s = {
        "width": "12px",
        "height": "12px",
        "borderRadius": "50%",
        "background": "#4ecdc4",
        "transition": "transform 0.2s",
        "transform": "translateX(12px)" if shortest_only else "translateX(0px)",
    }
    track_s = {
        "width": "28px",
        "height": "16px",
        "borderRadius": "8px",
        "background": "#1a4a3a" if shortest_only else "#1a2840",
        "cursor": "pointer",
        "display": "flex",
        "alignItems": "center",
        "padding": "2px",
        "transition": "background 0.2s",
    }
    all_lbl = {
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "9px",
        "letterSpacing": "0.1em",
        "color": "#2d4a66" if shortest_only else "#4ecdc4",
        "transition": "color 0.2s",
    }
    short_lbl = {
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "9px",
        "letterSpacing": "0.1em",
        "color": "#4ecdc4" if shortest_only else "#2d4a66",
        "transition": "color 0.2s",
    }
    return store, knob_s, track_s, all_lbl, short_lbl


@callback(
    Output("fat-tree-graph", "figure"),
    Output("stats-row", "children"),
    Output("path-panel", "children"),
    Input("selection-store", "data"),
    Input("k-slider", "value"),
    Input("depth-slider", "value"),
    Input("sim-store", "data"),
    Input("overrides-store", "data"),  # [OVERRIDE]
)
def render(store: dict, k: int, depth: int, sim: dict, overrides: dict) -> tuple[go.Figure, list[html.Div], html.Div]:
    selected: list[str] = store.get("hosts", [])
    paths: list[list[str]] = []
    total_paths = 0

    # Read profile from store — guaranteed consistent with k/depth
    profile_key = store.get("dc_profile", "custom")
    profile = apply_overrides(PRESET_PROFILES.get(profile_key, PRESET_PROFILES["custom"]), overrides or {})

    # [SIM] Simulation state
    sim = sim or {}
    failed_nodes: list[str] = sim.get("failed_nodes", [])
    link_util: float = float(sim.get("link_util", 0))

    path_costs: list[float] = []
    routing_mode = store.get("routing_mode", "shortest")

    if len(selected) == 2:
        _, topo_edges = build_fat_tree(k, depth)
        adj = build_adjacency_with_failures(topo_edges, failed_nodes)
        if routing_mode == "gpu_affinity":
            topo_nodes, _ = build_fat_tree(k, depth)
            assign_hw_types(topo_nodes, profile)
            nmap = {n["id"]: n for n in topo_nodes}
            paths, total_paths, path_costs = find_paths_weighted(
                adj,
                nmap,
                selected[0],
                selected[1],
                max_hops=10,
                gpu_affinity=True,
                cheapest_only=True,
            )
        else:
            paths, total_paths = find_all_paths(
                adj,
                selected[0],
                selected[1],
                max_hops=8,
                shortest_only=store.get("shortest_only", True),
            )

    stats = compute_stats(k, depth)
    stat_cards = [
        stat_card("Hosts", stats["hosts"], "#ff6b6b"),
        stat_card("Switches", stats["switches"], "#4ecdc4"),
        stat_card("Cables", stats["cables"], "#45b7d1"),
        stat_card("Transmitters", stats["transmitters"], "#f7dc6f"),
        stat_card("Switch Tx's", stats["switch_txs"], "#bb8fce"),
    ]

    return (
        make_figure(k, depth, selected, paths, profile, failed_nodes, link_util),
        stat_cards,
        build_path_panel(
            selected,
            paths,
            total_paths,
            store.get("shortest_only", True),
            routing_mode=routing_mode,
            path_costs=path_costs,
        ),
    )


# ============================================================================
# [NEW] Callbacks — DC profile sync + Analytics strip
# ============================================================================
@callback(
    Output("k-slider", "value"),
    Output("depth-slider", "value"),
    Output("selection-store", "data", allow_duplicate=True),
    Output("overrides-store", "data", allow_duplicate=True),  # [OVERRIDE] seed on profile change
    Output("interconnect-override", "value"),  # [OVERRIDE] sync radio to profile
    Output("gpu-frac-slider", "value"),  # [OVERRIDE] sync slider to profile
    Input("dc-profile", "value"),
    State("k-slider", "value"),
    State("depth-slider", "value"),
    State("selection-store", "data"),
    prevent_initial_call=True,
)
def sync_profile(profile_key: str, cur_k: int, cur_d: int, store: dict) -> tuple[int, int, dict, dict, str, int]:
    """
    When a DC profile is selected:
      1. Update k/depth sliders to match the profile.
      2. Write profile_key into selection-store.
      3. Reset overrides-store to the new profile's defaults.
      4. Sync override controls to the profile defaults.
    """
    p = PRESET_PROFILES.get(profile_key) or PRESET_PROFILES["custom"]
    new_store = {**store, "dc_profile": profile_key, "hosts": []}

    # Seed overrides from the profile's own values
    gpu_frac = (p.hw_mix or {}).get("gpu", 0.0)
    new_overrides = {
        "interconnect": p.interconnect,
        "gpu_frac": gpu_frac,
    }

    if profile_key == "custom":
        return cur_k, cur_d, new_store, new_overrides, p.interconnect, int(gpu_frac * 100)

    k_clamped = max(2, min(p.k, 12))
    d_clamped = max(1, min(p.depth, 3))
    new_store["k"] = k_clamped
    new_store["depth"] = d_clamped
    return k_clamped, d_clamped, new_store, new_overrides, p.interconnect, int(gpu_frac * 100)


@callback(
    Output("analytics-strip", "children"),
    Input("k-slider", "value"),
    Input("depth-slider", "value"),
    Input("selection-store", "data"),
    Input("overrides-store", "data"),  # [OVERRIDE]
)
def update_analytics(k: int, depth: int, store: dict, overrides: dict) -> list:
    """Recompute and render the analytics metrics strip."""
    nodes, edges = build_fat_tree(k, depth)
    profile_key = store.get("dc_profile", "custom")
    profile = apply_overrides(PRESET_PROFILES.get(profile_key, PRESET_PROFILES["custom"]), overrides or {})
    m = compute_analytics(nodes, edges, profile)

    def chip(label: Any, value: Any, color: str = "#4ecdc4") -> html.Div:
        return html.Div(
            [
                html.Span(label + ": ", style={"color": "#2d4a66"}),
                html.Span(str(value), style={"color": color, "fontWeight": "600"}),
            ],
            style={
                "background": "#0d1117",
                "border": "1px solid #131e2b",
                "borderRadius": "4px",
                "padding": "3px 10px",
            },
        )

    return [
        chip("Profile", profile.name, "#bb8fce"),
        chip("Bisection BW", f"{m['bisection_tbps']} Tbps", "#4ecdc4"),
        chip("Oversub", f"{m['oversubscription']}:1", "#f7dc6f"),
        chip("GPU Paths", m["avg_gpu_paths"], "#ff6b6b"),
        chip("Power (est.)", f"{m['total_power_mw']} MW", "#45b7d1"),
        chip("Switch Lat.", f"{m['switch_lat_ns']} ns", "#8ba3b8"),
        chip("Link Speed", f"{m['port_speed_gbps']} Gbps", "#4ecdc4"),
        chip("Interconnect", m["interconnect"], "#bb8fce"),
    ]


# ============================================================================
# [OVERRIDE] Profile overrides callback
# ============================================================================
@callback(
    Output("overrides-store", "data"),
    Output("gpu-mix-label", "children"),
    Output("gpu-mix-label", "style"),
    Input("interconnect-override", "value"),
    Input("gpu-frac-slider", "value"),
    Input("reset-overrides-btn", "n_clicks"),
    State("dc-profile", "value"),
    State("overrides-store", "data"),
    prevent_initial_call=False,
)
def update_overrides(
    interconnect: Any, gpu_pct: Any, reset_clicks: Any, profile_key: Any, current_overrides: Any
) -> tuple[dict, str, dict]:
    """Write interconnect and gpu_frac into overrides-store; reset to profile defaults on button."""
    from dash import ctx

    triggered = ctx.triggered_id

    if triggered == "reset-overrides-btn" or triggered is None:
        # Reset controls to the currently selected profile's values
        p = PRESET_PROFILES.get(profile_key or "custom", PRESET_PROFILES["custom"])
        gf = (p.hw_mix or {}).get("gpu", 0.0)
        new_overrides = {"interconnect": p.interconnect, "gpu_frac": gf}
        gpu_pct_effective = int(gf * 100)
        ic_effective = p.interconnect
    else:
        gf = (gpu_pct or 0) / 100.0
        ic_effective = interconnect or "ethernet"
        new_overrides = {"interconnect": ic_effective, "gpu_frac": gf}
        gpu_pct_effective = int(gf * 100)

    cpu_pct = 100 - gpu_pct_effective
    label = f"GPU MIX: GPU {gpu_pct_effective}%  CPU {cpu_pct}%"

    # Colour the label based on gpu fraction
    label_color = "#f7dc6f" if gpu_pct_effective >= 50 else "#4ecdc4" if gpu_pct_effective >= 10 else "#a8b5c1"
    label_style = {
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "9px",
        "letterSpacing": "0.08em",
        "color": label_color,
        "marginBottom": "4px",
        "minWidth": "220px",
        "fontWeight": "600" if gpu_pct_effective > 0 else "400",
    }

    return new_overrides, label, label_style


# ============================================================================
# [SIM] Simulation callbacks
# ============================================================================
@callback(
    Output("sim-store", "data"),
    Output("sim-toggle-btn", "children"),
    Output("sim-toggle-btn", "style"),
    Output("failed-counter", "children"),
    Output("failed-counter", "style"),
    Output("sim-instructions", "children"),
    Output("util-label", "children"),
    Input("sim-toggle-btn", "n_clicks"),
    Input("clear-failures-btn", "n_clicks"),
    Input("fat-tree-graph", "clickData"),
    Input("util-slider", "value"),
    Input("k-slider", "value"),
    Input("depth-slider", "value"),
    State("sim-store", "data"),
    prevent_initial_call=False,
)
def update_sim_store(
    toggle_clicks: Any, clear_clicks: Any, click_data: Any, util_val: Any, k: Any, depth: Any, sim: Any
) -> tuple[dict, str, dict, str, dict, str, str]:
    """Master simulation callback — handles mode toggle, click-to-fail, clear, and util slider."""
    from dash import ctx

    sim = sim or {"sim_mode": False, "failed_nodes": [], "link_util": 0}
    triggered = ctx.triggered_id

    sim_mode = sim.get("sim_mode", False)
    failed = list(sim.get("failed_nodes", []))
    link_util = sim.get("link_util", 0)

    # ── Toggle simulation mode ───────────────────────────────────────────────
    if triggered == "sim-toggle-btn":
        sim_mode = not sim_mode
        if not sim_mode:
            failed = []  # clear failures when turning off

    # ── Clear failures ───────────────────────────────────────────────────────
    elif triggered == "clear-failures-btn":
        failed = []

    # ── Topology change → reset failures ────────────────────────────────────
    elif triggered in ("k-slider", "depth-slider"):
        failed = []
        sim_mode = False

    # ── Click on graph → add/remove switch from failed set ──────────────────
    elif triggered == "fat-tree-graph" and click_data and sim_mode:
        nid = click_data["points"][0].get("text", "")
        # Only switches (non-host) can be failed via click in sim mode
        if nid and not nid.startswith("h_"):
            if nid in failed:
                failed.remove(nid)  # second click un-fails it
            else:
                failed.append(nid)

    # ── Utilisation slider ───────────────────────────────────────────────────
    elif triggered == "util-slider":
        link_util = util_val if util_val is not None else 0

    new_sim = {"sim_mode": sim_mode, "failed_nodes": failed, "link_util": link_util}

    # ── Build UI feedback ────────────────────────────────────────────────────
    btn_label = "ON  ●" if sim_mode else "OFF"
    btn_style = {
        "background": "#0a2010" if sim_mode else "#0d1821",
        "color": "#4ecdc4" if sim_mode else "#4e6880",
        "border": "1px solid #4ecdc4" if sim_mode else "1px solid #1a2840",
        "borderRadius": "4px",
        "padding": "3px 12px",
        "fontSize": "10px",
        "fontFamily": "'IBM Plex Mono', monospace",
        "cursor": "pointer",
        "letterSpacing": "0.1em",
        "fontWeight": "600" if sim_mode else "400",
    }

    n_failed = len(failed)
    ctr_label = f"{n_failed} NODE{'S' if n_failed != 1 else ''} FAILED"
    ctr_style = {
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "10px",
        "color": "#ef5350" if n_failed > 0 else "#4e6880",
        "marginRight": "12px",
        "fontWeight": "600" if n_failed > 0 else "400",
    }

    instructions = "⚡ Click any SWITCH to fail it — click again to restore" if sim_mode else ""

    # util_color = "#ef5350" if link_util >= 80 else "#f7dc6f" if link_util >= 50 else "#4ecdc4"
    util_label = f"LINK UTIL: {link_util}%"

    return new_sim, btn_label, btn_style, ctr_label, ctr_style, instructions, util_label


@callback(
    Output("util-label", "style"),
    Input("util-slider", "value"),
)
def update_util_label_color(util_val: int) -> dict:
    """Colour the utilisation label to match congestion level."""
    util_val = util_val or 0
    color = "#ef5350" if util_val >= 80 else "#f7dc6f" if util_val >= 50 else "#4ecdc4" if util_val > 0 else "#2d4a66"
    return {
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "9px",
        "letterSpacing": "0.1em",
        "color": color,
        "marginBottom": "4px",
        "minWidth": "130px",
        "fontWeight": "600" if util_val >= 80 else "400",
    }


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
