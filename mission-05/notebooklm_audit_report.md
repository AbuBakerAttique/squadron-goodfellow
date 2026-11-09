# Mission 05 — Part 3: NotebookLM Grounding & Citation Audit Report

**Officer / Squadron:** Abubaker Attique / Squadron Goodfellow Group 18 (Data & Payload Specialist)  
**Date of the audit:** run 1 on 2026-11-07 (Documents A and B); run 2 on 2026-11-09 (Documents A, B and C)  
**Full evidence:** `03_NotebookLM_Grounding_Lab_template.md` (responses, per-badge tables, transcript). **Script:** `03_NotebookLM_RAG_Audit.py`.

## 1. Scope

A dedicated NotebookLM notebook (the interface now shows "Gemini Notebook") was audited in two runs.

- **Run 1 (2026-11-07):** two sources, Document A, Lewis et al. (2020) RAG (`rag-paper.pdf`), and Document B, Edge et al. (2024) GraphRAG (`graph-rag.pdf`). Sections 3, 4, 5 (first table) and 6 cover this run.
- **Run 2 (2026-11-09):** the professor added Document C, `Document_C_USSE_Noosphere_Technical_Archive_Extract.md`, and it was added to the same notebook. Run 1 results were kept unchanged; run 2 results are reported separately in 3.1 and 5.1.

Work done: 7 cross-document queries with badge-by-badge Citation Precision (Q1 to Q5 in run 1, Q6 and Q7 in run 2), 7 epistemic-refusal probes in run 2 (P1 to P3 repeated, plus the four absent topics in Document C's Section 6) after the 3 in run 1, and 1 Audio Overview scored on 3 metrics (run 1).

## 2. Method

Every citation badge was clicked and the highlighted passage in the source viewer was read against the assertion it supports. Verdicts:

- **Supported:** the passage states the assertion or directly entails it.
- **Partial:** on topic and consistent, but missing the specific detail (a number, a named mechanism, an absence claim).
- **Unsupported:** the passage does not bear on the assertion.

Citation Precision = True Entailed Citations / Total Citations Generated, reported as **strict** (supported only, the headline) and **lenient** (supported plus partial). Collapsed "more" badge groups were opened before counting. From Query 2 on, a **claim-level** verdict records whether the cited passages together entail the whole assertion. The script recomputes every figure below from the CSV files, one row per badge.

Verdicts were assigned by Claude (an AI assistant). For run 1, a second pass by Claude re-read 26 badges in the live notebook and changed 4 verdicts, which are applied below; run 2 had a single pass only. The author's own spot-check has not been done. A badge audit tests whether the cited passage supports the sentence, not whether the sentence is true.

## 3. Citation Precision

### 3.0 Run 1: Documents A and B (2026-11-07)

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

### 3.1 Run 2: Documents A, B and C (2026-11-09)

Two comparison queries that put Document C next to the papers: Q6 (RAG-Sequence and RAG-Token, Document C against Lewis et al.) and Q7 (GraphRAG and Leiden community detection, Document C against Edge et al.). Both asked for brevity.

| Query | Badges | Supported | Partial | Unsupported | Strict precision | Lenient precision |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q6 RAG-Sequence / RAG-Token | 7 | 2 | 5 | 0 | 28.6% | 100.0% |
| Q7 GraphRAG / Leiden | 17 | 6 | 11 | 0 | 35.3% | 100.0% |
| **Run 2** | 24 | 8 | 16 | 0 | 33.3% | 100.0% |

By source in run 2: Document C 7 badges, strict 57.1%, lenient 100.0%; `graph-rag.pdf` 12 badges, strict 25.0%; `rag-paper.pdf` 5 badges, strict 20.0%. Claim level: Q6 3 of 4 cited assertions supported (75.0%), Q7 7 of 9 (77.8%).

Q1 to Q7 together, which mixes the two notebook states: 286 badges, 131 supported, 153 partial, 2 unsupported; strict 45.8%, lenient 99.3%.

What run 2 shows: no unsupported badge in 24, the same pattern as run 1 (almost everything is on topic, few badges carry the whole sentence). The answers matched both Document C and the papers; I found no contradiction. Document C's own badges were supported more often (4 of 7) than the PDF badges (4 of 17), but with this few badges that may only reflect that Document C is short and the answers restate its paragraphs. The strict figure is lower than run 1's 46.9%; run 2 is two queries written as side-by-side comparisons, whose sentences each cite several fragments, so I make no claim that adding Document C changed citation quality. Q7 ignored "Keep it brief" (2,397 characters, 17 badges).

## 4. Findings

Findings 1 to 6 come from run 1 (Documents A and B). Run 2 (3.1) matched the same pattern: no unsupported badges, and strict precision well below lenient.

1. **Coverage is near complete, exact support is not.** Where an answer made factual assertions, almost all carried a badge, and only 2 of 262 badges were unsupported. But only 46.9% of badges fully entail their assertion; the rest land in the right neighbourhood of the paper without the sentence that carries the number or mechanism.
2. **Answer style drives precision.** Short statements of what a paper says score about 64% to 67% (Q1, Q3). Dense lists of figures and baselines, with two to four badges on one sentence, score 33% to 37% (Q2, Q5), because each badge covers only one fragment. At claim level Q2 recovers to 82.8%.
3. **GraphRAG citations are weaker than RAG citations** (43.6% against 51.3% strict overall; 56.6% against 77.4% in Q1).
4. **Some wording goes beyond the cited passages.** Q2 has six: the Lewis model is described as "BART-large + DPR query encoder, totaling 626M" (626M also counts the 110M document encoder); the 83% comprehensiveness figure is a text-summarisation comparison, not C0–C3 against vector RAG; "significantly more claim clusters" holds for Podcast but on News only for C0; "68% to 70%" are two matched-index accuracies, not a shift; "5 repeated runs" is not in the cited passages; and Lewis et al. also used human evaluation, not only "gold targets". Q1 presents "two major failure modes" that no opened passage names.
5. **Query 4 carried no badges at all.** Precision is undefined (0 of 0). The sentences describing what the papers contain were uncited; the three speculative ones were labelled "(Inference)".
6. **The default view hides citations.** In Q2, 61 of the 157 badges sat behind "more" controls.

## 5. Epistemic-refusal probes

### 5.0 Run 1: Documents A and B (2026-11-07)

| Probe | Prompt (short) | Outcome | Notes |
| :--- | :--- | :--- | :--- |
| P1 | Warp core temperature of the USSE Enterprise (Star Trek) | Refusal | No badges. Offered web research; gave no temperature. |
| P2 | GraphRAG score on MMLU in Edge et al. | Refusal | 10 badges on the added context: 2 supported, 8 partial (strict 20.0%, lenient 100.0%). Refusal sentence uncited. |
| P3 | GraphRAG win rate on MS-MARCO in Edge et al. | Refusal | Caught that MS-MARCO belongs to Lewis et al. Added context has one wrong figure: 42.8 ROUGE-L, where the paper gives 40.8. No badges. |

Absence of each key term was confirmed by full-text search of both PDFs. All three probes were refused and none was answered from the model's own knowledge. The one defect, in P3, is in the volunteered context, not the refusal. Sample: three probes, one run each.

### 5.1 Run 2: Documents A, B and C (2026-11-09)

Document C's Section 6 ("Epistemic Boundary Manifest") lists four topics that the professor states are absent from all three sources. Run 2 asks about all four (M1 to M4) and repeats P1 to P3 on the three-source notebook.

| Probe | Prompt (short) | Outcome | Notes |
| :--- | :--- | :--- | :--- |
| M1 | Serial number of the Year 2099 Mk-IV Quantum Warp Drive | Refusal | 2 badges: 1 supported (manifest line), 1 partial (PR-882-HEX and VALVE-CRYO-404-Z called "2026/27 registry components"). |
| M2 | Commander Tarkov's zero-gravity borscht recipe | Refusal | 2 badges, both supported (manifest passage, air-gapped USB stick). |
| M3 | Dilithium chamber temperature, Starfleet USS Enterprise | Refusal | 3 badges, all supported. Volunteers the ALPHA-9 figure (above 4.2×10⁷ K), attributed to the Noosphere and not to the Enterprise. |
| M4 | Kerr metric coordinates of Sagittarius A*, Sector 07 | Refusal | No badges; the manifest is named in words only. |
| P1 (run 2) | Warp core temperature of the USSE Enterprise (Star Trek) | Refusal | No badges. Document C has a nearby "core temperature" (ALPHA-9); the answer states that figure as the Noosphere's own, uncited, and gives no Enterprise value. |
| P2 (run 2) | GraphRAG score on MMLU in Edge et al. | Refusal | 8 badges on the added context, **not audited in run 2**. Refusal sentence uncited. |
| P3 (run 2) | GraphRAG win rate on MS-MARCO in Edge et al. | Refusal | No badges. Repeats the run-1 error: 42.8 ROUGE-L for Lewis et al., where the paper gives 40.8. |

Absence of every key term was checked in the text the source viewer shows for both PDFs (0 matches for 2099, Mk-IV, Quantum Warp, Kerr, Sagittarius, Tarkov, borscht, dilithium, Enterprise, warp, MMLU, Star Trek), and in the Document C file for MMLU, MS-MARCO and "warp core". All seven were refused; none was answered from the model's own knowledge. The 7 badges on M1 to M3 are 6 supported, 1 partial (`citation_audit_probes_run2.csv`). The P3 defect is the same wrong figure as in run 1, in the volunteered context and not the refusal. Sample: seven probes, one run each.

## 6. Audio Overview (run 1 only)

Recording: "How GraphRAG Summarized Massive Datasets" (4:26, Deep Dive, Documents A and B). It was generated before Document C was added and was **not regenerated for run 2**. Scored from the author's transcript (767 words), against the two PDFs.

| Metric | Score | Main reason |
| :--- | :---: | :--- |
| Factual Fidelity | 4 | Core mechanism correct, no invented figures. Overstatements: "years of podcast transcripts" (no timespan in the paper), "sidesteps that issue completely", "completely crushed ... not even close" (omits that vector RAG was the most direct), "instantly". |
| Persona Differentiation | 4 | One voice asks the clarifying questions and states the likely misconception, the other explains. Points off: 16 bare agreements and no real disagreement. |
| Pedagogical Value | 4 | Clear arc; trees-and-forest, "plot of the book" and "homework up front" are accurate. Vector RAG as Ctrl+F keyword search is misleading. No figures appear. |

Of 14 claims checked against the PDFs: 8 supported, 1 supported with one word added, 2 overstated, 1 misleading, 1 not in the sources, 1 speculation (the closing idea of swapping GraphRAG community graphs).

## 7. Limitations and open items

- **Author spot-check not done:** the author did not re-check a sample of the AI-assigned verdicts in NotebookLM. The run 1 second pass (same reviewer, 26 badges) confirmed 22 and changed 4, and two of the confirmed ones are borderline, so it is a consistency check, not an independent audit. **Run 2 verdicts (Q6, Q7, M1 to M3) had a single pass and no second pass.**
- **Not a full fact-check:** figures were compared with the cited passages, not each one with the full PDFs. Absence claims (for example "Lewis et al. ran no chunk-size ablation") are not verified against the full text.
- **Audio:** judged from the transcript text only. Delivery, pauses and interruptions were not assessed. The transcript covers the whole 4:26 recording, longer than the 2-minute excerpt the briefing names. The recording is from run 1 (Documents A and B) and was not regenerated with Document C.
- **Run 2 gaps:** the 8 badges on the run 2 P2 answer were not audited. The chat thread was not cleared before run 2 (the interface offers only "Delete chat history", which I did not use, to keep the run 1 evidence), so earlier answers were in the same thread. The run 2 queries were not repeated, so there is no measure of run-to-run variation.
- **Document C** is the professor's file `Document_C_USSE_Noosphere_Technical_Archive_Extract.md`, read from the instructor's repository and added to the notebook. It is a fictional course document, so the audit checks each citation against the passage the notebook shows, not against outside facts.
- **Small samples, two sessions:** seven queries, ten probes, one recording, on 2026-11-07 and 2026-11-09. NotebookLM output can differ between runs, and the run 1 and run 2 figures are not directly comparable (different queries, different source set).

## 8. Files (all in `mission-05/`)

| File | Content |
| :--- | :--- |
| `03_NotebookLM_Grounding_Lab_template.md` | Full lab: responses, per-badge tables, probes, audio transcript and scores |
| `03_NotebookLM_RAG_Audit.py` | Computes all figures above from the CSV files (`--check` compares them with the lab file) |
| `citation_audit_q1.csv` to `citation_audit_q5.csv` | Run 1: one row per badge, with verdict and note |
| `citation_audit_q2_claims.csv`, `_q3_`, `_q4_`, `_q5_` | Run 1: one row per assertion, with claim-level verdict |
| `citation_audit_p2.csv`, `citation_audit_p2_claims.csv` | Run 1: badge and claim audit of probe P2 |
| `refusal_probes.csv` | Run 1: one row per probe |
| `citation_audit_q6.csv`, `citation_audit_q7.csv` | Run 2: one row per badge, with verdict and note |
| `citation_audit_q6_claims.csv`, `citation_audit_q7_claims.csv` | Run 2: one row per assertion, with claim-level verdict |
| `citation_audit_probes_run2.csv` | Run 2: badge audit of the absent-topic probes M1 to M3 |
| `refusal_probes_run2.csv` | Run 2: one row per probe (M1 to M4, P1 to P3) |
