#!/usr/bin/env python3
import argparse
import json
import time
import urllib.request


def parse_event(value):
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("event must be delay_seconds,pool,backend,capacity")
    delay, pool, backend, capacity = parts
    return float(delay), pool, backend, float(capacity)


def post_capacity(admin, pool, backend, capacity):
    url = admin.rstrip("/") + "/admin/capacity"
    body = json.dumps({"pool": pool, "backend": backend, "capacity": capacity}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = resp.read().decode("utf-8")
    print(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", default="http://127.0.0.1:8181")
    parser.add_argument("--event", action="append", type=parse_event, required=True)
    args = parser.parse_args()

    start = time.time()
    for delay, pool, backend, capacity in sorted(args.event, key=lambda item: item[0]):
        sleep_for = start + delay - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)
        print(f"set {pool}/{backend} capacity={capacity}")
        post_capacity(args.admin, pool, backend, capacity)


if __name__ == "__main__":
    main()
