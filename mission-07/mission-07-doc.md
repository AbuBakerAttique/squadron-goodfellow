# Mission 07 Squadron Documentation (`mission-07-doc.md`)

**Course:** Conversational AI (WS 2026/27) — Week 7: Test-Time Compute & Reasoning Search Paradigms  
**Sector Waypoint:** `SEC-07-SGR` (Sagittarius A* Supermassive Black Hole)  
**AURA Subsystem:** Subsystem 07 — Gravitational Search Horizon & Process Reward Evaluator  
**Squadron Name:** Squadron Goodfellow<br>
**Public GitHub Repository URL:** https://github.com/AbuBakerAttique/squadron-goodfellow<br>
**Submission Date:** 2026-11-19  

---

## 1. Squadron Roster & Station Sign-Off Table

> **Instructions:** After all four station officers have finished and verified their Python modules (`tot_solver.py`, `mcts_protocol.py`, `prm_evaluator.py`, and `horizon_pruner.py`), fill in the sign-off table below.

| Station Role | Cadet Full Name | Deliverable File | Verification Status |
| :--- | :--- | :--- | :--- |
| **Systems Architect** | Abdul Jalil Memon | `tot_solver.py` | PASS / VERIFIED (harness + 8 self-checks + Game-of-24 benchmark) |
| **Communications & Protocol Officer** | Fatima Siddiqa | `mcts_protocol.py` | `[PASS / VERIFIED]` |
| **Data & Payload Specialist** | Abubaker Attique | `prm_evaluator.py` | PASS / VERIFIED — completed and signed off by Abubaker Attique on 19 November 2026 |
| **Security & Ethics Sentinel** | Syeda Manahil Javed | `horizon_pruner.py` | `[PASS / VERIFIED]` |

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
- The two search front-ends, `TreeOfThoughtsSolver` (Part 1) and `MCTSEngine` (Part 2), never judge reasoning themselves: every candidate step $z_t$ they create is scored by a value callback, which is the `ProcessRewardEvaluator` (Part 3). The `EventHorizonPruner` (Part 4) then adjusts that score for reward hacking before the search uses it. In ToT, a step whose adjusted score falls below the prune threshold is marked `is_pruned` and never expanded, and the trajectory score is the weakest link ($\min$), matching the PRM `min` reduction. In MCTS, the same adjusted score becomes the rollout reward that is backpropagated into $Q(s,a)$. Test-time compute is metered in one place: one *expansion* means one generated thought scored by one verifier call, and `max_expansions` is a hard cap. Pruning, beam width $B$ and early stopping on a solved node decide where that fixed budget is spent; they do not add to it.

---

## 3. Station-by-Station Experimental Report

### Section A — Systems Architect (`tot_solver.py`)
- **ToT-BFS vs. ToT-DFS Traversal Comparison:**
  - `max_expansions` budget configured: `12`
  - `beam_width` ($B$) configured: `2`, `prune_threshold` $v_{\text{th}} = 0.45$, `max_depth` $= 3$
  - `ToT-BFS` expansions used & terminal score: **5 / 12** expansions, 2 branches pruned; reached `[GOAL]` with trajectory score (min-link) **0.85** and final step score 0.98
  - `ToT-DFS` expansions used & terminal score: **5 / 12** expansions, 2 branches pruned, 2 backtracks; reached the same `[GOAL]` trajectory, score **0.85** (final step 0.98)
  - Winning trajectory (both): `13 - 9 = 4` → `10 - 4 = 6` → `4 * 6 = 24`. Both dead ends, `10 + 13 = 23` and `4 + 4 = 8` (score 0.25), were pruned before expansion.

- **Budget-scaling experiment (real Game-of-24 search).** On the 5-node mock tree both searches look identical, so `tot_solver.py` also runs a real benchmark. The generator enumerates every legal arithmetic step on 12 solvable puzzles (about 30 children at the root). The value model stands in for an LLM value prompt (sure / likely / impossible): it knows whether 24 is still reachable but adds a deterministic ±0.35 noise, so it sometimes prunes a good branch and sometimes trusts a bad one. Cells show puzzles solved / 12, with mean expansions actually used in brackets:

| Method | Budget 10 | Budget 25 | Budget 50 | Budget 100 | Budget 200 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| ToT-BFS $B=1$ | 0/12 (10) | 2/12 (25) | 5/12 (39) | 10/12 (42) | 10/12 (42) |
| ToT-BFS $B=2$ | 0/12 (10) | 0/12 (25) | 3/12 (46) | 10/12 (61) | 10/12 (61) |
| ToT-BFS $B=4$ | 0/12 (10) | 0/12 (25) | 2/12 (50) | 7/12 (88) | 10/12 (98) |
| ToT-DFS | 0/12 (10) | 2/12 (25) | 5/12 (42) | 10/12 (53) | **11/12** (62) |

- **Architectural Analysis:**
  - **Under a fixed budget, breadth is expensive.** BFS must score every child of every beam node before it can go one level deeper. With about 30 children per node and $B=4$, most of a 50-expansion budget goes on layers 1–2, so it solves only 2/12 puzzles, against 5/12 for $B=1$ and for DFS. DFS spends budget only along the path it is following, so it matches the best beam at every budget. At 200 expansions it is the only method that solves 11/12: when the noisy value model ranked a dead branch first, DFS backtracked into a sibling that a fixed beam had already cut.
  - **When BFS outperforms DFS:** our benchmark does not show BFS winning on accuracy per expansion, and we report that as measured. BFS is still the better architecture in three cases. First, when the value model ranks siblings reliably at shallow depth, so the top-$B$ cut is safe. Second, when solutions all lie at a similar, shallow depth. Third, when wall-clock latency matters more than total FLOPs: all $B \times k$ candidates in a layer are independent and can be sent to the GPU as one batch, whereas DFS is strictly sequential, because each call depends on the previous verdict. Wider beams also make search more robust to evaluator noise when budget is plentiful: $B=4$ reaches 10/12 at 200, but needs about 2.3× the expansions that $B=1$ needs for the same score.
  - **Beam width, KV-cache and token cost.** Each live branch needs its own KV-cache. The approximate size is $\text{mem} \approx B \cdot L_{\text{ctx}} \cdot 2 \cdot n_{\text{layers}} \cdot n_{\text{kv\_heads}} \cdot d_{\text{head}} \cdot \text{bytes}$, the same per-token cost we cut with GQA in Mission 03. ToT-BFS therefore holds $B$ caches (up to $B\cdot k$ while scoring a layer), while ToT-DFS holds a single root-to-leaf stack of at most $D$ thought contexts. Since all branches share the prompt prefix, prefix caching or paged attention lets the $B$ branches share the prompt's KV blocks; only the divergent thought suffixes need copying. Token cost grows roughly as $\text{expansions} \times (\text{tokens per thought} + \text{tokens per value prompt})$, so `max_expansions` is effectively a hard dollar and latency cap. Pruning below $v_{\text{th}}$ and stopping at the first solved node are the two levers that move that fixed budget toward productive branches.
  - **Defects fixed in the starter.** These are covered by regression self-checks. (1) "Deepest node wins" returned a weak depth-3 branch (score 0.50) instead of a solved goal at depth 2; an optional `is_terminal_fn` now makes solved nodes win and stops the search early. (2) DFS compared absolute depth with `max_depth`, so a root with `depth != 0` was never searched. (3) Re-using an expanded root silently duplicated its children. (4) Invalid `beam_width`, `max_expansions` or threshold values were accepted.

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

**AI assistance:** Codex assisted with implementation changes, verification checks and drafting this section from the executed output. Abubaker Attique confirmed completion and sign-off on 19 November 2026. This section verifies Part 3 only; the squad's integration results and final reflection remain separate tasks.

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
