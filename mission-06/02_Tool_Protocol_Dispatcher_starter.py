"""
Mission 06 — Part 2: Communications & Protocol Officer
Tool Protocol Contracts, Schema Validation & Exception Boundaries

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
"""

import json
from typing import Callable, Dict, Any, Tuple


# 1. Tool Implementations
def navigate_warp_vector(x: float, y: float, z: float) -> str:
    """Sets course vector through the nebula."""
    return f"Warp navigational coordinates successfully aligned to vector [{x:.2f}, {y:.2f}, {z:.2f}]."


def adjust_plasma_shields(intensity: int) -> str:
    """Modulates magnetic plasma shield intensity (0 to 100%)."""
    if not (0 <= intensity <= 100):
        raise ValueError(f"Shield intensity {intensity}% is out of bounds! Valid range: [0, 100].")
    return f"Plasma shield harmonics adjusted to {intensity}% capacity."


def query_sensor_array(target: str) -> str:
    """Scans telemetry for anomalies or radiation spikes."""
    known_targets = {
        "homunculus_core": "Severe plasma flare detected. High density stellar dust at azimuth 142.",
        "eta_carinae_b": "Secondary O-type binary companion emission: 100x solar luminosity.",
        "escape_corridor": "Clear gravitational corridor detected along vector [-0.85, 0.52, 0.05]."
    }
    return known_targets.get(target.lower(), f"Sensor array reports: Target '{target}' unresolved.")


# 2. Schema Contracts
TOOL_SCHEMAS = {
    "navigate_warp_vector": {
        "type": "object",
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"}
        },
        "required": ["x", "y", "z"]
    },
    "adjust_plasma_shields": {
        "type": "object",
        "properties": {
            "intensity": {"type": "integer"}
        },
        "required": ["intensity"]
    },
    "query_sensor_array": {
        "type": "object",
        "properties": {
            "target": {"type": "string"}
        },
        "required": ["target"]
    }
}

TOOL_REGISTRY: Dict[str, Callable] = {
    "navigate_warp_vector": navigate_warp_vector,
    "adjust_plasma_shields": adjust_plasma_shields,
    "query_sensor_array": query_sensor_array
}


class ActionDispatcher:
    """
    Validates tool calls against JSON schemas and executes inside an error boundary.
    """
    @staticmethod
    def dispatch(tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name not in TOOL_REGISTRY:
            return f"Tool Execution Error: Unknown tool '{tool_name}'."

        # Validate arguments exist
        schema = TOOL_SCHEMAS.get(tool_name, {})
        required = schema.get("required", [])
        for req in required:
            if req not in arguments:
                return f"Tool Execution Error: Missing required argument '{req}' for '{tool_name}'."

        # Execute inside error boundary
        try:
            result = TOOL_REGISTRY[tool_name](**arguments)
            return f"Observation: {result}"
        except Exception as e:
            # Inject error back into context so agent can self-correct
            return f"Tool Execution Error: {type(e).__name__} — {str(e)}"


if __name__ == "__main__":
    dispatcher = ActionDispatcher()
    print("=== Subsystem 06: Tool Dispatcher & Error Boundary Tests ===")
    print(dispatcher.dispatch("adjust_plasma_shields", {"intensity": 85}))
    print(dispatcher.dispatch("adjust_plasma_shields", {"intensity": 150})) # Error boundary test
    print(dispatcher.dispatch("query_sensor_array", {"target": "escape_corridor"}))
