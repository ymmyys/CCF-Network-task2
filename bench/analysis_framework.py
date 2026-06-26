#!/usr/bin/env python3
"""
标准化实验分析框架
统一输出格式：每个实验输出 summary CSV 和 timeseries CSV
"""
import csv, json, sys, os
from collections import defaultdict
from datetime import datetime

# ============================================================
# 工具函数
# ============================================================

def load_csv(path):
    """加载CSV文件，返回行列表"""
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def safe_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def safe_int(v, default=0):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default

# ============================================================
# 按秒聚合
# ============================================================

def per_second_aggregation(rows, backend_field='backend', ts_field='ts', latency_field='latency_ms',
                           status_field='status', error_field='error'):
    """
    按秒聚合请求数据
    返回: dict { second: { 'backends': {id: count}, 'latencies': [ms], 'errors': count, 'total': count } }
    """
    if not rows:
        return {}
    
    start_ts = safe_float(rows[0][ts_field])
    ps = defaultdict(lambda: {'backends': defaultdict(int), 'latencies': [], 'errors': 0, 'total': 0})
    
    for r in rows:
        ts = safe_float(r[ts_field])
        s = int(ts - start_ts)
        backend = r.get(backend_field, '')
        latency = safe_float(r.get(latency_field, 0))
        status = r.get(status_field, '200')
        error = r.get(error_field, '')
        
        ps[s]['backends'][backend] += 1
        ps[s]['total'] += 1
        
        if status == '200' and not error:
            ps[s]['latencies'].append(latency)
        else:
            ps[s]['errors'] += 1
    
    return ps

# ============================================================
# 计算延迟分位数
# ============================================================

def latency_percentiles(all_latencies):
    if not all_latencies:
        return {'p50': 0, 'p95': 0, 'p99': 0, 'avg': 0, 'min': 0, 'max': 0}
    s = sorted(all_latencies)
    n = len(s)
    return {
        'p50': round(s[int(n*0.5)], 2),
        'p95': round(s[int(n*0.95)], 2),
        'p99': round(s[int(n*0.99)], 2),
        'avg': round(sum(s)/n, 2),
        'min': round(s[0], 2),
        'max': round(s[-1], 2),
    }

# ============================================================
# 提取时间窗口
# ============================================================

def window_stats(ps, start_sec, end_sec, backend_id=None):
    """提取指定时间窗口的统计数据"""
    total = 0
    errors = 0
    latencies = []
    backends = defaultdict(int)
    
    for s in range(start_sec, end_sec):
        if s not in ps:
            continue
        d = ps[s]
        total += d['total']
        errors += d['errors']
        latencies.extend(d['latencies'])
        for bk, cnt in d['backends'].items():
            backends[bk] += cnt
    
    result = {
        'window': f'{start_sec}-{end_sec}s',
        'total_requests': total,
        'errors': errors,
        'error_rate': round(errors / total * 100, 4) if total > 0 else 0,
        'latency': latency_percentiles(latencies),
        'backend_shares': {},
        'qps': round(total / max(end_sec - start_sec, 1), 2),
    }
    
    for bk, cnt in backends.items():
        result['backend_shares'][bk] = {
            'count': cnt,
            'share_pct': round(cnt / total * 100, 2) if total > 0 else 0,
        }
    
    if backend_id:
        result['target_backend_count'] = backends.get(backend_id, 0)
        result['target_backend_share_pct'] = round(backends.get(backend_id, 0) / total * 100, 2) if total > 0 else 0
    
    return result

# ============================================================
# 收敛时间计算
# ============================================================

def calc_convergence_time(ps, event_second, backend_id, target_share_pct, tolerance_pct=2.0,
                          window_size=5, max_lookahead=60):
    """
    计算从event_second开始，backend_id的流量占比收敛到target_share_pct±tolerance_pct的时间
    使用window_size秒滑动窗口
    """
    for t in range(event_second, event_second + max_lookahead):
        w_start = t
        w_end = t + window_size
        total = 0
        backend_total = 0
        for s in range(w_start, min(w_end, max(ps.keys())+1)):
            if s in ps:
                total += ps[s]['total']
                backend_total += ps[s]['backends'].get(backend_id, 0)
        
        if total > 0:
            share = backend_total / total * 100
            if abs(share - target_share_pct) <= tolerance_pct:
                return t - event_second
    
    return max_lookahead  # 未收敛

# ============================================================
# 生成 timeseries CSV
# ============================================================

def generate_timeseries(ps, backend_ids, output_path):
    """生成每秒时间序列表"""
    with open(output_path, 'w', newline='') as f:
        fields = ['second']
        for bid in backend_ids:
            fields.extend([f'{bid}_count', f'{bid}_share_pct', f'{bid}_desired_weight',
                          f'{bid}_effective_weight', f'{bid}_phase', f'{bid}_healthy',
                          f'{bid}_inflight'])
        fields.extend(['p50_ms', 'p95_ms', 'p99_ms', 'error_count', 'total'])
        
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        
        for s in sorted(ps.keys()):
            d = ps[s]
            row = {'second': s}
            
            for bid in backend_ids:
                cnt = d['backends'].get(bid, 0)
                t = d['total']
                row[f'{bid}_count'] = cnt
                row[f'{bid}_share_pct'] = round(cnt/t*100, 2) if t > 0 else 0
                row[f'{bid}_desired_weight'] = ''
                row[f'{bid}_effective_weight'] = ''
                row[f'{bid}_phase'] = ''
                row[f'{bid}_healthy'] = ''
                row[f'{bid}_inflight'] = ''
            
            lats = sorted(d['latencies'])
            n = len(lats)
            row['p50_ms'] = round(lats[int(n*0.5)], 2) if n > 0 else 0
            row['p95_ms'] = round(lats[int(n*0.95)], 2) if n > 0 else 0
            row['p99_ms'] = round(lats[int(n*0.99)], 2) if n > 0 else 0
            row['error_count'] = d['errors']
            row['total'] = d['total']
            
            w.writerow(row)

# ============================================================
# 生成 summary
# ============================================================

def write_summary(summaries, output_path):
    """写入summary CSV"""
    if not summaries:
        return
    with open(output_path, 'w', newline='') as f:
        fields = list(summaries[0].keys())
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(summaries)

# ============================================================
# 主入口
# ============================================================

if __name__ == '__main__':
    print("标准分析框架已加载")
    print("可用函数: load_csv, per_second_aggregation, window_stats, ")
    print("          latency_percentiles, calc_convergence_time, ")
    print("          generate_timeseries, write_summary")
