"""
Mission 07 — Part 1: Systems Architect (Lead Engineer)
Tree-of-Thoughts (ToT) Breadth-First Beam Search & Depth-First Backtracking Solver

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-07-SGR (Sagittarius A* Supermassive Black Hole)
Subsystem 07: Gravitational Search Horizon & Process Reward Evaluator
Officer: Abdul Jalil Memon - Squadron Goodfellow

AI assistance: Claude completed the starter, wrote the self-checks and the
Game-of-24 benchmark (author review not yet recorded; edit this line after you
have reviewed the code).
Run: python tot_solver.py            (verification + self-checks + benchmark)
     python tot_solver.py --trace    (also print the step-by-step search trace)

Briefing requirements covered
-----------------------------
1. ThoughtNode stores state, depth, step_score, cumulative_score, parent,
   children, plus get_trajectory() (root -> node).
2. bfs_beam_search(): frontier of at most B = beam_width nodes per depth,
   children below prune_threshold are pruned, and expansion stops once
   expansion_count >= max_expansions. Returns the best terminal / deepest node.
3. dfs_backtrack_search(): follows the highest-scoring child first and
   backtracks chronologically on pruned children and dead ends, under the
   same hard budget.

Budget unit: one "expansion" = one candidate thought generated AND scored by
evaluator_fn (i.e. one value-model call). The budget is never exceeded.

Starter behaviour kept
----------------------
Same class names, constructor arguments, method signatures and the original
verification harness (both searches still reach [GOAL] in 5/12 expansions).
cumulative_score is still the min-link (weakest step) of the trajectory.

Defects found in the starter draft and fixed (see _self_checks below)
--------------------------------------------------------------------
* "Deepest node wins" returned a weak deep branch (score 0.50) instead of a
  solved goal one level higher. Searches now accept an optional
  is_terminal_fn: terminal (solved) nodes are never expanded further, always
  outrank non-terminal nodes, and stop the search early to save compute.
* DFS compared ABSOLUTE depth with max_depth, so a root with depth != 0 was
  never searched. Depth limits are now relative to the root in both searches.
* Re-running a search on an already-expanded root silently duplicated its
  children. This now raises ValueError (pass a fresh root).
* max_expansions / beam_width / prune_threshold are now validated.
* A meaningless loop guard in the DFS starter was removed.

Added: per-search telemetry (pruned / backtracks / terminal_found) and an
optional event trace, used by the experimental report in mission-07-doc.md.
Pure standard library: no external framework.
"""

import hashlib
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class ThoughtNode:
    """Represents a discrete semantic reasoning step z_t in a Tree-of-Thoughts."""
    state: str
    depth: int = 0
    step_score: float = 1.0
    cumulative_score: float = 1.0
    parent: Optional["ThoughtNode"] = None
    children: List["ThoughtNode"] = field(default_factory=list)
    is_pruned: bool = False
    is_terminal: bool = False

    def add_child(self, child_state: str, step_score: float) -> "ThoughtNode":
        """Creates and attaches a child ThoughtNode, inheriting minimum-link cumulative score."""
        child = ThoughtNode(
            state=child_state,
            depth=self.depth + 1,
            step_score=step_score,
            cumulative_score=min(self.cumulative_score, step_score),
            parent=self,
        )
        self.children.append(child)
        return child

    def get_trajectory(self) -> List[str]:
        """Reconstructs the full chain of thoughts [z_0, z_1, ..., z_t] from root to this node."""
        path: List[str] = []
        curr: Optional[ThoughtNode] = self
        while curr is not None:
            path.append(curr.state)
            curr = curr.parent
        return list(reversed(path))

    def __repr__(self) -> str:  # parent/children would recurse forever in the dataclass repr
        return (f"ThoughtNode(depth={self.depth}, step={self.step_score:.2f}, "
                f"cum={self.cumulative_score:.2f}, terminal={self.is_terminal}, state={self.state!r})")


GeneratorFn = Callable[[ThoughtNode], List[str]]
EvaluatorFn = Callable[[str], float]
TerminalFn = Callable[[ThoughtNode], bool]


class TreeOfThoughtsSolver:
    """
    Executes deliberate System 2 Tree-of-Thoughts search under a strict inference compute budget.
    Supports both ToT-BFS (Beam Search of width B) and ToT-DFS (Chronological Backtracking).
    """

    def __init__(self, max_expansions: int = 16, beam_width: int = 2, prune_threshold: float = 0.45,
                 verbose: bool = False):
        if isinstance(max_expansions, bool) or not isinstance(max_expansions, int) or max_expansions < 0:
            raise ValueError(f"max_expansions must be an int >= 0, got {max_expansions!r}")
        if isinstance(beam_width, bool) or not isinstance(beam_width, int) or beam_width < 1:
            raise ValueError(f"beam_width must be an int >= 1, got {beam_width!r}")
        if not 0.0 <= prune_threshold <= 1.0:
            raise ValueError(f"prune_threshold must be in [0, 1], got {prune_threshold!r}")
        self.max_expansions = max_expansions
        self.beam_width = beam_width
        self.prune_threshold = prune_threshold
        self.verbose = verbose
        self.expansion_count = 0
        self.stats: Dict[str, object] = {}
        self.trace: List[str] = []

    # ------------------------------------------------------------------ helpers
    def _reset(self, root: ThoughtNode, method: str) -> None:
        if root.children:
            raise ValueError("root already has children; pass a fresh ThoughtNode for each search")
        self.expansion_count = 0
        self.trace = []
        self.stats = {"method": method, "pruned": 0, "backtracks": 0, "terminal_found": False,
                      "budget_exhausted": False}

    def _log(self, event: str) -> None:
        self.trace.append(event)
        if self.verbose:
            print("    " + event)

    @property
    def budget_left(self) -> bool:
        return self.expansion_count < self.max_expansions

    def _expand(self, node: ThoughtNode, generator_fn: GeneratorFn, evaluator_fn: EvaluatorFn,
                is_terminal_fn: Optional[TerminalFn]) -> List[ThoughtNode]:
        """Generate + score children of `node` within budget. Returns the non-pruned children."""
        survivors: List[ThoughtNode] = []
        for thought_str in generator_fn(node):
            if not self.budget_left:
                self.stats["budget_exhausted"] = True
                self._log(f"BUDGET  {self.expansion_count}/{self.max_expansions} exhausted at depth {node.depth}")
                break
            self.expansion_count += 1
            score = float(evaluator_fn(thought_str))
            child = node.add_child(thought_str, score)
            if score < self.prune_threshold:
                child.is_pruned = True
                self.stats["pruned"] += 1
                self._log(f"PRUNE   d={child.depth} v={score:.2f} < {self.prune_threshold:.2f} | {thought_str}")
                continue
            if is_terminal_fn is not None and is_terminal_fn(child):
                child.is_terminal = True
            self._log(f"EXPAND  d={child.depth} v={score:.2f} cum={child.cumulative_score:.2f}"
                      f"{' TERMINAL' if child.is_terminal else ''} | {thought_str}")
            survivors.append(child)
        return survivors

    @staticmethod
    def _rank(node: ThoughtNode, root: ThoughtNode) -> Tuple[bool, int, float, float]:
        """Best-node ordering: solved > deeper > higher min-link score > higher last-step score."""
        return (node.is_terminal, node.depth - root.depth, node.cumulative_score, node.step_score)

    # ------------------------------------------------------------------ ToT-BFS
    def bfs_beam_search(
        self,
        root: ThoughtNode,
        generator_fn: GeneratorFn,
        evaluator_fn: EvaluatorFn,
        max_depth: int = 3,
        is_terminal_fn: Optional[TerminalFn] = None,
    ) -> ThoughtNode:
        """
        Breadth-First Beam Search (ToT-BFS): expand every node of the beam, keep the top-B
        surviving children per depth, stop at max_depth, an empty frontier, the budget, or
        (if is_terminal_fn is given) the first depth layer containing a solved node.
        """
        self._reset(root, f"ToT-BFS(B={self.beam_width})")
        beam: List[ThoughtNode] = [root]
        best_node: ThoughtNode = root

        for _ in range(max_depth):
            candidates: List[ThoughtNode] = []
            for node in beam:
                if not self.budget_left:
                    self.stats["budget_exhausted"] = True
                    break
                candidates.extend(self._expand(node, generator_fn, evaluator_fn, is_terminal_fn))

            if not candidates:
                self._log("FRONTIER empty -> stop")
                break

            candidates.sort(key=lambda c: (c.is_terminal, c.cumulative_score, c.step_score), reverse=True)
            for dropped in candidates[self.beam_width:]:
                self._log(f"BEAM-CUT d={dropped.depth} cum={dropped.cumulative_score:.2f} | {dropped.state}")
            beam = candidates[: self.beam_width]
            if self._rank(beam[0], root) > self._rank(best_node, root):
                best_node = beam[0]
            if best_node.is_terminal:
                self.stats["terminal_found"] = True
                break
            # Solved nodes are never expanded further.
            beam = [n for n in beam if not n.is_terminal]

        return best_node

    # ------------------------------------------------------------------ ToT-DFS
    def dfs_backtrack_search(
        self,
        root: ThoughtNode,
        generator_fn: GeneratorFn,
        evaluator_fn: EvaluatorFn,
        max_depth: int = 3,
        is_terminal_fn: Optional[TerminalFn] = None,
    ) -> ThoughtNode:
        """
        Depth-First Backtracking Search (ToT-DFS): always descend into the highest-scoring
        surviving child; on a pruned child / dead end / depth limit, backtrack to the most
        recent ancestor with an untried sibling. Stops on the first solved node (if
        is_terminal_fn is given) or when the budget is spent.
        """
        self._reset(root, "ToT-DFS")
        best_node: ThoughtNode = root

        def _dfs(node: ThoughtNode) -> bool:
            """Returns True when a terminal node was found (unwinds the whole search)."""
            nonlocal best_node
            if self._rank(node, root) > self._rank(best_node, root):
                best_node = node
            if node.is_terminal:
                self.stats["terminal_found"] = True
                return True
            if node.depth - root.depth >= max_depth or not self.budget_left:
                return False

            children = self._expand(node, generator_fn, evaluator_fn, is_terminal_fn)
            children.sort(key=lambda c: (c.is_terminal, c.step_score), reverse=True)
            for child in children:
                if _dfs(child):
                    return True
            if node is not root:
                self.stats["backtracks"] += 1
                self._log(f"BACKTRACK from d={node.depth} | {node.state}")
            return False

        _dfs(root)
        return best_node


# ==============================================================================
# Self-checks: regression tests for the defects listed in the module docstring
# ==============================================================================
def _self_checks() -> None:
    tree = {"R": ["A", "B"], "A": ["GOAL"], "B": ["B2"], "B2": ["B3"]}
    vals = {"A": 0.90, "B": 0.60, "GOAL": 0.99, "B2": 0.50, "B3": 0.50}
    gen = lambda n: tree.get(n.state, [])
    ev = lambda s: vals[s]
    goal = lambda n: n.state == "GOAL"
    s = TreeOfThoughtsSolver(max_expansions=20)

    # 1. A solved goal at depth 2 must beat a weak branch that reaches depth 3.
    assert s.bfs_beam_search(ThoughtNode("R"), gen, ev, 3, goal).state == "GOAL"
    assert s.dfs_backtrack_search(ThoughtNode("R"), gen, ev, 3, goal).state == "GOAL"
    assert s.expansion_count == 3, "DFS should stop as soon as the goal is found"

    # 2. Depth limit is relative to the root.
    deep_root = ThoughtNode("R", depth=5)
    assert s.dfs_backtrack_search(deep_root, gen, ev, 3, goal).state == "GOAL"

    # 3. Re-using an expanded root is rejected instead of duplicating children.
    try:
        s.bfs_beam_search(deep_root, gen, ev, 3)
        raise AssertionError("expected ValueError for reused root")
    except ValueError:
        pass

    # 4. Hard budget is respected exactly, for both searches and any budget.
    wide = lambda n: [f"{n.state}.{i}" for i in range(5)]
    for budget in range(0, 30):
        t = TreeOfThoughtsSolver(max_expansions=budget, beam_width=3, prune_threshold=0.0)
        t.bfs_beam_search(ThoughtNode("x"), wide, lambda _: 0.7, 4)
        assert t.expansion_count == min(budget, 5 + 15 + 15 + 15), (budget, t.expansion_count)
        t.dfs_backtrack_search(ThoughtNode("x"), wide, lambda _: 0.7, 4)
        assert t.expansion_count <= budget

    # 5. Beam never holds more than B nodes per depth.
    t = TreeOfThoughtsSolver(max_expansions=100, beam_width=2, prune_threshold=0.0)
    r = ThoughtNode("x")
    t.bfs_beam_search(r, wide, lambda _: 0.7, 3)
    expanded_d1 = [c for c in r.children if c.children]
    assert len(expanded_d1) == 2

    # 6. DFS backtracks: the top-ranked first step dies one level later, the sibling succeeds.
    tree2 = {"R": ["good-looking", "plain"], "good-looking": ["bad"], "plain": ["GOAL"]}
    vals2 = {"good-looking": 0.95, "plain": 0.60, "bad": 0.10, "GOAL": 0.90}
    t = TreeOfThoughtsSolver(max_expansions=10)
    best = t.dfs_backtrack_search(ThoughtNode("R"), lambda n: tree2.get(n.state, []),
                                  lambda s_: vals2[s_], 3, goal)
    assert best.state == "GOAL" and t.stats["backtracks"] == 1 and t.stats["pruned"] == 1

    # 7. Pruned children are flagged and never chosen; cumulative score is the min link.
    r = ThoughtNode("R")
    TreeOfThoughtsSolver(max_expansions=10).bfs_beam_search(r, lambda n: tree2.get(n.state, []),
                                                            lambda s_: vals2[s_], 3, goal)
    bad = r.children[0].children[0]
    assert bad.is_pruned and abs(r.children[1].children[0].cumulative_score - 0.60) < 1e-9

    # 8. Invalid configuration is rejected.
    for kwargs in ({"max_expansions": -1}, {"beam_width": 0}, {"prune_threshold": 1.5}):
        try:
            TreeOfThoughtsSolver(**kwargs)
            raise AssertionError(f"expected ValueError for {kwargs}")
        except ValueError:
            pass
    print("[OK] 8 self-checks passed (goal preference, relative depth, root reuse, budget, "
          "beam width, backtracking, pruning, config validation).")


# ==============================================================================
# Benchmark: real Game-of-24 search with a noisy value model
# ==============================================================================
# The generator enumerates every legal arithmetic step (exact Fractions). The
# evaluator stands in for an LLM "sure / likely / impossible" value prompt: it
# knows whether the remaining numbers can still reach 24, but adds deterministic
# +/-0.35 noise (SHA-256 of the thought), so it sometimes prunes a good branch
# and sometimes trusts a bad one. The final step is checked exactly (verifiable).

def _fmt(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def _parse_remaining(state: str) -> Tuple[Fraction, ...]:
    inside = state[state.rindex("[") + 1: state.rindex("]")]
    return tuple(Fraction(tok) for tok in inside.split(",") if tok.strip())


_SOLVABLE: Dict[Tuple[Fraction, ...], bool] = {}


def _solvable(nums: Tuple[Fraction, ...]) -> bool:
    key = tuple(sorted(nums))
    if key not in _SOLVABLE:
        if len(key) == 1:
            _SOLVABLE[key] = key[0] == 24
        else:
            _SOLVABLE[key] = any(_solvable(rest) for _, rest in _successors(key))
    return _SOLVABLE[key]


def _successors(nums: Tuple[Fraction, ...]):
    """All (description, remaining) pairs from combining two numbers with + - * /."""
    seen = set()
    for i, j in combinations(range(len(nums)), 2):
        a, b = nums[i], nums[j]
        rest = [nums[k] for k in range(len(nums)) if k not in (i, j)]
        ops = [(f"{_fmt(a)} + {_fmt(b)}", a + b), (f"{_fmt(a)} * {_fmt(b)}", a * b),
               (f"{_fmt(a)} - {_fmt(b)}", a - b), (f"{_fmt(b)} - {_fmt(a)}", b - a)]
        if b != 0:
            ops.append((f"{_fmt(a)} / {_fmt(b)}", a / b))
        if a != 0:
            ops.append((f"{_fmt(b)} / {_fmt(a)}", b / a))
        for desc, val in ops:
            remaining = tuple(sorted(rest + [val]))
            if remaining in seen:  # duplicate state from this parent -> skip
                continue
            seen.add(remaining)
            yield f"{desc} = {_fmt(val)}", remaining


def game24_generator(node: ThoughtNode) -> List[str]:
    nums = _parse_remaining(node.state)
    if len(nums) <= 1:
        return []
    return [f"Step {node.depth + 1}: {desc} (Remaining: [{', '.join(_fmt(x) for x in rem)}])"
            for desc, rem in _successors(nums)]


def game24_value_model(thought: str, noise: float = 0.35) -> float:
    nums = _parse_remaining(thought)
    if len(nums) == 1:
        return 1.0 if nums[0] == 24 else 0.0
    base = 0.75 if _solvable(nums) else 0.30
    h = int(hashlib.sha256(thought.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF  # in [0, 1]
    return max(0.0, min(1.0, base + noise * (2 * h - 1)))


def game24_is_goal(node: ThoughtNode) -> bool:
    nums = _parse_remaining(node.state)
    return len(nums) == 1 and nums[0] == 24


GAME24_PUZZLES = [
    [4, 9, 10, 13], [1, 2, 3, 4], [3, 3, 8, 8], [1, 5, 5, 5], [1, 3, 4, 6], [4, 4, 10, 10],
    [3, 3, 7, 7], [2, 3, 5, 12], [1, 4, 5, 6], [6, 6, 6, 6], [2, 2, 6, 6], [3, 4, 5, 6],
]


def run_benchmark(budgets=(10, 25, 50, 100, 200), beams=(1, 2, 4), threshold: float = 0.45) -> None:
    puzzles = [p for p in GAME24_PUZZLES if _solvable(tuple(Fraction(x) for x in p))]
    print(f"\n=== Game-of-24 benchmark: {len(puzzles)} solvable puzzles, depth 3, "
          f"prune_threshold={threshold}, value-model noise +/-0.35 ===")
    print("solved/total (mean expansions used)")
    configs = [(f"ToT-BFS B={b}", "bfs", b) for b in beams] + [("ToT-DFS", "dfs", 1)]
    header = f"{'method':<14}" + "".join(f"{'budget ' + str(b):>16}" for b in budgets)
    print(header)
    print("-" * len(header))
    for label, method, beam in configs:
        row = f"{label:<14}"
        for budget in budgets:
            solved, used = 0, 0
            for p in puzzles:
                solver = TreeOfThoughtsSolver(max_expansions=budget, beam_width=beam, prune_threshold=threshold)
                root = ThoughtNode(f"Prompt: make 24 from [{', '.join(map(str, p))}]")
                search = solver.bfs_beam_search if method == "bfs" else solver.dfs_backtrack_search
                best = search(root, game24_generator, game24_value_model, 3, game24_is_goal)
                solved += best.is_terminal
                used += solver.expansion_count
            row += f"{f'{solved}/{len(puzzles)} ({used / len(puzzles):.0f})':>16}"
        print(row)


# ==============================================================================
# Verification Harness for Part 1 (Systems Architect)
# ==============================================================================
if __name__ == "__main__":
    trace_on = "--trace" in sys.argv
    print("=== Subsystem 07 (Part 1): Tree-of-Thoughts Solver Verification ===")

    # Mock Sagittarius A* 24-Vector Thruster Synthesis Tree
    MOCK_BRANCHES = {
        "Prompt: Synthesize 24.0 km/s from [4, 9, 10, 13]": [
            "Step 1A: 13 - 9 = 4 (Remaining: [4, 4, 10]) [VALID]",
            "Step 1B: 10 + 13 = 23 (Remaining: [4, 9, 23]) [DEAD-END]",
        ],
        "Step 1A: 13 - 9 = 4 (Remaining: [4, 4, 10]) [VALID]": [
            "Step 2A: 10 - 4 = 6 (Remaining: [4, 6]) [OPTIMAL]",
            "Step 2B: 4 + 4 = 8 (Remaining: [8, 10]) [DEAD-END]",
        ],
        "Step 2A: 10 - 4 = 6 (Remaining: [4, 6]) [OPTIMAL]": [
            "Step 3A: 4 * 6 = 24.0 km/s -> Escape Geodesic Locked! [GOAL]",
        ],
    }

    def mock_generator(node: ThoughtNode) -> List[str]:
        return MOCK_BRANCHES.get(node.state, [])

    def mock_evaluator(thought: str) -> float:
        if "[GOAL]" in thought:
            return 0.98
        if "[OPTIMAL]" in thought:
            return 0.92
        if "[VALID]" in thought:
            return 0.85
        return 0.25  # Dead-end branch below prune_threshold

    solver = TreeOfThoughtsSolver(max_expansions=12, beam_width=2, prune_threshold=0.45, verbose=trace_on)

    root_bfs = ThoughtNode("Prompt: Synthesize 24.0 km/s from [4, 9, 10, 13]")
    best_bfs = solver.bfs_beam_search(root_bfs, mock_generator, mock_evaluator, max_depth=3)
    print(f"[ToT-BFS] Expansions Used: {solver.expansion_count}/{solver.max_expansions} | "
          f"Pruned: {solver.stats['pruned']}")
    print(f"[ToT-BFS] Best Terminal Score: {best_bfs.cumulative_score:.2f} (last step {best_bfs.step_score:.2f})")
    print(f"[ToT-BFS] Winning Trajectory: {' -> '.join(best_bfs.get_trajectory())}")

    root_dfs = ThoughtNode("Prompt: Synthesize 24.0 km/s from [4, 9, 10, 13]")
    best_dfs = solver.dfs_backtrack_search(root_dfs, mock_generator, mock_evaluator, max_depth=3)
    print(f"[ToT-DFS] Expansions Used: {solver.expansion_count}/{solver.max_expansions} | "
          f"Pruned: {solver.stats['pruned']} | Backtracks: {solver.stats['backtracks']}")
    print(f"[ToT-DFS] Best Terminal Score: {best_dfs.cumulative_score:.2f} (last step {best_dfs.step_score:.2f})")
    print(f"[ToT-DFS] Winning Trajectory: {' -> '.join(best_dfs.get_trajectory())}")

    assert "[GOAL]" in best_bfs.state, "ToT-BFS failed to reach [GOAL] state!"
    assert "[GOAL]" in best_dfs.state, "ToT-DFS failed to reach [GOAL] state!"
    assert solver.expansion_count <= solver.max_expansions
    print("[OK] Part 1 (Systems Architect) verification passed.")

    _self_checks()
    run_benchmark()
