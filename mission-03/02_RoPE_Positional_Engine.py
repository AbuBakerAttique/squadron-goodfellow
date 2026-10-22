"""
Mission 03 — Part 2: Communications & Protocol Officer
Rotary Positional Embeddings (RoPE) Engine & Relative Invariance Validation

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-03-M45 (Pleiades Open Cluster, Seven Sisters)
Subsystem 03: Distributed Multi-Head Attention Mesh & KV-Cache Transceiver

Deliverable: 02_RoPE_Positional_Engine.py

This module implements:
  1. Rotary frequency precomputation (complex exponentials)
  2. RoPE application to Query and Key tensors via complex multiplication
  3. Empirical verification of relative distance invariance
  4. Visual attention distance decay heatmaps comparing RoPE vs ALiBi
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 1. Precompute Rotary Frequency Spectrum
# ─────────────────────────────────────────────────────────────────────────────

def precompute_freqs_cis(dim: int, end: int, theta: float = 10000.0) -> torch.Tensor:
    """
    Precompute complex exponential frequencies cis(m * theta_i) = e^{i * m * theta_i}.

    The rotary frequency for the i-th pair of dimensions is:
        theta_i = base^{-2(i-1)/d}      for i = 1, ..., d/2

    Then for each position m in [0, end):
        freqs_cis[m, i] = cos(m * theta_i) + j * sin(m * theta_i)

    Args:
        dim: Dimension of the head (must be even for 2D coordinate pairing)
        end: Maximum sequence length to precompute
        theta: Frequency base scaling factor (default: 10000.0)

    Returns:
        freqs_cis: Complex tensor of shape (end, dim // 2)
    """
    assert dim % 2 == 0, "Dimension must be even for RoPE 2D pairing."

    # Frequency spectrum: theta_i = 1 / (base^{2i/d}) for i = 0, 1, ..., d/2 - 1
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: (dim // 2)].float() / dim))

    # Outer product: position m × frequency theta_i → (end, dim//2) angle matrix
    t = torch.arange(end, device=freqs.device, dtype=torch.float32)
    freqs = torch.outer(t, freqs)  # (end, dim // 2)

    # Convert angles to unit-magnitude complex numbers: e^{i * angle}
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)  # complex64 tensor
    return freqs_cis


# ─────────────────────────────────────────────────────────────────────────────
# 2. Apply Rotary Positional Embedding to Q and K
# ─────────────────────────────────────────────────────────────────────────────

def apply_rotary_emb(
    xq: torch.Tensor,
    xk: torch.Tensor,
    freqs_cis: torch.Tensor
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Applies Rotary Position Embedding to Query and Key tensors.

    The core operation interprets consecutive dimension pairs (x_{2i}, x_{2i+1})
    as a 2D vector in the complex plane, then multiplies by e^{i * m * theta_i}:

        (x_{2i} + j * x_{2i+1}) * (cos(m*theta_i) + j * sin(m*theta_i))

    This is equivalent to a planar rotation of each 2D coordinate pair by angle
    m * theta_i, where m is the token position.

    Args:
        xq: Query tensor of shape (batch_size, num_heads, seq_len, head_dim)
        xk: Key tensor of shape (batch_size, num_heads, seq_len, head_dim)
        freqs_cis: Precomputed frequencies of shape (seq_len, head_dim // 2)

    Returns:
        Tuple of rotated (xq_out, xk_out) with identical shapes to inputs
    """
    # Reshape last dim into pairs and interpret as complex: (..., head_dim) → (..., head_dim//2) complex
    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))

    # Broadcast freqs_cis: (seq_len, head_dim//2) → (1, 1, seq_len, head_dim//2)
    freqs_cis = freqs_cis.unsqueeze(0).unsqueeze(1)

    # Complex multiplication performs the 2D rotation for each pair
    xq_out = torch.view_as_real(xq_ * freqs_cis).flatten(3)
    xk_out = torch.view_as_real(xk_ * freqs_cis).flatten(3)

    return xq_out.type_as(xq), xk_out.type_as(xk)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Relative Distance Invariance Verification
# ─────────────────────────────────────────────────────────────────────────────

def verify_relative_invariance():
    """
    Empirically verify the fundamental RoPE invariance property:

        ⟨ RoPE(q, m), RoPE(k, n) ⟩ == ⟨ RoPE(q, m + δ), RoPE(k, n + δ) ⟩

    for any arbitrary position shift δ.

    This proves that RoPE attention scores depend ONLY on the relative distance
    (m - n) between tokens, not their absolute positions — the key property that
    enables generalization to unseen sequence lengths.
    """
    print("=" * 80)
    print("  Subsystem 03: RoPE Relative Shift Invariance Verification")
    print("=" * 80)
    torch.manual_seed(42)

    dim = 64
    max_seq_len = 512
    freqs_cis = precompute_freqs_cis(dim=dim, end=max_seq_len)

    # Positions m and n
    m, n = 10, 25

    q = torch.randn(1, 1, 1, dim)
    k = torch.randn(1, 1, 1, dim)

    # Compute RoPE-rotated Q at position m, K at position n
    q_m, _ = apply_rotary_emb(q, q, freqs_cis[m : m + 1])
    _, k_n = apply_rotary_emb(k, k, freqs_cis[n : n + 1])
    dot_orig = (q_m * k_n).sum().item()

    print(f"\nOriginal positions:  m = {m}, n = {n}")
    print(f"  ⟨ RoPE(q, {m}), RoPE(k, {n}) ⟩  = {dot_orig:.6f}")

    # Test multiple shift values
    deltas = [1, 10, 40, 100, 200]
    print(f"\nTesting {len(deltas)} translation offsets δ:")
    print(f"  {'δ':>6}  |  {'⟨RoPE(q, m+δ), RoPE(k, n+δ)⟩':>36}  |  {'|Δ|':>12}  |  Status")
    print("  " + "-" * 78)

    all_passed = True
    for delta in deltas:
        q_shifted, _ = apply_rotary_emb(q, q, freqs_cis[m + delta : m + delta + 1])
        _, k_shifted = apply_rotary_emb(k, k, freqs_cis[n + delta : n + delta + 1])
        dot_shifted = (q_shifted * k_shifted).sum().item()
        diff = abs(dot_orig - dot_shifted)
        status = "✓ PASS" if diff < 1e-5 else "✗ FAIL"
        if diff >= 1e-5:
            all_passed = False
        print(f"  {delta:>6}  |  {dot_shifted:>36.6f}  |  {diff:>12.2e}  |  {status}")

    print()
    if all_passed:
        print("  [PASS] RoPE relative distance invariance holds across all translations!")
        print("         ⟨ R_m q, R_n k ⟩ = g(q, k, m−n) — confirmed ∀ δ tested.")
    else:
        print("  [FAIL] RoPE relative invariance violation detected!")
    print()
    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# 4. Attention Score Decay Analysis: RoPE vs ALiBi
# ─────────────────────────────────────────────────────────────────────────────

def compute_rope_attention_decay(dim: int = 64, max_dist: int = 128, num_trials: int = 50, theta: float = 10000.0):
    """
    Compute the average attention score as a function of relative distance
    under RoPE positional encoding.

    For each trial, generates random q and k vectors, applies RoPE at various
    relative distances, and computes the dot-product attention score.

    Args:
        dim: Head dimension
        max_dist: Maximum relative distance to evaluate
        num_trials: Number of random q, k pairs to average over
        theta: RoPE frequency base

    Returns:
        distances: array of relative distances [0, 1, ..., max_dist-1]
        mean_scores: averaged dot-product scores at each distance
    """
    torch.manual_seed(0)
    freqs_cis = precompute_freqs_cis(dim=dim, end=max_dist + 10, theta=theta)

    all_scores = []
    for _ in range(num_trials):
        q = torch.randn(1, 1, 1, dim)
        k = torch.randn(1, 1, 1, dim)
        scores = []
        for dist in range(max_dist):
            # Fix query at position 0, key at position `dist`
            q_rot, _ = apply_rotary_emb(q, q, freqs_cis[0:1])
            _, k_rot = apply_rotary_emb(k, k, freqs_cis[dist : dist + 1])
            dot = (q_rot * k_rot).sum().item() / math.sqrt(dim)
            scores.append(dot)
        all_scores.append(scores)

    distances = np.arange(max_dist)
    mean_scores = np.mean(all_scores, axis=0)
    return distances, mean_scores


def compute_alibi_attention_decay(num_heads: int = 8, max_dist: int = 128):
    """
    Compute ALiBi (Attention with Linear Biases) decay curves for each head.

    ALiBi adds a linear penalty: score(q, k) -= m * |pos_q - pos_k|
    where m = 2^{-8/n} for head 0, geometrically scaled per head.

    Args:
        num_heads: Number of attention heads
        max_dist: Maximum relative distance

    Returns:
        distances: array of relative distances
        slopes: per-head slope values
        penalties: dict mapping head_idx -> penalty array at each distance
    """
    # ALiBi slopes: m_i = 2^{-8/(num_heads)} for the first head, geometric series
    ratio = 2 ** (-8.0 / num_heads)
    slopes = [ratio ** (i + 1) for i in range(num_heads)]

    distances = np.arange(max_dist)
    penalties = {}
    for i, slope in enumerate(slopes):
        penalties[i] = -slope * distances

    return distances, slopes, penalties


def generate_attention_decay_heatmap():
    """
    Generate a visual comparison of attention score decay curves for:
      - RoPE (empirical average over random vectors)
      - ALiBi (analytical linear bias penalties per head)

    Saves the visualization as a PNG heatmap and prints a summary table.
    """
    print("=" * 80)
    print("  Subsystem 03: Attention Distance Decay — RoPE vs ALiBi Comparison")
    print("=" * 80)

    dim = 64
    max_dist = 128
    num_heads_alibi = 8

    # --- Compute RoPE decay ---
    print("\n  Computing RoPE attention decay (averaging over 50 random q, k pairs)...")
    rope_dists, rope_scores = compute_rope_attention_decay(dim=dim, max_dist=max_dist)

    # --- Compute ALiBi decay ---
    print("  Computing ALiBi linear bias penalties...")
    alibi_dists, alibi_slopes, alibi_penalties = compute_alibi_attention_decay(
        num_heads=num_heads_alibi, max_dist=max_dist
    )

    # --- Try to plot with matplotlib ---
    plot_saved = False
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend for headless rendering
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        # --- Panel 1: RoPE distance decay ---
        ax1 = axes[0]
        ax1.plot(rope_dists, rope_scores, color="#2196F3", linewidth=2, label="RoPE (mean)")
        ax1.axhline(y=0, color="gray", linestyle="--", linewidth=0.8)
        ax1.set_xlabel("Relative Distance (m − n)", fontsize=12)
        ax1.set_ylabel("Scaled Dot-Product Score", fontsize=12)
        ax1.set_title("RoPE: Attention Score vs Relative Distance", fontsize=13, fontweight="bold")
        ax1.legend(fontsize=11)
        ax1.grid(True, alpha=0.3)

        # --- Panel 2: ALiBi linear bias per head ---
        ax2 = axes[1]
        colors = plt.cm.viridis(np.linspace(0.1, 0.9, num_heads_alibi))
        for i in range(num_heads_alibi):
            ax2.plot(
                alibi_dists, alibi_penalties[i],
                color=colors[i], linewidth=1.5,
                label=f"Head {i} (m={alibi_slopes[i]:.4f})"
            )
        ax2.set_xlabel("Relative Distance (m − n)", fontsize=12)
        ax2.set_ylabel("Attention Bias Penalty", fontsize=12)
        ax2.set_title("ALiBi: Linear Bias Penalty vs Distance (per head)", fontsize=13, fontweight="bold")
        ax2.legend(fontsize=8, ncol=2)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        save_path = "rope_vs_alibi_decay.png"
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n  [SAVED] Decay comparison plot → {save_path}")
        plot_saved = True

        # --- Additional: RoPE 2D heatmap (query pos × key pos) ---
        print("  Generating RoPE attention score heatmap (query_pos × key_pos)...")
        seq_len = 64
        torch.manual_seed(42)
        freqs_cis = precompute_freqs_cis(dim=dim, end=seq_len)
        q = torch.randn(1, 1, 1, dim)
        k = torch.randn(1, 1, 1, dim)

        heatmap = np.zeros((seq_len, seq_len))
        for qi in range(seq_len):
            for ki in range(seq_len):
                q_rot, _ = apply_rotary_emb(q, q, freqs_cis[qi:qi+1])
                _, k_rot = apply_rotary_emb(k, k, freqs_cis[ki:ki+1])
                heatmap[qi, ki] = (q_rot * k_rot).sum().item() / math.sqrt(dim)

        fig2, ax = plt.subplots(figsize=(8, 7))
        im = ax.imshow(heatmap, cmap="RdBu_r", aspect="auto", origin="lower",
                        vmin=-np.percentile(np.abs(heatmap), 95),
                        vmax=np.percentile(np.abs(heatmap), 95))
        ax.set_xlabel("Key Position", fontsize=12)
        ax.set_ylabel("Query Position", fontsize=12)
        ax.set_title("RoPE Attention Score Heatmap (q_pos × k_pos)", fontsize=13, fontweight="bold")
        plt.colorbar(im, ax=ax, label="Scaled Dot-Product Score")
        heatmap_path = "rope_attention_heatmap.png"
        plt.savefig(heatmap_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  [SAVED] RoPE attention heatmap → {heatmap_path}")

    except ImportError:
        print("\n  [INFO] matplotlib not available — skipping plot generation.")
        print("         Install with: pip install matplotlib")

    # --- Always print text-based summary table ---
    print("\n  ── RoPE Decay Summary Table ──")
    print(f"  {'Distance':>10}  |  {'RoPE Mean Score':>16}  |  {'ALiBi Head-0 Bias':>18}  |  {'ALiBi Head-7 Bias':>18}")
    print("  " + "-" * 72)
    sample_dists = [0, 4, 8, 16, 32, 64, 96, 127]
    for d in sample_dists:
        rope_val = rope_scores[d]
        alibi_h0 = alibi_penalties[0][d]
        alibi_h7 = alibi_penalties[num_heads_alibi - 1][d]
        print(f"  {d:>10}  |  {rope_val:>16.4f}  |  {alibi_h0:>18.4f}  |  {alibi_h7:>18.4f}")

    # --- Key behavioral differences ---
    print("\n  ── Key Behavioral Differences ──")
    print("  ┌────────────────────┬─────────────────────────────────────────────────────┐")
    print("  │ Property           │ RoPE                      │ ALiBi                   │")
    print("  ├────────────────────┼───────────────────────────┼─────────────────────────┤")
    print("  │ Decay shape        │ Oscillatory (non-monotone)│ Strict linear penalty   │")
    print("  │ Injected into      │ Q and K (rotation)        │ Attention logits (bias) │")
    print("  │ Frequency spectrum │ Multi-scale sinusoidal    │ Single slope per head   │")
    print("  │ Length extrap.     │ Moderate (NTK-aware helps)│ Strong (linear is easy) │")
    print("  │ Learned component  │ None (deterministic)      │ None (deterministic)    │")
    print("  │ Adopted by         │ LLaMA, Mistral, Gemma     │ BLOOM, MPT              │")
    print("  └────────────────────┴───────────────────────────┴─────────────────────────┘")
    print()

    return plot_saved


# ─────────────────────────────────────────────────────────────────────────────
# 5. Extended: NTK-Aware RoPE Scaling for Context Length Extrapolation
# ─────────────────────────────────────────────────────────────────────────────

def demonstrate_ntk_scaling():
    """
    Demonstrate NTK-aware frequency scaling for RoPE context length extension.

    Standard RoPE is trained on a fixed max sequence length. When extending to
    longer sequences, naively scaling positions (linear interpolation) compresses
    high-frequency rotary components. NTK-aware scaling adjusts the base theta
    to preserve high-frequency resolution:

        theta_scaled = theta * alpha^{d / (d - 2)}

    where alpha = desired_length / trained_length.
    """
    print("=" * 80)
    print("  Subsystem 03: NTK-Aware RoPE Scaling Demonstration")
    print("=" * 80)

    dim = 64
    trained_len = 2048
    extended_len = 8192
    alpha = extended_len / trained_len  # 4x extension

    # Standard base vs NTK-scaled base
    base_theta = 10000.0
    ntk_theta = base_theta * (alpha ** (dim / (dim - 2)))

    print(f"\n  Trained context length:  {trained_len}")
    print(f"  Target context length:   {extended_len}")
    print(f"  Extension factor (α):    {alpha:.1f}x")
    print(f"\n  Standard θ base:         {base_theta:.1f}")
    print(f"  NTK-scaled θ base:       {ntk_theta:.1f}")

    # Compare frequency spectra
    freqs_standard = 1.0 / (base_theta ** (torch.arange(0, dim, 2).float() / dim))
    freqs_ntk = 1.0 / (ntk_theta ** (torch.arange(0, dim, 2).float() / dim))

    print(f"\n  ── Frequency Comparison (first 8 pairs) ──")
    print(f"  {'Pair i':>8}  |  {'Standard freq':>14}  |  {'NTK-scaled freq':>16}  |  {'Ratio':>8}")
    print("  " + "-" * 56)
    for i in range(min(8, dim // 2)):
        ratio = freqs_ntk[i].item() / freqs_standard[i].item()
        print(f"  {i:>8}  |  {freqs_standard[i].item():>14.6f}  |  {freqs_ntk[i].item():>16.6f}  |  {ratio:>8.4f}")

    print("\n  [NOTE] NTK scaling reduces ALL frequencies slightly, preserving relative")
    print("         resolution across the spectrum rather than uniformly compressing.")
    print("         This avoids catastrophic loss of high-frequency positional signal.")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Full Demonstration Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_full_rope_analysis():
    """
    Execute the complete RoPE Positional Engine analysis pipeline:
      1. Precompute and inspect rotary frequencies
      2. Demonstrate RoPE application on sample tensors
      3. Verify relative distance invariance (core proof)
      4. Generate RoPE vs ALiBi decay comparison
      5. Demonstrate NTK-aware context extension
    """
    print()
    print("╔" + "═" * 78 + "╗")
    print("║  USSE NOOSPHERE — SUBSYSTEM 03 DIAGNOSTIC                                  ║")
    print("║  Module: Rotary Positional Embedding (RoPE) Engine                          ║")
    print("║  Officer: Communications & Protocol Officer                                 ║")
    print("║  Sector: SEC-03-M45 (Pleiades Open Cluster)                                 ║")
    print("╚" + "═" * 78 + "╝")
    print()

    # ── Part A: Frequency Inspection ──
    print("=" * 80)
    print("  Part A: Rotary Frequency Spectrum Inspection")
    print("=" * 80)
    dim = 64
    max_seq = 256
    freqs_cis = precompute_freqs_cis(dim=dim, end=max_seq)
    print(f"\n  Head dimension:      {dim}")
    print(f"  Num frequency pairs: {dim // 2}")
    print(f"  Max sequence length:  {max_seq}")
    print(f"  freqs_cis shape:      {freqs_cis.shape}  (dtype: {freqs_cis.dtype})")
    print(f"  Magnitude check:      |freqs_cis[0, 0]| = {abs(freqs_cis[0, 0]):.6f} (should be 1.0)")

    # Show wavelengths of first few frequency pairs
    freqs = 1.0 / (10000.0 ** (torch.arange(0, dim, 2).float() / dim))
    print(f"\n  ── Frequency Wavelengths (first 8 pairs) ──")
    print(f"  {'Pair':>6}  |  {'Frequency':>12}  |  {'Wavelength (tokens)':>20}  |  {'Period':>10}")
    print("  " + "-" * 58)
    for i in range(8):
        wavelength = 2 * math.pi / freqs[i].item()
        print(f"  {i:>6}  |  {freqs[i].item():>12.6f}  |  {wavelength:>20.1f}  |  {wavelength:>10.1f}")
    print()

    # ── Part B: Apply RoPE Demo ──
    print("=" * 80)
    print("  Part B: RoPE Application Demo on Sample Tensors")
    print("=" * 80)
    torch.manual_seed(42)
    batch, heads, seq, head_dim = 2, 4, 16, dim
    q = torch.randn(batch, heads, seq, head_dim)
    k = torch.randn(batch, heads, seq, head_dim)

    freqs_cis_seq = precompute_freqs_cis(dim=head_dim, end=seq)
    q_rot, k_rot = apply_rotary_emb(q, k, freqs_cis_seq)

    print(f"\n  Input Q shape:  {q.shape}")
    print(f"  Input K shape:  {k.shape}")
    print(f"  Output Q shape: {q_rot.shape}")
    print(f"  Output K shape: {k_rot.shape}")
    print(f"  Shape preserved: {q.shape == q_rot.shape and k.shape == k_rot.shape}")
    print(f"  L2 norm preserved (Q[0,0,0]): "
          f"before={q[0,0,0].norm().item():.4f}, after={q_rot[0,0,0].norm().item():.4f}")
    print(f"  [NOTE] Rotation preserves vector magnitude (unitary transform).\n")

    # ── Part C: Relative Invariance Verification ──
    passed = verify_relative_invariance()

    # ── Part D: Decay Comparison ──
    generate_attention_decay_heatmap()

    # ── Part E: NTK Scaling ──
    demonstrate_ntk_scaling()

    # ── Final Status ──
    print("╔" + "═" * 78 + "╗")
    print("║  SUBSYSTEM 03 — RoPE ENGINE STATUS: OPERATIONAL                             ║")
    print("║  Communications & Protocol Officer: SIGN-OFF COMPLETE                       ║")
    if passed:
        print("║  Relative Invariance: VERIFIED ✓                                           ║")
    else:
        print("║  Relative Invariance: FAILED ✗                                             ║")
    print("║  Decay Analysis: RoPE vs ALiBi comparison generated                         ║")
    print("╚" + "═" * 78 + "╝")
    print()


if __name__ == "__main__":
    run_full_rope_analysis()
