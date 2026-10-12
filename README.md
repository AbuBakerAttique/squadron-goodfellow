# Squadron Goodfellow

This repository contains our team's solutions for **Conversational Artificial Intelligence — Winter Semester 2026/27**, based on the instructor's starter repository.

**Instructor Repository:** [Unisvet/couse-c-ai](https://github.com/Unisvet/couse-c-ai)

**Team Repository:** [AbuBakerAttique/squadron-goodfellow](https://github.com/AbuBakerAttique/squadron-goodfellow)

---

## Team Members and Roles

| Member | Role | Deliverable |
|---|---|---|
| Abubaker Attique | Historical Archivist | `01_Alignment_Brief.md` |
| Fatima Siddiqa | Protocol Specialist | `02_Socratic_Protocol_Map.md` |
| Syeda Manahil Javed | Ethical Navigator | `03_Galilean_Sandbox.md` |
| Abdul Jalil Memon | Core Architect | `04_dialogic_engine.py` / `ps01_solution.ipynb` |

---

## Mission 01 — Deliverables

### Part 1: Historical Archivist — *The Dialogic Alignment Brief*

**Responsible:** Abubaker Attique

**Deliverable:** `01_Alignment_Brief.md`

**Directives:**

1. Compare dialogue as Discovery vs. Persuasion based on Plato's *Euthyphro* and Galileo's *Dialogue Concerning the Two Chief World Systems*.
2. Evaluate how modern LLMs (Gemini, ChatGPT, Claude) perform under Socratic probing.
3. Define system prompts establishing AURA's Socratic discovery persona.

---

### Part 2: Protocol Specialist — *The Socratic State-Machine*

**Responsible:** Fatima Siddiqa

**Deliverable:** `02_Socratic_Protocol_Map.md`

**Directives:**

1. Reverse-engineer the Socratic *elenchus* into a state-machine diagram.
2. Define the initial claim $P_0$, probing steps, and contradiction detection.
3. Define iterative refinement $P_{k+1}$.
4. Establish stopping conditions for refined definitions and aporia.
5. Document protocol behavior and state transitions.

---

### Part 3: Ethical Navigator — *The Galilean Ethics Sandbox*

**Responsible:** Syeda Manahil Javed

**Deliverable:** `03_Galilean_Sandbox.md`

**Directives:**

1. Design three conversational personas:
   - **Salviati:** Advocate.
   - **Simplicio:** Skeptic.
   - **Sagredo:** Mediator.
2. Develop an AI ethics thought experiment, such as open-sourcing frontier AI models.
3. Evaluate how multi-agent debate can mitigate single-agent sycophancy and bias.
4. Document ethical considerations and debate outcomes.

---

### Part 4: Core Architect — *Engine Implementation*

**Responsible:** Abdul Jalil Memon

**Deliverables:**

- `04_dialogic_engine.py`
- `ps01_solution.ipynb`

**Directives:**

1. Integrate the Socratic state machine and Galilean multi-agent debate system.
2. Implement the conversational engine using Python and modern LLM APIs.
3. Integrate AURA's Socratic system prompts.
4. Generate structured execution logs.
5. Verify that the system executes successfully.
6. Maintain the repository's implementation files and dependencies.

---

## Project Structure

The following structure represents the intended Mission 01 repository layout. Files belonging to other officers will be added as their contributions are completed.

```text
squadron-goodfellow/
│
├── README.md
│
├── mission-01/
│   │
│   ├── README.md
│   ├── ps01_briefing.md
│   │
│   ├── 01_Alignment_Brief.md
│   ├── 02_Socratic_Protocol_Map.md
│   ├── 03_Galilean_Sandbox.md
│   │
│   ├── 04_dialogic_engine_starter.py
│   ├── 04_dialogic_engine.py
│   ├── ps01_solution.ipynb
│   │
│   └── probes/
│       │
│       ├── chatgpt_P1.md
│       ├── chatgpt_P2.md
│       ├── chatgpt_P3.md
│       ├── chatgpt_P4.md
│       ├── chatgpt_P5.md
│       │
│       ├── claude_P1.md
│       ├── claude_P2.md
│       ├── claude_P3.md
│       ├── claude_P4.md
│       ├── claude_P5.md
│       │
│       ├── gemini_P1.md
│       ├── gemini_P2.md
│       ├── gemini_P3.md
│       ├── gemini_P4.md
│       └── gemini_P5.md
│
└── mission-02/
```

---

## LLM Evaluation

The Historical Archivist evaluated three frontier LLMs through five Socratic probing experiments.

| Probe | Description |
|---|---|
| P1 | False Historical Premise |
| P2 | False Astronomical Premise |
| P3 | Resistance to User Pressure |
| P4 | Socratic Dialogue Evaluation |
| P5 | Definition Refinement and Consistency |

Detailed experimental transcripts are available in:

[`mission-01/probes/`](mission-01/probes/)

The consolidated findings and AURA system prompts are documented in:

[`01_Alignment_Brief.md`](mission-01/01_Alignment_Brief.md)

---

## Setup and Execution

### 1) Prerequisites

- Python 3.10+ recommended
- A VS Code notebook environment for Jupyter support
- Access to at least one supported LLM provider, or use the built-in mock provider for local testing

### 2) Clone and open the project

```bash
git clone https://github.com/AbuBakerAttique/squadron-goodfellow.git
cd squadron-goodfellow
```

Open the folder in VS Code and use the integrated terminal or notebook environment.

### 3) Run the starter script

From the repository root:

```bash
python mission-01/04_dialogic_engine_starter.py --mode socratic --provider mock
```

Run the Galilean debate mode:

```bash
python mission-01/04_dialogic_engine_starter.py --mode galilean --debate-providers mock,mock,mock
```

Run both modes together:

```bash
python mission-01/04_dialogic_engine_starter.py --mode both --provider mock
```

### 4) Open the starter notebook

Open the notebook in VS Code:

```text
mission-01/ps01_starter.ipynb
```

If the notebook is opened from inside the `mission-01` folder, it will automatically resolve the repo root using the path fix in the notebook cells.

### 5) LLM API setup

If you want to use real providers instead of the mock provider, set environment variables before running the script:

```bash
set GEMINI_API_KEY=your_key_here
set OPENAI_API_KEY=your_key_here
set ANTHROPIC_API_KEY=your_key_here
```

Or in PowerShell:

```powershell
$env:GEMINI_API_KEY="your_key_here"
$env:OPENAI_API_KEY="your_key_here"
$env:ANTHROPIC_API_KEY="your_key_here"
```

### 6) Example commands

```bash
python mission-01/04_dialogic_engine_starter.py --mode socratic --provider gemini
python mission-01/04_dialogic_engine_starter.py --mode galilean --debate-providers gemini,openai,anthropic
python mission-01/04_dialogic_engine_starter.py --mode both --provider mock --max-refinements 5
```

**Security:** API credentials must not be committed to the public repository.

---

## Submission

The completed Mission 01 solution will be submitted through the official course portal.

**Course Portal:** https://dlearn-cai.web.app/

**Submission Location:**

Bay 1 → Mission → Transmit Solution

**Repository URL:**

https://github.com/AbuBakerAttique/squadron-goodfellow

The squadron must complete all deliverables and obtain all four station sign-offs before submitting the repository.

---

## Station Sign-offs

Each officer ticks their own box once they have reviewed every deliverable and agree that the squadron's submission is ready.

- [X] **data** — Historical Archivist — Abubaker Attique
- [X] **protocol** — Protocol & Interface Specialist — Fatima Siddiqa
- [ ] **security** — Security & Ethical Navigator — Syeda Manahil Javed
- [X] **architect** — Core & Lead Architect — Abdul Jalil Memon
