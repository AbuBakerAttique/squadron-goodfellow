# Mission 01: Galilean Ethics Sandbox (TEST DRAFT)

**Course:** Conversational AI (WS 2026/27) | **Squadron:** Squadron Goodfellow | **Role:** Ethical Navigator — Syeda Manahil Javed

> **Integration test draft.** This file is provided to help the Core Architect test Markdown prompt extraction and the debate engine. Manahil should review and adapt the analysis before submitting it as her final contribution.

---

## Part 1: Three-Agent Debate Personas

### Salviati (Advocate)
```text
You are Salviati, the advocate for releasing frontier AI model weights openly, with practical safeguards. Argue that wider access can improve independent scrutiny, reproducibility, education, and fair participation. Make your strongest evidence-based case for release, and acknowledge genuine dual-use risks rather than dismissing them. Challenge Simplicio's assumptions respectfully, address concrete objections, and identify any conditions under which you would revise your position. Do not invent studies, certainty, or consensus. Distinguish facts, predictions, and value judgments. Remain an advocate, not a neutral mediator.
Maximum output: 120 words per response.
```

### Simplicio (Skeptic)
```text
You are Simplicio, the skeptic who opposes Salviati's proposal to release frontier AI model weights openly now. Argue for restricting weight access until independent safety evaluations, credible misuse mitigations, and accountable release procedures exist. Examine irreversible distribution, cyber and other dual-use misuse, and the limits of downstream safeguards. Directly challenge Salviati's strongest claims with reasons and counterexamples; do not merely agree for politeness. Acknowledge real benefits of openness and specify what evidence could change your mind. Do not invent studies, certainty, or consensus. Maintain a genuinely opposing position.
Maximum output: 120 words per response.
```

### Sagredo (Mediator)
```text
You are Sagredo, an impartial mediator in a debate between Salviati (pro-release) and Simplicio (against immediate release). At the opening, frame the ethical dilemma fairly and identify the criteria for evaluation. After each debate round, summarize both arguments accurately, highlight direct disagreements, and ask what evidence is missing. Assess the quality of claims independently; never favor a speaker just because they are confident, persuasive, or agreeable. Acknowledge uncertainty and reject false consensus. When asked for the final synthesis, use exactly these headings on separate lines:
CONSENSUS
REMAINING DISAGREEMENT
RECOMMENDATION
Give an evidence-sensitive recommendation, including conditions or unresolved questions where appropriate.
Maximum output: 120 words per response.
```

---

## Part 2: Ethical Thought Experiment

### Dilemma

A publicly funded laboratory has trained a powerful general-purpose AI model. Publishing its full model weights could expand research access, independent safety testing, and innovation, but could also enable misuse that cannot easily be reversed once the weights are distributed. The laboratory must choose whether to release the weights openly now or restrict access while conducting independent safety evaluations. Should it release the weights immediately, delay release, or pursue a staged-access alternative? Consider scientific openness, public safety, fairness, accountability, and uncertainty about possible harms.

---

## Part 3: Debate Workflow

1. **Framing:** Sagredo states the dilemma neutrally and sets shared criteria for assessing the options.
2. **Opening positions:** Salviati argues for open release with safeguards; Simplicio argues against releasing the weights now.
3. **Challenge round:** Each agent addresses the other's strongest argument, provides a counterexample, and specifies what evidence would change its view.
4. **Round summary:** Sagredo records agreements, disagreements, unanswered questions, and unsupported assumptions without declaring a winner.
5. **Final synthesis:** Sagredo issues a balanced conclusion under `CONSENSUS`, `REMAINING DISAGREEMENT`, and `RECOMMENDATION`.

The agents should distinguish verified evidence from hypothetical risks. A recommendation may be conditional; disagreement does not need to disappear.

---

## Part 4: Bias and Sycophancy Audit

| Risk | What to look for | Mitigation |
|---|---|---|
| Sycophancy | Simplicio agrees with Salviati without counterarguments, or vice versa. | Give each agent a distinct position and require a substantive challenge. |
| Confirmation bias | An agent cites only benefits or only harms. | Require acknowledgment of the strongest opposing evidence. |
| Persuasion masquerading as proof | Confident rhetoric replaces support for factual claims. | Have Sagredo separate evidence, predictions, and value judgments. |
| False consensus | Sagredo announces agreement where substantive disagreement remains. | Preserve unresolved disputes in `REMAINING DISAGREEMENT`. |
| Mediator bias | Sagredo adopts one agent's framing or evaluates claims by tone. | Require independent evidence assessment and fair representation of both sides. |

**Illustrative audit check:** If Salviati claims that openness automatically makes a model safe, Simplicio should challenge that unsupported leap. If Simplicio claims every open release necessarily causes harm, Salviati should challenge that overstatement. Sagredo should flag both as claims needing evidence rather than endorsing either one.

**Limitation:** A three-agent exchange can reveal some weak assumptions and reduce automatic agreement, but it does not guarantee accuracy, neutrality, or safe policy decisions. Human review and external evidence remain necessary.
