#!/usr/bin/env python3
import argparse
import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class BackendHandler(BaseHTTPRequestHandler):
    backend_id = "backend"
    latency_ms = 50.0
    status = 200

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return

        time.sleep(self.latency_ms / 1000.0)
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Fake-Backend", self.backend_id)
        self.end_headers()
        body = {"backend": self.backend_id, "path": self.path}
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


class MetricsHandler(BaseHTTPRequestHandler):
    utilization = 35.0
    queue_depth = 0.0
    kv_cache = 0.2
    latency_ms = 50.0

    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        metrics = f"""npu_utilization_rate {self.utilization}
request_queue_depth {self.queue_depth}
kv_cache_usage_ratio {self.kv_cache}
decode_latency_ms {self.latency_ms}
"""
        self.wfile.write(metrics.encode("utf-8"))

    def log_message(self, fmt, *args):
        return


def serve(server):
    with server:
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--metrics-port", type=int, required=True)
    parser.add_argument("--id", default="backend")
    parser.add_argument("--latency-ms", type=float, default=50)
    parser.add_argument("--utilization", type=float, default=35)
    parser.add_argument("--queue-depth", type=float, default=0)
    parser.add_argument("--kv-cache", type=float, default=0.2)
    args = parser.parse_args()

    BackendHandler.backend_id = args.id
    BackendHandler.latency_ms = args.latency_ms
    MetricsHandler.utilization = args.utilization
    MetricsHandler.queue_depth = args.queue_depth
    MetricsHandler.kv_cache = args.kv_cache
    MetricsHandler.latency_ms = args.latency_ms

    backend = ThreadingHTTPServer((args.host, args.port), BackendHandler)
    metrics = ThreadingHTTPServer((args.host, args.metrics_port), MetricsHandler)

    stop = threading.Event()

    def shutdown(signum, frame):
        stop.set()
        backend.shutdown()
        metrics.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    threads = [
        threading.Thread(target=serve, args=(backend,), daemon=True),
        threading.Thread(target=serve, args=(metrics,), daemon=True),
    ]
    for thread in threads:
        thread.start()

    print(f"backend {args.id} on {args.host}:{args.port}, metrics on {args.host}:{args.metrics_port}")
    while not stop.is_set():
        time.sleep(0.2)


if __name__ == "__main__":
    main()
