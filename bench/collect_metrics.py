#!/usr/bin/env python3
"""
增强版vLLM指标采集器
采集TTFT、TPOT、queue time、inference time等关键指标
"""
import argparse
import csv
import time
import urllib.request
import json
from datetime import datetime

def parse_prometheus_metrics(text):
    """解析Prometheus格式的指标"""
    metrics = {}
    for line in text.split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split(' ')
        if len(parts) == 2:
            name, value = parts
            # 去掉标签，只保留指标名
            metric_name = name.split('{')[0]
            try:
                metrics[metric_name] = float(value)
            except ValueError:
                pass
    return metrics

def collect_vllm_metrics(metrics_url):
    """从单个vLLM后端采集指标"""
    try:
        req = urllib.request.Request(metrics_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode('utf-8')
            metrics = parse_prometheus_metrics(text)
            
            # 计算关键指标
            result = {
                'timestamp': datetime.now().isoformat(),
                'ttft_p50_ms': 0,
                'ttft_p95_ms': 0,
                'ttft_p99_ms': 0,
                'tpot_p50_ms': 0,
                'tpot_p95_ms': 0,
                'tpot_p99_ms': 0,
                'queue_time_p50_ms': 0,
                'queue_time_p95_ms': 0,
                'queue_time_p99_ms': 0,
                'e2e_latency_p50_ms': 0,
                'e2e_latency_p95_ms': 0,
                'e2e_latency_p99_ms': 0,
                'requests_total': 0,
                'requests_per_second': 0,
            }
            
            # 提取TTFT
            ttft_sum = metrics.get('vllm:time_to_first_token_seconds_sum', 0)
            ttft_count = metrics.get('vllm:time_to_first_token_seconds_count', 0)
            if ttft_count > 0:
                result['ttft_avg_ms'] = (ttft_sum / ttft_count) * 1000
                result['requests_total'] = ttft_count
            
            # 提取TPOT (inter-token latency)
            tpot_sum = metrics.get('vllm:inter_token_latency_seconds_sum', 0)
            tpot_count = metrics.get('vllm:inter_token_latency_seconds_count', 0)
            if tpot_count > 0:
                result['tpot_avg_ms'] = (tpot_sum / tpot_count) * 1000
            
            # 提取queue time
            queue_sum = metrics.get('vllm:request_queue_time_seconds_sum', 0)
            queue_count = metrics.get('vllm:request_queue_time_seconds_count', 0)
            if queue_count > 0:
                result['queue_time_avg_ms'] = (queue_sum / queue_count) * 1000
            
            # 提取e2e latency
            e2e_sum = metrics.get('vllm:e2e_request_latency_seconds_sum', 0)
            e2e_count = metrics.get('vllm:e2e_request_latency_seconds_count', 0)
            if e2e_count > 0:
                result['e2e_latency_avg_ms'] = (e2e_sum / e2e_count) * 1000
            
            return result
    except Exception as e:
        return {'error': str(e)}

def collect_router_state(admin_url):
    """从router采集状态"""
    try:
        req = urllib.request.Request(f"{admin_url}/admin/state")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict):
                return data
            return {'error': 'Invalid response format'}
    except Exception as e:
        return {'error': str(e)}

def main():
    parser = argparse.ArgumentParser(description='增强版指标采集器')
    parser.add_argument('--vllm-urls', required=True, help='vLLM指标URL，逗号分隔')
    parser.add_argument('--admin-url', default='http://127.0.0.1:8181', help='Router管理URL')
    parser.add_argument('--output', required=True, help='输出CSV文件')
    parser.add_argument('--interval', type=float, default=1.0, help='采集间隔(秒)')
    parser.add_argument('--duration', type=float, default=60, help='采集时长(秒)')
    args = parser.parse_args()
    
    vllm_urls = args.vllm_urls.split(',')
    
    with open(args.output, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'timestamp',
            'backend_id',
            'requests_total',
            'ttft_avg_ms',
            'tpot_avg_ms',
            'queue_time_avg_ms',
            'e2e_latency_avg_ms',
            'router_phase',
            'router_capacity',
            'router_effective_weight',
            'router_desired_weight',
            'router_inflight'
        ])
        
        start_time = time.time()
        while time.time() - start_time < args.duration:
            # 采集router状态
            router_state = collect_router_state(args.admin_url)
            
            # 采集每个vLLM后端指标
            for i, url in enumerate(vllm_urls):
                backend_id = f"backend-{i}"
                metrics = collect_vllm_metrics(url)
                
                if 'error' not in metrics:
                    # 从router状态中提取对应后端信息
                    router_info = {}
                    if 'pools' in router_state:
                        for pool in router_state['pools']:
                            for backend in pool.get('backends', []):
                                if backend.get('url', '').rstrip('/') == url.rstrip('/'):
                                    router_info = {
                                        'phase': backend.get('phase', ''),
                                        'capacity': backend.get('capacity', 0),
                                        'effective_weight': backend.get('effective_weight', 0),
                                        'desired_weight': backend.get('desired_weight', 0),
                                        'inflight': backend.get('inflight', 0),
                                    }
                    
                    writer.writerow([
                        metrics.get('timestamp', ''),
                        backend_id,
                        metrics.get('requests_total', 0),
                        metrics.get('ttft_avg_ms', 0),
                        metrics.get('tpot_avg_ms', 0),
                        metrics.get('queue_time_avg_ms', 0),
                        metrics.get('e2e_latency_avg_ms', 0),
                        router_info.get('phase', ''),
                        router_info.get('capacity', 0),
                        router_info.get('effective_weight', 0),
                        router_info.get('desired_weight', 0),
                        router_info.get('inflight', 0),
                    ])
            
            time.sleep(args.interval)
    
    print(f"指标已保存到 {args.output}")

if __name__ == '__main__':
    main()