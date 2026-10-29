"""
Mission 04 — Part 2: Communications & Protocol Officer
Implicit Reward Extraction & Bradley-Terry Evaluation

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse)
Subsystem 04: Plasma Ignition & Ethical Steering Core
"""

import math
import torch
from typing import List, Dict, Any


def evaluate_implicit_rewards(
    policy_chosen_logps: torch.FloatTensor,
    policy_rejected_logps: torch.FloatTensor,
    ref_chosen_logps: torch.FloatTensor,
    ref_rejected_logps: torch.FloatTensor,
    beta: float = 0.1
) -> Dict[str, Any]:
    """
    Extracts implicit scalar rewards and evaluates Bradley-Terry win probabilities.
    
    Under DPO:
        r(x, y) = beta * (log pi(y|x) - log pi_ref(y|x))
        P(yw > yl | x) = sigma(r(x, yw) - r(x, yl))
    """
    reward_w = beta * (policy_chosen_logps - ref_chosen_logps)
    reward_l = beta * (policy_rejected_logps - ref_rejected_logps)
    delta_r = reward_w - reward_l

    # Bradley-Terry pairwise preference probability
    p_win = torch.sigmoid(delta_r)

    # Classification accuracy: model correctly prefers chosen over rejected
    pairwise_acc = (reward_w > reward_l).float().mean().item()

    return {
        "reward_w": reward_w.tolist(),
        "reward_l": reward_l.tolist(),
        "delta_r": delta_r.tolist(),
        "p_win": p_win.tolist(),
        "pairwise_accuracy": pairwise_acc,
        "mean_margin": delta_r.mean().item(),
        "mean_p_win": p_win.mean().item()
    }


def compute_calibration_curve(
    predicted_probs: List[float],
    ground_truth_labels: List[int],
    num_bins: int = 5
) -> List[Dict[str, float]]:
    """
    Computes a reliability calibration curve by binning predicted probabilities.
    """
    bins = [[] for _ in range(num_bins)]
    bin_edges = [i / num_bins for i in range(num_bins + 1)]

    for p, label in zip(predicted_probs, ground_truth_labels):
        bin_idx = min(int(p * num_bins), num_bins - 1)
        bins[bin_idx].append((p, label))

    calibration = []
    for i, b in enumerate(bins):
        if len(b) == 0:
            avg_pred = (bin_edges[i] + bin_edges[i+1]) / 2
            emp_acc = 0.0
            count = 0
        else:
            avg_pred = sum(item[0] for item in b) / len(b)
            emp_acc = sum(item[1] for item in b) / len(b)
            count = len(b)
            
        calibration.append({
            "bin": f"[{bin_edges[i]:.2f}, {bin_edges[i+1]:.2f})",
            "count": count,
            "avg_predicted_prob": avg_pred,
            "empirical_accuracy": emp_acc,
            "calibration_error": abs(avg_pred - emp_acc) if count > 0 else 0.0
        })

    return calibration


if __name__ == "__main__":
    print("=" * 70)
    print("USSE NOOSPHERE • IMPLICIT REWARD & BRADLEY-TERRY CALIBRATION ENGINE")
    print("=" * 70)

    # Simulated log-probabilities for 8 test queries aboard the Noosphere
    p_w = torch.tensor([-10.2, -12.4, -8.1, -14.5, -9.8, -11.0, -15.2, -7.9])
    p_l = torch.tensor([-15.1, -13.0, -11.5, -13.8, -14.2, -16.4, -14.9, -12.1])
    r_w = torch.tensor([-12.0, -14.0, -10.0, -15.0, -11.0, -13.0, -16.0, -9.5])
    r_l = torch.tensor([-13.0, -13.5, -10.5, -14.0, -12.0, -14.0, -15.5, -10.0])

    eval_results = evaluate_implicit_rewards(p_w, p_l, r_w, r_l, beta=0.1)

    print(f"[✓] Pairwise Classification Accuracy: {eval_results['pairwise_accuracy'] * 100:.1f}%")
    print(f"[✓] Mean Implicit Reward Margin: {eval_results['mean_margin']:+.4f}")
    print(f"[✓] Mean Bradley-Terry Probability: {eval_results['mean_p_win'] * 100:.2f}%\n")

    print("Detailed Test Pairs:")
    print("-" * 65)
    print(f"{'Pair':<6} {'r(y_w)':<12} {'r(y_l)':<12} {'Margin (Δr)':<14} {'P(y_w > y_l)':<12}")
    print("-" * 65)
    for i in range(len(eval_results['reward_w'])):
        rw = eval_results['reward_w'][i]
        rl = eval_results['reward_l'][i]
        delta = eval_results['delta_r'][i]
        prob = eval_results['p_win'][i]
        print(f"#{i+1:<5} {rw:<12.3f} {rl:<12.3f} {delta:<+14.3f} {prob*100:<6.1f}%")

    # Calibration analysis
    labels = [1] * len(p_w)  # All y_w are ground-truth preferred
    calib = compute_calibration_curve(eval_results['p_win'], labels, num_bins=4)

    print("\nBradley-Terry Reliability Calibration:")
    print("-" * 65)
    for c in calib:
        print(f"Bin {c['bin']}: Count={c['count']} | Pred Prob={c['avg_predicted_prob']:.3f} | Emp Acc={c['empirical_accuracy']:.3f} | Error={c['calibration_error']:.3f}")
    print("=" * 70)
