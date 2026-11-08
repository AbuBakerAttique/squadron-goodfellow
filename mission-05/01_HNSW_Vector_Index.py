"""
Mission 05 — Part 1: Systems Architect (Lead Engineer)
Hierarchical Navigable Small World (HNSW) Multi-Layer Vector Proximity Index
(pure Python + NumPy, after Malkov & Yashunin, 2018)

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-05-M01 (Crab Pulsar Remnant / Messier 1)
Subsystem 05: Dual-Path Associative Memory Core

Deliverables implemented here
  1. Cosine similarity core on normalized unit vectors (vectorized)
  2. Layer assignment  l = floor(-ln(U) * m_L),  m_L = 1 / ln(M)
  3. Greedy skip-graph traversal: search_layer(entry_point, query, ef, layer)
  4. Latency benchmark: HNSW vs brute-force flat search (N = 25,000, d = 768)

Usage:
    python 01_HNSW_Vector_Index.py              # self-tests + full benchmark (N=25,000, d=768)
    python 01_HNSW_Vector_Index.py --quick      # self-tests + small benchmark (N=5,000)
"""

import argparse
import heapq
import json
import math
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
# 1. Cosine similarity core
# ---------------------------------------------------------------------------

def cosine_similarity(u: np.ndarray, v: np.ndarray) -> float:
    """Sim(u, v) = u.v / (||u|| ||v||) for two 1-D vectors (0.0 if either has zero norm)."""
    norm_u = np.linalg.norm(u)
    norm_v = np.linalg.norm(v)
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return float(np.dot(u, v) / (norm_u * norm_v))


def normalize_rows(x: np.ndarray) -> np.ndarray:
    """Scales each row (or a single vector) to unit L2 norm. Zero vectors stay zero."""
    x = np.asarray(x, dtype=np.float32)
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-12)


def cosine_similarity_matrix(unit_matrix: np.ndarray, unit_query: np.ndarray) -> np.ndarray:
    """
    Vectorized cosine similarity of one query against many rows.
    On unit-normalized inputs cosine similarity is a plain dot product: one BLAS mat-vec.
    """
    return unit_matrix @ unit_query


# ---------------------------------------------------------------------------
# 2-3. HNSW index
# ---------------------------------------------------------------------------

class HNSWIndex:
    """
    Multi-layer navigable small-world graph.

    * Layer l keeps each node with probability ~ M^-l (exponential decay), so upper layers are
      sparse "express lanes" and layer 0 holds every vector.
    * Queries enter at the top layer, hop greedily toward the query (long-range edges), drop one
      layer at a time, and finish with a best-first beam search of width `ef` on layer 0.
    * Degree caps: M links per node on layers >= 1, 2*M on layer 0 (Malkov & Yashunin's M_max0).
    * Neighbours are chosen with the diversity heuristic (Algorithm 4), which keeps long-range
      links across cluster boundaries instead of only the M nearest points.

    Node ids given to insert()/returned by query() are external ids; graph internals use the
    insertion index. Public search_layer() works on internal indices.
    """

    def __init__(self, dim: int = 768, M: int = 16, ef_construction: int = 100,
                 ef_search: int = 64, seed: int = 42):
        if M < 2:
            raise ValueError("M must be >= 2")
        self.dim = dim
        self.M = M
        self.M0 = 2 * M
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.m_L = 1.0 / math.log(M)
        self._rng = random.Random(seed)

        self.entry_point: int = -1
        self.max_level: int = -1
        self.graphs: List[Dict[int, List[int]]] = []   # graphs[level][node] -> neighbour list
        self._levels: List[int] = []
        self._ids: List[int] = []
        self._id2idx: Dict[int, int] = {}
        self._vecs = np.empty((1024, dim), dtype=np.float32)
        self._n = 0
        self.n_dist_evals = 0                           # similarity evaluations (search cost metric)

    def __len__(self) -> int:
        return self._n

    # -- helpers ------------------------------------------------------------------------

    def _random_level(self) -> int:
        """l = floor(-ln(uniform(0,1)) * m_L); uniform draw is kept strictly > 0."""
        r = self._rng.random()
        while r == 0.0:
            r = self._rng.random()
        return int(math.floor(-math.log(r) * self.m_L))

    def _sims(self, idxs: Sequence[int], query: np.ndarray) -> np.ndarray:
        self.n_dist_evals += len(idxs)
        return self._vecs[idxs] @ query

    def level_of(self, idx: int) -> int:
        return self._levels[idx]

    # -- search -------------------------------------------------------------------------

    def _greedy(self, ep: int, query: np.ndarray, layer: int) -> int:
        """Greedy hill-climb on one layer (ef = 1): hop to the best neighbour until none improves."""
        graph = self.graphs[layer]
        best = ep
        best_s = float(self._vecs[ep] @ query)
        self.n_dist_evals += 1
        while True:
            nbrs = graph[best]
            if not nbrs:
                return best
            ns = self._sims(nbrs, query)
            j = int(ns.argmax())
            if ns[j] > best_s:
                best, best_s = nbrs[j], float(ns[j])
            else:
                return best

    def search_layer(self, entry_point: Union[int, Sequence[int]], query: np.ndarray,
                     ef: int, layer: int) -> List[Tuple[int, float]]:
        """
        Best-first beam search on one layer (Algorithm 2).
        `query` must be unit-normalized. Returns up to `ef` (internal_index, similarity) pairs,
        most similar first.
        """
        eps = [entry_point] if isinstance(entry_point, (int, np.integer)) else list(entry_point)
        graph = self.graphs[layer]
        visited = set(eps)
        sims0 = self._sims(eps, query).tolist()
        cand = [(-s, e) for s, e in zip(sims0, eps)]     # max-heap on similarity
        res = [(s, e) for s, e in zip(sims0, eps)]       # min-heap: res[0] is the current worst
        heapq.heapify(cand)
        heapq.heapify(res)
        while len(res) > ef:
            heapq.heappop(res)

        while cand:
            neg_s, c = heapq.heappop(cand)
            if len(res) >= ef and -neg_s < res[0][0]:
                break                                    # best candidate is worse than worst result
            nbrs = [n for n in graph[c] if n not in visited]
            if not nbrs:
                continue
            visited.update(nbrs)
            for n, s in zip(nbrs, self._sims(nbrs, query).tolist()):
                if len(res) < ef or s > res[0][0]:
                    heapq.heappush(cand, (-s, n))
                    heapq.heappush(res, (s, n))
                    if len(res) > ef:
                        heapq.heappop(res)
        return [(n, s) for s, n in sorted(res, reverse=True)]

    def query(self, query_vec: np.ndarray, top_k: int = 5,
              ef_search: Optional[int] = None) -> List[Tuple[int, float]]:
        """Top-k (external_id, cosine_similarity) pairs, most similar first."""
        if self.entry_point == -1:
            return []
        q = normalize_rows(query_vec)
        ep = self.entry_point
        for layer in range(self.max_level, 0, -1):       # skip-graph descent
            ep = self._greedy(ep, q, layer)
        ef = max(ef_search or self.ef_search, top_k)
        found = self.search_layer(ep, q, ef, 0)
        return [(self._ids[i], s) for i, s in found[:top_k]]

    # -- construction -------------------------------------------------------------------

    def _select_neighbors(self, cands: List[Tuple[int, float]], m: int) -> List[int]:
        """
        Diversity heuristic (Algorithm 4). `cands` = (idx, sim_to_base) sorted best first.
        A candidate is kept only if it is closer to the base than to every already-kept
        neighbour; leftovers fill remaining slots (keepPrunedConnections).
        """
        if len(cands) <= m:
            return [i for i, _ in cands]
        idxs = [i for i, _ in cands]
        base_sims = np.fromiter((s for _, s in cands), dtype=np.float32, count=len(cands))
        V = self._vecs[idxs]
        G = V @ V.T
        self.n_dist_evals += len(idxs)
        selected: List[int] = []
        discarded: List[int] = []
        for k in range(len(idxs)):
            if len(selected) >= m:
                break
            if not selected or bool((base_sims[k] > G[k, selected]).all()):
                selected.append(k)
            else:
                discarded.append(k)
        for k in discarded:
            if len(selected) >= m:
                break
            selected.append(k)
        return [idxs[k] for k in selected]

    def insert(self, node_id: int, vector: np.ndarray) -> None:
        """Inserts one vector (Algorithm 1)."""
        if node_id in self._id2idx:
            raise ValueError(f"duplicate node id {node_id}")
        v = normalize_rows(vector)
        idx = self._n
        if idx >= self._vecs.shape[0]:
            self._vecs = np.concatenate([self._vecs, np.empty_like(self._vecs)], axis=0)
        self._vecs[idx] = v
        self._n += 1
        self._ids.append(node_id)
        self._id2idx[node_id] = idx

        level = self._random_level()
        self._levels.append(level)
        while len(self.graphs) <= level:
            self.graphs.append({})
        for l in range(level + 1):
            self.graphs[l][idx] = []

        if self.entry_point == -1:
            self.entry_point, self.max_level = idx, level
            return

        ep = self.entry_point
        for l in range(self.max_level, level, -1):       # coarse hops above the node's top layer
            ep = self._greedy(ep, v, l)

        for l in range(min(level, self.max_level), -1, -1):
            W = self.search_layer(ep, v, self.ef_construction, l)
            neigh = self._select_neighbors(W, self.M)
            self.graphs[l][idx] = list(neigh)
            cap = self.M0 if l == 0 else self.M
            for n in neigh:                              # bidirectional links, shrink on overflow
                lst = self.graphs[l][n]
                lst.append(idx)
                if len(lst) > cap:
                    s = self._sims(lst, self._vecs[n])
                    order = np.argsort(-s)
                    pruned = [(lst[o], float(s[o])) for o in order]
                    self.graphs[l][n] = self._select_neighbors(pruned, cap)
            ep = W[0][0]

        if level > self.max_level:
            self.max_level, self.entry_point = level, idx

    def add_batch(self, vectors: np.ndarray, start_id: int = 0) -> None:
        for i, v in enumerate(vectors):
            self.insert(start_id + i, v)

    # -- introspection ------------------------------------------------------------------

    def layer_sizes(self) -> List[int]:
        return [len(g) for g in self.graphs]

    def degree_stats(self) -> Dict[str, float]:
        out = {}
        for l, g in enumerate(self.graphs):
            deg = [len(v) for v in g.values()]
            out[f"layer{l}_mean_deg"] = float(np.mean(deg)) if deg else 0.0
            out[f"layer{l}_max_deg"] = float(max(deg)) if deg else 0.0
        return out


# Backwards-compatible name used by the instructor starter
SimpleHNSW = HNSWIndex


# ---------------------------------------------------------------------------
# 4. Brute-force baseline, data generator, benchmark
# ---------------------------------------------------------------------------

def flat_search(unit_matrix: np.ndarray, unit_query: np.ndarray, top_k: int = 10) -> np.ndarray:
    """Exact cosine top-k by linear scan: one mat-vec over all N rows + partial sort."""
    sims = unit_matrix @ unit_query
    part = np.argpartition(-sims, top_k - 1)[:top_k]
    return part[np.argsort(-sims[part])]


def make_embeddings(n: int, dim: int = 768, n_clusters: int = 100, rank: int = 32,
                    seed: int = 42) -> np.ndarray:
    """
    Synthetic 'sentence-embedding-like' vectors: a mixture of clusters whose within-cluster spread
    lives mostly in a low-dimensional subspace (real embeddings have low intrinsic dimension),
    plus a little isotropic noise. Returns unit-normalized float32 rows.
    """
    rng = np.random.default_rng(seed)
    centers = normalize_rows(rng.standard_normal((n_clusters, dim)))
    basis = rng.standard_normal((rank, dim)).astype(np.float32) / math.sqrt(dim)
    assign = rng.integers(0, n_clusters, size=n)
    z = rng.standard_normal((n, rank)).astype(np.float32)
    x = centers[assign] + 0.9 * (z @ basis) + 0.05 * rng.standard_normal((n, dim)).astype(np.float32) / math.sqrt(dim)
    return normalize_rows(x)


def _timed_queries(fn, queries: np.ndarray) -> Tuple[float, list]:
    out, t = [], []
    for q in queries:
        t0 = time.perf_counter()
        out.append(fn(q))
        t.append(time.perf_counter() - t0)
    return float(np.mean(t) * 1e3), out


def run_benchmark(n: int = 25000, dim: int = 768, n_queries: int = 200, top_k: int = 10,
                  M: int = 16, ef_construction: int = 100, ef_search: int = 64,
                  seed: int = 42, verbose: bool = True) -> Dict:
    """Builds an index incrementally, measuring HNSW vs flat search at growing checkpoints."""
    data = make_embeddings(n + n_queries, dim, seed=seed)
    base, queries = data[:n], data[n:]
    checkpoints = sorted({c for c in (1000, 2500, 5000, 10000, 25000, n) if c <= n})

    index = HNSWIndex(dim=dim, M=M, ef_construction=ef_construction, ef_search=ef_search, seed=seed)
    rows, t_build = [], 0.0
    for start, stop in zip([0] + checkpoints[:-1], checkpoints):
        t0 = time.perf_counter()
        for i in range(start, stop):
            index.insert(i, base[i])
        t_build += time.perf_counter() - t0

        sub = base[:stop]
        truth = [set(flat_search(sub, q, top_k).tolist()) for q in queries]
        flat_ms, _ = _timed_queries(lambda q: flat_search(sub, q, top_k), queries)
        index.n_dist_evals = 0
        h_ms, found = _timed_queries(lambda q: index.query(q, top_k), queries)
        evals = index.n_dist_evals / len(queries)
        recall = float(np.mean([len({i for i, _ in f} & t) / top_k for f, t in zip(found, truth)]))
        row = dict(N=stop, hnsw_ms=h_ms, flat_ms=flat_ms, speedup=flat_ms / h_ms,
                   recall_at_k=recall, dist_evals=evals, layers=len(index.graphs),
                   build_s=t_build)
        rows.append(row)
        if verbose:
            print(f"  N={stop:>6,}  flat {flat_ms:7.3f} ms | HNSW {h_ms:7.3f} ms | "
                  f"speedup {row['speedup']:5.2f}x | recall@{top_k} {recall:.3f} | "
                  f"sim evals/query {evals:7.0f} | layers {len(index.graphs)} | built {t_build:6.1f}s",
                  flush=True)

    # ef_search sweep on the full index
    truth = [set(flat_search(base, q, top_k).tolist()) for q in queries]
    sweep = []
    if verbose:
        print(f"\n  ef_search sweep at N={n:,}:")
    for ef in (16, 32, 64, 128, 256):
        index.n_dist_evals = 0
        ms, found = _timed_queries(lambda q: index.query(q, top_k, ef_search=ef), queries)
        rec = float(np.mean([len({i for i, _ in f} & t) / top_k for f, t in zip(found, truth)]))
        sweep.append(dict(ef_search=ef, hnsw_ms=ms, recall_at_k=rec,
                          dist_evals=index.n_dist_evals / len(queries)))
        if verbose:
            print(f"    ef={ef:>3}  {ms:7.3f} ms/query  recall@{top_k} {rec:.3f}  "
                  f"sim evals/query {sweep[-1]['dist_evals']:.0f}", flush=True)

    return dict(config=dict(n=n, dim=dim, n_queries=n_queries, top_k=top_k, M=M,
                            ef_construction=ef_construction, ef_search=ef_search, seed=seed),
                scaling=rows, ef_sweep=sweep, layer_sizes=index.layer_sizes(),
                degree_stats=index.degree_stats(), build_seconds=t_build)


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

def run_self_tests() -> None:
    print("=" * 74)
    print("USSE NOOSPHERE • SUBSYSTEM 05: HNSW VECTOR PROXIMITY INDEX — SELF-TESTS")
    print("=" * 74)
    rng = np.random.default_rng(0)

    # [1] cosine core
    u, v = rng.standard_normal(768), rng.standard_normal(768)
    ref = float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v)))
    assert abs(cosine_similarity(u, v) - ref) < 1e-9
    assert cosine_similarity(u, np.zeros(768)) == 0.0
    X = normalize_rows(rng.standard_normal((50, 768)))
    q = normalize_rows(rng.standard_normal(768))
    assert np.allclose(cosine_similarity_matrix(X, q),
                       [cosine_similarity(x, q) for x in X], atol=1e-5)
    print("[1] cosine core: scalar, zero-vector and vectorized forms agree")

    # [2] layer assignment ~ geometric with ratio 1/M
    M = 16
    idx = HNSWIndex(dim=4, M=M, seed=1)
    levels = np.array([idx._random_level() for _ in range(200_000)])
    p1, p2 = (levels >= 1).mean(), (levels >= 2).mean()
    assert abs(p1 - 1 / M) < 0.003 and abs(p2 - 1 / M ** 2) < 0.001
    print(f"[2] layer assignment: P(l>=1)={p1:.4f} (theory {1/M:.4f}), "
          f"P(l>=2)={p2:.5f} (theory {1/M**2:.5f}), m_L={idx.m_L:.4f}")

    # [3] correctness on a small index: high ef => exact; degree caps hold
    data = normalize_rows(rng.standard_normal((600, 32)))
    small = HNSWIndex(dim=32, M=8, ef_construction=64, seed=3)
    small.add_batch(data)
    qs = normalize_rows(rng.standard_normal((50, 32)))
    hits = 0
    for qv in qs:
        truth = set(flat_search(data, qv, 5).tolist())
        hits += len({i for i, _ in small.query(qv, 5, ef_search=600)} & truth)
    assert hits == 50 * 5
    for l, g in enumerate(small.graphs):
        cap = small.M0 if l == 0 else small.M
        assert max(len(nb) for nb in g.values()) <= cap
    print(f"[3] small index (N=600): exact recall with ef=N; degree caps M={small.M}/M0={small.M0} respected; "
          f"layers {small.layer_sizes()}")

    # [4] search_layer contract + greedy descent
    qv = qs[0]
    res = small.search_layer(small.entry_point, qv, 10, 0)
    sims = [s for _, s in res]
    assert len(res) == 10 and sims == sorted(sims, reverse=True)
    top = small.query(qv, 1, ef_search=600)[0]
    assert top[0] == int(flat_search(data, qv, 1)[0])
    print("[4] search_layer returns ef results sorted by similarity; best hit matches exact search")

    # [5] determinism
    a = HNSWIndex(dim=32, M=8, seed=5); a.add_batch(data[:200])
    b = HNSWIndex(dim=32, M=8, seed=5); b.add_batch(data[:200])
    assert a.query(qs[0], 5) == b.query(qs[0], 5)
    print("[5] same seed -> identical graph and results")
    print("\n[SUCCESS] HNSW self-tests passed.\n")


def print_summary(res: Dict) -> None:
    last = res["scaling"][-1]
    print("\n" + "=" * 74)
    print(f"BENCHMARK SUMMARY  N={last['N']:,}  d={res['config']['dim']}  "
          f"M={res['config']['M']}  efC={res['config']['ef_construction']}  "
          f"ef={res['config']['ef_search']}")
    print("=" * 74)
    print(f"  Flat (brute-force) : {last['flat_ms']:8.3f} ms / query")
    print(f"  HNSW               : {last['hnsw_ms']:8.3f} ms / query   ({last['speedup']:.2f}x faster)")
    print(f"  Recall@{res['config']['top_k']}          : {last['recall_at_k']:8.3f}")
    print(f"  Similarity evals   : {last['dist_evals']:8.0f} per query vs {last['N']:,} for flat "
          f"({100 * last['dist_evals'] / last['N']:.1f}%)")
    print(f"  Layer sizes        : {res['layer_sizes']}")
    print("=" * 74)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25000)
    ap.add_argument("--dim", type=int, default=768)
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--quick", action="store_true", help="N=5000 benchmark")
    ap.add_argument("--out", default="hnsw_benchmark_results.json")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()
    n = 5000 if args.quick else args.n

    if not args.skip_tests:
        run_self_tests()
    print(f"Benchmark: N={n:,}, d={args.dim}, {args.queries} queries, top-10, single-thread loop")
    results = run_benchmark(n=n, dim=args.dim, n_queries=args.queries)
    print_summary(results)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {args.out}")
