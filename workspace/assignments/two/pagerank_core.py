################################################################################
#  Filename:      two/pagerank_core.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, February 27th 2026, 4:22:42 am                       #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday February 27th 2026 7:09:26 am                         #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
PageRank: Iterative vs Closed-Form
===================================
Implements:
  1. Iterative power-method PageRank (production-style)
  2. Closed-form PageRank via matrix inverse (small graphs)
  3. Analysis of how p (teleport probability) affects ranks
  4. Evaluation on web-Google_10k.txt
"""

import time
from collections import defaultdict
from typing import Any

import numpy as np
import scipy.sparse as sp

# ─────────────────────────────────────────────────────────────
# I.  GRAPH LOADING
# ─────────────────────────────────────────────────────────────


def load_graph(filepath: str) -> tuple[list[tuple[int, int]], list[int], dict[int, int]]:
    """
    Parse a tab-separated edge-list (Google contest format).
    Returns:
        edges       : list of (src, dst) ints
        node_ids    : sorted list of all unique node ids
        id_to_idx   : dict mapping original id -> 0-based index
    """
    edges, nodes = [], set()
    with open(filepath) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split()
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                edges.append((u, v))
                nodes.update([u, v])

    node_ids = sorted(nodes)
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    return edges, node_ids, id_to_idx


def build_sparse_transition(edges: Any, node_ids: Any, id_to_idx: Any) -> tuple[sp.csc_matrix, np.ndarray]:
    """
    Build a column-stochastic sparse transition matrix H (CSC format).
    Dangling nodes (out-degree 0) are handled by the power iteration.
    """
    n = len(node_ids)
    out_degree: dict[int, int] = defaultdict(int)
    for u, _ in edges:
        out_degree[id_to_idx[u]] += 1

    rows, cols, data = [], [], []
    for u, v in edges:
        ui, vi = id_to_idx[u], id_to_idx[v]
        if out_degree[ui] > 0:
            rows.append(vi)
            cols.append(ui)
            data.append(1.0 / out_degree[ui])

    H = sp.csc_matrix((data, (rows, cols)), shape=(n, n))
    dangling_mask = np.array([out_degree[i] == 0 for i in range(n)])
    return H, dangling_mask


# ─────────────────────────────────────────────────────────────
# II.  ITERATIVE PAGERANK (power method)
# ─────────────────────────────────────────────────────────────


def pagerank_iterative(
    H: Any, dangling_mask: Any, p: float = 0.15, tol: float = 1e-10, max_iter: int = 500
) -> tuple[np.ndarray, int]:
    """
    Google PageRank power method.

    The Google matrix is:
        G = (1-p)*H' + p*(1/n)*E  +  dangling correction

    where H' is the column-stochastic hyperlink matrix,
    E is an all-ones matrix / n (teleportation),
    and dangling nodes re-distribute their rank uniformly.

    The stationary distribution π satisfies  G π = π.

    Parameters
    ----------
    p : float   – teleportation probability (default 0.15)
    tol : float – L1 convergence threshold

    Returns
    -------
    ranks : np.ndarray  – PageRank vector (sums to 1)
    iters : int         – number of iterations until convergence
    """
    n = H.shape[0]
    rank = np.full(n, 1.0 / n)
    teleport = np.full(n, p / n)

    for it in range(1, max_iter + 1):
        # Dangling nodes send their mass to all nodes uniformly
        dangling_mass = rank[dangling_mask].sum()

        new_rank = (1 - p) * H.dot(rank) + (1 - p) * dangling_mass / n + teleport

        if np.abs(new_rank - rank).sum() < tol:
            return new_rank, it
        rank = new_rank

    return rank, max_iter


# ─────────────────────────────────────────────────────────────
# III.  CLOSED-FORM PAGERANK  (small graphs only)
# ─────────────────────────────────────────────────────────────
#
#  Derivation summary
#  ------------------
#  The Google matrix (ignoring dangling nodes for clarity):
#
#      G = (1-p) * M  +  (p/n) * E_n
#
#  where M is the column-stochastic link matrix, E_n = 11^T / n.
#
#  PageRank π is the dominant eigenvector: G π = π, ||π||_1 = 1.
#
#  Re-arrange:
#      π - (1-p) M π = (p/n) E_n π
#      [I - (1-p) M] π = (p/n) 1      (since E_n π = 1 * 1/n ... no)
#
#  More carefully, since 1^T π = 1:
#      E_n π = (1/n) * 1   (each row of E_n is 1/n, summed = 1·(1/n) not right)
#
#  E_n is n×n all-ones/n matrix, so  E_n π = (1^T π / n) * 1 = (1/n)*1
#
#  Therefore:
#      π = [I - (1-p) M]^{-1}  (p/n) 1
#
#  Which gives the closed form:
#
#      π = (p/n) * [I - (1-p) M]^{-1} * 1_n
#
#  Then normalise so ||π||_1 = 1 (the formula already gives a probability
#  vector when M is column-stochastic and the graph is strongly connected,
#  but we normalise for safety with dangling / non-square matrices).


def pagerank_closed_form(M_dense: np.ndarray, p: float = 0.15) -> np.ndarray:
    """
    Closed-form PageRank:  π = (p/n) [I - (1-p)M]^{-1} 1_n

    M_dense : n×n dense column-stochastic matrix (SMALL graphs only)
    p       : teleportation probability

    Returns normalised PageRank vector.
    """
    n = M_dense.shape[0]
    A = np.eye(n) - (1 - p) * M_dense  # [I - (1-p)M]
    ones = np.ones(n)
    pi = np.linalg.solve(A, ones) * (p / n)  # solve linear system
    pi = pi / pi.sum()  # normalise
    return pi


# ─────────────────────────────────────────────────────────────
# IV.  EFFECT OF p ON PAGERANK  (illustrative examples)
# ─────────────────────────────────────────────────────────────


def analyse_p_effect() -> None:
    """
    Illustrate how teleportation probability p changes PageRank on toy graphs.

    Graph 1 – "Star": node 0 is a hub (many in-links)
    Graph 2 – "Loop + outlier": one disconnected node
    """
    print("=" * 60)
    print("EFFECT OF TELEPORTATION PROBABILITY p ON PAGERANK")
    print("=" * 60)

    # Graph 1: 4 nodes, node 0 is the hub
    # Edges (directed): 1->0, 2->0, 3->0, 0->1
    #          0 1 2 3
    M_star = np.array(
        [
            [0, 1, 1, 1],  # node 0 receives from 1,2,3
            [1, 0, 0, 0],  # node 1 receives from 0
            [0, 0, 0, 0],  # node 2 – dangling (we'll handle via uniform)
            [0, 0, 0, 0],  # node 3 – dangling
        ],
        dtype=float,
    )
    # Normalise columns (col-stochastic). Dangling cols -> uniform.
    col_sums = M_star.sum(axis=0)
    for j in range(4):
        if col_sums[j] == 0:
            M_star[:, j] = 1.0 / 4
        else:
            M_star[:, j] /= col_sums[j]

    print("\nGraph 1 (Star hub): edges 1→0, 2→0, 3→0, 0→1")
    print(f"{'p':>6}  {'π(hub=0)':>10}  {'π(1)':>8}  {'π(2)':>8}  {'π(3)':>8}")
    for p in [0.01, 0.10, 0.15, 0.30, 0.50, 0.85, 0.99]:
        pi = pagerank_closed_form(M_star, p)
        print(f"{p:6.2f}  {pi[0]:10.4f}  {pi[1]:8.4f}  {pi[2]:8.4f}  {pi[3]:8.4f}")

    print()
    # Graph 2: 3-node loop (0→1→2→0) + isolated node 3
    M_loop = np.zeros((4, 4))
    M_loop[1, 0] = 1
    M_loop[2, 1] = 1
    M_loop[0, 2] = 1
    col_sums = M_loop.sum(axis=0)
    for j in range(4):
        if col_sums[j] == 0:
            M_loop[:, j] = 1.0 / 4
        else:
            M_loop[:, j] /= col_sums[j]

    print("Graph 2 (Loop 0→1→2→0, node 3 isolated):")
    print(f"{'p':>6}  {'π(0)':>8}  {'π(1)':>8}  {'π(2)':>8}  {'π(3=isolated)':>14}")
    for p in [0.01, 0.10, 0.15, 0.30, 0.50, 0.85, 0.99]:
        pi = pagerank_closed_form(M_loop, p)
        print(f"{p:6.2f}  {pi[0]:8.4f}  {pi[1]:8.4f}  {pi[2]:8.4f}  {pi[3]:14.4f}")

    print()
    print("KEY INSIGHT:")
    print("  p→0  : ranks concentrate on link structure (hub dominates / loop equalises).")
    print("  p=0.15: Google's original setting balances structure & exploration.")
    print("  p→1  : all ranks converge to 1/n (pure random jump, no link signal).")
    print()


# ─────────────────────────────────────────────────────────────
# V.  EVALUATE ON WEB-GOOGLE_10K
# ─────────────────────────────────────────────────────────────


def evaluate_large_graph(
    filepath: str, p: float = 0.15, top_k: int = 20
) -> tuple[np.ndarray, list[int], dict[int, int]]:
    print("=" * 60)
    print(f"PAGERANK ON: {filepath}")
    print("=" * 60)

    t0 = time.time()
    edges, node_ids, id_to_idx = load_graph(filepath)
    n = len(node_ids)
    print(f"Nodes: {n:,}  |  Edges: {len(edges):,}  |  Load: {time.time()-t0:.2f}s")

    t1 = time.time()
    H, dangling_mask = build_sparse_transition(edges, node_ids, id_to_idx)
    ranks, iters = pagerank_iterative(H, dangling_mask, p=p)
    t2 = time.time()
    print(f"Converged in {iters} iterations  |  Time: {t2-t1:.3f}s")
    print(f"Rank sum (should be ~1.0): {ranks.sum():.8f}")

    # Top-k nodes
    idx_sorted = np.argsort(ranks)[::-1][:top_k]
    print(f"\nTop-{top_k} pages (p={p}):")
    print(f"  {'Rank':>5}  {'NodeID':>10}  {'PageRank':>12}")
    for rank_pos, i in enumerate(idx_sorted, 1):
        print(f"  {rank_pos:>5}  {node_ids[i]:>10}  {ranks[i]:12.8f}")

    return ranks, node_ids, id_to_idx


# ─────────────────────────────────────────────────────────────
# VI.  NUMERICAL COMPARISON: iterative vs closed-form
# ─────────────────────────────────────────────────────────────


def compare_methods(filepath: str, p: float = 0.15, sample_size: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """
    Compare iterative PageRank with closed-form on a small subgraph sample.
    Closed-form is O(n^3) so we cap at sample_size nodes.
    """
    print("=" * 60)
    print("NUMERICAL COMPARISON: Iterative vs Closed-Form")
    print("=" * 60)

    edges, node_ids, id_to_idx = load_graph(filepath)
    # n_all = len(node_ids)

    # Take induced subgraph on first `sample_size` nodes by index
    sampled_ids = set(node_ids[:sample_size])
    sub_edges = [(u, v) for u, v in edges if u in sampled_ids and v in sampled_ids]
    sub_node_ids = sorted(sampled_ids)
    sub_id_to_idx = {nid: i for i, nid in enumerate(sub_node_ids)}
    n = len(sub_node_ids)

    print(f"Subgraph: {n} nodes, {len(sub_edges)} edges  (p={p})")

    # --- Iterative ---
    H, dangling_mask = build_sparse_transition(sub_edges, sub_node_ids, sub_id_to_idx)
    pi_iter, iters = pagerank_iterative(H, dangling_mask, p=p, tol=1e-12)

    # --- Closed-form: build dense M with dangling → uniform ---
    out_deg: dict[int, int] = defaultdict(int)
    for u, _ in sub_edges:
        out_deg[sub_id_to_idx[u]] += 1

    M_dense = np.zeros((n, n))
    for u, v in sub_edges:
        ui, vi = sub_id_to_idx[u], sub_id_to_idx[v]
        M_dense[vi, ui] += 1.0 / out_deg[ui]
    for j in range(n):
        if out_deg[j] == 0:
            M_dense[:, j] = 1.0 / n  # dangling → uniform

    pi_cf = pagerank_closed_form(M_dense, p=p)

    # Compare
    l1_err = np.abs(pi_iter - pi_cf).sum()
    linf_err = np.abs(pi_iter - pi_cf).max()
    corr = np.corrcoef(pi_iter, pi_cf)[0, 1]

    print(f"  L1 error   : {l1_err:.2e}")
    print(f"  Linf error : {linf_err:.2e}")
    print(f"  Correlation: {corr:.10f}")
    print(f"  Iterative iterations: {iters}")
    print("\nSample comparison (first 10 nodes):")
    print(f"  {'NodeID':>10}  {'Iterative':>12}  {'Closed-Form':>12}  {'Diff':>10}")
    for i in range(min(10, n)):
        diff = abs(pi_iter[i] - pi_cf[i])
        print(f"  {sub_node_ids[i]:>10}  {pi_iter[i]:12.8f}  {pi_cf[i]:12.8f}  {diff:10.2e}")

    return pi_iter, pi_cf


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DATA = "/mnt/user-data/uploads/web-Google_10k.txt"

    analyse_p_effect()

    ranks, node_ids, id_to_idx = evaluate_large_graph(DATA, p=0.15, top_k=20)

    print()
    compare_methods(DATA, p=0.15, sample_size=200)

    # Sensitivity to p on full graph
    print("\n" + "=" * 60)
    print("SENSITIVITY OF TOP-5 NODES TO TELEPORTATION PROBABILITY p")
    print("=" * 60)
    edges, node_ids, id_to_idx = load_graph(DATA)
    H, dangling_mask = build_sparse_transition(edges, node_ids, id_to_idx)
    top5_ref, _ = pagerank_iterative(H, dangling_mask, p=0.15)
    top5_ids = [node_ids[i] for i in np.argsort(top5_ref)[::-1][:5]]
    print(f"Reference top-5 node IDs (p=0.15): {top5_ids}")
    print(f"\n{'p':>6}  " + "  ".join(f"Node {nid:>7}" for nid in top5_ids))
    for p_val in [0.05, 0.10, 0.15, 0.25, 0.50, 0.85]:
        r, _ = pagerank_iterative(H, dangling_mask, p=p_val)
        vals = [r[id_to_idx[nid]] for nid in top5_ids]
        print(f"{p_val:6.2f}  " + "  ".join(f"{v:12.8f}" for v in vals))
