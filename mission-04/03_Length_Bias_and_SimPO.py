"""
Mission 04 — Part 3: Data & Payload Specialist
Length Bias Diagnostics & Reference-Free SimPO

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-04-ORI (Betelgeuse)
Subsystem 04: Plasma Ignition & Ethical Steering Core
Officer: Abubaker Attique — Squadron Goodfellow

AI assistance: Codex and Claude drafted the implementation, checks and report
formatting; reviewed by the author (Abubaker Attique).
Run: python 03_Length_Bias_and_SimPO.py
GPU benchmark (NVIDIA): python 03_Length_Bias_and_SimPO.py --benchmark-cuda
GPU benchmark (Apple Silicon): python 03_Length_Bias_and_SimPO.py --benchmark-mps
Other scored preference pairs: --pairs path/to/pairs.json
Re-score the real pairs (downloads two ~135M models): --score-real
Reference: Meng et al., SimPO, https://arxiv.org/abs/2405.14734

What is real and what is not:
* results/length_bias_scored_pairs.json holds 100 real Anthropic HH-RLHF
  helpful-base test pairs scored by SmolLM2-135M-Instruct (policy) and
  SmolLM2-135M (reference). This is an exploratory checkpoint comparison, NOT
  a DPO model trained by this squad; dataset, revisions and limits are in
  results/length_bias_evaluation.json. Correlation is association, not cause.
* The SimPO loss example uses synthetic numbers (arithmetic check only).
* The memory accounting uses a small token-level model, not a pretrained LLM.
  It reports weight-only memory separately from total training memory: a 50%
  weight-only saving is NOT a 50% total training-memory saving. Only
  --benchmark-cuda and --benchmark-mps measure GPU allocator memory.
"""
import argparse
import copy
import gc
import json
import math
import random
import subprocess
import sys
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F


def calculate_pearson_correlation(x, y):
    """Pearson r; undefined (constant input) is NaN, never zero correlation."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("Provide equal-length vectors with at least two pairs")
    if not all(math.isfinite(float(v)) for v in [*x, *y]):
        raise ValueError("Correlation inputs must be finite")
    mean_x, mean_y = sum(x)/len(x), sum(y)/len(y)  # computed once: O(n), not O(n^2)
    dx = [float(v)-mean_x for v in x]
    dy = [float(v)-mean_y for v in y]
    denominator = math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    if denominator == 0:
        return float('nan')
    return max(-1.0, min(1.0, sum(a*b for a,b in zip(dx,dy))/denominator))


def diagnose_length_bias(pairs):
    """Use response-token counts and sequence SUM logps from policy/reference.

    Required keys per pair: chosen_length, rejected_length, policy_chosen_logp,
    policy_rejected_logp, ref_chosen_logp, ref_rejected_logp. Exclude prompt and
    padding tokens consistently. A positive r is association, not causal proof.
    """
    lengths, margins = [], []
    for row in pairs:
        for key in ('chosen_length', 'rejected_length'):
            if not isinstance(row[key], int) or isinstance(row[key], bool) or row[key] <= 0:
                raise ValueError("Response lengths must be positive integer token counts")
        lengths.append(row['chosen_length']-row['rejected_length'])
        margins.append((row['policy_chosen_logp']-row['ref_chosen_logp']) -
                       (row['policy_rejected_logp']-row['ref_rejected_logp']))
    return {'pairs': len(pairs), 'length_differences': lengths,
            'dpo_logratio_margins': margins,
            'pearson_r': calculate_pearson_correlation(lengths, margins)}


PAIR_KEYS = ('chosen_length', 'rejected_length', 'policy_chosen_logp',
             'policy_rejected_logp', 'ref_chosen_logp', 'ref_rejected_logp')
RESULTS_DIR = Path(__file__).resolve().parent / 'results'
DEFAULT_PAIRS = RESULTS_DIR / 'length_bias_scored_pairs.json'
DEFAULT_EVALUATION = RESULTS_DIR / 'length_bias_evaluation.json'


def bootstrap_pearson_ci(x, y, resamples=1000, seed=123):
    """Approximate 95% percentile interval for Pearson r (pair resampling, fixed seed)."""
    rng, n, boots = random.Random(seed), len(x), []
    for _ in range(resamples):
        pos = [rng.randrange(n) for _ in range(n)]
        r = calculate_pearson_correlation([x[i] for i in pos], [y[i] for i in pos])
        if math.isfinite(r):
            boots.append(r)
    if not boots:
        return float('nan'), float('nan')
    boots.sort()
    return boots[int(.025*(len(boots)-1))], boots[int(.975*(len(boots)-1))]


def describe_correlation(r):
    """Sign-aware plain-language reading of a length correlation (never causal)."""
    if not math.isfinite(r):
        return 'undefined (constant input)'
    size = 'negligible' if abs(r) < .1 else 'weak' if abs(r) < .3 else 'moderate' if abs(r) < .5 else 'strong'
    if size == 'negligible':
        return 'negligible length dependence'
    side = 'HIGHER' if r > 0 else 'LOWER'
    return f'{size} length dependence: when the chosen answer is longer the margin tends to be {side}'


def load_pairs(path):
    """Read and validate a JSON list of scored pairs; exit with a clear message on bad input."""
    try:
        pairs = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'ERROR: pairs file not found: {path}')
    except json.JSONDecodeError as exc:
        raise SystemExit(f'ERROR: {path} is not valid JSON: {exc}')
    if not isinstance(pairs, list) or len(pairs) < 2:
        raise SystemExit('ERROR: expected a JSON list with at least two scored pairs')
    for i, row in enumerate(pairs):
        missing = [k for k in PAIR_KEYS if not isinstance(row, dict) or k not in row]
        if missing:
            raise SystemExit(f'ERROR: pair {i} is missing keys: {missing}')
    return pairs


def synthetic_pairs():
    """Ten invented pairs (the starter's numbers): arithmetic check only, not evidence."""
    lengths = [120, -40, 210, 85, -90, 175, 230, -15, 140, 195]
    margins = [1.8, -.4, 2.7, 1.2, -1.1, 2.3, 3.1, -.1, 1.9, 2.6]
    return [dict(chosen_length=300+d, rejected_length=300, policy_chosen_logp=-500+m, ref_chosen_logp=-500,
                 policy_rejected_logp=-500, ref_rejected_logp=-500) for d, m in zip(lengths, margins)]


def average_token_logps(token_logps, response_mask):
    """Average already-aligned token logps over response tokens only.

    Caller performs any causal label shift before this function. False mask
    entries include padding/prompt tokens and receive zero gradient.
    """
    if token_logps.ndim != 2 or response_mask.shape != token_logps.shape or response_mask.dtype != torch.bool:
        raise ValueError("Expected [batch,tokens] logps and same-shape boolean mask")
    if not token_logps.is_floating_point() or token_logps.device != response_mask.device:
        raise ValueError("Floating logps and mask must share device")
    lengths = response_mask.sum(-1)
    if token_logps.shape[0] == 0 or (lengths == 0).any():
        raise ValueError("Every sequence must contain at least one response token")
    if not torch.isfinite(token_logps[response_mask]).all():
        raise ValueError("Response log probabilities must be finite")
    values = token_logps.float() if token_logps.dtype in (torch.float16, torch.bfloat16) else token_logps
    return values.masked_fill(~response_mask, 0).sum(-1)/lengths


class SimPOLoss(nn.Module):
    """-mean(logsigmoid(beta*(mean_logp_w - mean_logp_l) - gamma)).

    Gamma is subtracted ONCE from the pairwise difference, not from both
    rewards (where it would cancel). Normalisation mitigates length bias;
    it does not guarantee its elimination on arbitrary datasets.
    """
    def __init__(self, beta=2.0, gamma=0.5):
        super().__init__()
        if not math.isfinite(beta) or beta <= 0 or not math.isfinite(gamma) or gamma < 0:
            raise ValueError("beta must be positive and gamma nonnegative, both finite")
        self.beta, self.gamma = beta, gamma

    def forward(self, chosen_avg_logps, rejected_avg_logps):
        if chosen_avg_logps.ndim != 1 or chosen_avg_logps.shape != rejected_avg_logps.shape or chosen_avg_logps.numel() == 0:
            raise ValueError("Expected equal nonempty [batch] average logps")
        if chosen_avg_logps.device != rejected_avg_logps.device:
            raise ValueError("Both batches must share device")
        for t in (chosen_avg_logps, rejected_avg_logps):
            if not t.is_floating_point() or not torch.isfinite(t).all():
                raise ValueError("Logps must be floating point and finite")
        w, l = chosen_avg_logps, rejected_avg_logps
        if w.dtype in (torch.float16, torch.bfloat16): w = w.float()
        if l.dtype in (torch.float16, torch.bfloat16): l = l.float()
        rw, rl = self.beta*w, self.beta*l
        logits = rw-rl-self.gamma
        loss = -F.logsigmoid(logits).mean()
        metrics = {k: v.detach() for k,v in {
            'loss': loss, 'reward_w': rw.mean(), 'reward_l': rl.mean(),
            'reward_gap': (rw-rl).mean(), 'win_rate': (rw>rl).float().mean(),
            'margin_pass_rate': (rw-rl>self.gamma).float().mean(),
            'margin_prob': torch.sigmoid(logits).mean()}.items()}
        return loss, metrics


def profile_memory_usage(num_params=7_000_000_000, batch_size=4, seq_len=2048):
    """Analytical FP16 weight-only GiB; no activation/optimizer estimate.

    batch_size/seq_len retained for starter-call compatibility; they do not
    change weight storage. No measured total training-memory claim is made.
    """
    if num_params <= 0: raise ValueError("num_params must be positive")
    one = num_params*2/2**30
    return {'policy_weight_gib': one, 'dpo_two_model_weights_gib': 2*one,
            'simpo_one_model_weights_gib': one, 'weight_only_savings_percent': 50.0}


class TinyTokenModel(nn.Module):
    """Synthetic benchmark fixture; not a transformer or pretrained LLM."""
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(1024, 256)
        self.output = nn.Linear(256, 1024, bias=False)
    def forward(self, ids):
        return self.output(self.embedding(ids))


def _training_step(policy, ref, ids, labels, mask, optimizer, probe=None):
    """One optimiser step on the synthetic fixture: DPO if ref is given, else SimPO.

    Rows 0-3 are the chosen answers and rows 4-7 the rejected ones. Labels are
    already-aligned targets. The reference model never receives gradients.
    probe(stage) is an optional callback used by the MPS benchmark to sample memory.
    """
    optimizer.zero_grad(set_to_none=True)
    token_logps = policy(ids).log_softmax(-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1)
    if ref is not None:
        with torch.no_grad():
            ref_logps = ref(ids).log_softmax(-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1).sum(-1)
        delta = token_logps.sum(-1)-ref_logps
        loss = -F.logsigmoid(0.1*(delta[:4]-delta[4:])).mean()
    else:
        averages = average_token_logps(token_logps, mask)
        loss, _ = SimPOLoss()(averages[:4], averages[4:])
    if probe: probe('after forward')
    loss.backward()
    if probe: probe('after backward')
    optimizer.step()
    if probe: probe('after optimiser step')
    if ref is not None:
        assert all(p.grad is None for p in ref.parameters())
    return loss.item()


def measure_tensor_bytes():
    """MEASURED CPU accounting of the same toy fixture used by benchmark_cuda (MiB).

    Sums the bytes of model weights, gradients, AdamW state and the tensors autograd
    saves for backward (de-duplicated by storage, parameters excluded). This is NOT
    GPU VRAM: allocator overhead and short-lived buffers (for example the reference
    model's no-grad forward) are not counted, so real peaks can be higher for DPO.
    """
    MiB, rows = 2**20, {}
    for method in ('DPO', 'SimPO'):
        torch.manual_seed(42)
        policy = TinyTokenModel()
        ref = copy.deepcopy(policy).requires_grad_(False).eval() if method == 'DPO' else None
        ids = torch.randint(0, 1024, (8, 128)); labels = torch.randint(0, 1024, (8, 128))
        mask = torch.ones_like(labels, dtype=torch.bool)
        optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-4, foreach=False)
        models = [policy] + ([ref] if ref is not None else [])
        param_storage = {p.untyped_storage().data_ptr() for m in models for p in m.parameters()}
        saved = {}
        def pack(t):
            storage = t.untyped_storage()
            if storage.data_ptr() not in param_storage:
                saved[storage.data_ptr()] = storage.nbytes()
            return t
        _training_step(policy, ref, ids, labels, mask, optimizer)  # warm-up creates AdamW state
        with torch.autograd.graph.saved_tensors_hooks(pack, lambda t: t):
            loss = _training_step(policy, ref, ids, labels, mask, optimizer)
        nbytes = lambda tensors: sum(t.numel()*t.element_size() for t in tensors)
        weights = nbytes(p for m in models for p in m.parameters())
        grads = nbytes(p.grad for p in policy.parameters() if p.grad is not None)
        adam = nbytes(t for s in optimizer.state.values() for t in s.values() if torch.is_tensor(t))
        activations = sum(saved.values())
        rows[method] = {'weights': weights/MiB, 'gradients': grads/MiB, 'adamw_state': adam/MiB,
                        'saved_activations': activations/MiB,
                        'total': (weights+grads+adam+activations)/MiB, 'loss': loss}
    return {'unit': 'MiB', 'rows': rows,
            'weight_only_savings_percent': 100*(1-rows['SimPO']['weights']/rows['DPO']['weights']),
            'total_savings_percent': 100*(1-rows['SimPO']['total']/rows['DPO']['total'])}


def benchmark_cuda():
    """Compare identical FP32 policies, paired batches, AdamW and loss steps.

    Ref gradients are disabled. Synthetic labels are already aligned targets.
    Warmup creates optimizer state before measuring a steady training step.
    Allocation measurements are bytes from the CUDA allocator, not nvidia-smi.
    """
    if not torch.cuda.is_available():
        return {'status': 'NOT RUN: CUDA unavailable; GPU measurements remain pending'}
    rows = []
    for method in ('DPO', 'SimPO'):
        gc.collect(); torch.cuda.empty_cache(); torch.manual_seed(42)
        baseline = torch.cuda.memory_allocated()
        policy = TinyTokenModel().cuda()
        ref = copy.deepcopy(policy).requires_grad_(False).eval() if method == 'DPO' else None
        torch.cuda.synchronize()
        weights = torch.cuda.memory_allocated()-baseline
        ids = torch.randint(0, 1024, (8, 128), device='cuda')
        labels = torch.randint(0, 1024, (8, 128), device='cuda')
        mask = torch.ones_like(labels, dtype=torch.bool)
        optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-4, foreach=False)
        _training_step(policy, ref, ids, labels, mask, optimizer)
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        loss_value = _training_step(policy, ref, ids, labels, mask, optimizer); torch.cuda.synchronize()
        rows.append({'method': method, 'model_weight_allocation_mib': weights/2**20,
                     'peak_training_allocation_mib': (torch.cuda.max_memory_allocated()-baseline)/2**20,
                     'loss': loss_value})
        del optimizer, policy, ref, ids, labels, mask
    return {'status': 'MEASURED', 'device': torch.cuda.get_device_name(),
            'dtype': 'float32', 'batch_pairs': 4, 'tokens': 128, 'vocabulary': 1024,
            'hidden': 256, 'seed': 42, 'optimizer': 'AdamW, foreach=False',
            'rows': rows, 'peak_training_savings_percent':
            100*(1-rows[1]['peak_training_allocation_mib']/rows[0]['peak_training_allocation_mib'])}


def _chip_name():
    try:
        out = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or 'Apple Silicon'
    except Exception:
        return 'Apple Silicon'


def benchmark_mps():
    """Apple-Silicon (MPS) counterpart of benchmark_cuda, for a Mac without CUDA.

    Same fixture, FP32, AdamW and loss steps as benchmark_cuda. PyTorch's MPS backend has
    no reset-peak call, so allocation is sampled with torch.mps.current_allocated_memory()
    at three points of one steady training step (after the forward pass, after backward, after
    the optimiser step) and the largest sample is the reported figure. That is a LOWER BOUND on
    the true peak: buffers that live only inside one operation are not seen. Apple Silicon has
    unified memory, so these are allocator bytes taken from system RAM, not dedicated VRAM.
    """
    if not (hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()):
        return {'status': 'NOT RUN: MPS unavailable; run this on an Apple-Silicon Mac with a current PyTorch'}
    device, rows = 'mps', []
    for method in ('DPO', 'SimPO'):
        gc.collect(); torch.mps.synchronize(); torch.mps.empty_cache(); torch.manual_seed(42)
        baseline = torch.mps.current_allocated_memory()
        policy = TinyTokenModel().to(device)
        ref = copy.deepcopy(policy).requires_grad_(False).eval() if method == 'DPO' else None
        torch.mps.synchronize()
        weights = torch.mps.current_allocated_memory()-baseline
        ids = torch.randint(0, 1024, (8, 128), device=device)
        labels = torch.randint(0, 1024, (8, 128), device=device)
        mask = torch.ones_like(labels, dtype=torch.bool)
        optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-4, foreach=False)
        _training_step(policy, ref, ids, labels, mask, optimizer)  # warm-up creates AdamW state
        optimizer.zero_grad(set_to_none=True)
        stages = {}
        def probe(stage):
            torch.mps.synchronize()
            stages[stage] = (torch.mps.current_allocated_memory()-baseline)/2**20
        loss_value = _training_step(policy, ref, ids, labels, mask, optimizer, probe)
        rows.append({'method': method, 'model_weight_allocation_mib': weights/2**20,
                     'stages_mib': stages, 'peak_training_allocation_mib': max(stages.values()),
                     'loss': loss_value})
        del optimizer, policy, ref, ids, labels, mask
    return {'status': 'MEASURED', 'backend': 'mps', 'device': _chip_name()+' (MPS, unified memory)',
            'dtype': 'float32', 'batch_pairs': 4, 'tokens': 128, 'vocabulary': 1024,
            'hidden': 256, 'seed': 42, 'optimizer': 'AdamW, foreach=False',
            'method': 'sampled at 3 points of one step; lower bound of the true peak',
            'rows': rows, 'peak_training_savings_percent':
            100*(1-rows[1]['peak_training_allocation_mib']/rows[0]['peak_training_allocation_mib'])}


def verify_correctness():
    assert math.isclose(calculate_pearson_correlation([1,2,3],[2,4,6]),1)
    assert math.isclose(calculate_pearson_correlation([1,2,3],[6,4,2]),-1)
    assert math.isnan(calculate_pearson_correlation([1,1],[2,3]))
    for x,y in [([],[]),([1],[1]),([1,2],[1]),([1,float('nan')],[1,2])]:
        try: calculate_pearson_correlation(x,y)
        except ValueError: pass
        else: raise AssertionError('Invalid correlation input accepted')
    print('PASS: Pearson positive/negative/undefined and invalid inputs')
    w=torch.tensor([-.2,-.4],dtype=torch.float64,requires_grad=True)
    l=torch.tensor([-.7,-.8],dtype=torch.float64,requires_grad=True)
    loss,metrics=SimPOLoss()(w,l)
    torch.testing.assert_close(loss,F.softplus(-2*(w-l)+.5).mean())
    loss.backward(); assert (w.grad<0).all() and (l.grad>0).all()
    assert all(not v.requires_grad for v in metrics.values())
    assert torch.autograd.gradcheck(lambda a,b: SimPOLoss()(a,b)[0],(w,l))
    baseline=SimPOLoss()(w.detach(),l.detach())[0]
    assert SimPOLoss()(w.detach()+.1,l.detach())[0]<baseline
    assert SimPOLoss(gamma=1)(w.detach(),l.detach())[0]>baseline
    # FP16 differences that would overflow if performed before promotion.
    assert torch.isfinite(SimPOLoss()(torch.tensor([-65000.],dtype=torch.float16),torch.tensor([0.],dtype=torch.float16))[0])
    values=torch.tensor([[-.2,-.4,float('nan')]],requires_grad=True)
    mask=torch.tensor([[True,True,False]])
    mean=average_token_logps(values,mask)
    torch.testing.assert_close(mean,torch.tensor([-.3]))
    mean.sum().backward();assert values.grad[0,2]==0
    try: average_token_logps(values,torch.zeros_like(mask))
    except ValueError: pass
    else: raise AssertionError('Empty response accepted')
    # Duplicating all tokens must not change a normalised reward.
    torch.testing.assert_close(average_token_logps(values.repeat(1,2),mask.repeat(1,2)),mean)
    print('PASS: SimPO formula, finite differences, gradient direction, margin, stability and masked normalisation')
    # Report helpers: fixture r, bootstrap interval, wording and input validation.
    fixture = diagnose_length_bias(synthetic_pairs())
    assert math.isclose(fixture['pearson_r'], 0.9989162387658821, rel_tol=1e-9)
    lo, hi = bootstrap_pearson_ci([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert math.isclose(lo, 1.0) and math.isclose(hi, 1.0)
    assert bootstrap_pearson_ci([1, 2, 3, 4], [4, 1, 3, 2], 200, 7) == bootstrap_pearson_ci([1, 2, 3, 4], [4, 1, 3, 2], 200, 7)
    assert 'LOWER' in describe_correlation(-.42) and 'HIGHER' in describe_correlation(.42)
    assert 'negligible' in describe_correlation(.05) and 'undefined' in describe_correlation(float('nan'))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (('bad.json', '{'), ('short.json', '[]'), ('keys.json', '[{"chosen_length": 3}, {"chosen_length": 4}]')):
            path = Path(tmp)/name; path.write_text(text, encoding='utf-8')
            try: load_pairs(path)
            except SystemExit: pass
            else: raise AssertionError('Invalid pairs file accepted: '+name)
        good = Path(tmp)/'good.json'; good.write_text(json.dumps(synthetic_pairs()), encoding='utf-8')
        assert len(load_pairs(good)) == 10
    print('PASS: bootstrap interval, correlation wording and pairs-file validation')


def score_real_preferences(output_dir, sample_size=100):
    """CPU evaluation on pinned HH-RLHF helpful-base/test preference pairs.

    Optional dependencies: transformers==4.57.6, numpy. Downloads public data
    and two ~135M models into output_dir. No external inference API is used.
    The instruct/base comparison is exploratory, not a DPO training experiment.
    """
    import gzip
    import hashlib
    import importlib.util
    import platform
    import random
    from datetime import datetime, timezone
    from urllib.request import urlopen
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    policy_id = 'HuggingFaceTB/SmolLM2-135M-Instruct'
    ref_id = 'HuggingFaceTB/SmolLM2-135M'
    policy_rev = '12fd25f77366fa6b3b4b768ec3050bf629380bac'
    ref_rev = '93efa2f097d58c2a74874c7e644dbc9b0cee75a2'
    data_rev = '09be8c5bbc57cb3887f3a9732ad6aa7ec602a1fa'
    data_url = f'https://huggingface.co/datasets/Anthropic/hh-rlhf/resolve/{data_rev}/helpful-base/test.jsonl.gz'
    cache = output_dir / 'hf_cache'
    data_path = output_dir / 'helpful-base-test.jsonl.gz'
    if not data_path.exists():
        print('Downloading pinned helpfulness test split...', flush=True)
        with urlopen(data_url, timeout=120) as response:
            data_path.write_bytes(response.read())
    with gzip.open(data_path, 'rt', encoding='utf-8') as stream:
        dataset = [json.loads(line) for line in stream if line.strip()]
    tok = AutoTokenizer.from_pretrained(policy_id, revision=policy_rev, cache_dir=cache, token=False)
    ref_tok = AutoTokenizer.from_pretrained(ref_id, revision=ref_rev, cache_dir=cache, token=False)
    if tok.get_vocab() != ref_tok.get_vocab():
        raise ValueError('Policy and reference vocabularies differ')
    torch.set_num_threads(4)
    torch.manual_seed(42)
    indices = list(range(len(dataset)))
    random.Random(42).shuffle(indices)
    selected, encoded = [], []
    excluded = {'context_mismatch': 0, 'length_or_boundary': 0}
    for index in indices:
        pair = dataset[index]
        boundary = '\n\nAssistant:'
        pc, sep_c, rc = pair['chosen'].rpartition(boundary)
        pr, sep_r, rr = pair['rejected'].rpartition(boundary)
        if not sep_c or not sep_r or pc != pr:
            excluded['context_mismatch'] += 1
            continue
        prefix = pc + boundary
        items = []
        for response in (rc, rr):
            full = tok(prefix+response, add_special_tokens=False, return_offsets_mapping=True)
            offsets = full['offset_mapping']
            # Reject a token that straddles the prompt/response character boundary.
            crossing = any(a < len(prefix) < b for a,b in offsets)
            ids = full['input_ids']
            response_mask = [a >= len(prefix) and b > a for a,b in offsets]
            if tok.bos_token_id is not None:
                ids = [tok.bos_token_id]+ids
                response_mask = [False]+response_mask
            if crossing or len(ids)>512 or len(ids)<2 or not any(response_mask[1:]):
                items = []; break
            items.append((ids,response_mask))
        if len(items)!=2:
            excluded['length_or_boundary'] += 1
            continue
        selected.append({'dataset_row': index,
                         'pair_sha256': hashlib.sha256((pair['chosen']+'\0'+pair['rejected']).encode()).hexdigest(),
                         'chosen_length': sum(items[0][1][1:]),
                         'rejected_length': sum(items[1][1][1:])})
        encoded.extend(items)
        if len(selected)==sample_size: break
    if len(selected)!=sample_size:
        raise ValueError('Insufficient pairs under the fixed eligibility rules')
    print(f'Selected {sample_size} pairs (no response truncation), skipped {excluded}', flush=True)
    # Cross-check summed scores with the squad Part 1 function on the first answer.
    spec = importlib.util.spec_from_file_location('mission4_dpo', Path(__file__).with_name('01_DPO_Loss_Core.py'))
    dpo = importlib.util.module_from_spec(spec); spec.loader.exec_module(dpo)
    for name, model_id, revision in [('policy',policy_id,policy_rev),('ref',ref_id,ref_rev)]:
        print('Loading '+model_id, flush=True)
        model = AutoModelForCausalLM.from_pretrained(model_id, revision=revision, cache_dir=cache,
                   token=False, trust_remote_code=False, use_safetensors=True, dtype=torch.float32).eval()
        model.requires_grad_(False)
        values = []
        with torch.inference_mode():
            for i,(ids,mask) in enumerate(encoded):
                x = torch.tensor([ids],dtype=torch.long)
                logits = model(input_ids=x, use_cache=False).logits
                # Actual teacher-forced log p(token_t | prefix and preceding tokens).
                per_token = -F.cross_entropy(logits[0,:-1].float(), x[0,1:], reduction='none')
                response_mask = torch.tensor(mask[1:],dtype=torch.bool)
                value = per_token[response_mask].double().sum().item()
                if not math.isfinite(value): raise ValueError('Nonfinite model score')
                if i==0:
                    labels = x.clone(); labels[0,~torch.tensor(mask)] = -100
                    reference = dpo.get_batch_logps(logits,labels).item()
                    if not math.isclose(value,reference,rel_tol=1e-5,abs_tol=1e-4):
                        raise AssertionError('Scoring disagrees with Part 1 log-probability gather')
                values.append(value)
                if (i+1)%20==0: print(f'{name}: {i+1}/{len(encoded)} answers scored',flush=True)
                del logits, per_token
        for i,row in enumerate(selected):
            row[name+'_chosen_logp'] = values[2*i]
            row[name+'_rejected_logp'] = values[2*i+1]
        del model
        gc.collect()
    diagnostic = diagnose_length_bias(selected)
    normalised_margins = [(r['policy_chosen_logp']/r['chosen_length']-
                          r['policy_rejected_logp']/r['rejected_length']) for r in selected]
    normalised_r = calculate_pearson_correlation(diagnostic['length_differences'],normalised_margins)
    w = torch.tensor([r['policy_chosen_logp']/r['chosen_length'] for r in selected])
    l = torch.tensor([r['policy_rejected_logp']/r['rejected_length'] for r in selected])
    loss, metrics = SimPOLoss()(w,l)
    rng = random.Random(123)
    boots = []
    for _ in range(1000):
        positions = [rng.randrange(sample_size) for _ in range(sample_size)]
        r = calculate_pearson_correlation([diagnostic['length_differences'][i] for i in positions],
                                          [diagnostic['dpo_logratio_margins'][i] for i in positions])
        if math.isfinite(r): boots.append(r)
    boots.sort()
    ci = [boots[int(.025*(len(boots)-1))],boots[int(.975*(len(boots)-1))]]
    metadata = {'executed_utc': datetime.now(timezone.utc).isoformat(),
        'dataset': 'Anthropic/hh-rlhf', 'dataset_revision': data_rev,
        'dataset_file': 'helpful-base/test.jsonl.gz', 'dataset_url': data_url,
        'dataset_file_sha256': hashlib.sha256(data_path.read_bytes()).hexdigest(),
        'policy': policy_id, 'policy_revision': policy_rev, 'reference': ref_id, 'reference_revision': ref_rev,
        'sample_size': sample_size, 'dataset_rows': len(dataset), 'selection_seed':42, 'excluded_before_sample_filled':excluded,
        'selection': 'Shuffle dataset indices with random.Random(42); take first eligible pairs. Shared final assistant prompt; both complete sequences <=512 tokens; no truncation.',
        'format': 'Dataset Human:/Assistant: text for BOTH checkpoints; not instruct chat template. BOS prepended if tokenizer supplies it. No EOS appended. Response-only tokens, causal shift; padding absent.',
        'device':'cpu','dtype':'float32','threads':4,'torch':torch.__version__, 'transformers':transformers.__version__,
        'python': platform.python_version(), 'trained_here':False,
        'limitations':'Exploratory instruct/base log-ratio comparison; base is not claimed as original DPO training reference. 100 short-context eligible test pairs, not full dataset. Checkpoint training overlap unknown. No causal bias or SimPO training-improvement claim.',
        'bootstrap': '1000 pair resamples, seed123, approximate percentile interval; small selected sample only',
        'scoring_validation': 'First answer under each model cross-checked with Part1 get_batch_logps; matching vocabulary asserted'}
    results = {'metadata': metadata, 'diagnostic':diagnostic, 'pearson_bootstrap_95pct':ci,
               'simpo_normalised_margin_length_r':normalised_r,
               'simpo_metrics':{k:v.item() for k,v in metrics.items()}}
    (output_dir/'scored_pairs.json').write_text(json.dumps(selected,indent=2)+'\n')
    (output_dir/'evaluation.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps({k:v for k,v in results.items() if k!='metadata' and k!='diagnostic'},indent=2))
    print('MEASURED Pearson r:',diagnostic['pearson_r'],flush=True)
    print('Evidence saved to:',output_dir,flush=True)
    return results


LINE = '=' * 70


def _provenance_lines(evaluation):
    meta = (evaluation or {}).get('metadata')
    if not meta:
        return ['    Provenance: not supplied with this pairs file; document dataset, models and masking yourself.']
    rev = lambda key: str(meta.get(key, '?'))[:7]
    lines = [f"    Data    : {meta.get('dataset')} {meta.get('dataset_file')} @ {rev('dataset_revision')}, "
             f"{meta.get('sample_size')} pairs (seed {meta.get('selection_seed')}, no truncation)",
             f"    Policy  : {meta.get('policy')} @ {rev('policy_revision')}",
             f"    Ref     : {meta.get('reference')} @ {rev('reference_revision')}"]
    if meta.get('trained_here') is False:
        lines.append('    Status  : exploratory instruct-vs-base comparison; no model was trained here')
    return lines


def report_length_bias(pairs, source, evaluation=None, synthetic=False):
    result = diagnose_length_bias(pairs)
    lengths, margins = result['length_differences'], result['dpo_logratio_margins']
    lo, hi = bootstrap_pearson_ci(lengths, margins)
    ratio = lambda r, side: (r['policy_'+side+'_logp']-r['ref_'+side+'_logp'])/r[side+'_length']
    normalised = [ratio(r, 'chosen')-ratio(r, 'rejected') for r in pairs]
    simpo_gap = [r['policy_chosen_logp']/r['chosen_length']-r['policy_rejected_logp']/r['rejected_length'] for r in pairs]
    n = len(pairs)
    print(f'[2] LENGTH-BIAS DIAGNOSTIC  ({source})')
    if synthetic:
        print('    SYNTHETIC fixture: arithmetic check only, not evidence of real-model verbosity bias.')
    for line in _provenance_lines(evaluation):
        print(line)
    print(f"    Pairs   : {n}; chosen answer is the longer one in {sum(v > 0 for v in lengths)}")
    print(f"    Mean per-token log-ratio (policy vs ref): chosen {sum(ratio(r, 'chosen') for r in pairs)/n:+.4f}, "
          f"rejected {sum(ratio(r, 'rejected') for r in pairs)/n:+.4f}")
    print('    Pearson r against the length difference |yw|-|yl|:')
    print(f"      DPO log-ratio margin (summed, dw-dl)      : {result['pearson_r']:+.3f}   95% bootstrap [{lo:+.3f}, {hi:+.3f}]")
    if not synthetic:  # the invented fixture has no per-token structure, so these two would mislead
        print(f"      length-normalised log-ratio margin        : {calculate_pearson_correlation(lengths, normalised):+.3f}")
        print(f"      SimPO margin (avg-logp gap, ref-free)     : {calculate_pearson_correlation(lengths, simpo_gap):+.3f}")
    print(f"    Implicit-reward accuracy (dw-dl > 0)        : {100*sum(m > 0 for m in margins)/n:.0f}%")
    print(f"    Reading : {describe_correlation(result['pearson_r'])}.")
    print('    Association only, not cause. The sign depends on the checkpoints: a negative mean per-token')
    print('    log-ratio makes longer answers score LOWER, a positive one HIGHER.')


def report_simpo(real_pairs=None):
    print('[3] SimPO LOSS (beta=2.0, gamma=0.5, average per-token log-probs)')
    cases = [('Synthetic sample, 4 pairs (arithmetic check)',
              torch.tensor([-.15, -.22, -.18, -.12]), torch.tensor([-.45, -.38, -.52, -.41]))]
    if real_pairs:
        cases.append((f'Real pairs, policy log-probs, {len(real_pairs)} pairs (policy was not SimPO-trained)',
                      torch.tensor([r['policy_chosen_logp']/r['chosen_length'] for r in real_pairs]),
                      torch.tensor([r['policy_rejected_logp']/r['rejected_length'] for r in real_pairs])))
    for name, chosen, rejected in cases:
        loss, m = SimPOLoss()(chosen, rejected)
        print(f'    {name}')
        print(f"      loss {loss.item():.4f} | reward gap {m['reward_gap'].item():+.3f} | "
              f"win rate (gap>0) {100*m['win_rate'].item():.0f}% | margin pass rate (gap>gamma) {100*m['margin_pass_rate'].item():.0f}%")


def report_memory(backend=None):
    print('[4] MEMORY: DPO (policy + frozen reference) vs SimPO (policy only)')
    a = profile_memory_usage()
    print(f"    Analytical, 7B model, FP16 weights only : DPO {a['dpo_two_model_weights_gib']:.2f} GiB | "
          f"SimPO {a['simpo_one_model_weights_gib']:.2f} GiB | saving {a['weight_only_savings_percent']:.1f}%")
    m = measure_tensor_bytes(); rows = m['rows']
    print('    MEASURED CPU tensor-byte accounting, toy token model, FP32 AdamW (MiB; NOT GPU VRAM):')
    print(f"      {'component':<20}{'DPO':>10}{'SimPO':>10}")
    for key, label in (('weights', 'model weights'), ('gradients', 'gradients'), ('adamw_state', 'AdamW state'),
                       ('saved_activations', 'saved activations'), ('total', 'TOTAL')):
        print(f"      {label:<20}{rows['DPO'][key]:>10.2f}{rows['SimPO'][key]:>10.2f}")
    print(f"      saving: weights only {m['weight_only_savings_percent']:.1f}% | total {m['total_savings_percent']:.1f}%")
    print('    The briefing\'s ~50% holds for stored weights only. Gradients, optimiser state and activations')
    print('    exist once in both methods, so the total saving is smaller. A real VRAM figure needs a GPU run.')
    if backend is None:
        print('    GPU allocator measurement not requested: run with --benchmark-cuda (CUDA machine, e.g. Colab T4)')
        print('    or --benchmark-mps (Apple-Silicon Mac).')
        return 0
    result = benchmark_cuda() if backend == 'cuda' else benchmark_mps()
    if result['status'] != 'MEASURED':
        print('    '+result['status'])
        return 1
    allocator = 'CUDA allocator' if backend == 'cuda' else 'MPS allocator'
    print(f"    MEASURED on {result['device']} ({allocator}, MiB; {result['dtype']}, {result['optimizer']}):")
    print(f"      {'method':<8}{'weights':>10}{'peak training':>16}")
    for row in result['rows']:
        print(f"      {row['method']:<8}{row['model_weight_allocation_mib']:>10.2f}{row['peak_training_allocation_mib']:>16.2f}")
    print(f"      peak-training saving, SimPO vs DPO: {result['peak_training_savings_percent']:.1f}%")
    if backend == 'mps':
        print(f"      Sampled allocation per stage (MiB, {result['method']}):")
        stages = list(result['rows'][0]['stages_mib'])
        print(f"        {'stage':<24}" + ''.join(f"{r['method']:>10}" for r in result['rows']))
        for stage in stages:
            print(f"        {stage:<24}" + ''.join(f"{r['stages_mib'][stage]:>10.2f}" for r in result['rows']))
        print('      Unified memory: this is allocator bytes from system RAM, not dedicated VRAM.')
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pairs', type=Path, help='JSON list of scored preference pairs; see diagnose_length_bias')
    gpu = parser.add_mutually_exclusive_group()
    gpu.add_argument('--benchmark-cuda', action='store_true', help='measure CUDA allocator memory (needs an NVIDIA GPU)')
    gpu.add_argument('--benchmark-mps', action='store_true', help='measure MPS allocator memory (Apple-Silicon Mac)')
    parser.add_argument('--verify-only', action='store_true', help='run the self-checks and stop')
    parser.add_argument('--score-real', action='store_true',
                        help='re-score 100 real HH-RLHF pairs with SmolLM2 (downloads data and two ~135M models)')
    parser.add_argument('--evidence-dir', type=Path, default=Path(__file__).resolve().parent/'logs'/'length_bias_real',
                        help='where --score-real writes its files (git-ignored by default)')
    args = parser.parse_args()
    print(LINE)
    print('USSE NOOSPHERE • LENGTH BIAS AUDIT & REFERENCE-FREE SimPO CORE')
    print('Mission 04 / Part 3 — Data & Payload Specialist')
    print(LINE)
    print('[1] SELF-CHECKS')
    verify_correctness()
    if args.verify_only:
        return 0
    if args.score_real:
        score_real_preferences(args.evidence_dir)
        print(f'To make these the default evidence, copy scored_pairs.json and evaluation.json from\n  {args.evidence_dir}\n'
              f'to {RESULTS_DIR} as length_bias_scored_pairs.json and length_bias_evaluation.json.')
        return 0
    evaluation, synthetic = None, False
    if args.pairs:
        pairs, source = load_pairs(args.pairs), f'pairs file {args.pairs}; provenance is the author\'s to document'
    elif DEFAULT_PAIRS.exists():
        pairs, source = load_pairs(DEFAULT_PAIRS), 'real exploratory pairs'
        if DEFAULT_EVALUATION.exists():
            evaluation = json.loads(DEFAULT_EVALUATION.read_text(encoding='utf-8'))
    else:
        pairs, source, synthetic = synthetic_pairs(), 'synthetic fixture', True
    print(LINE)
    report_length_bias(pairs, source, evaluation, synthetic)
    print(LINE)
    report_simpo(None if synthetic else pairs)
    print(LINE)
    status = report_memory('cuda' if args.benchmark_cuda else 'mps' if args.benchmark_mps else None)
    print(LINE)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
