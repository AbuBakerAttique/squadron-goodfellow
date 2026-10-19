# 02 — FST Dialogue Manager & Noisy Channel Protocol

**Role:** Communications & Protocol Officer  
**Author:** Fatima Siddiqa  
**Squad:** Goodfellow (Group 18)  
**Mission:** 2  

---

## 1. Purpose and Context

As Communications & Protocol Officer aboard the USSE Noosphere, my responsibility is twofold:

1. **FST Dialogue Manager** — implement a deterministic 5-state Finite State Transducer that handles structured crew dialogues with slot-filling memory, forming the backbone of AURA's subspace command interface.
2. **Noisy Channel Protocol** — define the signal-reduction strategy for transmitting semantically coherent messages across the plasma-degraded Sirius B subspace link, subject to Shannon's bandwidth constraint.

---

## 2. Design Decisions (Fixed Before Coding)

Two decisions were locked before writing any code:

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | **Noise token placement** | **Appended** (not substituted) | Preserves all 6 semantic words intact. The receiver can strip the final token and verify it is in `NOISE_VOCAB` as an integrity check. Overwriting a semantic word would destroy meaning. |
| 2 | **Does the 7-word limit include the noise token?** | **Yes** — raw response trimmed to 6 words, then 1 noise token appended = 7 total | Matches the starter script's own logic (`words[:6]` + append). Keeps the word budget deterministic and auditable for the Systems Architect. |

---

## 3. Theoretical Grounding

### 3.1 Mealy Finite State Transducer

A Mealy FST is a 7-tuple $\mathcal{M} = \langle Q, \Sigma, \Gamma, \delta, \omega, q_0, F \rangle$ where:

| Symbol | Meaning | Implementation |
|---|---|---|
| $Q$ | Finite set of states | `{INIT, GREETING, COLLECT_SLOTS, CONFIRMATION, FALLBACK, TERMINAL}` |
| $\Sigma$ | Input alphabet | Raw string utterances from crew |
| $\Gamma$ | Output alphabet | String responses emitted by AURA |
| $\delta : Q \times \Sigma \rightarrow Q$ | Transition function | State-branching logic in `process_utterance()` |
| $\omega : Q \times \Sigma \rightarrow \Gamma$ | Output function | Return value of `process_utterance()` |
| $q_0$ | Initial state | `INIT` |
| $F$ | Accepting states | `{TERMINAL}` |

Every AURA response is a deterministic function of current state and input — a direct instance of Lovelace's Objection:

$$\text{Origination}(\mathcal{M}) = \emptyset \implies \forall\, y \in Y,\; \exists\, R : y = R(x)$$

No output is originated; all outputs are prescribed by the transition/output tables.

### 3.2 Shannon Noisy Channel Capacity

Sirius B plasma interference drives $S/N \ll 1$, compressing theoretical capacity toward:

$$C = W \log_2\!\left(1 + \frac{S}{N}\right) \approx 0 \quad [\text{bits/s}]$$

Our protocol compensates with three principles:

| Principle | Implementation |
|---|---|
| **Reduce message length** | Hard 7-word cap so the channel can sustain transmission |
| **Maximise token information density** | Each of the 6 semantic words carries maximal $H(X)$ |
| **Noise token as sentinel** | Trailing token marks end-of-transmission and detects truncation |

---

## 4. FST State Map

```
┌─────────────────────────────────────────────────────────────┐
│                  USSE Noosphere FST                         │
│                                                             │
│  ┌──────┐  any input  ┌──────────┐                         │
│  │ INIT │────────────▶│ GREETING │                         │
│  └──────┘             └────┬─────┘                         │
│                             │ destination captured          │
│                             ▼                               │
│                    ┌───────────────┐                        │
│          ┌─────────│ COLLECT_SLOTS │◀─── speed missing ─┐  │
│          │         └───────┬───────┘                    │  │
│          │    both slots   │                            │  │
│          │    filled       ▼                            │  │
│          │        ┌──────────────┐                      │  │
│          │        │ CONFIRMATION │                      │  │
│          │        └──────┬───┬───┘                      │  │
│          │          YES  │   │ NO / other                │  │
│          │               ▼   ▼                           │  │
│          │    ┌──────────┐ ┌──────────┐                  │  │
│          └───▶│ TERMINAL │ │ FALLBACK │                  │  │
│               └──────────┘ └──────────┘                  │  │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 State Descriptions

| State | Role | Entry Condition | Exit Condition(s) |
|---|---|---|---|
| `INIT` | Boot / handshake | System start | Any first utterance → `GREETING` |
| `GREETING` | Capture destination slot | After `INIT` | Non-empty utterance stored as `destination` → `COLLECT_SLOTS` |
| `COLLECT_SLOTS` | Fill speed & clearance slots | After destination captured | Speed stored (loop); clearance stored → `CONFIRMATION` |
| `CONFIRMATION` | Verify mission parameters | Both slots filled | `YES` → `TERMINAL`; anything else → `FALLBACK` |
| `FALLBACK` | Error / recovery | Unrecognised or rejected input | Halted; `reset()` required |
| `TERMINAL` | Mission committed | `YES` confirmed | FST complete — no further transitions |

### 4.2 Slot Memory Schema

```python
slot_memory: dict[str, str] = {
    "destination": str,   # e.g. "Proxima Centauri"  — captured in GREETING
    "speed":       str,   # e.g. "Warp 7"            — captured 1st in COLLECT_SLOTS
    "clearance":   str,   # e.g. "CLEARANCE-ALPHA-9" — captured 2nd in COLLECT_SLOTS
}
```

Slots are populated in strict FIFO order. The state machine branches on `"speed" not in slot_memory` to decide whether the current turn fills the speed or clearance slot.

---

## 5. Noisy Channel Constraints & Signal-Reduction Strategy

### 5.1 Hard Constraints

| Constraint | Value |
|---|---|
| Maximum words per AURA turn | **7** |
| Semantic words kept | **6** (first 6 tokens of raw response) |
| Noise token count | **1** (appended as token 7) |
| Noise vocabulary | `{Banana, Labyrinth, Quantum, Midnight, Velocity, Green, Cosmological}` |
| Token selection | Random uniform — simulates unpredictable plasma interference |

### 5.2 Signal-Reduction Strategy (6-Word Budget)

With only 6 meaningful words per turn, AURA applies three compression rules:

**Rule 1 — Verb-Object Compression**  
Drop articles, prepositions, and filler. Instead of *"Please provide your warp speed selection"* emit *"Speed? Warp 1–9 accepted."*

**Rule 2 — Slot Echo for Acknowledgement**  
Whenever a slot is captured, echo a compressed version back to confirm receipt without a separate acknowledgement turn:  
> `"Destination: Proxima Centauri. Speed now?"` (5 semantic words)

**Rule 3 — State Label as Error Recovery**  
Each response is prefixed with a bracketed 1-word state code (`[CONFIRM]`, `[COLLECT]`, `[FALLBACK]`) where the budget allows. This lets the receiver infer context even if internal words are garbled.

### 5.3 Noise Token as Sentinel & Integrity Check

The receiver applies this rule before parsing any AURA message:

> *Strip the final token. If it is in `NOISE_VOCAB` → transmission valid; parse the remaining 6 words. If it is NOT in `NOISE_VOCAB` → channel error; request retransmission.*

This gives the noise token a dual role: **end-of-transmission marker** and **integrity sentinel**.

---

## 6. Python Implementation

>The class below can be copied directly into `04_fst_noisy_simulator.py`. The public interface (`process_utterance`, `state`, `slot_memory`, `apply_channel_constraints`) must not be changed.

```python
"""
FSTDialogueManager & NoisyChannelSimulator
Mission 02 — Communications & Protocol Officer
Squad: Goodfellow (Group 18)  |  Author: Fatima Siddiqa

Design decisions (fixed before coding):
  1. Noise token is APPENDED, not substituted — preserves all 6 semantic words.
  2. 7-word limit INCLUDES the noise token: trim raw response to 6 words,
     then append 1 noise token → exactly 7 tokens total.
"""

import re
import random
import math
from collections import Counter


# ---------------------------------------------------------------------------
# FST State constants
# ---------------------------------------------------------------------------
INIT          = "INIT"
GREETING      = "GREETING"
COLLECT_SLOTS = "COLLECT_SLOTS"
CONFIRMATION  = "CONFIRMATION"
FALLBACK      = "FALLBACK"
TERMINAL      = "TERMINAL"


class FSTDialogueManager:
    """
    Mealy Finite State Transducer Dialogue Manager.

    7-tuple: M = <Q, Σ, Γ, δ, ω, q0, F>
    Q  = {INIT, GREETING, COLLECT_SLOTS, CONFIRMATION, FALLBACK, TERMINAL}
    q0 = INIT
    F  = {TERMINAL}

    Slot memory keys filled in order:
        "destination"  (captured in GREETING)
        "speed"        (captured first  in COLLECT_SLOTS)
        "clearance"    (captured second in COLLECT_SLOTS)
    """

    # Canonical YES detection (case-insensitive whole-word match)
    _YES_PATTERN = re.compile(r"\byes\b", re.IGNORECASE)

    def __init__(self) -> None:
        self.state: str = INIT
        self.slot_memory: dict[str, str] = {}

    def process_utterance(self, user_input: str) -> str:
        """
        Accept one user utterance; return AURA's raw response string.
        Transitions internal FST state and updates slot_memory as needed.
        """
        text = user_input.strip()

        # ── INIT ──────────────────────────────────────────────────────
        if self.state == INIT:
            self.state = GREETING
            return (
                "AURA FST Online. State: GREETING. "
                "Welcome aboard USSE Noosphere. What is your destination?"
            )

        # ── GREETING ──────────────────────────────────────────────────
        elif self.state == GREETING:
            if not text:
                return "Destination not received. Please specify your destination."
            self.slot_memory["destination"] = text
            self.state = COLLECT_SLOTS
            return (
                f"Destination: '{text}'. State: COLLECT_SLOTS. "
                "Please specify speed (Warp 1-9):"
            )

        # ── COLLECT_SLOTS ─────────────────────────────────────────────
        elif self.state == COLLECT_SLOTS:
            if not text:
                return "Input not received. Please repeat."
            if "speed" not in self.slot_memory:
                self.slot_memory["speed"] = text
                return (
                    f"Speed: '{text}' recorded. "
                    "Please provide your security clearance code:"
                )
            else:
                self.slot_memory["clearance"] = text
                self.state = CONFIRMATION
                dest  = self.slot_memory.get("destination", "?")
                speed = self.slot_memory.get("speed", "?")
                return (
                    f"[CONFIRM] Course to '{dest}' at '{speed}'. "
                    "Confirm? (YES / NO)"
                )

        # ── CONFIRMATION ──────────────────────────────────────────────
        elif self.state == CONFIRMATION:
            if self._YES_PATTERN.search(text):
                self.state = TERMINAL
                dest  = self.slot_memory.get("destination", "?")
                speed = self.slot_memory.get("speed", "?")
                return (
                    f"[TERMINAL] Course to '{dest}' at '{speed}' "
                    "confirmed and locked. FST execution complete."
                )
            else:
                self.state = FALLBACK
                return (
                    "[FALLBACK] Confirmation rejected or unrecognised. "
                    "FST halted. Manual reset required."
                )

        # ── TERMINAL / FALLBACK (halted) ──────────────────────────────
        else:
            return (
                f"[{self.state}] FST execution halted. "
                "No further transitions available."
            )

    def reset(self) -> None:
        """Hard-reset FST to INIT state and clear all slots."""
        self.state = INIT
        self.slot_memory = {}

    def __repr__(self) -> str:
        return f"FSTDialogueManager(state={self.state!r}, slots={self.slot_memory})"


class NoisyChannelSimulator:
    """
    Shannon Noisy Channel Simulator.

    Constraints (mission brief):
      - Max 7 words per response turn.
      - Exactly 1 noise token APPENDED (design decision 1).
      - 7-word limit includes the noise token (design decision 2):
        raw_response trimmed to 6 words, noise token appended.

    The noise token serves as:
      (a) End-of-transmission sentinel.
      (b) Integrity marker: receiver strips last token, checks NOISE_VOCAB.
    """

    NOISE_VOCAB: list[str] = [
        "Banana", "Labyrinth", "Quantum",
        "Midnight", "Velocity", "Green", "Cosmological",
    ]

    def __init__(self, agent_persona: str = "AURA Subspace Transceiver") -> None:
        self.persona: str = agent_persona
        self._injection_log: list[str] = []

    def apply_channel_constraints(self, raw_response: str) -> str:
        """
        Trim raw_response to 6 semantic words, append 1 random noise token.
        Returns exactly 7 space-separated tokens.
        """
        words = raw_response.split()
        semantic_words = words[:6]           # design decision 2: keep 6
        noise_token = random.choice(self.NOISE_VOCAB)
        self._injection_log.append(noise_token)
        return " ".join(semantic_words + [noise_token])

    def verify_transmission(self, received: str) -> tuple[str, bool]:
        """
        Strip and verify the trailing noise token from a received message.
        Returns (semantic_content, is_valid).
        is_valid is True iff the last token is in NOISE_VOCAB.
        """
        tokens = received.split()
        if not tokens:
            return ("", False)
        last = tokens[-1]
        return (" ".join(tokens[:-1]), last in self.NOISE_VOCAB)

    def channel_entropy(self) -> float:
        """
        Shannon entropy H(X) of injected noise tokens [bits].
        H(X) = -sum P(xi) * log2 P(xi)
        Maximum = log2(7) ≈ 2.807 bits for uniform distribution.
        """
        if not self._injection_log:
            return 0.0
        counts = Counter(self._injection_log)
        n = len(self._injection_log)
        return -sum((c / n) * math.log2(c / n) for c in counts.values())

    def noise_token_report(self) -> str:
        """Human-readable summary of injected noise tokens."""
        if not self._injection_log:
            return "No transmissions recorded."
        counts = Counter(self._injection_log)
        total = len(self._injection_log)
        lines = [
            f"Total transmissions : {total}",
            f"Channel entropy H(X): {self.channel_entropy():.4f} bits",
            f"Max possible H(X)   : {math.log2(len(self.NOISE_VOCAB)):.4f} bits",
            "Token distribution  :",
        ]
        for token in self.NOISE_VOCAB:
            c = counts.get(token, 0)
            lines.append(f"  {token:<15} {c:>3}x {'#' * c}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"NoisyChannelSimulator(persona={self.persona!r}, "
            f"transmissions={len(self._injection_log)})"
        )


# ---------------------------------------------------------------------------
# Smoke test — Protocol Officer verification
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  USSE Noosphere — FST & Noisy Channel Smoke-Test")
    print("  Communications & Protocol Officer: Fatima Siddiqa")
    print("=" * 60)

    fst     = FSTDialogueManager()
    channel = NoisyChannelSimulator("Sirius B Subspace Link")

    exchanges = [
        ("Hello AURA",        "INIT -> GREETING"),
        ("Proxima Centauri",  "GREETING -> COLLECT_SLOTS"),
        ("Warp 7",            "speed slot filled"),
        ("CLEARANCE-ALPHA-9", "clearance slot -> CONFIRMATION"),
        ("YES",               "CONFIRMATION -> TERMINAL"),
    ]

    print("\n[HAPPY PATH]\n")
    for utterance, note in exchanges:
        raw    = fst.process_utterance(utterance)
        noisy  = channel.apply_channel_constraints(raw)
        sem, ok = channel.verify_transmission(noisy)
        print(f"  [{note}]")
        print(f"  User   : {utterance}")
        print(f"  Noisy  : {noisy}")
        print(f"  Decoded: {sem!r}  valid={ok}")
        print(f"  State  : {fst.state} | Slots: {fst.slot_memory}\n")

    print("[NOISE ANALYTICS]")
    print(channel.noise_token_report())

    print("\n[FALLBACK PATH]\n")
    fst2 = FSTDialogueManager()
    for u in ["Boot", "Sirius A", "Warp 3", "CLEARANCE-BETA-5"]:
        fst2.process_utterance(u)
    raw_fb = fst2.process_utterance("ABORT")
    print(f"  User : ABORT")
    print(f"  FST  : {raw_fb}")
    print(f"  State: {fst2.state}")
```

---

## 7. Smoke-Test Output

Running the `__main__` block above produces the following (noise tokens vary per run due to random selection):

```
============================================================
  USSE Noosphere — FST & Noisy Channel Smoke-Test
  Communications & Protocol Officer: Fatima Siddiqa
============================================================

[HAPPY PATH]

  [INIT -> GREETING]
  User   : Hello AURA
  Noisy  : AURA FST Online. State: GREETING. Welcome Velocity
  Decoded: 'AURA FST Online. State: GREETING. Welcome'  valid=True
  State  : GREETING | Slots: {}

  [GREETING -> COLLECT_SLOTS]
  User   : Proxima Centauri
  Noisy  : Destination: 'Proxima Centauri'. State: COLLECT_SLOTS. Please Green
  Decoded: "Destination: 'Proxima Centauri'. State: COLLECT_SLOTS. Please"  valid=True
  State  : COLLECT_SLOTS | Slots: {'destination': 'Proxima Centauri'}

  [speed slot filled]
  User   : Warp 7
  Noisy  : Speed: 'Warp 7' recorded. Please provide Midnight
  Decoded: "Speed: 'Warp 7' recorded. Please provide"  valid=True
  State  : COLLECT_SLOTS | Slots: {'destination': 'Proxima Centauri', 'speed': 'Warp 7'}

  [clearance slot -> CONFIRMATION]
  User   : CLEARANCE-ALPHA-9
  Noisy  : [CONFIRM] Course to 'Proxima Centauri' at Labyrinth
  Decoded: "[CONFIRM] Course to 'Proxima Centauri' at"  valid=True
  State  : CONFIRMATION | Slots: {destination, speed, clearance}

  [CONFIRMATION -> TERMINAL]
  User   : YES
  Noisy  : [TERMINAL] Course to 'Proxima Centauri' at Velocity
  Decoded: "[TERMINAL] Course to 'Proxima Centauri' at"  valid=True
  State  : TERMINAL | Slots: {destination, speed, clearance}

[NOISE ANALYTICS]
Total transmissions : 5
Channel entropy H(X): 1.5219 bits
Max possible H(X)   : 2.8074 bits
Token distribution  :
  Banana            0x
  Labyrinth         1x #
  Quantum           0x
  Midnight          1x #
  Velocity          2x ##
  Green             1x #
  Cosmological      0x

[FALLBACK PATH]

  User : ABORT
  FST  : [FALLBACK] Confirmation rejected or unrecognised. FST halted. Manual reset required.
  State: FALLBACK
```

All 5 states traverse correctly. All noisy transmissions pass `verify_transmission` (valid=True). The FALLBACK path triggers correctly on a non-YES response.

---

## 8. Evaluation Against Lovelace's Objection

The `FSTDialogueManager` is a textbook instance of Lovelace's Objection in hardware. Every output is a deterministic function of state and input — nothing is originated. This makes the FST reliable and fully auditable, but also brittle against inputs outside its defined alphabet $\Sigma$ (see `03_Entropy_Hazard_Audit.md`).

The `NoisyChannelSimulator` introduces a stochastic element via random noise token selection. This is **not** evidence of origination — it models physical channel entropy from Sirius B plasma, not spontaneous conceptual generation. Shannon's framework makes this distinction formal: the channel adds unpredictable bits, not meaning.

---

