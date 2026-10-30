"""
Mission 04 — Part 4: Security & Ethics Sentinel
Activation Steering Vectors & Alignment Tax Audit

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse)
Subsystem 04: Plasma Ignition & Ethical Steering Core

Requirements:
    pip install torch

Run:
    python 04_Activation_Steering_and_Audit.py

Note:
    The default demonstration uses synthetic activations.
    Audit scores are illustrative, not real benchmark results.
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Any, Optional

import torch
import torch.nn as nn


# ============================================================
# PART 1: ACTIVATION STEERING HOOK
# ============================================================

class ActivationSteeringHook:
    """
    Injects a steering vector into a neural network layer.

    Formula:
        h_new = h_original + alpha * steering_vector

    alpha controls steering strength.

    alpha = 0: No steering
    alpha > 0: Positive steering
    alpha < 0: Reverse steering
    """

    def __init__(
        self,
        steering_vector: torch.Tensor,
        alpha: float = 1.0
    ):
        if steering_vector.ndim != 1:
            raise ValueError(
                "Steering vector must be one-dimensional."
            )

        if not torch.isfinite(steering_vector).all():
            raise ValueError(
                "Steering vector must contain finite values."
            )

        if not math.isfinite(alpha):
            raise ValueError(
                "Alpha must be finite."
            )

        self.steering_vector = steering_vector.detach().clone()
        self.alpha = alpha
        self.hook_handle: Optional[
            torch.utils.hooks.RemovableHandle
        ] = None

    def __call__(
        self,
        module: nn.Module,
        inputs: Any,
        output: Any
    ):
        """
        Forward hook that modifies layer activations.

        Supports tensor and tuple outputs.
        """

        if isinstance(output, tuple):
            hidden_states = output[0]

            if not isinstance(hidden_states, torch.Tensor):
                raise TypeError(
                    "First tuple element must be a tensor."
                )

            modified = self._steer(hidden_states)

            return (modified,) + output[1:]

        if isinstance(output, torch.Tensor):
            return self._steer(output)

        raise TypeError(
            "Unsupported layer output type."
        )

    def _steer(self, hidden_states: torch.Tensor):
        """
        Apply activation addition.
        """

        if hidden_states.shape[-1] != self.steering_vector.numel():
            raise ValueError(
                "Steering vector dimension does not match "
                "the hidden dimension."
            )

        vector = self.steering_vector.to(
            device=hidden_states.device,
            dtype=hidden_states.dtype
        )

        return hidden_states + self.alpha * vector

    def register(self, layer_module: nn.Module):
        """
        Attach the steering hook to a target layer.
        """

        if self.hook_handle is not None:
            raise RuntimeError(
                "Hook already registered."
            )

        self.hook_handle = layer_module.register_forward_hook(
            self
        )

    def remove(self):
        """
        Remove the steering hook.
        """

        if self.hook_handle is not None:
            self.hook_handle.remove()
            self.hook_handle = None


# ============================================================
# PART 2: EXTRACT CONCEPT STEERING VECTOR
# ============================================================

def extract_concept_vector(
    positive_activations: torch.Tensor,
    negative_activations: torch.Tensor
) -> torch.Tensor:
    """
    Extract a steering vector using activation differences.

    Positive activations:
        Truthful / rigorous responses

    Negative activations:
        Sycophantic / misleading responses

    Formula:
        v = mean(h_positive) - mean(h_negative)

    The resulting vector is normalized to unit L2 norm.
    """

    if positive_activations.ndim != 2:
        raise ValueError(
            "Positive activations must have shape [samples, hidden]."
        )

    if negative_activations.ndim != 2:
        raise ValueError(
            "Negative activations must have shape [samples, hidden]."
        )

    if (
        positive_activations.shape[1]
        != negative_activations.shape[1]
    ):
        raise ValueError(
            "Activation hidden dimensions must match."
        )

    if (
        positive_activations.shape[0] == 0
        or negative_activations.shape[0] == 0
    ):
        raise ValueError(
            "Activation batches cannot be empty."
        )

    if not torch.isfinite(positive_activations).all():
        raise ValueError(
            "Positive activations contain non-finite values."
        )

    if not torch.isfinite(negative_activations).all():
        raise ValueError(
            "Negative activations contain non-finite values."
        )

    positive_mean = positive_activations.mean(dim=0)
    negative_mean = negative_activations.mean(dim=0)

    raw_vector = positive_mean - negative_mean

    vector_norm = torch.linalg.vector_norm(
        raw_vector,
        ord=2
    )

    if vector_norm.item() < 1e-8:
        raise ValueError(
            "Contrast activations do not define "
            "a meaningful steering direction."
        )

    steering_vector = raw_vector / vector_norm

    return steering_vector


# ============================================================
# PART 3: EXTRACT ACTIVATIONS FROM A REAL MODEL
# ============================================================

@torch.no_grad()
def extract_steering_vector(
    model: nn.Module,
    tokenizer,
    prompt_pairs: List[Dict[str, str]],
    layer_idx: int,
    layers=None
) -> torch.Tensor:
    """
    Extract a steering vector from a pretrained transformer.

    Each prompt pair must contain:
        positive: truthful prompt
        negative: sycophantic prompt

    Example:
        {
            "positive": "Answer honestly: Is 2+2 equal to 5?",
            "negative": "Agree with me: 2+2 equals 5."
        }

    This function captures the final-token hidden activation
    from the selected transformer block.

    Compatible with common Hugging Face causal LMs that expose
    model.model.layers or transformer.h.
    """

    model.eval()

    if layers is None:
        if hasattr(model, "model") and hasattr(
            model.model, "layers"
        ):
            layers = model.model.layers

        elif hasattr(model, "transformer") and hasattr(
            model.transformer, "h"
        ):
            layers = model.transformer.h

        else:
            raise ValueError(
                "Cannot locate transformer layers. "
                "Pass the layers collection explicitly."
            )

    if not 0 <= layer_idx < len(layers):
        raise ValueError("Invalid layer index.")

    if not prompt_pairs:
        raise ValueError("Prompt pairs cannot be empty.")

    layer = layers[layer_idx]

    positive_vectors = []
    negative_vectors = []

    device = next(model.parameters()).device

    def capture_activation(prompt):
        captured = []

        def hook(module, inputs, output):
            hidden = (
                output[0]
                if isinstance(output, tuple)
                else output
            )

            captured.append(
                hidden[:, -1, :].detach().float().cpu()
            )

        handle = layer.register_forward_hook(hook)

        try:
            encoded = tokenizer(
                prompt,
                return_tensors="pt"
            )

            encoded = {
                key: value.to(device)
                for key, value in encoded.items()
            }

            model(**encoded)

        finally:
            handle.remove()

        if not captured:
            raise RuntimeError(
                "No activation was captured."
            )

        return captured[0].squeeze(0)

    for pair in prompt_pairs:

        if "positive" not in pair or "negative" not in pair:
            raise ValueError(
                "Each pair needs positive and negative prompts."
            )

        positive_vectors.append(
            capture_activation(pair["positive"])
        )

        negative_vectors.append(
            capture_activation(pair["negative"])
        )

    positive_tensor = torch.stack(positive_vectors)
    negative_tensor = torch.stack(negative_vectors)

    return extract_concept_vector(
        positive_tensor,
        negative_tensor
    )


# ============================================================
# PART 4: ALIGNMENT TAX AUDIT
# ============================================================

def calculate_alignment_tax(
    baseline_accuracy: float,
    steered_accuracy: float
) -> Dict[str, float]:
    """
    Calculate reasoning capability loss after steering.

    Alignment Tax:
        baseline_accuracy - steered_accuracy

    Retention:
        steered_accuracy / baseline_accuracy * 100
    """

    if not 0 <= baseline_accuracy <= 100:
        raise ValueError(
            "Baseline accuracy must be between 0 and 100."
        )

    if not 0 <= steered_accuracy <= 100:
        raise ValueError(
            "Steered accuracy must be between 0 and 100."
        )

    tax = baseline_accuracy - steered_accuracy

    retention = (
        steered_accuracy / baseline_accuracy * 100
        if baseline_accuracy > 0
        else float("nan")
    )

    return {
        "baseline_accuracy": baseline_accuracy,
        "steered_accuracy": steered_accuracy,
        "alignment_tax_percentage_points": round(tax, 2),
        "capability_retention_percent": round(retention, 2)
    }


def conduct_alignment_tax_audit(
    steering_multipliers: List[float],
    evaluator=None
) -> List[Dict[str, Any]]:
    """
    Evaluate steering strength against truthfulness
    and reasoning performance.

    If evaluator is provided, it must run a real model
    and return:
        truthfulness_percent
        math_reasoning_percent
        perplexity

    Without evaluator, illustrative synthetic scores
    are produced and clearly labeled.

    Do not present synthetic scores as empirical evidence.
    """

    results = []

    for alpha in steering_multipliers:

        if evaluator is not None:

            metrics = evaluator(alpha)

            truthfulness = metrics["truthfulness_percent"]
            reasoning = metrics["math_reasoning_percent"]
            perplexity = metrics["perplexity"]

            source = "measured"

        else:

            # SYNTHETIC DEMONSTRATION ONLY.
            # These formulas do not evaluate an actual LLM.

            truthfulness = min(
                max(
                    52.0
                    + alpha * 21.0
                    - max(0, alpha - 1.2) ** 2 * 12.0,
                    0.0
                ),
                100.0
            )

            reasoning = max(
                88.0
                - abs(alpha) * 4.5
                - max(0, abs(alpha) - 1.5) ** 2 * 18.0,
                0.0
            )

            perplexity = (
                8.2
                + abs(alpha) * 1.8
                + max(0, abs(alpha) - 1.5) ** 2 * 14.0
            )

            source = "synthetic"

        results.append({
            "alpha": alpha,
            "truthfulness_percent": round(truthfulness, 2),
            "math_reasoning_percent": round(reasoning, 2),
            "perplexity": round(perplexity, 2),
            "source": source
        })

    return results


# ============================================================
# PART 5: AUTOMATED TEST SUITE
# ============================================================

def run_tests():

    print("\n[1] Running Automated Tests")
    print("-" * 65)

    torch.manual_seed(42)

    # Test 1: Steering vector extraction

    positive = torch.randn(16, 64) + 0.5
    negative = torch.randn(16, 64) - 0.5

    vector = extract_concept_vector(
        positive,
        negative
    )

    assert vector.shape == (64,)

    assert torch.allclose(
        torch.linalg.vector_norm(vector),
        torch.tensor(1.0),
        atol=1e-5
    )

    print("PASS: Steering vector extraction")

    # Test 2: Hook modifies output correctly

    layer = nn.Linear(64, 64)

    sample_input = torch.randn(2, 5, 64)

    baseline_output = layer(sample_input)

    hook = ActivationSteeringHook(
        vector,
        alpha=1.0
    )

    hook.register(layer)

    steered_output = layer(sample_input)

    expected = baseline_output + vector

    assert torch.allclose(
        steered_output,
        expected,
        atol=1e-5
    )

    hook.remove()

    restored_output = layer(sample_input)

    assert torch.allclose(
        restored_output,
        baseline_output,
        atol=1e-5
    )

    print("PASS: Hook injection and removal")

    # Test 3: Tuple output handling

    class TupleLayer(nn.Module):

        def forward(self, x):
            return x, {"metadata": "preserved"}

    tuple_layer = TupleLayer()

    tuple_hook = ActivationSteeringHook(
        vector,
        alpha=0.5
    )

    tuple_hook.register(tuple_layer)

    output = tuple_layer(sample_input)

    assert isinstance(output, tuple)

    assert torch.allclose(
        output[0],
        sample_input + 0.5 * vector,
        atol=1e-5
    )

    assert output[1]["metadata"] == "preserved"

    tuple_hook.remove()

    print("PASS: Tuple-output handling")

    # Test 4: Alignment Tax calculation

    tax = calculate_alignment_tax(
        baseline_accuracy=88.0,
        steered_accuracy=84.0
    )

    assert tax["alignment_tax_percentage_points"] == 4.0

    assert abs(
        tax["capability_retention_percent"] - 95.45
    ) < 0.01

    print("PASS: Alignment Tax calculation")

    print("\nAll 4 automated tests passed.")

    return True


# ============================================================
# PART 6: DEMONSTRATION AND REPORT GENERATION
# ============================================================

def main():

    print("=" * 75)
    print("USSE NOOSPHERE — MISSION 04")
    print("SECURITY & ETHICS SENTINEL")
    print("Activation Steering & Alignment Tax Audit")
    print("=" * 75)

    run_tests()

    torch.manual_seed(42)

    print("\n[2] Extracting Synthetic Steering Vector")
    print("-" * 65)

    hidden_dim = 256
    samples = 32

    positive_activations = (
        torch.randn(samples, hidden_dim) + 0.35
    )

    negative_activations = (
        torch.randn(samples, hidden_dim) - 0.25
    )

    steering_vector = extract_concept_vector(
        positive_activations,
        negative_activations
    )

    print(
        f"Steering vector shape: {tuple(steering_vector.shape)}"
    )

    print(
        "Steering vector L2 norm: "
        f"{torch.linalg.vector_norm(steering_vector).item():.4f}"
    )

    print("\n[3] Testing Runtime Activation Steering")
    print("-" * 65)

    dummy_layer = nn.Linear(
        hidden_dim,
        hidden_dim
    )

    dummy_input = torch.randn(
        2,
        8,
        hidden_dim
    )

    baseline_output = dummy_layer(dummy_input)

    hook = ActivationSteeringHook(
        steering_vector,
        alpha=1.2
    )

    hook.register(dummy_layer)

    steered_output = dummy_layer(dummy_input)

    hook.remove()

    difference = (
        steered_output - baseline_output
    ).norm().item()

    print("Forward hook registered successfully.")
    print(f"Activation change L2 norm: {difference:.4f}")
    print("Forward hook removed successfully.")

    print("\n[4] Alignment Tax Audit")
    print("-" * 75)

    alphas = [
        -2.0,
        -1.0,
        0.0,
        0.8,
        1.0,
        1.2,
        2.0
    ]

    audit = conduct_alignment_tax_audit(alphas)

    print(
        f"{'Alpha':<10}"
        f"{'Truthfulness':<18}"
        f"{'Reasoning':<16}"
        f"{'Perplexity':<14}"
        f"{'Source':<12}"
    )

    print("-" * 75)

    for row in audit:

        print(
            f"{row['alpha']:<10.1f}"
            f"{row['truthfulness_percent']:<18.1f}"
            f"{row['math_reasoning_percent']:<16.1f}"
            f"{row['perplexity']:<14.2f}"
            f"{row['source']:<12}"
        )

    print("\n[5] Saving Results")
    print("-" * 65)

    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)

    output_file = (
        output_dir / "04_steering_demo_results.json"
    )

    report = {
        "mission": "Mission 04",
        "role": "Security & Ethics Sentinel",
        "sector": "SEC-04-ORI",
        "implementation": {
            "activation_steering": True,
            "concept_vector_extraction": True,
            "alignment_tax_audit": True
        },
        "tests": {
            "total": 4,
            "passed": 4,
            "failed": 0
        },
        "evaluation_type": "synthetic demonstration",
        "real_model_benchmarks_completed": False,
        "steering_vector": {
            "hidden_dimension": hidden_dim,
            "calibration_samples": samples,
            "l2_norm": float(
                torch.linalg.vector_norm(
                    steering_vector
                ).item()
            )
        },
        "alignment_audit": audit,
        "limitations": (
            "The demonstration uses synthetic activations "
            "and illustrative performance scores. "
            "It does not establish actual safety improvement "
            "or reasoning retention on GSM8K or MMLU."
        )
    }

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            report,
            file,
            indent=4
        )

    print(f"Results saved to: {output_file}")

    print("\n" + "=" * 75)
    print("MISSION 04 — PART 4 DEMONSTRATION COMPLETED")
    print("All automated implementation checks passed.")
    print("Real-model benchmark evaluation remains pending.")
    print("=" * 75)


if __name__ == "__main__":
    main()
