
"""
Mission 06 — Part 4: Security & Ethics Sentinel
System 2 Warp Pilot, Cycle Detection & Emergency Halting

Course: Conversational AI WS 2026/27
Squadron: Goodfellow
Sector: SEC-06-CAR

Integrates:
- Part 1: AgentStateMachine
- Part 2: ActionDispatcher
- Part 3: InfiniteLoopSentinel and TrajectoryLogger
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import logging
import sys
import math 
from pathlib import Path
from typing import Any, Dict, List, Tuple

LOG = logging.getLogger("warp_pilot")


# -------------------------------------------------------
# 1. Load existing squad modules
# -------------------------------------------------------

def load_module(module_name, filenames):
    root = Path(__file__).resolve().parent

    for filename in filenames:
        path = root / filename

        if path.is_file():
            spec = importlib.util.spec_from_file_location(
                module_name, path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module

    raise FileNotFoundError(
        f"Missing module. Expected one of: {filenames}"
    )


def load_squad_modules():
    agent = load_module("squad_agent", (
        "01_Agent_State_Machine.py",
        "01_Agent_State_Machine_starter.py"
    ))

    protocol = load_module("squad_protocol", (
        "02_Tool_Protocol_Dispatcher.py",
        "02_Tool_Protocol_Dispatcher_starter.py"
    ))

    sentinel = load_module("squad_sentinel", (
        "03_Infinite_Loop_Sentinel.py",
        "03_Infinite_Loop_Sentinel_starter.py"
    ))

    mdp = load_module("squad_mdp", (
        "03_MDP_Trajectory_Logger.py",
    ))

    return agent, protocol, sentinel, mdp


# -------------------------------------------------------
# 2. System 2 Deliberation Engine
# -------------------------------------------------------

class System2DeliberationEngine:
    """
    System 1 proposes actions quickly.
    System 2 checks safety before execution.

    Unsafe actions are corrected or rejected.
    """

    def __init__(self, shield_safety_margin=60):
        if (
            type(shield_safety_margin) is not int
            or not 0 <= shield_safety_margin <= 100
        ):
            raise ValueError(
                "Shield safety margin must be 0-100."
            )

        self.shield_safety_margin = shield_safety_margin
        self.current_shields = 0
        self.escape_corridor_scanned = False
        self.audit_log = []

    def deliberate(
        self,
        thought: str,
        proposed_action: str,
        proposed_args: Dict[str, Any]
    ) -> Dict[str, Any]:

        args = (
            dict(proposed_args)
            if isinstance(proposed_args, dict)
            else {}
        )

        status = "APPROVED"
        explanation = "Passed safety audit"

        allowed_tools = {
            "query_sensor_array",
            "adjust_plasma_shields",
            "navigate_warp_vector"
        }

        # Guardrail 1: Reject unauthorized actions
        if proposed_action not in allowed_tools:
            status = "REJECTED"
            explanation = "Unknown or unauthorized action"

        elif not isinstance(proposed_args, dict):
            status = "REJECTED"
            explanation = "Arguments must be a dictionary"

        # Guardrail 2: Validate shield intensity
        elif proposed_action == "adjust_plasma_shields":
            intensity = args.get("intensity")

            if (
                type(intensity) is not int
                or not 0 <= intensity <= 100
            ):
                status = "REJECTED"
                explanation = "Invalid shield intensity"

            elif intensity < self.shield_safety_margin:
                args["intensity"] = self.shield_safety_margin
                status = "MODIFIED"

                explanation = (
                    f"Unsafe shield intensity {intensity}% "
                    f"corrected to {self.shield_safety_margin}%"
                )

        # Guardrail 3: Verify navigation safety
        elif proposed_action == "navigate_warp_vector":

            if self.current_shields < self.shield_safety_margin:
                status = "REJECTED"
                explanation = (
                    "Warp blocked: insufficient shields"
                )

            elif not self.escape_corridor_scanned:
                status = "REJECTED"
                explanation = (
                    "Warp blocked: escape corridor not verified"
                )

            elif (
                set(args) != {"x", "y", "z"}
                or any(
                    isinstance(args[k], bool)
                    or not isinstance(args[k], (int, float))
                    or not math.isfinite(args[k])
                    for k in ("x", "y", "z")
                    if k in args
                )
            ):
                status = "REJECTED"
                explanation = "Invalid navigation vector"

        trace = (
            f"System 1: {thought} | "
            f"System 2: {explanation}"
        )

        self.audit_log.append(f"{status}: {trace}")

        return {
            "status": status,
            "action": proposed_action,
            "arguments": args,
            "deliberation_trace": trace
        }

    def record_observation(self, action, args, result):
        """
        Update ship safety status only when a tool
        has executed successfully.
        """

        if not result.startswith("Observation:"):
            return

        if action == "adjust_plasma_shields":
            self.current_shields = args["intensity"]

        elif (
            action == "query_sensor_array"
            and args.get("target") == "escape_corridor"
        ):
            self.escape_corridor_scanned = (
                "Clear gravitational corridor detected" in result
            )


# -------------------------------------------------------
# 3. Pilot Outcome
# -------------------------------------------------------

@dataclass
class PilotOutcome:
    agent: Any
    observations: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    trajectory: Any = None


# -------------------------------------------------------
# 4. Integrated System 2 Warp Pilot
# -------------------------------------------------------

class WarpPilot:
    """
    Integrates state transitions, tool calls,
    MDP logging and infinite-loop protection.
    """

    def __init__(
        self,
        agent_module,
        protocol_module,
        sentinel_module,
        mdp_module,
        max_steps=20,
        repeat_threshold=3
    ):

        if not 1 <= max_steps <= 20:
            raise ValueError("Step budget must be 1-20")

        self.agent_api = agent_module
        self.agent = agent_module.Agent(max_steps=max_steps)

        self.dispatcher = protocol_module.ActionDispatcher()

        self.sentinel = sentinel_module.InfiniteLoopSentinel(
            repeat_threshold=repeat_threshold
        )

        if not hasattr(self.sentinel, "observe"):
            raise TypeError(
                "Extended InfiniteLoopSentinel.observe() required"
            )

        self.logger = mdp_module.TrajectoryLogger(gamma=0.95)

        self.engine = System2DeliberationEngine(
            shield_safety_margin=60
        )

        self.outcome = PilotOutcome(self.agent)

    # Emergency Circuit Breaker
    def emergency_halt(self, reason):

        self.agent.state = self.agent_api.AgentState.HALTED

        violation = f"SECURITY VIOLATION: {reason}"

        LOG.critical(violation)
        self.outcome.violations.append(violation)

    def advance_to(self, target):
        """
        Follow deterministic state transitions.
        Never continue after HALTED.
        """

        halted = self.agent_api.AgentState.HALTED

        while self.agent.state not in (target, halted):
            self.agent.step()

        return self.agent.state == target

    def execute_action(
        self,
        thought,
        action,
        arguments,
        environment_state,
        reward
    ):

        S = self.agent_api.AgentState

        if not self.advance_to(S.DELIBERATING):
            return False

        # System 2 safety audit
        decision = self.engine.deliberate(
            thought, action, arguments
        )

        self.outcome.decisions.append(decision)

        # Check repeated state-action patterns
        report = self.sentinel.observe(
            action,
            arguments,
            state=environment_state
        )

        if report.tripped:
            self.emergency_halt(
                f"Emergency Tripwire: {report.reason}"
            )
            return False

        if not self.advance_to(S.ACTING):
            return False

        # Execute only approved or corrected actions
        if decision["status"] == "REJECTED":
            observation = (
                "Tool Execution Error: "
                "System 2 safety rejection"
            )
        else:
            observation = self.dispatcher.dispatch(
                decision["action"],
                decision["arguments"]
            )

        self.outcome.observations.append(observation)

        # Store decision in agent memory
        self.agent.memory.append({
            "environment": environment_state,
            "thought": thought,
            "action": action,
            "arguments": dict(arguments),
            "decision": decision,
            "observation": observation
        })

        self.engine.record_observation(
            action,
            decision["arguments"],
            observation
        )

        # Log MDP transition
        success = observation.startswith("Observation:")

        next_state = (
            "escape_corridor"
            if success and action == "navigate_warp_vector"
            else environment_state
        )

        self.logger.log_step(
            action,
            reward if success else -5.0,
            next_state
        )

        if not self.advance_to(S.OBSERVING):
            return False

        if not self.advance_to(S.REFLECTING):
            return False

        if action == "navigate_warp_vector" and success:
            self.agent.mission_completed = True

        self.agent.step()

        return self.agent.state != S.HALTED

    # Safe navigation mission
    def run_escape_mission(self):

        self.logger.start_episode("homunculus_nebula")

        mission_plan = [
            (
                "Locate a safe exit",
                "query_sensor_array",
                {"target": "escape_corridor"},
                "homunculus_nebula",
                -1.0
            ),
            (
                "Lower shields to conserve energy",
                "adjust_plasma_shields",
                {"intensity": 20},
                "homunculus_nebula",
                -1.0
            ),
            (
                "Navigate through verified corridor",
                "navigate_warp_vector",
                {"x": -0.85, "y": 0.52, "z": 0.05},
                "homunculus_nebula",
                20.0
            )
        ]

        for plan in mission_plan:
            self.execute_action(*plan)

            if self.agent.state == self.agent_api.AgentState.HALTED:
                break

        if self.agent.state != self.agent_api.AgentState.HALTED:
            self.emergency_halt(
                "Mission ended without terminal state"
            )

        if self.logger.episode_open and self.logger._actions:
            self.outcome.trajectory = (
                self.logger.end_episode()
            )

        return self.outcome

    # Ship Anomaly 06: Infinite loop simulation
    def run_loop_anomaly(self):

        repeating_states = ["s1", "s2", "s3"]

        for attempt in range(12):
            state = repeating_states[attempt % 3]
            action = f"a{attempt % 3 + 1}"

            report = self.sentinel.observe(
                action,
                {},
                state=state
            )

            if report.tripped:
                self.emergency_halt(
                    f"Emergency Tripwire at attempt "
                    f"{attempt + 1}: {report.reason}"
                )
                break

        return self.outcome


# -------------------------------------------------------
# 5. Automated Security & Ethics Tests
# -------------------------------------------------------

def run_part4_tests():

    agent_mod, protocol_mod, sentinel_mod, mdp_mod = (
        load_squad_modules()
    )

    S = agent_mod.AgentState

    print("\n=== Mission 06: Security & Ethics Tests ===")

    # Test 1: Unsafe warp rejected
    engine = System2DeliberationEngine(60)

    result = engine.deliberate(
        "Jump immediately",
        "navigate_warp_vector",
        {"x": 1, "y": 0, "z": 0}
    )

    assert result["status"] == "REJECTED"

    print("[PASS] Unsafe warp navigation blocked")

    # Test 2: Shield intensity corrected
    original = {"intensity": 20}

    result = engine.deliberate(
        "Lower shields",
        "adjust_plasma_shields",
        original
    )

    assert result["status"] == "MODIFIED"
    assert result["arguments"]["intensity"] == 60
    assert original == {"intensity": 20}

    print("[PASS] Unsafe shield intensity corrected")

    # Test 3: Invalid shield rejected
    result = engine.deliberate(
        "Set negative shields",
        "adjust_plasma_shields",
        {"intensity": -10}
    )

    assert result["status"] == "REJECTED"

    print("[PASS] Invalid shield intensity rejected")

    # Test 4: Successful mission
    pilot = WarpPilot(
        agent_mod, protocol_mod, sentinel_mod, mdp_mod
    )

    outcome = pilot.run_escape_mission()

    assert outcome.agent.state == S.HALTED
    assert outcome.agent.mission_completed
    assert outcome.agent.step_count <= 20
    assert len(outcome.observations) == 3
    assert not outcome.violations
    assert outcome.trajectory.T == 3

    print("[PASS] Ship escaped safely and halted")

    # Test 5: Floyd cycle + emergency breaker
    anomaly = WarpPilot(
        agent_mod, protocol_mod, sentinel_mod, mdp_mod
    )

    outcome = anomaly.run_loop_anomaly()

    assert outcome.agent.state == S.HALTED
    assert len(anomaly.sentinel.history_hashes) < 10
    assert outcome.violations
    assert "SECURITY VIOLATION" in outcome.violations[0]

    print("[PASS] Infinite loop detected and halted")
    print("[PASS] Emergency Circuit Breaker activated")

    print("\nAll Part 4 tests PASSED!")


if __name__ == "__main__":
    import math

    logging.basicConfig(
        level=logging.ERROR,
        format="%(levelname)s: %(message)s"
    )

    run_part4_tests()
