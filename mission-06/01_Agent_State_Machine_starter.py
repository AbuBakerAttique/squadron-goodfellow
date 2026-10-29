"""
Mission 06 — Part 1: Systems Architect (Lead Engineer)
Deterministic Agent State Machine Core & Step Budget Enforcement

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


class AgentState(Enum):
    IDLE = auto()
    PERCEIVING = auto()
    DELIBERATING = auto()
    ACTING = auto()
    OBSERVING = auto()
    REFLECTING = auto()
    HALTED = auto()


@dataclass
class Agent:
    state: AgentState = AgentState.IDLE
    step_count: int = 0
    max_steps: int = 20
    memory: List[Dict[str, Any]] = field(default_factory=list)
    mission_completed: bool = False

    def step(self, perception_input: Optional[str] = None):
        """
        Executes exactly one state transition according to the deterministic cycle:
        IDLE -> PERCEIVING -> DELIBERATING -> ACTING -> OBSERVING -> REFLECTING -> DELIBERATING | HALTED
        """
        if self.step_count >= self.max_steps:
            print(f"[SECURITY] Maximum step budget ({self.max_steps}) exceeded! Forcing state -> HALTED.")
            self.state = AgentState.HALTED
            return

        self.step_count += 1
        prev_state = self.state

        if self.state == AgentState.IDLE:
            self.state = AgentState.PERCEIVING
        elif self.state == AgentState.PERCEIVING:
            self.state = AgentState.DELIBERATING
        elif self.state == AgentState.DELIBERATING:
            self.state = AgentState.ACTING
        elif self.state == AgentState.ACTING:
            self.state = AgentState.OBSERVING
        elif self.state == AgentState.OBSERVING:
            self.state = AgentState.REFLECTING
        elif self.state == AgentState.REFLECTING:
            if self.mission_completed:
                self.state = AgentState.HALTED
            else:
                self.state = AgentState.DELIBERATING

        print(f"Step {self.step_count:02d}: Transitioned from {prev_state.name} -> {self.state.name}")


if __name__ == "__main__":
    print("=== Subsystem 06: Agent State Machine Simulation ===")
    pilot = Agent(max_steps=10)
    for _ in range(12):
        if pilot.state == AgentState.HALTED:
            print("Agent safely HALTED.")
            break
        pilot.step()
