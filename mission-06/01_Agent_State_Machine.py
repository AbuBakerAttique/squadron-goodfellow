"""
Mission 06 - Part 1: Systems Architect (Lead Engineer)
Deterministic Agent State Machine Core & Step Budget Enforcement

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
Officer: Abdul Jalil Memon - Squadron Goodfellow

AI assistance: Claude completed the starter and wrote the self-checks (author
review not yet recorded; edit this line after you have reviewed the code).
Run: python 01_Agent_State_Machine.py

Briefing requirements covered
-----------------------------
1. AgentState (Enum) with exactly: IDLE, PERCEIVING, DELIBERATING, ACTING,
   OBSERVING, REFLECTING, HALTED.
2. Agent as a standard @dataclass.
3. step() performs exactly one transition on the strict graph:
       IDLE -> PERCEIVING -> DELIBERATING -> ACTING -> OBSERVING -> REFLECTING
       REFLECTING -> DELIBERATING (loop)  OR  HALTED (terminal)
4. Hard step budget N <= 20: once N transitions have been used, the next
   call to step() forces the agent to HALTED.

Starter behaviour kept (the other parts depend on it)
-----------------------------------------------------
Agent(max_steps=...), Agent.step(perception_input=None), .state, .step_count,
.max_steps, .memory, .mission_completed. Parts 3 and 4 load this module by
file name and set `agent.state = AgentState.HALTED` directly for the
emergency tripwire, which still works.

Changes made to the starter
---------------------------
* The graph is a data table (TRANSITIONS) instead of an if/elif chain, so it
  can be inspected and tested.
* HALTED is terminal: step() on a halted agent does nothing and does not
  consume budget (the starter counted a bogus "HALTED -> HALTED" step).
* max_steps is validated (1..20), so the budget cannot be configured away.
* The halt reason is recorded, and every transition is appended to `history`.
* perception_input is stored in `memory` instead of being ignored.
* Pure standard library: no external framework.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

MAX_STEP_BUDGET = 20  # briefing: N <= 20


class AgentState(Enum):
    IDLE = auto()
    PERCEIVING = auto()
    DELIBERATING = auto()
    ACTING = auto()
    OBSERVING = auto()
    REFLECTING = auto()
    HALTED = auto()


S = AgentState

# The strict graph. REFLECTING is the only state with two successors; which
# one is taken depends on Agent.mission_completed (see Agent._next_state).
TRANSITIONS: Dict[AgentState, tuple] = {
    S.IDLE: (S.PERCEIVING,),
    S.PERCEIVING: (S.DELIBERATING,),
    S.DELIBERATING: (S.ACTING,),
    S.ACTING: (S.OBSERVING,),
    S.OBSERVING: (S.REFLECTING,),
    S.REFLECTING: (S.DELIBERATING, S.HALTED),
    S.HALTED: (),  # terminal
}


@dataclass
class Agent:
    state: AgentState = AgentState.IDLE
    step_count: int = 0
    max_steps: int = MAX_STEP_BUDGET
    memory: List[Dict[str, Any]] = field(default_factory=list)
    mission_completed: bool = False
    halt_reason: Optional[str] = None
    history: List[tuple] = field(default_factory=list)
    verbose: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int):
            raise TypeError(f"max_steps must be an int, got {type(self.max_steps).__name__}")
        if not 1 <= self.max_steps <= MAX_STEP_BUDGET:
            raise ValueError(f"max_steps must be in 1..{MAX_STEP_BUDGET}, got {self.max_steps}")

    # ------------------------------------------------------------------ #
    @property
    def is_halted(self) -> bool:
        return self.state == AgentState.HALTED

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def _next_state(self) -> AgentState:
        """Successor of the current state on the graph."""
        if self.state == AgentState.REFLECTING:
            return AgentState.HALTED if self.mission_completed else AgentState.DELIBERATING
        return TRANSITIONS[self.state][0]

    def halt(self, reason: str) -> None:
        """Force the agent into the terminal state (budget, tripwire, ...)."""
        if self.state != AgentState.HALTED:
            self.state = AgentState.HALTED
        if self.halt_reason is None:
            self.halt_reason = reason

    # ------------------------------------------------------------------ #
    def step(self, perception_input: Optional[str] = None) -> AgentState:
        """
        Execute exactly one state transition:
        IDLE -> PERCEIVING -> DELIBERATING -> ACTING -> OBSERVING -> REFLECTING
        -> DELIBERATING | HALTED

        * HALTED is terminal: calling step() again changes nothing.
        * If the budget of `max_steps` transitions is already used up, the
          agent is forced to HALTED instead of transitioning further.
        """
        if self.state == AgentState.HALTED:
            return self.state

        if self.step_count >= self.max_steps:
            self._log(f"[SECURITY] Maximum step budget ({self.max_steps}) exceeded! Forcing state -> HALTED.")
            self.halt(f"step budget of {self.max_steps} exceeded")
            return self.state

        if perception_input is not None:
            self.memory.append(
                {"step": self.step_count + 1, "state": self.state.name, "perception": perception_input}
            )

        prev_state = self.state
        self.state = self._next_state()
        self.step_count += 1
        self.history.append((self.step_count, prev_state, self.state))

        if self.state == AgentState.HALTED and self.halt_reason is None:
            self.halt_reason = "mission completed"

        self._log(f"Step {self.step_count:02d}: Transitioned from {prev_state.name} -> {self.state.name}")
        return self.state


# ---------------------------------------------------------------------- #
# Self-tests (briefing: "State Machine Test")
# ---------------------------------------------------------------------- #
def run_self_tests() -> None:
    print("\n=== Mission 06 Part 1: State Machine Self-Tests ===")

    # 0. Enum has exactly the required states, in order.
    assert [s.name for s in AgentState] == [
        "IDLE", "PERCEIVING", "DELIBERATING", "ACTING", "OBSERVING", "REFLECTING", "HALTED",
    ]
    print("[PASS] AgentState has exactly the 7 required states")

    # 1. Full graph, step by step, IDLE -> ... -> REFLECTING -> DELIBERATING (loop).
    a = Agent(verbose=False)
    path = [a.state]
    for _ in range(6):
        path.append(a.step())
    assert path == [S.IDLE, S.PERCEIVING, S.DELIBERATING, S.ACTING, S.OBSERVING, S.REFLECTING, S.DELIBERATING]
    assert a.step_count == 6
    print("[PASS] Graph transitions in strict order, REFLECTING loops to DELIBERATING")

    # 2. IDLE -> HALTED through the graph when the mission completes.
    a = Agent(verbose=False)
    for _ in range(5):
        a.step()
    assert a.state == S.REFLECTING
    a.mission_completed = True
    assert a.step() == S.HALTED
    assert a.halt_reason == "mission completed"
    assert a.step_count == 6
    print("[PASS] IDLE -> HALTED when mission_completed at REFLECTING")

    # 3. Exactly one transition per call.
    a = Agent(verbose=False)
    for i in range(1, 8):
        before = a.step_count
        a.step()
        assert a.step_count == before + 1 == i
    print("[PASS] step() performs exactly one transition per call")

    # 4. HALTED is terminal and consumes no budget.
    a = Agent(verbose=False)
    a.halt("test")
    for _ in range(5):
        assert a.step() == S.HALTED
    assert a.step_count == 0
    print("[PASS] HALTED is terminal (step() is a no-op)")

    # 5. Budget: forced to run 21 steps with a never-completing mission.
    a = Agent(max_steps=20, verbose=False)
    calls = 0
    while not a.is_halted:
        a.step()
        calls += 1
        assert calls <= 21, "agent failed to terminate by call 21"
    assert calls == 21 and a.step_count == 20
    assert a.state == S.HALTED and "budget" in a.halt_reason
    print("[PASS] Step budget: 20 transitions, 21st call forces HALTED")

    # 6. Smaller budget.
    a = Agent(max_steps=3, verbose=False)
    for _ in range(4):
        a.step()
    assert a.is_halted and a.step_count == 3
    print("[PASS] Custom budget (max_steps=3) enforced")

    # 7. Budget cannot be configured above 20 or below 1.
    for bad in (0, -1, 21, 100):
        try:
            Agent(max_steps=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"max_steps={bad} should be rejected")
    for bad in ("5", 2.5, True):
        try:
            Agent(max_steps=bad)
        except TypeError:
            pass
        else:
            raise AssertionError(f"max_steps={bad!r} should be rejected")
    print("[PASS] max_steps validated (1..20, int only)")

    # 8. Perception input is stored; histories are not shared between instances.
    a, b = Agent(verbose=False), Agent(verbose=False)
    a.step("radiation spike at sector 7")
    assert a.memory[0]["perception"] == "radiation spike at sector 7"
    assert b.memory == [] and b.history == []
    print("[PASS] perception_input recorded; no shared mutable defaults")

    # 9. Emergency tripwire contract used by Parts 3/4: set state directly.
    a = Agent(verbose=False)
    a.step()
    a.state = S.HALTED
    assert a.step() == S.HALTED and a.step_count == 1
    print("[PASS] External forced HALTED (tripwire) is respected")

    print("\nAll Part 1 self-tests passed.")


if __name__ == "__main__":
    print("=== Subsystem 06: Agent State Machine Simulation ===")
    pilot = Agent(max_steps=10)
    for _ in range(12):
        if pilot.state == AgentState.HALTED:
            print(f"Agent safely HALTED ({pilot.halt_reason}).")
            break
        pilot.step()
    run_self_tests()
    