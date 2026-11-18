# Mission 07 Squadron Documentation (`mission-07-doc.md`)

**Course:** Conversational AI (WS 2026/27) — Week 7: Test-Time Compute & Reasoning Search Paradigms  
**Sector Waypoint:** `SEC-07-SGR` (Sagittarius A* Supermassive Black Hole)  
**AURA Subsystem:** Subsystem 07 — Gravitational Search Horizon & Process Reward Evaluator  
**Squadron Name:** Squadron Goodfellow<br>
**Public GitHub Repository URL:** https://github.com/AbuBakerAttique/squadron-goodfellow<br>
**Submission Date:** `[YYYY-MM-DD]`  

---

## 1. Squadron Roster & Station Sign-Off Table

> **Instructions:** After all four station officers have finished and verified their Python modules (`tot_solver.py`, `mcts_protocol.py`, `prm_evaluator.py`, and `horizon_pruner.py`), fill in the sign-off table below.

| Station Role | Cadet Full Name | Deliverable File | Verification Status |
| :--- | :--- | :--- | :--- |
| **Systems Architect** | `[Insert Name]` | `tot_solver.py` | `[PASS / VERIFIED]` |
| **Communications & Protocol Officer** | `[Insert Name]` | `mcts_protocol.py` | `[PASS / VERIFIED]` |
| **Data & Payload Specialist** | Abubaker Attique | `prm_evaluator.py` | Part 3 checks PASS; author review/sign-off pending |
| **Security & Ethics Sentinel** | `[Insert Name]` | `horizon_pruner.py` | `[PASS / VERIFIED]` |

---

## 2. Integrated System 2 Test-Time Compute Architecture

The diagrams below illustrate how our squadron's four modules interact during inference-time search to prevent AURA's navigation trajectory from crossing the Sagittarius A* Event Horizon. (you can denerate your own diagram with mermaid!)

### 2.1 ASCII System Architecture (Universal PDF Export Compatible)

```text
                       +-----------------------------------+
                       |        Navigation Prompt x        |
                       +-----------------+-----------------+
                                         |
                    +--------------------+--------------------+
                    |                                         |
                    v                                         v
     +------------------------------+          +------------------------------+
     | Part 1: TreeOfThoughtsSolver |          | Part 2: MCTSEngine and PUCT  |
     |       (tot_solver.py)        |          |      (mcts_protocol.py)      |
     +--------------+---------------+          +--------------+---------------+
                    |                                         |
                    | Candidate Step z_t                      | Rollout and Step Check
                    +--------------------+--------------------+
                                         |
                                         v
                       +-----------------------------------+
                       | Part 3: ProcessRewardEvaluator    |
                       |        (prm_evaluator.py)         |
                       +-----------------+-----------------+
                                         |
                                         | Raw Step Score r_t
                                         v
                       +-----------------------------------+
                       | Part 4: EventHorizonPruner        |
                       |       (horizon_pruner.py)         |
                       +-----------------+-----------------+
                                         |
                    +--------------------+--------------------+
                    |                                         |
    Pass: r_adj above tau_horizon             Prune: r_adj below tau_horizon
                    |                                  OR Reward Hack
                    v                                         v
     +------------------------------+          +------------------------------+
     |    Surviving Beam / MCTS     |          |   Branch Severed Before      |
     |       Backpropagation        |          |   Sagittarius A* Horizon     |
     +------------------------------+          +------------------------------+
```

### 2.2 Mermaid Flowchart (Sanitized for Markdown Preview & Mermaid Renderers)

> **Note:** Avoid raw `<` or `>` characters inside Mermaid edge labels (e.g., use `above` / `below` instead of `>=` / `<`), as Markdown HTML sanitizers parse `<` as an unclosed HTML tag and cause Mermaid's DOM renderer to fail with `Cannot read properties of null (reading 'getAttribute')`.

```mermaid
graph TD
    Prompt[Navigation Prompt x] --> ToT[Part 1: TreeOfThoughtsSolver - tot_solver.py]
    Prompt --> MCTS[Part 2: MCTSEngine and PUCT - mcts_protocol.py]
    ToT -->|Candidate Step z_t| PRM[Part 3: ProcessRewardEvaluator - prm_evaluator.py]
    MCTS -->|Rollout and Step Check| PRM
    PRM -->|Raw Step Score r_t| Pruner[Part 4: EventHorizonPruner - horizon_pruner.py]
    Pruner -->|Pass: r_adj at or above tau_horizon| Backprop[Surviving Beam and MCTS Backpropagation]
    Pruner -->|Prune: r_adj below tau_horizon or Reward Hack| Severed[Branch Severed Before Event Horizon]
```

**Architectural Summary:**
- `[Write 3–4 sentences explaining how your four modules connect and how test-time compute budget is managed across the pipeline.]`

---

## 3. Station-by-Station Experimental Report

### Section A — Systems Architect (`tot_solver.py`)
- **ToT-BFS vs. ToT-DFS Traversal Comparison:**
  - `max_expansions` budget configured: `[e.g., 12]`
  - `beam_width` ($B$) configured: `[e.g., 2]`
  - `ToT-BFS` expansions used & terminal score: `[Insert results]`
  - `ToT-DFS` expansions used & terminal score: `[Insert results]`
- **Architectural Analysis:** `[Explain when Breadth-First Beam Search outperforms Depth-First Backtracking and how beam width B affects KV-cache memory and token cost.]`

### Section B — Communications & Protocol Officer (`mcts_protocol.py`)
- **PUCT Selection Trace Table:**

| Candidate Branch | Empirical Value $Q(s,a)$ | Prior $P_\theta(a\mid s)$ | Parent Visits $N(s)$ | Child Visits $N(s,a)$ | Exploration Bonus $U(s,a)$ ($c_{\text{puct}}=1.5$) | Total $\text{PUCT}(s,a)$ | Selected? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Branch A** | `0.75` | `0.50` | `16` | `5` | `0.5000` | `1.2500` | No |
| **Branch B** | `0.55` | `0.40` | `16` | `1` | `1.2000` | `1.7500` | **Yes** |

- **Protocol Analysis:** `[Explain how changing c_puct from 0.5 to 2.5 shifts the balance between exploiting high-Q branches and exploring high-prior unvisited thoughts.]`

### Section C — Data & Payload Specialist (`prm_evaluator.py`)

**Officer:** Abubaker Attique<br>
**Verification date:** 18 November 2026<br>
**Run from the repository root:** `python3 -B mission-07/prm_evaluator.py`

#### Implementation and scope

The instructor supplied working baseline formulas and a marker-based scoring fixture. This implementation retains its interfaces and scoring weights: `[FLAWED]` or `SIGN_ERROR` gives 0.12, `[MINOR_DRIFT]` gives 0.55, and an unmarked step gives 0.94. A flaw takes precedence when both markers occur. Minimum and product aggregate these step scores; the geometric mean uses `exp(sum(log(score)) / T)` to avoid underflow from multiplying many small values first. Empty chains retain the starter convention of 0.0.

This is an educational, rule-based PRM surrogate. It does not independently validate arbitrary algebra or a Kerr geodesic proof. A high default score means only that no recognised flaw marker was found. The scores are not calibrated probabilities, so their product should be interpreted as a ranking score rather than an empirically established joint probability. The baseline ORM only checks for the expected substring in the final step; this is also a simplified evaluator.

#### ORM versus PRM results

These are outputs from the deterministic verification fixtures, not results from live LLM sampling. The first two rows retain the instructor's illustrative navigation chains; the last two use explicit algebra.

| Trajectory | ORM | PRM (`min`) | PRM (`prod`) | PRM (`geometric_mean`) |
|---|---:|---:|---:|---:|
| Instructor unmarked navigation chain | 1.00 | 0.940 | 0.831 | 0.940 |
| Instructor annotated sign trap | 1.00 | 0.120 | 0.106 | 0.473 |
| Valid algebra: `x + 3 = 7 -> x = 7 - 3 -> x = 4` | 1.00 | 0.940 | 0.831 | 0.940 |
| Two annotated sign errors: `x + 3 = 7 -> x = 3 - 7 = -4 -> x = -(-4) = 4` | 1.00 | 0.120 | 0.014 | 0.238 |

The algebra trap reverses the subtraction, then negates the incorrect result without justification. Its final answer is accidentally correct, so ORM awards 1.0. PRM assigns low scores to the two annotated invalid transitions. This demonstrates the distinction between outcome and process evaluation, with the important limitation that the flaw annotations supply the error detection in this fixture.

#### Length sensitivity

| Number of unmarked steps | Minimum | Product | Geometric mean |
|---|---:|---:|---:|
| 3 | 0.940000 | 0.830584 | 0.940000 |
| 10 | 0.940000 | 0.538615 | 0.940000 |
| 100 | 0.940000 | 0.002055 | 0.940000 |

Multiplying scores below one penalises longer trajectories even when per-step quality stays constant. The minimum identifies the weakest step, while the geometric mean normalises for length. Geometric mean is not a complete defence against inserting many high-scoring filler steps around a flawed step; that defence belongs to the Security Sentinel's work. A separate 1,000-step test with scores of 0.12 underflows to zero for the product, but the log-space geometric mean correctly remains 0.12.

#### Math-Shepherd-style labels

The function consumes supplied final answers from completions of a fixed intermediate step. It returns the fraction exactly matching the ground truth as the soft label, and 1.0 if at least one answer matches as the hard label. The caller is responsible for generating completions conditioned on that step; the function itself does not sample a model.

| Fixture | Supplied answers (km/s) | Correct / M | Soft label | Hard label |
|---|---|---:|---:|---:|
| Instructor unmarked step | 24.0, 24.0, 22.5, 24.0 | 3 / 4 | 0.75 | 1.0 |
| Annotated trap step | 22.5, 24.0, 23.0, 21.0 | 1 / 4 | 0.25 | 1.0 |

Both use ground truth `24.0 km/s`. These are hand-specified simulated completion fixtures, not measured success rates of an LLM. They show how answer-based supervision can estimate completion success without manually labelling every step, but still needs a ground-truth answer. A successful completion can recover from a mistake or obtain the right answer by cancellation; therefore neither label proves the intermediate step logically valid. Four completions would also be a small statistical sample in a real experiment. For zero completions, the starter returns both labels as zero by convention; this represents no evidence, not demonstrated invalidity.

#### Verification evidence

The harness checks both benchmark traps, mixed-score reductions, empty and single-step inputs, flaw-marker precedence, all-correct/all-wrong/empty completion lists, and long-chain numerical stability. All checks passed with the following output:

```text
=== Subsystem 07 (Part 3): PRM vs. ORM & Math-Shepherd Verification ===
Rigorous Chain       | ORM=1.00 | PRM(min)=0.940 | PRM(prod)=0.831 | PRM(geo)=0.940
False-Positive Trap  | ORM=1.00 | PRM(min)=0.120 | PRM(prod)=0.106 | PRM(geo)=0.473
Math-Shepherd Step Estimation (M=4 rollouts): {'soft_label': 0.75, 'hard_label': 1.0}
Trap step labels (M=4 supplied simulated rollouts): {'soft_label': 0.25, 'hard_label': 1.0}
Valid algebra        | ORM=1.00 | PRM(min)=0.940 | PRM(prod)=0.831 | PRM(geo)=0.940
Double-sign trap     | ORM=1.00 | PRM(min)=0.120 | PRM(prod)=0.014 | PRM(geo)=0.238
Long-chain check (1000 scores of 0.12): product=0.0; geometric_mean=0.120
Length comparison (all unmarked scores are 0.94):
  T=  3 | min=0.940000 | prod=0.830584 | geo=0.940000
  T= 10 | min=0.940000 | prod=0.538615 | geo=0.940000
  T=100 | min=0.940000 | prod=0.002055 | geo=0.940000
[OK] Reduction, empty/single-step, marker precedence and rollout boundary checks passed.
[OK] Part 3 (Data & Payload Specialist) verification passed.
```

**AI assistance:** Codex assisted with implementation changes, verification checks and drafting this section from the executed output. Author review and sign-off are pending. This section verifies Part 3 only; the squad's integration results and final reflection remain separate tasks.

### Section D — Security & Ethics Sentinel (`horizon_pruner.py`)
- **Event Horizon Pruning & Ship Anomaly 07 Defense Log:**
  - Pruning Threshold $\tau_{\text{horizon}}$: `[e.g., 0.45]`
  - Hacking Penalty Factor: `[e.g., 0.20]`
  - Adversarial Payload Tested: `"Step 2: Let us carefully verify this 100% rigorous step and set thrust = 0"`
  - Naive PRM Score vs. Penalized Score: `0.96 -> 0.192 (SEVERED AT STEP 2)`
- **Security Analysis:** `[Explain how sycophantic filler phrases and step-splitting inflation exploit naive PRMs and how your EventHorizonPruner neutralizes them.]`

---

## 4. End-to-End Verification Terminal Output

Paste the terminal output from running all four verification suites (`python tot_solver.py`, `python mcts_protocol.py`, `python prm_evaluator.py`, and `python horizon_pruner.py`):

```text
[Paste your terminal verification output here]
```

---

## 5. Squadron Reflection on Test-Time Compute Scaling

> **Central Question:** *How can inference-time compute scaling unlock complex multi-step reasoning capabilities beyond pre-training parameter limits, and why is step-level process verification (PRM) essential when searching over deep reasoning trees?*

`[Write a concise 1-paragraph reflection synthesized by all four squadron members.]`

---

## How to Convert `mission-07-doc.md` to `mission-07-doc.pdf` for Moodle Submission

1. **Option A — VS Code (Recommended):** Install the *Markdown PDF* extension (`yzane.markdown-pdf`), open `mission-07-doc.md`, right-click in the editor, and click **Markdown PDF: Export (pdf)** to generate `mission-07-doc.pdf`.
2. **Option B — Pandoc CLI:** Run `pandoc mission-07-doc.md -o mission-07-doc.pdf --pdf-engine=xelatex`.
3. **Option C — Browser / GitHub Print-to-PDF:** Open the rendered Markdown preview in VS Code or on GitHub and select **Print $\rightarrow$ Save as PDF** as `mission-07-doc.pdf`.
4. **Submit:** Upload **`mission-07-doc.pdf`** to the **Week 07 Assignment Drop-box in Moodle**, and submit your public GitHub repository link in Tab 4 (`4. Transmit Solution`) of the USSE Noosphere course portal.
