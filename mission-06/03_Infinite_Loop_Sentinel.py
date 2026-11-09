"""
Mission 06 — Part 3: Data & Payload Specialist
Infinite Loop Sentinel & State History Hashing

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
Officer: Abubaker Attique — Squadron Goodfellow

AI assistance: Claude completed the starter and wrote the self-checks (author
review not yet recorded; edit this line after you have reviewed the code).
Run: python 03_Infinite_Loop_Sentinel.py

Starter behaviour kept: InfiniteLoopSentinel(repeat_threshold=3), compute_step_hash()
(SHA-256 of the action and its arguments) and check_loop(), which counts
CONSECUTIVE identical steps and returns (is_loop_detected, repeat_count).

Added in this file:
* The hash can also cover the environment state (briefing: "hashes the current
  environmental state and AURA's planned action"). Without a state the hash is
  identical to the starter's.
* floyd_cycle(): Floyd's tortoise-and-hare over the recorded trajectory. The
  starter only sees "same step N times in a row", so a loop such as
  s1 -> s2 -> s3 -> s1 -> ... would never trip it.
* observe(): one call per agent step, returns a SentinelReport and logs a
  CRITICAL "SECURITY VIOLATION" when the tripwire fires. The caller then forces
  the agent to HALTED (see the integration check in run_self_tests()).
* Per-hash visit counters, so "how often has this exact state+action occurred"
  is an O(1) dictionary lookup.

Tripwire rule: trip when the same state+action occurs `repeat_threshold` times
in a row, OR when Floyd finds a cycle in the trajectory AND the current
state+action has been seen `repeat_threshold` times. Floyd needs the trajectory
to be deterministic (the same state+action is always followed by the same
next one); if it is not, floyd_cycle() returns None and only the consecutive
rule applies. Without a state in the hash, three equal actions with equal
arguments can come from different situations; pass state= to avoid that.

Use check_loop() OR observe() for a given sentinel, not both: each call records
one step.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Hashable, List, Optional, Sequence, Tuple

LOG = logging.getLogger("sentinel")
LINE = "=" * 74


def floyd_cycle(sequence: Sequence[Hashable]) -> Optional[Tuple[int, int]]:
    """Floyd's tortoise and hare over an observed trajectory.

    Returns (mu, lam): the index where the cycle starts and its length, or
    None when the trajectory has not (visibly) repeated or is not deterministic.
    O(len(sequence)) time and memory.
    """
    if len(sequence) < 2:
        return None
    succ: Dict[Hashable, Hashable] = {}
    for a, b in zip(sequence, sequence[1:]):
        if succ.setdefault(a, b) != b:
            return None                      # same node, two different successors

    def nxt(x: Optional[Hashable]) -> Optional[Hashable]:
        return None if x is None else succ.get(x)

    x0 = sequence[0]
    tortoise, hare = nxt(x0), nxt(nxt(x0))
    while tortoise != hare:                  # phase 1: meet somewhere inside the cycle
        if hare is None:
            return None                      # the trajectory ends before it loops
        tortoise, hare = nxt(tortoise), nxt(nxt(hare))
    if tortoise is None:
        return None
    mu, tortoise = 0, x0                     # phase 2: find where the cycle starts
    while tortoise != hare:
        tortoise, hare, mu = nxt(tortoise), nxt(hare), mu + 1
    lam, hare = 1, nxt(tortoise)             # phase 3: measure the cycle length
    while tortoise != hare:
        hare, lam = nxt(hare), lam + 1
    return mu, lam


@dataclass(frozen=True)
class SentinelReport:
    step_hash: str
    consecutive_repeats: int
    visits: int
    cycle: Optional[Tuple[int, int]]         # (start index, length) from Floyd, or None
    tripped: bool
    reason: str


class InfiniteLoopSentinel:
    """Prevents AURA from falling into cyclic action-observation traps by
    hashing (state, action, arguments) for every step."""

    def __init__(self, repeat_threshold: int = 3):
        if isinstance(repeat_threshold, bool) or not isinstance(repeat_threshold, int) or repeat_threshold < 2:
            raise ValueError("repeat_threshold must be an integer >= 2")
        self.repeat_threshold = repeat_threshold
        self.reset()

    def reset(self) -> None:
        self.history_hashes: List[str] = []
        self._visits: Counter = Counter()
        self._run_hash: Optional[str] = None
        self._run_len = 0

    def compute_step_hash(self, action: str, arguments: Dict[str, Any], state: Any = None) -> str:
        """Deterministic SHA-256 of the intended action, its parameters and, if given, the state."""
        payload: Dict[str, Any] = {"action": action, "arguments": arguments}
        if state is not None:
            payload["state"] = state
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _record(self, step_hash: str) -> int:
        self.history_hashes.append(step_hash)
        self._visits[step_hash] += 1
        if step_hash == self._run_hash:
            self._run_len += 1
        else:
            self._run_hash, self._run_len = step_hash, 1
        return self._run_len

    def check_loop(self, action: str, arguments: Dict[str, Any], state: Any = None) -> Tuple[bool, int]:
        """Starter interface: is the identical step repeating? -> (is_loop_detected, repeat_count)."""
        consecutive = self._record(self.compute_step_hash(action, arguments, state))
        return consecutive >= self.repeat_threshold, consecutive

    def visits(self, action: str, arguments: Dict[str, Any], state: Any = None) -> int:
        """How often this exact state+action has been recorded (O(1))."""
        return self._visits[self.compute_step_hash(action, arguments, state)]

    def observe(self, action: str, arguments: Dict[str, Any], state: Any = None) -> SentinelReport:
        """Record one step and decide whether the emergency tripwire fires."""
        step_hash = self.compute_step_hash(action, arguments, state)
        consecutive = self._record(step_hash)
        visits = self._visits[step_hash]
        cycle = floyd_cycle(self.history_hashes) if visits >= 2 else None
        reason = ""
        if consecutive >= self.repeat_threshold:
            reason = f"identical state+action {consecutive}x in a row"
        elif cycle is not None and visits >= self.repeat_threshold:
            reason = f"cycle of length {cycle[1]} starting at step {cycle[0] + 1}; this state+action seen {visits}x"
        if reason:
            LOG.critical("SECURITY VIOLATION: infinite loop detected at step %d (%s): action=%s state=%s",
                         len(self.history_hashes), reason, action, state)
        return SentinelReport(step_hash, consecutive, visits, cycle, bool(reason), reason)


# --------------------------------------------------------------------------
# Self-checks
# --------------------------------------------------------------------------
def _load_agent_module() -> Optional[Any]:
    """Part 1's Agent, if it sits next to this file (starter or final name)."""
    here = Path(__file__).resolve().parent
    for name in ("01_Agent_State_Machine.py", "01_Agent_State_Machine_starter.py"):
        path = here / name
        if path.exists():
            spec = importlib.util.spec_from_file_location("agent_part1", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def _brute_force_cycle(seq: Sequence[Hashable]) -> Optional[Tuple[int, int]]:
    seen: Dict[Hashable, int] = {}
    for i, x in enumerate(seq):
        if x in seen:
            return seen[x], i - seen[x]
        seen[x] = i
    return None


def run_self_tests() -> None:
    logging.getLogger("sentinel").setLevel(logging.CRITICAL + 1)   # keep test output quiet

    print("[TEST 1] SHA-256 step hash is deterministic and covers state + action + arguments")
    s = InfiniteLoopSentinel()
    h = s.compute_step_hash("query_sensor_array", {"target": "x", "n": 1})
    ref = hashlib.sha256(json.dumps({"action": "query_sensor_array", "arguments": {"target": "x", "n": 1}},
                                    sort_keys=True).encode()).hexdigest()
    assert h == ref and len(h) == 64                                   # same as the starter's hash
    assert h == s.compute_step_hash("query_sensor_array", {"n": 1, "target": "x"})   # key order is irrelevant
    assert h != s.compute_step_hash("query_sensor_array", {"target": "y", "n": 1})
    assert h != s.compute_step_hash("adjust_plasma_shields", {"target": "x", "n": 1})
    assert h != s.compute_step_hash("query_sensor_array", {"target": "x", "n": 1}, state="s1")
    print("         PASS")

    print("[TEST 2] starter interface: check_loop() counts consecutive repeats")
    s = InfiniteLoopSentinel(repeat_threshold=3)
    got = [s.check_loop("query_sensor_array", {"target": "corrupted_sector"}) for _ in range(4)]
    assert got == [(False, 1), (False, 2), (True, 3), (True, 4)], got
    s.reset()
    assert s.check_loop("a", {}) == (False, 1) and s.check_loop("b", {}) == (False, 1) and s.check_loop("a", {}) == (False, 1)
    assert s.check_loop("a", {"x": 1}) == (False, 1)                   # different arguments: different step
    for bad in (1, 0, True, 2.5, "3"):
        try:
            InfiniteLoopSentinel(bad)                                   # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"threshold {bad!r} should be rejected")
    print("         PASS")

    print("[TEST 3] Floyd's tortoise and hare agrees with brute force (300 random trajectories)")
    assert floyd_cycle(["s1", "s2", "s3", "s1", "s2", "s3"]) == (0, 3)
    assert floyd_cycle(["a", "b", "c", "d"]) is None
    assert floyd_cycle(["a", "b", "a", "c"]) is None                   # not deterministic: no verdict
    assert floyd_cycle(["x", "a", "b", "a", "b"]) == (1, 2)            # tail of length 1, cycle of length 2
    assert floyd_cycle(["a", "a"]) == (0, 1) and floyd_cycle(["a"]) is None and floyd_cycle([]) is None
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(2, 9)
        f = [rng.randrange(n) for _ in range(n)]
        x, seq = rng.randrange(n), []
        for _ in range(rng.randint(1, 25)):
            seq.append(x)
            x = f[x]
        assert floyd_cycle(seq) == _brute_force_cycle(seq), (seq, f)
    print("         PASS")

    print("[TEST 4] Sentinel Cycle Test (briefing): [s1, s2, s3, s1, s2, s3, ...] trips before step 10")
    seq = [("s1", "a1"), ("s2", "a2"), ("s3", "a3")] * 4
    s, tripped_at, report = InfiniteLoopSentinel(repeat_threshold=3), None, None
    for step, (state, action) in enumerate(seq, start=1):
        report = s.observe(action, {}, state=state)
        if report.tripped:
            tripped_at = step
            break
    assert tripped_at is not None and tripped_at < 10, tripped_at
    assert report.cycle == (0, 3) and report.visits == 3
    print(f"         tripwire fired at step {tripped_at}: {report.reason}   PASS")

    print("[TEST 5] no false alarms on a trajectory that never repeats or only varies")
    s = InfiniteLoopSentinel(repeat_threshold=3)
    assert not any(s.observe("navigate_warp_vector", {"x": float(i), "y": 0.0, "z": 0.0}).tripped for i in range(12))
    s = InfiniteLoopSentinel(repeat_threshold=3)                       # A visited 3x, but A -> B and A -> C: not a loop
    assert not any(s.observe(a, {}, state="s").tripped for a in ["A", "B", "A", "C", "A"])
    s = InfiniteLoopSentinel(repeat_threshold=3)                       # same action, different state each time
    assert not any(s.observe("adjust_plasma_shields", {"intensity": 85}, state=f"s{i}").tripped for i in range(6))
    s = InfiniteLoopSentinel(repeat_threshold=3)                       # consecutive rule fires on the third repeat
    assert [s.observe("query_sensor_array", {"target": "bad"}).tripped for _ in range(3)] == [False, False, True]
    print("         PASS")

    print("[TEST 6] security logging: a CRITICAL 'SECURITY VIOLATION' record is written")
    logger = logging.getLogger("sentinel")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.CRITICAL)
    try:
        s = InfiniteLoopSentinel(repeat_threshold=3)
        for _ in range(3):
            s.observe("query_sensor_array", {"target": "bad"}, state="s1")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.CRITICAL + 1)
    assert "SECURITY VIOLATION" in stream.getvalue()
    print("         PASS")

    print("[TEST 7] integration with Part 1: the sentinel halts the Agent before step 10")
    mod = _load_agent_module()
    if mod is None:
        print("         SKIPPED (no 01_Agent_State_Machine*.py next to this file)")
    else:
        agent, s = mod.Agent(max_steps=20), InfiniteLoopSentinel(repeat_threshold=3)
        for state, action in seq:
            with contextlib.redirect_stdout(io.StringIO()):            # Part 1 prints every transition
                agent.step()
            if s.observe(action, {}, state=state).tripped:
                agent.state = mod.AgentState.HALTED
                break
        assert agent.state == mod.AgentState.HALTED and agent.step_count < 10, (agent.state, agent.step_count)
        print(f"         Agent HALTED at step {agent.step_count}   PASS")
    print("[SUCCESS] Infinite Loop Sentinel self-tests passed.")


def demo() -> None:
    logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")
    LOG.setLevel(logging.INFO)
    print("Demo 1 — reflex loop: the same failed sensor query, again and again")
    s = InfiniteLoopSentinel(repeat_threshold=3)
    for i in range(1, 5):
        r = s.observe("query_sensor_array", {"target": "corrupted_sector"}, state="nebula_edge")
        print(f"  Cycle {i}: repeats in a row = {r.consecutive_repeats}, tripwire = {r.tripped}")
        if r.tripped:
            print("  >>> [ALARM] Repetitive reflex loop trapped! Forcing HALTED / System 2 cognitive reset. <<<")
            break
    print("\nDemo 2 — three-step loop s1 -> s2 -> s3 -> s1 ...: the starter's consecutive counter never fires")
    plain, s = InfiniteLoopSentinel(), InfiniteLoopSentinel()
    seq = [("s1", "a1"), ("s2", "a2"), ("s3", "a3")] * 3
    missed = [plain.check_loop(a, {}, state=st)[0] for st, a in seq]
    print(f"  check_loop() over 9 steps flagged a loop: {any(missed)}")
    for step, (st, a) in enumerate(seq, start=1):
        r = s.observe(a, {}, state=st)
        if r.tripped:
            print(f"  observe() tripped at step {step}: {r.reason}")
            break


if __name__ == "__main__":
    print(LINE)
    print("USSE NOOSPHERE • INFINITE LOOP SENTINEL & STATE HISTORY HASHING")
    print("Mission 06 / Part 3 — Data & Payload Specialist")
    print(LINE)
    run_self_tests()
    print(LINE)
    demo()
    print(LINE)
