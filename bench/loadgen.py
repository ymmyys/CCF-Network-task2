#!/usr/bin/env python3
import argparse
import csv
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait


def parse_header(value):
    if ":" not in value:
        raise argparse.ArgumentTypeError("header must be KEY:VALUE")
    key, val = value.split(":", 1)
    return key.strip(), val.strip()


def request_once(url, method, headers, body, timeout):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    start = time.perf_counter()
    status = 0
    backend = ""
    error = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            backend = resp.headers.get("X-Router-Backend", "")
            resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        backend = exc.headers.get("X-Router-Backend", "")
        error = str(exc)
    except Exception as exc:
        error = str(exc)
    latency_ms = (time.perf_counter() - start) * 1000
    return {
        "ts": time.time(),
        "status": status,
        "latency_ms": latency_ms,
        "backend": backend,
        "error": error,
    }


def worker(args, stop_at, rows, rows_lock):
    headers = dict(args.header)
    body = args.body.encode("utf-8") if args.body else None
    while time.time() < stop_at:
        row = request_once(args.url, args.method, headers, body, args.timeout)
        with rows_lock:
            rows.append(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--method", default="POST")
    parser.add_argument("--body", default=json.dumps({"prompt": "hello"}))
    parser.add_argument("--header", action="append", type=parse_header, default=[])
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", default="bench/results.csv")
    args = parser.parse_args()

    stop_at = time.time() + args.duration
    rows = []
    rows_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, args, stop_at, rows, rows_lock) for _ in range(args.concurrency)]
        wait(futures)

    rows.sort(key=lambda item: item["ts"])
    with open(args.output, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["ts", "status", "latency_ms", "backend", "error"])
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for row in rows if 200 <= int(row["status"]) < 500 and not row["error"])
    elapsed = max(args.duration, 0.001)
    print(f"wrote {len(rows)} rows to {args.output}; ok={ok}; qps={len(rows)/elapsed:.2f}")


if __name__ == "__main__":
    main()
