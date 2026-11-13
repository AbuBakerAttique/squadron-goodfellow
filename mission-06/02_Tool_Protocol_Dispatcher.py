"""
Mission 06 — Part 2: Communications & Protocol Officer
Tool Protocol Contracts, Schema Validation & Exception Boundaries

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
"""

import json
import math
from typing import Callable, Dict, Any, List, Union


# 1. Tool Implementations

def navigate_warp_vector(x: float, y: float, z: float) -> str:
    """Sets course vector through the Homunculus Nebula.

    Args:
        x: X-axis warp coordinate component.
        y: Y-axis warp coordinate component.
        z: Z-axis warp coordinate component.

    Returns:
        Confirmation string with aligned vector coordinates.
    """
    return (
        f"Warp navigational coordinates successfully aligned "
        f"to vector [{x:.2f}, {y:.2f}, {z:.2f}]."
    )


def adjust_plasma_shields(intensity: int) -> str:
    """Modulates magnetic plasma shield intensity.

    Args:
        intensity: Shield power percentage (0-100 inclusive).

    Returns:
        Confirmation of shield adjustment.

    Raises:
        ValueError: If intensity is outside [0, 100].
    """
    if not isinstance(intensity, int) or isinstance(intensity, bool):
        raise TypeError(
            f"Shield intensity must be an integer, got {type(intensity).__name__}."
        )
    if not (0 <= intensity <= 100):
        raise ValueError(
            f"Shield intensity {intensity}% is out of bounds! Valid range: [0, 100]."
        )
    return f"Plasma shield harmonics adjusted to {intensity}% capacity."


def query_sensor_array(target: str) -> str:
    """Scans telemetry for anomalies, radiation spikes, or escape corridors.

    Args:
        target: Sensor sweep target identifier.

    Returns:
        Sensor reading for the requested target, or an 'unresolved' notice.
    """
    known_targets = {
        "homunculus_core": (
            "Severe plasma flare detected. "
            "High density stellar dust at azimuth 142."
        ),
        "eta_carinae_b": (
            "Secondary O-type binary companion emission: "
            "100x solar luminosity."
        ),
        "escape_corridor": (
            "Clear gravitational corridor detected "
            "along vector [-0.85, 0.52, 0.05]."
        ),
    }
    return known_targets.get(
        target.lower(),
        f"Sensor array reports: Target '{target}' unresolved.",
    )


# 2. Schema Contracts

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "navigate_warp_vector": {
        "type": "object",
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
        },
        "required": ["x", "y", "z"],
    },
    "adjust_plasma_shields": {
        "type": "object",
        "properties": {
            "intensity": {"type": "integer"},
        },
        "required": ["intensity"],
    },
    "query_sensor_array": {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
        },
        "required": ["target"],
    },
}

TOOL_REGISTRY: Dict[str, Callable] = {
    "navigate_warp_vector": navigate_warp_vector,
    "adjust_plasma_shields": adjust_plasma_shields,
    "query_sensor_array": query_sensor_array,
}

# Maps JSON Schema type keywords to Python type-check callables.
# Each entry returns True when the value is acceptable for that type.
_JSON_TYPE_CHECKERS: Dict[str, Callable[[Any], bool]] = {
    "number": lambda v: isinstance(v, (int, float))
                        and not isinstance(v, bool)
                        and math.isfinite(v),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
}


# 3. ActionDispatcher

class ActionDispatcher:
    """
    Validates tool calls against JSON-Schema contracts and executes them
    inside an error boundary.  If validation or execution fails, the error
    is formatted as an observation string and injected back into the agent
    context for self-correction -- the Python process never crashes.

    The dispatch() method accepts either:
      - a dict of keyword arguments, or
      - a raw JSON string (which will be parsed first).
    Any other input type (None, list, int, ...) is safely rejected with a
    formatted error string.
    """

    @staticmethod
    def _coerce_arguments(raw: Any) -> Dict[str, Any]:
        """Try to produce a dict from the raw arguments payload.

        Accepts a dict (pass-through) or a JSON string (parsed).
        Raises TypeError for anything else, or ValueError / json.JSONDecodeError
        for malformed JSON strings.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            parsed = json.loads(raw)          # may raise json.JSONDecodeError
            if not isinstance(parsed, dict):
                raise TypeError(
                    f"JSON payload decoded to {type(parsed).__name__}, "
                    f"expected a JSON object (dict)."
                )
            return parsed
        raise TypeError(
            f"Arguments must be a dict or a JSON string, "
            f"got {type(raw).__name__}."
        )

    @staticmethod
    def validate_schema(
        tool_name: str, arguments: Dict[str, Any]
    ) -> List[str]:
        """Validate arguments against the tool's JSON-Schema contract.

        Returns:
            A list of validation error messages (empty if valid).
        """
        schema = TOOL_SCHEMAS.get(tool_name)
        if schema is None:
            return [f"No schema registered for tool '{tool_name}'."]

        errors: List[str] = []
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Check required arguments are present
        for req in required:
            if req not in arguments:
                errors.append(f"Missing required argument '{req}'.")

        # Type-check every provided argument
        for arg_name, arg_value in arguments.items():
            if arg_name not in properties:
                errors.append(
                    f"Unexpected argument '{arg_name}' not in schema."
                )
                continue

            expected_type_key = properties[arg_name].get("type")
            checker = _JSON_TYPE_CHECKERS.get(expected_type_key)
            if checker and not checker(arg_value):
                errors.append(
                    f"Argument '{arg_name}' expects type '{expected_type_key}', "
                    f"got '{type(arg_value).__name__}'"
                    + (
                        " (non-finite)"
                        if isinstance(arg_value, float)
                        and not math.isfinite(arg_value)
                        else ""
                    )
                    + "."
                )

        return errors

    @staticmethod
    def dispatch(tool_name: str, arguments: Any) -> str:
        """Validate and execute a tool call inside an error boundary.

        Args:
            tool_name: Name of the tool to invoke.
            arguments: Keyword arguments as a dict, a raw JSON string,
                       or any other value (safely rejected).

        Returns:
            An observation string on success, or a formatted
            'Tool Execution Error: ...' string on any failure.
            Never raises -- the Python process never crashes.
        """
        # --- Outer error boundary: catches absolutely everything ---
        try:
            # 1. Check tool exists
            if tool_name not in TOOL_REGISTRY:
                return f"Tool Execution Error: Unknown tool '{tool_name}'."

            # 2. Coerce raw payload into a dict
            arguments = ActionDispatcher._coerce_arguments(arguments)

            # 3. Schema validation
            validation_errors = ActionDispatcher.validate_schema(
                tool_name, arguments
            )
            if validation_errors:
                detail = "; ".join(validation_errors)
                return (
                    f"Tool Execution Error: Schema validation failed "
                    f"for '{tool_name}' -- {detail}"
                )

            # 4. Execute tool
            result = TOOL_REGISTRY[tool_name](**arguments)
            return f"Observation: {result}"

        except Exception as e:
            # Catches tool-raised errors (ValueError, TypeError, ...)
            # AND payload-coercion errors (JSONDecodeError, TypeError)
            return f"Tool Execution Error: {type(e).__name__} -- {str(e)}"


# 4. Protocol Dispatch Test Suite 


def run_protocol_dispatch_tests() -> None:
    """Automated assert-based test suite for the Tool Protocol Dispatcher.

    Validates that:
    - Successful tool executions return Observation strings.
    - Invalid / malformed JSON payloads return formatted errors (NO CRASH).
    - Missing, wrong-type, and unexpected arguments are caught.
    - Boolean values do not leak through as integers or numbers.
    - NaN / inf are rejected for number fields.
    - Runtime exceptions (ValueError) are caught by the error boundary.
    """
    d = ActionDispatcher()

    # -- Successful calls ------------------------------------------

    # T01: Valid warp vector
    r = d.dispatch("navigate_warp_vector", {"x": 1.0, "y": 2.0, "z": 3.0})
    assert r.startswith("Observation:"), f"T01 fail: {r}"

    # T02: Valid shield adjustment
    r = d.dispatch("adjust_plasma_shields", {"intensity": 85})
    assert r.startswith("Observation:") and "85%" in r, f"T02 fail: {r}"

    # T03: Valid sensor query
    r = d.dispatch("query_sensor_array", {"target": "escape_corridor"})
    assert r.startswith("Observation:") and "corridor" in r, f"T03 fail: {r}"

    # T04: Unresolved sensor target (valid call, unknown target)
    r = d.dispatch("query_sensor_array", {"target": "phantom_signal"})
    assert r.startswith("Observation:") and "unresolved" in r, f"T04 fail: {r}"

    # -- Unknown tool ----------------------------------------------

    # T05: Non-existent tool
    r = d.dispatch("self_destruct", {"confirm": True})
    assert "Tool Execution Error" in r and "Unknown tool" in r, f"T05 fail: {r}"

    # -- Schema validation errors ----------------------------------

    # T06: Missing required argument
    r = d.dispatch("navigate_warp_vector", {"x": 1.0, "y": 2.0})
    assert "Tool Execution Error" in r and "Missing required" in r, f"T06 fail: {r}"

    # T07: Wrong argument type (string where integer expected)
    r = d.dispatch("adjust_plasma_shields", {"intensity": "high"})
    assert "Tool Execution Error" in r and "Schema validation" in r, f"T07 fail: {r}"

    # T08: Unexpected extra argument
    r = d.dispatch("query_sensor_array", {"target": "core", "mode": "deep"})
    assert "Tool Execution Error" in r and "Unexpected argument" in r, f"T08 fail: {r}"

    # -- Boolean leakage (Python bool is subclass of int) ----------

    # T09: bool must NOT pass as integer
    r = d.dispatch("adjust_plasma_shields", {"intensity": True})
    assert "Tool Execution Error" in r, f"T09 fail: bool leaked through: {r}"

    # T10: bool must NOT pass as number
    r = d.dispatch("navigate_warp_vector", {"x": True, "y": 0.0, "z": 0.0})
    assert "Tool Execution Error" in r, f"T10 fail: bool leaked through: {r}"

    # -- Non-finite rejection (NaN / inf) --------------------------

    # T11: NaN rejected for number field
    r = d.dispatch("navigate_warp_vector", {"x": float("nan"), "y": 0, "z": 0})
    assert "Tool Execution Error" in r, f"T11 fail: NaN leaked through: {r}"

    # T12: inf rejected for number field
    r = d.dispatch("navigate_warp_vector", {"x": float("inf"), "y": 0, "z": 0})
    assert "Tool Execution Error" in r, f"T12 fail: inf leaked through: {r}"

    # -- Invalid / malformed payloads (THE GRADED TEST) ------------

    # T13: Malformed JSON string (missing closing brace)
    r = d.dispatch("adjust_plasma_shields", '{"intensity": 85')
    assert "Tool Execution Error" in r, f"T13 fail: malformed JSON crashed: {r}"

    # T14: None as arguments
    r = d.dispatch("query_sensor_array", None)
    assert "Tool Execution Error" in r, f"T14 fail: None crashed: {r}"

    # T15: List instead of dict
    r = d.dispatch("query_sensor_array", ["escape_corridor"])
    assert "Tool Execution Error" in r, f"T15 fail: list crashed: {r}"

    # T16: Integer instead of dict
    r = d.dispatch("adjust_plasma_shields", 85)
    assert "Tool Execution Error" in r, f"T16 fail: bare int crashed: {r}"

    # T17: Valid JSON string (should parse and succeed)
    r = d.dispatch("adjust_plasma_shields", '{"intensity": 42}')
    assert r.startswith("Observation:") and "42%" in r, f"T17 fail: {r}"

    # -- Error boundary catches runtime ValueError -----------------

    # T18: Shield intensity out of range (ValueError from tool)
    r = d.dispatch("adjust_plasma_shields", {"intensity": 150})
    assert "Tool Execution Error" in r and "ValueError" in r, f"T18 fail: {r}"

    # T19: Negative shield intensity
    r = d.dispatch("adjust_plasma_shields", {"intensity": -10})
    assert "Tool Execution Error" in r and "out of bounds" in r, f"T19 fail: {r}"

    print("[PASS] All 19 Protocol Dispatch tests passed.")


# 5. Main -- Demonstration & Test Execution

if __name__ == "__main__":
    print("=" * 65)
    print("  Subsystem 06: Tool Protocol Dispatcher & Error Boundary")
    print("  Communications & Protocol Officer -- Mission 06")
    print("=" * 65)

    dispatcher = ActionDispatcher()

    # Demo: Successful calls
    print("\n-- Successful Tool Calls --")
    print(dispatcher.dispatch(
        "navigate_warp_vector", {"x": -0.85, "y": 0.52, "z": 0.05}
    ))
    print(dispatcher.dispatch("adjust_plasma_shields", {"intensity": 85}))
    print(dispatcher.dispatch(
        "query_sensor_array", {"target": "escape_corridor"}
    ))

    # Demo: Error boundary catches
    print("\n-- Error Boundary Demonstrations --")
    print(dispatcher.dispatch(
        "adjust_plasma_shields", {"intensity": 150}
    ))
    print(dispatcher.dispatch(
        "adjust_plasma_shields", {"intensity": "max"}
    ))
    print(dispatcher.dispatch("self_destruct", {"confirm": True}))
    print(dispatcher.dispatch("navigate_warp_vector", {"x": 1.0}))

    # Demo: Invalid payload handling (the graded scenario)
    print("\n-- Invalid Payload Handling --")
    print(dispatcher.dispatch(
        "adjust_plasma_shields", '{"intensity": 85'
    ))
    print(dispatcher.dispatch("query_sensor_array", None))
    print(dispatcher.dispatch("query_sensor_array", ["escape_corridor"]))

    # Demo: Bool / NaN rejection
    print("\n-- Bool and NaN Rejection --")
    print(dispatcher.dispatch(
        "adjust_plasma_shields", {"intensity": True}
    ))
    print(dispatcher.dispatch(
        "navigate_warp_vector", {"x": float("nan"), "y": 0, "z": 0}
    ))

    # Automated test suite
    print("\n-- Automated Test Suite (Section 3, Test #2) --")
    run_protocol_dispatch_tests()
