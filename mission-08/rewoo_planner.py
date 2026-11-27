"""
Mission 08 — Part 1: Systems Architect (Lead Engineer)
ReWOO (Reasoning Without Observation) Decoupled DAG Planner, Worker & Token Profiler

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-08-CYG (Cygnus X-1 & Veil Nebula)
Subsystem 08: ReWOO DAG Planner, Reflexion Surgeon & MemGPT Virtual Pager
Officer: Abdul Jalil Memon - Squadron Goodfellow

AI assistance: Claude completed the starter, wrote the self-checks and the
prompt-token / parallel-latency benchmark (author review not yet recorded; edit
this line after you have reviewed the code).
Run: python rewoo_planner.py     (verification + self-checks + benchmark)

Briefing requirements covered
-----------------------------
1. parse_blueprint(): "Plan: <reasoning>" + "#E_i = ToolName[raw_arg]" lines
   -> (var_name, plan_desc, tool_name, raw_arg) tuples; to_plan_steps() turns
   them into PlanStep nodes with their #E dependencies.
2. build_dependency_levels(): Kahn-style topological levels; every step in a
   level depends only on earlier levels, so a level can run concurrently.
   execute_dag(): substitutes resolved #E outputs into downstream arguments,
   runs level by level (optionally on a thread pool via max_workers), and calls
   fallback_replan_fn(var_name, error_output) on ERR_ outputs or tool crashes.
3. compare_token_cost(): exact closed-form cumulative input tokens
     C_ReAct(K) = K*L0 + K(K-1)/2 * (L_step + L_obs)        = O(K^2)
     C_ReWOO(K) = 2*L0 + K * (L_step + L_obs)               = O(K)
   returning react_tokens, rewoo_tokens, savings_pct and speedup_ratio.

Starter behaviour kept
----------------------
Same class/method names, signatures, return types and the original harness
(levels [[#E1, #E2], [#E3], [#E4]], K=5 -> 10,000 vs 4,400 tokens).
New arguments are keyword-only with defaults that reproduce the old behaviour.

Defects found in the starter draft and fixed (see _self_checks below)
--------------------------------------------------------------------
* Substitution used str.replace in evidence order, so "#E1" also rewrote the
  prefix of "#E10": in an 11-step plan #E11 received "T1(x1)0" instead of the
  output of #E10. It also re-scanned already substituted text, so a tool
  output that happened to contain "#E2" was overwritten by #E2's value.
  Substitution is now one regex pass over whole tokens (#E\\d+).
* A duplicated "#E1 = ..." line silently dropped one of the steps, and a
  malformed "#E" line (e.g. "#E1 = Tool(x)") was silently ignored, so the plan
  ran with steps missing. Both now raise ValueError with the line number.
* A reference to a never-defined variable was reported as a "cyclic"
  dependency; undefined references and true cycles now get distinct errors.
* A tool that raised an exception bypassed fallback_replan_fn entirely; it is
  now converted to "ERR_TOOL_EXCEPTION: ..." and routed to the fallback (and
  re-raised when no fallback is given, as before).
* An unknown tool name was only detected when its level was reached, after
  earlier tools had already run (side effects). Tools are validated up front.
* "Parallel" levels were always executed one by one; max_workers > 1 now runs
  each level on a thread pool (results are still stored in plan order).
* Negative k_steps / token sizes were accepted and gave meaningless output.

Note on K: ReWOO pays two L0 prompts (Planner + Solver), so with L0 > 0 it is
cheaper than ReAct only from K >= 3 (K = 1, 2 cost more). Proof: C_ReAct -
C_ReWOO = (K-2)*L0 + (L_step+L_obs)*K(K-3)/2, which is -g at K=2, L0 at K=3.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass
class PlanStep:
    """Represents a single symbolic node #E_i = ToolName[raw_arg] in a ReWOO DAG."""
    var_name: str
    plan_desc: str
    tool_name: str
    raw_arg: str
    dependencies: List[str] = field(default_factory=list)


class ReWOOEngine:
    """
    Implements the 3-stage ReWOO (Reasoning Without Observation) paradigm (Xu et al., 2023):
      1. Planner (P): Emits a complete symbolic execution graph (#E1, #E2, ..., #EK) in one LLM call.
      2. Worker (E): Resolves #E variable dependencies in topological levels and executes tools.
      3. Solver (S): Synthesizes final output from resolved evidence in a single final LLM call.
    Also supports dynamic fallback re-planning when a tool emits a runtime sensor fault (e.g. ERR_CORONA_SPIKE).
    """

    VAR_PATTERN = re.compile(r"#E\d+")
    STEP_PATTERN = re.compile(r"^(#E\d+)\s*=\s*(\w+)\[(.*)\]$")
    # A plan line may carry its step inline: "Plan: ... #E1 = Tool[arg]" (ReWOO paper format).
    INLINE_STEP = re.compile(r"\s(#E\d+\s*=\s*\w+\[.*\])$")

    def __init__(self, tools: Dict[str, Callable[[str], str]]):
        self.tools = tools
        # Diagnostics from the most recent execute_dag() call.
        self.last_levels: List[List[str]] = []
        self.failed_steps: Dict[str, str] = {}   # var -> unrecovered ERR_ output
        self.replanned_steps: List[str] = []

    # ------------------------------------------------------------------ Planner
    def parse_blueprint(self, blueprint_text: str) -> List[Tuple[str, str, str, str]]:
        """
        Parse a ReWOO blueprint containing lines formatted as:
            Plan: <reasoning>
            #E1 = ToolName[argument_string_possibly_referencing_#E_vars]
        Return a list of tuples: (var_name, plan_desc, tool_name, raw_arg).
        Raises ValueError on a malformed "#E" line or a duplicated variable name.
        """
        steps: List[Tuple[str, str, str, str]] = []
        seen: Set[str] = set()
        current_plan = ""
        for line_no, line in enumerate(blueprint_text.strip().splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            step_text = None
            if line.startswith("Plan:"):
                current_plan = line[len("Plan:"):].strip()
                inline = self.INLINE_STEP.search(current_plan)
                if inline:
                    step_text = inline.group(1)
                    current_plan = current_plan[: inline.start()].strip()
            elif line.startswith("#E"):
                step_text = line
            if step_text is None:
                continue
            match = self.STEP_PATTERN.match(step_text)
            if not match:
                raise ValueError(f"Malformed ReWOO step on line {line_no}: {step_text!r}")
            var_name, tool_name, raw_arg = match.groups()
            if var_name in seen:
                raise ValueError(f"Duplicate ReWOO variable {var_name} on line {line_no}")
            seen.add(var_name)
            steps.append((var_name, current_plan, tool_name, raw_arg))
        return steps

    def to_plan_steps(self, steps: List[Tuple[str, str, str, str]]) -> List[PlanStep]:
        """Converts parsed 4-tuples into structured PlanStep nodes with extracted #E dependencies."""
        plan_nodes: List[PlanStep] = []
        for var_name, plan_desc, tool_name, raw_arg in steps:
            deps = sorted(set(self.VAR_PATTERN.findall(raw_arg)), key=lambda v: int(v[2:]))
            plan_nodes.append(
                PlanStep(
                    var_name=var_name,
                    plan_desc=plan_desc,
                    tool_name=tool_name,
                    raw_arg=raw_arg,
                    dependencies=deps,
                )
            )
        return plan_nodes

    def build_dependency_levels(self, steps: List[Tuple[str, str, str, str]]) -> List[List[str]]:
        """
        Group step variable names (#E1, #E2, ...) into topological execution levels so that
        independent tool calls in the same level can execute concurrently.
        Raise ValueError if an unresolvable (undefined) or cyclic dependency is detected.
        """
        remaining: Dict[str, Set[str]] = {}
        order_index: Dict[str, int] = {}

        for idx, (var_name, _, _, raw_arg) in enumerate(steps):
            if var_name in remaining:
                raise ValueError(f"Duplicate ReWOO variable {var_name}")
            remaining[var_name] = set(self.VAR_PATTERN.findall(raw_arg))
            order_index[var_name] = idx

        undefined = {
            var: sorted(deps - remaining.keys()) for var, deps in remaining.items() if deps - remaining.keys()
        }
        if undefined:
            raise ValueError(f"Undefined variable reference(s) in ReWOO DAG: {undefined}")

        resolved: Set[str] = set()
        levels: List[List[str]] = []

        while remaining:
            ready = [var for var, deps in remaining.items() if deps.issubset(resolved)]
            if not ready:
                raise ValueError(f"Cyclic variable dependency in ReWOO DAG: {remaining}")
            ready.sort(key=lambda v: order_index[v])
            levels.append(ready)
            for var in ready:
                resolved.add(var)
                del remaining[var]

        return levels

    # ------------------------------------------------------------------ Worker
    def _substitute(self, raw_arg: str, evidence: Dict[str, str]) -> str:
        """Replace whole #E tokens in one pass (no prefix collisions, no re-substitution)."""
        return self.VAR_PATTERN.sub(lambda m: evidence.get(m.group(0), m.group(0)), raw_arg)

    def _run_step(
        self,
        var_name: str,
        tool_name: str,
        resolved_arg: str,
        fallback_replan_fn: Optional[Callable[[str, str], str]],
    ) -> str:
        try:
            output = str(self.tools[tool_name](resolved_arg))
        except Exception as exc:  # a crashing tool is a runtime fault like ERR_
            if fallback_replan_fn is None:
                raise
            output = f"ERR_TOOL_EXCEPTION: {type(exc).__name__}: {exc}"
        if "ERR_" in output and fallback_replan_fn is not None:
            self.replanned_steps.append(var_name)
            output = str(fallback_replan_fn(var_name, output))
        return output

    def execute_dag(
        self,
        steps: List[Tuple[str, str, str, str]],
        fallback_replan_fn: Optional[Callable[[str, str], str]] = None,
        *,
        max_workers: int = 1,
    ) -> Dict[str, str]:
        """
        Resolve variable placeholders (#E1, #E2, ...) in tool arguments and execute each tool
        in topological level order, storing outputs in an evidence dictionary (plan order).
        If a tool output contains 'ERR_' (or the tool raises) and `fallback_replan_fn` is
        provided, invoke `fallback_replan_fn(var_name, error_output)` to recover gracefully.
        max_workers > 1 runs the steps of each level concurrently on a thread pool.
        """
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        step_lookup: Dict[str, Tuple[str, str, str, str]] = {s[0]: s for s in steps}
        levels = self.build_dependency_levels(steps)
        unknown = sorted({s[2] for s in steps if s[2] not in self.tools})
        if unknown:
            raise KeyError(f"Unknown tool(s) referenced in ReWOO plan: {unknown}")

        self.last_levels = levels
        self.failed_steps = {}
        self.replanned_steps = []
        evidence: Dict[str, str] = {}

        pool = ThreadPoolExecutor(max_workers=max_workers) if max_workers > 1 else None
        try:
            for level in levels:
                jobs = []
                for var_name in level:
                    _, _, tool_name, raw_arg = step_lookup[var_name]
                    resolved_arg = self._substitute(raw_arg, evidence)
                    jobs.append((var_name, tool_name, resolved_arg, fallback_replan_fn))
                if pool is not None and len(jobs) > 1:
                    outputs = list(pool.map(lambda job: self._run_step(*job), jobs))
                else:
                    outputs = [self._run_step(*job) for job in jobs]
                for (var_name, *_), output in zip(jobs, outputs):
                    evidence[var_name] = output
                    if "ERR_" in output:
                        self.failed_steps[var_name] = output
        finally:
            if pool is not None:
                pool.shutdown()

        return {s[0]: evidence[s[0]] for s in steps}

    # ------------------------------------------------------------------ Profiler
    @staticmethod
    def compare_token_cost(
        k_steps: int,
        base_tokens: int,
        step_tokens: int,
        obs_tokens: int,
    ) -> Dict[str, float]:
        """
        Compute theoretical cumulative input token cost for K-step ReAct vs. ReWOO:
          C_ReAct = sum_{t=1..K} (base_tokens + (t - 1) * (step_tokens + obs_tokens))
                  = K * base_tokens + (K * (K - 1) // 2) * (step_tokens + obs_tokens)
          C_ReWOO = 2 * base_tokens + K * (step_tokens + obs_tokens)
        Return {'react_tokens': ..., 'rewoo_tokens': ..., 'savings_pct': ..., 'speedup_ratio': ...}.
        """
        if min(k_steps, base_tokens, step_tokens, obs_tokens) < 0:
            raise ValueError("k_steps and token sizes must be non-negative")
        per_turn_growth = step_tokens + obs_tokens
        react_tokens = k_steps * base_tokens + (k_steps * (k_steps - 1) // 2) * per_turn_growth
        rewoo_tokens = 2 * base_tokens + k_steps * per_turn_growth
        savings_pct = ((react_tokens - rewoo_tokens) / react_tokens) * 100.0 if react_tokens > 0 else 0.0
        speedup_ratio = react_tokens / rewoo_tokens if rewoo_tokens > 0 else 1.0
        return {
            "react_tokens": float(react_tokens),
            "rewoo_tokens": float(rewoo_tokens),
            "savings_pct": round(savings_pct, 2),
            "speedup_ratio": round(speedup_ratio, 2),
        }


# ==============================================================================
# Self-checks (regression tests for the defects listed in the module docstring)
# ==============================================================================
def _self_checks() -> None:
    def echo(name: str) -> Callable[[str], str]:
        return lambda arg: f"{name}({arg})"

    tools = {f"T{i}": echo(f"T{i}") for i in range(1, 13)}
    eng = ReWOOEngine(tools)

    # 1. #E1 must not rewrite the prefix of #E10 (11-step plan).
    bp = "\n".join(f"#E{i} = T{i}[x{i}]" for i in range(1, 11)) + "\n#E11 = T11[#E10|#E1]"
    ev = eng.execute_dag(eng.parse_blueprint(bp))
    assert ev["#E11"] == "T11(T10(x10)|T1(x1))", ev["#E11"]

    # 2. Evidence text that mentions "#E2" is not re-substituted.
    e2 = ReWOOEngine({"A": lambda a: "see #E2", "B": lambda a: "BVAL", "C": lambda a: a})
    ev = e2.execute_dag(e2.parse_blueprint("#E1 = A[x]\n#E2 = B[y]\n#E3 = C[#E1 and #E2]"))
    assert ev["#E3"] == "see #E2 and BVAL", ev["#E3"]

    # 3. Duplicate variables and malformed steps are rejected, not dropped.
    for bad in ("#E1 = T1[a]\n#E1 = T2[b]", "#E1 = T1(a)", "Plan: x\n#E2 = Bad Tool[x]"):
        try:
            eng.parse_blueprint(bad)
            raise AssertionError(f"accepted bad blueprint: {bad!r}")
        except ValueError:
            pass

    # 4. Undefined reference vs. true cycle get distinct errors.
    for bp, word in (("#E1 = T1[#E7]", "Undefined"), ("#E1 = T1[#E2]\n#E2 = T2[#E1]", "Cyclic")):
        try:
            eng.build_dependency_levels(eng.parse_blueprint(bp))
            raise AssertionError("dependency error not raised")
        except ValueError as exc:
            assert str(exc).startswith(word), exc

    # 5. A crashing tool is routed to the fallback; without one it still raises.
    e3 = ReWOOEngine({"Boom": lambda a: 1 / 0, "Use": lambda a: f"used({a})"})
    seen: List[str] = []
    ev = e3.execute_dag(
        e3.parse_blueprint("#E1 = Boom[x]\n#E2 = Use[#E1]"),
        fallback_replan_fn=lambda var, err: seen.append(err) or "BACKUP_SENSOR_OK",
    )
    assert seen and seen[0].startswith("ERR_TOOL_EXCEPTION: ZeroDivisionError")
    assert ev["#E2"] == "used(BACKUP_SENSOR_OK)" and e3.replanned_steps == ["#E1"]
    try:
        e3.execute_dag(e3.parse_blueprint("#E1 = Boom[x]"))
        raise AssertionError("exception swallowed without fallback")
    except ZeroDivisionError:
        pass

    # 6. ERR_ output: fallback replaces it; an unrecovered error is recorded.
    e4 = ReWOOEngine({"Scan": lambda a: "ERR_CORONA_SPIKE", "Fuse": lambda a: f"fused({a})"})
    ev = e4.execute_dag(e4.parse_blueprint("#E1 = Scan[s]\n#E2 = Fuse[#E1]"),
                        fallback_replan_fn=lambda v, e: "Scan_Backup=3.9e37")
    assert ev["#E2"] == "fused(Scan_Backup=3.9e37)" and not e4.failed_steps
    e4.execute_dag(e4.parse_blueprint("#E1 = Scan[s]"),
                   fallback_replan_fn=lambda v, e: "ERR_STILL_DOWN")
    assert e4.failed_steps == {"#E1": "ERR_STILL_DOWN"}

    # 7. Unknown tools are rejected before any tool runs.
    calls: List[str] = []
    e5 = ReWOOEngine({"A": lambda a: calls.append(a) or "ok"})
    try:
        e5.execute_dag(e5.parse_blueprint("#E1 = A[x]\n#E2 = Nope[#E1]"))
        raise AssertionError("unknown tool accepted")
    except KeyError:
        assert calls == [], calls

    # 8. Inline "Plan: ... #E1 = Tool[arg]" lines (ReWOO paper format) parse too.
    steps = eng.parse_blueprint("Plan: scan the corona #E1 = T1[c]\nPlan: fuse\n#E2 = T2[#E1]")
    assert steps == [("#E1", "scan the corona", "T1", "c"), ("#E2", "fuse", "T2", "#E1")], steps
    nodes = eng.to_plan_steps(steps)
    assert nodes[1].dependencies == ["#E1"]

    # 9. Parallel execution gives identical evidence in plan order.
    bp = "#E1 = T1[a]\n#E2 = T2[b]\n#E3 = T3[c]\n#E4 = T4[#E1,#E2,#E3]"
    seq = eng.execute_dag(eng.parse_blueprint(bp))
    par = eng.execute_dag(eng.parse_blueprint(bp), max_workers=4)
    assert seq == par and list(par) == ["#E1", "#E2", "#E3", "#E4"]

    # 10. Token formula: closed form == explicit sum, break-even at K=3, input validation.
    for k in range(0, 12):
        m = ReWOOEngine.compare_token_cost(k, 1200, 120, 280)
        assert m["react_tokens"] == sum(1200 + (t - 1) * 400 for t in range(1, k + 1))
    assert ReWOOEngine.compare_token_cost(2, 1200, 120, 280)["savings_pct"] < 0
    assert ReWOOEngine.compare_token_cost(3, 1200, 120, 280)["savings_pct"] > 0
    try:
        ReWOOEngine.compare_token_cost(-1, 1200, 120, 280)
        raise AssertionError("negative K accepted")
    except ValueError:
        pass

    print("[OK] Self-checks passed: #E10 prefix collision, re-substitution, duplicate/malformed steps,")
    print("     undefined vs cyclic refs, tool crash -> fallback, upfront tool check, inline plans,")
    print("     parallel == sequential, closed-form token cost and K=3 break-even.")


# ==============================================================================
# Benchmark: measured prompt tokens (ReAct vs ReWOO) and parallel tool latency
# ==============================================================================
TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    """Deterministic word/punctuation token count (a stand-in for a BPE tokenizer)."""
    return len(TOKEN_RE.findall(text))


SYSTEM_PROMPT = (
    "You are AURA, the navigation agent of the USSE Noosphere in sector SEC-08-CYG. "
    "Solve the task by calling tools. Available tools: TelemetryScan[sector] returns the hard "
    "X-ray flux of a corona sector; PlasmaProbe[region] returns ion density; HohmannCalc[flux, "
    "density] returns an escape delta-v; ShieldModulate[vector] returns a deflector harmonic lock. "
    "Task: compute a safe escape burn out of the Cygnus X-1 accretion corona and lock the shields."
)


def measure_prompt_tokens(engine: ReWOOEngine, blueprint: str) -> Dict[str, int]:
    """
    Build the actual input prompt of every LLM call and count its tokens.
      ReAct: call t sees SYSTEM + all earlier (Thought, Action, Observation) blocks;
             actions carry the *resolved* arguments.
      ReWOO: Planner sees SYSTEM; Solver sees SYSTEM + plan (symbolic #E args) + evidence.
    """
    steps = engine.parse_blueprint(blueprint)
    evidence = engine.execute_dag(steps)
    l0 = count_tokens(SYSTEM_PROMPT)

    react_total, trajectory = 0, ""
    for var, desc, tool, raw in steps:
        react_total += count_tokens(SYSTEM_PROMPT + "\n" + trajectory)
        action_arg = engine._substitute(raw, evidence)
        trajectory += f"Thought: {desc}\nAction: {tool}[{action_arg}]\nObservation: {evidence[var]}\n"

    plan = "".join(f"Plan: {desc}\n{var} = {tool}[{raw}]\n" for var, desc, tool, raw in steps)
    ev_block = "".join(f"{var} = {evidence[var]}\n" for var, *_ in steps)
    rewoo_total = l0 + count_tokens(SYSTEM_PROMPT + "\n" + plan + ev_block)
    return {"k": len(steps), "l0": l0, "react": react_total, "rewoo": rewoo_total,
            "llm_calls_react": len(steps), "llm_calls_rewoo": 2}


def time_execution(blueprint: str, delay_s: float = 0.05) -> Dict[str, float]:
    """Wall-clock of the Worker stage with each tool sleeping delay_s (stand-in for I/O latency)."""
    def slow(name: str) -> Callable[[str], str]:
        def tool(arg: str) -> str:
            time.sleep(delay_s)
            return f"{name}_OK"
        return tool

    names = {s[2] for s in ReWOOEngine({}).parse_blueprint(blueprint)}
    engine = ReWOOEngine({n: slow(n) for n in names})
    steps = engine.parse_blueprint(blueprint)
    out = {"k": len(steps), "levels": len(engine.build_dependency_levels(steps))}
    for label, workers in (("serial_ms", 1), ("parallel_ms", 8)):
        start = time.perf_counter()
        engine.execute_dag(steps, max_workers=workers)
        out[label] = (time.perf_counter() - start) * 1000.0
    return out


CYGNUS_BLUEPRINT = """
Plan: Scan Cygnus X-1 hard X-ray flare flux from primary telemetry array.
#E1 = TelemetryScan[Cygnus_X1_Corona_Sector_08]
Plan: Measure Veil Nebula shockwave plasma density in parallel.
#E2 = PlasmaProbe[Veil_Nebula_Shock_Front]
Plan: Compute Hohmann escape burn vector combining X-ray flux #E1 and plasma density #E2.
#E3 = HohmannCalc[flux=#E1, density=#E2]
Plan: Modulate deflector shield harmonics for burn trajectory #E3.
#E4 = ShieldModulate[vector=#E3]
"""

# K = 8 survey: six independent corona scans, one fusion step, one shield step.
SURVEY_BLUEPRINT = "\n".join(
    [f"Plan: Scan corona sector {i}.\n#E{i} = TelemetryScan[Corona_Sector_0{i}]" for i in range(1, 7)]
    + ["Plan: Fuse all six flux readings into one burn vector.\n"
       "#E7 = HohmannCalc[flux=#E1,#E2,#E3,#E4,#E5,#E6, density=nominal]",
       "Plan: Lock shields for the fused vector.\n#E8 = ShieldModulate[vector=#E7]"]
)


def run_benchmark(tools: Dict[str, Callable[[str], str]]) -> None:
    print("\n--- Benchmark A: measured prompt tokens (regex word/punct tokenizer) ---")
    engine = ReWOOEngine(tools)
    for name, bp in (("Cygnus K=4", CYGNUS_BLUEPRINT), ("Survey K=8", SURVEY_BLUEPRINT)):
        m = measure_prompt_tokens(engine, bp)
        saving = 100.0 * (m["react"] - m["rewoo"]) / m["react"]
        print(f"  {name}: L0={m['l0']} | ReAct={m['react']:5d} tok in {m['llm_calls_react']} calls | "
              f"ReWOO={m['rewoo']:4d} tok in {m['llm_calls_rewoo']} calls | "
              f"savings={saving:5.2f}% ({m['react'] / m['rewoo']:.2f}x)")

    print("\n--- Benchmark B: Worker wall-clock, each tool sleeps 50 ms ---")
    for name, bp in (("Cygnus K=4", CYGNUS_BLUEPRINT), ("Survey K=8", SURVEY_BLUEPRINT)):
        t = time_execution(bp)
        print(f"  {name}: {t['levels']} levels | serial={t['serial_ms']:6.1f} ms | "
              f"level-parallel={t['parallel_ms']:6.1f} ms ({t['serial_ms'] / t['parallel_ms']:.2f}x)")


# ==============================================================================
# Verification Harness for Part 1 (Systems Architect)
# ==============================================================================
if __name__ == "__main__":
    print("=== Subsystem 08 (Part 1): ReWOO DAG Planner & Token Profiler Verification ===")

    BLUEPRINT = CYGNUS_BLUEPRINT

    mock_tools: Dict[str, Callable[[str], str]] = {
        "TelemetryScan": lambda arg: f"XRayFlux({arg})=4.2e37_erg/s",
        "PlasmaProbe": lambda arg: f"IonDensity({arg})=14.8_cm^-3",
        "HohmannCalc": lambda arg: f"DeltaV({arg})=18.4_km/s",
        "ShieldModulate": lambda arg: f"HarmonicLock({arg})=STABLE",
    }

    engine = ReWOOEngine(mock_tools)
    steps = engine.parse_blueprint(BLUEPRINT)
    levels = engine.build_dependency_levels(steps)
    evidence = engine.execute_dag(steps)

    print(f"Parsed Steps ({len(steps)}): {[s[0] for s in steps]}")
    print(f"Topological Parallel Execution Levels: {levels}")
    for k, v in evidence.items():
        print(f"  {k} -> {v}")

    assert levels == [["#E1", "#E2"], ["#E3"], ["#E4"]], f"Unexpected DAG levels: {levels}"
    assert "4.2e37_erg/s" in evidence["#E3"] and "14.8_cm^-3" in evidence["#E3"]
    assert evidence["#E4"].startswith("HarmonicLock(vector=DeltaV(")

    print("\n--- Fallback re-planning: #E1 sensor emits ERR_CORONA_SPIKE ---")
    faulty_tools = dict(mock_tools, TelemetryScan=lambda arg: "ERR_CORONA_SPIKE(saturated)")
    faulty = ReWOOEngine(faulty_tools)
    recovered = faulty.execute_dag(
        steps, fallback_replan_fn=lambda var, err: f"BackupFlux({var})=3.9e37_erg/s"
    )
    print(f"  re-planned: {faulty.replanned_steps} | #E3 -> {recovered['#E3']}")
    assert "3.9e37_erg/s" in recovered["#E3"] and not faulty.failed_steps

    print("\n--- ReAct vs. ReWOO Cumulative Input Token Benchmark (L0=1200, L_step=120, L_obs=280) ---")
    for k in (1, 2, 3, 5, 8):
        metrics = ReWOOEngine.compare_token_cost(k_steps=k, base_tokens=1200, step_tokens=120, obs_tokens=280)
        print(
            f"  K={k} tools | ReAct={int(metrics['react_tokens']):6d} tok | "
            f"ReWOO={int(metrics['rewoo_tokens']):5d} tok | "
            f"Savings={metrics['savings_pct']:7.2f}% ({metrics['speedup_ratio']:.2f}x)"
        )

    m5 = ReWOOEngine.compare_token_cost(5, 1200, 120, 280)
    assert m5["react_tokens"] == 10000.0 and m5["rewoo_tokens"] == 4400.0
    print("[OK] Part 1 (Systems Architect) verification passed.\n")

    _self_checks()
    run_benchmark(mock_tools)
