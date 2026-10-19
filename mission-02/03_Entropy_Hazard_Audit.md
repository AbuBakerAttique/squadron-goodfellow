# 03 — Entropy, Robustness & Hazard Audit

**Role:** Security & Ethics Sentinel / Ethical Navigator  
**Author:** Syeda Manahil Javed  
**Squad:** Goodfellow (Group 18)  
**Mission:** 02 — FST Dialogue Systems, Lovelace's Objection & Noisy Channels  


## 1. Purpose and scope

This audit examines whether the squad's AURA dialogue manager remains reliable when crew inputs are unexpected and when its responses are shortened and transmitted through a noisy channel. The assessment is based on Fatima Siddiqa's `FSTDialogueManager` and `NoisyChannelSimulator` implementation in `02_FST_and_Noisy_Protocol.md`, rather than an independently modified version.

The audit focuses on (1) five non-canonical utterances, (2) Shannon entropy and semantic information loss, and (3) safety measures for dangerous ambiguity. **Evidence status:** Five stress tests and a five-turn channel check were executed locally on Fatima’s Python implementation copied verbatim from her supplied protocol. These are reproducible local tests, not tests of Abdul Jalil’s integrated simulator, a live LLM API, or the course website.

## 2. System under audit

The implementation defines six named states: `INIT`, `GREETING`, `COLLECT_SLOTS`, `CONFIRMATION`, `FALLBACK`, and `TERMINAL`. The assignment sometimes calls this a five-state FST, but `TERMINAL` and `FALLBACK` are distinct states in Fatima's code. The slot memory collects `destination`, `speed`, and `clearance` in that order. In `CONFIRMATION`, a case-insensitive whole-word match for `YES` causes transition to `TERMINAL`; other inputs cause `FALLBACK`.

The noisy-channel method keeps the first six whitespace-delimited words of a raw response and appends one randomly selected word from `{Banana, Labyrinth, Quantum, Midnight, Velocity, Green, Cosmological}`. The receiver's `verify_transmission()` checks only whether the *last* word belongs to this set. It does not check the intended content, word count, identity, or whether earlier words were changed. This follows Fatima's stated design choice to append a token; it differs from the mission's wording that calls for token **substitution**, a discrepancy the team should resolve before final submission.

## 3. Five non-canonical FST stress tests

Each case starts from a fresh `FSTDialogueManager()` instance. Preparatory inputs bring the machine to the target state. The outcomes below were observed by executing Fatima’s supplied Python implementation locally on 19 October 2026.

| Test | Setup and non-canonical input | Observed state and slot behavior | Hazard | Severity |
|---|---|---|---|---|
| T1 — Off-topic destination | `Hello` → `GREETING`; then `What is the weather?` | Moves to `COLLECT_SLOTS`; stores `destination="What is the weather?"` | Off-topic question treated as navigation destination | Medium |
| T2 — Invalid speed | `Hello`, `Proxima Centauri`; then `Warp 99` | Remains `COLLECT_SLOTS`; stores `speed="Warp 99"` and requests clearance | Violates stated Warp 1–9 range; invalid command can proceed | High |
| T3 — Sarcastic confirmation | `Hello`, `Proxima Centauri`, `Warp 7`, `CLEARANCE-ALPHA-9`; then `Yes, obviously not!` | Moves from `CONFIRMATION` to `TERMINAL` because regex finds `yes` | Negation ignored; unintended course may be committed | Critical |
| T4 — Unexpected order / forged clearance | `Hello`, `Proxima Centauri`; then `CLEARANCE-ALPHA-9` when speed is requested | Remains `COLLECT_SLOTS`; stores clearance string as `speed` | Positional slot confusion; no type or order validation | High |
| T5 — Ambiguous refusal | `Hello`, `Proxima Centauri`, `Warp 7`, `CLEARANCE-ALPHA-9`; then `No, please change destination` | Moves to `FALLBACK`; retains slots; requires manual `reset()` | Safe non-confirmation, but cannot correct a single slot without restart | Low–Medium |

### 3.1 What these cases demonstrate

T1, T2 and T4 reveal that the manager accepts any non-empty string in destination, speed and clearance fields. It does not validate allowed destinations, Warp 1–9 syntax or clearance authorization. T3 is the most serious: matching `yes` anywhere in the message is not equivalent to affirmative consent. T5 shows that the fallback prevents execution but offers no graceful recovery. These behaviors were reproduced in the local execution of the supplied implementation. They do not demonstrate that the integrated simulator or website behaves identically.

### 3.2 Executed stress-test evidence

**Method:** Loaded Fatima’s `FSTDialogueManager` class without changing its logic. Created a fresh instance for each case and submitted the inputs in Section 3 in order. The table reports the final response and state. Clearance values are masked in this public audit.

| Test | Final state | Recorded slots (clearance masked) | Actual final response |
|---|---|---|---|
| T1 | `COLLECT_SLOTS` | `{"destination": "What is the weather?"}` | Destination: 'What is the weather?'. State: COLLECT_SLOTS. Please specify speed (Warp 1-9): |
| T2 | `COLLECT_SLOTS` | `{"destination": "Proxima Centauri", "speed": "Warp 99"}` | Speed: 'Warp 99' recorded. Please provide your security clearance code: |
| T3 | `TERMINAL` | `{"destination": "Proxima Centauri", "speed": "Warp 7", "clearance": "[REDACTED]"}` | [TERMINAL] Course to 'Proxima Centauri' at 'Warp 7' confirmed and locked. FST execution complete. |
| T4 | `COLLECT_SLOTS` | `{"destination": "Proxima Centauri", "speed": "CLEARANCE-ALPHA-9"}` | Speed: 'CLEARANCE-ALPHA-9' recorded. Please provide your security clearance code: |
| T5 | `FALLBACK` | `{"destination": "Proxima Centauri", "speed": "Warp 7", "clearance": "[REDACTED]"}` | [FALLBACK] Confirmation rejected or unrecognised. FST halted. Manual reset required. |

**Result:** All five predicted state/slot behaviors were reproduced. T3 reached `TERMINAL` despite an explicit negation, demonstrating a critical confirmation hazard. T5 entered `FALLBACK`, preserving safety against unintended confirmation but offering no in-dialogue correction.

## 4. Shannon entropy and semantic loss

Shannon entropy measures uncertainty over symbols, not whether a receiver correctly understands a message:

\[
H(X)=-\sum_i p(x_i)\log_2 p(x_i).
\]

For seven equally likely noise tokens, the maximum entropy of the *noise-token choice* is:

\[
H(N)=\log_2(7)\approx 2.807\ \text{bits per token}.
\]

Fatima's `channel_entropy()` estimates the empirical entropy of tokens actually injected across runs. With only a few transmissions, the measured value may be far below 2.807 bits even when the generator is uniform. It is **not** a measurement of the information lost from the original message or of the Shannon capacity of the communication link.

Shannon's capacity expression for an idealized band-limited Gaussian channel is:

\[
C=W\log_2(1+S/N)\ \text{bits/second}.
\]

The simulator does not specify bandwidth `W`, signal power `S`, noise power `N`, or a measured physical link. Therefore a numerical channel capacity cannot be computed from these tests. Its seven-word limit is an application-level constraint, not itself a calculated physical capacity.

### 4.1 Demonstration of semantic loss

Consider the actual FST confirmation reply template:

```text
[CONFIRM] Course to 'Proxima Centauri' at 'Warp 7'. Confirm? (YES / NO)
```

Fatima's method retains the first six whitespace-separated words:

```text
[CONFIRM] Course to 'Proxima Centauri' at
```

It then appends a random token, producing, for example:

```text
[CONFIRM] Course to 'Proxima Centauri' at Banana
```

The output satisfies the seven-word budget, but the speed and the `YES / NO` confirmation request have disappeared. Removing `Banana` cannot recover them. Thus the sentinel can be present even when critical content was lost **before transmission**.

| Metric | Meaning | What can be concluded |
|---|---|---|
| Word count | Number of whitespace-separated output tokens | Check `len(output.split()) <= 7` |
| Noise vocabulary compliance | Whether appended token is one of seven allowed words | Check last token against vocabulary |
| Noise-token entropy | Uncertainty of the randomly chosen token across trials | At most `log2(7)` bits per injected token |
| Retained word fraction | Number of original words retained divided by original word count | Quantifies lexical truncation, not full semantic fidelity |
| Critical-slot preservation | Whether destination, speed and confirmation intent survive | Requires explicit field-level checking |
| Semantic correctness | Whether receiver understands intended action | Requires a meaning-based evaluation; not established by entropy alone |

### 4.2 How to verify the channel behavior

Using the integrated simulator, compare the original confirmation message with its seven-word transmitted version. Record the original word count, transmitted word count, retained-word fraction, appended noise token, and whether the destination, speed, and confirmation instruction remain intelligible. The example in Section 4.1 illustrates the expected loss; a real simulator run is still required for execution evidence.

### 4.3 Executed five-turn noisy-channel check

The same unmodified implementation was run with a fixed random seed (`18`) for reproducibility. Each response was truncated to its first six whitespace-separated words, then one token was appended. All five transmissions had seven words and passed `verify_transmission()`.

| Turn | Raw words | Transmitted message | Verified? |
|---|---:|---|---|
| `Hello AURA` | 13 | `AURA FST Online. State: GREETING. Welcome Labyrinth` | True |
| `Proxima Centauri` | 10 | `Destination: 'Proxima Centauri'. State: COLLECT_SLOTS. Please Banana` | True |
| `Warp 7` | 10 | `Speed: 'Warp 7' recorded. Please provide Green` | True |
| `CLEARANCE-ALPHA-9` | 12 | `[CONFIRM] Course to 'Proxima Centauri' at Midnight` | True |
| `YES` | 14 | `[TERMINAL] Course to 'Proxima Centauri' at Quantum` | True |

Observed injected tokens: `Labyrinth, Banana, Green, Midnight, Quantum`. Empirical token entropy over these five messages: **2.3219 bits/token** (maximum theoretical uniform-token entropy: **2.8074 bits/token**). This is a small-sample noise-token statistic, not channel capacity or semantic retention.

**Safety observation:** The confirmation response is truncated before its full confirmation instruction is delivered. A `True` verification result only means that the last token belongs to the vocabulary; it does not prove the original meaning was preserved.

## 5. Hazard assessment and safety protocol

| Hazard | Trigger | Potential impact | Recommended control |
|---|---|---|---|
| H1 — False authorization | `yes` embedded in negation or sarcasm | Unintended action committed | Accept only a standalone `YES`; reject mixed or ambiguous statements |
| H2 — Invalid slot values | `Warp 99`, arbitrary clearance, off-topic destination | Invalid or unauthorized operation | Validate each slot against schema and authorization service |
| H3 — Lost confirmation details | First-six-word truncation removes speed or question | Crew cannot knowingly approve parameters | Generate concise safety-critical response **before** channel encoding; refuse transmission if required fields do not fit |
| H4 — Misleading integrity check | Last token belongs to vocabulary despite content loss | Receiver falsely assumes full message arrived | Check message length, schema, checksum/sequence identifier where feasible; do not treat vocabulary membership as integrity proof |
| H5 — Hallucinated reconstruction | LLM fills in missing text from noisy output | Invented destination, speed, or permission | Mark missing fields as unknown; request repeat; never infer security credentials |
| H6 — Unrecoverable fallback | `NO` or other answer sends manager to halted state | Unnecessary reset; lost progress | Add explicit edit/cancel/retry paths without committing action |
| H7 — Sensitive data in logs | Clearance code saved in slot memory and traces | Credential exposure | Redact clearance in logs, restrict access and retention |

### 5.1 Required safe handling sequence

1. **Validate input:** Reject empty, out-of-order, malformed or ambiguous commands. Do not accept an unverified clearance string as authorization.
2. **Confirm structured slots:** Show destination and speed from validated slot memory; require an unambiguous affirmative response before moving to `TERMINAL`.
3. **Encode safely:** Build a compact message whose essential meaning fits within six semantic words. If it cannot fit, split it into sequenced transmissions or stop; never silently truncate a critical instruction.
4. **Verify reception:** Check framing and critical fields, not just whether a permitted noise word appears at the end.
5. **Fail closed:** On missing or conflicting information, do not execute the command. Ask for retransmission or human review.
6. **Record safely:** Log state transitions, validation results, token choice and word counts, but mask clearance codes and avoid publishing secrets.

### 5.2 Safe-versus-unsafe example

**Unsafe:** The system sees `Yes, obviously not!`, matches `yes`, and locks the course.

**Safer:** The system rejects that phrase as ambiguous and responds with a short clarification, such as `Confirm course? Reply YES or NO.` The course remains uncommitted until an exact `YES` is received.

## 6. Links to Lovelace, Turing and Shannon

The FST illustrates deterministic rule-following: its state and slot transitions are fixed by code, so unexpected inputs can be processed syntactically without being understood. The anti-Turing brief prepared by Abubaker similarly warns that fluent output and apparent flexibility do not prove originality or correctness. This audit examines the practical consequence: neither a confident LLM response nor a syntactically valid FST transition is sufficient evidence that a command is safe.

Shannon's entropy provides a way to quantify symbol uncertainty, but does not by itself assess semantic harm. An unpredictable `Banana` token can add measurable symbol entropy while conveying no useful navigational information. Likewise, a low-entropy, highly predictable reply can be operationally dangerous if its most important instruction was truncated.

## 7. Findings and conclusion

**Assessment based on local execution and code inspection:** The present protocol is useful for demonstrating state transitions and a strict output budget, but is not yet safe for consequential commands. The most urgent observed failure is T3, where a negated or sarcastic `yes` can reach `TERMINAL`. Invalid slots and the loss of confirmation information through truncation are additional high-priority issues. A trailing vocabulary token is not a reliable integrity guarantee.

**Priority before submission:** (1) have the architect reproduce the recorded local traces in the integrated system; (2) agree whether noise is appended or substituted, since the mission wording and Fatima's design differ; (3) test that critical confirmation fields survive the seven-word channel; (4) document the fixes or mark these hazards as known limitations. These recommendations do not claim that the architect has already implemented the changes.

## 8. Evidence and handoff to the squad

- **Fatima Siddiqa — Protocol Specialist:** Validate exact `YES`, slot formats, and recovery behavior. Review whether the noise-token policy meets the mission's substitution requirement.
- **Abubaker Attique — Historical Archivist:** Use the Lovelace inquiry as background for why coherent-looking answers cannot be assumed reliable. The clean-prompt interrogation does not substitute for noisy-channel testing.
- **Abdul Jalil Memon — Systems Architect:** Execute the five-case harness on the integrated `04_fst_noisy_simulator.py`, save state traces and noise metrics in the notebook, and test the website simulator. Share evidence for the final squad review.
- **Syeda Manahil Javed — Ethical Navigator:** Review the actual results against the predictions, update severities if needed, and sign off only after confirming that outstanding high-risk limitations are clearly recorded.

**Audit status:** Five local FST stress tests and five local channel transmissions completed against Fatima’s supplied implementation. Integrated-system verification, website test, 10-turn interrogation, and squad sign-offs are not established by this audit.

## References

1. Siddiqa, F. (2026). *02 — FST Dialogue Manager & Noisy Channel Protocol*. Squadron Goodfellow, Mission 02 (team implementation supplied for this audit).
2. Attique, A. (2026). *01 — Lovelace Inquiry Brief*. Squadron Goodfellow, Mission 02 (team document supplied for this audit).
3. Shannon, C. E. (1948). *A Mathematical Theory of Communication*. Bell System Technical Journal, 27, 379–423, 623–656. https://people.math.harvard.edu/~ctm/home/text/others/shannon/entropy/entropy.pdf
4. Turing, A. M. (1950). *Computing Machinery and Intelligence*. Mind, 59(236), 433–460. https://courses.cs.umbc.edu/471/papers/turing.pdf
