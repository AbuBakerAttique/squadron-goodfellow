"""
Mission 03 — Part 3: Data & Payload Specialist
Grouped-Query Attention (GQA) & Autoregressive KV-Cache Benchmark

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-03-M45 (Pleiades Open Cluster, Seven Sisters)
Subsystem 03: Distributed Multi-Head Attention Mesh & KV-Cache Transceiver

Completed by: Abubaker Attique, Data & Payload Specialist.

Run: python 03_GQA_and_KVCache_Benchmark_starter.py
Requires PyTorch >= 2.4. Use --help for device, dtype and output options.

AI assistance: implementation and tests were drafted with Codex assistance.
Review the code and benchmark assumptions before team sign-off.

Standalone implementation: positional embeddings are not required for these
cache/attention checks. For RoPE integration, rotate new Q/K at their absolute
positions BEFORE storing K, and never rotate cached keys a second time.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
import platform
import statistics
import time
from pathlib import Path

import torch
from torch import nn


class KVCache:
    """Preallocated inference-only cache; stores compact, unexpanded KV heads."""

    def __init__(self, max_batch_size, max_seq_len, n_kv_heads, head_dim,
                 device="cpu", dtype=torch.float32):
        if min(max_batch_size, max_seq_len, n_kv_heads, head_dim) <= 0:
            raise ValueError("Cache dimensions must be positive")
        shape = (max_batch_size, n_kv_heads, max_seq_len, head_dim)
        self.k_cache = torch.empty(shape, device=device, dtype=dtype)
        self.v_cache = torch.empty_like(self.k_cache)
        self.seq_len = 0
        self.batch_size = None

    def reset(self):
        # Old storage is inaccessible until overwritten by contiguous updates.
        self.seq_len, self.batch_size = 0, None

    def update(self, k_val, v_val, start_pos):
        if k_val.ndim != 4 or k_val.shape != v_val.shape:
            raise ValueError("K and V must have identical [batch, KV heads, tokens, head_dim] shapes")
        b, h, n, d = k_val.shape
        B, H, N, D = self.k_cache.shape
        if not (0 < b <= B and h == H and n > 0 and d == D):
            raise ValueError("Input shape does not match cache capacity")
        if start_pos != self.seq_len or start_pos < 0 or start_pos + n > N:
            raise ValueError("Cache updates must be contiguous and within capacity")
        if self.batch_size is not None and b != self.batch_size:
            raise ValueError("Reset cache before changing batch size")
        for val in (k_val, v_val):
            if val.device != self.k_cache.device or val.dtype != self.k_cache.dtype:
                raise ValueError("Cache and inputs must share device and dtype")
        with torch.no_grad():
            self.k_cache[:b, :, start_pos:start_pos+n].copy_(k_val)
            self.v_cache[:b, :, start_pos:start_pos+n].copy_(v_val)
        self.batch_size, self.seq_len = b, start_pos+n
        return self.k_cache[:b, :, :self.seq_len], self.v_cache[:b, :, :self.seq_len]

    def get_memory_mb(self):
        """Allocated capacity in MiB, retained name for starter compatibility."""
        return (self.k_cache.numel()+self.v_cache.numel()) * self.k_cache.element_size() / 2**20

    def used_memory_mib(self):
        b = self.batch_size or 0
        return 2*b*self.k_cache.shape[1]*self.seq_len*self.k_cache.shape[3]*self.k_cache.element_size()/2**20


class GQAAttention(nn.Module):
    """Causal MHA, GQA or MQA according to configurable Q:KV head counts.

    KV head broadcasting uses an explicit group dimension and tensor expansion,
    not a persistent expanded cache. Attention is ordinary PyTorch, not a fused
    FlashAttention implementation. Decode cost still grows with context length.
    """
    def __init__(self, d_model=1024, num_q_heads=16, num_kv_heads=4):
        super().__init__()
        if min(d_model, num_q_heads, num_kv_heads) <= 0:
            raise ValueError("Dimensions must be positive")
        if d_model % num_q_heads or num_q_heads % num_kv_heads:
            raise ValueError("d_model must divide into Q heads; Q heads must divide into KV groups")
        self.d_model, self.num_q_heads, self.num_kv_heads = d_model, num_q_heads, num_kv_heads
        self.head_dim = d_model // num_q_heads
        self.num_queries_per_kv = num_q_heads // num_kv_heads
        self.scale = self.head_dim**-0.5
        self.w_q = nn.Linear(d_model, d_model, bias=False)
        self.w_k = nn.Linear(d_model, num_kv_heads*self.head_dim, bias=False)
        self.w_v = nn.Linear(d_model, num_kv_heads*self.head_dim, bias=False)
        self.w_o = nn.Linear(d_model, d_model, bias=False)

    def forward(self, x, start_pos=0, kv_cache=None):
        if x.ndim != 3 or x.shape[-1] != self.d_model or x.shape[1] == 0:
            raise ValueError("Expected nonempty [batch, tokens, d_model] input")
        if start_pos < 0 or (kv_cache is None and start_pos != 0):
            raise ValueError("Nonzero position requires a cache")
        if kv_cache is not None and torch.is_grad_enabled():
            raise RuntimeError("Cached decoding is inference-only: use torch.inference_mode()")
        b, t, _ = x.shape
        q = self.w_q(x).view(b,t,self.num_q_heads,self.head_dim).transpose(1,2)
        k = self.w_k(x).view(b,t,self.num_kv_heads,self.head_dim).transpose(1,2)
        v = self.w_v(x).view(b,t,self.num_kv_heads,self.head_dim).transpose(1,2)
        if kv_cache is not None:
            k, v = kv_cache.update(k,v,start_pos)
        n = k.shape[2]
        g = self.num_queries_per_kv
        q = q.reshape(b,self.num_kv_heads,g,t,self.head_dim)
        k = k.unsqueeze(2).expand(-1,-1,g,-1,-1)
        v = v.unsqueeze(2).expand(-1,-1,g,-1,-1)
        scores = torch.matmul(q,k.transpose(-2,-1))*self.scale
        # Offset-aware masking also handles cached multi-token chunks correctly.
        if t > 1:
            allowed = torch.arange(n,device=x.device)[None,:] <= (start_pos+torch.arange(t,device=x.device))[:,None]
            scores = scores.masked_fill(~allowed,float('-inf'))
        weights = torch.softmax(scores.float(),dim=-1).to(x.dtype)
        out = torch.matmul(weights,v).reshape(b,self.num_q_heads,t,self.head_dim)
        return self.w_o(out.transpose(1,2).contiguous().view(b,t,self.d_model))


def verify_correctness():
    torch.manual_seed(42)
    checks = []
    with torch.inference_mode():
        for heads in (4,2,1):
            layer = GQAAttention(32,4,heads).eval()
            x = torch.randn(2,7,32)
            full = layer(x)
            cache = KVCache(2,7,heads,8)
            decoded = torch.cat([layer(x[:,i:i+1],i,cache) for i in range(7)],dim=1)
            torch.testing.assert_close(full,decoded,rtol=1e-4,atol=1e-5)
            cache.reset()
            chunked = torch.cat([layer(x[:,:3],0,cache),layer(x[:,3:],3,cache)],dim=1)
            torch.testing.assert_close(full,chunked,rtol=1e-4,atol=1e-5)
            changed = x.clone(); changed[:,4:] += 100
            torch.testing.assert_close(full[:,:4],layer(changed)[:,:4],rtol=1e-4,atol=1e-5)
            # Independent repeated-head reference for grouping and scaling.
            q=layer.w_q(x).view(2,7,4,8).transpose(1,2)
            k=layer.w_k(x).view(2,7,heads,8).transpose(1,2).repeat_interleave(4//heads,dim=1)
            v=layer.w_v(x).view(2,7,heads,8).transpose(1,2).repeat_interleave(4//heads,dim=1)
            scores=(q@k.transpose(-2,-1))/math.sqrt(8)
            scores.masked_fill_(torch.ones(7,7,dtype=torch.bool).triu(1),float('-inf'))
            ref=layer.w_o((scores.softmax(-1)@v).transpose(1,2).reshape(2,7,32))
            torch.testing.assert_close(full,ref,rtol=1e-4,atol=1e-5)
            checks.append(f'Q:KV=4:{heads}: reference, token/chunk cache equivalence, causal isolation PASS')
        cache=KVCache(1,2,1,4)
        k=torch.randn(1,1,1,4); v=torch.randn_like(k)
        cache.update(k,v,0)
        torch.testing.assert_close(cache.k_cache[:,:,:1],k)
        assert cache.used_memory_mib()==2*4*4/2**20
        for position in (0,2):
            try: cache.update(k,v,position)
            except ValueError: pass
            else: raise AssertionError('Invalid position accepted')
        cache.update(k,v,1)
        try: cache.update(k,v,2)
        except ValueError: pass
        else: raise AssertionError('Overflow accepted')
        cache.reset(); cache.update(k,v,0)
        try: cache.update(k.double(),v.double(),1)
        except ValueError: pass
        else: raise AssertionError('Wrong dtype accepted')
        checks.append('Cache append, storage, reset, bounds and dtype checks PASS')
    return checks


def synchronise(device):
    if device.type=='cuda': torch.cuda.synchronize(device)
    elif device.type=='mps': torch.mps.synchronize()


def run_kv_cache_benchmark(args):
    device=torch.device(args.device)
    dtype=getattr(torch,args.dtype)
    element_size=torch.empty((),dtype=dtype).element_size()
    rows=[]
    for n in args.lengths:
        for name,h in [('MHA',32),('GQA',8),('MQA',1)]:
            size=2*args.batch_size*h*n*args.head_dim*element_size
            # One read of past KV plus writes of new KV; excludes weights,
            # activations, allocator overhead and implementation-specific re-reads.
            traffic=(size+2*args.batch_size*h*args.head_dim*element_size)*50/1e9
            row=dict(configuration=name,query_heads=32,kv_heads=h,context_tokens=n,
                     cache_capacity_mib=size/2**20,estimated_kv_traffic_gb_s_at_50_tps=traffic,
                     latency_median_ms=None,latency_min_ms=None,status='not measured')
            if size/2**20 > args.max_cache_mib:
                row['status']='skipped: cache exceeds configured allocation limit'
            else:
                layer=cache=x=None
                try:
                    layer=GQAAttention(32*args.head_dim,32,h).to(device=device,dtype=dtype).eval()
                    cache=KVCache(args.batch_size,n,h,args.head_dim,device,dtype)
                    with torch.inference_mode():
                        # Synthetic projected prefix: prefill is deliberately NOT timed.
                        cache.k_cache.normal_(); cache.v_cache.normal_()
                        cache.batch_size=args.batch_size
                        x=torch.randn(args.batch_size,1,32*args.head_dim,device=device,dtype=dtype)
                        samples=[]
                        for i in range(args.warmup+args.repeats):
                            # Repeat one-token decoding at a fixed total context N.
                            cache.seq_len=n-1
                            synchronise(device); start=time.perf_counter()
                            out=layer(x,n-1,cache)
                            synchronise(device); elapsed=(time.perf_counter()-start)*1000
                            if not torch.isfinite(out).all(): raise RuntimeError('Nonfinite output')
                            if i>=args.warmup: samples.append(elapsed)
                        row['latency_median_ms']=statistics.median(samples)
                        row['latency_min_ms']=min(samples)
                        row['status']='measured'
                except (RuntimeError,MemoryError) as exc:
                    row['status']='measurement failed: '+str(exc).splitlines()[0]
                finally:
                    del layer,cache,x
                    if device.type=='cuda': torch.cuda.empty_cache()
                    elif device.type=='mps': torch.mps.empty_cache()
            rows.append(row)
            latency='N/A' if row['latency_median_ms'] is None else f"{row['latency_median_ms']:.3f}"
            print(f"{name:4} N={n:5} cache={size/2**20:8.2f} MiB traffic={traffic:7.3f} GB/s median={latency:>9} ms  {row['status']}",flush=True)
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device',choices=['cpu','mps','cuda'],default='cpu')
    p.add_argument('--dtype',choices=['float16','float32','bfloat16'],default='float16')
    p.add_argument('--head-dim',type=int,default=128)
    p.add_argument('--batch-size',type=int,default=1)
    p.add_argument('--lengths',nargs='+',type=int,default=[1024,4096,16384,32768])
    p.add_argument('--warmup',type=int,default=2)
    p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--threads',type=int,default=4)
    p.add_argument('--max-cache-mib',type=float,default=1024)
    p.add_argument('--output',type=Path,default=None,help='Optional JSON output; also writes a sibling CSV')
    p.add_argument('--verify-only',action='store_true')
    args=p.parse_args()
    if min(args.head_dim,args.batch_size,args.repeats,args.threads,*args.lengths)<=0 or args.warmup<0:
        p.error('Dimensions, repeats, threads and lengths must be positive; warmup must be nonnegative')
    torch.set_num_threads(args.threads); torch.manual_seed(42)
    checks=verify_correctness()
    print('\n'.join(checks),flush=True)
    if args.verify_only: return
    metadata=dict(run_time_utc=datetime.now(timezone.utc).isoformat(),torch_version=torch.__version__,python=platform.python_version(),platform=platform.platform(),
                  processor=platform.processor(),device=args.device,dtype=args.dtype,threads=args.threads,
                  batch_size=args.batch_size,head_dim=args.head_dim,layers=1,seed=42,
                  warmup=args.warmup,repeats=args.repeats,context_definition='N includes the newly decoded token',
                  method='Single-layer projections + cache append + attention + output projection; synthetic projected prefix; no prefill or full model',
                  memory='Calculated K+V capacity only, MiB (2^20 bytes); not measured peak VRAM',
                  traffic='Estimated single KV read plus new KV writes at 50 tokens/s; decimal GB/s, not measured hardware bandwidth',
                  caveat='Grouped tensor expansion may create backend temporaries; KV storage savings do not guarantee equal latency savings')
    print(json.dumps(metadata,indent=2),flush=True)
    rows=run_kv_cache_benchmark(args)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(metadata=metadata,checks=checks,results=rows),indent=2)+'\n')
        with args.output.with_suffix('.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    if any(r['status']!='measured' for r in rows):
        print('Some timings were not measured; inspect status. Estimates are not substitute timings.')
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
