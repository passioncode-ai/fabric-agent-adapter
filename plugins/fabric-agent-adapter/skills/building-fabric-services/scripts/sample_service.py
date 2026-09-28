#!/usr/bin/env python3
"""A complete, minimal fabric-service/0.1 service built on fabric_service.py.

It is the worked example the skill points at, the target check_service.py tests
itself against, and the fixture Fabric Dashboards runs its end-to-end tests on.

  sample_service.py serve --port 47190 --data-dir DIR [--id sample] [--instance default]
  sample_service.py register --port 47190 --data-dir DIR [--services-dir DIR]
"""

from __future__ import annotations

import argparse
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import sys
import threading
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as fs  # noqa: E402

VERSION = "0.1.0"
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{name}</title>
<style>body{{font:15px system-ui;margin:2rem;color:#e9e4ec;background:#0a070d}}li{{margin:.3rem 0}}</style>
</head><body><h1>{name}</h1><p>Status: {status}</p><ul>{rows}</ul></body></html>"""


class Service:
    def __init__(self, args: argparse.Namespace):
        self.id = args.id
        self.instance = args.instance
        self.name = args.name
        self.port = args.port
        self.data = Path(args.data_dir)
        self.token_file = Path(args.token_file) if args.token_file else self.data / "service.token"
        self.degraded = [{"source": "demo", "reason": args.degraded}] if args.degraded else []
        self.started_at = fs.now_iso()
        self.build = {"commit": os.environ.get("FABRIC_BUILD_COMMIT", "0000000"), "builtAt": self.started_at}

    def start(self) -> None:
        # Rule: the lock comes before ANY side effect, including creating the token.
        self.lock = fs.hold_single_instance(self.data)
        self.token = fs.ensure_token(self.token_file)
        self.log = fs.JsonlEventLog(self.data / "events.jsonl")
        self.codes = fs.LoginCodes(self.data / "auth")
        self.log.append("service.started", "info", "%s started on build %s." % (self.name, self.build["commit"]))

    def well_known(self) -> Dict[str, Any]:
        return fs.build_well_known(
            service_id=self.id, instance=self.instance, name=self.name, version=VERSION, build=self.build,
            started_at=self.started_at, status="ready", degraded=self.degraded,
            summary=[{"label": "Events", "value": len(self.log.fetch(None, fs.EVENTS_MAX_LIMIT))}],
            surfaces={"dashboard": {"path": "/", "login": True}, "events": {"path": "/fabric/v1/events"}},
        )


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fabric-sample/" + VERSION

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
            return

        def _send(self, status: int, body: Any = None, headers: Optional[Dict[str, str]] = None,
                  content_type: str = "application/json") -> None:
            payload = b""
            if body is not None:
                payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'")
            if body is not None:
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if payload:
                self.wfile.write(payload)

        def _guard(self) -> bool:
            reason = fs.check_request(svc.port, self.headers.get("Host"), self.headers.get("Origin"),
                                      self.headers.get("Sec-Fetch-Site"))
            if reason:
                self._send(403, {"error": reason})
                return False
            return True

        def _token_ok(self) -> bool:
            if fs.token_matches(self.headers.get("Authorization"), svc.token):
                return True
            self._send(401, {"error": "The service token is required."}, {"WWW-Authenticate": "Bearer"})
            return False

        def _session_ok(self) -> bool:
            return svc.codes.session_valid(fs.cookie_value(self.headers.get("Cookie")))

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard():
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/.well-known/fabric-service":
                return self._send(200, svc.well_known())
            if url.path == "/fabric/v1/events":
                if not self._token_ok():
                    return
                try:
                    limit = fs.parse_limit((query.get("limit") or [None])[0])
                    page = fs.events_page(svc.log.fetch, (query.get("after") or [None])[0], limit)
                except fs.ServiceError as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, page)
            if url.path == "/fabric/v1/login":
                cookie = svc.codes.redeem((query.get("code") or [None])[0])
                if not cookie:
                    return self._send(403, "This sign-in link was already used or has expired.", content_type="text/plain")
                return self._send(302, None, {"Location": "/", "Set-Cookie": fs.session_cookie_header(cookie)})
            if url.path == "/":
                if not self._session_ok():
                    return self._send(401, "Open this dashboard from Fabric Dashboards.", content_type="text/plain")
                rows = "".join("<li>%s — %s</li>" % (html.escape(e["at"]), html.escape(e["text"]))
                               for e in reversed(svc.log.fetch(None, 20)))
                return self._send(200, PAGE.format(name=html.escape(svc.name), status="ready", rows=rows),
                                  content_type="text/html; charset=utf-8")
            self._send(404, {"error": "Not found."})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            url = urlparse(self.path)
            if url.path == "/fabric/v1/login-code":
                if not self._token_ok():
                    return
                return self._send(200, svc.codes.issue())
            if url.path == "/api/emit":
                if not (self._session_ok() or fs.token_matches(self.headers.get("Authorization"), svc.token)):
                    return self._send(401, {"error": "Sign in first."})
                if self.headers.get("X-Fabric-Request") != "1":
                    return self._send(403, {"error": "Missing request header."})
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                body = json.loads(self.rfile.read(length) or b"{}")
                event = svc.log.append(body.get("kind", "demo.note"), body.get("level", "info"),
                                       body.get("text", "A note from the sample service."),
                                       notify=bool(body.get("notify")), link=body.get("link"))
                return self._send(200, event)
            self._send(404, {"error": "Not found."})

    return Handler


def serve(args: argparse.Namespace) -> int:
    svc = Service(args)
    svc.start()
    server = ThreadingHTTPServer(("127.0.0.1", svc.port), make_handler(svc))
    server.daemon_threads = True

    def stop(signum: int, _frame: Any) -> None:
        svc.log.append("service.stopping", "info", "%s is stopping." % svc.name)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        svc.lock.release()
    return 0


def register(args: argparse.Namespace) -> int:
    data = Path(args.data_dir)
    descriptor = {
        "protocol": fs.PROTOCOL, "id": args.id, "instance": args.instance, "name": args.name,
        "summary": "Sample fabric-service/0.1 service.",
        "origin": "http://127.0.0.1:%d" % args.port,
        "auth": {"tokenFile": str(Path(args.token_file) if args.token_file else data / "service.token")},
        "lifecycle": {"manager": "launchd", "label": args.label, "plist": args.plist} if args.label
        else {"manager": "none"},
        "paths": {"data": str(data), "logs": []},
        "installedAt": fs.now_iso(), "installedBy": "sample_service.py register",
    }
    try:
        path = fs.write_descriptor(descriptor, Path(args.services_dir) if args.services_dir else None)
    except fs.ServiceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(path)
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "register"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, required=True)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--token-file")
        p.add_argument("--id", default="sample")
        p.add_argument("--instance", default="default")
        p.add_argument("--name", default="Sample Service")
        if name == "serve":
            p.add_argument("--degraded", help="report one degraded source with this reason")
        else:
            p.add_argument("--services-dir")
            p.add_argument("--label")
            p.add_argument("--plist")
    args = parser.parse_args(argv)
    return serve(args) if args.command == "serve" else register(args)


if __name__ == "__main__":
    raise SystemExit(main())
