# Mission 07 Squadron Documentation (`mission-07-doc.md`)

**Course:** Conversational AI (WS 2026/27) — Week 7: Test-Time Compute & Reasoning Search Paradigms  
**Sector Waypoint:** `SEC-07-SGR` (Sagittarius A* Supermassive Black Hole)  
**AURA Subsystem:** Subsystem 07 — Gravitational Search Horizon & Process Reward Evaluator  
**Squadron Name:** Squadron Goodfellow  
**Public GitHub Repository URL:** https://github.com/AbuBakerAttique/squadron-goodfellow  
**Submission Date:** `[YYYY-MM-DD]`  

---

## 1. Squadron Roster & Station Sign-Off Table

> **Instructions:** After all four station officers have finished and verified their Python modules (`tot_solver.py`, `mcts_protocol.py`, `prm_evaluator.py`, and `horizon_pruner.py`), fill in the sign-off table below.

| Station Role | Cadet Full Name | Deliverable File | Verification Status |
| :--- | :--- | :--- | :--- |
| **Systems Architect** | Abdul Jalil Memon | `tot_solver.py` | PASS / VERIFIED (harness + 8 self-checks + Game-of-24 benchmark) |
| **Communications & Protocol Officer** | Fatima Siddiqa | `mcts_protocol.py` | `[PASS / VERIFIED]` |
| **Data & Payload Specialist** | Abubaker Attique | `prm_evaluator.py` | `[PASS / VERIFIED]` |
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
- **Empirical Comparison: Outcome Reward Model (ORM) vs. Process Reward Model (PRM):**

| Trajectory Type | ORM Terminal Score | PRM (`min`) | PRM (`prod`) | PRM (`geometric_mean`) | Math-Shepherd Soft Label ($M=4$) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Rigorous Kerr Proof** | `1.00` | `0.940` | `0.831` | `0.940` | `0.75` |
| **False-Positive Sign Trap** | `1.00 (Trap!)` | `0.120` | `0.106` | `0.473` | `[Insert]` |

- **Data Analysis:** `[Explain why ORM fails on false-positive intermediate reasoning errors, why product reduction penalizes longer chains, and how Math-Shepherd estimates step quality without human annotations.]`

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
