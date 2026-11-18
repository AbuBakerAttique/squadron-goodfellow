"""
Mission 07 — Part 3: Data & Payload Specialist
Process Reward Model (PRM) Step Evaluator & Math-Shepherd Automated Supervision

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-07-SGR (Sagittarius A* Supermassive Black Hole)
Subsystem 07: Gravitational Search Horizon & Process Reward Evaluator
"""

import math
from typing import Dict, List


class OutcomeRewardEvaluator:
    """
    Outcome Reward Model (ORM): Grades a reasoning chain solely by its final terminal step.
    Vulnerable to false-positive trajectories where intermediate algebraic errors cancel out.
    """

    def __init__(self, expected_final_marker: str):
        self.expected_final_marker = expected_final_marker

    def score_trajectory(self, steps: List[str]) -> float:
        if not steps:
            return 0.0
        return 1.0 if self.expected_final_marker in steps[-1] else 0.0


class ProcessRewardEvaluator:
    """
    Educational PRM surrogate using the instructor's annotated-step scoring rules.

    Scores are heuristic weights, not calibrated probabilities or a trained model's
    judgement. Unmarked incorrect mathematics can receive the default high score.
    Public method signatures are retained for the other mission modules.
    """

    def step_score(self, step: str) -> float:
        """
        Score supplied annotations in (0.0, 1.0]. Explicit flaw markers take
        precedence over minor drift. The default does not prove a step correct.
        """
        if "[FLAWED]" in step or "SIGN_ERROR" in step:
            return 0.12
        if "[MINOR_DRIFT]" in step:
            return 0.55
        return 0.94

    def score_all_steps(self, steps: List[str]) -> List[float]:
        return [self.step_score(s) for s in steps]

    def aggregate_trajectory_min(self, steps: List[str]) -> float:
        """
        Weakest-link reduction: min_{t=1..T} r_t. Empty chains score zero.
        """
        if not steps:
            return 0.0
        return min(self.score_all_steps(steps))

    def aggregate_trajectory_prod(self, steps: List[str]) -> float:
        """
        Product reduction: prod_{t=1..T} r_t. Empty chains score zero.
        This is a ranking heuristic here, not an established joint probability.
        """
        if not steps:
            return 0.0
        prod = 1.0
        for r in self.score_all_steps(steps):
            prod *= r
        return prod

    def aggregate_trajectory_geometric_mean(self, steps: List[str]) -> float:
        """
        Length-normalized geometric mean computed in log space.
        Taking logs before multiplication avoids product underflow on long chains.
        """
        if not steps:
            return 0.0
        scores = self.score_all_steps(steps)
        return math.exp(math.fsum(math.log(r) for r in scores) / len(scores))

    def math_shepherd_estimation(
        self,
        intermediate_step: str,
        rollout_final_answers: List[str],
        ground_truth_answer: str,
    ) -> Dict[str, float]:
        """
        Estimate Math-Shepherd-style labels from supplied simulated completions.
        The caller must supply answers conditioned on `intermediate_step`; this
        function counts exact matches and does not generate or verify rollouts.
        An empty list returns zeros by the starter convention (no evidence).
        Given M Monte Carlo completion answers `rollout_final_answers` sampled from `intermediate_step`:
          - soft_label = (1 / M) * sum(1 for ans in rollout_final_answers if ans == ground_truth_answer)
          - hard_label = 1.0 if any rollout matches ground_truth_answer else 0.0
        """
        if not rollout_final_answers:
            return {"soft_label": 0.0, "hard_label": 0.0}
        matches = sum(1 for ans in rollout_final_answers if ans == ground_truth_answer)
        soft_label = matches / len(rollout_final_answers)
        hard_label = 1.0 if matches > 0 else 0.0
        return {"soft_label": soft_label, "hard_label": hard_label}


# ==============================================================================
# Verification Harness for Part 3 (Data & Payload Specialist)
# ==============================================================================
if __name__ == "__main__":
    print("=== Subsystem 07 (Part 3): PRM vs. ORM & Math-Shepherd Verification ===")

    orm = OutcomeRewardEvaluator(expected_final_marker="v_esc = 24.0 km/s")
    prm = ProcessRewardEvaluator()

    # Instructor-provided illustrative chain; not a verified Kerr derivation.
    valid_chain = [
        "Step 1: Set metric tensor g_uv for Kerr spin parameter a = 0.9M",
        "Step 2: Integrate conserved orbital energy E and angular momentum L_z",
        "Step 3: Solve radial potential boundary -> v_esc = 24.0 km/s",
    ]

    # Trajectory 2: False-Positive Trap (Double-sign cancellation in Step 2 reaches lucky right scalar!)
    false_positive_chain = [
        "Step 1: Set metric tensor g_uv for Kerr spin parameter a = 0.9M",
        "Step 2: [FLAWED] Flip sign of frame-dragging term twice (-1 * -1 = +1) via illegal tensor contraction",
        "Step 3: Accidental cancellation yields -> v_esc = 24.0 km/s",
    ]

    for label, chain in [("Rigorous Chain", valid_chain), ("False-Positive Trap", false_positive_chain)]:
        orm_score = orm.score_trajectory(chain)
        prm_min = prm.aggregate_trajectory_min(chain)
        prm_prod = prm.aggregate_trajectory_prod(chain)
        prm_geo = prm.aggregate_trajectory_geometric_mean(chain)
        print(
            f"{label:20s} | ORM={orm_score:.2f} | PRM(min)={prm_min:.3f} | "
            f"PRM(prod)={prm_prod:.3f} | PRM(geo)={prm_geo:.3f}"
        )

    assert orm.score_trajectory(false_positive_chain) == 1.0, "ORM should be fooled by the terminal answer!"
    assert prm.aggregate_trajectory_min(false_positive_chain) < 0.20, "PRM(min) must catch the flawed intermediate step!"

    # Test Math-Shepherd Monte Carlo Step Estimation
    shepherd = prm.math_shepherd_estimation(
        intermediate_step=valid_chain[1],
        rollout_final_answers=["24.0 km/s", "24.0 km/s", "22.5 km/s", "24.0 km/s"],
        ground_truth_answer="24.0 km/s",
    )
    print(f"Math-Shepherd Step Estimation (M=4 rollouts): {shepherd}")
    assert abs(shepherd["soft_label"] - 0.75) < 1e-6 and shepherd["hard_label"] == 1.0
    # Four supplied simulated answers for the trap; no live model was sampled.
    trap_labels = prm.math_shepherd_estimation(
        false_positive_chain[1],
        ["22.5 km/s", "24.0 km/s", "23.0 km/s", "21.0 km/s"],
        "24.0 km/s",
    )
    assert trap_labels == {"soft_label": 0.25, "hard_label": 1.0}
    print(f"Trap step labels (M=4 supplied simulated rollouts): {trap_labels}")

    # An explicit algebraic example: two illegal sign changes cancel.
    # Correct: x + 3 = 7 -> x = 7 - 3 -> x = 4.
    algebra_valid = ["x + 3 = 7", "x = 7 - 3", "x = 4"]
    algebra_trap = [
        "x + 3 = 7",
        "[FLAWED] SIGN_ERROR: x = 3 - 7 = -4",
        "[FLAWED] SIGN_ERROR: x = -(-4) = 4; final x = 4",
    ]
    algebra_orm = OutcomeRewardEvaluator(expected_final_marker="x = 4")
    for label, chain in [("Valid algebra", algebra_valid), ("Double-sign trap", algebra_trap)]:
        print(
            f"{label:20s} | ORM={algebra_orm.score_trajectory(chain):.2f} | "
            f"PRM(min)={prm.aggregate_trajectory_min(chain):.3f} | "
            f"PRM(prod)={prm.aggregate_trajectory_prod(chain):.3f} | "
            f"PRM(geo)={prm.aggregate_trajectory_geometric_mean(chain):.3f}"
        )
    assert algebra_orm.score_trajectory(algebra_trap) == 1.0
    assert prm.aggregate_trajectory_min(algebra_trap) == 0.12

    # Check the three reductions against independently calculated fixture values.
    mixed = ["normal", "[MINOR_DRIFT]", "[FLAWED]"]
    assert prm.aggregate_trajectory_min(mixed) == 0.12
    assert math.isclose(prm.aggregate_trajectory_prod(mixed), 0.06204)
    assert math.isclose(prm.aggregate_trajectory_geometric_mean(mixed), 0.06204 ** (1 / 3))
    assert prm.step_score("[MINOR_DRIFT] SIGN_ERROR") == 0.12
    for reducer in (prm.aggregate_trajectory_min, prm.aggregate_trajectory_prod,
                    prm.aggregate_trajectory_geometric_mean):
        assert reducer([]) == 0.0
        assert math.isclose(reducer(["[MINOR_DRIFT]"]), 0.55)
    assert orm.score_trajectory([]) == 0.0
    assert orm.score_trajectory(["wrong final answer"]) == 0.0
    for answers, expected in [([], (0.0, 0.0)), (["wrong"] * 4, (0.0, 0.0)),
                              (["correct"] * 4, (1.0, 1.0))]:
        labels = prm.math_shepherd_estimation("fixed step", answers, "correct")
        assert (labels["soft_label"], labels["hard_label"]) == expected

    # All steps have the same quality: geometric mean must stay 0.12 even
    # when the product is too small to represent in a Python float.
    long_chain = ["[FLAWED]"] * 1000
    assert prm.aggregate_trajectory_prod(long_chain) == 0.0
    assert math.isclose(prm.aggregate_trajectory_geometric_mean(long_chain), 0.12)
    print("Long-chain check (1000 scores of 0.12): product=0.0; geometric_mean=0.120")
    print("Length comparison (all unmarked scores are 0.94):")
    for length in (3, 10, 100):
        chain = ["unmarked step"] * length
        print(f"  T={length:3d} | min={prm.aggregate_trajectory_min(chain):.6f} | "
              f"prod={prm.aggregate_trajectory_prod(chain):.6f} | "
              f"geo={prm.aggregate_trajectory_geometric_mean(chain):.6f}")
    print("[OK] Reduction, empty/single-step, marker precedence and rollout boundary checks passed.")
    print("[OK] Part 3 (Data & Payload Specialist) verification passed.")
