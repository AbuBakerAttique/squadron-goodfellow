"""
Mission 05 -- Part 2: Communications & Protocol Officer
Okapi BM25 Lexical Retrieval & Reciprocal Rank Fusion (RRF)

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-05-M01 (Crab Pulsar Remnant / Messier 1)
Subsystem 05: Dual-Path Associative Memory Core

Deliverables implemented here
  1. Okapi BM25 scoring engine with TF saturation (k1) and length normalisation (b)
  2. Reciprocal Rank Fusion (RRF) combiner merging dense + sparse candidate streams
  3. Evaluation metrics: Mean Reciprocal Rank (MRR) and NDCG@10
  4. Benchmark on mixed technical/natural-language starship queries
  5. Integration with the Systems Architect's HNSW index for true hybrid retrieval
Usage:
    python 02_BM25_and_RRF_Combiner.py              # full self-tests + benchmark
    python 02_BM25_and_RRF_Combiner.py --quick       # skip long benchmark
    python 02_BM25_and_RRF_Combiner.py --quick       # self-tests only
    python 02_BM25_and_RRF_Combiner.py --out FILE     # write results JSON
"""

import argparse
import importlib.util
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 0.  Starship document corpus -- mixed technical codes & natural language
# ---------------------------------------------------------------------------

STARSHIP_CORPUS: List[str] = [
    # 0  - technical code ALPHA-9
    "Emergency warp plasma containment procedure code ALPHA-9 activated in engineering bay 3",
    # 1  - AURA + Crab Pulsar
    "Crab Pulsar synchrotron radiation induced memory desynchronization in AURA entity graph layer",
    # 2  - navigation code DELTA-12
    "Navigation deflector array realigned using stellar parallax correction algorithm DELTA-12",
    # 3  - life support module 7B
    "Life support O2 recycler module 7B operating at 94% efficiency after coolant flush cycle",
    # 4  - prompt injection batch 0x4F
    "Security sentinel detected indirect prompt injection in retrieved context chunk batch 0x4F",
    # 5  - warp field geometry
    "Warp field geometry coefficient epsilon recalculated for Messier 1 gravitational anomaly",
    # 6  - propulsion antimatter
    "Propulsion system antimatter injector flow rate stabilized at 2.4 kg per second",
    # 7  - HNSW index
    "HNSW vector index rebuilt with M=16 ef_construction=200 after memory core reset procedure",
    # 8  - BM25 calibration
    "BM25 lexical retrieval calibrated k1=1.5 b=0.75 for starship technical log corpus",
    # 9  - RRF deployment
    "Reciprocal Rank Fusion combiner deployed with smoothing constant k=60 for hybrid search",
    # 10 - GraphRAG Leiden
    "GraphRAG community detection identified 47 Leiden clusters in propulsion knowledge graph",
    # 11 - dense embeddings
    "Dense embedding model encoded 150000 maintenance logs into 768-dimensional vector space",
    # 12 - subspace comm
    "Quantum entanglement relay subspace frequency locked at 47.3 GHz for deep space comms",
    # 13 - electromagnetic interference
    "Electromagnetic interference from neutron star degraded subspace comm channel bandwidth 40%",
    # 14 - shield modulation
    "Shield modulation frequency rotated to 347.2 MHz to counter pulsar radiation harmonics",
    # 15 - hull integrity
    "Ship hull integrity scan shows micro-fracture on deck 14 section C requiring sealant protocol",
    # 16 - medical hologram
    "Emergency medical hologram activated in sickbay after crew radiation exposure incident deck 5",
    # 17 - dilithium crystal
    "Dilithium crystal matrix realignment completed using harmonic resonance frequency 42.7 kHz",
    # 18 - astrometrics
    "Astrometrics lab stellar cartography updated with 12000 new catalog entries from deep scan",
    # 19 - transporter
    "Transporter pattern buffer integrity verified with 99.97% signal fidelity after diagnostic",
    # 20 - phaser array
    "Phaser array power coupling rerouted through secondary EPS conduit on deck 12 port side",
    # 21 - RAG Triad
    "RAG Triad evaluation scored faithfulness 0.92 context relevance 0.88 answer relevance 0.95",
    # 22 - MemGPT
    "MemGPT operating system paged 2048 archival memories from vector store into working context",
    # 23 - inertial dampeners
    "Inertial dampener field harmonics adjusted to compensate for pulsar gravitational waves",
    # 24 - AURA subsystem nominal
    "AURA Subsystem 05 dual-path associative memory core status nominal after Crab Pulsar transit",
    # 25 - sensor array
    "Long range sensor array detected M-class planet bearing 127 mark 4 in adjacent sector",
    # 26 - relativistic shielding
    "Relativistic particle shielding requires magnetic field recalibration at 4.7 Tesla threshold",
    # 27 - telemetry Sirius
    "Telemetry logs from Sirius waypoint recorded zero anomalies across all navigation channels",
    # 28 - neural gel pack
    "Neural gel pack biological processor replaced in computer core junction room deck 8",
    # 29 - Zettelkasten
    "Zettelkasten atomic note links between propulsion and life support entities severed by radiation",
]

# ---------------------------------------------------------------------------
# Semantic concept clusters for building dense embeddings with real structure.
# Each cluster groups synonyms / conceptually related terms so that paraphrase
# queries without any shared keywords can still retrieve the right document.
# ---------------------------------------------------------------------------

CONCEPT_CLUSTERS: Dict[str, List[str]] = {
    "propulsion": [
        "warp", "plasma", "containment", "antimatter", "injector", "propulsion",
        "drive", "engine", "fuel", "thrust", "impulse", "nacelle", "dilithium",
        "crystal", "breach", "flow",
    ],
    "radiation_em": [
        "radiation", "electromagnetic", "synchrotron", "pulsar", "neutron",
        "photon", "crab", "remnant", "stellar", "harmonics", "frequency",
        "modulation", "shield", "particle", "relativistic", "interference",
    ],
    "ai_memory": [
        "aura", "memory", "desynchronization", "entity", "graph", "hnsw",
        "vector", "embedding", "index", "associative", "core", "memgpt",
        "archival", "working", "context", "paging", "neural", "processor",
    ],
    "retrieval": [
        "bm25", "lexical", "retrieval", "rrf", "fusion", "search", "dense",
        "sparse", "hybrid", "ranking", "scoring", "query", "corpus", "graphrag",
        "leiden", "community", "rag", "triad", "faithfulness", "relevance",
    ],
    "security": [
        "injection", "prompt", "adversarial", "security", "sentinel",
        "sanitizer", "quarantine", "exploit", "attack", "defence",
        "hijacking", "payload", "malicious",
    ],
    "navigation": [
        "navigation", "deflector", "parallax", "astrometrics", "cartography",
        "bearing", "sensor", "array", "scan", "telemetry", "waypoint",
        "coordinates", "course", "heading",
    ],
    "life_support": [
        "life", "support", "oxygen", "o2", "recycler", "coolant", "medical",
        "hologram", "sickbay", "exposure", "crew", "breathing", "air",
    ],
    "hull_systems": [
        "hull", "integrity", "fracture", "sealant", "deck", "transporter",
        "pattern", "buffer", "phaser", "eps", "conduit", "coupling", "power",
    ],
    "emergency": [
        "emergency", "procedure", "code", "protocol", "alert", "breach",
        "activated", "critical", "failure", "containment",
    ],
}



GROUND_TRUTH_EXACT: Dict[str, List[int]] = {
    # Code-bearing queries -- BM25 territory
    "containment procedure ALPHA-9":            [0],
    "algorithm DELTA-12 parallax":              [2],
    "prompt injection batch 0x4F":              [4],
    "module 7B recycler efficiency":            [3],
    "HNSW M=16 ef_construction":               [7],
    "k1=1.5 b=0.75 BM25 calibration":          [8],
    "Leiden clusters GraphRAG knowledge graph": [10],
    "EPS conduit phaser array deck 12":         [20],
}

GROUND_TRUTH_CONCEPT: Dict[str, List[int]] = {
    # Paraphrased queries -- Dense territory (no keyword overlap with target)
    # Target doc 0: "Emergency warp plasma containment procedure code ALPHA-9 ..."
    "fuel breach isolation drill":                          [0],
    # Target doc 1: "Crab Pulsar synchrotron radiation induced memory desynchronization ..."
    "stellar remnant photon corruption of AI associative links":  [1],
    # Target doc 5: "Warp field geometry coefficient epsilon ..."
    "faster-than-light drive spatial distortion calculations":   [5],
    # Target doc 3: "Life support O2 recycler module 7B ..."
    "breathing gas recycling unit performance":                  [3],
    # Target doc 4: "Security sentinel detected indirect prompt injection ..."
    "adversarial payload detection in search results":           [4],
    # Target doc 6: "Propulsion system antimatter injector flow rate ..."
    "engine fuel injection throughput stabilisation":            [6],
    # Target doc 13: "Electromagnetic interference from neutron star ..."
    "stellar body emission degrading communications bandwidth":  [13],
    # Target doc 16: "Emergency medical hologram activated in sickbay ..."
    "shipboard physician treating crew after photon exposure":   [16],
}

# Combined for convenience
GROUND_TRUTH: Dict[str, List[int]] = {**GROUND_TRUTH_EXACT, **GROUND_TRUTH_CONCEPT}


# ---------------------------------------------------------------------------
# 1.  Okapi BM25 Lexical Scoring Engine
# ---------------------------------------------------------------------------

class BM25Okapi:
    """
    Okapi BM25 scoring engine for exact keyword preservation and sparse lexical
    retrieval in the starship log corpus.

    BM25(q, d) = sum_{t in q}  IDF(t) * [ tf(t,d) * (k1 + 1) ]
                                        / [ tf(t,d) + k1 * (1 - b + b * |d|/avgdl) ]

    Parameters
    ----------
    corpus : list of str
        Raw document strings; tokenized internally.
    k1 : float
        Term frequency saturation parameter (default 1.5).
        Controls how much additional occurrences of a term increase the score.
        Higher k1 -> more credit for repeated terms before saturation.
    b : float
        Document length normalisation parameter (default 0.75).
        b = 0  -> no length penalty (long documents score same as short ones)
        b = 1  -> full length penalty (score shrinks proportionally with doc length)
    """

    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        if not corpus:
            raise ValueError("corpus must be non-empty")
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        self.doc_lens = [len(doc) for doc in self.tokenized_corpus]
        self.avgdl = sum(self.doc_lens) / self.corpus_size

        # Document frequencies: df[t] = number of documents containing term t
        self.df: Dict[str, int] = Counter()
        for doc_tokens in self.tokenized_corpus:
            for term in set(doc_tokens):
                self.df[term] += 1

        # Inverse Document Frequency -- Robertson-Sparck-Jones variant
        # IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
        self.idf: Dict[str, float] = {}
        for term, freq in self.df.items():
            self.idf[term] = math.log(
                1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5)
            )

        # Pre-compute per-document term frequency counters
        self._tf_cache: List[Counter] = [Counter(doc) for doc in self.tokenized_corpus]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        Lowercases and splits on non-alphanumeric boundaries.
        Note: hyphenated codes like ALPHA-9 are split into separate tokens
        ('alpha', '9'). This is intentional -- BM25 still retrieves the
        document because both sub-tokens match.
        """
        return re.findall(r"[a-z0-9_]+", text.lower())

    def idf_of(self, term: str) -> float:
        """Returns the IDF weight of a term (0.0 if unseen)."""
        return self.idf.get(term.lower(), 0.0)

    def score(self, query: str, top_k: Optional[int] = None) -> List[Tuple[int, float]]:
        """
        Scores every document against the query using the BM25 formula.

        Returns
        -------
        list of (doc_index, score) sorted descending by score.
        If top_k is given, only the top k results are returned.
        Only documents with score > 0 are included.
        """
        query_terms = self._tokenize(query)
        scores: List[Tuple[int, float]] = []

        for doc_idx in range(self.corpus_size):
            tf = self._tf_cache[doc_idx]
            doc_len = self.doc_lens[doc_idx]
            score = 0.0

            for term in query_terms:
                if term not in tf:
                    continue
                term_tf = tf[term]
                idf = self.idf.get(term, 0.0)

                # BM25 TF component with saturation and length normalisation
                numerator = term_tf * (self.k1 + 1.0)
                denominator = term_tf + self.k1 * (
                    1.0 - self.b + self.b * (doc_len / self.avgdl)
                )
                score += idf * (numerator / denominator)

            if score > 0.0:
                scores.append((doc_idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        if top_k is not None:
            return scores[:top_k]
        return scores

    def get_ranked_ids(self, query: str, top_k: Optional[int] = None) -> List[int]:
        """Returns just the doc indices in ranked order (zero-score docs excluded)."""
        return [doc_id for doc_id, _ in self.score(query, top_k)]

    def explain(self, query: str, doc_idx: int) -> Dict[str, Any]:
        """
        Term-level breakdown of BM25 score for one (query, doc) pair.
        Useful for debugging and interpretability.
        """
        query_terms = self._tokenize(query)
        tf = self._tf_cache[doc_idx]
        doc_len = self.doc_lens[doc_idx]
        breakdown: Dict[str, Dict[str, float]] = {}
        total = 0.0

        for term in query_terms:
            term_tf = tf.get(term, 0)
            idf = self.idf.get(term, 0.0)
            if term_tf == 0:
                breakdown[term] = {"tf": 0, "idf": round(idf, 4), "contribution": 0.0}
                continue
            numerator = term_tf * (self.k1 + 1.0)
            denominator = term_tf + self.k1 * (
                1.0 - self.b + self.b * (doc_len / self.avgdl)
            )
            contribution = idf * (numerator / denominator)
            total += contribution
            breakdown[term] = {
                "tf": term_tf,
                "idf": round(idf, 4),
                "tf_norm": round(numerator / denominator, 4),
                "contribution": round(contribution, 4),
            }

        return {
            "doc_idx": doc_idx,
            "doc_len": doc_len,
            "avgdl": round(self.avgdl, 2),
            "total_score": round(total, 4),
            "terms": breakdown,
        }

    def __repr__(self) -> str:
        return (
            f"BM25Okapi(N={self.corpus_size}, avgdl={self.avgdl:.1f}, "
            f"k1={self.k1}, b={self.b}, vocab={len(self.df)})"
        )


# ---------------------------------------------------------------------------
# 2.  Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(
    *rank_lists: List[int],
    k: int = 60,
) -> List[Tuple[int, float]]:
    """
    Reciprocal Rank Fusion (Cormack, Clarke & Buettcher, 2009).

    Merges an arbitrary number of ranked retrieval lists without score
    normalisation.

        RRF(d) = sum_{m in M}  1 / (k + rank_m(d))

    where rank_m(d) is the 1-based rank of document d in list m.

    Parameters
    ----------
    *rank_lists : list of list[int]
        Each is an ordered list of document IDs (best first).
        Zero-score documents should be excluded before calling this function.
    k : int
        Smoothing constant (default 60). Prevents over-weighting top-1 results.
        Higher k -> more uniform fusion; lower k -> more emphasis on top ranks.

    Returns
    -------
    list of (doc_id, rrf_score) sorted descending by fused score.
    """
    if k < 1:
        raise ValueError(f"smoothing parameter k must be >= 1, got {k}")

    rrf_scores: Dict[int, float] = defaultdict(float)

    for rank_list in rank_lists:
        for rank_0based, doc_id in enumerate(rank_list):
            # RRF uses 1-based rank
            rrf_scores[doc_id] += 1.0 / (k + rank_0based + 1)

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return merged


# Backward-compatible two-list signature matching the starter file
def reciprocal_rank_fusion_pair(
    dense_rankings: List[int],
    sparse_rankings: List[int],
    k: int = 60,
) -> List[Tuple[int, float]]:
    """Two-list RRF (backward compatible with starter file signature)."""
    return reciprocal_rank_fusion(dense_rankings, sparse_rankings, k=k)


def rrf_with_labels(
    named_lists: Dict[str, List[int]],
    k: int = 60,
) -> Tuple[List[Tuple[int, float]], Dict[int, Dict[str, int]]]:
    """
    Extended RRF that also returns per-document rank provenance.

    Returns
    -------
    (fused_ranking, provenance)
        provenance[doc_id][list_name] = 1-based rank in that list (absent if not ranked).
    """
    rrf_scores: Dict[int, float] = defaultdict(float)
    provenance: Dict[int, Dict[str, int]] = defaultdict(dict)

    for list_name, rank_list in named_lists.items():
        for rank_0, doc_id in enumerate(rank_list):
            rank_1 = rank_0 + 1
            rrf_scores[doc_id] += 1.0 / (k + rank_1)
            provenance[doc_id][list_name] = rank_1

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return merged, dict(provenance)


# ---------------------------------------------------------------------------
# 3.  Evaluation Metrics: MRR and NDCG@k
# ---------------------------------------------------------------------------

def mean_reciprocal_rank(
    ranked_results: List[List[int]],
    ground_truths: List[Set[int]],
) -> float:
    """
    Mean Reciprocal Rank (MRR).

        MRR = (1/|Q|) sum_{q}  1 / rank_q

    where rank_q is the position of the first relevant document in the
    ranked list for query q (1-based). If no relevant document is found,
    the reciprocal rank for that query is 0.
    """
    if len(ranked_results) != len(ground_truths):
        raise ValueError("ranked_results and ground_truths must have the same length")

    rr_sum = 0.0
    for ranked, relevant in zip(ranked_results, ground_truths):
        for rank_0, doc_id in enumerate(ranked):
            if doc_id in relevant:
                rr_sum += 1.0 / (rank_0 + 1)
                break
        # else: no relevant doc found, contributes 0

    return rr_sum / len(ranked_results) if ranked_results else 0.0


def dcg_at_k(ranked: List[int], relevant: Set[int], k: int) -> float:
    """
    Discounted Cumulative Gain at rank k.

        DCG@k = sum_{i=1}^{k}  rel(i) / log2(i + 1)

    where rel(i) = 1 if document at rank i is relevant, else 0.
    """
    score = 0.0
    for i, doc_id in enumerate(ranked[:k]):
        if doc_id in relevant:
            score += 1.0 / math.log2(i + 2)  # i is 0-based, formula uses 1-based
    return score


def ndcg_at_k(
    ranked_results: List[List[int]],
    ground_truths: List[Set[int]],
    k: int = 10,
) -> float:
    """
    Normalised Discounted Cumulative Gain at rank k (NDCG@k).

        NDCG@k = DCG@k / IDCG@k

    where IDCG@k is the DCG of the ideal ranking (all relevant docs at the top).
    Averaged over all queries. Queries with no relevant documents contribute 0.
    """
    if len(ranked_results) != len(ground_truths):
        raise ValueError("ranked_results and ground_truths must have the same length")

    ndcg_sum = 0.0
    for ranked, relevant in zip(ranked_results, ground_truths):
        if not relevant:
            continue

        dcg = dcg_at_k(ranked, relevant, k)

        # Ideal DCG: all relevant docs ranked at the top
        n_rel_in_k = min(len(relevant), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(n_rel_in_k))

        if idcg > 0:
            ndcg_sum += dcg / idcg

    return ndcg_sum / len(ranked_results) if ranked_results else 0.0


def precision_at_k(
    ranked_results: List[List[int]],
    ground_truths: List[Set[int]],
    k: int = 10,
) -> float:
    """Precision@k averaged over all queries."""
    if len(ranked_results) != len(ground_truths):
        raise ValueError("mismatched lengths")
    prec_sum = 0.0
    for ranked, relevant in zip(ranked_results, ground_truths):
        hits = sum(1 for doc_id in ranked[:k] if doc_id in relevant)
        prec_sum += hits / k
    return prec_sum / len(ranked_results) if ranked_results else 0.0


def recall_at_k(
    ranked_results: List[List[int]],
    ground_truths: List[Set[int]],
    k: int = 10,
) -> float:
    """Recall@k averaged over all queries."""
    if len(ranked_results) != len(ground_truths):
        raise ValueError("mismatched lengths")
    rec_sum = 0.0
    for ranked, relevant in zip(ranked_results, ground_truths):
        if not relevant:
            continue
        hits = sum(1 for doc_id in ranked[:k] if doc_id in relevant)
        rec_sum += hits / len(relevant)
    return rec_sum / len(ranked_results) if ranked_results else 0.0


# ---------------------------------------------------------------------------
# 4.  Semantic Embedding Builder (concept-cluster based)
# ---------------------------------------------------------------------------

class ConceptEmbedder:
    """
    Builds dense embeddings where terms in the same semantic cluster have
    correlated vectors.  This gives paraphrase queries (no shared keywords)
    a real geometric advantage over bag-of-words / BM25.

    Each concept cluster gets a random centroid in R^dim. A term's vector
    is its cluster centroid plus a small per-term perturbation. Terms not
    in any cluster get an independent random vector.

    Document / query embeddings are the mean of their token vectors,
    L2-normalised.
    """

    def __init__(self, clusters: Dict[str, List[str]], dim: int = 128, seed: int = 42):
        self.dim = dim
        rng = np.random.default_rng(seed)

        # Build cluster centroids -- orthogonalised via QR so clusters are
        # maximally separated in high-dimensional space.
        n_clusters = len(clusters)
        raw = rng.standard_normal((n_clusters, dim)).astype(np.float32)
        Q, _ = np.linalg.qr(raw.T)  # Q columns are orthonormal
        centroid_matrix = Q.T[:n_clusters]  # one row per cluster

        centroids: Dict[str, np.ndarray] = {}
        for i, name in enumerate(clusters):
            centroids[name] = centroid_matrix[i]

        # Build per-term vectors: centroid + small noise so intra-cluster
        # terms have high cosine similarity (~0.85-0.95 pairwise).
        self._vocab: Dict[str, np.ndarray] = {}
        perturbation_scale = 0.15

        for cluster_name, terms in clusters.items():
            centroid = centroids[cluster_name]
            for term in terms:
                t = term.lower()
                if t not in self._vocab:
                    noise = rng.standard_normal(dim).astype(np.float32) * perturbation_scale
                    v = centroid + noise
                    self._vocab[t] = v / np.linalg.norm(v)

        # Out-of-vocabulary terms get random vectors (low similarity to any
        # cluster), so they dilute the embedding rather than biasing it.
        self._rng = rng

    def _token_vec(self, token: str) -> np.ndarray:
        """Returns the vector for a token, creating a random one if unseen."""
        t = token.lower()
        if t not in self._vocab:
            v = self._rng.standard_normal(self.dim).astype(np.float32)
            self._vocab[t] = v / np.linalg.norm(v)
        return self._vocab[t]

    def embed(self, text: str) -> np.ndarray:
        """Mean-pool token vectors, L2-normalise."""
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        if not tokens:
            return np.zeros(self.dim, dtype=np.float32)
        vecs = np.array([self._token_vec(t) for t in tokens])
        mean = vecs.mean(axis=0)
        norm = np.linalg.norm(mean)
        if norm < 1e-12:
            return np.zeros(self.dim, dtype=np.float32)
        return (mean / norm).astype(np.float32)


# ---------------------------------------------------------------------------
# 5.  HNSW Integration (real dense retrieval)
# ---------------------------------------------------------------------------

def _load_hnsw_module():
    """
    Imports the Systems Architect's HNSW module from the same directory.
    Raises ImportError with a clear message if the file is missing or broken.
    """
    hnsw_path = Path(__file__).resolve().parent / "01_HNSW_Vector_Index.py"
    if not hnsw_path.exists():
        raise ImportError(
            f"01_HNSW_Vector_Index.py not found at {hnsw_path}. "
            "The Systems Architect's deliverable is required for dense retrieval."
        )
    spec = importlib.util.spec_from_file_location("hnsw_module", str(hnsw_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {hnsw_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_hnsw_rankings(
    corpus: List[str],
    queries: List[str],
    embedder: ConceptEmbedder,
    top_k: int = 30,
) -> Dict[str, List[int]]:
    """
    Builds an HNSW index over the corpus using concept-cluster embeddings
    and returns per-query rankings.

    Raises ImportError if the HNSW module is unavailable.
    """
    hnsw_mod = _load_hnsw_module()
    HNSWIndex = hnsw_mod.HNSWIndex

    dim = embedder.dim
    index = HNSWIndex(dim=dim, M=8, ef_construction=64, ef_search=48, seed=42)

    for i, doc in enumerate(corpus):
        index.insert(i, embedder.embed(doc))

    rankings: Dict[str, List[int]] = {}
    for query in queries:
        q_vec = embedder.embed(query)
        results = index.query(q_vec, top_k=top_k)
        rankings[query] = [doc_id for doc_id, _ in results]

    return rankings


# ---------------------------------------------------------------------------
# 6.  Self-Tests
# ---------------------------------------------------------------------------

def run_self_tests() -> None:
    print("=" * 78)
    print("USSE NOOSPHERE - SUBSYSTEM 05: BM25 & RRF COMBINER - SELF-TESTS")
    print("=" * 78)

    # ---- [1] BM25 scoring fundamentals -----------------------------------
    mini_corpus = [
        "the cat sat on the mat",
        "the dog chased the cat",
        "fish swim in the ocean",
    ]
    bm25 = BM25Okapi(mini_corpus, k1=1.5, b=0.75)

    # "cat" appears in docs 0 and 1 but not 2; docs 0,1 should rank above 2
    results = bm25.score("cat")
    top_ids = [r[0] for r in results]
    assert set(top_ids) == {0, 1}, f"expected docs 0,1 for 'cat', got {top_ids}"
    assert 2 not in top_ids, "doc 2 should not appear (zero-score filtered out)"
    print("[1] BM25 basic scoring: correct top-2 for 'cat'; zero-score doc excluded")

    # ---- [2] IDF correctness --------------------------------------------
    # "the" appears in all 3 docs -> IDF should be low
    # "ocean" appears in 1 doc  -> IDF should be high
    assert bm25.idf_of("the") < bm25.idf_of("ocean"), \
        "IDF('the') should be < IDF('ocean')"
    assert bm25.idf_of("xyzzy") == 0.0
    print("[2] IDF: common term 'the' has lower IDF than rare term 'ocean'")

    # ---- [3] k1 saturation effect ----------------------------------------
    bm25_low_k1 = BM25Okapi(mini_corpus, k1=0.5, b=0.75)
    bm25_high_k1 = BM25Okapi(mini_corpus, k1=3.0, b=0.75)
    score_low = bm25_low_k1.score("the")[0][1]
    score_high = bm25_high_k1.score("the")[0][1]
    print(f"[3] k1 saturation: k1=0.5 -> {score_low:.4f}, k1=3.0 -> {score_high:.4f}")

    # ---- [4] b length normalisation effect --------------------------------
    length_corpus = [
        "plasma containment",  # short doc
        "plasma containment emergency procedure for warp core breach alpha nine",  # long doc
    ]
    bm25_b0 = BM25Okapi(length_corpus, k1=1.5, b=0.0)
    bm25_b1 = BM25Okapi(length_corpus, k1=1.5, b=1.0)
    scores_b0 = bm25_b0.score("plasma containment")
    scores_b1 = bm25_b1.score("plasma containment")
    ratio_b0 = scores_b0[0][1] / max(scores_b0[1][1], 1e-12)
    ratio_b1 = scores_b1[0][1] / max(scores_b1[1][1], 1e-12)
    print(f"[4] b normalisation: score_ratio(short/long) b=0->{ratio_b0:.3f}, b=1->{ratio_b1:.3f}")

    # ---- [5] Zero-score filtering ----------------------------------------
    full_bm25 = BM25Okapi(STARSHIP_CORPUS)
    results_alpha = full_bm25.score("ALPHA-9 containment")
    assert all(s > 0 for _, s in results_alpha), "all returned docs should have positive score"
    assert len(results_alpha) < len(STARSHIP_CORPUS), \
        f"should filter zero-score docs: got {len(results_alpha)}/{len(STARSHIP_CORPUS)}"
    print(f"[5] Zero-score filtering: 'ALPHA-9 containment' returns {len(results_alpha)}/{len(STARSHIP_CORPUS)} docs")

    # ---- [6] RRF fusion correctness --------------------------------------
    dense = [3, 1, 0, 2, 4]
    sparse = [1, 3, 4, 0, 2]
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    fused_ids = [doc_id for doc_id, _ in fused]
    assert set(fused_ids[:2]) == {1, 3}, f"expected docs 1,3 at top after RRF, got {fused_ids[:2]}"
    expected_rrf_1 = 1.0 / 62 + 1.0 / 61
    actual_rrf_1 = dict(fused)[1]
    assert abs(actual_rrf_1 - expected_rrf_1) < 1e-10
    print(f"[6] RRF fusion: docs {{1,3}} correctly ranked top-2; RRF(doc1) = {actual_rrf_1:.6f} [OK]")

    # ---- [7] Backward-compatible two-list RRF ----------------------------
    fused_pair = reciprocal_rank_fusion_pair(dense, sparse, k=60)
    assert fused_pair == fused, "reciprocal_rank_fusion_pair should match *args version"
    print("[7] Backward-compatible two-list RRF signature matches [OK]")

    # ---- [8] MRR computation ---------------------------------------------
    ranked = [[0, 1, 2], [2, 0, 1], [1, 2, 0]]
    truths = [{0}, {1}, {2}]
    mrr = mean_reciprocal_rank(ranked, truths)
    expected_mrr = (1.0 + 1.0 / 3 + 1.0 / 2) / 3
    assert abs(mrr - expected_mrr) < 1e-10
    print(f"[8] MRR = {mrr:.4f} (expected {expected_mrr:.4f}) [OK]")

    # ---- [9] NDCG@k computation ------------------------------------------
    perfect = [[0, 1, 2]]
    perfect_truth = [{0, 1}]
    ndcg_perfect = ndcg_at_k(perfect, perfect_truth, k=3)
    assert abs(ndcg_perfect - 1.0) < 1e-10

    worst = [[2, 3, 0, 1]]
    worst_truth = [{0, 1}]
    ndcg_worst = ndcg_at_k(worst, worst_truth, k=4)
    assert ndcg_worst < 1.0
    print(f"[9] NDCG: perfect = {ndcg_perfect:.4f}, degraded = {ndcg_worst:.4f} [OK]")

    # ---- [10] ConceptEmbedder cluster coherence --------------------------
    embedder = ConceptEmbedder(CONCEPT_CLUSTERS, dim=128, seed=42)
    # Terms in the same cluster should be more similar than cross-cluster terms
    v_plasma = embedder._token_vec("plasma")
    v_warp = embedder._token_vec("warp")           # same cluster: propulsion
    v_sensor = embedder._token_vec("sensor")        # different cluster: navigation
    sim_same = float(v_plasma @ v_warp)
    sim_diff = float(v_plasma @ v_sensor)
    assert sim_same > sim_diff, \
        f"intra-cluster sim ({sim_same:.3f}) should exceed inter-cluster ({sim_diff:.3f})"
    print(f"[10] Concept embeddings: sim(plasma,warp)={sim_same:.3f} > sim(plasma,sensor)={sim_diff:.3f} [OK]")

    print("\n[SUCCESS] All BM25 & RRF self-tests passed.\n")


# ---------------------------------------------------------------------------
# 7.  Benchmark: BM25, Dense (HNSW), and Hybrid RRF -- per query type
# ---------------------------------------------------------------------------

def _eval_metrics(
    ranked: List[List[int]], truths: List[Set[int]], k: int = 10
) -> Dict[str, float]:
    return {
        "MRR": round(mean_reciprocal_rank(ranked, truths), 4),
        "NDCG@10": round(ndcg_at_k(ranked, truths, k=k), 4),
        "P@10": round(precision_at_k(ranked, truths, k=k), 4),
        "R@10": round(recall_at_k(ranked, truths, k=k), 4),
    }


def run_benchmark(verbose: bool = True) -> Dict[str, Any]:
    """
    Evaluates BM25, Dense (HNSW + concept embeddings), and Hybrid RRF
    on the starship corpus.  Reports metrics split by query type:
      - Exact-code queries (BM25 territory)
      - Paraphrase queries (Dense territory)
      - Combined
    """
    corpus = STARSHIP_CORPUS
    results: Dict[str, Any] = {
        "corpus_size": len(corpus),
        "bm25_params": {"k1": 1.5, "b": 0.75},
        "rrf_k": 60,
    }

    if verbose:
        print("=" * 78)
        print("SUBSYSTEM 05: HYBRID RETRIEVAL BENCHMARK")
        print("=" * 78)
        print(f"\nCorpus: {len(corpus)} starship documents")

    # ---- Build retrievers ------------------------------------------------
    bm25 = BM25Okapi(corpus, k1=1.5, b=0.75)
    embedder = ConceptEmbedder(CONCEPT_CLUSTERS, dim=128, seed=42)

    if verbose:
        print(f"BM25 index: {bm25}")

    # Build HNSW dense index -- fail loudly if unavailable
    try:
        all_queries = list(GROUND_TRUTH.keys())
        hnsw_rankings = build_hnsw_rankings(corpus, all_queries, embedder)
        if verbose:
            print("HNSW dense index: loaded from 01_HNSW_Vector_Index.py")
    except ImportError as e:
        print(f"\n[ERROR] Cannot build dense retrieval: {e}")
        print("Dense and hybrid results will not be available.")
        print("Fix: ensure 01_HNSW_Vector_Index.py is in the same directory.\n")
        # Run BM25-only evaluation
        all_queries_e = list(GROUND_TRUTH_EXACT.keys())
        truths_e = [set(GROUND_TRUTH_EXACT[q]) for q in all_queries_e]
        bm25_ranked_e = [bm25.get_ranked_ids(q) for q in all_queries_e]
        results["bm25_exact"] = _eval_metrics(bm25_ranked_e, truths_e)
        if verbose:
            print("--- BM25 on exact-code queries (dense unavailable) ---")
            for k_, v_ in results["bm25_exact"].items():
                print(f"  {k_:<10} = {v_}")
        return results

    # ---- Define query groups ---------------------------------------------
    query_groups = {
        "exact": (GROUND_TRUTH_EXACT, "Exact-code queries (BM25 territory)"),
        "concept": (GROUND_TRUTH_CONCEPT, "Paraphrase queries (Dense territory)"),
        "all": (GROUND_TRUTH, "All queries combined"),
    }

    results["n_queries"] = {
        "exact": len(GROUND_TRUTH_EXACT),
        "concept": len(GROUND_TRUTH_CONCEPT),
        "total": len(GROUND_TRUTH),
    }

    if verbose:
        print(f"Queries: {len(GROUND_TRUTH_EXACT)} exact-code + "
              f"{len(GROUND_TRUTH_CONCEPT)} paraphrase = {len(GROUND_TRUTH)} total\n")

    # ---- Evaluate each method x query group ------------------------------
    for group_key, (gt_dict, group_label) in query_groups.items():
        queries = list(gt_dict.keys())
        truths = [set(gt_dict[q]) for q in queries]

        # BM25
        t0 = time.perf_counter()
        bm25_ranked = [bm25.get_ranked_ids(q) for q in queries]
        bm25_ms = (time.perf_counter() - t0) * 1000 / max(len(queries), 1)

        # Dense (HNSW)
        dense_ranked = [hnsw_rankings.get(q, []) for q in queries]

        # Hybrid RRF
        rrf_ranked: List[List[int]] = []
        for i in range(len(queries)):
            fused = reciprocal_rank_fusion(bm25_ranked[i], dense_ranked[i], k=60)
            rrf_ranked.append([doc_id for doc_id, _ in fused])

        bm25_m = _eval_metrics(bm25_ranked, truths)
        dense_m = _eval_metrics(dense_ranked, truths)
        rrf_m = _eval_metrics(rrf_ranked, truths)

        results[f"bm25_{group_key}"] = bm25_m
        results[f"dense_{group_key}"] = dense_m
        results[f"rrf_{group_key}"] = rrf_m

        if verbose:
            print(f"--- {group_label} (n={len(queries)}) ---")
            print(f"  {'Method':<20}  {'MRR':>8}  {'NDCG@10':>8}  {'P@10':>8}  {'R@10':>8}")
            print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
            for method, m in [("BM25 (sparse)", bm25_m), ("Dense (HNSW)", dense_m), ("Hybrid RRF k=60", rrf_m)]:
                print(f"  {method:<20}  {m['MRR']:>8.4f}  {m['NDCG@10']:>8.4f}  {m['P@10']:>8.4f}  {m['R@10']:>8.4f}")
            print()

    # ---- Per-query detail table ------------------------------------------
    if verbose:
        print("--- Per-Query Detail (top-1 hit?) ---")
        print(f"  {'Type':<8} {'Query':<58} {'BM25':>5} {'Dense':>5} {'RRF':>5}")
        print(f"  {'-'*8} {'-'*58} {'-'*5} {'-'*5} {'-'*5}")

    per_query_detail: List[Dict[str, Any]] = []
    for qtype, gt_dict in [("EXACT", GROUND_TRUTH_EXACT), ("CONCEPT", GROUND_TRUTH_CONCEPT)]:
        for query, rel_ids in gt_dict.items():
            rel_set = set(rel_ids)
            bm25_ids = bm25.get_ranked_ids(query)
            dense_ids = hnsw_rankings.get(query, [])
            fused = reciprocal_rank_fusion(bm25_ids, dense_ids, k=60)
            rrf_ids = [d for d, _ in fused]

            bm25_hit = bm25_ids[0] in rel_set if bm25_ids else False
            dense_hit = dense_ids[0] in rel_set if dense_ids else False
            rrf_hit = rrf_ids[0] in rel_set if rrf_ids else False

            detail = {
                "type": qtype, "query": query, "relevant": rel_ids,
                "bm25_hit": bm25_hit, "dense_hit": dense_hit, "rrf_hit": rrf_hit,
                "bm25_top3": bm25_ids[:3], "dense_top3": dense_ids[:3], "rrf_top3": rrf_ids[:3],
            }
            per_query_detail.append(detail)

            if verbose:
                q_short = query[:56] + ".." if len(query) > 58 else query
                b = "Y" if bm25_hit else "N"
                d = "Y" if dense_hit else "N"
                r = "Y" if rrf_hit else "N"
                print(f"  {qtype:<8} {q_short:<58} {b:>5} {d:>5} {r:>5}")

    results["per_query"] = per_query_detail

    # ---- k sensitivity sweep (on all queries) ----------------------------
    all_queries = list(GROUND_TRUTH.keys())
    all_truths = [set(GROUND_TRUTH[q]) for q in all_queries]
    bm25_all = [bm25.get_ranked_ids(q) for q in all_queries]
    dense_all = [hnsw_rankings.get(q, []) for q in all_queries]

    if verbose:
        print(f"\n--- RRF Smoothing Parameter k Sweep (all {len(all_queries)} queries) ---")
        print(f"  {'k':>6}  {'MRR':>8}  {'NDCG@10':>8}")
        print(f"  {'---':>6}  {'---':>8}  {'---':>8}")

    k_sweep: List[Dict[str, Any]] = []
    for k_val in [1, 10, 30, 60, 100, 200]:
        k_fused: List[List[int]] = []
        for i in range(len(all_queries)):
            fused = reciprocal_rank_fusion(bm25_all[i], dense_all[i], k=k_val)
            k_fused.append([doc_id for doc_id, _ in fused])
        k_mrr = mean_reciprocal_rank(k_fused, all_truths)
        k_ndcg = ndcg_at_k(k_fused, all_truths, k=10)
        k_sweep.append({"k": k_val, "MRR": round(k_mrr, 4), "NDCG@10": round(k_ndcg, 4)})
        if verbose:
            print(f"  {k_val:>6}  {k_mrr:>8.4f}  {k_ndcg:>8.4f}")

    results["k_sweep"] = k_sweep

    # ---- Summary ---------------------------------------------------------
    if verbose:
        print(f"\n{'=' * 78}")
        print("RETRIEVAL COMPARISON SUMMARY")
        print(f"{'=' * 78}")
        print()
        print("Expected pattern:")
        print("  - BM25 wins on EXACT-CODE queries (keyword match)")
        print("  - Dense wins on PARAPHRASE queries (semantic similarity)")
        print("  - Hybrid RRF holds up on BOTH")
        print(f"{'=' * 78}")

    return results


# ---------------------------------------------------------------------------
# 8.  BM25 Term-Level Demo: Interpretability Trace
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """Detailed BM25 scoring demonstration with term-level explanations."""
    print("\n" + "=" * 78)
    print("SUBSYSTEM 05: BM25 LEXICAL RETRIEVAL - DETAILED TRACE")
    print("=" * 78)

    bm25 = BM25Okapi(STARSHIP_CORPUS, k1=1.5, b=0.75)
    print(f"\nIndex: {bm25}\n")

    demo_queries = [
        ("EXACT", "containment procedure ALPHA-9"),
        ("EXACT", "algorithm DELTA-12 parallax"),
        ("CONCEPT", "fuel breach isolation drill"),
        ("CONCEPT", "stellar remnant photon corruption of AI associative links"),
    ]

    for qtype, query in demo_queries:
        print(f"[{qtype}] QUERY: \"{query}\"")
        results = bm25.score(query, top_k=3)
        if not results:
            print("  (no results -- all docs scored zero)")
        for rank, (doc_id, score) in enumerate(results, 1):
            doc_preview = STARSHIP_CORPUS[doc_id][:75]
            print(f"  #{rank} Doc {doc_id:>2} (BM25={score:.4f}): \"{doc_preview}...\"")
            explanation = bm25.explain(query, doc_id)
            for term, info in explanation["terms"].items():
                if info["contribution"] > 0:
                    print(f"       -> '{term}': tf={info['tf']}, "
                          f"idf={info['idf']}, contribution={info['contribution']}")
        print()

    # RRF fusion demonstration
    print("-" * 78)
    print("RRF FUSION DEMONSTRATION")
    print("-" * 78)
    query = "stellar remnant photon corruption of AI associative links"
    bm25_ids = bm25.get_ranked_ids(query, top_k=10)

    try:
        embedder = ConceptEmbedder(CONCEPT_CLUSTERS, dim=128, seed=42)
        dense_rankings = build_hnsw_rankings(
            STARSHIP_CORPUS, [query], embedder
        )
        dense_ids = dense_rankings[query][:10]
    except ImportError:
        print("  (HNSW unavailable -- skipping RRF demo)")
        return

    fused, provenance = rrf_with_labels({"BM25": bm25_ids, "Dense": dense_ids}, k=60)

    print(f"\n[CONCEPT] Query: \"{query}\"")
    print(f"  Target: doc 1 (Crab Pulsar synchrotron radiation...)")
    print(f"\n  BM25  returns: {bm25_ids[:5]}  (may miss target -- no shared keywords)")
    print(f"  Dense returns: {dense_ids[:5]}  (should find target via semantic cluster)")
    print(f"\n  {'Rank':<6} {'DocID':<8} {'RRF Score':<12} {'BM25 rank':<12} {'Dense rank':<12}")
    print(f"  {'-'*6} {'-'*8} {'-'*12} {'-'*12} {'-'*12}")
    for rank, (doc_id, rrf_score) in enumerate(fused[:8], 1):
        prov = provenance.get(doc_id, {})
        bm25_r = str(prov.get("BM25", "-"))
        dense_r = str(prov.get("Dense", "-"))
        print(f"  {rank:<6} {doc_id:<8} {rrf_score:<12.6f} {bm25_r:<12} {dense_r:<12}")
    print()


# Main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Mission 05 Part 2: BM25 & RRF Combiner"
    )
    ap.add_argument("--quick", action="store_true", help="self-tests only, skip benchmark")
    ap.add_argument("--out", default=None, help="write benchmark results to JSON file")
    ap.add_argument("--skip-tests", action="store_true", help="skip self-tests")
    ap.add_argument("--demo-only", action="store_true", help="run only the detailed BM25 demo")
    args = ap.parse_args()

    if args.demo_only:
        run_demo()
        sys.exit(0)

    if not args.skip_tests:
        run_self_tests()

    if not args.quick:
        run_demo()
        results = run_benchmark(verbose=True)
        if args.out:
            out_path = args.out
            with open(out_path, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\nResults written to {out_path}")
    else:
        print("[quick mode] Benchmark skipped. Run without --quick for full evaluation.")
