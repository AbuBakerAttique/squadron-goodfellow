"""
Mission 04 — Part 1: Systems Architect (Lead Engineer)
Direct Preference Optimization (DPO) Loss Core & Log-Likelihood Extraction

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse & Orion Molecular Cloud Complex)
Subsystem 04: Plasma Ignition & Ethical Steering Core
"""

import copy
import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple, Dict, Optional


def get_batch_logps(
    logits: torch.FloatTensor,
    labels: torch.LongTensor,
    label_pad_token_id: int = -100,
    average_log_prob: bool = False
) -> torch.FloatTensor:
    """
    Computes per-sequence log-probabilities of token labels under model logits.
    
    Args:
        logits: Tensor of shape (batch_size, seq_len, vocab_size)
        labels: Tensor of shape (batch_size, seq_len) with prompt/pad tokens set to label_pad_token_id
        label_pad_token_id: Token ID to ignore in loss computation
        average_log_prob: If True, returns mean log-prob per non-pad token (used in SimPO)
        
    Returns:
        Tensor of shape (batch_size,) containing sequence log-probabilities
    """
    # Shift so that tokens < n predict n
    shift_logits = logits[:, :-1, :].contiguous()
    shift_labels = labels[:, 1:].contiguous()

    # Create loss mask for non-padding tokens
    loss_mask = (shift_labels != label_pad_token_id)

    # Replace padding tokens with 0 for gather operation
    clean_labels = shift_labels.clone()
    clean_labels[~loss_mask] = 0

    # Calculate log-softmax over vocabulary
    log_probs = F.log_softmax(shift_logits, dim=-1)

    # Gather log-probabilities corresponding to true token labels
    per_token_logps = torch.gather(
        log_probs,
        dim=2,
        index=clean_labels.unsqueeze(2)
    ).squeeze(2)

    # Mask out padding tokens
    per_token_logps = per_token_logps * loss_mask.float()

    if average_log_prob:
        seq_lengths = loss_mask.sum(dim=-1).clamp(min=1)
        return per_token_logps.sum(dim=-1) / seq_lengths
    else:
        return per_token_logps.sum(dim=-1)


def dpo_log_ratios(
    policy_chosen_logps: torch.FloatTensor,
    policy_rejected_logps: torch.FloatTensor,
    reference_chosen_logps: torch.FloatTensor,
    reference_rejected_logps: torch.FloatTensor
) -> Tuple[torch.FloatTensor, torch.FloatTensor]:
    """
    DPO log-ratio deltas (Deliverable 2):
        Delta_w = log pi_theta(y_w|x) - log pi_ref(y_w|x)
        Delta_l = log pi_theta(y_l|x) - log pi_ref(y_l|x)
    Gradients flow only through the policy terms; reference log-probs must come from a frozen model.
    """
    return (
        policy_chosen_logps - reference_chosen_logps,
        policy_rejected_logps - reference_rejected_logps,
    )


def compute_sequence_logps(
    model: nn.Module,
    input_ids: torch.LongTensor,
    attention_mask: torch.LongTensor,
    labels: torch.LongTensor,
    average_log_prob: bool = False
) -> torch.FloatTensor:
    """
    Runs a causal LM (any module mapping (input_ids, attention_mask) -> logits of shape
    (B, T, V)) and returns per-sequence log-probs via get_batch_logps.
    Gradient behaviour is decided by the caller (wrap reference calls in torch.no_grad()).
    """
    logits = model(input_ids, attention_mask)
    return get_batch_logps(logits, labels, average_log_prob=average_log_prob)


class DPOLoss(nn.Module):
    """
    Direct Preference Optimization (DPO) Loss Module (Rafailov et al., NeurIPS 2023).
    
    Optimizes policy directly from pairwise preferences without training an explicit reward model:
        L_DPO = -E_{(x, yw, yl)} [ log sigma( beta * ( log(pi(yw)/pi_ref(yw)) - log(pi(yl)/pi_ref(yl)) ) ) ]
    """

    def __init__(self, beta: float = 0.1, label_pad_token_id: int = -100):
        super().__init__()
        self.beta = beta
        self.label_pad_token_id = label_pad_token_id

    def forward(
        self,
        policy_chosen_logps: torch.FloatTensor,
        policy_rejected_logps: torch.FloatTensor,
        reference_chosen_logps: torch.FloatTensor,
        reference_rejected_logps: torch.FloatTensor
    ) -> Tuple[torch.FloatTensor, Dict[str, torch.FloatTensor]]:
        """
        Calculates DPO loss, implicit rewards, and preference margins.
        """
        # Calculate log-ratio differences: log(pi_theta(y|x) / pi_ref(y|x))
        chosen_logratios, rejected_logratios = dpo_log_ratios(
            policy_chosen_logps, policy_rejected_logps,
            reference_chosen_logps, reference_rejected_logps
        )

        # Implicit rewards derived analytically via Rafailov reparameterization:
        # r(x, y) = beta * log(pi_theta(y|x) / pi_ref(y|x))
        chosen_rewards = self.beta * chosen_logratios.detach()
        rejected_rewards = self.beta * rejected_logratios.detach()
        reward_margins = chosen_rewards - rejected_rewards

        # Compute Bradley-Terry logit: beta * (chosen_logratios - rejected_logratios)
        logits = self.beta * (chosen_logratios - rejected_logratios)

        # Numerically stable DPO loss: -log(sigmoid(logits))
        loss = -F.logsigmoid(logits).mean()

        # Metrics for monitoring training
        with torch.no_grad():
            chosen_win_rate = (chosen_rewards > rejected_rewards).float().mean()
            mean_margin = reward_margins.mean()
            bt_probs = torch.sigmoid(logits).mean()

        metrics = {
            "loss": loss.detach(),
            "chosen_win_rate": chosen_win_rate,
            "reward_margin": mean_margin,
            "bt_probability": bt_probs,
            "chosen_rewards": chosen_rewards.mean(),
            "rejected_rewards": rejected_rewards.mean()
        }

        return loss, metrics


# ---------------------------------------------------------------------------
# Verification harness: tiny real causal LMs (policy + frozen reference)
# ---------------------------------------------------------------------------

class TinyCausalLM(nn.Module):
    """Small decoder-only transformer (pure PyTorch, no downloads) used for the gradient test."""

    def __init__(self, vocab_size: int = 64, d_model: int = 32, n_heads: int = 4,
                 n_layers: int = 2, max_len: int = 32):
        super().__init__()
        self.tok = nn.Embedding(vocab_size, d_model)
        self.pos = nn.Embedding(max_len, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model, n_heads, dim_feedforward=4 * d_model, dropout=0.0,
            batch_first=True, norm_first=True
        )
        self.blocks = nn.TransformerEncoder(layer, n_layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size, bias=False)

    def forward(self, input_ids: torch.LongTensor, attention_mask: Optional[torch.Tensor] = None):
        T = input_ids.size(1)
        x = self.tok(input_ids) + self.pos(torch.arange(T, device=input_ids.device))
        causal = torch.triu(torch.ones(T, T, dtype=torch.bool, device=input_ids.device), 1)
        x = self.blocks(x, mask=causal)  # causal => right-padding never leaks into earlier tokens
        return self.head(self.norm(x))


def make_preference_batch(batch_size=8, seq_len=20, prompt_len=6, vocab_size=64, seed=0):
    """Synthetic (prompt, chosen, rejected) batch with right padding. Prompt and pad labels = -100."""
    g = torch.Generator().manual_seed(seed)
    out = {}
    for side in ("chosen", "rejected"):
        ids = torch.randint(1, vocab_size, (batch_size, seq_len), generator=g)
        lens = torch.randint(prompt_len + 3, seq_len + 1, (batch_size,), generator=g)
        mask = (torch.arange(seq_len)[None, :] < lens[:, None]).long()
        ids = ids * mask
        labels = ids.clone()
        labels[:, :prompt_len] = -100
        labels[mask == 0] = -100
        out[side] = (ids, mask, labels)
    return out


def naive_sequence_logp(logits, labels, pad=-100):
    """Slow reference implementation with explicit Python loops (used only to cross-check)."""
    out = []
    for b in range(logits.size(0)):
        total = 0.0
        for t in range(logits.size(1) - 1):
            tgt = labels[b, t + 1].item()
            if tgt == pad:
                continue
            total += torch.log_softmax(logits[b, t].double(), -1)[tgt].item()
        out.append(total)
    return torch.tensor(out, dtype=torch.float64)


def run_verification() -> None:
    torch.manual_seed(42)
    W = 70
    print("=" * W)
    print("USSE NOOSPHERE • SUBSYSTEM 04 CALIBRATION: DPO LOSS CORE TEST")
    print("=" * W)

    # ---- Test 1: get_batch_logps vs naive loop, padding invariance --------------------
    print("\n[1] get_batch_logps (torch.gather + padding mask)")
    B, T, V = 4, 16, 128
    logits = torch.randn(B, T, V)
    labels = torch.randint(0, V, (B, T))
    labels[:, :4] = -100          # prompt masked
    labels[1, 10:] = -100         # right padding on one row
    labels[3, :] = -100           # fully masked row -> must be 0, not NaN
    fast = get_batch_logps(logits, labels)
    slow = naive_sequence_logp(logits, labels)
    assert torch.allclose(fast.double(), slow, atol=1e-4), (fast, slow)
    print(f"    matches naive loop (max |diff| = {(fast.double() - slow).abs().max().item():.2e})")
    assert fast[3].item() == 0.0
    print("    fully-masked row -> 0.0 (no NaN)")
    # logits at masked positions must not influence the result
    logits2 = logits.clone()
    logits2[1, 9:, :] = torch.randn(T - 9, V) * 100   # only affects predictions of masked targets
    assert torch.allclose(get_batch_logps(logits2, labels), fast)
    print("    logits feeding masked targets do not change the result")
    avg = get_batch_logps(logits, labels, average_log_prob=True)
    n_tok = (labels[:, 1:] != -100).sum(-1).clamp(min=1)
    assert torch.allclose(avg, fast / n_tok)
    print("    average_log_prob=True equals sum / n_response_tokens")

    # ---- Test 2: numerical stability of F.logsigmoid -----------------------------------
    print("\n[2] Numerical stability: -logsigmoid vs naive -log(sigmoid)")
    z = torch.tensor([-1e4, -100.0, 0.0, 100.0, 1e4], requires_grad=True)
    naive = -torch.log(torch.sigmoid(z))
    stable = -F.logsigmoid(z)
    print(f"    z       : {z.detach().tolist()}")
    print(f"    naive   : {naive.detach().tolist()}")
    print(f"    stable  : {stable.detach().tolist()}")
    assert torch.isinf(naive[0]) and torch.isfinite(stable).all()
    stable.sum().backward()
    assert torch.isfinite(z.grad).all()
    print("    stable loss and gradients finite at |z| = 1e4 (naive version gives inf)")

    # ---- Test 3: DPOLoss values, analytic gradient -------------------------------------
    print("\n[3] DPOLoss analytic checks")
    beta = 0.1
    pc, pr, rc, rr = (torch.randn(6, requires_grad=(i < 2)) * 5 for i in range(4))
    pc = pc.detach().requires_grad_(); pr = pr.detach().requires_grad_()
    loss, m = DPOLoss(beta)(pc, pr, rc, rr)
    dw, dl = dpo_log_ratios(pc, pr, rc, rr)
    expect = -torch.log(torch.sigmoid(beta * (dw - dl))).mean()
    assert torch.allclose(loss, expect, atol=1e-6)
    loss.backward()
    sig = torch.sigmoid(-beta * (dw - dl)).detach()
    assert torch.allclose(pc.grad, -beta * sig / 6, atol=1e-6)
    assert torch.allclose(pr.grad, beta * sig / 6, atol=1e-6)
    print("    loss == -mean(log sigma(beta(Dw - Dl))); d loss/d logp_w = -beta*sigma(-z)/B (analytic)")
    eq = DPOLoss(beta)(torch.zeros(3), torch.zeros(3), torch.zeros(3), torch.zeros(3))[0]
    assert abs(eq.item() - math.log(2)) < 1e-6
    print(f"    policy == reference -> loss = ln 2 = {eq.item():.4f}")

    # ---- Test 4: real policy + frozen reference model ----------------------------------
    print("\n[4] Gradient test with real models: trainable policy vs frozen reference")
    V = 64
    reference = TinyCausalLM(vocab_size=V)
    policy = copy.deepcopy(reference)            # standard DPO init: pi_theta = pi_ref
    for p in reference.parameters():
        p.requires_grad_(False)                  # freeze reference
    reference.eval()
    ref_snapshot = {k: v.clone() for k, v in reference.state_dict().items()}
    pol_snapshot = {k: v.clone() for k, v in policy.state_dict().items()}

    batch = make_preference_batch(vocab_size=V)
    criterion = DPOLoss(beta=0.1)
    optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-3)   # policy params ONLY

    def step():
        optimizer.zero_grad(set_to_none=True)
        p_c = compute_sequence_logps(policy, *batch["chosen"])
        p_r = compute_sequence_logps(policy, *batch["rejected"])
        with torch.no_grad():
            r_c = compute_sequence_logps(reference, *batch["chosen"])
            r_r = compute_sequence_logps(reference, *batch["rejected"])
        loss, metrics = criterion(p_c, p_r, r_c, r_r)
        loss.backward()
        optimizer.step()
        return loss.item(), metrics

    l0, m0 = step()
    assert abs(l0 - math.log(2)) < 1e-5 and abs(m0["reward_margin"].item()) < 1e-5
    print(f"    step 0: loss = {l0:.4f} (= ln 2), reward margin = {m0['reward_margin'].item():+.4f} (policy == reference)")

    pol_grads = [p.grad for p in policy.parameters()]
    assert all(g is not None for g in pol_grads) and any(g.abs().sum() > 0 for g in pol_grads)
    assert all(p.grad is None for p in reference.parameters())
    assert not any(p.requires_grad for p in reference.parameters())
    print(f"    policy: {len(pol_grads)}/{len(pol_grads)} parameter tensors received gradients")
    print(f"    reference: 0/{sum(1 for _ in reference.parameters())} parameter tensors have .grad (all None, requires_grad=False)")

    losses = [l0]
    for _ in range(29):
        l, mk = step()
        losses.append(l)
    assert all(torch.equal(ref_snapshot[k], v) for k, v in reference.state_dict().items())
    changed = sum(not torch.equal(pol_snapshot[k], v) for k, v in policy.state_dict().items())
    assert changed > 0
    print(f"    after 30 AdamW steps: reference weights bit-identical to snapshot (frozen)")
    print(f"    after 30 AdamW steps: {changed}/{len(pol_snapshot)} policy tensors changed")
    assert losses[-1] < losses[0]
    print(f"    loss {losses[0]:.4f} -> {losses[-1]:.4f}; chosen win-rate {mk['chosen_win_rate'].item():.2f}, "
          f"reward margin {mk['reward_margin'].item():+.4f}")

    # Counter-check: an optimizer given ONLY frozen reference params cannot move them either
    print("\n[5] Sanity: reference stays frozen even if it is (wrongly) put in the optimizer")
    ref_check = copy.deepcopy(reference)
    opt2 = torch.optim.SGD(ref_check.parameters(), lr=1.0)
    opt2.step()   # no .grad -> no-op
    assert all(torch.equal(ref_snapshot[k], v) for k, v in ref_check.state_dict().items())
    print("    optimizer.step() on grad-less reference parameters is a no-op")

    print("\n[SUCCESS] Subsystem 04 DPO Core module successfully validated.")
    print("=" * W)


if __name__ == "__main__":
    run_verification()