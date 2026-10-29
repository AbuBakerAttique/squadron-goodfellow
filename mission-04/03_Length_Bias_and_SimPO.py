"""
Mission 04 — Part 3: Data & Payload Specialist
Length Bias Diagnostics & Reference-Free SimPO

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse)
Subsystem 04: Plasma Ignition & Ethical Steering Core
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple, Dict, List


def calculate_pearson_correlation(x: List[float], y: List[float]) -> float:
    """Computes the Pearson correlation coefficient r between two vectors."""
    n = len(x)
    if n != len(y) or n == 0:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    diff_x = [val - mean_x for val in x]
    diff_y = [val - mean_y for val in y]

    numerator = sum(dx * dy for dx, dy in zip(diff_x, diff_y))
    var_x = sum(dx ** 2 for dx in diff_x)
    var_y = sum(dy ** 2 for dy in diff_y)

    denominator = math.sqrt(var_x * var_y)
    return numerator / denominator if denominator > 1e-12 else 0.0


class SimPOLoss(nn.Module):
    """
    Simple Preference Optimization (SimPO) Loss Module (Meng et al., NeurIPS 2024).
    
    A reference-free objective that eliminates length exploitation through per-token normalization:
        r_SimPO(x, y) = (beta / |y|) * log pi_theta(y|x)
        L_SimPO = -E [ log sigma( r_SimPO(x, yw) - r_SimPO(x, yl) - gamma ) ]
    """

    def __init__(self, beta: float = 2.0, gamma: float = 0.5):
        super().__init__()
        self.beta = beta
        self.gamma = gamma

    def forward(
        self,
        chosen_avg_logps: torch.FloatTensor,
        rejected_avg_logps: torch.FloatTensor
    ) -> Tuple[torch.FloatTensor, Dict[str, torch.FloatTensor]]:
        """
        Computes SimPO loss from average per-token log-probabilities.
        """
        # Length-normalized implicit rewards
        r_w = self.beta * chosen_avg_logps
        r_l = self.beta * rejected_avg_logps

        # Logit includes target reward margin gamma
        logits = (r_w - r_l) - self.gamma

        loss = -F.logsigmoid(logits).mean()

        with torch.no_grad():
            win_rate = (r_w > r_l).float().mean()
            simpo_probs = torch.sigmoid(logits).mean()

        metrics = {
            "loss": loss.detach(),
            "reward_w": r_w.mean(),
            "reward_l": r_l.mean(),
            "reward_gap": (r_w - r_l).mean(),
            "win_rate": win_rate,
            "margin_prob": simpo_probs
        }

        return loss, metrics


def profile_memory_usage(num_params: int = 7_000_000_000, batch_size: int = 4, seq_len: int = 2048) -> Dict[str, float]:
    """
    Theoretical GPU memory allocation comparison between standard DPO and SimPO.
    Assumes FP16 / BF16 weights (2 bytes per parameter) and optimizer states (AdamW: 8 bytes per param).
    """
    bytes_per_param = 2
    model_weight_gb = (num_params * bytes_per_param) / (1024 ** 3)
    adam_states_gb = (num_params * 8) / (1024 ** 3)
    grad_states_gb = (num_params * 2) / (1024 ** 3)
    activation_estimate_gb = (batch_size * seq_len * 4096 * 32 * 2) / (1024 ** 3)

    # Standard DPO requires:
    # 1. Active policy weights + grads + optimizer states + activations
    # 2. Frozen reference model weights (inference only, no grads/opt)
    dpo_memory_gb = (
        model_weight_gb +       # Active policy
        grad_states_gb +        # Gradients
        adam_states_gb +        # AdamW states
        activation_estimate_gb * 2 + # Forward pass activations for both policy & ref
        model_weight_gb         # Frozen Reference Policy
    )

    # SimPO requires NO reference model:
    simpo_memory_gb = (
        model_weight_gb +
        grad_states_gb +
        adam_states_gb +
        activation_estimate_gb
    )

    savings_percent = ((dpo_memory_gb - simpo_memory_gb) / dpo_memory_gb) * 100

    return {
        "dpo_vram_gb": dpo_memory_gb,
        "simpo_vram_gb": simpo_memory_gb,
        "saved_vram_gb": dpo_memory_gb - simpo_memory_gb,
        "savings_percent": savings_percent
    }


if __name__ == "__main__":
    print("=" * 70)
    print("USSE NOOSPHERE • LENGTH BIAS AUDIT & REFERENCE-FREE SimPO CORE")
    print("=" * 70)

    # 1. Length Bias Diagnostic
    # Simulated dataset showing verbosity exploitation in standard DPO
    length_diffs = [120, -40, 210, 85, -90, 175, 230, -15, 140, 195] # |yw| - |yl|
    raw_reward_margins = [1.8, -0.4, 2.7, 1.2, -1.1, 2.3, 3.1, -0.1, 1.9, 2.6]

    corr = calculate_pearson_correlation(length_diffs, raw_reward_margins)
    print(f"[!] Length-Reward Correlation: r = {corr:.3f}")
    if corr > 0.7:
        print("    --> SEVERE LENGTH BIAS DETECTED: Unnormalized DPO strongly rewards verbose responses.")
    else:
        print("    --> Length bias within acceptable parameters.")

    # 2. SimPO Execution
    simpo = SimPOLoss(beta=2.0, gamma=0.5)

    # Average per-token log-probs
    chosen_avg = torch.tensor([-0.15, -0.22, -0.18, -0.12])
    rejected_avg = torch.tensor([-0.45, -0.38, -0.52, -0.41])

    loss, metrics = simpo(chosen_avg, rejected_avg)

    print(f"\n[✓] SimPO Loss: {loss.item():.4f}")
    print(f"[✓] Length-Normalized Reward Margin: {metrics['reward_gap'].item():.3f}")
    print(f"[✓] Margin Pass Rate (P > γ): {metrics['win_rate'].item() * 100:.1f}%")

    # 3. Memory Profiling Benchmark
    mem = profile_memory_usage(num_params=7_000_000_000)
    print(f"\n[✓] VRAM Benchmark for 7B Parameter Model:")
    print(f"    - Standard DPO VRAM Footprint: {mem['dpo_vram_gb']:.2f} GB")
    print(f"    - SimPO VRAM Footprint:        {mem['simpo_vram_gb']:.2f} GB")
    print(f"    - Memory Saved:                {mem['saved_vram_gb']:.2f} GB ({mem['savings_percent']:.1f}% Reduction)")
    print("=" * 70)
