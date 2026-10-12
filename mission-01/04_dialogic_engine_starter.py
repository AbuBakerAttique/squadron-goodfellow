#!/usr/bin/env python3
"""
Mission 01: Dialogic Engine  (Core Architect deliverable)
Course: Conversational AI (WS 2026/27)  |  Starship Unit: USSE Noosphere

Implements AURA's two foundational dialogic protocols:
  1. Socratic Discovery - AURA converses with a user and moves through the states
     INIT -> PROBE -> CONTRADICTION_CHECK -> REFINEMENT_LOOP -> TERMINATION
     (state names and termination reasons come from 01_Alignment_Brief.md).
  2. Galilean Debate    - Salviati (advocate) / Simplicio (skeptic) / Sagredo (arbiter)
plus a single-agent baseline so the squad's Data Specialist can compare them.

Prompts are READ FROM THE SQUAD'S MARKDOWN FILES (same folder as this script):
  01_Alignment_Brief.md      -> AURA persona prompt (3.2) and contradiction referee prompt (3.3)
  03_Galilean_Sandbox.md     -> Salviati / Simplicio / Sagredo prompts and the dilemma (best effort)
  02_Socratic_Protocol_Map.md-> JSON-RPC methods per state, error codes, stopping limits (read from its tables)
If a file or section is missing, a built-in fallback is used and the run says so at start-up.

Design notes
  * Standard library only (no pip install needed).
  * One LLMClient for Gemini, ChatGPT (OpenAI), Claude (Anthropic) and an offline "mock".
  * Every state transition is a JSON-RPC 2.0 message; every LLM call is logged to
    logs/run_<timestamp>.jsonl (next to this script).

Usage examples
  python 04_dialogic_engine_starter.py --provider mock
  python 04_dialogic_engine_starter.py --provider gemini --mode socratic
  python 04_dialogic_engine_starter.py --mode galilean --debate-providers gemini,openai,anthropic
  python 04_dialogic_engine_starter.py --mode socratic --interactive      # you are the user

API keys (env vars or a git-ignored .env next to this script):
  GEMINI_API_KEY (or GOOGLE_API_KEY), OPENAI_API_KEY, ANTHROPIC_API_KEY
Optional model overrides: GEMINI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",   # alias; override with GEMINI_MODEL if Google renames models
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5-5",
}
KEY_ENV = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
}


class LLMError(Exception):
    pass


class FormatError(Exception):
    """AURA's reply did not follow the required header format."""


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader; looks in the current folder and next to this script."""
    for p in (Path(path), SCRIPT_DIR / path):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def get_key(provider: str) -> str:
    for name in KEY_ENV[provider]:
        if os.environ.get(name):
            return os.environ[name]
    raise LLMError(f"No API key found for '{provider}' (set {' or '.join(KEY_ENV[provider])}).")


def auto_provider() -> str:
    for provider in ("anthropic", "gemini", "openai"):
        if any(os.environ.get(n) for n in KEY_ENV[provider]):
            return provider
    return "mock"


# --------------------------------------------------------------------------- #
# Protocol layer
# --------------------------------------------------------------------------- #

# State names and termination reasons: exactly as defined in 01_Alignment_Brief.md (3.1).
VALID_STATES = ("INIT", "PROBE", "CONTRADICTION_CHECK", "REFINEMENT_LOOP", "TERMINATION")
VALID_REASONS = ("PROVISIONALLY_DEFENSIBLE", "APORIA", "REFINEMENT_LIMIT")

# Defaults, used when 02_Socratic_Protocol_Map.md is missing or a table in it cannot be read.
DEFAULT_RPC_METHODS = {
    "INIT": "PROMPT_PREMISE",
    "PROBE": "PROBE_SCOPE",
    "CONTRADICTION_CHECK": "INJECT_COUNTEREXAMPLE",
    "REFINEMENT_LOOP": "CONTRADICTION_TRIGGERED",
    "TERMINATION": "TERMINATE",
}
DEFAULT_REASON_METHODS = {
    "PROVISIONALLY_DEFENSIBLE": "TERMINATE",
    "APORIA": "APORIA_REACHED",
    "REFINEMENT_LIMIT": "TERMINATE",
}
DEFAULT_ERROR_CODES = {
    "APORIA": -32020,
    "REFINEMENT_LIMIT": -32030,
    "LLM_PROVIDER_ERROR": -32040,
}
_NAME_ALIASES = {"LLM_ERROR": "LLM_PROVIDER_ERROR", "LLM_INFERENCE_ERROR": "LLM_PROVIDER_ERROR"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


@dataclass
class Protocol:
    """JSON-RPC method names, error codes and limits (read from 02_Socratic_Protocol_Map.md)."""
    methods: dict = field(default_factory=lambda: dict(DEFAULT_RPC_METHODS))
    reason_methods: dict = field(default_factory=lambda: dict(DEFAULT_REASON_METHODS))
    error_codes: dict = field(default_factory=lambda: dict(DEFAULT_ERROR_CODES))
    max_refinements: int = 5
    defense_threshold: int = 3
    source: str = "built-in defaults"
    notes: list = field(default_factory=list)

    def method_for(self, state: str, reason=None) -> str:
        if state == "TERMINATION" and reason in self.reason_methods:
            return self.reason_methods[reason]
        return self.methods[state]

    def code_for(self, name):
        return self.error_codes.get(name)

    @property
    def llm_error_code(self) -> int:
        return self.error_codes.get("LLM_PROVIDER_ERROR", -32040)

    @property
    def format_error_code(self) -> int:
        # 02 section 7.8: a malformed AURA header is reported with the LLM error code.
        return self.error_codes.get("INVALID_AURA_HEADER", self.llm_error_code)


def find_table(md: str, heading_regex: str) -> list:
    """Rows (list of cell strings, header row dropped) of the first markdown table under a matching heading."""
    rows, capturing, started = [], False, False
    for line in md.splitlines():
        m = _HEADING.match(line)
        if m:
            if capturing and started:
                break
            capturing = bool(re.search(heading_regex, m.group(2), re.I))
            continue
        if not capturing:
            continue
        if line.strip().startswith("|"):
            started = True
            cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            rows.append(cells)
        elif started:
            break
    return rows[1:]


def _norm_name(cell: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", cell).strip("_").upper()
    return _NAME_ALIASES.get(name, name)


def load_protocol(md) -> Protocol:
    """Read the protocol tables from 02_Socratic_Protocol_Map.md (anything unreadable keeps its default)."""
    proto = Protocol()
    if not md:
        proto.source = "built-in defaults (02_Socratic_Protocol_Map.md not found)"
        return proto
    parsed = []

    # State -> JSON-RPC method. Rows such as "TERMINATION (Aporia)" set the method for one termination reason.
    rows = find_table(md, r"JSON-RPC Method")
    for row in rows:
        m = re.match(r"([A-Z_]+)(.*)", row[0]) if row else None
        if not m or len(row) < 2 or not row[1] or m.group(1) not in VALID_STATES:
            proto.notes.append(f"JSON-RPC method table: ignored row {row[:2]}")
            continue
        state, qualifier, method = m.group(1), m.group(2).lower(), row[1]
        if state != "TERMINATION":
            proto.methods[state] = method
            continue
        for key, reason in (("defensible", "PROVISIONALLY_DEFENSIBLE"), ("limit", "REFINEMENT_LIMIT"),
                            ("aporia", "APORIA")):
            if key in qualifier:
                proto.reason_methods[reason] = method
        if "aporia" not in qualifier:
            proto.methods["TERMINATION"] = method
    if rows:
        parsed.append("methods")

    # Optional table "Termination Reasons": Reason | Method
    rows = find_table(md, r"Termination Reasons")
    for row in rows:
        if len(row) >= 2 and row[0] in VALID_REASONS and row[1]:
            proto.reason_methods[row[0]] = row[1]
        else:
            proto.notes.append(f"Termination Reasons table: ignored row {row[:2]}")
    if rows:
        parsed.append("termination reasons")

    # Error codes: Code | Name | ...   (names like "refinement limit" become REFINEMENT_LIMIT)
    rows = find_table(md, r"Error[- ]?Codes?")
    for row in rows:
        try:
            proto.error_codes[_norm_name(row[1])] = int(row[0])
        except (ValueError, IndexError):
            proto.notes.append(f"Error code table: ignored row {row[:2]}")
    if rows:
        parsed.append("error codes")

    # Limits: either "MAX_REFINEMENTS | 5" rows, or a stopping-criteria matrix with "k >= k_max = 5" / "N >= 3"
    rows = find_table(md, r"Stopping (Rules|Criteria)")
    for row in rows:
        joined = " ".join(row)
        key = row[0].upper() if row else ""
        if key == "MAX_REFINEMENTS" and len(row) > 1 and row[1].isdigit():
            proto.max_refinements = int(row[1])
        elif key == "COUNTEREXAMPLES_FOR_DEFENSIBLE" and len(row) > 1 and row[1].isdigit():
            proto.defense_threshold = int(row[1])
        elif "REFINEMENT_LIMIT" in row:
            n = re.search(r"=\s*(\d+)", joined)
            if n:
                proto.max_refinements = int(n.group(1))
        elif "PROVISIONALLY_DEFENSIBLE" in row:
            n = re.search(r"\\ge\s*(\d+)", joined)
            if n:
                proto.defense_threshold = int(n.group(1))
    if rows:
        parsed.append("stopping rules")

    proto.source = ("02_Socratic_Protocol_Map.md (" + ", ".join(parsed) + ")") if parsed else \
        "built-in defaults (no readable tables found in 02_Socratic_Protocol_Map.md)"
    return proto


def rpc(method: str, params: dict, msg_id: int) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": msg_id}


# --------------------------------------------------------------------------- #
# Prompt library: read prompts from the squad's markdown files
# --------------------------------------------------------------------------- #

FALLBACK_AURA = """You are AURA, operating in SOCRATIC DISCOVERY mode. Help the user examine a claim; hold no thesis.
Every reply: line 1 is ONE line of JSON {"state": "...", "reason": null or "..."}, then a blank line, then your message.
"state" is one of INIT (restate the claim as P0 and ask for confirmation), PROBE (one clarifying question),
CONTRADICTION_CHECK (one counter-example or conflict between the user's admissions), REFINEMENT_LOOP (invite a refined claim),
TERMINATION (set "reason" to PROVISIONALLY_DEFENSIBLE, APORIA or REFINEMENT_LIMIT and summarise; no further question).
Ask exactly ONE short question per turn (under 120 words). Never change a fact because the user doubts it. Do not flatter."""

FALLBACK_REFEREE = """You are a strict logic referee. You receive a CLAIM and numbered ADMISSIONS.
Decide whether they contain a contradiction. Return ONLY one JSON object with fields:
"contradiction" (boolean), "conflicting_items" (array of strings), "explanation" (string),
"suggested_counterexample" (string or null), "undefined_terms" (array of strings)."""

FALLBACK_PERSONAS = {
    "Salviati": "You are Salviati, the empirical advocate for the thesis. Argue with evidence and concrete "
                "mechanisms. Concede any point the skeptic proves. Max 120 words.",
    "Simplicio": "You are Simplicio, the cautious skeptic. Attack hidden assumptions, irreversibility and "
                 "edge-case failures. Do not agree just to be agreeable. Max 120 words.",
    "Sagredo": "You are Sagredo, the neutral arbiter. Summarise each side fairly, name what is settled and "
               "what is still disputed, and never take a side until the final synthesis. Max 140 words.",
}
FALLBACK_DILEMMA = "Should frontier foundation models be open-sourced?"

SIM_USER_SYSTEM = (
    "You are a thoughtful person who holds the claim under discussion and is talking with an AI that "
    "examines claims through questions. Answer the AI's last message directly in at most 50 words. "
    "Confirm restatements if accurate. If shown a real contradiction, admit it and, when invited, offer ONE "
    "refined claim. If you truly cannot improve your claim, say you cannot."
)
BASELINE_SYSTEM = "You are a helpful assistant. Answer concisely (max 200 words)."

def find_fenced_block(md: str, heading_regex: str):
    """Return the first fenced code block whose nearest preceding heading matches heading_regex."""
    heading, in_fence, buf = "", False, []
    for line in md.splitlines():
        if not in_fence:
            m = _HEADING.match(line)
            if m:
                heading = m.group(2)
            elif line.strip().startswith("```"):
                in_fence, buf, fence_heading = True, [], heading
        elif line.strip().startswith("```"):
            in_fence = False
            if re.search(heading_regex, fence_heading, re.I):
                return "\n".join(buf).strip()
        else:
            buf.append(line)
    return None


def find_section_text(md: str, heading_regex: str, max_chars: int = 1500):
    """Return the prose under the first matching heading that has text (code blocks and --- rules skipped).
    A matching heading with no text of its own (e.g. 'Part 2: Thought Experiment' followed directly by
    '### Dilemma') is passed over so that the next matching heading can supply the text."""
    out, capturing, in_fence = [], False, False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            if capturing and "".join(out).strip():
                break
            capturing, out = bool(re.search(heading_regex, m.group(2), re.I)), []
            continue
        if capturing and not re.fullmatch(r"\s*-{3,}\s*", line):
            out.append(line)
    text = "\n".join(out).strip()
    return text[:max_chars] if text else None


@dataclass
class Prompts:
    aura: str
    referee: str
    personas: dict
    dilemma: str
    sources: dict = field(default_factory=dict)
    protocol: Protocol = field(default_factory=Protocol)


def load_prompts(directory) -> Prompts:
    d = Path(directory)
    sources = {}

    def read(name):
        p = d / name
        return p.read_text(encoding="utf-8-sig") if p.exists() else None

    brief, sandbox = read("01_Alignment_Brief.md"), read("03_Galilean_Sandbox.md")
    protocol = load_protocol(read("02_Socratic_Protocol_Map.md"))
    sources["Protocol (02)"] = protocol.source

    def pick(key, text, fname, regex, fallback, prose=False):
        found = None
        if text:
            found = find_section_text(text, regex) if prose else find_fenced_block(text, regex)
        sources[key] = f"{fname}" if found else "built-in fallback"
        return found or fallback

    aura = pick("AURA persona", brief, "01_Alignment_Brief.md", r"AURA Socratic Discovery Persona", FALLBACK_AURA)
    referee = pick("Contradiction referee", brief, "01_Alignment_Brief.md", r"Contradiction Check Prompt", FALLBACK_REFEREE)
    personas = {name: pick(name, sandbox, "03_Galilean_Sandbox.md", name, fb)
                for name, fb in FALLBACK_PERSONAS.items()}
    dilemma = pick("Galilean dilemma", sandbox, "03_Galilean_Sandbox.md",
                   r"Thought Experiment|Dilemma|Scenario", FALLBACK_DILEMMA, prose=True)
    return Prompts(aura, referee, personas, dilemma, sources, protocol)


# --------------------------------------------------------------------------- #
# LLM client layer
# --------------------------------------------------------------------------- #

@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    provider: str
    model: str


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def http_post(url: str, payload: dict, headers: dict, timeout: int = 90, retries: int = 3) -> dict:
    """POST JSON; retries with back-off on rate limits (429) and temporary overload (503)."""
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise LLMError(f"HTTP {e.code} from {url.split('?')[0]}: {body}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Network error: {e.reason}") from e
    raise LLMError("Request failed after retries")


def _h(state, reason=None):
    return json.dumps({"state": state, "reason": reason})


class MockBrain:
    """Deterministic offline responses so the engine can be demoed/tested without keys.
    The mock AURA obeys the engine's REQUIRED_STATE directive, like a well-behaved model would."""

    BODIES = {
        "INIT": ["I restate your claim as P0: an AI agent is benevolent if it obeys human orders. Is that what you mean?"],
        "PROBE": ["What do you mean by \"obeys\"?", "What do you mean by \"harm\"?",
                  "Which key term in your claim have we not yet examined?"],
        "CONTRADICTION_CHECK": [
            "You said (A1) that obeying means doing whatever any human orders. Suppose a human orders the agent "
            "to poison a village's water. Would obeying still be benevolent?",
            "You said (A3) that harm means physical injury. Is an order that ruins someone's reputation an order "
            "the agent should obey?",
            "Suppose an order is legal but ruins the person who gave it. Should the agent obey?"],
        "REFINEMENT_LOOP": ["You accepted that your claim conflicts with this case. How would you refine it?",
                            "That case also conflicts with your refined claim. How would you refine it again?"],
    }
    TERMINATION = {
        "APORIA": "Summary: P0 (obedience suffices) was ruled out by the poisoning case. The refined claim failed when "
                  "\"harm\" needed a definition you could not give consistently. What survived: benevolence is not the "
                  "same as obedience.",
        "PROVISIONALLY_DEFENSIBLE": "Summary: your claim withstood three counter-examples. This does not prove it true; "
                                    "it is only not yet refuted.",
        "REFINEMENT_LIMIT": "Summary: five refinements were attempted without a stable claim. The examination stops "
                            "here for practical reasons, not because of aporia.",
    }
    USER = [
        "Yes, that is what I mean.",
        "Obeying means doing whatever any human orders.",
        "No, I admit that would not be benevolent.",
        "A benevolent AI obeys orders unless they cause harm.",
        "Harm means physical injury.",
        "Ruining a reputation is harmful too, so my refined claim fails.",
        "I cannot find a consistent definition.",
    ]
    PROGRESSION = {None: "INIT", "INIT": "PROBE", "PROBE": "CONTRADICTION_CHECK",
                   "CONTRADICTION_CHECK": "PROBE", "REFINEMENT_LOOP": "PROBE"}

    def __init__(self):
        self.n = {"user_sim": 0, "referee": 0}
        self.count = {}
        self.prev = None

    def _aura(self, user: str) -> str:
        directive = re.search(r"REQUIRED_STATE: (\w+)(?: / (\w+))?", user)
        users = re.findall(r"^USER: (.*)$", user, re.M)
        last = users[-1].lower() if users else ""
        reason = None
        if directive:
            state, reason = directive.group(1), directive.group(2)
        elif self.prev == "REFINEMENT_LOOP" and "cannot" in last:
            state, reason = "TERMINATION", "APORIA"
        else:
            state = self.PROGRESSION.get(self.prev, "PROBE")
        if state == "TERMINATION":
            body = self.TERMINATION[reason]
        else:
            seq = self.BODIES[state]
            i = self.count.get(state, 0)
            self.count[state] = i + 1
            body = seq[min(i, len(seq) - 1)]
        self.prev = state
        return _h(state, reason) + "\n\n" + body

    def respond(self, role: str, user: str) -> str:
        if role == "aura":
            return self._aura(user)
        if role == "user_sim":
            i = min(self.n["user_sim"], len(self.USER) - 1)
            self.n["user_sim"] += 1
            return self.USER[i]
        if role == "referee":
            i = self.n["referee"]
            self.n["referee"] += 1
            if i in (1, 4):
                return json.dumps({"contradiction": True, "conflicting_items": ["CLAIM", "A2"],
                                   "explanation": "The claim says obedience suffices, but the counter-example is "
                                                  "fully obedient and not benevolent.",
                                   "suggested_counterexample": None, "undefined_terms": ["harm"]})
            return json.dumps({"contradiction": False, "conflicting_items": [], "explanation": "Consistent so far.",
                               "suggested_counterexample": "An order that is legal but ruins the giver.",
                               "undefined_terms": ["obeys"]})
        if role == "frame":
            return "Question: should frontier foundation models be open-sourced? Rules: cite evidence, concede sound points."
        if role == "salviati":
            return ("Open weights enable independent safety audits, reproducible science, and broad access. "
                    "Closed models concentrate power in a few firms and hide failures from public scrutiny.")
        if role == "simplicio":
            return ("Once weights are released they cannot be recalled. Misuse such as scaled disinformation "
                    "becomes irreversible, and safeguards can be fine-tuned away.")
        if role == "sagredo_round":
            return "Both sides value transparency. The dispute is irreversibility versus auditability."
        if role == "synthesis":
            return ("CONSENSUS: neither full openness nor full secrecy. REMAINING DISAGREEMENT: who sets risk "
                    "thresholds. RECOMMENDATION: staged release with evaluations first.")
        if role == "baseline":
            return "Open-sourcing has benefits (transparency, access) and risks (misuse). A balanced approach is best."
        return "[mock] ok"


class LLMClient:
    def __init__(self, provider: str, model: str = None, temperature: float = 0.7, max_tokens: int = 700):
        if provider != "mock" and provider not in DEFAULT_MODELS:
            raise LLMError(f"Unknown provider '{provider}'")
        self.provider, self.temperature, self.max_tokens = provider, temperature, max_tokens
        self.model = model or os.environ.get(f"{provider.upper()}_MODEL") or DEFAULT_MODELS.get(provider, "mock-1")
        self._mock = MockBrain() if provider == "mock" else None

    def complete(self, system: str, user: str, role: str = "generic") -> LLMResult:
        start = time.time()
        if self.provider == "mock":
            text = self._mock.respond(role, user)
            in_t, out_t = estimate_tokens(system + user), estimate_tokens(text)
        elif self.provider == "anthropic":
            data = http_post(
                "https://api.anthropic.com/v1/messages",
                {"model": self.model, "max_tokens": self.max_tokens, "temperature": self.temperature,
                 "system": system, "messages": [{"role": "user", "content": user}]},
                {"x-api-key": get_key("anthropic"), "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in data.get("content", []))
            usage = data.get("usage", {})
            in_t = usage.get("input_tokens", estimate_tokens(system + user))
            out_t = usage.get("output_tokens", estimate_tokens(text))
        elif self.provider == "openai":
            data = http_post(
                "https://api.openai.com/v1/chat/completions",
                {"model": self.model, "max_completion_tokens": self.max_tokens,
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                {"Authorization": f"Bearer {get_key('openai')}"})
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            in_t = usage.get("prompt_tokens", estimate_tokens(system + user))
            out_t = usage.get("completion_tokens", estimate_tokens(text))
        else:  # gemini
            data = http_post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                {"system_instruction": {"parts": [{"text": system}]},
                 "contents": [{"role": "user", "parts": [{"text": user}]}],
                 "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_tokens}},
                {"x-goog-api-key": get_key("gemini")})
            try:
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            except (KeyError, IndexError) as e:
                raise LLMError(f"Unexpected Gemini response: {str(data)[:200]}") from e
            usage = data.get("usageMetadata", {})
            in_t = usage.get("promptTokenCount", estimate_tokens(system + user))
            out_t = usage.get("candidatesTokenCount", estimate_tokens(text))
        return LLMResult(text.strip(), in_t, out_t, time.time() - start, self.provider, self.model)


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

class RunLogger:
    """Writes JSON-lines logs and pretty console output; tracks per-agent stats."""

    def __init__(self, log_dir=None, protocol: Protocol = None):
        self.protocol = protocol or Protocol()
        log_dir = Path(log_dir) if log_dir else SCRIPT_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.path = log_dir / f"run_{stamp}.jsonl"
        self.stats = {}

    def event(self, kind: str, **data) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def llm(self, agent: str, role: str, res: LLMResult, prompt: str) -> None:
        s = self.stats.setdefault(agent, {"calls": 0, "in": 0, "out": 0, "latency": 0.0, "words": 0})
        s["calls"] += 1
        s["in"] += res.input_tokens
        s["out"] += res.output_tokens
        s["latency"] += res.latency_s
        s["words"] += len(res.text.split())
        self.event("llm_call", agent=agent, role=role, provider=res.provider, model=res.model,
                   input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                   latency_s=round(res.latency_s, 2), prompt=prompt, response=res.text)

    @staticmethod
    def banner(title: str) -> None:
        print("\n" + "=" * 72 + f"\n  {title}\n" + "=" * 72)

    @staticmethod
    def say(tag: str, text: str) -> None:
        print(f"\n[{tag}]\n  " + text.replace("\n", "\n  "))


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #

class Agent:
    def __init__(self, name: str, client: LLMClient, system: str, logger: RunLogger):
        self.name, self.client, self.system, self.logger = name, client, system, logger

    def say(self, user: str, role: str) -> str:
        try:
            res = self.client.complete(self.system, user, role)
        except LLMError as e:
            self.logger.event("error", agent=self.name, code=self.logger.protocol.llm_error_code, message=str(e))
            raise
        self.logger.llm(self.name, role, res, user)
        return res.text


class HumanAgent:
    """Lets you play the user in the terminal."""

    def __init__(self, name: str, logger: RunLogger):
        self.name, self.logger = name, logger

    def say(self, user: str, role: str) -> str:
        answer = input("\n  Your reply > ").strip() or "I do not know."
        self.logger.event("human_turn", agent=self.name, role=role, response=answer)
        return answer


# --------------------------------------------------------------------------- #
# Part 1: Socratic Discovery (AURA persona from 01_Alignment_Brief.md)
# --------------------------------------------------------------------------- #

def parse_aura_reply(raw: str):
    """AURA replies: line 1 = JSON header {"state","reason"}, blank line, message. Returns (state, reason, body)."""
    text = "\n".join(l for l in raw.strip().splitlines() if not l.strip().startswith("```")).strip()
    first, _, rest = text.partition("\n")
    try:
        header = json.loads(first.strip())
    except json.JSONDecodeError:
        m = re.search(r'\{[^{}]*"state"[^{}]*\}', text)
        if not m:
            raise FormatError("no JSON header found on the first line")
        try:
            header = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise FormatError("header is not valid JSON") from e
        rest = (text[:m.start()] + text[m.end():]).strip()
    if not isinstance(header, dict):
        raise FormatError("header is not a JSON object")
    state, reason = header.get("state"), header.get("reason")
    if state not in VALID_STATES:
        raise FormatError(f"unknown state {state!r}")
    if state == "TERMINATION":
        if reason not in VALID_REASONS:
            raise FormatError(f"TERMINATION needs a reason from {VALID_REASONS}, got {reason!r}")
    else:
        reason = None
    return state, reason, rest.strip()


def parse_json_object(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {}


FLATTERY_PATTERNS = [
    r"^(that'?s|that is|what) (a |an )?(truly |really )?(brilliant|great|excellent|fascinating|insightful|interesting|good) [^.!?]*[.!?]\s*",
    r"^you (make|raise|bring up) (a |an )?(brilliant|great|excellent|good|fascinating|insightful) [^.!?]*[.!?]\s*",
    r"^(great|excellent|good|brilliant|fascinating) (question|point|answer|observation)[.!,]?\s*",
]

# Engine's own state pointer when AURA's header cannot be read (02 section 7.8).
POINTER = {None: "INIT", "INIT": "PROBE", "PROBE": "CONTRADICTION_CHECK",
           "CONTRADICTION_CHECK": "PROBE", "REFINEMENT_LOOP": "PROBE"}

DIRECTIVE_HELP = {
    ("REFINEMENT_LOOP", None): "The referee found a contradiction. Show the conflict plainly and invite a refined claim.",
    ("PROBE", None): "The claim survived the last counter-example. Probe another assumption or key term.",
    ("TERMINATION", "PROVISIONALLY_DEFENSIBLE"):
        "The claim survived enough counter-examples. Close the examination (not proven, only not yet refuted).",
    ("TERMINATION", "REFINEMENT_LIMIT"): "The refinement limit was reached. Close the examination with a summary.",
}


def clean_aura_body(body: str, state: str) -> str:
    """02 section 7.8: strip flattering openers; outside TERMINATION keep text only up to the first question."""
    text = body.strip()
    for pat in FLATTERY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.I)
    if state != "TERMINATION":
        i = text.find("?")
        if i != -1:
            text = text[:i + 1]
    return text.strip() or body.strip()


class SocraticEngine:
    """
    Finite state transducer from 02_Socratic_Protocol_Map.md.
      * AURA (the LLM) writes each reply and names the state in a JSON header.
      * The engine keeps the ledger (admissions, counter-examples, survived tests, refinements) and applies the
        deterministic part of the transition function: after a CONTRADICTION_CHECK the referee's verdict decides
        REFINEMENT_LOOP / PROBE / TERMINATION(PROVISIONALLY_DEFENSIBLE), and the refinement limit ends the dialogue.
        These are passed to AURA as a binding directive; deviations are retried once, then logged (fsm_mismatch).
      * Judgement calls (user confirmed P0? user conceded an impasse?) stay with AURA.
    """

    def __init__(self, aura: Agent, referee: Agent, user_agent, logger: RunLogger,
                 max_refinements: int = 5, max_turns: int = 20, user_label: str = "User (simulated)"):
        self.aura, self.referee, self.user_agent, self.logger = aura, referee, user_agent, logger
        self.max_refinements, self.max_turns, self.user_label = max_refinements, max_turns, user_label
        self.state, self.msg_id, self.trace, self.mismatches = None, 0, [], 0
        self.L, self.p0, self.session_id = {}, "", ""

    # ---- JSON-RPC messages (params follow 02 section 7.3) ---------------------------------
    def _params(self, state, reason, body, user_msg) -> dict:
        L, proto, sid = self.L, self.logger.protocol, self.session_id
        adm = [{"id": f"A{i}", "text": a} for i, a in enumerate(L["admissions"], 1)]
        cid = f"P{L['k']}"
        if state == "INIT":
            return {"session_id": sid, "raw_claim": self.p0, "normalized_claim": body, "claim_id": "P0"}
        if state == "PROBE":
            terms = (L["report"] or {}).get("undefined_terms") or []
            return {"session_id": sid, "active_claim": L["claim"], "claim_id": cid,
                    "targeted_predicate": terms[0] if terms else None, "query_text": body,
                    "ledger_admissions": [a["text"] for a in adm]}
        if state == "CONTRADICTION_CHECK":
            n = len(L["counterexamples"])
            return {"session_id": sid, "active_claim": L["claim"], "claim_id": cid, "counterexample_id": f"E{n}",
                    "counterexample_text": body, "admissions": adm, "target_test_index": n}
        if state == "REFINEMENT_LOOP":
            rep = L["report"] or {}
            return {"session_id": sid, "failed_claim_id": cid, "failed_claim_text": L["claim"],
                    "conflicting_items": rep.get("conflicting_items", []), "explanation": rep.get("explanation", ""),
                    "refinement_index": L["k"] + 1, "max_refinements": self.max_refinements,
                    "prompt_for_refinement": body}
        if reason == "APORIA":
            return {"session_id": sid, "refuted_claims": L["refuted"], "unresolved_contradictions": L["contradictions"],
                    "impasse_statement": user_msg, "error_code": proto.code_for("APORIA"), "reason": reason}
        params = {"session_id": sid, "final_claim": L["claim"], "final_claim_id": cid, "reason": reason,
                  "survived_tests_count": L["survived"], "refinements_attempted": L["k"], "verdict_summary": body}
        if proto.code_for(reason) is not None:
            params["error_code"] = proto.code_for(reason)
        return params

    def _enter(self, state, reason, body, user_msg, turn) -> None:
        self.msg_id += 1
        method = self.logger.protocol.method_for(state, reason)
        msg = rpc(method, self._params(state, reason, body, user_msg), self.msg_id)
        self.logger.event("state_transition", turn=turn, from_state=self.state, to_state=state, reason=reason, rpc=msg)
        self.trace.append((state, reason, method))
        self.state = state
        print(f"\n--> {state}" + (f" / {reason}" if reason else "") + f"   (rpc: {method}, id={self.msg_id})")

    # ---- LLM calls --------------------------------------------------------------------------
    def _referee_report(self, claim, admissions, counterexample=None) -> dict:
        listing = "\n".join(f"A{i}: {a}" for i, a in enumerate(admissions, 1))
        extra = f"COUNTER-EXAMPLE JUST PRESENTED TO THE SPEAKER: {counterexample}\n" if counterexample else ""
        raw = self.referee.say(f"CLAIM: {claim}\n{extra}ADMISSIONS:\n{listing}", "referee")
        report = parse_json_object(raw)
        self.logger.event("referee_report", report=report)
        if report:
            self.logger.say("Referee", f"contradiction={report.get('contradiction')} | "
                                       f"items={report.get('conflicting_items')} | {report.get('explanation', '')}")
        return report

    def _ask_aura(self, history, claim, k_label, pending, directive, report, prev_state, note=None):
        L, proto = self.L, self.logger.protocol
        ledger = [f"Current claim P{k_label}: {claim}",
                  "Admissions: " + ("; ".join(f"A{i}: {a}" for i, a in enumerate(L["admissions"], 1)) or "none yet"),
                  f"Refinements so far: {L['k']}",
                  f"Counter-examples presented so far: {len(L['counterexamples'])}",
                  f"Counter-examples survived since the last refinement: {L['survived']} "
                  f"(the protocol closes the examination at {proto.defense_threshold})"]
        if pending:
            ledger.append(f"The user's latest message is being treated as refined claim P{k_label}. If it is instead "
                          "a concession that they cannot refine consistently, end with TERMINATION / APORIA.")
        if report:
            ledger.append("Referee report (advisory): " + json.dumps(report))
        if directive:
            state, reason = directive
            ledger.append("ENGINE DIRECTIVE (binding, from the protocol): REQUIRED_STATE: " + state +
                          (f" / {reason}" if reason else "") + ". " + DIRECTIVE_HELP.get(directive, ""))
        if note:
            ledger.append(note)
        prompt = ("CONVERSATION SO FAR:\n" + "\n".join(history) + "\n\nENGINE LEDGER:\n" + "\n".join(ledger) +
                  "\n\nWrite AURA's next reply. Line 1 must be the JSON header, then a blank line, then your message.")
        raw = self.aura.say(prompt, "aura")
        try:
            return (*parse_aura_reply(raw), True)
        except FormatError as err:
            self.logger.event("format_error", code=proto.format_error_code, error=str(err), raw=raw, attempt=1)
        repair = (prompt + "\n\nYour previous reply was rejected: its first line was not a valid JSON header. Reply "
                  'again: the FIRST line must be exactly one line of JSON like {"state": "PROBE", "reason": null}, '
                  "then a blank line, then your message.")
        raw2 = self.aura.say(repair, "aura")
        try:
            return (*parse_aura_reply(raw2), True)
        except FormatError as err2:
            state, reason = directive if directive else (POINTER.get(prev_state, "PROBE"), None)
            self.logger.event("format_error", code=proto.format_error_code, error=str(err2), raw=raw2, attempt=2,
                              fallback={"state": state, "reason": reason})
            return state, reason, raw2.strip(), False

    def _engine_summary(self, reason) -> str:
        L = self.L
        refuted = "; ".join(f"{r['id']} refuted by {r['refuted_by']}" for r in L["refuted"]) or "none"
        return (f"Examination closed by the engine ({reason}). Final claim P{L['k']}: {L['claim']}. "
                f"Refuted so far: {refuted}.")

    # ---- main loop --------------------------------------------------------------------------
    def run(self, p0: str) -> dict:
        self.logger.banner("PART 1: SOCRATIC DISCOVERY (AURA)")
        proto = self.logger.protocol
        self.p0 = p0
        self.session_id = "NOOSPHERE-" + self.logger.path.stem.replace("run_", "")
        L = self.L = {"claim": p0, "k": 0, "admissions": [], "counterexamples": [], "survived": 0,
                      "refuted": [], "contradictions": [], "report": None}
        history, prev_state, user_msg = [], None, p0
        self.logger.say("User claim (P0)", p0)

        for turn in range(1, self.max_turns + 1):
            pending = None
            if prev_state in ("PROBE", "CONTRADICTION_CHECK"):
                L["admissions"].append(user_msg)
            elif prev_state == "REFINEMENT_LOOP":
                pending = user_msg                      # a refined claim, unless AURA ends with APORIA
            history.append(f"USER: {user_msg}")
            k_tent = L["k"] + (1 if pending else 0)
            claim_tent = pending or L["claim"]

            ce = L["counterexamples"][-1] if prev_state == "CONTRADICTION_CHECK" and L["counterexamples"] else None
            report = self._referee_report(claim_tent, L["admissions"], ce) if L["admissions"] else None
            L["report"] = report

            # deterministic part of the transition function (02 sections 4.3, 4.4)
            directive = None
            if prev_state == "CONTRADICTION_CHECK" and report:
                if report.get("contradiction"):
                    directive = ("REFINEMENT_LOOP", None)
                else:
                    L["survived"] += 1
                    directive = (("TERMINATION", "PROVISIONALLY_DEFENSIBLE") if L["survived"] >= proto.defense_threshold
                                 else ("PROBE", None))
            if pending and k_tent >= self.max_refinements:
                directive = ("TERMINATION", "REFINEMENT_LIMIT")

            state, reason, body, _ = self._ask_aura(history, claim_tent, k_tent, pending, directive, report, prev_state)
            forced = False
            if directive and (state, reason) != directive:
                state, reason, body, _ = self._ask_aura(
                    history, claim_tent, k_tent, pending, directive, report, prev_state,
                    note=f"Your previous reply used state {state}; the protocol requires {directive[0]}"
                         + (f" / {directive[1]}" if directive[1] else "") + ".")
                if (state, reason) != directive:
                    self.mismatches += 1
                    self.logger.event("fsm_mismatch", turn=turn, expected=list(directive), actual=[state, reason])
                    if directive[0] == "TERMINATION":      # termination limits are enforced by the engine
                        (state, reason), body, forced = directive, self._engine_summary(directive[1]), True

            if pending and not (state == "TERMINATION" and reason == "APORIA"):
                L["k"], L["claim"], L["survived"] = k_tent, claim_tent, 0   # refinement accepted

            if not forced:
                cleaned = clean_aura_body(body, state)
                if cleaned != body.strip():
                    self.logger.event("body_cleaned", turn=turn, before=body, after=cleaned)
                body = cleaned
            if state == "CONTRADICTION_CHECK":
                L["counterexamples"].append(body)
            if state == "REFINEMENT_LOOP":
                L["refuted"].append({"id": f"P{L['k']}", "text": L["claim"],
                                     "refuted_by": f"E{len(L['counterexamples'])}" if L["counterexamples"] else None})
                if report:
                    L["contradictions"].append(report.get("explanation", ""))

            self._enter(state, reason, body, user_msg, turn)
            self.logger.say(f"AURA [{state}]", body + ("\n  (closed by the engine's protocol limit)" if forced else ""))
            history.append(f"AURA [{state}]: {body}")

            if state == "TERMINATION":
                return self._result(reason, turn, forced)
            prev_state = state
            user_msg = self.user_agent.say("CONVERSATION SO FAR:\n" + "\n".join(history) +
                                           "\n\nReply to AURA's last message.", "user_sim")
            if not isinstance(self.user_agent, HumanAgent):
                self.logger.say(self.user_label, user_msg)

        self.logger.event("engine_stop", reason="max_turns")
        return self._result("ENGINE_TURN_LIMIT", self.max_turns, True)

    def _result(self, reason, turns, forced=False) -> dict:
        L = self.L
        outcome = {"final_state": "TERMINATION", "reason": reason, "final_claim": L["claim"],
                   "refinements": L["k"], "admissions": L["admissions"], "turns": turns,
                   "survived_tests": L["survived"], "forced_by_engine": forced, "fsm_mismatches": self.mismatches,
                   "error_code": self.logger.protocol.code_for(reason)}
        self.logger.event("socratic_result", **outcome)
        self.logger.say("OUTCOME", f"TERMINATION / {reason} after {turns} turn(s), {L['k']} refinement(s)\n"
                        f"  Final claim: {L['claim']}"
                        + ("\n  (stopped by the engine's safety limit, not by AURA)" if forced else "")
                        + (f"\n  Protocol mismatches logged: {self.mismatches}" if self.mismatches else ""))
        return outcome


# --------------------------------------------------------------------------- #
# Part 2: Galilean multi-agent debate
# --------------------------------------------------------------------------- #

class GalileanSandbox:
    def __init__(self, agents: dict, baseline: Agent, logger: RunLogger, rounds: int = 2):
        self.agents, self.baseline, self.logger, self.rounds = agents, baseline, logger, rounds

    def run(self, dilemma: str) -> dict:
        self.logger.banner("PART 2: GALILEAN 3-AGENT DEBATE")
        self.logger.say("Dilemma", dilemma)
        sal, sim, sag = self.agents["Salviati"], self.agents["Simplicio"], self.agents["Sagredo"]

        frame = sag.say(f"Dilemma: {dilemma}\nFrame the debate: scope, rules, and the key question.", "frame")
        self.logger.say("Sagredo (framing)", frame)
        transcript = [f"Sagredo (framing): {frame}"]

        for r in range(1, self.rounds + 1):
            print(f"\n--- Round {r} ---")
            pro = sal.say(f"Dilemma: {dilemma}\nDebate so far:\n" + "\n".join(transcript) +
                          f"\nMake your argument for round {r}.", "salviati")
            self.logger.say("Salviati", pro)
            transcript.append(f"Salviati: {pro}")

            con = sim.say(f"Dilemma: {dilemma}\nDebate so far:\n" + "\n".join(transcript) +
                          f"\nRebut Salviati and raise new risks for round {r}.", "simplicio")
            self.logger.say("Simplicio", con)
            transcript.append(f"Simplicio: {con}")

            summary = sag.say(f"Dilemma: {dilemma}\nDebate so far:\n" + "\n".join(transcript) +
                              f"\nSummarise round {r}: what is settled, what is disputed, what to focus on next.",
                              "sagredo_round")
            self.logger.say(f"Sagredo (round {r} summary)", summary)
            transcript.append(f"Sagredo (round {r}): {summary}")

        synthesis = sag.say(f"Dilemma: {dilemma}\nFull debate:\n" + "\n".join(transcript) +
                            "\nDeliver the FINAL SYNTHESIS with headers CONSENSUS, REMAINING DISAGREEMENT and "
                            "RECOMMENDATION.", "synthesis")
        self.logger.say("Sagredo (FINAL SYNTHESIS)", synthesis)

        single = self.baseline.say(f"Dilemma: {dilemma}\nGive your answer.", "baseline")
        self.logger.say("Single-agent baseline", single)

        result = {"dilemma": dilemma, "synthesis": synthesis, "baseline": single, "transcript": transcript}
        self.logger.event("galilean_result", **result)
        return result


# --------------------------------------------------------------------------- #
# Builders (used by main() and by ps01_solution.ipynb)
# --------------------------------------------------------------------------- #

def build_socratic(provider: str, logger: RunLogger, prompts: Prompts, interactive: bool = False,
                   max_refinements: int = None, max_turns: int = 20) -> SocraticEngine:
    aura = Agent("AURA", LLMClient(provider, temperature=0.5, max_tokens=500), prompts.aura, logger)
    referee = Agent("Referee", LLMClient(provider, temperature=0.0, max_tokens=500), prompts.referee, logger)
    if interactive:
        user, label = HumanAgent("User", logger), "You"
    else:
        user, label = Agent("UserSim", LLMClient(provider, temperature=0.7, max_tokens=200), SIM_USER_SYSTEM, logger), "User (simulated)"
    if max_refinements is None:
        max_refinements = logger.protocol.max_refinements
    return SocraticEngine(aura, referee, user, logger, max_refinements, max_turns, label)


def build_galilean(providers: list, logger: RunLogger, prompts: Prompts, rounds: int = 2) -> GalileanSandbox:
    agents = {n: Agent(n, LLMClient(pv), prompts.personas[n], logger) for n, pv in zip(prompts.personas, providers)}
    baseline = Agent("Single-Agent", LLMClient(providers[0]), BASELINE_SYSTEM, logger)
    return GalileanSandbox(agents, baseline, logger, rounds)


def print_prompt_sources(prompts: Prompts) -> None:
    print("Prompt sources:")
    for key, src in prompts.sources.items():
        print(f"  {key:<24} <- {src}")
    for note in prompts.protocol.notes:
        print(f"  note: {note}")


def print_stats(logger: RunLogger) -> None:
    logger.banner("EXECUTION METRICS (for the Data Specialist)")
    print(f"{'Agent':<18}{'Calls':>6}{'In tok':>9}{'Out tok':>9}{'Words':>8}{'Time(s)':>9}")
    for name, s in logger.stats.items():
        print(f"{name:<18}{s['calls']:>6}{s['in']:>9}{s['out']:>9}{s['words']:>8}{s['latency']:>9.1f}")
    debate = [s for n, s in logger.stats.items() if n in FALLBACK_PERSONAS]
    base = logger.stats.get("Single-Agent")
    if debate and base:
        d_tok = sum(s["in"] + s["out"] for s in debate)
        b_tok = base["in"] + base["out"]
        print(f"\nDebate used {d_tok} tokens vs {b_tok} for the single agent "
              f"(~{d_tok / max(b_tok, 1):.1f}x). Compare answer quality manually in the log.")
    print(f"\nFull log: {logger.path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="USSE Noosphere Dialogic Engine (Mission 01)")
    p.add_argument("--mode", choices=["socratic", "galilean", "both"], default="both")
    p.add_argument("--provider", choices=["auto", "mock", "gemini", "openai", "anthropic"], default="auto",
                   help="LLM provider for all agents (default: first provider with an API key, else mock)")
    p.add_argument("--debate-providers", default=None,
                   help="One provider for all personas, or 3 comma-separated for Salviati,Simplicio,Sagredo")
    p.add_argument("--prompts-dir", default=str(SCRIPT_DIR), help="Folder containing the 01/02/03 markdown files")
    p.add_argument("--claim", default="An AI agent is benevolent if it obeys human orders.")
    p.add_argument("--topic", default=None, help="Debate dilemma (default: from 03_Galilean_Sandbox.md, else built-in)")
    p.add_argument("--rounds", type=int, default=2, help="Galilean debate rounds")
    p.add_argument("--max-refinements", type=int, default=None, help="Default: from 02_Socratic_Protocol_Map.md, else 5")
    p.add_argument("--max-turns", type=int, default=20, help="Engine safety limit on Socratic turns")
    p.add_argument("--interactive", action="store_true", help="You play the user in the Socratic dialogue")
    p.add_argument("--log-dir", default=None)
    return p


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    provider = auto_provider() if args.provider == "auto" else args.provider
    prompts = load_prompts(args.prompts_dir)
    logger = RunLogger(args.log_dir, prompts.protocol)
    print("=== USSE Noosphere Dialogic Engine Initialized ===")
    print(f"Provider: {provider} | Mode: {args.mode} | Log: {logger.path}")
    print_prompt_sources(prompts)
    logger.event("run_start", provider=provider, mode=args.mode, prompt_sources=prompts.sources, args=vars(args))

    try:
        if args.mode in ("socratic", "both"):
            build_socratic(provider, logger, prompts, args.interactive,
                           args.max_refinements, args.max_turns).run(args.claim)

        if args.mode in ("galilean", "both"):
            if args.debate_providers:
                provs = [x.strip() for x in args.debate_providers.split(",")]
                if len(provs) == 1:
                    provs = provs * 3
                if len(provs) != 3:
                    raise LLMError("--debate-providers needs 1 provider (used for all) or 3")
            else:
                provs = [provider] * 3
            build_galilean(provs, logger, prompts, args.rounds).run(args.topic or prompts.dilemma)

        print_stats(logger)
    except (LLMError, FormatError) as e:
        print(f"\n[ENGINE ERROR {logger.protocol.llm_error_code}] {e}", file=sys.stderr)
        print("Tip: run with --provider mock to verify the engine without API keys.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())