"""
Mission 03 — Part 1: Systems Architect (Lead Engineer)
Multi-Head Attention from Scratch with Causal Masking & Variance Preservation

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-03-M45 (Pleiades Open Cluster, Seven Sisters)
Subsystem 03: Distributed Multi-Head Attention Mesh & KV-Cache Transceiver

Assigned officer: Abdul Jalil Memon — Systems Architect, Squadron Goodfellow
AI assistance: Codex extended the instructor starter and drafted validation
at the squad's request. Officer review and sign-off remain pending.

Run this file to execute variance, reference, masking, gradient and dtype checks.
Requires PyTorch >= 2.4. Tests run on CPU; no GPU performance is claimed.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple


class MultiHeadSelfAttention(nn.Module):
    def __init__(self, d_model: int = 512, num_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        if d_model <= 0 or num_heads <= 0 or d_model % num_heads:
            raise ValueError("Positive d_model must be divisible by positive num_heads")
        if not 0 <= dropout < 1:
            raise ValueError("dropout must be in [0, 1)")

        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.scale = 1.0 / math.sqrt(self.head_dim)

        # Linear projections for Query, Key, Value and Output
        self.w_q = nn.Linear(d_model, d_model, bias=False)
        self.w_k = nn.Linear(d_model, d_model, bias=False)
        self.w_v = nn.Linear(d_model, d_model, bias=False)
        self.w_o = nn.Linear(d_model, d_model, bias=False)

        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: torch.Tensor,
        causal: bool = True,
        attention_mask: Optional[torch.Tensor] = None
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass for Multi-Head Self-Attention.

        Args:
            x: Input tensor of shape (batch_size, seq_len, d_model)
            causal: If True, applies lower-triangular causal attention mask
            attention_mask: Boolean (batch_size, seq_len), True for valid tokens.
                Invalid keys cannot be attended to; invalid query outputs are zero.
                Rows with no allowed keys have zero weights and output.

        Returns:
            Tuple of (output, attention_weights):
                output: shape (batch_size, seq_len, d_model)
                attention_weights: shape (batch_size, num_heads, seq_len, seq_len)
        """
        if x.ndim != 3 or x.shape[-1] != self.d_model or x.shape[1] == 0:
            raise ValueError("Expected nonempty (batch, sequence, d_model) input")
        batch_size, seq_len, _ = x.shape
        if attention_mask is not None:
            if attention_mask.shape != (batch_size, seq_len) or attention_mask.dtype != torch.bool:
                raise ValueError("attention_mask must be boolean (batch, sequence)")
            if attention_mask.device != x.device:
                raise ValueError("attention_mask and input must share a device")

        # 1. Project inputs to Q, K, V
        q = self.w_q(x)
        k = self.w_k(x)
        v = self.w_v(x)

        # 2. Reshape into (batch_size, num_heads, seq_len, head_dim)
        q = q.view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = k.view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        v = v.view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)

        # Accumulate low-precision scores/softmax in float32. Cast probabilities
        # back before multiplying by V; this also avoids the starter's FP16 error.
        score_dtype = torch.float32 if q.dtype in (torch.float16, torch.bfloat16) else q.dtype
        scores = torch.matmul(q.to(score_dtype), k.to(score_dtype).transpose(-2, -1)) * self.scale
        allowed = torch.ones((1, 1, seq_len, seq_len), dtype=torch.bool, device=x.device)
        if causal:
            allowed = allowed.tril()
        if attention_mask is not None:
            allowed = allowed & attention_mask[:, None, None, :]
            allowed = allowed & attention_mask[:, None, :, None]

        # softmax([-inf, ...]) is NaN. Replace entirely masked rows temporarily
        # with zeros, then explicitly zero all forbidden probabilities.
        has_keys = allowed.any(dim=-1, keepdim=True)
        scores = scores.masked_fill(~allowed, float('-inf'))
        scores = torch.where(has_keys, scores, torch.zeros_like(scores))
        attn_weights = F.softmax(scores, dim=-1).masked_fill(~allowed, 0).to(v.dtype)
        attn_weights = self.dropout(attn_weights)

        # 6. Weight values and project output
        context = torch.matmul(attn_weights, v) # (batch_size, num_heads, seq_len, head_dim)
        context = context.transpose(1, 2).contiguous().view(batch_size, seq_len, self.d_model)
        output = self.w_o(context)

        return output, attn_weights


def verify_variance_preservation():
    """
    Cadet Verification: Validate that scaling by 1/sqrt(d_k) preserves unit variance
    across dot products before softmax when inputs have zero mean and unit variance.
    """
    print("=== Subsystem 03: Attention Variance Preservation Verification ===")
    torch.manual_seed(42)
    d_k = 64
    seq_len = 128
    batch_size = 32

    # Standard normal inputs (zero mean, unit variance)
    q = torch.randn(batch_size, seq_len, d_k)
    k = torch.randn(batch_size, seq_len, d_k)

    unscaled_dot = torch.matmul(q, k.transpose(-2, -1))
    scaled_dot = unscaled_dot / math.sqrt(d_k)

    print(f"Head Dim (d_k): {d_k}")
    print(f"Unscaled Dot Product — Mean: {unscaled_dot.mean().item():.4f}, Variance: {unscaled_dot.var().item():.4f} (Expected ~{d_k})")
    print(f"Scaled Dot Product   — Mean: {scaled_dot.mean().item():.4f}, Variance: {scaled_dot.var().item():.4f} (Expected ~1.000)")
    assert abs(scaled_dot.var().item() - 1.0) < 0.1, "Variance preservation check failed!"
    print("[PASS] Variance preservation holds within tolerance! Subsystem 03 Attention Matrix stabilized.")



def verify_attention_correctness():
    """Independent reference and regressions for causal/padding/FP16 failures.

    PyTorch SDPA is used only as a test oracle, never in the implementation.
    Returned attention weights are post-dropout; row sums equal 1 only with
    dropout disabled and at least one allowed key.
    """
    torch.manual_seed(7)
    layer = MultiHeadSelfAttention(32, 4, dropout=0).eval()
    x = torch.randn(2, 6, 32)
    with torch.no_grad():
        for causal in (False, True):
            actual, weights = layer(x, causal=causal)
            q, k, v = [proj(x).view(2, 6, 4, 8).transpose(1, 2)
                       for proj in (layer.w_q, layer.w_k, layer.w_v)]
            expected_heads = F.scaled_dot_product_attention(q, k, v, is_causal=causal)
            expected = layer.w_o(expected_heads.transpose(1, 2).reshape(2, 6, 32))
            torch.testing.assert_close(actual, expected, atol=1e-6, rtol=1e-5)
            torch.testing.assert_close(weights.sum(-1), torch.ones(2, 4, 6))
        original, weights = layer(x)
        changed = x.clone()
        changed[:, 3:] += 100
        torch.testing.assert_close(original[:, :3], layer(changed)[0][:, :3])
        assert torch.count_nonzero(weights.triu(1)) == 0
        print("PASS: independent SDPA reference, row sums and causal isolation")

        # First sample is left padded; second has no valid tokens at all.
        mask = torch.tensor([[False, False, True, True, True, True], [False]*6])
        output, weights = layer(x, attention_mask=mask)
        assert torch.isfinite(output).all() and torch.isfinite(weights).all()
        assert torch.count_nonzero(output[~mask]) == 0
        assert torch.count_nonzero(weights[0, :, :, :2]) == 0
        unpadded = layer(x[0:1, 2:])[0]
        torch.testing.assert_close(output[0:1, 2:], unpadded, atol=1e-6, rtol=1e-5)
        single, single_weights = layer(x[:, :1])
        assert single.shape == (2, 1, 32)
        torch.testing.assert_close(single_weights, torch.ones_like(single_weights))
        print("PASS: left padding, fully masked rows and single-token attention")

        for dtype in (torch.float16, torch.bfloat16):
            low = MultiHeadSelfAttention(32, 4, dropout=0).to(dtype).eval()
            low.load_state_dict(layer.state_dict())
            output, weights = low(x.to(dtype), attention_mask=mask)
            assert output.dtype == dtype and weights.dtype == dtype
            assert torch.isfinite(output).all() and torch.isfinite(weights).all()
            reference = layer(x.to(dtype).float(), attention_mask=mask)[0]
            torch.testing.assert_close(output.float(), reference, atol=0.01, rtol=0.05)
        print("PASS: FP16 and BF16 forward passes and float32 agreement")

    # All-masked rows must not introduce NaN gradients into training.
    training_input = x.clone().requires_grad_()
    output, _ = layer(training_input, attention_mask=mask)
    output.square().sum().backward()
    assert torch.isfinite(training_input.grad).all()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in layer.parameters())
    assert torch.count_nonzero(training_input.grad[~mask]) == 0
    print("PASS: finite backward gradients with padding and fully masked rows")

    for bad_mask in (torch.ones(2, 6), torch.ones(2, 5, dtype=torch.bool)):
        try:
            layer(x, attention_mask=bad_mask)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid mask accepted")
    print("PASS: mask shape and dtype validation")


if __name__ == "__main__":
    verify_variance_preservation()
    verify_attention_correctness()
    print("All Part 1 checks passed. Officer review/sign-off pending.")
