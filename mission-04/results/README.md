# Mission 4, Part 3: length-bias evidence

Officer: Abubaker Attique, Data & Payload Specialist, Squadron Goodfellow.

These files are the evidence behind sections [2] to [4] of `../03_Length_Bias_and_SimPO.py`.
The script reads `length_bias_scored_pairs.json` by default.

| File | What it is |
| --- | --- |
| `length_bias_scored_pairs.json` | 100 scored preference pairs: response token counts and **summed** response log-probs under the policy and the reference. |
| `length_bias_evaluation.json` | Provenance, limitations, the Pearson result with a bootstrap interval, and SimPO metrics. |
| `memory_benchmark_mps.txt` | Saved output of `--benchmark-mps` on an Apple M4 Pro (see below). |

## Where the data comes from

- Dataset: `Anthropic/hh-rlhf`, `helpful-base/test.jsonl.gz`, revision `09be8c5bbc57cb3887f3a9732ad6aa7ec602a1fa`
  (file sha256 `8be3fc1a…adc37b`). 100 pairs, shuffled with `random.Random(42)`, answers never truncated, both sequences at most 512 tokens.
- Policy: `HuggingFaceTB/SmolLM2-135M-Instruct` @ `12fd25f`. Reference: `HuggingFaceTB/SmolLM2-135M` @ `93efa2f`. CPU, float32.
- Scoring uses only the response tokens, with the usual causal shift. The first answer was cross-checked against Part 1's `get_batch_logps`.

## What this is, and what it is not

- It **is** a real-data run of the length-bias diagnostic: Pearson r between the length difference and the policy-minus-reference log-ratio margin.
- It is **not** a DPO or SimPO model trained by this team. The "policy" is an instruct checkpoint and the "reference" is its base model,
  so the margins show how the two checkpoints differ, not how a preference-optimised model behaves.
- Result: r = -0.420, 95% bootstrap interval [-0.644, -0.127]. Association only, from 100 pairs. The sign follows from the checkpoints
  (mean per-token log-ratio is about -0.11, so longer answers collect more negative sums). It is not evidence that the data rewards verbosity.
- The SimPO numbers on these pairs are computed from the instruct model's log-probs. That model was not trained with SimPO, so they are a worked example, not a training result.

## Reproduce

```bash
python mission-04/03_Length_Bias_and_SimPO.py                 # formatted report from the files above
python mission-04/03_Length_Bias_and_SimPO.py --verify-only   # self-checks only
python mission-04/03_Length_Bias_and_SimPO.py --score-real    # re-score from Hugging Face (downloads two ~135M models; CPU is fine)
```

`--score-real` writes to the git-ignored `mission-04/logs/length_bias_real/`, so it will not overwrite the files in this folder.

## Memory benchmark

The default run reports a CPU tensor-byte accounting on a toy model (not VRAM) and the analytical 7B weights-only figure.

**Measured on an Apple M4 Pro** (PyTorch MPS allocator, FP32, AdamW, toy token model, 4 pairs x 128 tokens), saved in
`memory_benchmark_mps.txt`:

| | DPO (policy + frozen reference) | SimPO (policy only) |
| --- | --- | --- |
| Model weights | 4.00 MiB | 2.00 MiB |
| Peak training allocation (sampled) | 13.02 MiB | 11.02 MiB |

Weights halve exactly (50%), but the peak saving is only 15.3%, because gradients, AdamW state and activations are the same
for both methods. The peak is sampled at three points of one training step, so it is a lower bound, and Apple's unified
memory means these are allocator bytes from system RAM, not dedicated VRAM. The briefing's "about 50%" therefore holds for
stored weights only.

```bash
python mission-04/03_Length_Bias_and_SimPO.py --benchmark-mps 2>&1 | tee mission-04/results/memory_benchmark_mps.txt
```

On an NVIDIA machine (for example a free Colab T4) use `--benchmark-cuda` instead; that path measures with the CUDA
allocator's peak counter but has not been run by this team.
