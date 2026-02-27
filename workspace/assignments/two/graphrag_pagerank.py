################################################################################
#  Filename:      two/graphrag_pagerank.py                                     #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, February 27th 2026, 4:22:42 am                       #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday February 27th 2026 7:10:14 am                         #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
GraphRAG with PageRank-Weighted Retrieval
==========================================
A lightweight, self-contained implementation of the GraphRAG idea
(inspired by circlemind-ai/fast-graphrag) that uses Personalised PageRank
(also called Personalised / Topic-Sensitive PageRank) to retrieve the
top-k most relevant nodes for a multi-hop query.

Query example:
  "What discoveries by Marie Curie led to later advances in medical imaging?"

Seed entities: {"Marie Curie", "medical imaging"}

Algorithm (Personalised PageRank for GraphRAG):
  1. Build a knowledge graph (entity → relation → entity triples).
  2. Assign teleportation bias towards seed query entities.
  3. Run Personalised PageRank: random surfer teleports to a SEED node
     (not uniformly) with probability p.
  4. The stationary distribution gives a relevance score for every node.
  5. Return top-k nodes as the "retrieved context".

Closed-form Personalised PageRank:
    π = [I - (1-p) M]^{-1}  (p * v)
where v is the personalisation (seed bias) vector (sums to 1).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple

import numpy as np

# ─────────────────────────────────────────────────────────────
# Knowledge Graph
# ─────────────────────────────────────────────────────────────

# Triples: (head, relation, tail)
# Each triple adds a directed edge head → tail in the graph.
MARIE_CURIE_KG: List[Tuple[str, str, str]] = [
    ("Marie Curie", "discovered", "polonium"),
    ("Marie Curie", "discovered", "radium"),
    ("Marie Curie", "pioneered", "radioactivity research"),
    ("Marie Curie", "won", "Nobel Prize Physics"),
    ("Marie Curie", "won", "Nobel Prize Chemistry"),
    ("radium", "emits", "ionizing radiation"),
    ("polonium", "emits", "ionizing radiation"),
    ("ionizing radiation", "used in", "radiotherapy"),
    ("ionizing radiation", "enables", "X-ray imaging"),
    ("radioactivity research", "led to", "nuclear medicine"),
    ("nuclear medicine", "branch of", "medical imaging"),
    ("radiotherapy", "treats", "cancer"),
    ("radiotherapy", "part of", "medical imaging"),
    ("X-ray imaging", "type of", "medical imaging"),
    ("X-ray imaging", "discovered by", "Wilhelm Röntgen"),
    ("Wilhelm Röntgen", "contemporary of", "Marie Curie"),
    ("nuclear medicine", "uses", "radioactive tracers"),
    ("radioactive tracers", "derived from", "radium"),
    ("radioactive tracers", "used in", "PET scan"),
    ("PET scan", "type of", "medical imaging"),
    ("MRI", "type of", "medical imaging"),
    ("CT scan", "type of", "medical imaging"),
    ("CT scan", "uses", "X-ray imaging"),
    ("medical imaging", "revolutionised", "diagnostics"),
    ("diagnostics", "improves", "cancer treatment"),
    ("cancer treatment", "includes", "radiotherapy"),
]


def build_kg_graph(triples: List[Tuple[str, str, str]]) -> Tuple[Dict[str, List[str]], List[str]]:
    """Convert triples to adjacency list and collect all nodes."""
    adj: Dict[str, List[str]] = defaultdict(list)
    nodes: Set[str] = set()
    for h, _r, t in triples:
        adj[h].append(t)
        nodes.update([h, t])
    return adj, sorted(nodes)


def build_transition_matrix(adj: Dict[str, List[str]], nodes: List[str]) -> np.ndarray:
    """Build column-stochastic transition matrix from adjacency list."""
    n = len(nodes)
    idx = {node: i for i, node in enumerate(nodes)}
    M = np.zeros((n, n))
    for node in nodes:
        outlinks = adj.get(node, [])
        if outlinks:
            for target in outlinks:
                M[idx[target], idx[node]] += 1.0 / len(outlinks)
        else:
            M[:, idx[node]] = 1.0 / n  # dangling → uniform
    return M


# ─────────────────────────────────────────────────────────────
# Personalised PageRank (GraphRAG retrieval)
# ─────────────────────────────────────────────────────────────


def personalised_pagerank(
    M: np.ndarray,
    nodes: List[str],
    seed_entities: List[str],
    p: float = 0.25,  # higher p = stronger query focus
) -> Dict[str, float]:
    """
    Compute Personalised (query-biased) PageRank.

    Closed form:  π = [I - (1-p) M]^{-1} (p * v)

    where v[i] = 1/|seeds| if node i is a seed, else 0.

    Parameters
    ----------
    M            : column-stochastic n×n transition matrix
    nodes        : ordered list of node names
    seed_entities: query seed nodes (bias teleportation here)
    p            : teleportation probability

    Returns
    -------
    dict: node -> personalised PageRank score
    """
    n = len(nodes)
    idx = {node: i for i, node in enumerate(nodes)}

    # Personalisation vector v
    v = np.zeros(n)
    found_seeds = [s for s in seed_entities if s in idx]
    if not found_seeds:
        v = np.full(n, 1.0 / n)
        print("[WARN] No seed entities found in graph; using uniform teleportation.")
    else:
        for s in found_seeds:
            v[idx[s]] = 1.0 / len(found_seeds)

    # Closed-form solve
    A = np.eye(n) - (1 - p) * M
    rhs = p * v
    pi = np.linalg.solve(A, rhs)
    pi = np.maximum(pi, 0)  # numerical safety
    pi /= pi.sum()

    return {node: float(pi[i]) for i, node in enumerate(nodes)}


def top_k_nodes(
    scores: Dict[str, float],
    k: int = 10,
    exclude: List[str] | None = None,
) -> List[Tuple[str, float]]:
    """Return top-k (node, score) pairs, optionally excluding seed nodes."""
    exclude_set = set(exclude or [])
    ranked = sorted(
        [(node, score) for node, score in scores.items() if node not in exclude_set],
        key=lambda x: -x[1],
    )
    return ranked[:k]


# ─────────────────────────────────────────────────────────────
# Answer generation (simulated – in production, call an LLM)
# ─────────────────────────────────────────────────────────────


def answer_query(query: str, retrieved_nodes: List[Tuple[str, float]], triples: List[Tuple[str, str, str]]) -> None:
    """Simulate answer synthesis from retrieved context."""
    node_names = {n for n, _ in retrieved_nodes}

    print(f"\nQUERY: {query}")
    print("-" * 60)
    print("Retrieved context (top nodes by Personalised PageRank):")
    for node, score in retrieved_nodes:
        print(f"  [{score:.5f}]  {node}")

    print("\nRelevant triples from retrieved nodes:")
    for h, r, t in triples:
        if h in node_names or t in node_names:
            print(f"  {h}  --[{r}]-->  {t}")

    print("\nSynthesised answer (simulated):")
    print(
        "  Marie Curie's discovery of radium and polonium established the science of "
        "radioactivity. Ionizing radiation emitted by these elements was found to destroy "
        "malignant cells, giving rise to radiotherapy — a cornerstone of cancer treatment. "
        "Simultaneously, her work informed the development of radioactive tracers used in "
        "nuclear medicine, which underpins modern PET scanning. X-ray imaging, though "
        "independently discovered by Röntgen, was deeply informed by the radiation physics "
        "Curie helped codify. Together these threads converged on contemporary medical "
        "imaging (PET, CT, fluoroscopy), transforming diagnostics and cancer care."
    )


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("GraphRAG with Personalised PageRank")
    print("=" * 65)

    adj, nodes = build_kg_graph(MARIE_CURIE_KG)
    M = build_transition_matrix(adj, nodes)

    query = "What discoveries by Marie Curie led to later advances in medical imaging?"
    seed_entities = ["Marie Curie", "medical imaging"]

    # Personalised PageRank with p = 0.25 (strong query focus)
    scores = personalised_pagerank(M, nodes, seed_entities, p=0.25)

    print(f"\nPersonalised PageRank scores (seed={seed_entities}, p=0.25):")
    print(f"  {'Node':40s}  {'Score':>8}")
    for node, score in sorted(scores.items(), key=lambda x: -x[1]):
        print(f"  {node:40s}  {score:8.5f}")

    top10 = top_k_nodes(scores, k=10)
    answer_query(query, top10, MARIE_CURIE_KG)

    # Show effect of p on retrieval focus
    print("\n" + "=" * 65)
    print("EFFECT OF p ON RETRIEVAL (which nodes surface)")
    print("=" * 65)
    for p_val in [0.05, 0.15, 0.30, 0.50, 0.85]:
        s = personalised_pagerank(M, nodes, seed_entities, p=p_val)
        top3 = [n for n, _ in sorted(s.items(), key=lambda x: -x[1])[:3]]
        print(f"  p={p_val:.2f}  →  {top3}")

    print()
    print("INSIGHT:")
    print("  Low p  → surfer rarely teleports; ranks dominated by graph structure.")
    print("  High p → surfer frequently jumps to seeds; retrieved nodes closely match")
    print("           the query seeds (Marie Curie, medical imaging) but miss lateral")
    print("           connections like radioactive tracers or PET scan.")
    print("  p≈0.25 → balanced: seeds are highly ranked AND multi-hop connections surface.")
