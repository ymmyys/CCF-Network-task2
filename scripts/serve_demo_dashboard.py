#!/usr/bin/env python3
"""Serve MUTT Live Console and optionally proxy a remote admin plane.

Compatible with existing MUTT admin APIs:
  GET  /admin/state
  POST /admin/capacity
  POST /admin/health
  GET  /metrics

Typical teammate usage (MUTT already running on :8181):

  python3 scripts/serve_demo_dashboard.py
  # open http://127.0.0.1:8787/

Remote Ascend box (port-forward or reachable admin URL):

  python3 scripts/serve_demo_dashboard.py --admin http://127.0.0.1:8181 --port 8787

If MUTT was rebuilt with embedded demo UI, you can skip this script and open:

  http://127.0.0.1:8181/demo/
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "internal" / "router" / "static" / "index.html"


class Handler(BaseHTTPRequestHandler):
    admin_base: str = "http://127.0.0.1:8181"
    index_path: Path = DEFAULT_INDEX

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET(body=False)

    def do_GET(self, body: bool = True) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/demo", "/demo/"):
            data = self.index_path.read_bytes()
            self._send(200, data if body else b"", "text/html; charset=utf-8")
            return
        if path.startswith("/admin/") or path in ("/metrics", "/healthz"):
            self._proxy("GET")
            return
        self._send(404, b"not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/admin/"):
            self._proxy("POST")
            return
        self._send(404, b"not found\n", "text/plain; charset=utf-8")

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        payload = self.rfile.read(length) if length > 0 else None
        target = self.admin_base.rstrip("/") + urlparse(self.path).path
        if urlparse(self.path).query:
            target += "?" + urlparse(self.path).query
        req = urllib.request.Request(target, data=payload, method=method)
        if payload is not None:
            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                self._send(resp.status, data, ctype)
        except urllib.error.HTTPError as err:
            data = err.read() if err.fp else str(err).encode()
            ctype = err.headers.get("Content-Type", "text/plain; charset=utf-8") if err.headers else "text/plain; charset=utf-8"
            self._send(err.code, data, ctype)
        except Exception as err:  # noqa: BLE001 - surface proxy errors to the UI
            body = json.dumps({"error": str(err)}, ensure_ascii=False).encode("utf-8")
            self._send(502, body, "application/json; charset=utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve MUTT Live Console")
    parser.add_argument("--admin", default=os.environ.get("MUTT_ADMIN", "http://127.0.0.1:8181"),
                        help="MUTT admin base URL (default http://127.0.0.1:8181)")
    parser.add_argument("--host", default="0.0.0.0", help="bind host")
    parser.add_argument("--port", type=int, default=8787, help="dashboard port")
    parser.add_argument("--index", default=str(DEFAULT_INDEX), help="path to index.html")
    args = parser.parse_args()

    index_path = Path(args.index)
    if not index_path.is_file():
        print(f"index.html not found: {index_path}", file=sys.stderr)
        return 1

    Handler.admin_base = args.admin.rstrip("/")
    Handler.index_path = index_path

    # Quick connectivity hint (non-fatal).
    try:
        parsed = urlparse(Handler.admin_base)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=2)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        resp.read()
        print(f"[ok] admin reachable: {Handler.admin_base}/healthz -> {resp.status}")
    except Exception as err:  # noqa: BLE001
        print(f"[warn] admin not reachable yet ({Handler.admin_base}): {err}")
        print("       start MUTT first, or use the page's Offline Demo mode")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MUTT Live Console: http://127.0.0.1:{args.port}/")
    print(f"Proxying admin API to {Handler.admin_base}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
