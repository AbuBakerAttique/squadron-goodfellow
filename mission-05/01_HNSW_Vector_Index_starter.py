"""
Mission 05 — Part 1: Systems Architect (Lead Engineer)
Hierarchical Navigable Small World (HNSW) Vector Index Starter

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-05-M01 (Crab Pulsar Remnant / Messier 1)
Subsystem 05: Dual-Path Associative Memory Core
"""

import math
import random
import time
import numpy as np
from typing import List, Dict, Set, Tuple


def cosine_similarity(u: np.ndarray, v: np.ndarray) -> float:
    """Computes cosine similarity between two 1D normalized or unnormalized vectors."""
    norm_u = np.linalg.norm(u)
    norm_v = np.linalg.norm(v)
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return float(np.dot(u, v) / (norm_u * norm_v))


class SimpleHNSW:
    """
    Simplified Hierarchical Navigable Small World (HNSW) index for educational exploration.
    Implements multi-layer skip-graph traversal with logarithmic scaling.
    """
    def __init__(self, dim: int = 768, M: int = 16, ef_construction: int = 64):
        self.dim = dim
        self.M = M
        self.ef_construction = ef_construction
        self.m_L = 1.0 / math.log(M)
        self.entry_point: int = -1
        self.max_level: int = -1
        self.vectors: Dict[int, np.ndarray] = {}
        self.graphs: Dict[int, Dict[int, Set[int]]] = {} # level -> {node_id -> set of neighbors}

    def _random_level(self) -> int:
        """Assigns layer index using exponential decay."""
        r = random.random()
        while r == 0:
            r = random.random()
        return math.floor(-math.log(r) * self.m_L)

    def insert(self, node_id: int, vector: np.ndarray):
        """Inserts a vector into the multi-layer HNSW graph."""
        norm_vec = vector / (np.linalg.norm(vector) + 1e-9)
        self.vectors[node_id] = norm_vec
        level = self._random_level()

        if self.entry_point == -1:
            self.entry_point = node_id
            self.max_level = level
            for l in range(level + 1):
                self.graphs[l] = {node_id: set()}
            return

        curr_ep = self.entry_point
        # 1. Greedy search from top level down to level + 1
        for l in range(self.max_level, level, -1):
            curr_ep = self._search_layer_greedy(curr_ep, norm_vec, l)

        # 2. Connect at levels <= min(level, max_level)
        for l in range(min(level, self.max_level), -1, -1):
            if l not in self.graphs:
                self.graphs[l] = {}
            neighbors = self._search_layer_ef(curr_ep, norm_vec, ef=self.ef_construction, level=l)
            self.graphs[l][node_id] = set(neighbors[:self.M])
            for neighbor in self.graphs[l][node_id]:
                if neighbor in self.graphs[l]:
                    self.graphs[l][neighbor].add(node_id)
            curr_ep = neighbors[0] if neighbors else curr_ep

        if level > self.max_level:
            for l in range(self.max_level + 1, level + 1):
                self.graphs[l] = {node_id: set()}
            self.max_level = level
            self.entry_point = node_id

    def _search_layer_greedy(self, ep: int, query: np.ndarray, level: int) -> int:
        best = ep
        best_sim = float(np.dot(self.vectors[best], query))
        while True:
            improved = False
            for neighbor in self.graphs.get(level, {}).get(best, []):
                sim = float(np.dot(self.vectors[neighbor], query))
                if sim > best_sim:
                    best_sim = sim
                    best = neighbor
                    improved = True
            if not improved:
                break
        return best

    def _search_layer_ef(self, ep: int, query: np.ndarray, ef: int, level: int) -> List[int]:
        visited = {ep}
        candidates = [(float(np.dot(self.vectors[ep], query)), ep)]
        results = [(float(np.dot(self.vectors[ep], query)), ep)]

        while candidates:
            candidates.sort(reverse=True)
            curr_sim, curr_node = candidates.pop(0)

            results.sort(reverse=True)
            worst_res_sim = results[-1][0] if len(results) >= ef else -1.0

            if curr_sim < worst_res_sim and len(results) >= ef:
                break

            for neighbor in self.graphs.get(level, {}).get(curr_node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    sim = float(np.dot(self.vectors[neighbor], query))
                    if sim > worst_res_sim or len(results) < ef:
                        candidates.append((sim, neighbor))
                        results.append((sim, neighbor))
                        results.sort(reverse=True)
                        if len(results) > ef:
                            results.pop()

        results.sort(reverse=True)
        return [node for _, node in results]

    def query(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[int, float]]:
        """Queries the HNSW index for the top-k most similar vectors."""
        if self.entry_point == -1:
            return []
        norm_query = query_vec / (np.linalg.norm(query_vec) + 1e-9)
        curr = self.entry_point
        for l in range(self.max_level, 0, -1):
            curr = self._search_layer_greedy(curr, norm_query, l)
        candidates = self._search_layer_ef(curr, norm_query, ef=max(self.ef_construction, top_k), level=0)
        return [(c, float(np.dot(self.vectors[c], norm_query))) for c in candidates[:top_k]]


if __name__ == "__main__":
    print("=== Subsystem 05: HNSW Vector Proximity Index Simulation ===")
    np.random.seed(42)
    dim = 64
    n_docs = 500
    hnsw = SimpleHNSW(dim=dim, M=8, ef_construction=32)

    print(f"Building index with {n_docs} vectors of dimension {dim}...")
    for i in range(n_docs):
        vec = np.random.randn(dim)
        hnsw.insert(i, vec)

    q = np.random.randn(dim)
    top_matches = hnsw.query(q, top_k=5)
    print("Top 5 Nearest Astrogation Neighbors (ID, Similarity):")
    for doc_id, sim in top_matches:
        print(f"  Node {doc_id:04d} -> Cosine Similarity: {sim:.4f}")
