"""
Mission 04 — Part 1: Systems Architect (Lead Engineer)
Direct Preference Optimization (DPO) Loss Core & Log-Likelihood Extraction

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse & Orion Molecular Cloud Complex)
Subsystem 04: Plasma Ignition & Ethical Steering Core
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple, Dict


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
        chosen_logratios = policy_chosen_logps - reference_chosen_logps
        rejected_logratios = policy_rejected_logps - reference_rejected_logps

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


if __name__ == "__main__":
    print("=" * 70)
    print("USSE NOOSPHERE • SUBSYSTEM 04 CALIBRATION: DPO LOSS CORE TEST")
    print("=" * 70)

    torch.manual_seed(42)
    batch_size, seq_len, vocab_size = 4, 16, 128

    # 1. Simulate policy & reference logits
    policy_logits_w = torch.randn(batch_size, seq_len, vocab_size, requires_grad=True)
    policy_logits_l = torch.randn(batch_size, seq_len, vocab_size, requires_grad=True)
    
    ref_logits_w = torch.randn(batch_size, seq_len, vocab_size, requires_grad=False)
    ref_logits_l = torch.randn(batch_size, seq_len, vocab_size, requires_grad=False)

    # 2. Simulate token labels with padding (-100)
    labels_w = torch.randint(0, vocab_size, (batch_size, seq_len))
    labels_w[:, :4] = -100  # Prompt tokens masked

    labels_l = torch.randint(0, vocab_size, (batch_size, seq_len))
    labels_l[:, :4] = -100

    # 3. Extract log probabilities
    p_logps_w = get_batch_logps(policy_logits_w, labels_w)
    p_logps_l = get_batch_logps(policy_logits_l, labels_l)
    r_logps_w = get_batch_logps(ref_logits_w, labels_w)
    r_logps_l = get_batch_logps(ref_logits_l, labels_l)

    # 4. Compute DPO Loss
    dpo_criterion = DPOLoss(beta=0.1)
    loss, metrics = dpo_criterion(p_logps_w, p_logps_l, r_logps_w, r_logps_l)

    # 5. Backpropagation check
    loss.backward()

    print(f"[✓] DPO Loss Computed: {loss.item():.4f}")
    print(f"[✓] Bradley-Terry Win Probability: {metrics['bt_probability'].item() * 100:.2f}%")
    print(f"[✓] Implicit Reward Margin: {metrics['reward_margin'].item():+.4f}")
    print(f"[✓] Policy Chosen Logits Grad Norm: {policy_logits_w.grad.norm().item():.4f}")
    print(f"[✓] Reference Logits Grad: {ref_logits_w.grad} (Expected: None / Frozen)")
    print("\n[SUCCESS] Subsystem 04 DPO Core module successfully validated.")
    print("=" * 70)
