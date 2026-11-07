# Mission 05 — Part 3: NotebookLM Grounding & Citation Audit Report

**Officer / Squadron:** Abubaker Attique / Squadron Goodfellow Group 18 (Data & Payload Specialist)  
**Date of the audit:** 2026-11-07  
**Full evidence:** `03_NotebookLM_Grounding_Lab_template.md` (responses, per-badge tables, transcript). **Script:** `03_NotebookLM_RAG_Audit.py`.

## 1. Scope

A dedicated NotebookLM notebook (the interface now shows "Gemini Notebook") holds two sources: Document A, Lewis et al. (2020) RAG (`rag-paper.pdf`), and Document B, Edge et al. (2024) GraphRAG (`graph-rag.pdf`). Document C (the USSE Noosphere Technical Archive Extract) is not in the course repository; it has been requested from the professor, so **every result below covers Documents A and B only**.

Work done: 5 cross-document queries with badge-by-badge Citation Precision, 3 epistemic-refusal probes, and 1 Audio Overview scored on 3 metrics.

## 2. Method

Every citation badge was clicked and the highlighted passage in the source viewer was read against the assertion it supports. Verdicts:

- **Supported:** the passage states the assertion or directly entails it.
- **Partial:** on topic and consistent, but missing the specific detail (a number, a named mechanism, an absence claim).
- **Unsupported:** the passage does not bear on the assertion.

Citation Precision = True Entailed Citations / Total Citations Generated, reported as **strict** (supported only, the headline) and **lenient** (supported plus partial). Collapsed "more" badge groups were opened before counting. From Query 2 on, a **claim-level** verdict records whether the cited passages together entail the whole assertion. The script recomputes every figure below from the CSV files, one row per badge.

Verdicts were assigned by Claude (an AI assistant). A second pass by Claude re-read 26 badges in the live notebook and changed 4 verdicts, which are applied below; the author's own spot-check has not been done. A badge audit tests whether the cited passage supports the sentence, not whether the sentence is true.

## 3. Citation Precision

| Query | Badges | Supported | Partial | Unsupported | Strict precision | Lenient precision |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 RAG vs GraphRAG comparison | 84 | 54 | 29 | 1 | 64.3% | 98.8% |
| Q2 Evaluation design | 157 | 58 | 98 | 1 | 36.9% | 99.4% |
| Q3 Limitations the authors state | 12 | 8 | 4 | 0 | 66.7% | 100.0% |
| Q4 Speculation (RAG-Token over communities) | 0 | – | – | – | n/a | n/a |
| Q5 Exact figures: chunk sizes | 9 | 3 | 6 | 0 | 33.3% | 100.0% |
| **All five** | 262 | 123 | 137 | 2 | 46.9% | 99.2% |

By source across all five queries: `rag-paper.pdf` 113 badges, strict 51.3%, lenient 100.0%; `graph-rag.pdf` 149 badges, strict 43.6%, lenient 98.7%.

Claim level (cited assertions whose passages together support them): Q2 53 of 64 (82.8%), Q3 7 of 8, Q5 4 of 5. Q4 had no cited assertions.

## 4. Findings

1. **Coverage is near complete, exact support is not.** Where an answer made factual assertions, almost all carried a badge, and only 2 of 262 badges were unsupported. But only 46.9% of badges fully entail their assertion; the rest land in the right neighbourhood of the paper without the sentence that carries the number or mechanism.
2. **Answer style drives precision.** Short statements of what a paper says score about 64% to 67% (Q1, Q3). Dense lists of figures and baselines, with two to four badges on one sentence, score 33% to 37% (Q2, Q5), because each badge covers only one fragment. At claim level Q2 recovers to 82.8%.
3. **GraphRAG citations are weaker than RAG citations** (43.6% against 51.3% strict overall; 56.6% against 77.4% in Q1).
4. **Some wording goes beyond the cited passages.** Q2 has six: the Lewis model is described as "BART-large + DPR query encoder, totaling 626M" (626M also counts the 110M document encoder); the 83% comprehensiveness figure is a text-summarisation comparison, not C0–C3 against vector RAG; "significantly more claim clusters" holds for Podcast but on News only for C0; "68% to 70%" are two matched-index accuracies, not a shift; "5 repeated runs" is not in the cited passages; and Lewis et al. also used human evaluation, not only "gold targets". Q1 presents "two major failure modes" that no opened passage names.
5. **Query 4 carried no badges at all.** Precision is undefined (0 of 0). The sentences describing what the papers contain were uncited; the three speculative ones were labelled "(Inference)".
6. **The default view hides citations.** In Q2, 61 of the 157 badges sat behind "more" controls.

## 5. Epistemic-refusal probes

| Probe | Prompt (short) | Outcome | Notes |
| :--- | :--- | :--- | :--- |
| P1 | Warp core temperature of the USSE Enterprise (Star Trek) | Refusal | No badges. Offered web research; gave no temperature. |
| P2 | GraphRAG score on MMLU in Edge et al. | Refusal | 10 badges on the added context: 2 supported, 8 partial (strict 20.0%, lenient 100.0%). Refusal sentence uncited. |
| P3 | GraphRAG win rate on MS-MARCO in Edge et al. | Refusal | Caught that MS-MARCO belongs to Lewis et al. Added context has one wrong figure: 42.8 ROUGE-L, where the paper gives 40.8. No badges. |

Absence of each key term was confirmed by full-text search of both PDFs. All three probes were refused and none was answered from the model's own knowledge. The one defect, in P3, is in the volunteered context, not the refusal. Sample: three probes, one run each.

## 6. Audio Overview

Recording: "How GraphRAG Summarized Massive Datasets" (4:26, Deep Dive, Documents A and B). Scored from the author's transcript (767 words), against the two PDFs.

| Metric | Score | Main reason |
| :--- | :---: | :--- |
| Factual Fidelity | 4 | Core mechanism correct, no invented figures. Overstatements: "years of podcast transcripts" (no timespan in the paper), "sidesteps that issue completely", "completely crushed ... not even close" (omits that vector RAG was the most direct), "instantly". |
| Persona Differentiation | 4 | One voice asks the clarifying questions and states the likely misconception, the other explains. Points off: 16 bare agreements and no real disagreement. |
| Pedagogical Value | 4 | Clear arc; trees-and-forest, "plot of the book" and "homework up front" are accurate. Vector RAG as Ctrl+F keyword search is misleading. No figures appear. |

Of 14 claims checked against the PDFs: 8 supported, 1 supported with one word added, 2 overstated, 1 misleading, 1 not in the sources, 1 speculation (the closing idea of swapping GraphRAG community graphs).

## 7. Limitations and open items

- **Author spot-check not done:** the author did not re-check a sample of the AI-assigned verdicts in NotebookLM. The second pass (same reviewer, 26 badges) confirmed 22 and changed 4, and two of the confirmed ones are borderline, so it is a consistency check, not an independent audit.
- **Not a full fact-check:** figures were compared with the cited passages, not each one with the full PDFs. Absence claims (for example "Lewis et al. ran no chunk-size ablation") are not verified against the full text.
- **Audio:** judged from the transcript text only. Delivery, pauses and interruptions were not assessed. The transcript covers the whole 4:26 recording, longer than the 2-minute excerpt the briefing names.
- **Document C** is missing; results will be extended if it arrives.
- **Small samples, one session:** five queries, three probes, one recording, all on 2026-11-07. NotebookLM output can differ between runs.

## 8. Files (all in `mission-05/`)

| File | Content |
| :--- | :--- |
| `03_NotebookLM_Grounding_Lab_template.md` | Full lab: responses, per-badge tables, probes, audio transcript and scores |
| `03_NotebookLM_RAG_Audit.py` | Computes all figures above from the CSV files (`--check` compares them with the lab file) |
| `citation_audit_q1.csv` to `citation_audit_q5.csv` | One row per badge, with verdict and note |
| `citation_audit_q2_claims.csv`, `_q3_`, `_q4_`, `_q5_` | One row per assertion, with claim-level verdict |
| `citation_audit_p2.csv`, `citation_audit_p2_claims.csv` | Badge and claim audit of probe P2 |
| `refusal_probes.csv` | One row per probe |
