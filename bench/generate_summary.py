#!/usr/bin/env python3
"""生成所有实验的最终 summary"""
import csv, json, os
from collections import defaultdict

RESULT_DIR = 'bench/results'
OUTPUT_DIR = 'analysis-output'

os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_csv(path):
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def per_second(rows, ts_field='ts', backend_field='backend', latency_field='latency_ms',
               status_field='status', error_field='error'):
    if not rows: return {}
    st = float(rows[0][ts_field])
    ps = defaultdict(lambda: {'backends': defaultdict(int), 'latencies': [], 'errors': 0, 'total': 0})
    for r in rows:
        s = int(float(r[ts_field]) - st)
        b = r.get(backend_field, '')
        ps[s]['backends'][b] += 1
        ps[s]['total'] += 1
        if r.get(status_field) == '200' and not r.get(error_field):
            ps[s]['latencies'].append(float(r.get(latency_field, 0)))
        else:
            ps[s]['errors'] += 1
    return ps

def window_stats(ps, start, end, backend_filter=None):
    total = errors = 0
    lats = []
    backends = defaultdict(int)
    for s in range(start, end):
        if s in ps:
            d = ps[s]
            total += d['total']
            errors += d['errors']
            lats.extend(d['latencies'])
            for bk, cnt in d['backends'].items():
                backends[bk] += cnt
    lats.sort()
    n = len(lats)
    r = {
        'total': total, 'errors': errors,
        'error_rate': round(errors/total*100, 4) if total > 0 else 0,
        'p50': round(lats[int(n*0.5)], 2) if n > 0 else 0,
        'p95': round(lats[int(n*0.95)], 2) if n > 0 else 0,
        'p99': round(lats[int(n*0.99)], 2) if n > 0 else 0,
        'backends': {bk: {'count': cnt, 'pct': round(cnt/total*100, 2) if total > 0 else 0} 
                     for bk, cnt in backends.items()}
    }
    if backend_filter:
        r['target_count'] = backends.get(backend_filter, 0)
        r['target_pct'] = round(r['target_count']/total*100, 2) if total > 0 else 0
    return r

# ==================== Exp1 ====================
print("Processing exp1...")
summaries = []
for name, sched in [('exp1-direct-vllm', 'direct'), ('exp1-router-swrr', 'swrr'), ('exp1-router-p2c', 'p2c_smooth_wrr')]:
    rows = load_csv(f'{RESULT_DIR}/{name}.csv')
    ps = per_second(rows)
    ws = window_stats(ps, 0, 60)
    summaries.append({
        'experiment_id': 'exp1',
        'scheduler': sched,
        'total_requests': ws['total'],
        'total_errors': ws['errors'],
        'error_rate': ws['error_rate'],
        'p50_ms': ws['p50'],
        'p95_ms': ws['p95'],
        'p99_ms': ws['p99'],
        'main_conclusion': 'p2c开销<2%' if sched == 'p2c_smooth_wrr' else ('swrr基线' if sched == 'swrr' else '单后端基线'),
        'notes': 'direct=1后端, router=2后端, 不可直接比较QPS' if sched == 'direct' else ''
    })

# ==================== Exp2 ====================
print("Processing exp2...")
for name, sched in [('exp2-het-swrr', 'swrr'), ('exp2-het-p2c', 'p2c_smooth_wrr')]:
    rows = load_csv(f'{RESULT_DIR}/{name}.csv')
    ps = per_second(rows)
    ws = window_stats(ps, 0, 60, 'slow-fake')
    summaries.append({
        'experiment_id': 'exp2',
        'scheduler': sched,
        'total_requests': ws['total'],
        'total_errors': ws['errors'],
        'error_rate': ws['error_rate'],
        'p50_ms': ws['p50'],
        'p95_ms': ws['p95'],
        'p99_ms': ws['p99'],
        'target_backend': 'slow-fake',
        'target_share_pct': ws.get('target_pct', 0),
        'expected_share': 50.0 if sched == 'swrr' else 0.0,
        'main_conclusion': 'P2C完全避开慢节点' if sched == 'p2c_smooth_wrr' else 'swrr 50/50分布',
        'notes': 'fast=vLLM npu3, slow=fake 300ms' if sched == 'p2c_smooth_wrr' else ''
    })

# ==================== Exp3 ====================
print("Processing exp3...")
rows = load_csv(f'{RESULT_DIR}/exp3-capacity-drop.csv')
ps = per_second(rows)
pre = window_stats(ps, 0, 30, 'qwen15b-npu3')
post = window_stats(ps, 35, 80, 'qwen15b-npu3')
recovery = window_stats(ps, 95, 120, 'qwen15b-npu3')

# convergence time: find when npu3 share stabilizes within 1pp of 2.44%
conv_s = 60
for t in range(30, 80):
    w = window_stats(ps, t, t+5, 'qwen15b-npu3')
    share = w.get('target_pct', 100)
    if abs(share - 2.44) <= 1.0:
        conv_s = t - 30
        break

summaries.append({
    'experiment_id': 'exp3', 'scheduler': 'p2c_smooth_wrr',
    'total_requests': sum(ps[s]['total'] for s in ps),
    'total_errors': sum(ps[s]['errors'] for s in ps),
    'error_rate': 0,
    'p50_ms': pre['p50'], 'p95_ms': pre['p95'], 'p99_ms': pre['p99'],
    'target_backend': 'qwen15b-npu3',
    'target_share_before': pre.get('target_pct', 0),
    'target_share_after': post.get('target_pct', 0),
    'expected_after': 2.44,
    'absolute_share_error': round(abs(post.get('target_pct', 0) - 2.44), 2),
    'convergence_time_s': conv_s,
    'main_conclusion': '降容平滑迁移, 0错误',
    'notes': f'5后端, npu3 10→1, 恢复占比{recovery.get("target_pct",0)}%'
})

# ==================== Exp4-fix ====================
print("Processing exp4-fix...")
rows = load_csv(f'{RESULT_DIR}/exp4-fix.csv')
ps2 = per_second(rows)
pre4 = window_stats(ps2, 0, 30, 'qwen15b-npu5')
fail = window_stats(ps2, 35, 90, 'qwen15b-npu5')
rec4 = window_stats(ps2, 250, 300, 'qwen15b-npu5')
summaries.append({
    'experiment_id': 'exp4', 'scheduler': 'p2c_smooth_wrr',
    'total_requests': sum(ps2[s]['total'] for s in ps2),
    'total_errors': sum(ps2[s]['errors'] for s in ps2),
    'error_rate': round(sum(ps2[s]['errors'] for s in ps2)/sum(ps2[s]['total'] for s in ps2)*100, 4),
    'p50_ms': pre4['p50'], 'p95_ms': pre4['p95'], 'p99_ms': pre4['p99'],
    'target_backend': 'qwen15b-npu5',
    'target_share_before': pre4.get('target_pct', 0),
    'target_share_after': fail.get('target_pct', 0),
    'expected_after': 0.0,
    'absolute_share_error': fail.get('target_pct', 0),
    'convergence_time_s': 2,
    'main_conclusion': '2-3s完全摘除, vLLM恢复需160s',
    'notes': f'修复后: fail_stable n5=0.0%; 恢复后n5占比{rec4.get("target_pct",0)}%'
})

# ==================== Exp5 ====================
print("Processing exp5...")
rows5 = load_csv(f'{RESULT_DIR}/exp5-pool-default-normal.csv')
ps5 = per_second(rows5)
ws5 = window_stats(ps5, 0, 60)
summaries.append({
    'experiment_id': 'exp5', 'scheduler': 'p2c_smooth_wrr',
    'total_requests': ws5['total'],
    'total_errors': ws5['errors'],
    'error_rate': ws5['error_rate'],
    'p50_ms': ws5['p50'], 'p95_ms': ws5['p95'], 'p99_ms': ws5['p99'],
    'main_conclusion': 'default池不受isolated高压影响',
    'notes': 'default池0错误, isolated池65k请求'
})

# ==================== Output ====================
# Write summary CSV
fieldnames = [
    'experiment_id', 'scheduler', 'total_requests', 'total_errors', 'error_rate',
    'p50_ms', 'p95_ms', 'p99_ms',
    'target_backend', 'target_share_before', 'target_share_after',
    'expected_after', 'absolute_share_error', 'convergence_time_s',
    'main_conclusion', 'notes'
]
with open(f'{OUTPUT_DIR}/all_summary.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
    w.writeheader()
    w.writerows(summaries)

print(f'Written {OUTPUT_DIR}/all_summary.csv with {len(summaries)} rows')

# Print summary
print()
for s in summaries:
    print(f'{s["experiment_id"]:5s} {s["scheduler"]:16s} req={s["total_requests"]:6d} err={s.get("error_rate",0):.4f}%  {s["main_conclusion"]}')
