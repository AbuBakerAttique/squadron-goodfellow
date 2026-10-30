"""
Mission 04 — Part 2: Communications & Protocol Officer
Implicit Reward Extraction & Bradley-Terry Evaluation

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse)
Subsystem 04: Plasma Ignition & Ethical Steering Core
"""


import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import torch
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def evaluate_implicit_rewards(
    policy_chosen_logps: torch.FloatTensor,
    policy_rejected_logps: torch.FloatTensor,
    ref_chosen_logps: torch.FloatTensor,
    ref_rejected_logps: torch.FloatTensor,
    beta: float = 0.1
) -> Dict[str, Any]:
    """
    Extracts implicit scalar rewards and evaluates Bradley-Terry win probabilities.

    Under DPO the optimal policy satisfies the closed-form reward identity:
        r(x, y) = beta * (log pi_theta(y|x) - log pi_ref(y|x)) + const(x)

    The prompt-dependent constant cancels in the pairwise comparison:
        P(y_w > y_l | x) = sigma( r(x, y_w) - r(x, y_l) )
                          = sigma( beta * (Delta_w - Delta_l) )

    Pairwise accuracy uses strict inequality (r_w > r_l). Ties (r_w == r_l)
    count as incorrect, which is conservative: an aligned model should
    separate chosen from rejected, not land on zero margin.

    Args:
        policy_chosen_logps:   log pi_theta(y_w | x), shape (N,)
        policy_rejected_logps: log pi_theta(y_l | x), shape (N,)
        ref_chosen_logps:      log pi_ref(y_w | x),   shape (N,)
        ref_rejected_logps:    log pi_ref(y_l | x),   shape (N,)
        beta: DPO temperature controlling reward scaling

    Returns:
        Dictionary with per-pair rewards, margins, win probabilities, and
        aggregate statistics.
    """
    if beta <= 0 or not math.isfinite(beta):
        raise ValueError("beta must be a positive finite scalar")
    for name, tensor in [("policy_chosen_logps", policy_chosen_logps),
                         ("policy_rejected_logps", policy_rejected_logps),
                         ("ref_chosen_logps", ref_chosen_logps),
                         ("ref_rejected_logps", ref_rejected_logps)]:
        if tensor.ndim != 1 or tensor.numel() == 0:
            raise ValueError(f"{name} must be a non-empty 1-D tensor")
        if not torch.isfinite(tensor).all():
            raise ValueError(f"{name} contains non-finite values")
    n = policy_chosen_logps.shape[0]
    if not all(t.shape == (n,) for t in [policy_rejected_logps,
                                          ref_chosen_logps,
                                          ref_rejected_logps]):
        raise ValueError("All input tensors must share the same length")

    # Implicit rewards: r(x, y) = beta * log(pi_theta(y|x) / pi_ref(y|x))
    reward_w = beta * (policy_chosen_logps - ref_chosen_logps)
    reward_l = beta * (policy_rejected_logps - ref_rejected_logps)

    # Pairwise margin: Delta r = r(x, y_w) - r(x, y_l)
    delta_r = reward_w - reward_l

    # Bradley-Terry pairwise preference probability:
    # P(y_w > y_l | x) = sigma(delta_r)
    p_win = torch.sigmoid(delta_r)

    # Classification accuracy: fraction where model correctly ranks chosen > rejected
    # Ties (delta_r == 0) count as incorrect (strict >).
    pairwise_acc = (reward_w > reward_l).float().mean().item()

    # Margin separation statistics
    mean_margin = delta_r.mean().item()
    std_margin = delta_r.std().item() if n > 1 else 0.0

    return {
        "reward_w": reward_w.tolist(),
        "reward_l": reward_l.tolist(),
        "delta_r": delta_r.tolist(),
        "p_win": p_win.tolist(),
        "pairwise_accuracy": pairwise_acc,
        "mean_margin": mean_margin,
        "std_margin": std_margin,
        "mean_p_win": p_win.mean().item(),
        "mean_reward_w": reward_w.mean().item(),
        "mean_reward_l": reward_l.mean().item(),
        "num_pairs": n,
        "beta": beta,
    }


def randomised_calibration_data(
    reward_w: List[float],
    reward_l: List[float],
    seed: int = 42
) -> Tuple[List[float], List[int]]:
    """
    Construct a calibration dataset with mixed labels by randomly assigning
    A/B presentation order to each pair.

    For each pair, with probability 0.5 (fixed seed):
      - "A = chosen":  p = sigma(r_w - r_l),  label = 1
      - "A = rejected": p = sigma(r_l - r_w), label = 0

    This gives a genuine mix of 0/1 labels so that binned empirical accuracy
    is informative (unlike the degenerate case where all labels are 1 and
    every bin's empirical accuracy is trivially 1.0).

    Args:
        reward_w: Implicit rewards for chosen responses.
        reward_l: Implicit rewards for rejected responses.
        seed: Random seed for reproducible A/B assignment.

    Returns:
        (predicted_probs, labels) suitable for compute_calibration_curve.
    """
    rng = random.Random(seed)
    probs = []
    labels = []
    for rw, rl in zip(reward_w, reward_l):
        if rng.random() < 0.5:
            # A = chosen
            probs.append(1.0 / (1.0 + math.exp(-(rw - rl))))
            labels.append(1)
        else:
            # A = rejected
            probs.append(1.0 / (1.0 + math.exp(-(rl - rw))))
            labels.append(0)
    return probs, labels


def compute_calibration_curve(
    predicted_probs: List[float],
    ground_truth_labels: List[int],
    num_bins: int = 5
) -> List[Dict[str, Any]]:
    """
    Computes a reliability calibration curve by binning predicted probabilities.

    Bins the predicted Bradley-Terry probabilities into equal-width intervals
    and computes the empirical accuracy in each bin. Perfect calibration means
    avg_predicted_prob == empirical_accuracy within every bin.

    Args:
        predicted_probs:    List of predicted probabilities in [0, 1].
        ground_truth_labels: List of binary labels (1 = A preferred, 0 = B preferred).
                            Must contain a genuine mix of 0s and 1s for the
                            calibration to be meaningful; see randomised_calibration_data.
        num_bins:           Number of equal-width bins across [0, 1).

    Returns:
        List of dicts, one per bin, containing bin boundaries, count,
        average prediction, empirical accuracy, and per-bin calibration error.
        Each dict also contains the overall Expected Calibration Error (ECE).
    """
    if len(predicted_probs) != len(ground_truth_labels):
        raise ValueError("predicted_probs and ground_truth_labels must have equal length")
    if num_bins < 1:
        raise ValueError("num_bins must be >= 1")

    bins: List[List[Tuple[float, int]]] = [[] for _ in range(num_bins)]
    bin_edges = [i / num_bins for i in range(num_bins + 1)]

    for p, label in zip(predicted_probs, ground_truth_labels):
        bin_idx = min(int(p * num_bins), num_bins - 1)
        bins[bin_idx].append((p, label))

    calibration = []
    total_ece = 0.0
    total_count = len(predicted_probs)
    for i, b in enumerate(bins):
        if len(b) == 0:
            avg_pred = (bin_edges[i] + bin_edges[i + 1]) / 2
            emp_acc = 0.0
            count = 0
        else:
            avg_pred = sum(item[0] for item in b) / len(b)
            emp_acc = sum(item[1] for item in b) / len(b)
            count = len(b)

        ce = abs(avg_pred - emp_acc) if count > 0 else 0.0
        if total_count > 0 and count > 0:
            total_ece += ce * (count / total_count)

        calibration.append({
            "bin": f"[{bin_edges[i]:.2f}, {bin_edges[i + 1]:.2f})",
            "count": count,
            "avg_predicted_prob": round(avg_pred, 4),
            "empirical_accuracy": round(emp_acc, 4),
            "calibration_error": round(ce, 4),
        })

    # Append overall Expected Calibration Error (ECE)
    for entry in calibration:
        entry["overall_ECE"] = round(total_ece, 4)

    return calibration


def compute_margin_histogram(
    delta_r: List[float],
    num_bins: int = 6
) -> List[Dict[str, Any]]:
    """
    Builds a histogram of reward margin values to visualise separation.

    Useful for diagnosing whether the policy has learned a clear implicit
    preference ordering (margins far from zero) or remains confused
    (margins clustered near zero).
    """
    if not delta_r:
        return []
    lo = min(delta_r)
    hi = max(delta_r)
    if lo == hi:
        return [{"bin": f"[{lo:.3f}, {hi:.3f}]", "count": len(delta_r)}]
    width = (hi - lo) / num_bins
    histogram = []
    for i in range(num_bins):
        edge_lo = lo + i * width
        edge_hi = lo + (i + 1) * width
        count = sum(1 for v in delta_r if edge_lo <= v < edge_hi or (i == num_bins - 1 and v == edge_hi))
        histogram.append({
            "bin": f"[{edge_lo:+.3f}, {edge_hi:+.3f}{']' if i == num_bins - 1 else ')'}",
            "count": count,
        })
    return histogram


def plot_calibration_diagram(
    calibration: List[Dict[str, Any]],
    output_path: Path,
    title: str = "Bradley-Terry Reliability Diagram",
) -> bool:
    """
    Saves a matplotlib reliability diagram to output_path.

    Returns True on success, False if matplotlib is unavailable.
    The plot shows:
      - Bars for empirical accuracy per bin (the "reliability" diagram).
      - A diagonal line for perfect calibration.
      - Text annotation with the Expected Calibration Error (ECE).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    populated = [c for c in calibration if c["count"] > 0]
    if not populated:
        return False

    avg_preds = [c["avg_predicted_prob"] for c in populated]
    emp_accs = [c["empirical_accuracy"] for c in populated]
    counts = [c["count"] for c in populated]
    ece = calibration[0]["overall_ECE"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 8), gridspec_kw={"height_ratios": [3, 1]})

    # --- Top panel: reliability diagram ---
    bar_width = 0.12
    ax1.bar(avg_preds, emp_accs, width=bar_width, alpha=0.7, color="steelblue",
            edgecolor="black", linewidth=0.5, label="Empirical accuracy")
    ax1.plot([0, 1], [0, 1], "k--", linewidth=1.0, label="Perfect calibration")
    # Gap shading
    for ap, ea in zip(avg_preds, emp_accs):
        ax1.plot([ap, ap], [min(ap, ea), max(ap, ea)], color="tomato", linewidth=2, alpha=0.6)
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.set_xlabel("Mean predicted probability (per bin)")
    ax1.set_ylabel("Empirical accuracy (fraction label=1)")
    ax1.set_title(f"{title}\nECE = {ece:.4f}")
    ax1.legend(loc="upper left")
    ax1.set_aspect("equal")

    # --- Bottom panel: sample count per bin ---
    bin_labels = [c["bin"] for c in populated]
    ax2.bar(range(len(counts)), counts, color="gray", edgecolor="black", linewidth=0.5)
    ax2.set_xticks(range(len(counts)))
    ax2.set_xticklabels(bin_labels, rotation=30, ha="right", fontsize=8)
    ax2.set_ylabel("Count")
    ax2.set_title("Samples per bin")

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Self-Verification Test Suite
# ---------------------------------------------------------------------------

def verify_correctness():
    """Run mathematical and behavioural invariant checks."""

    # --- Test 1: Known closed-form results ---
    # If policy == reference, all rewards must be zero regardless of beta.
    logps = torch.tensor([-10.0, -20.0, -5.0])
    result = evaluate_implicit_rewards(logps, logps, logps, logps, beta=0.1)
    assert all(abs(r) < 1e-7 for r in result["reward_w"]), "Reward must be 0 when policy==ref"
    assert all(abs(r) < 1e-7 for r in result["reward_l"]), "Reward must be 0 when policy==ref"
    assert all(abs(p - 0.5) < 1e-6 for p in result["p_win"]), "P(win) must be 0.5 when rewards equal"
    print("  PASS: policy==reference => zero rewards, P(win)=0.5")

    # --- Test 2: Scaling linearity in beta ---
    # Compare via multiplication (rw2 == 5 * rw1) to avoid division-by-zero
    # if a reward happens to be exactly 0.
    p_w = torch.tensor([-8.0, -12.0])
    p_l = torch.tensor([-14.0, -10.0])
    r_w = torch.tensor([-10.0, -13.0])
    r_l = torch.tensor([-12.0, -11.0])
    res1 = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=0.1)
    res2 = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=0.5)
    for rw1, rw2 in zip(res1["reward_w"], res2["reward_w"]):
        assert abs(rw2 - 5.0 * rw1) < 1e-5, "Rewards must scale linearly with beta"
    print("  PASS: rewards scale linearly with beta")

    # --- Test 3: Perfect separation => 100% accuracy ---
    # Chosen always beats rejected by a fixed margin
    p_w = torch.tensor([-5.0, -6.0, -4.0, -7.0])
    p_l = torch.tensor([-15.0, -16.0, -14.0, -17.0])
    r_w = torch.tensor([-8.0, -8.0, -8.0, -8.0])
    r_l = torch.tensor([-8.0, -8.0, -8.0, -8.0])
    res = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=0.1)
    assert res["pairwise_accuracy"] == 1.0, "Perfect separation must yield 100% accuracy"
    assert all(m > 0 for m in res["delta_r"]), "All margins must be positive"
    print("  PASS: perfect separation => 100% pairwise accuracy")

    # --- Test 4: Reversed preference => 0% accuracy ---
    # Policy prefers rejected over chosen
    res_rev = evaluate_implicit_rewards(p_l, p_w, r_w, r_l, beta=0.1)
    assert res_rev["pairwise_accuracy"] == 0.0, "Reversed preferences must yield 0% accuracy"
    print("  PASS: reversed preferences => 0% accuracy")

    # --- Test 5: Sigmoid boundary values & tie semantics ---
    # When delta_r == 0, P(win) must be exactly 0.5.
    # Ties count as incorrect under strict >, so accuracy == 0.
    p = torch.tensor([-10.0])
    r = torch.tensor([-10.0])
    res0 = evaluate_implicit_rewards(p, p, r, r, beta=0.1)
    assert abs(res0["p_win"][0] - 0.5) < 1e-7, "Zero margin => P(win) = 0.5"
    assert res0["pairwise_accuracy"] == 0.0, "Tied margin must count as incorrect (strict >)"
    print("  PASS: zero margin => sigmoid(0) = 0.5, tie counts as incorrect")

    # --- Test 6: Randomised calibration data ---
    rw = [0.5, -0.2, 0.8, -0.1, 0.3]
    rl = [-0.3, 0.1, -0.5, 0.4, -0.2]
    probs, labels = randomised_calibration_data(rw, rl, seed=42)
    assert len(probs) == len(labels) == 5
    assert set(labels) <= {0, 1}, "Labels must be binary"
    # With these rewards (chosen > rejected in most), expect a mix
    assert 0 in labels and 1 in labels, "Randomised labels should contain both 0 and 1"
    # Verify probability computation for each case
    for i, (rw_i, rl_i, p_i, lbl_i) in enumerate(zip(rw, rl, probs, labels)):
        if lbl_i == 1:
            expected = 1.0 / (1.0 + math.exp(-(rw_i - rl_i)))
        else:
            expected = 1.0 / (1.0 + math.exp(-(rl_i - rw_i)))
        assert abs(p_i - expected) < 1e-10, f"Pair {i}: probability mismatch"
    # Deterministic with same seed
    probs2, labels2 = randomised_calibration_data(rw, rl, seed=42)
    assert probs == probs2 and labels == labels2, "Must be deterministic for same seed"
    print("  PASS: randomised calibration data produces mixed labels, correct probs, deterministic")

    # --- Test 7: Calibration curve correctness ---
    probs = [0.1, 0.2, 0.3, 0.6, 0.7, 0.8, 0.9, 0.95]
    labels = [0,   0,   0,   1,   1,   1,   1,   1]
    cal = compute_calibration_curve(probs, labels, num_bins=4)
    assert len(cal) == 4, "Must produce exactly num_bins entries"
    # High-probability bin: [0.75, 1.00) contains 0.8, 0.9, 0.95 all with label=1
    high_bin = cal[3]
    assert high_bin["empirical_accuracy"] == 1.0, "All labels=1 in top bin"
    assert high_bin["count"] == 3, "Three samples (0.8, 0.9, 0.95) in top bin"
    # Low-probability bin: [0.00, 0.25) contains 0.1, 0.2 both with label=0
    low_bin = cal[0]
    assert low_bin["empirical_accuracy"] == 0.0, "All labels=0 in bottom bin"
    # ECE must be non-negative
    assert all(entry["overall_ECE"] >= 0 for entry in cal), "ECE must be >= 0"
    # Well-calibrated example should have low ECE
    assert cal[0]["overall_ECE"] < 0.25, "Well-separated labels should give moderate ECE"
    print("  PASS: calibration curve binning, ECE computation")

    # --- Test 8: Margin histogram ---
    hist = compute_margin_histogram([0.1, 0.2, 0.5, -0.3, -0.1, 1.0], num_bins=3)
    assert len(hist) == 3, "Must produce exactly num_bins entries"
    assert sum(h["count"] for h in hist) == 6, "Histogram must cover all samples"
    print("  PASS: margin histogram covers all samples")

    # --- Test 9: Input validation ---
    try:
        evaluate_implicit_rewards(torch.tensor([1.0]), torch.tensor([1.0, 2.0]),
                                  torch.tensor([1.0]), torch.tensor([1.0]))
        assert False, "Should reject mismatched lengths"
    except ValueError:
        pass
    try:
        evaluate_implicit_rewards(torch.tensor([float("nan")]), torch.tensor([1.0]),
                                  torch.tensor([1.0]), torch.tensor([1.0]))
        assert False, "Should reject NaN"
    except ValueError:
        pass
    try:
        evaluate_implicit_rewards(torch.tensor([1.0]), torch.tensor([1.0]),
                                  torch.tensor([1.0]), torch.tensor([1.0]), beta=-1.0)
        assert False, "Should reject negative beta"
    except ValueError:
        pass
    print("  PASS: input validation rejects bad inputs")

    # --- Test 10: Cross-check with Part 1 DPO loss sign ---
    # Verify that our implicit rewards match what DPOLoss computes internally:
    # the sign of our mean delta_r must agree with DPOLoss's reward_margin.
    import importlib.util
    part1_path = Path(__file__).with_name("01_DPO_Loss_Core.py")
    if part1_path.exists():
        spec = importlib.util.spec_from_file_location("dpo_core", part1_path)
        dpo_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dpo_mod)

        torch.manual_seed(42)
        p_w_logps = torch.tensor([-8.5, -10.2, -7.3])
        p_l_logps = torch.tensor([-12.1, -14.0, -11.8])
        r_w_logps = torch.tensor([-9.0, -11.0, -8.0])
        r_l_logps = torch.tensor([-10.0, -12.0, -9.5])
        beta = 0.1

        # Part 1: DPOLoss metrics
        dpo_criterion = dpo_mod.DPOLoss(beta=beta)
        _, dpo_metrics = dpo_criterion(p_w_logps, p_l_logps, r_w_logps, r_l_logps)

        # Part 2: Our implicit rewards
        our_results = evaluate_implicit_rewards(p_w_logps, p_l_logps,
                                                r_w_logps, r_l_logps, beta=beta)

        # Rewards must match the formula: r = beta * (policy_logp - ref_logp)
        for i in range(3):
            expected_rw = beta * (p_w_logps[i] - r_w_logps[i]).item()
            assert abs(our_results["reward_w"][i] - expected_rw) < 1e-5
            expected_rl = beta * (p_l_logps[i] - r_l_logps[i]).item()
            assert abs(our_results["reward_l"][i] - expected_rl) < 1e-5

        # Sign of margin must agree
        dpo_margin_sign = (dpo_metrics["reward_margin"] > 0).item()
        our_margin_sign = our_results["mean_margin"] > 0
        assert dpo_margin_sign == our_margin_sign, "Margin sign must agree with Part 1"
        print("  PASS: cross-validated with Part 1 DPOLoss (reward values + margin sign)")
    else:
        print("  SKIP: Part 1 file not found for cross-validation")


# ---------------------------------------------------------------------------
# Evaluation on Real or Synthetic Data
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_SCORED_PAIRS = RESULTS_DIR / "length_bias_scored_pairs.json"
DEFAULT_EVALUATION = RESULTS_DIR / "length_bias_evaluation.json"


def load_scored_pairs(path: Path) -> List[Dict[str, Any]]:
    """Load and validate scored preference pairs from Part 3's JSON output."""
    required_keys = ("chosen_length", "rejected_length",
                     "policy_chosen_logp", "policy_rejected_logp",
                     "ref_chosen_logp", "ref_rejected_logp")
    try:
        pairs = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"ERROR: scored pairs file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {path} is not valid JSON: {exc}")
    if not isinstance(pairs, list) or len(pairs) < 2:
        raise SystemExit("ERROR: expected a JSON list with at least two scored pairs")
    for i, row in enumerate(pairs):
        missing = [k for k in required_keys if k not in row]
        if missing:
            raise SystemExit(f"ERROR: pair {i} is missing keys: {missing}")
    return pairs


def evaluate_on_pairs(
    pairs: List[Dict[str, Any]],
    beta: float = 0.1,
    calibration_seed: int = 42,
) -> Dict[str, Any]:
    """
    Run full implicit-reward evaluation on scored preference pairs.

    Extracts policy and reference log-probabilities from the pair dicts,
    computes implicit rewards, pairwise accuracy, calibration curve
    (with randomised A/B ordering for genuine mixed labels), and margin
    histogram.
    """
    p_w = torch.tensor([r["policy_chosen_logp"] for r in pairs], dtype=torch.float64)
    p_l = torch.tensor([r["policy_rejected_logp"] for r in pairs], dtype=torch.float64)
    r_w = torch.tensor([r["ref_chosen_logp"] for r in pairs], dtype=torch.float64)
    r_l = torch.tensor([r["ref_rejected_logp"] for r in pairs], dtype=torch.float64)

    eval_results = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=beta)

    # Calibration with randomised A/B assignment for genuine mixed labels.
    cal_probs, cal_labels = randomised_calibration_data(
        eval_results["reward_w"], eval_results["reward_l"], seed=calibration_seed)
    calibration = compute_calibration_curve(cal_probs, cal_labels, num_bins=5)

    # Margin histogram
    histogram = compute_margin_histogram(eval_results["delta_r"], num_bins=6)

    return {
        "eval": eval_results,
        "calibration": calibration,
        "calibration_probs": cal_probs,
        "calibration_labels": cal_labels,
        "histogram": histogram,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

LINE = "=" * 70


def _provenance_lines(evaluation: Optional[Dict]) -> List[str]:
    """Build provenance description from Part 3's evaluation metadata."""
    meta = (evaluation or {}).get("metadata")
    if not meta:
        return ["    Provenance: not supplied; document dataset, models and masking yourself."]
    rev = lambda key: str(meta.get(key, "?"))[:7]
    lines = [
        f"    Data    : {meta.get('dataset')} {meta.get('dataset_file')} @ {rev('dataset_revision')}, "
        f"{meta.get('sample_size')} pairs (seed {meta.get('selection_seed')}, no truncation)",
        f"    Policy  : {meta.get('policy')} @ {rev('policy_revision')}",
        f"    Ref     : {meta.get('reference')} @ {rev('reference_revision')}",
    ]
    if meta.get("trained_here") is False:
        lines.append("    Status  : exploratory instruct-vs-base comparison; no model was trained here")
    return lines


def report_synthetic(beta: float = 0.1):
    """Report on 8 hardcoded synthetic log-probability pairs."""
    # Simulated log-probabilities for 8 test queries aboard the Noosphere
    p_w = torch.tensor([-10.2, -12.4,  -8.1, -14.5,  -9.8, -11.0, -15.2,  -7.9])
    p_l = torch.tensor([-15.1, -13.0, -11.5, -13.8, -14.2, -16.4, -14.9, -12.1])
    r_w = torch.tensor([-12.0, -14.0, -10.0, -15.0, -11.0, -13.0, -16.0,  -9.5])
    r_l = torch.tensor([-13.0, -13.5, -10.5, -14.0, -12.0, -14.0, -15.5, -10.0])

    eval_results = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=beta)

    print(f"[2] SYNTHETIC EVALUATION  (8 hardcoded pairs, beta={beta})")
    print(f"    Pairwise Classification Accuracy : {eval_results['pairwise_accuracy'] * 100:.1f}%")
    print(f"    Mean Implicit Reward Margin      : {eval_results['mean_margin']:+.4f}")
    print(f"    Std  Implicit Reward Margin      : {eval_results['std_margin']:.4f}")
    print(f"    Mean Bradley-Terry P(y_w > y_l)  : {eval_results['mean_p_win'] * 100:.2f}%")
    print(f"    Mean r(x, y_w)                   : {eval_results['mean_reward_w']:+.4f}")
    print(f"    Mean r(x, y_l)                   : {eval_results['mean_reward_l']:+.4f}")
    print(f"    (Ties count as incorrect under strict > comparison.)")

    print()
    print("    Per-Pair Implicit Rewards:")
    print("    " + "-" * 62)
    fmt = "    {:<6}{:<12}{:<12}{:<14}{:<12}"
    print(fmt.format("Pair", "r(y_w)", "r(y_l)", "Margin (dr)", "P(y_w>y_l)"))
    print("    " + "-" * 62)
    for i in range(len(eval_results["reward_w"])):
        rw = eval_results["reward_w"][i]
        rl = eval_results["reward_l"][i]
        delta = eval_results["delta_r"][i]
        prob = eval_results["p_win"][i]
        status = "OK" if delta > 0 else ("TIE" if delta == 0 else "MISS")
        print(f"    #{i+1:<5}{rw:<12.4f}{rl:<12.4f}{delta:<+14.4f}{prob*100:<6.1f}%  [{status}]")

    # Calibration with randomised A/B ordering
    cal_probs, cal_labels = randomised_calibration_data(
        eval_results["reward_w"], eval_results["reward_l"], seed=42)
    calib = compute_calibration_curve(cal_probs, cal_labels, num_bins=4)

    print()
    print("    Bradley-Terry Reliability Calibration (4 bins, randomised A/B order, seed=42):")
    print("    " + "-" * 62)
    for c in calib:
        print(f"    Bin {c['bin']}: n={c['count']} | "
              f"Pred={c['avg_predicted_prob']:.4f} | "
              f"Emp={c['empirical_accuracy']:.4f} | "
              f"CE={c['calibration_error']:.4f}")
    print(f"    Expected Calibration Error (ECE): {calib[0]['overall_ECE']:.4f}")

    # Margin histogram
    hist = compute_margin_histogram(eval_results["delta_r"], num_bins=4)
    print()
    print("    Reward Margin Histogram:")
    print("    " + "-" * 40)
    for h in hist:
        bar = "#" * min(h["count"] * 3, 24)
        print(f"    {h['bin']:<24} | {bar} ({h['count']})")

    return eval_results


def report_real_pairs(pairs: List[Dict[str, Any]],
                      evaluation: Optional[Dict] = None,
                      beta: float = 0.1):
    """Report implicit reward evaluation on real scored preference pairs."""
    results = evaluate_on_pairs(pairs, beta=beta)
    ev = results["eval"]

    print(f"[3] REAL DATA EVALUATION  ({ev['num_pairs']} scored pairs, beta={beta})")
    for line in _provenance_lines(evaluation):
        print(line)
    print(f"    Pairwise Classification Accuracy : {ev['pairwise_accuracy'] * 100:.1f}%")
    print(f"    Mean Implicit Reward Margin      : {ev['mean_margin']:+.6f}")
    print(f"    Std  Implicit Reward Margin      : {ev['std_margin']:.6f}")
    print(f"    Mean Bradley-Terry P(y_w > y_l)  : {ev['mean_p_win'] * 100:.2f}%")
    print(f"    Mean r(x, y_w)                   : {ev['mean_reward_w']:+.6f}")
    print(f"    Mean r(x, y_l)                   : {ev['mean_reward_l']:+.6f}")
    print(f"    (Ties count as incorrect under strict > comparison.)")

    # Margin statistics
    margins = ev["delta_r"]
    positive = sum(1 for m in margins if m > 0)
    negative = sum(1 for m in margins if m < 0)
    tied = sum(1 for m in margins if m == 0)
    print(f"    Positive margins (correct rank)   : {positive}/{len(margins)}")
    print(f"    Negative margins (incorrect rank)  : {negative}/{len(margins)}")
    if tied > 0:
        print(f"    Tied margins (zero, counted wrong) : {tied}/{len(margins)}")

    # Calibration
    calib = results["calibration"]
    print()
    print("    Bradley-Terry Reliability Calibration (5 bins, randomised A/B order, seed=42):")
    print("    " + "-" * 62)
    for c in calib:
        print(f"    Bin {c['bin']}: n={c['count']:<3} | "
              f"Pred={c['avg_predicted_prob']:.4f} | "
              f"Emp={c['empirical_accuracy']:.4f} | "
              f"CE={c['calibration_error']:.4f}")
    print(f"    Expected Calibration Error (ECE): {calib[0]['overall_ECE']:.4f}")

    # Plot
    plot_path = RESULTS_DIR / "bt_calibration_diagram.png"
    plotted = plot_calibration_diagram(calib, plot_path,
                                       title="Bradley-Terry Reliability Diagram (real pairs)")
    if plotted:
        print(f"    Calibration plot saved to: {plot_path}")
    else:
        print("    (matplotlib not available; skipping calibration plot)")

    # Margin histogram
    hist = results["histogram"]
    max_count = max((h["count"] for h in hist), default=1)
    print()
    print("    Reward Margin Distribution:")
    print("    " + "-" * 50)
    for h in hist:
        bar_len = max(1, int(h["count"] / max_count * 20))
        bar = "#" * bar_len
        print(f"    {h['bin']:<24} | {bar} ({h['count']})")

    # Assessment
    print()
    if ev["pairwise_accuracy"] >= 0.7:
        print("    Assessment: The policy assigns higher implicit reward to the")
        print(f"    human-preferred response in {ev['pairwise_accuracy']*100:.0f}% of pairs.")
        print("    The reward signal is informative for preference ranking.")
    elif ev["pairwise_accuracy"] >= 0.5:
        print("    Assessment: The policy shows weak preference alignment")
        print(f"    ({ev['pairwise_accuracy']*100:.0f}% accuracy). Further DPO training")
        print("    is expected to improve separation.")
    else:
        print(f"    Assessment: The instruct-vs-base log-ratio ranks the human-preferred")
        print(f"    response higher in only {ev['pairwise_accuracy']*100:.0f}% of pairs. This means")
        print(f"    the instruct checkpoint's distributional shift from its base model does not")
        print(f"    track human helpfulness preferences on these pairs. This is not surprising:")
        print(f"    the instruct model's fine-tuning objective was not DPO on this dataset, so")
        print(f"    its implicit log-ratio reward is not expected to align with Anthropic HH-RLHF")
        print(f"    labels. A DPO-trained model on these pairs would be expected to exceed 50%.")

    return results


def report_beta_sensitivity(pairs: List[Dict[str, Any]]):
    """Sweep beta values and show how reward margin and calibration change.

    Note: pairwise accuracy is INVARIANT to beta. Scaling all margins by a
    constant preserves their sign, so the same pairs are classified correctly
    regardless of beta. What changes is the magnitude of the margins and
    the Bradley-Terry probabilities (which saturate toward 0 or 1 at large
    beta), and consequently the calibration ECE.
    """
    print("[4] BETA SENSITIVITY ANALYSIS")
    print("    Sweeping beta to observe its effect on margin magnitude and calibration.")
    print("    NOTE: Accuracy is invariant to beta (scaling margins preserves their sign).")
    print("    Only the margin magnitude, P(win) saturation, and ECE change.")
    print("    " + "-" * 70)
    fmt = "    {:<8}{:<12}{:<16}{:<14}{:<12}"
    print(fmt.format("beta", "Accuracy", "Mean Margin", "Mean P(win)", "ECE"))
    print("    " + "-" * 70)

    p_w = torch.tensor([r["policy_chosen_logp"] for r in pairs], dtype=torch.float64)
    p_l = torch.tensor([r["policy_rejected_logp"] for r in pairs], dtype=torch.float64)
    r_w = torch.tensor([r["ref_chosen_logp"] for r in pairs], dtype=torch.float64)
    r_l = torch.tensor([r["ref_rejected_logp"] for r in pairs], dtype=torch.float64)

    for beta in [0.01, 0.05, 0.1, 0.2, 0.5, 1.0]:
        ev = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=beta)
        cal_probs, cal_labels = randomised_calibration_data(
            ev["reward_w"], ev["reward_l"], seed=42)
        cal = compute_calibration_curve(cal_probs, cal_labels, num_bins=5)
        ece = cal[0]["overall_ECE"]
        print(f"    {beta:<8.2f}{ev['pairwise_accuracy']*100:<12.1f}{ev['mean_margin']:<+16.6f}"
              f"{ev['mean_p_win']*100:<14.2f}{ece:<12.4f}")
    print("    At small beta, P(win) clusters near 0.5 and margins are tiny.")
    print("    At large beta, P(win) saturates toward 0/1 and margins blow up.")
    print("    The ECE reflects how well the sigmoid-scaled margins match empirical rates.")


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def main():
    # Fix Windows encoding issues
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--pairs", type=Path,
        help="JSON list of scored preference pairs (from Part 3's output)"
    )
    parser.add_argument(
        "--beta", type=float, default=0.1,
        help="DPO temperature beta (default: 0.1)"
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Run self-checks and exit"
    )
    args = parser.parse_args()

    print(LINE)
    print("USSE NOOSPHERE * IMPLICIT REWARD & BRADLEY-TERRY CALIBRATION ENGINE")
    print("Mission 04 / Part 2 -- Communications & Protocol Officer")
    print(LINE)

    # [1] Self-checks
    print("[1] SELF-CHECKS")
    verify_correctness()
    print("    All checks passed.")
    if args.verify_only:
        print(LINE)
        return 0

    print(LINE)

    # [2] Synthetic evaluation (always runs)
    report_synthetic(beta=args.beta)

    # [3] Real data evaluation (if available)
    print(LINE)
    evaluation = None
    if args.pairs:
        pairs = load_scored_pairs(args.pairs)
        report_real_pairs(pairs, beta=args.beta)
        # [4] Beta sensitivity
        print(LINE)
        report_beta_sensitivity(pairs)
    elif DEFAULT_SCORED_PAIRS.exists():
        pairs = load_scored_pairs(DEFAULT_SCORED_PAIRS)
        if DEFAULT_EVALUATION.exists():
            evaluation = json.loads(DEFAULT_EVALUATION.read_text(encoding="utf-8"))
        report_real_pairs(pairs, evaluation=evaluation, beta=args.beta)
        # [4] Beta sensitivity
        print(LINE)
        report_beta_sensitivity(pairs)
    else:
        print("[3] REAL DATA EVALUATION")
        print("    No scored pairs found. Run Part 3 with --score-real first, or provide")
        print("    --pairs path/to/scored_pairs.json")
        print("    Skipping real-data evaluation and beta sweep.")

    print(LINE)
    print("[COMPLETE] Subsystem 04 Implicit Reward & Bradley-Terry Calibration Engine validated.")
    print(LINE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
