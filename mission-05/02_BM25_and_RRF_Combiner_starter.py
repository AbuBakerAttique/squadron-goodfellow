"""
Mission 05 — Part 2: Communications & Protocol Officer
Okapi BM25 Lexical Retrieval & Reciprocal Rank Fusion (RRF)

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-05-M01 (Crab Pulsar Remnant / Messier 1)
Subsystem 05: Dual-Path Associative Memory Core
"""

import math
from collections import Counter
from typing import List, Dict, Tuple


class BM25Okapi:
    """
    Okapi BM25 scoring engine for exact keyword preservation and sparse lexical retrieval.
    """
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.tokenized_corpus = [doc.lower().split() for doc in corpus]
        self.doc_lens = [len(doc) for doc in self.tokenized_corpus]
        self.avgdl = sum(self.doc_lens) / self.corpus_size if self.corpus_size > 0 else 0.0

        # Term document frequencies
        self.df: Dict[str, int] = Counter()
        for doc in self.tokenized_corpus:
            unique_terms = set(doc)
            for term in unique_terms:
                self.df[term] += 1

        # Inverse Document Frequency (IDF)
        self.idf: Dict[str, float] = {}
        for term, freq in self.df.items():
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score(self, query: str) -> List[Tuple[int, float]]:
        """Scores each document against query using BM25 formula."""
        query_terms = query.lower().split()
        scores = []

        for doc_idx, doc in enumerate(self.tokenized_corpus):
            doc_len = self.doc_lens[doc_idx]
            tf = Counter(doc)
            score = 0.0

            for term in query_terms:
                if term in tf:
                    term_tf = tf[term]
                    numerator = term_tf * (self.k1 + 1.0)
                    denominator = term_tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avgdl))
                    score += self.idf.get(term, 0.0) * (numerator / denominator)

            scores.append((doc_idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


def reciprocal_rank_fusion(
    dense_rankings: List[int],
    sparse_rankings: List[int],
    k: int = 60
) -> List[Tuple[int, float]]:
    """
    Merges dense vector ranking and sparse lexical ranking via Reciprocal Rank Fusion (RRF).
    RRF(d) = sum_{m in {dense, sparse}} 1 / (k + rank_m(d))
    """
    rrf_scores: Dict[int, float] = {}

    for rank, doc_id in enumerate(dense_rankings):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

    for rank, doc_id in enumerate(sparse_rankings):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return merged


if __name__ == "__main__":
    docs = [
        "AURA Subsystem 05 contains the dual-path associative memory core",
        "Pulsar radiation in Crab nebula induces high frequency electromagnetic interference",
        "Warp drive emergency plasma containment procedure code ALPHA-9",
        "Telemetry logs from Sirius waypoint recorded zero anomalies",
        "Relativistic particles from neutron star require magnetic shield recalibration"
    ]
    bm25 = BM25Okapi(docs)
    query = "plasma containment emergency ALPHA-9"
    results = bm25.score(query)
    print("=== Subsystem 05: BM25 Lexical Retrieval Scores ===")
    for doc_id, score in results[:3]:
        print(f"Doc {doc_id} (Score: {score:.4f}): '{docs[doc_id]}'")

    # Sample RRF merge
    dense_ranks = [2, 0, 1, 4, 3]
    sparse_ranks = [res[0] for res in results]
    merged_ranks = reciprocal_rank_fusion(dense_ranks, sparse_ranks, k=60)
    print("\n=== Reciprocal Rank Fusion Combined Rankings ===")
    for doc_id, rrf_val in merged_ranks[:3]:
        print(f"Doc {doc_id} -> RRF Score: {rrf_val:.6f}")
