"""
Mission 07 — Part 2: Communications & Protocol Officer
4-Phase Monte Carlo Tree Search (MCTS) & PUCT Selection Engine

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-07-SGR (Sagittarius A* Supermassive Black Hole)
Subsystem 07: Gravitational Search Horizon & Process Reward Evaluator
"""

import math
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class MCTSNode:
    """Represents a node in the Monte Carlo Reasoning Tree."""
    state: str
    prior_prob: float = 1.0
    parent: Optional["MCTSNode"] = None
    children: List["MCTSNode"] = field(default_factory=list)
    visit_count: int = 0
    value_sum: float = 0.0
    is_terminal: bool = False

    @property
    def q_value(self) -> float:
        """Empirical mean action-value Q(s, a) = W(s, a) / N(s, a).

        Returns 0.0 when the node has never been visited (N=0), which
        means unvisited nodes are ranked purely by their exploration bonus.
        """
        if self.visit_count == 0:
            return 0.0
        return self.value_sum / self.visit_count

    def get_trajectory(self) -> List[str]:
        """Reconstructs the reasoning chain [root_state, ..., this_state]."""
        path: List[str] = []
        curr: Optional[MCTSNode] = self
        while curr is not None:
            path.append(curr.state)
            curr = curr.parent
        return list(reversed(path))

    def __repr__(self) -> str:
        return (f"MCTSNode(state={self.state!r}, Q={self.q_value:.3f}, "
                f"N={self.visit_count}, P={self.prior_prob:.2f}, "
                f"terminal={self.is_terminal})")


class MCTSEngine:
    """
    Implements the 4 canonical phases of Monte Carlo Tree Search (MCTS) for
    LLM reasoning, guided by a Predictor + Upper Confidence Bound applied to
    Trees (PUCT) selection formula.

    The 4 Phases:
        1. Selection   — Traverse the existing tree via PUCT to find a leaf.
        2. Expansion   — Attach candidate reasoning steps with LLM priors.
        3. Simulation  — Evaluate the new node via PRM or rollout completion.
        4. Backpropagation — Update N(s,a) and W(s,a) along the ancestor path.

    Args:
        c_puct:  Exploration constant balancing Q(s,a) exploitation vs.
                 P(a|s) * sqrt(N) / (1+N(s,a)) exploration. Default 1.5.
        verbose: If True, log each phase to stdout.
    """

    def __init__(self, c_puct: float = 1.5, verbose: bool = False):
        if c_puct < 0:
            raise ValueError(f"c_puct must be >= 0, got {c_puct}")
        self.c_puct = c_puct
        self.verbose = verbose
        self.trace: List[str] = []

#  helpers
    def _log(self, msg: str) -> None:
        self.trace.append(msg)
        if self.verbose:
            print("    " + msg)

    #  Phase 0: PUCT Scoring
    def puct_score(self, parent: MCTSNode, child: MCTSNode) -> float:
        """Compute the exact PUCT score for `child` under `parent`.

        PUCT(s, a) = Q(s, a) + c_puct * P(a | s) * sqrt(max(1, N(s))) / (1 + N(s, a))

        where:
            Q(s, a) = W(s,a) / N(s,a) if N(s,a) > 0 else 0.0
            N(s)    = max(1, parent.visit_count)   # avoid sqrt(0)

        The max(1, ...) on parent visits ensures that unvisited roots still
        produce a valid exploration bonus for their children.
        """
        parent_visits = max(1, parent.visit_count)
        exploration = self.c_puct * child.prior_prob * (math.sqrt(parent_visits) / (1 + child.visit_count))
        return child.q_value + exploration

    def select_best_child(self, node: MCTSNode) -> MCTSNode:
        """Return the child of `node` that maximises PUCT score.

        Raises ValueError if the node has no children (leaf node).
        """
        if not node.children:
            raise ValueError("Cannot select a child from a leaf node with no children.")
        best = max(node.children, key=lambda c: self.puct_score(node, c))
        self._log(f"SELECT  {best.state!r}  PUCT={self.puct_score(node, best):.4f}  "
                  f"(Q={best.q_value:.3f}, N={best.visit_count}, P={best.prior_prob:.2f})")
        return best

    #  Phase 1: Selection
    def select_leaf(self, root: MCTSNode) -> MCTSNode:
        """Phase 1 (Selection): Traverse down the tree from `root` using PUCT
        until reaching a leaf node (no children or terminal).

        Returns the leaf MCTSNode selected for expansion.
        """
        self._log("PHASE 1 — Selection")
        curr = root
        depth = 0
        while curr.children and not curr.is_terminal:
            curr = self.select_best_child(curr)
            depth += 1
        self._log(f"  Leaf reached at depth {depth}: {curr.state!r}")
        return curr

    #  Phase 2: Expansion
    def expand(self, node: MCTSNode, action_priors: Dict[str, float]) -> List[MCTSNode]:
        """Phase 2 (Expansion): Instantiate and attach child MCTSNode objects
        for each (state_str, prior_prob) in `action_priors`.

        Args:
            node:           The leaf node to expand.
            action_priors:  Dict mapping candidate thought strings to their
                            LLM policy prior probabilities P(a|s).

        Returns:
            The list of newly created child nodes.
        """
        self._log(f"PHASE 2 — Expansion: {len(action_priors)} children from {node.state!r}")
        new_children: List[MCTSNode] = []
        for state_str, prior_prob in action_priors.items():
            child = MCTSNode(state=state_str, prior_prob=prior_prob, parent=node)
            node.children.append(child)
            new_children.append(child)
            self._log(f"  + Child {state_str!r}  P={prior_prob:.3f}")
        return new_children

    #  Phase 3: Simulation
    def simulate_rollout(self, node: MCTSNode, rollout_evaluator: Callable[[str], float]) -> float:
        """Phase 3 (Simulation / Rollout): Evaluate `node.state` using the
        provided `rollout_evaluator` callable and clamp the scalar reward
        to [0.0, 1.0].
        """
        raw_reward = float(rollout_evaluator(node.state))
        reward = max(0.0, min(1.0, raw_reward))
        self._log(f"PHASE 3 — Simulation: {node.state!r}  raw={raw_reward:.4f}  clamped={reward:.4f}")
        return reward

    #  Phase 4: Backpropagation
    def backpropagate(self, node: MCTSNode, reward: float) -> None:
        """Phase 4 (Backpropagation): Traverse from `node` up to the root,
        incrementing `visit_count += 1` and adding `reward` to `value_sum`
        for every node along the path.

        This ensures that the Q-value of every ancestor reflects the new
        evidence from the simulated rollout.
        """
        self._log(f"PHASE 4 — Backpropagation: reward={reward:.4f}")
        curr: Optional[MCTSNode] = node
        depth = 0
        while curr is not None:
            curr.visit_count += 1
            curr.value_sum += reward
            self._log(f"  ^ depth-{depth} {curr.state!r}  N={curr.visit_count}  W={curr.value_sum:.4f}  Q={curr.q_value:.4f}")
            curr = curr.parent
            depth += 1

    #  Full MCTS Search Loop
    def run_search(
        self,
        root: MCTSNode,
        n_iterations: int,
        get_action_priors: Callable[[MCTSNode], Dict[str, float]],
        rollout_evaluator: Callable[[str], float],
        is_terminal_fn: Optional[Callable[[MCTSNode], bool]] = None,
    ) -> MCTSNode:
        """Run `n_iterations` full MCTS cycles (select → expand → simulate →
        backpropagate) from `root` and return the most-visited direct child.

        Args:
            root:                The root MCTSNode (the problem prompt).
            n_iterations:        Number of MCTS iterations (the compute budget).
            get_action_priors:   Callable that takes a leaf node and returns a
                                 dict of {thought_str: prior_prob} candidates.
            rollout_evaluator:   Callable that takes a state string and returns
                                 a scalar reward estimate in [0, 1].
            is_terminal_fn:      Optional callable that returns True if a node
                                 represents a solved / terminal state. When
                                 provided, newly expanded children are checked
                                 and marked is_terminal=True accordingly.

        Returns:
            The direct child of `root` with the highest visit count (the
            recommended next reasoning step).
        """
        self._log(f"=== MCTS run_search: {n_iterations} iterations, c_puct={self.c_puct} ===")

        for i in range(n_iterations):
            self._log(f"\n--- Iteration {i + 1}/{n_iterations} ---")

            # Phase 1: Selection
            leaf = self.select_leaf(root)

            # If the leaf is terminal, just backpropagate its cached reward
            if leaf.is_terminal:
                reward = leaf.q_value if leaf.visit_count > 0 else 1.0
                self.backpropagate(leaf, reward)
                continue

            # Phase 2: Expansion
            priors = get_action_priors(leaf)
            if not priors:
                # Dead-end node — still evaluate it rather than assuming 0.
                # A leaf with no further expansions may still represent a
                # valuable (or terminal) reasoning state.
                reward = self.simulate_rollout(leaf, rollout_evaluator)
                self.backpropagate(leaf, reward)
                continue
            new_children = self.expand(leaf, priors)

            # Mark terminal children if a terminal check is provided
            if is_terminal_fn is not None:
                for child in new_children:
                    if is_terminal_fn(child):
                        child.is_terminal = True

            # Phase 3: Simulation — evaluate the highest-prior new child.
            child_to_simulate = max(new_children, key=lambda c: c.prior_prob)
            reward = self.simulate_rollout(child_to_simulate, rollout_evaluator)

            # Phase 4: Backpropagation
            self.backpropagate(child_to_simulate, reward)

        # Return the most-visited direct child of root
        if not root.children:
            return root
        best = max(root.children, key=lambda c: c.visit_count)
        self._log(f"=== Best child (most visited): {best.state!r}  N={best.visit_count}  Q={best.q_value:.4f} ===")
        return best


# ==============================================================================
# PUCT Sensitivity Sweep — c_puct ∈ {0.5, 1.0, 1.5, 2.0, 2.5}
# ==============================================================================
def puct_sensitivity_sweep(verbose: bool = False) -> List[Dict]:
    """Demonstrate how c_puct shifts selection from exploitation to exploration.

    Setup: root with N=20, two children:
        Branch A:  Q=0.80, N=8,  P=0.35  (high exploitation value, well-visited)
        Branch B:  Q=0.50, N=4,  P=0.65  (lower Q but higher prior, less visited)
    """
    results: List[Dict] = []

    c_puct_values = [0.5, 1.0, 1.5, 2.0, 2.5]
    print("\n=== PUCT Sensitivity Sweep (c_puct variation) ===")
    print(f"{'c_puct':>8} | {'PUCT(A)':>10} {'Q(A)':>8} {'U(A)':>8} | "
          f"{'PUCT(B)':>10} {'Q(B)':>8} {'U(B)':>8} | {'Selected':>12}")
    print("-" * 95)

    for c in c_puct_values:
        engine = MCTSEngine(c_puct=c, verbose=verbose)

        root = MCTSNode(state="Root: Ergosphere Entry", visit_count=20)

        # Branch A: high empirical reward, well-visited, modest prior
        branch_a = MCTSNode(state="Branch A: Prograde Assist", prior_prob=0.35, parent=root)
        branch_a.visit_count = 8
        branch_a.value_sum = 0.80 * 8  # Q(s, A) = 0.80

        # Branch B: lower empirical reward, fewer visits, strong prior
        branch_b = MCTSNode(state="Branch B: Penrose Extraction", prior_prob=0.65, parent=root)
        branch_b.visit_count = 4
        branch_b.value_sum = 0.50 * 4  # Q(s, B) = 0.50

        root.children = [branch_a, branch_b]

        puct_a = engine.puct_score(root, branch_a)
        puct_b = engine.puct_score(root, branch_b)
        u_a = puct_a - branch_a.q_value
        u_b = puct_b - branch_b.q_value
        selected = engine.select_best_child(root)

        result = {
            "c_puct": c,
            "puct_a": puct_a, "q_a": branch_a.q_value, "u_a": u_a,
            "puct_b": puct_b, "q_b": branch_b.q_value, "u_b": u_b,
            "selected": "A" if selected is branch_a else "B",
        }
        results.append(result)

        print(f"{c:>8.1f} | {puct_a:>10.4f} {branch_a.q_value:>8.4f} {u_a:>8.4f} | "
              f"{puct_b:>10.4f} {branch_b.q_value:>8.4f} {u_b:>8.4f} | "
              f"{'Branch A *' if selected is branch_a else 'Branch B *':>12}")

    # Verify the crossover behaviour
    assert results[0]["selected"] == "A", "At c_puct=0.5, exploitation should favour Branch A"
    assert results[-1]["selected"] == "B", "At c_puct=2.5, exploration should favour Branch B"
    print("[OK] PUCT sensitivity sweep: exploitation -> exploration crossover confirmed.")
    return results


# ==============================================================================
# Self-checks: regression tests for edge cases and invariants
# ==============================================================================
def _self_checks() -> None:
    """Comprehensive tests beyond the basic verification harness."""
    engine = MCTSEngine(c_puct=1.5)

    # 1. Zero-visit node: Q should be 0.0, PUCT is pure exploration
    root = MCTSNode(state="R", visit_count=10)
    unvisited = MCTSNode(state="U", prior_prob=0.6, parent=root)
    root.children = [unvisited]
    assert unvisited.q_value == 0.0, "Unvisited Q must be 0.0"
    expected_puct = 0.0 + 1.5 * 0.6 * (math.sqrt(10) / 1)
    assert abs(engine.puct_score(root, unvisited) - expected_puct) < 1e-9

    # 2. Backpropagation increments all ancestors
    grandparent = MCTSNode(state="GP")
    parent = MCTSNode(state="P", parent=grandparent)
    grandparent.children = [parent]
    child = MCTSNode(state="C", parent=parent)
    parent.children = [child]
    engine.backpropagate(child, 0.8)
    assert child.visit_count == 1 and parent.visit_count == 1 and grandparent.visit_count == 1
    assert abs(child.value_sum - 0.8) < 1e-9
    assert abs(grandparent.q_value - 0.8) < 1e-9

    # 3. Multiple backpropagations average correctly
    engine.backpropagate(child, 0.4)
    assert child.visit_count == 2
    assert abs(child.q_value - 0.6) < 1e-9  # (0.8 + 0.4) / 2

    # 4. Expansion creates correct parent links and priors
    leaf = MCTSNode(state="Leaf")
    priors = {"A": 0.5, "B": 0.3, "C": 0.2}
    new_children = engine.expand(leaf, priors)
    assert len(new_children) == 3
    assert all(c.parent is leaf for c in new_children)
    assert all(c.visit_count == 0 for c in new_children)
    assert abs(new_children[0].prior_prob - 0.5) < 1e-9

    # 5. Simulate clamps rewards to [0, 1]
    assert engine.simulate_rollout(MCTSNode(state="X"), lambda _: -0.5) == 0.0
    assert engine.simulate_rollout(MCTSNode(state="X"), lambda _: 1.7) == 1.0
    assert abs(engine.simulate_rollout(MCTSNode(state="X"), lambda _: 0.42) - 0.42) < 1e-9

    # 6. select_leaf traverses to the deepest unexpanded node
    r = MCTSNode(state="R", visit_count=5)
    c1 = MCTSNode(state="C1", prior_prob=0.9, parent=r, visit_count=3, value_sum=2.4)
    c2 = MCTSNode(state="C2", prior_prob=0.1, parent=r, visit_count=2, value_sum=0.4)
    r.children = [c1, c2]
    gc = MCTSNode(state="GC", prior_prob=0.5, parent=c1, visit_count=1, value_sum=0.9)
    c1.children = [gc]
    # C1 -> GC is a leaf (no children), so select_leaf should reach GC
    leaf = engine.select_leaf(r)
    assert leaf.state == "GC", f"Expected GC, got {leaf.state}"

    # 7. select_best_child raises on childless node
    try:
        engine.select_best_child(MCTSNode(state="Empty"))
        raise AssertionError("Expected ValueError for childless node")
    except ValueError:
        pass

    # 8. Invalid c_puct is rejected
    try:
        MCTSEngine(c_puct=-1.0)
        raise AssertionError("Expected ValueError for negative c_puct")
    except ValueError:
        pass

    # 9. get_trajectory reconstructs the full path
    r = MCTSNode(state="Root")
    a = MCTSNode(state="Step A", parent=r)
    b = MCTSNode(state="Step B", parent=a)
    assert b.get_trajectory() == ["Root", "Step A", "Step B"]

    # 10. run_search returns the most-visited child with meaningful Q-values
    r = MCTSNode(state="Prompt")
    action_fn = lambda node: {"Good": 0.7, "Bad": 0.3} if not node.children else {}
    value_fn = lambda s: 0.9 if "Good" in s else 0.2
    best = engine.run_search(r, n_iterations=10, get_action_priors=action_fn, rollout_evaluator=value_fn)
    assert best.visit_count > 0, "run_search must visit the returned child"
    # The highest-prior child "Good" (P=0.7) is simulated first and gets reward 0.9.
    # Dead-end re-visits of "Good" and "Bad" now evaluate properly instead of
    # backpropagating 0.0, so Q-values should reflect the evaluator's scores.
    good_child = [c for c in r.children if "Good" in c.state][0]
    bad_child = [c for c in r.children if "Bad" in c.state][0]
    assert good_child.q_value > bad_child.q_value, \
        f"Good child Q={good_child.q_value:.3f} should exceed Bad child Q={bad_child.q_value:.3f}"
    assert good_child.q_value > 0.5, \
        f"Good child Q={good_child.q_value:.3f} should reflect evaluator score 0.9, not be washed out"

    # 11. run_search dead-end evaluation: a leaf with no priors still gets evaluated
    r2 = MCTSNode(state="DeadEndTest")
    # Proposer gives one child on first call, then no priors (dead end)
    call_count = [0]
    def deadend_priors(node: MCTSNode) -> Dict[str, float]:
        if node.state == "DeadEndTest" and call_count[0] == 0:
            call_count[0] += 1
            return {"Valuable Leaf": 1.0}
        return {}
    deadend_eval = lambda s: 0.85 if "Valuable" in s else 0.1
    best2 = engine.run_search(r2, n_iterations=5, get_action_priors=deadend_priors, rollout_evaluator=deadend_eval)
    assert abs(best2.q_value - 0.85) < 1e-9, \
        f"Dead-end leaf should have Q=0.85 from evaluator, got Q={best2.q_value:.3f}"

    # 12. run_search with is_terminal_fn marks solved nodes
    r3 = MCTSNode(state="TerminalTest")
    term_priors = lambda n: {"GOAL": 0.8, "Other": 0.2} if n.state == "TerminalTest" and not n.children else {}
    term_eval = lambda s: 0.99 if "GOAL" in s else 0.3
    term_check = lambda n: "GOAL" in n.state
    best3 = engine.run_search(r3, n_iterations=8, get_action_priors=term_priors,
                              rollout_evaluator=term_eval, is_terminal_fn=term_check)
    goal_node = [c for c in r3.children if "GOAL" in c.state][0]
    assert goal_node.is_terminal, "is_terminal_fn should have marked the GOAL node"

    print("[OK] 12 self-checks passed (zero-visit, backprop accumulation, expansion links, "
          "clamping, traversal, error handling, trajectory, run_search Q-values, "
          "dead-end evaluation, terminal marking).")


# ==============================================================================
# Full MCTS demo: multi-iteration search on a small reasoning tree
# ==============================================================================
def run_mcts_demo(verbose: bool = False) -> None:
    """Run a complete MCTS search on a small navigation problem to demonstrate
    all four phases working together across multiple iterations."""

    print("\n=== Full MCTS Search Demo (12 iterations) ===")

    # Simulated LLM proposer: returns candidate thoughts with policy priors
    action_map: Dict[str, Dict[str, float]] = {
        "Root: Navigate Sagittarius A* Ergosphere": {
            "Path A: Prograde frame-dragging slingshot": 0.50,
            "Path B: Retrograde Penrose energy extraction": 0.35,
            "Path C: Direct radial plunge (DANGER)": 0.15,
        },
        "Path A: Prograde frame-dragging slingshot": {
            "A1: Lock onto stable circular orbit at r=3M": 0.60,
            "A2: Accelerate through ISCO boundary": 0.40,
        },
        "Path B: Retrograde Penrose energy extraction": {
            "B1: Split payload at ergosphere boundary": 0.55,
            "B2: Full retrograde deceleration burn": 0.45,
        },
        "Path C: Direct radial plunge (DANGER)": {
            "C1: Emergency braking at r=2M": 0.70,
            "C2: Accept tidal spaghettification": 0.30,
        },
    }

    # Simulated PRM / value model
    value_map: Dict[str, float] = {
        "Path A: Prograde frame-dragging slingshot": 0.75,
        "Path B: Retrograde Penrose energy extraction": 0.65,
        "Path C: Direct radial plunge (DANGER)": 0.15,
        "A1: Lock onto stable circular orbit at r=3M": 0.92,
        "A2: Accelerate through ISCO boundary": 0.45,
        "B1: Split payload at ergosphere boundary": 0.70,
        "B2: Full retrograde deceleration burn": 0.50,
        "C1: Emergency braking at r=2M": 0.30,
        "C2: Accept tidal spaghettification": 0.05,
    }

    def get_priors(node: MCTSNode) -> Dict[str, float]:
        return action_map.get(node.state, {})

    def evaluate(state: str) -> float:
        return value_map.get(state, 0.3)

    engine = MCTSEngine(c_puct=1.5, verbose=verbose)
    root = MCTSNode(state="Root: Navigate Sagittarius A* Ergosphere")

    best = engine.run_search(root, n_iterations=12, get_action_priors=get_priors, rollout_evaluator=evaluate)

    print(f"Root visits after search: N={root.visit_count}")
    print("Direct children of root:")
    for child in root.children:
        print(f"  {child.state:55s}  N={child.visit_count:3d}  Q={child.q_value:.4f}  P={child.prior_prob:.2f}")

    print(f"\nRecommended path (most visited): {best.state}")
    print(f"  Visit count: {best.visit_count},  Q-value: {best.q_value:.4f}")

    # The safe prograde path should dominate over the dangerous plunge
    assert "Prograde" in best.state or "Penrose" in best.state, \
        f"MCTS should not recommend the dangerous plunge path, got: {best.state}"
    print("[OK] MCTS demo: safe navigation path selected over dangerous plunge.")


# ==============================================================================
# Verification Harness for Part 2 
# ==============================================================================
if __name__ == "__main__":
    trace_on = "--trace" in sys.argv

    print("=== Subsystem 07 (Part 2): MCTS & PUCT Protocol Verification ===")

    # --- Original starter verification (preserved for compatibility) ---
    engine = MCTSEngine(c_puct=1.5, verbose=trace_on)
    root = MCTSNode(state="Root: Sagittarius A* Ergosphere Geodesic Entry", visit_count=16)

    branch_a = MCTSNode(state="Branch A: Prograde Frame-Dragging Assist", prior_prob=0.50, parent=root)
    branch_a.visit_count = 5
    branch_a.value_sum = 0.75 * 5  # Q(s, A) = 0.75

    branch_b = MCTSNode(state="Branch B: Retrograde Penrose Extraction", prior_prob=0.40, parent=root)
    branch_b.visit_count = 1
    branch_b.value_sum = 0.55 * 1  # Q(s, B) = 0.55

    root.children = [branch_a, branch_b]

    puct_a = engine.puct_score(root, branch_a)
    puct_b = engine.puct_score(root, branch_b)
    selected = engine.select_best_child(root)

    print(f"Branch A -> Q={branch_a.q_value:.2f}, N={branch_a.visit_count}, P={branch_a.prior_prob:.2f} | PUCT = {puct_a:.4f}")
    print(f"Branch B -> Q={branch_b.q_value:.2f}, N={branch_b.visit_count}, P={branch_b.prior_prob:.2f} | PUCT = {puct_b:.4f}")
    print(f"Selected Next Node for Expansion: {selected.state}")

    # --- Hand-calculated reference values ---
    # Branch A: Q=0.75, U = 1.5 * 0.50 * sqrt(16) / (1+5) = 1.5 * 0.50 * 4 / 6 = 0.50
    #           PUCT(A) = 0.75 + 0.50 = 1.25
    # Branch B: Q=0.55, U = 1.5 * 0.40 * sqrt(16) / (1+1) = 1.5 * 0.40 * 4 / 2 = 1.20
    #           PUCT(B) = 0.55 + 1.20 = 1.75
    assert abs(puct_a - 1.25) < 1e-6, f"Expected PUCT(A)=1.25, got {puct_a}"
    assert abs(puct_b - 1.75) < 1e-6, f"Expected PUCT(B)=1.75, got {puct_b}"
    assert selected is branch_b, "MCTS failed to select under-explored high-PUCT Branch B!"

    # --- Test Backpropagation ---
    engine.backpropagate(branch_b, reward=0.95)
    assert branch_b.visit_count == 2, f"Expected N(B)=2, got {branch_b.visit_count}"
    assert root.visit_count == 17, f"Expected N(root)=17, got {root.visit_count}"
    assert abs(branch_b.value_sum - (0.55 + 0.95)) < 1e-9, "Branch B value_sum incorrect after backprop"
    assert abs(branch_b.q_value - (0.55 + 0.95) / 2) < 1e-9, "Branch B Q-value incorrect after backprop"
    print("[OK] Part 2 (Communications & Protocol Officer) verification passed.")

    # --- Extended verification suite ---
    _self_checks()
    puct_sensitivity_sweep(verbose=trace_on)
    run_mcts_demo(verbose=trace_on)
