"""
Mission 08 — Part 2: Communications & Protocol Officer
3-Actor Reflexion Verbal RL & AST Traceback Surgeon (Shinn et al., NeurIPS 2023)

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-08-CYG (Cygnus X-1 & Veil Nebula)
Subsystem 08: ReWOO DAG Planner, Reflexion Surgeon & MemGPT Virtual Pager
"""


import copy
import hashlib
import io
import math
import re
import signal
import sys
import time
import tokenize
import traceback
from collections import deque
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

# TracebackParser — Structured Stack-Trace Diagnostic Extraction

class TracebackParser:
    """Helper utility to extract structured (file, line_number, exception_type, fault_summary) from Python tracebacks."""

    HEADER = "Traceback (most recent call last)"
    FRAME_PATTERN = re.compile(r'File "([^"]+)", line (\d+)')
    # 'Name', 'pkg.mod.Name', or 'Name: message' — matched on an UNINDENTED line only
    EXCEPTION_PATTERN = re.compile(r"^([A-Za-z_][\w.]*)(?::\s*(.*))?$")

    @classmethod
    def _last_block(cls, lines: List[str]) -> List[str]:
        blocks: List[List[str]] = []
        current: List[str] = []
        for ln in lines:
            if ln.startswith(cls.HEADER):
                if current:
                    blocks.append(current)
                current = [ln]
            else:
                current.append(ln)
        if current:
            blocks.append(current)
        return blocks[-1] if blocks else []

    @classmethod
    def parse(cls, stderr_text: str) -> Dict[str, object]:
        block = cls._last_block(stderr_text.splitlines())

        all_frames: List[Tuple[str, str]] = []
        last_frame_idx = -1
        for idx, ln in enumerate(block):
            m = cls.FRAME_PATTERN.search(ln)
            if m:
                all_frames.append((m.group(1), m.group(2)))
                last_frame_idx = idx

        file_name, line_number = all_frames[-1] if all_frames else ("unknown.py", "-1")

        exception_type: Optional[str] = None
        fault_summary = ""
        for ln in block[last_frame_idx + 1:]:
            if not ln.strip() or ln[0].isspace() or ln.startswith(cls.HEADER):
                continue
            m = cls.EXCEPTION_PATTERN.match(ln.rstrip())
            if m:
                exception_type = m.group(1)
                fault_summary = (m.group(2) or "").strip()
                break

        if exception_type is None:  # unparseable -> conservative fallback
            exception_type = "RuntimeError"
            fault_summary = stderr_text.strip()

        return {
            "file": file_name,
            "line_number": line_number,
            "exception_type": exception_type,
            "fault_summary": fault_summary,
            "all_frames": all_frames,
        }

# UnitTestEvaluator — Evaluator M_e (grounded external oracle)

class _Timeout:
    """
    Wall-clock guard for candidate code.

      * POSIX main thread: SIGALRM interval timer (interrupts almost anything).
      * Windows / non-main thread: a sys.settrace deadline check that raises
        TimeoutError inside the running Python frames (stops `while True: pass`).

    Limitation: a single long-running C call (e.g. 10 ** 10**9) cannot be interrupted
    by the trace fallback.
    """

    def __init__(self, seconds: float, force_trace: bool = False):
        self.seconds = seconds
        self.force_trace = force_trace
        self._mode = None
        self._old = None

    @staticmethod
    def _handler(signum, frame):
        raise TimeoutError("candidate exceeded time limit")

    def __enter__(self):
        if (not self.force_trace and hasattr(signal, "SIGALRM")
                and hasattr(signal, "setitimer")):
            try:
                self._old = signal.signal(signal.SIGALRM, self._handler)
                signal.setitimer(signal.ITIMER_REAL, self.seconds)
                self._mode = "signal"
                return self
            except ValueError:  # not in the main thread -> use trace fallback
                pass

        deadline = time.monotonic() + self.seconds

        def tracer(frame, event, arg):
            if time.monotonic() > deadline:
                raise TimeoutError("candidate exceeded time limit")
            return tracer

        self._old = sys.gettrace()
        sys.settrace(tracer)
        self._mode = "trace"
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._mode == "signal":
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old)
        elif self._mode == "trace":
            sys.settrace(self._old)
        return False


# A test case: (label, positional args tuple, expected return value)
TestCase = Tuple[str, Tuple, object]


class UnitTestEvaluator:
    """
    Grounded evaluator M_e. Compiles and EXECUTES candidate code, then runs a
    deterministic suite of (label, args, expected) cases against `func_name`.
    Returns (passed, stderr) so it can be used directly as `evaluator_fn`.

    The returned stderr is a Python-style traceback restricted to candidate frames
    (plus a synthetic frame at the function definition for wrong-value failures),
    so TracebackParser works on it exactly as on real stderr.
    """

    SAFE_BUILTINS = (
        "abs all any bool dict divmod enumerate filter float int isinstance len list "
        "map max min range reversed round set sorted str sum tuple zip "
        "Exception ArithmeticError AttributeError AssertionError IndexError KeyError "
        "LookupError NameError StopIteration TypeError ValueError ZeroDivisionError"
    ).split()

    def __init__(
        self,
        func_name: str,
        tests: Sequence[TestCase],
        filename: str = "telemetry_parser.py",
        guard: Optional[Callable[[str], Tuple[bool, str]]] = None,
        timeout_s: float = 2.0,
        force_trace_timeout: bool = False,
    ):
        self.func_name = func_name
        self.tests = list(tests)
        self.filename = filename
        self.guard = guard
        self.timeout_s = timeout_s
        self.force_trace_timeout = force_trace_timeout
        self.runs = 0  # number of real evaluations performed

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _trace(frames: List[Tuple[str, object, str]], exc_line: str) -> str:
        out = ["Traceback (most recent call last):"]
        for fname, lineno, name in frames:
            out.append(f'  File "{fname}", line {lineno}, in {name}')
        out.append(exc_line)
        return "\n".join(out)

    def _from_exception(self, exc: BaseException, func: Optional[Callable]) -> str:
        frames = [
            (fs.filename, fs.lineno, fs.name)
            for fs in traceback.extract_tb(exc.__traceback__)
            if fs.filename == self.filename
        ]
        if not frames:  # raised outside candidate code (e.g. wrong arity)
            lineno = func.__code__.co_firstlineno if func is not None else 1
            frames = [(self.filename, lineno, self.func_name)]
        exc_line = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return self._trace(frames, exc_line)

    @staticmethod
    def _matches(got: object, expected: object) -> bool:
        numeric = (int, float)
        if (isinstance(got, numeric) and isinstance(expected, numeric)
                and not isinstance(got, bool) and not isinstance(expected, bool)):
            return math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-12)
        return got == expected

    # -- evaluator_fn interface -----------------------------------------------
    def __call__(self, code: str) -> Tuple[bool, str]:
        self.runs += 1

        if self.guard is not None:
            ok, reason = self.guard(code)
            if not ok:
                return False, self._trace(
                    [("<sandbox-guard>", 1, "<static-check>")],
                    f"SandboxViolationError: {reason}",
                )

        try:
            compiled = compile(code, self.filename, "exec")
        except SyntaxError as exc:  # includes IndentationError
            return False, self._trace(
                [(self.filename, exc.lineno or 1, "<module>")],
                f"{type(exc).__name__}: {exc.msg}",
            )

        import builtins
        namespace: Dict[str, object] = {
            "__builtins__": {n: getattr(builtins, n) for n in self.SAFE_BUILTINS},
            "__name__": "candidate",
            "math": math,
        }

        try:
            with _Timeout(self.timeout_s, self.force_trace_timeout):
                exec(compiled, namespace)  # defines the candidate function(s)
        except Exception as exc:
            return False, self._from_exception(exc, None)

        func = namespace.get(self.func_name)
        if not callable(func):
            return False, self._trace(
                [(self.filename, 1, "<module>")],
                f"NameError: candidate does not define callable '{self.func_name}'",
            )

        for label, args, expected in self.tests:  # deterministic order, fail-fast
            try:
                with _Timeout(self.timeout_s, self.force_trace_timeout):
                    got = func(*copy.deepcopy(args))
            except Exception as exc:
                return False, self._from_exception(exc, func)
            if not self._matches(got, expected):
                return False, self._trace(
                    [(self.filename, func.__code__.co_firstlineno, self.func_name)],
                    f"AssertionError: {label}: expected {expected!r}, got {got!r}",
                )
        return True, ""


# SelfReflection — M_sr: Verbal Critique Generation

class SelfReflection:
    """Translates structured traceback diagnostics into a natural-language critique r_k."""

    PRESCRIPTION_TABLE: Dict[str, str] = {
        "ZeroDivisionError": "Guard denominator against zero before dividing telemetry flux.",
        "KeyError": "Use dict.get() with a safe default or verify the key exists in the telemetry packet.",
        "IndexError": "Check array bounds before indexing the shockwave sample buffer.",
        "TypeError": "Validate operand types before arithmetic or calls; cast sensor readings to float.",
        "ValueError": "Sanitise input values and reject out-of-range telemetry readings.",
        "AttributeError": "Confirm the object has the expected attribute; check for None sensor returns.",
        "AssertionError": "Output disagreed with the unit-test oracle; re-derive the expected computation and handle the failing input case explicitly.",
        "NameError": "Define every name before use; only whitelisted builtins are available in the sandbox.",
        "SyntaxError": "Fix the syntax error before any behavioural change; keep indentation consistent.",
        "TimeoutError": "Remove unbounded loops; the patch must terminate within the time limit.",
    }

    @staticmethod
    def _offending_line(code: str, line_number: str) -> str:
        try:
            idx = int(line_number) - 1
            lines = code.splitlines()
            return lines[idx].strip() if 0 <= idx < len(lines) else ""
        except ValueError:
            return ""

    def reflect(self, diag: Dict[str, object], failed_code: str) -> str:
        exc = str(diag.get("exception_type", "Exception"))
        short = exc.rsplit(".", 1)[-1]
        line_no = str(diag.get("line_number", "?"))
        summary = str(diag.get("fault_summary", "")) or "(no message)"
        source_file = str(diag.get("file", "unknown.py"))

        if short == "KeyError" and summary != "(no message)":
            prescription = f"Use dict.get() or verify key {summary} exists in telemetry packet."
        else:
            prescription = self.PRESCRIPTION_TABLE.get(
                short, f"Resolve {exc} ({summary}) with explicit input validation."
            )

        offending = self._offending_line(failed_code, line_no)
        where = f" Offending code: `{offending}`." if offending else ""
        return (
            f"[Reflection {source_file}:{line_no} | {exc}]: Fault '{summary}'.{where} "
            f"Constraint for next trial: {prescription}"
        )


# ReflexionSurgeon — Actor -> Evaluator -> Self-Reflection Loop

class ReflexionSurgeon:
    """
    Implements the 3-Actor Verbal Reinforcement Learning loop (Shinn et al., 2023):
      - Actor (M_a): Generates candidate code patches conditioned on bounded episodic memory.
      - Evaluator (M_e): Executes deterministic unit tests / runtime verification (grounded external oracle).
      - Self-Reflection (M_sr): Translates traceback diagnostics into a natural-language critique r_k
        stored in a sliding episodic buffer capped at Omega = 3, with SHA-256 cycle detection.
    """


    def __init__(
        self,
        max_trials: int = 4,
        buffer_cap: int = 3,
        max_consecutive_duplicates: int = 2,
    ):
        if max_trials < 1:
            raise ValueError("max_trials must be >= 1")
        if buffer_cap < 1:
            raise ValueError("buffer_cap (Omega) must be >= 1")
        if max_consecutive_duplicates < 1:
            raise ValueError("max_consecutive_duplicates must be >= 1")

        self.max_trials = max_trials
        self.buffer_cap = buffer_cap  # Omega
        self.max_consecutive_duplicates = max_consecutive_duplicates

        self.episodic_buffer: deque = deque(maxlen=buffer_cap)  # Tail_Omega invariant
        self.patch_hashes: Set[str] = set()
        self.reflector = SelfReflection()

    # -- traceback + reflection ----------------------------------------------
    def parse_traceback(self, stderr_text: str) -> Dict[str, object]:
        return TracebackParser.parse(stderr_text)

    def generate_verbal_reflection(self, diag: Dict[str, object], failed_code: str) -> str:
        """Produce r_k and append it to the bounded buffer (oldest evicted beyond Omega)."""
        reflection = self.reflector.reflect(diag, failed_code)
        self.episodic_buffer.append(reflection)
        return reflection

    # -- duplicate patch detection -------------------------------------------
    @staticmethod
    def normalise_code(code: str) -> str:
        """
        Canonical form for hashing. Tokenises the source, so formatting-only changes
        (blank lines, comments, spacing, indentation width) do not change the hash while
        structural changes do. Falls back to a line-based form if the code does not
        tokenise (e.g. a broken patch).
        """
        try:
            parts: List[str] = []
            for tok in tokenize.generate_tokens(io.StringIO(code).readline):
                if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER):
                    continue
                if tok.type in (tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE):
                    parts.append(tokenize.tok_name[tok.type])
                else:
                    parts.append(f"{tokenize.tok_name[tok.type]}:{tok.string}")
            return "\n".join(parts)
        except (tokenize.TokenError, SyntaxError):
            lines = []
            for ln in code.strip().splitlines():
                ln = re.sub(r"\s+#.*$", "", ln.strip())
                if ln and not ln.startswith("#"):
                    lines.append(ln)
            return "RAW:" + "\n".join(lines)

    def is_duplicate_patch(self, candidate_code: str) -> bool:
        """True if the normalised patch was seen before; otherwise record it and return False."""
        digest = hashlib.sha256(self.normalise_code(candidate_code).encode("utf-8")).hexdigest()
        if digest in self.patch_hashes:
            return True
        self.patch_hashes.add(digest)
        return False

    # -- main loop -----------------------------------------------------------
    def run_repair_loop(
        self,
        initial_code: str,
        evaluator_fn: Callable[[str], Tuple[bool, str]],
        actor_patch_fn: Callable[[str, List[str]], str],
    ) -> Dict[str, object]:
        """
        for k = 1..max_trials:
            duplicate? -> skip evaluation, warn Actor via buffer (abort if repeated)
            evaluate   -> passed? return success
            else       -> parse traceback, reflect (buffer), Actor proposes next patch
        Report keys: success, trials_used, final_code, episodic_buffer, history,
                     duplicate_count, stopped_reason ('passed'|'max_trials'|'cycle_detected').
        """
        current_code = initial_code
        history: List[Dict[str, object]] = []
        duplicate_count = 0
        consecutive_dups = 0
        stopped_reason = "max_trials"
        trials_used = 0

        for trial in range(1, self.max_trials + 1):
            trials_used = trial
            is_dup = self.is_duplicate_patch(current_code)

            if is_dup:
                duplicate_count += 1
                consecutive_dups += 1
                warning = (
                    "[Reflection cycle | DuplicatePatch]: The Actor re-submitted a patch "
                    "already evaluated (SHA-256 match). Constraint for next trial: produce a "
                    "semantically different patch that addresses the most recent failure."
                )
                self.episodic_buffer.append(warning)
                history.append({
                    "trial": trial, "passed": False, "duplicate": True,
                    "skipped_evaluation": True, "reflection": warning,
                })
                if consecutive_dups >= self.max_consecutive_duplicates:
                    stopped_reason = "cycle_detected"
                    break
            else:
                consecutive_dups = 0
                passed, stderr = evaluator_fn(current_code)

                if passed:
                    history.append({
                        "trial": trial, "passed": True, "duplicate": False,
                        "reflection": "PASS",
                    })
                    return {
                        "success": True,
                        "trials_used": trial,
                        "final_code": current_code,
                        "episodic_buffer": list(self.episodic_buffer),
                        "history": history,
                        "duplicate_count": duplicate_count,
                        "stopped_reason": "passed",
                    }

                diag = self.parse_traceback(stderr)
                reflection = self.generate_verbal_reflection(diag, current_code)
                history.append({
                    "trial": trial, "passed": False, "duplicate": False,
                    "exception": diag["exception_type"],
                    "line": diag["line_number"],
                    "file": diag["file"],
                    "reflection": reflection,
                })

            if trial < self.max_trials:
                current_code = actor_patch_fn(current_code, list(self.episodic_buffer))

        return {
            "success": False,
            "trials_used": trials_used,
            "final_code": current_code,
            "episodic_buffer": list(self.episodic_buffer),
            "history": history,
            "duplicate_count": duplicate_count,
            "stopped_reason": stopped_reason,
        }


# UngroundedReflexionBaseline — Intrinsic Self-Correction (Huang et al., 2023)

class UngroundedReflexionBaseline:
    """
    Self-correction WITHOUT an external oracle. Two documented failure modes:

      (A) False positive — the model's own verdict says "looks correct" for broken
          code, so the loop stops with a bug still present.
      (B) No-signal drift — the model keeps "revising" without any grounded error,
          producing cosmetic edits that never change behaviour.
    """

    def __init__(self, max_trials: int = 4):
        self.max_trials = max_trials

    def run_ungrounded_loop(
        self,
        initial_code: str,
        intrinsic_eval_fn: Callable[[str], Tuple[bool, str]],
        ground_truth_fn: Optional[Callable[[str], Tuple[bool, str]]] = None,
    ) -> Dict[str, object]:
        current_code = initial_code
        history: List[Dict[str, object]] = []
        candidates: List[str] = [current_code]
        converged = False

        for trial in range(1, self.max_trials + 1):
            passed, critique = intrinsic_eval_fn(current_code)
            history.append({"trial": trial, "intrinsic_passed": passed, "critique": critique})
            if passed:
                converged = True
                break
            if trial < self.max_trials:
                # No grounded error to act on -> the "revision" is cosmetic.
                current_code = current_code.rstrip() + "\n    # self-correction applied\n"
                candidates.append(current_code)

        report: Dict[str, object] = {
            "converged": converged,
            "trials_used": len(history),
            "final_code": current_code,
            "history": history,
            "candidates": candidates,
        }
        if ground_truth_fn is not None:
            truth_ok, truth_err = ground_truth_fn(current_code)
            report["ground_truth_passed"] = truth_ok
            report["ground_truth_error"] = truth_err
            report["false_positive"] = converged and not truth_ok
        return report

# Verification Harness for Part 2 (Communications & Protocol Officer)

if __name__ == "__main__":
    BAR = "=" * 78
    print(BAR)
    print("  Subsystem 08 (Part 2): Reflexion Surgeon & Traceback Parser Verification")
    print(BAR)

    # ── Test 1: TracebackParser — standard + edge cases ─────────────────────
    print("\n--- Test 1: TracebackParser ---")
    d = TracebackParser.parse(
        'Traceback (most recent call last):\n'
        '  File "telemetry_parser.py", line 3, in normalize_xray_flux\n'
        'ZeroDivisionError: division by zero when window_sec=0')
    assert (d["file"], d["line_number"], d["exception_type"]) == ("telemetry_parser.py", "3", "ZeroDivisionError")
    assert "division by zero" in str(d["fault_summary"]) and len(d["all_frames"]) == 1
    print(f"  Parsed: {d['exception_type']} at {d['file']}:{d['line_number']} | {d['fault_summary']}")

    d = TracebackParser.parse(
        'Traceback (most recent call last):\n'
        '  File "main.py", line 10, in <module>\n    run_diagnostics()\n'
        '  File "diagnostics.py", line 42, in run_diagnostics\n    parse_sensor(data)\n'
        '  File "sensor.py", line 7, in parse_sensor\n'
        'TypeError: cannot unpack non-sequence NoneType')
    assert (d["file"], d["line_number"], d["exception_type"]) == ("sensor.py", "7", "TypeError")
    assert len(d["all_frames"]) == 3
    print(f"  Multi-frame: deepest = {d['file']}:{d['line_number']}, frames={d['all_frames']}")

    d = TracebackParser.parse(
        'Traceback (most recent call last):\n  File "t.py", line 9, in <module>\n    assert f(1)==2\nAssertionError')
    assert d["exception_type"] == "AssertionError" and d["fault_summary"] == ""
    d = TracebackParser.parse(
        'Traceback (most recent call last):\n  File "t.py", line 9, in <module>\nStopIteration')
    assert d["exception_type"] == "StopIteration"
    d = TracebackParser.parse(
        'Traceback (most recent call last):\n  File "t.py", line 9, in f\nmy.mod.CustomFaultError: bad')
    assert d["exception_type"] == "my.mod.CustomFaultError" and d["fault_summary"] == "bad"
    d = TracebackParser.parse(
        'Traceback (most recent call last):\n  File "a.py", line 2, in <module>\nKeyError: \'flux\'\n\n'
        'During handling of the above exception, another exception occurred:\n\n'
        'Traceback (most recent call last):\n  File "c.py", line 1, in h\nValueError: x')
    assert (d["file"], d["exception_type"], d["all_frames"]) == ("c.py", "ValueError", [("c.py", "1")])
    d = TracebackParser.parse("ValueError: a")  # no header / no frames
    assert d["exception_type"] == "ValueError" and d["file"] == "unknown.py"
    d = TracebackParser.parse("sensor went dark")  # unparseable -> fallback
    assert d["exception_type"] == "RuntimeError" and d["fault_summary"] == "sensor went dark"
    print("  [OK] bare AssertionError, StopIteration, dotted names, chained traces, fallbacks verified.")

    # ── Test 2: Grounded repair loop with a REAL executing oracle ───────────
    print("\n--- Test 2: Reflexion Repair Loop (Grounded UnitTestEvaluator, Omega=3) ---")

    BUGGY_CODE_V1 = """
def normalize_xray_flux(packet):
    return packet['flux'] / packet['window_sec']
"""
    PATCH_V2 = """
def normalize_xray_flux(packet):
    if packet['window_sec'] == 0:
        return 0.0
    return packet['flux'] / packet['window_sec']
"""
    PATCH_V3 = """
def normalize_xray_flux(packet):
    flux = packet.get('flux', 0.0)
    window = packet.get('window_sec', 1.0)
    if window == 0:
        return 0.0
    return flux / window
"""
    UNIT_TESTS: List[TestCase] = [
        ("nominal flux",        ({"flux": 10.0, "window_sec": 2.0},), 5.0),
        ("zero window (flare)", ({"flux": 10.0, "window_sec": 0},),   0.0),
        ("missing flux (flip)", ({"window_sec": 2.0},),               0.0),
        ("missing window",      ({"flux": 4.0},),                     4.0),
    ]
    oracle = UnitTestEvaluator("normalize_xray_flux", UNIT_TESTS)

    def scripted_actor(curr_code: str, reflections: List[str]) -> str:
        latest = reflections[-1] if reflections else ""
        if "ZeroDivisionError" in latest:
            return PATCH_V2
        if "KeyError" in latest:
            return PATCH_V3
        return curr_code

    surgeon = ReflexionSurgeon(max_trials=4, buffer_cap=3)
    report = surgeon.run_repair_loop(BUGGY_CODE_V1, oracle, scripted_actor)

    print(f"  Repair Success: {report['success']} in {report['trials_used']} trials "
          f"({oracle.runs} real executions)")
    for step in report["history"]:
        tag = "PASS" if step["passed"] else f"{step.get('exception', '?')} @ line {step.get('line', '?')}"
        print(f"    Trial {step['trial']}: [{tag}] dup={step['duplicate']} | {step['reflection']}")
    print(f"  Episodic Buffer (len={len(report['episodic_buffer'])}), "
          f"duplicates={report['duplicate_count']}, stopped_reason={report['stopped_reason']}")

    assert report["success"] is True and report["trials_used"] == 3
    assert [h.get("exception") for h in report["history"][:2]] == ["ZeroDivisionError", "KeyError"]
    assert report["stopped_reason"] == "passed" and report["duplicate_count"] == 0

    # Oracle sanity: it really executes — it distinguishes right from wrong code
    assert oracle(PATCH_V3) == (True, "")
    ok, err = oracle("def normalize_xray_flux(packet):\n    return 1.0\n")
    assert ok is False and TracebackParser.parse(err)["exception_type"] == "AssertionError"
    ok, err = oracle("def normalize_xray_flux(packet)\n    return 1.0\n")
    assert ok is False and TracebackParser.parse(err)["exception_type"] == "SyntaxError"
    ok, err = oracle("import os\ndef normalize_xray_flux(packet):\n    return 1.0\n")
    assert ok is False and TracebackParser.parse(err)["exception_type"] == "ImportError"
    ok, err = oracle("def normalize_xray_flux(packet):\n    while True:\n        pass\n")
    assert ok is False and TracebackParser.parse(err)["exception_type"] == "TimeoutError"
    # Windows-style fallback path (sys.settrace), forced so it is tested on every OS
    trace_oracle = UnitTestEvaluator("normalize_xray_flux", UNIT_TESTS, timeout_s=1.0,
                                     force_trace_timeout=True)
    ok, err = trace_oracle("def normalize_xray_flux(packet):\n    while True:\n        pass\n")
    assert ok is False and TracebackParser.parse(err)["exception_type"] == "TimeoutError"
    guarded = UnitTestEvaluator("normalize_xray_flux", UNIT_TESTS,
                                guard=lambda c: (False, "forbidden import 'os'") if "import os" in c else (True, ""))
    ok, err = guarded("import os\n")
    assert ok is False and "SandboxViolationError" in err
    print("  [OK] Oracle executes code: wrong value, SyntaxError, blocked import, timeout (signal + trace paths), guard hook verified.")

    # ── Test 3: SHA-256 duplicate detection (token-normalised) ──────────────
    print("\n--- Test 3: SHA-256 Duplicate Patch Detection ---")
    s = ReflexionSurgeon()
    assert s.is_duplicate_patch("x = 1") is False
    assert s.is_duplicate_patch("x = 1") is True
    assert s.is_duplicate_patch("x=1  # trailing comment") is True       # comment + spacing
    assert s.is_duplicate_patch("\n\n# header\nx = 1\n\n") is True        # blank lines/comments
    assert s.is_duplicate_patch("x = 2") is False                         # real change
    assert s.is_duplicate_patch("if a:\n    b()\nc()") is False
    assert s.is_duplicate_patch("if a:\n    b()\n    c()") is False      # indentation is semantic
    assert s.is_duplicate_patch("if a:\n  b()\nc()") is True             # indent WIDTH is not
    assert s.is_duplicate_patch("def f(:\n  pass  # broken") is False     # non-tokenising fallback
    assert s.is_duplicate_patch("def f(:\n  pass") is True
    print("  [OK] Comments/blank lines/spacing ignored; structural + indentation changes detected.")

    # ── Test 4: Bounded episodic buffer ─────────────────────────────────────
    print("\n--- Test 4: Bounded Episodic Buffer (Omega=3) ---")
    buf = ReflexionSurgeon(max_trials=10, buffer_cap=3)
    for i in range(5):
        buf.generate_verbal_reflection(
            {"exception_type": "TestError", "line_number": str(i),
             "fault_summary": f"fault_{i}", "file": "test.py"}, f"code_v{i}")
    contents = list(buf.episodic_buffer)
    assert len(contents) == 3 and "fault_2" in contents[0] and "fault_4" in contents[2]
    assert not any("fault_0" in e or "fault_1" in e for e in contents)
    for e in contents:
        print(f"    {e[:78]}...")
    print("  [OK] Tail_Omega invariant: 5 reflections in, newest 3 retained, oldest evicted.")

    # ── Test 5: Grounded vs. ungrounded ─────────────────────────────────────
    print("\n--- Test 5: Grounded vs. Ungrounded Reflexion (Huang et al., 2023) ---")
    base = UngroundedReflexionBaseline(max_trials=4)

    # (A) Overconfident self-check approves the buggy code
    rep_a = base.run_ungrounded_loop(
        BUGGY_CODE_V1,
        intrinsic_eval_fn=lambda c: ("return" in c and "/" in c, "Looks correct to me."),
        ground_truth_fn=oracle)
    print(f"  (A) Intrinsic verdict: converged={rep_a['converged']} in {rep_a['trials_used']} trial(s)")
    print(f"      Real unit tests:   passed={rep_a['ground_truth_passed']} -> {str(rep_a['ground_truth_error']).splitlines()[-1]}")
    assert rep_a["converged"] and rep_a["ground_truth_passed"] is False and rep_a["false_positive"] is True

    # (B) Never-satisfied self-check drifts through cosmetic edits
    rep_b = base.run_ungrounded_loop(
        BUGGY_CODE_V1,
        intrinsic_eval_fn=lambda c: (False, "The code might have edge cases. Consider more checks."),
        ground_truth_fn=oracle)
    probe = ReflexionSurgeon()
    dup_flags = [probe.is_duplicate_patch(c) for c in rep_b["candidates"]]
    print(f"  (B) Converged={rep_b['converged']}; behaviour-identical rewrites flagged by SHA-256: "
          f"{sum(dup_flags)}/{len(dup_flags) - 1}")
    assert rep_b["converged"] is False and rep_b["ground_truth_passed"] is False
    assert dup_flags == [False, True, True, True]

    print(f"  Grounded (unit-test oracle):  SUCCESS in {report['trials_used']} trials, verified by execution")
    print("  Ungrounded (intrinsic eval):  (A) false positive, (B) no-op drift")
    print("  [OK] External grounding (M_e) is what makes Reflexion converge.")

    # ── Test 6: Exhaustion ──────────────────────────────────────────────────
    print("\n--- Test 6: Repair Loop Exhaustion ---")
    fail_trace = ('Traceback (most recent call last):\n  File "broken.py", line 1\n'
                  'RuntimeError: Unrecoverable sensor fault')
    counter = {"n": 0}

    def always_fail(code: str) -> Tuple[bool, str]:
        counter["n"] += 1
        return False, fail_trace

    counter_actor_calls = {"n": 0}

    def varying_actor(code: str, refl: List[str]) -> str:
        counter_actor_calls["n"] += 1
        return code + f"\n# v{counter_actor_calls['n']}\nx{counter_actor_calls['n']} = 0"

    r = ReflexionSurgeon(max_trials=3).run_repair_loop("x = 0", always_fail, varying_actor)
    assert r["success"] is False and r["trials_used"] == 3 and r["stopped_reason"] == "max_trials"
    print(f"  success={r['success']}, trials={r['trials_used']}, stopped_reason={r['stopped_reason']}")
    print("  [OK] Graceful exhaustion handling verified.")

    # ── Test 7: Active cycle handling ───────────────────────────────────────
    print("\n--- Test 7: Active Cycle Detection (Actor stuck in a loop) ---")
    counter["n"] = 0
    r = ReflexionSurgeon(max_trials=6).run_repair_loop("def f(): pass", always_fail, lambda c, rf: c)
    print(f"  trials_used={r['trials_used']}/6, evaluator calls={counter['n']}, "
          f"duplicates={r['duplicate_count']}, stopped_reason={r['stopped_reason']}")
    assert r["stopped_reason"] == "cycle_detected" and r["trials_used"] == 3
    assert counter["n"] == 1, "duplicate patches must not be re-evaluated"
    assert any("DuplicatePatch" in e for e in r["episodic_buffer"])
    print("  [OK] Duplicate patches skip evaluation, warn the Actor via the buffer, and abort on repeat.")

    print("\n" + BAR)
    print("  [OK] Part 2 (Communications & Protocol Officer) — ALL VERIFICATIONS PASSED")
    print(BAR)