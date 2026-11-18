"""
USSE Noosphere — Mission 09 (SEC-09-LMC: Large Magellanic Cloud / Tarantula Nebula)
Station Role 3: Data & Payload Specialist
Deliverable: torchtpu_hbm_indexer.py
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math
import torch
import torch.nn.functional as F

try:
    import torch_tpu  # type: ignore
    HAS_TORCHTPU = True
except ImportError:
    HAS_TORCHTPU = False


def get_compute_device() -> torch.device:
    if HAS_TORCHTPU and hasattr(torch, "tpu") and torch.tpu.is_available():
        return torch.device("tpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


@dataclass
class EpistemicClaim:
    doc_id: str
    entity: str
    attribute: str
    value: str
    timestamp_year: int
    authority_tier: float  # in [0.0, 1.0], e.g. 1.0 = Primary Observatory Telemetry, 0.4 = Legacy Archive


@dataclass
class ContradictionResolution:
    entity: str
    attribute: str
    winning_doc_id: str
    winning_value: str
    winning_weight: float
    superseded_claims: List[Tuple[str, str, int]]
    audit_explanation: str


def _normalise(tensor: torch.Tensor) -> torch.Tensor:
    """Normalise in FP32, then store/multiply in BF16."""
    if not tensor.is_floating_point() or not torch.isfinite(tensor).all().item():
        raise ValueError("Embeddings must be finite floating-point tensors")
    return F.normalize(tensor.float(), p=2, dim=-1).to(torch.bfloat16)


def _mask(mask: Optional[torch.Tensor], shape: Tuple[int, ...], device: torch.device) -> torch.Tensor:
    if mask is None:
        return torch.ones(shape, dtype=torch.bool, device=device)
    if tuple(mask.shape) != shape or mask.dtype != torch.bool:
        raise ValueError(f"Mask must be boolean with shape {shape}; True means valid")
    return mask.to(device)


def _reduce_maxsim(sim: torch.Tensor, query_mask: torch.Tensor, doc_mask: torch.Tensor) -> torch.Tensor:
    # Zero padding cannot be allowed to beat a genuinely negative match.
    masked = sim.masked_fill(~doc_mask[:, None, :], -torch.inf)
    maxima = masked.max(dim=-1).values.float()
    maxima = maxima.masked_fill(~query_mask, 0.0)
    scores = maxima.sum(dim=-1)
    return scores.masked_fill(~doc_mask.any(dim=-1), -torch.inf)


def colbert_maxsim_bfloat16(
    query_Interaction: torch.Tensor,
    doc_Interaction: torch.Tensor,
    query_mask: Optional[torch.Tensor] = None,
    doc_mask: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """Compatibility scorer for paired [B,Q,D] and [B,L,D] inputs.

    True mask entries are real tokens. Entirely padded documents score -inf;
    queries with no valid tokens are rejected. Returns FP32 sums.
    """
    q, d = query_Interaction, doc_Interaction
    if q.ndim != 3 or d.ndim != 3 or q.shape[0] != d.shape[0] or q.shape[2] != d.shape[2]:
        raise ValueError("Expected compatible [B,Q,D] and [B,L,D] tensors")
    if min(q.shape[1:]) == 0 or d.shape[1] == 0 or q.device != d.device:
        raise ValueError("Token dimensions must be non-empty and devices must match")
    qm = _mask(query_mask, tuple(q.shape[:2]), q.device)
    dm = _mask(doc_mask, tuple(d.shape[:2]), d.device)
    if not qm.any(dim=-1).all().item():
        raise ValueError("Every query needs a valid token")
    sim = torch.matmul(_normalise(q), _normalise(d).transpose(-1, -2))
    return _reduce_maxsim(sim, qm, dm)


class EpistemicContradictionResolver:
    """Rank current-state claims for one entity/attribute, not establish truth.

    Authority values and publication dates are supplied metadata. Historical
    claims may have been correct in their own era; lower rank does not erase them.
    """

    def resolve_contradictions(self, claims: List[EpistemicClaim], current_year: int = 2026,
                               alpha: float = 0.55, decay_lambda: float = 0.04) -> ContradictionResolution:
        if not claims:
            raise ValueError("Claims list cannot be empty")
        if not 0 <= alpha <= 1 or not math.isfinite(decay_lambda) or decay_lambda < 0:
            raise ValueError("alpha must be in [0,1]; decay_lambda must be finite/non-negative")
        group = (claims[0].entity, claims[0].attribute)
        if len({c.doc_id for c in claims}) != len(claims):
            raise ValueError("Claim document IDs must be unique")
        scored = []
        for claim in claims:
            if (claim.entity, claim.attribute) != group:
                raise ValueError("Claims must concern the same entity and attribute")
            if not 0 <= claim.authority_tier <= 1 or claim.timestamp_year > current_year:
                raise ValueError("Invalid authority or future publication year")
            weight = alpha * claim.authority_tier + (1 - alpha) * math.exp(
                -decay_lambda * (current_year - claim.timestamp_year))
            scored.append((weight, claim))
        # Do not round before ordering. Explicit ties prefer newer, then more
        # authoritative sources, then lexicographic ID for reproducibility.
        scored.sort(key=lambda pair: (-pair[0], -pair[1].timestamp_year,
                                     -pair[1].authority_tier, pair[1].doc_id))
        weight, winner = scored[0]
        superseded = [(c.doc_id, c.value, c.timestamp_year) for _, c in scored[1:]
                      if c.value != winner.value]
        explanation = (
            f"Current-state selection for {winner.entity}.{winner.attribute}: "
            f"{winner.doc_id} ({winner.timestamp_year}, weight={weight:.6f}); "
            f"superseded {len(superseded)} conflicting claim(s). "
            "Historical records are retained; metadata weighting is not independent fact verification."
        )
        return ContradictionResolution(winner.entity, winner.attribute, winner.doc_id,
                                       winner.value, weight, superseded, explanation)


class TorchTPUHBMIndexer:
    """Device-resident BF16 index with eager TPU/CUDA/CPU dispatch.

    On CPU this uses ordinary RAM, not TPU HBM. Synthetic embeddings in the
    verification harness test arithmetic only, not semantic retrieval quality.
    """

    def __init__(self, use_torch_compile: bool = False):
        self.device = get_compute_device()
        self.scorer_fn = colbert_maxsim_bfloat16
        if use_torch_compile and self.device.type == "tpu":
            self.scorer_fn = torch.compile(colbert_maxsim_bfloat16, backend="tpu")
        self.query_tokens: Optional[torch.Tensor] = None
        self.document_tokens: Optional[torch.Tensor] = None

    @torch.no_grad()
    def compute_maxsim(self, query_emb: torch.Tensor, doc_embs: torch.Tensor,
                       query_mask: Optional[torch.Tensor] = None,
                       doc_mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        """One query [Q,D] (or [1,Q,D]) against documents [M,L,D].

        Masks have shapes [Q] and [M,L], with True for real tokens. Returned
        scores stay on the compute device. An all-padding document scores -inf.
        """
        if query_emb.ndim == 3 and query_emb.shape[0] == 1:
            query_emb = query_emb.squeeze(0)
        if query_emb.ndim != 2 or doc_embs.ndim != 3 or query_emb.shape[-1] != doc_embs.shape[-1]:
            raise ValueError("Expected [Q,D] query and [M,L,D] documents")
        if min(query_emb.shape) == 0 or doc_embs.shape[1] == 0:
            raise ValueError("Token and embedding dimensions must be non-empty")
        qm = _mask(query_mask, (query_emb.shape[0],), self.device)
        dm = _mask(doc_mask, tuple(doc_embs.shape[:2]), self.device)
        if not qm.any().item():
            raise ValueError("Query needs at least one valid token")
        self.query_tokens = _normalise(query_emb.to(self.device))
        self.document_tokens = _normalise(doc_embs.to(self.device))
        sim = torch.einsum("id,mjd->mij", self.query_tokens, self.document_tokens)
        return _reduce_maxsim(sim, qm[None, :], dm)

    def rank_documents_maxsim(self, query_emb: torch.Tensor, doc_embs: torch.Tensor,
                              doc_ids: List[str], query_mask: Optional[torch.Tensor] = None,
                              doc_mask: Optional[torch.Tensor] = None) -> List[Tuple[str, float]]:
        if doc_embs.ndim != 3 or len(doc_ids) != doc_embs.shape[0] or len(set(doc_ids)) != len(doc_ids):
            raise ValueError("Provide one unique ID per document")
        scores = self.compute_maxsim(query_emb, doc_embs, query_mask, doc_mask).cpu().tolist()
        # Keep full scores for sorting; round only when displaying results.
        return sorted(zip(doc_ids, scores), key=lambda pair: pair[1], reverse=True)

    def resolve_contradictions(self, claims: List[EpistemicClaim], current_year: int = 2026,
                               alpha: float = 0.55, decay_lambda: float = 0.04) -> ContradictionResolution:
        return EpistemicContradictionResolver().resolve_contradictions(claims, current_year, alpha, decay_lambda)


# Preserve the instructor starter's spelling for existing team imports.
TorchTpuHbmIndexer = TorchTPUHBMIndexer


if __name__ == "__main__":
    torch.manual_seed(42)
    indexer = TorchTpuHbmIndexer(use_torch_compile=False)
    print(f"[Data Specialist] Running bfloat16 ColBERT MaxSim on device: {indexer.device}")

    q_vec = torch.randn(1, 8, 64)
    # Create 3 docs where doc_1 is strongly aligned with q_vec
    d0 = torch.randn(8, 64)
    d1 = q_vec.squeeze(0) + 0.05 * torch.randn(8, 64)
    d2 = torch.randn(8, 64)
    docs_tensor = torch.stack([d0, d1, d2], dim=0)

    ranked = indexer.rank_documents_maxsim(q_vec, docs_tensor, ["DOC_NOISE_0", "DOC_R136_TELEMETRY", "DOC_NOISE_2"])
    print("MaxSim Ranking:", ranked)
    assert ranked[0][0] == "DOC_R136_TELEMETRY"

    # Test SN 1987A vs Sanduleak -69 202 contradiction resolution
    conflicting_claims = [
        EpistemicClaim(
            doc_id="EARTH_CATALOG_1978",
            entity="Sanduleak -69 202",
            attribute="stellar_state",
            value="Intact Luminous Blue Supergiant (LMC)",
            timestamp_year=1978,
            authority_tier=0.60,
        ),
        EpistemicClaim(
            doc_id="NOOSPHERE_LMC_TELEMETRY_2026",
            entity="Sanduleak -69 202",
            attribute="stellar_state",
            value="Collapsed Core-Collapse Supernova Remnant SN 1987A with Equatorial Ring",
            timestamp_year=2026,
            authority_tier=0.98,
        ),
    ]
    res = indexer.resolve_contradictions(conflicting_claims)
    print("[Contradiction Resolver]", res.audit_explanation)
    assert res.winning_doc_id == "NOOSPHERE_LMC_TELEMETRY_2026"
    # Independent FP32 reference: explicit loops, rather than the einsum path.
    q_ref = F.normalize(q_vec.squeeze(0), dim=-1)
    d_ref = F.normalize(docs_tensor, dim=-1)
    reference = torch.tensor([sum(max(float(torch.dot(q, token)) for token in doc)
                                  for q in q_ref) for doc in d_ref])
    actual = indexer.compute_maxsim(q_vec, docs_tensor).cpu()
    error = (actual - reference).abs().max().item()
    assert torch.allclose(actual, reference, atol=0.06, rtol=0.01)
    assert indexer.query_tokens.dtype == torch.bfloat16
    assert indexer.document_tokens.dtype == torch.bfloat16
    print(f"FP32 reference maximum absolute error: {error:.6f}")

    # Padding must not win over negative valid similarities or contribute query scores.
    mq = torch.tensor([[1., 0.], [0., 1.]])
    md = torch.tensor([[[-1., 0.], [0., 0.]], [[1., 0.], [0., 1.]]])
    qm = torch.tensor([True, False])
    dm = torch.tensor([[True, False], [False, False]])
    masked = indexer.compute_maxsim(mq, md, qm, dm).cpu()
    assert masked[0].item() == -1 and masked[1].item() == -math.inf
    pair_scores = colbert_maxsim_bfloat16(mq.unsqueeze(0), md[:1], qm.unsqueeze(0), dm[:1])
    assert pair_scores[0].item() == -1
    assert indexer.rank_documents_maxsim(mq, md[:0], [], qm, dm[:0]) == []
    print("Padding regression: valid negative match=-1.0; all-padding document=-inf")
    print("Claim weights (alpha=0.55, lambda=0.04, current_year=2026):")
    for claim in conflicting_claims:
        rec = math.exp(-0.04 * (2026 - claim.timestamp_year))
        print(f"  {claim.doc_id}: authority={claim.authority_tier:.2f}; "
              f"recency={rec:.6f}; weight={0.55 * claim.authority_tier + 0.45 * rec:.6f}")
    same = EpistemicClaim("AGREEMENT", conflicting_claims[1].entity, "stellar_state",
                          conflicting_claims[1].value, 2025, 0.9)
    assert not indexer.resolve_contradictions([conflicting_claims[1], same]).superseded_claims
    assert indexer.resolve_contradictions(list(reversed(conflicting_claims))).winning_doc_id == res.winning_doc_id
    invalid_claim = EpistemicClaim("BAD", "other entity", "stellar_state", "value", 2026, 0.5)
    for operation in (
        lambda: indexer.compute_maxsim(mq, md, torch.tensor([False, False]), dm),
        lambda: indexer.compute_maxsim(mq, md, qm, torch.ones(2, 3, dtype=torch.bool)),
        lambda: indexer.rank_documents_maxsim(mq, md, ["one"]),
        lambda: indexer.resolve_contradictions([]),
        lambda: indexer.resolve_contradictions([conflicting_claims[0], invalid_claim]),
        lambda: indexer.resolve_contradictions(conflicting_claims, current_year=2020),
    ):
        try:
            operation()
        except ValueError:
            pass
        else:
            raise AssertionError("Expected invalid input to be rejected")
    print("[PASS] FP32 reference, padding, compatibility, empty-index and validation checks.")
    print("[PASS] Contradiction ordering, agreeing claims and entity/date validation checks.")
    print("[PASS] Part 3 TorchTPU bfloat16 MaxSim Indexer & Contradiction Resolver verified!")
