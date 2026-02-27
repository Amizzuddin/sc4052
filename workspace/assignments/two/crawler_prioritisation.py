################################################################################
#  Filename:      two/crawler_prioritisation.py                                #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, February 27th 2026, 4:22:42 am                       #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday February 27th 2026 6:42:38 am                         #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
GPTBot-style Crawler Prioritisation Using PageRank
====================================================
Given a directed web graph (URL -> outlinks) and precomputed PageRank scores,
return the top-k URLs to crawl next, respecting robots.txt signals.

Heuristic: Crawl-Quality Score (CQS) =
    α * PageRank(url)
  + β * avg_PageRank(outlinks)    # neighbours signal neighbourhood quality
  + γ * (crawl_allowed ? 1 : 0)  # robots.txt compliance bonus
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, List

# ─────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────


@dataclass(order=True)
class CrawlCandidate:
    score: float  # negative for max-heap via heapq
    url: str = field(compare=False)
    reason: str = field(compare=False, default="")


# ─────────────────────────────────────────────────────────────
# Robots.txt helper (lightweight, no network calls in demo)
# ─────────────────────────────────────────────────────────────

# In production: fetch robots.txt per domain asynchronously.
# Here we simulate a small allow/deny table for the toy graph.
ROBOTS_ALLOW: Dict[str, bool] = {
    "https://ai.example.com": True,
    "https://news.example.com": True,
    "https://shop.example.com": False,  # disallows GPTBot
    "https://blog.example.com": True,
    "https://docs.example.com": True,
    "https://social.example.com": False,  # disallows GPTBot
    "https://research.example.com": True,
    "https://forum.example.com": True,
}


def crawl_allowed(url: str, bot_agent: str = "GPTBot") -> bool:
    """Return True if the given bot is allowed to crawl url."""
    return ROBOTS_ALLOW.get(url, True)  # default: allow unknown


# ─────────────────────────────────────────────────────────────
# Crawler Prioritisation
# ─────────────────────────────────────────────────────────────


def prioritise_crawl(
    web_graph: Dict[str, List[str]],
    pagerank: Dict[str, float],
    top_k: int = 5,
    alpha: float = 0.70,  # weight: own PageRank
    beta: float = 0.20,  # weight: avg PageRank of outlinks
    gamma: float = 0.10,  # weight: crawl permission bonus
) -> List[CrawlCandidate]:
    """
    Rank candidate URLs for crawling.

    Parameters
    ----------
    web_graph : dict  url -> list of outlink urls
    pagerank  : dict  url -> PageRank score
    top_k     : int   number of top urls to return
    alpha, beta, gamma : float  weights (should sum to 1)

    Returns
    -------
    Sorted list of top-k CrawlCandidate objects.
    """
    max_pr = max(pagerank.values()) if pagerank else 1.0

    candidates = []
    for url, outlinks in web_graph.items():
        own_pr = pagerank.get(url, 0.0) / max_pr  # normalise to [0,1]

        # Neighbourhood quality: mean PageRank of out-neighbours
        if outlinks:
            nbr_pr = sum(pagerank.get(u, 0.0) for u in outlinks) / len(outlinks)
            nbr_pr /= max_pr
        else:
            nbr_pr = 0.0

        allowed = crawl_allowed(url)
        permission_bonus = 1.0 if allowed else 0.0

        cqs = alpha * own_pr + beta * nbr_pr + gamma * permission_bonus

        reason = (
            f"PR={pagerank.get(url, 0):.4f}, "
            f"nbr_avg_PR={nbr_pr*max_pr:.4f}, "
            f"crawl_allowed={'yes' if allowed else 'NO (blocked)'}, "
            f"CQS={cqs:.4f}"
        )
        candidates.append(CrawlCandidate(score=-cqs, url=url, reason=reason))

    heapq.heapify(candidates)
    return [heapq.heappop(candidates) for _ in range(min(top_k, len(candidates)))]


# ─────────────────────────────────────────────────────────────
# Heuristic: Robots-aware high-quality page finder
# ─────────────────────────────────────────────────────────────


def find_high_quality_allowed_pages(
    web_graph: Dict[str, List[str]],
    pagerank: Dict[str, float],
    top_k: int = 5,
) -> List[str]:
    """
    Heuristic: return top-k pages with:
      - crawl_allowed == True
      - PageRank in top 25% percentile
      - at least 1 outlink (not a sink for crawler)

    These pages yield high-quality training data AND are legally
    permissible to crawl, making them ideal first-pass candidates
    for a new AI training crawl.
    """
    pr_values = sorted(pagerank.values(), reverse=True)
    threshold = pr_values[max(0, len(pr_values) // 4)]  # top 25%

    eligible = [
        (url, pagerank.get(url, 0.0))
        for url in web_graph
        if crawl_allowed(url) and pagerank.get(url, 0.0) >= threshold and len(web_graph.get(url, [])) > 0
    ]
    eligible.sort(key=lambda x: -x[1])
    return [url for url, _ in eligible[:top_k]]


# ─────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────

DEMO_GRAPH: Dict[str, List[str]] = {
    "https://ai.example.com": ["https://research.example.com", "https://docs.example.com"],
    "https://news.example.com": ["https://ai.example.com", "https://social.example.com"],
    "https://shop.example.com": ["https://news.example.com"],
    "https://blog.example.com": ["https://ai.example.com", "https://research.example.com"],
    "https://docs.example.com": ["https://ai.example.com"],
    "https://social.example.com": ["https://news.example.com", "https://shop.example.com"],
    "https://research.example.com": ["https://ai.example.com", "https://docs.example.com", "https://blog.example.com"],
    "https://forum.example.com": ["https://ai.example.com", "https://blog.example.com"],
}

DEMO_PAGERANK: Dict[str, float] = {
    "https://ai.example.com": 0.312,
    "https://news.example.com": 0.095,
    "https://shop.example.com": 0.041,
    "https://blog.example.com": 0.098,
    "https://docs.example.com": 0.145,
    "https://social.example.com": 0.062,
    "https://research.example.com": 0.198,
    "https://forum.example.com": 0.049,
}

if __name__ == "__main__":
    print("=" * 65)
    print("GPTBot-Style Crawler Prioritisation with PageRank")
    print("=" * 65)

    top_k = 5
    results = prioritise_crawl(DEMO_GRAPH, DEMO_PAGERANK, top_k=top_k)

    print(f"\nTop-{top_k} URLs to crawl (ranked by Crawl-Quality Score):\n")
    for rank, cand in enumerate(results, 1):
        print(f"  #{rank}  {cand.url}")
        print(f"       {cand.reason}")
        print()

    print("-" * 65)
    print("High-quality + crawl-allowed heuristic:")
    allowed = find_high_quality_allowed_pages(DEMO_GRAPH, DEMO_PAGERANK, top_k=5)
    for i, url in enumerate(allowed, 1):
        pr = DEMO_PAGERANK.get(url, 0.0)
        print(f"  {i}. {url}  (PageRank={pr:.3f}, crawl=allowed)")

    print("\nWHY HIGH-PAGERANK PAGES YIELD BETTER TRAINING DATA:")
    print("  • High PageRank → many authoritative inbound links → peer-validated content")
    print("  • Authority pages tend to be well-written, factual, and densely informative")
    print("  • They act as hubs: crawling them discovers high-quality outlinks too")
    print("  • Low-PR pages are often spam, thin content, or orphaned – low signal-to-noise")
    print()
    print("PROPOSED HEURISTIC (Robots-Aware Authority Filter):")
    print("  1. Discard any page where robots.txt blocks GPTBot.")
    print("  2. Keep pages with PageRank >= 75th percentile of the known graph.")
    print("  3. Among those, prefer pages with ≥1 allowed outlink (extend crawl frontier).")
    print("  4. Break ties by freshness (Last-Modified header) for recency.")
