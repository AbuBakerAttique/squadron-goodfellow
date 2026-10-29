"""
Mission 06 — Part 3: Data & Payload Specialist
Infinite Loop Sentinel & State History Hashing

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-06-CAR (Eta Carinae & Homunculus Nebula)
Subsystem 06: Autonomous Warp State Machine & Deliberation Loop
"""

import hashlib
import json
from typing import List, Dict, Any, Tuple


class InfiniteLoopSentinel:
    """
    Prevents AURA from falling into cyclic action-observation traps
    by hashing (thought, action, observation) triples.
    """
    def __init__(self, repeat_threshold: int = 3):
        self.repeat_threshold = repeat_threshold
        self.history_hashes: List[str] = []

    def compute_step_hash(self, action: str, arguments: Dict[str, Any]) -> str:
        """Generates deterministic SHA-256 hash of the intended action and parameters."""
        serialized = json.dumps({"action": action, "arguments": arguments}, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def check_loop(self, action: str, arguments: Dict[str, Any]) -> Tuple[bool, int]:
        """
        Inspects whether the identical action has been repeated sequentially.
        Returns:
            (is_loop_detected, current_repeat_count)
        """
        step_hash = self.compute_step_hash(action, arguments)
        self.history_hashes.append(step_hash)

        # Count consecutive identical steps from recent history
        consecutive_count = 0
        for h in reversed(self.history_hashes):
            if h == step_hash:
                consecutive_count += 1
            else:
                break

        is_loop = consecutive_count >= self.repeat_threshold
        return is_loop, consecutive_count


if __name__ == "__main__":
    sentinel = InfiniteLoopSentinel(repeat_threshold=3)
    print("=== Subsystem 06: Infinite Loop Detection Simulation ===")
    
    # Simulate repeated failed query
    action = "query_sensor_array"
    args = {"target": "corrupted_sector"}

    for step in range(1, 5):
        loop_flag, count = sentinel.check_loop(action, args)
        print(f"Cycle {step}: Repeated action count = {count}. Loop detected? {loop_flag}")
        if loop_flag:
            print(">>> [ALARM] Repetitive reflex loop trapped! Triggering System 2 cognitive reset. <<<")
            break
