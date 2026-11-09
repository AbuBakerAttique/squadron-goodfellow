"""
Mission 06 — Part 3: Data & Payload Specialist
MDP Trajectory Logger & Empirical Return Evaluator

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
Officer: Abubaker Attique — Squadron Goodfellow

AI assistance: Claude drafted the implementation and the self-checks (author
review not yet recorded; edit this line after you have reviewed the code).
Run: python 03_MDP_Trajectory_Logger.py
Use another jump log: python 03_MDP_Trajectory_Logger.py --jumps jumps.csv
     (CSV header: state,action,next_state)

What this file does (briefing, Part 3):
1. TrajectoryLogger records one episode as tau = (s0, a0, r0, s1, a1, r1, ..., sT).
2. discounted_return() computes G_0 = sum_t gamma^t * r_t with gamma = 0.95.
3. TransitionModel turns a log of past jumps (s, a, s') into the empirical
   transition probabilities P(s' | s, a) = N(s, a, s') / N(s, a).

What is real and what is not:
* The briefing mentions "a provided historical dataset of past jumps", but no
  such file is in the course repository. JUMP_LOG below is a MOCK, written by
  hand so that every probability can be checked by counting. Replace it with
  the real data through --jumps (or load_jumps_csv) when it is available.
* The two demo episodes at the end use made-up rewards for illustration only.
* The empirical P(s' | s, a) is a maximum-likelihood estimate. A pair (s, a)
  that never appears in the log has NO estimate (KeyError), not probability 0.
* The briefing writes the sum up to t = T, while a trajectory that ends in s_T
  has T rewards (r_0 .. r_{T-1}). discounted_return() sums every reward it is
  given, which is what the master test (four rewards) expects.
"""
import argparse
import csv
import json
import math
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

GAMMA = 0.95
LINE = "=" * 74


# --------------------------------------------------------------------------
# 2. Discounted return
# --------------------------------------------------------------------------
def _check_gamma(gamma: float) -> float:
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)):
        raise TypeError("gamma must be a number")
    if not math.isfinite(gamma) or not 0.0 <= gamma <= 1.0:
        raise ValueError(f"gamma must be in [0, 1], got {gamma!r}")
    return float(gamma)


def _check_rewards(rewards: Iterable[float]) -> List[float]:
    out = []
    for r in rewards:
        if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r):
            raise ValueError(f"rewards must be finite numbers, got {r!r}")
        out.append(float(r))
    if not out:
        raise ValueError("a trajectory needs at least one reward")
    return out


def discounted_return(rewards: Sequence[float], gamma: float = GAMMA) -> float:
    """Empirical discounted return G_0 = sum_{t=0}^{T-1} gamma^t * r_t.

    Evaluated backwards (G = r + gamma * G), which equals the direct sum and
    never computes gamma**t for large t.
    """
    gamma = _check_gamma(gamma)
    g = 0.0
    for r in reversed(_check_rewards(rewards)):
        g = r + gamma * g
    return g


def returns_to_go(rewards: Sequence[float], gamma: float = GAMMA) -> List[float]:
    """G_t for every step t, using G_t = r_t + gamma * G_{t+1}."""
    gamma = _check_gamma(gamma)
    rewards = _check_rewards(rewards)
    out, g = [0.0] * len(rewards), 0.0
    for t in range(len(rewards) - 1, -1, -1):
        g = rewards[t] + gamma * g
        out[t] = g
    return out


# --------------------------------------------------------------------------
# 1. Trajectory logging
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Trajectory:
    """A finished episode: T steps, T+1 states."""

    states: Tuple[Any, ...]
    actions: Tuple[Any, ...]
    rewards: Tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.actions) < 1:
            raise ValueError("a trajectory needs at least one step")
        if not (len(self.states) == len(self.actions) + 1 == len(self.rewards) + 1):
            raise ValueError("need len(states) == len(actions) + 1 == len(rewards) + 1")
        _check_rewards(self.rewards)

    @property
    def T(self) -> int:
        return len(self.actions)

    def as_sequence(self) -> List[Any]:
        """[s0, a0, r0, s1, a1, r1, ..., sT] — the tau of the briefing."""
        seq: List[Any] = []
        for t in range(self.T):
            seq += [self.states[t], self.actions[t], self.rewards[t]]
        seq.append(self.states[-1])
        return seq

    def discounted_return(self, gamma: float = GAMMA) -> float:
        return discounted_return(self.rewards, gamma)

    def returns_to_go(self, gamma: float = GAMMA) -> List[float]:
        return returns_to_go(self.rewards, gamma)

    def to_dict(self) -> Dict[str, Any]:
        return {"states": list(self.states), "actions": list(self.actions), "rewards": list(self.rewards)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Trajectory":
        return cls(tuple(d["states"]), tuple(d["actions"]), tuple(float(r) for r in d["rewards"]))


class TrajectoryLogger:
    """Records state-action-reward trajectories, one episode at a time.

    Hook for the deliberation loop (Part 4): call start_episode(s0) once, then
    after every executed action call log_step(action, reward, next_state), and
    end_episode() when the agent reaches HALTED.
    """

    def __init__(self, gamma: float = GAMMA) -> None:
        self.gamma = _check_gamma(gamma)
        self.episodes: List[Trajectory] = []
        self._states: List[Any] = []
        self._actions: List[Any] = []
        self._rewards: List[float] = []
        self._open = False

    @property
    def episode_open(self) -> bool:
        return self._open

    def start_episode(self, initial_state: Any) -> None:
        if self._open:
            raise RuntimeError("an episode is already open; call end_episode() first")
        self._states, self._actions, self._rewards = [initial_state], [], []
        self._open = True

    def log_step(self, action: Any, reward: float, next_state: Any) -> None:
        """Record a_t, r_t and s_{t+1} for the current state s_t."""
        if not self._open:
            raise RuntimeError("no open episode; call start_episode(s0) first")
        _check_rewards([reward])
        self._actions.append(action)
        self._rewards.append(float(reward))
        self._states.append(next_state)

    def end_episode(self) -> Trajectory:
        if not self._open:
            raise RuntimeError("no open episode to end")
        if not self._actions:
            raise RuntimeError("cannot end an episode with no steps")
        traj = Trajectory(tuple(self._states), tuple(self._actions), tuple(self._rewards))
        self.episodes.append(traj)
        self._open = False
        return traj

    def returns(self) -> List[float]:
        """G_0 of every completed episode, in the order they were logged."""
        return [t.discounted_return(self.gamma) for t in self.episodes]

    def to_json(self) -> str:
        return json.dumps({"gamma": self.gamma, "episodes": [t.to_dict() for t in self.episodes]}, indent=2)


# --------------------------------------------------------------------------
# 3. Transition frequency matrix
# --------------------------------------------------------------------------
Jump = Tuple[str, str, str]  # (state, action, next_state)


class TransitionModel:
    """Empirical P(s' | s, a) = N(s, a, s') / N(s, a) from a log of jumps."""

    def __init__(self) -> None:
        self._counts: Dict[Tuple[str, str], Counter] = {}

    @classmethod
    def from_jumps(cls, jumps: Iterable[Jump]) -> "TransitionModel":
        model = cls()
        for jump in jumps:
            if len(jump) != 3 or not all(isinstance(x, str) and x for x in jump):
                raise ValueError(f"each jump must be (state, action, next_state) of non-empty strings, got {jump!r}")
            s, a, s2 = jump
            model._counts.setdefault((s, a), Counter())[s2] += 1
        if not model._counts:
            raise ValueError("the jump log is empty")
        return model

    @property
    def pairs(self) -> List[Tuple[str, str]]:
        return sorted(self._counts)

    @property
    def next_states(self) -> List[str]:
        return sorted({s2 for c in self._counts.values() for s2 in c})

    @property
    def total_jumps(self) -> int:
        return sum(sum(c.values()) for c in self._counts.values())

    def n(self, s: str, a: str) -> int:
        """N(s, a): how many times action a was taken in state s."""
        return sum(self._row(s, a).values())

    def counts(self, s: str, a: str) -> Dict[str, int]:
        return dict(self._row(s, a))

    def prob(self, s: str, a: str, s_next: str) -> float:
        row = self._row(s, a)
        return row.get(s_next, 0) / sum(row.values())

    def row(self, s: str, a: str) -> Dict[str, float]:
        row = self._row(s, a)
        total = sum(row.values())
        return {s2: c / total for s2, c in sorted(row.items())}

    def probability_of(self, s: str, a: str, outcomes: Iterable[str]) -> float:
        """P(s' in outcomes | s, a), e.g. the chance of reaching the escape corridor."""
        row = self._row(s, a)
        wanted = set(outcomes)
        return sum(c for s2, c in row.items() if s2 in wanted) / sum(row.values())

    def matrix(self) -> Tuple[List[Tuple[str, str]], List[str], List[List[float]]]:
        """Rows are the observed (s, a) pairs, columns the observed s'; each row sums to 1."""
        rows, cols = self.pairs, self.next_states
        return rows, cols, [[self.prob(s, a, c) for c in cols] for s, a in rows]

    def format_table(self) -> str:
        rows, cols, m = self.matrix()
        label_w = max(len(f"{s} | {a}") for s, a in rows)
        col_w = max(8, *(len(c) for c in cols)) + 1
        head = " " * label_w + " " + "".join(c.rjust(col_w) for c in cols) + "      N"
        lines = [head]
        for (s, a), vals in zip(rows, m):
            lines.append(f"{s} | {a}".ljust(label_w) + " " + "".join(f"{v:{col_w}.3f}" for v in vals) + f"{self.n(s, a):7d}")
        return "\n".join(lines)

    def _row(self, s: str, a: str) -> Counter:
        try:
            return self._counts[(s, a)]
        except KeyError:
            raise KeyError(f"no jumps logged for state={s!r}, action={a!r}: P(s'|s,a) is undefined, not 0") from None


def load_jumps_csv(path: Path) -> List[Jump]:
    """Read a jump log with the header state,action,next_state."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        need = {"state", "action", "next_state"}
        if reader.fieldnames is None or not need <= {f.strip() for f in reader.fieldnames}:
            raise ValueError(f"{path}: header must contain {sorted(need)}")
        jumps: List[Jump] = []
        for line, rec in enumerate(reader, start=2):
            vals = tuple((rec.get(k) or "").strip() for k in ("state", "action", "next_state"))
            if not all(vals):
                raise ValueError(f"{path}, line {line}: empty field in {vals!r}")
            jumps.append(vals)  # type: ignore[arg-type]
    return jumps


def _expand(table: Sequence[Tuple[str, str, str, int]]) -> List[Jump]:
    return [(s, a, s2) for s, a, s2, n in table for _ in range(n)]


# MOCK historical jump log (see the module docstring). Each row: state, action, next state, how often.
JUMP_LOG: List[Jump] = _expand([
    ("outer_filament", "warp_high_shields", "plasma_shear", 6),
    ("outer_filament", "warp_high_shields", "dust_lane", 3),
    ("outer_filament", "warp_high_shields", "outer_filament", 1),
    ("outer_filament", "warp_low_shields", "plasma_shear", 3),
    ("outer_filament", "warp_low_shields", "hull_breach", 2),
    ("plasma_shear", "warp_high_shields", "dust_lane", 5),
    ("plasma_shear", "warp_high_shields", "homunculus_core", 2),
    ("plasma_shear", "warp_high_shields", "hull_breach", 1),
    ("plasma_shear", "warp_low_shields", "hull_breach", 4),
    ("plasma_shear", "warp_low_shields", "dust_lane", 1),
    ("plasma_shear", "hold_and_scan", "plasma_shear", 3),
    ("plasma_shear", "hold_and_scan", "dust_lane", 1),
    ("dust_lane", "warp_high_shields", "escape_corridor", 6),
    ("dust_lane", "warp_high_shields", "homunculus_core", 3),
    ("dust_lane", "warp_high_shields", "hull_breach", 1),
    ("dust_lane", "warp_low_shields", "homunculus_core", 2),
    ("dust_lane", "warp_low_shields", "hull_breach", 2),
    ("homunculus_core", "warp_high_shields", "escape_corridor", 4),
    ("homunculus_core", "warp_high_shields", "hull_breach", 3),
    ("homunculus_core", "hold_and_scan", "homunculus_core", 2),
    ("homunculus_core", "hold_and_scan", "hull_breach", 1),
])


# --------------------------------------------------------------------------
# Self-checks (assert-based, as the briefing's "MDP Return Test" requires)
# --------------------------------------------------------------------------
def _raises(exc: type, fn, *args) -> bool:
    try:
        fn(*args)
    except exc:
        return True
    return False


def run_self_tests() -> None:
    print("[TEST 1] MDP Return Test (briefing): rewards [10, 0, -5, 20], gamma = 0.95")
    expected = 10 + 0.95 * 0 + 0.95 ** 2 * -5 + 0.95 ** 3 * 20  # written out term by term
    got = discounted_return([10, 0, -5, 20], 0.95)
    assert math.isclose(got, expected, abs_tol=1e-12) and math.isclose(got, 22.635, abs_tol=1e-9), got
    print(f"         G_0 = {got:.6f}  (expected 22.635000)  PASS")

    print("[TEST 2] discounted_return edge cases and returns_to_go")
    assert discounted_return([3, 4, 5], 1.0) == 12.0          # gamma = 1: plain sum
    assert discounted_return([3, 4, 5], 0.0) == 3.0           # gamma = 0: first reward only
    assert discounted_return([7]) == 7.0                      # one step
    rtg = returns_to_go([10, 0, -5, 20], 0.95)
    assert math.isclose(rtg[0], got, abs_tol=1e-12) and rtg[-1] == 20.0
    assert all(math.isclose(rtg[t], [10, 0, -5, 20][t] + 0.95 * rtg[t + 1], abs_tol=1e-12) for t in range(3))
    assert _raises(ValueError, discounted_return, [])
    assert _raises(ValueError, discounted_return, [1, float("nan")])
    assert _raises(ValueError, discounted_return, [1, 2], 1.5)
    assert _raises(ValueError, discounted_return, [1, 2], -0.1)
    assert _raises(TypeError, discounted_return, [1, 2], "0.9")
    print("         PASS")

    print("[TEST 3] TrajectoryLogger records tau = (s0, a0, r0, ..., sT)")
    log = TrajectoryLogger()
    assert _raises(RuntimeError, log.log_step, "a", 1.0, "s1")        # no open episode
    log.start_episode("s0")
    assert _raises(RuntimeError, log.start_episode, "s0")             # already open
    assert _raises(RuntimeError, log.end_episode)                     # zero steps
    log.log_step("a0", 10, "s1")
    log.log_step("a1", 0, "s2")
    assert _raises(ValueError, log.log_step, "a2", float("inf"), "s3")
    log.log_step("a2", -5, "s3")
    log.log_step("a3", 20, "s4")
    traj = log.end_episode()
    assert traj.T == 4 and not log.episode_open
    assert traj.as_sequence() == ["s0", "a0", 10.0, "s1", "a1", 0.0, "s2", "a2", -5.0, "s3", "a3", 20.0, "s4"]
    assert math.isclose(traj.discounted_return(), 22.635, abs_tol=1e-9) and math.isclose(log.returns()[0], 22.635, abs_tol=1e-9)
    assert Trajectory.from_dict(json.loads(json.dumps(traj.to_dict()))) == traj   # JSON round trip
    assert _raises(ValueError, Trajectory, ("s0",), ("a0",), (1.0,))              # wrong lengths
    print("         PASS")

    print("[TEST 4] TransitionModel on the mock jump log (hand-counted values)")
    model = TransitionModel.from_jumps(JUMP_LOG)
    assert model.total_jumps == len(JUMP_LOG) == 56
    assert model.n("outer_filament", "warp_high_shields") == 10
    assert math.isclose(model.prob("outer_filament", "warp_high_shields", "plasma_shear"), 0.6)
    assert math.isclose(model.prob("dust_lane", "warp_high_shields", "escape_corridor"), 0.6)
    assert math.isclose(model.prob("plasma_shear", "warp_low_shields", "hull_breach"), 0.8)
    assert model.prob("dust_lane", "warp_low_shields", "escape_corridor") == 0.0    # observed zero
    assert math.isclose(model.probability_of("dust_lane", "warp_high_shields", ["hull_breach"]), 0.1)
    rows, cols, m = model.matrix()
    assert len(rows) == 9 and all(math.isclose(sum(r), 1.0, abs_tol=1e-12) for r in m)
    assert all(0.0 <= v <= 1.0 for r in m for v in r)
    assert _raises(KeyError, model.prob, "escape_corridor", "warp_high_shields", "dust_lane")  # unseen pair
    assert _raises(ValueError, TransitionModel.from_jumps, [])
    assert _raises(ValueError, TransitionModel.from_jumps, [("a", "b")])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jumps.csv"
        path.write_text("state,action,next_state\nA,go,B\nA,go,B\nA,go,C\n", encoding="utf-8")
        assert math.isclose(TransitionModel.from_jumps(load_jumps_csv(path)).prob("A", "go", "B"), 2 / 3)
        path.write_text("state,action\nA,go\n", encoding="utf-8")
        assert _raises(ValueError, load_jumps_csv, path)
        path.write_text("state,action,next_state\nA,,B\n", encoding="utf-8")
        assert _raises(ValueError, load_jumps_csv, path)
    print("         PASS")
    print("[SUCCESS] Part 3 (MDP logger, G_0, transition matrix) self-tests passed.")


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
def demo_episodes() -> TrajectoryLogger:
    """Two illustrative episodes (made-up rewards; every jump exists in JUMP_LOG)."""
    log = TrajectoryLogger()
    # System 1 reflex: saves shield energy (+5 per step), then breaches the hull (-100 on the last step).
    log.start_episode("outer_filament")
    log.log_step("warp_low_shields", 5, "plasma_shear")
    log.log_step("warp_low_shields", 5 - 100, "hull_breach")
    reflex = log.end_episode()
    # System 2 deliberation: pays -1 per step for full shields, escapes (+100 on arrival).
    log.start_episode("outer_filament")
    log.log_step("warp_high_shields", -1, "plasma_shear")
    log.log_step("warp_high_shields", -1, "dust_lane")
    log.log_step("warp_high_shields", 99, "escape_corridor")
    deliberate = log.end_episode()
    print("Demo episodes (illustrative rewards)")
    g_reflex, g_delib = reflex.discounted_return(0.95), deliberate.discounted_return(0.95)
    for name, t in (("System 1 reflex    ", reflex), ("System 2 deliberate", deliberate)):
        print(f"  {name}: T={t.T}  rewards={list(t.rewards)}  G_0(gamma=0.95)={t.discounted_return(0.95):8.3f}  "
              f"G_0(gamma=0, first reward only)={t.discounted_return(0.0):5.1f}")
    assert reflex.discounted_return(0.0) > deliberate.discounted_return(0.0) and g_delib > g_reflex
    print("  A short-sighted agent (gamma=0) prefers the reflex; at gamma=0.95 the deliberate plan wins.")
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--jumps", type=Path, help="CSV jump log (state,action,next_state) instead of the mock JUMP_LOG")
    args = ap.parse_args()
    print(LINE)
    print("USSE NOOSPHERE • MDP TRAJECTORY LOGGER & EMPIRICAL RETURN EVALUATOR")
    print("Mission 06 / Part 3 — Data & Payload Specialist")
    print(LINE)
    run_self_tests()
    print(LINE)
    demo_episodes()
    print(LINE)
    if args.jumps:
        jumps, source = load_jumps_csv(args.jumps), str(args.jumps)
    else:
        jumps, source = JUMP_LOG, "MOCK jump log (hand-written; the real dataset is not in the repository)"
    model = TransitionModel.from_jumps(jumps)
    print(f"Empirical P(s' | s, a) from {model.total_jumps} jumps — {source}")
    print(model.format_table())
    if not args.jumps:
        print(f"\nExample: P(reach escape_corridor | dust_lane, warp_high_shields) = "
              f"{model.probability_of('dust_lane', 'warp_high_shields', ['escape_corridor']):.2f}; "
              f"P(hull_breach | plasma_shear, warp_low_shields) = "
              f"{model.prob('plasma_shear', 'warp_low_shields', 'hull_breach'):.2f}")
    print(LINE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
