# Mission 3 — GQA and KV-cache benchmark results

Officer: Abubaker Attique — Data & Payload Specialist

## Reproduce

From the repository root, with PyTorch installed in the project environment:

```bash
.venv/bin/python mission-03/03_GQA_and_KVCache_Benchmark_starter.py --output mission-03/results/gqa_kvcache_results.json
```

Use `--verify-only` to run correctness checks without the benchmark. The implementation is completed directly in the instructor’s original starter file.

## Method and limits

- Recorded on 22 October 2026: macOS ARM CPU, PyTorch 2.14.1, Python 3.14.3, four CPU threads.
- Single attention layer; batch 1, 32 query heads, head dimension 128, float16, fixed seed 42.
- Two warm-ups and five measured repeats for each configuration and context length.
- The timed path computes one new token: projections, cache append, attention against a synthetic projected prefix, and output projection. Prefix generation is excluded; these are not full-model generation timings.
- Context length N includes the newly decoded token. Every repeat restores the cache cursor to N−1 and overwrites its last slot, so all samples use the same context length.
- Cache capacity = 2 × batch × KV heads × N × head dimension × bytes per element. MiB means 2^20 bytes. These are calculated tensor-storage footprints, not measured VRAM or total process memory; this run used CPU.
- Estimated traffic at 50 tokens/s = (one full K+V cache read plus one new K+V token write) × 50 / 10^9 GB/s. This is a simple logical traffic estimate, not a measurement of hardware bandwidth. It excludes weights, activations and backend re-reads.
- Explicit grouped broadcasting can produce temporary tensors or less efficient kernels. The benchmark does not claim fused-kernel efficiency, constant-time decoding, or preserved model quality.
- GPU results would require a separate run on the intended GPU; they must not be inferred from these CPU timings.

## Results

| Context tokens | Configuration (Q:KV) | Cache capacity (MiB, calculated) | KV traffic (GB/s at 50 tokens/s, estimated) | Median decode latency (ms, measured CPU) |
|---:|---|---:|---:|---:|
| 1024 | MHA (32:32) | 16.00 | 0.840 | 1.786 |
| 1024 | GQA (32:8) | 4.00 | 0.210 | 1.995 |
| 1024 | MQA (32:1) | 0.50 | 0.026 | 1.343 |
| 4096 | MHA (32:32) | 64.00 | 3.356 | 2.833 |
| 4096 | GQA (32:8) | 16.00 | 0.839 | 5.731 |
| 4096 | MQA (32:1) | 2.00 | 0.105 | 2.566 |
| 16384 | MHA (32:32) | 256.00 | 13.423 | 7.242 |
| 16384 | GQA (32:8) | 64.00 | 3.356 | 21.698 |
| 16384 | MQA (32:1) | 8.00 | 0.419 | 6.531 |
| 32768 | MHA (32:32) | 512.00 | 26.844 | 13.248 |
| 32768 | GQA (32:8) | 128.00 | 6.711 | 49.188 |
| 32768 | MQA (32:1) | 16.00 | 0.839 | 11.880 |

## Interpretation

At every context length, GQA stores one quarter of the MHA cache (75% reduction), and MQA stores one thirty-second (96.875% reduction), for equal batch, context, head dimension and dtype. This is a storage calculation, not an accuracy result. GQA was slower than MHA in these CPU measurements, so the observed memory reduction must not be presented as a latency improvement. A small number of repeats on one machine is descriptive evidence, not a general performance ranking.

## Correctness checks

- Q:KV=4:4: reference, token/chunk cache equivalence, causal isolation PASS
- Q:KV=4:2: reference, token/chunk cache equivalence, causal isolation PASS
- Q:KV=4:1: reference, token/chunk cache equivalence, causal isolation PASS
- Cache append, storage, reset, bounds and dtype checks PASS

Tests compare grouped attention against an independently repeated-head reference, compare full causal attention with token-by-token and chunked cached decoding, and verify that future inputs cannot change earlier outputs. Cache tests cover append, reset, capacity, shape/storage and dtype handling. RoPE integration with the teammate’s module has not been tested; new keys must be rotated once at their absolute positions before caching.

## AI assistance

Codex assisted with the implementation, correctness checks and report preparation and executed the recorded local CPU benchmark. The squad should review the implementation and evidence before signing off.
