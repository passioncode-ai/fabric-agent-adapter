#!/usr/bin/env python3
"""The entry of a dashboard-only fabric-service/0.1 service (FAA-268), the descriptor install.py wrote.

  python3 dashboard_service.py serve --descriptor <path>

It serves the well-known document (surfaces `dashboard` and `events`, no `mcp`, no `usage`: it calls no model and
offers no capability), its events feed, the login code and the signed-in page. The page shows `<folder>/snapshot.json`,
which the person's agent writes from what it read through the Fabric Dashboards MCP (`list_services`, `spend`,
`connections`) and Project Observatory; the service holds no token but its own and calls nobody. A missing snapshot,
one that cannot be read and one older than a day are reported in `degraded`, never shown as data.

snapshot.json: {"takenAt": "<RFC 3339>", "sections": [{"title": str, "source": str, "columns": [str], "rows": [[str]]}]}
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

if str(Path(__file__).resolve().parent) not in sys.path:  # the kit installed beside it, under `python3 -I` too
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import fabric_service as fs
except ImportError:  # in the adapter's repository: the kit is two folders up
    sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))
    import fabric_service as fs

VERSION = "0.1.0"
STALE_SECONDS = 24 * 3600
MAX_SNAPSHOT_BYTES = 1048576
_HERE = Path(__file__).resolve().parent
KIT_DIR = next((d for d in (_HERE / "kit", _HERE.parents[1] / "assets" / "dashboard-kit")
                if (d / "fabric-dashboard.css").is_file()), None)
KIT_FILES = {"/kit/fabric-dashboard.css": ("fabric-dashboard.css", "text/css; charset=utf-8"),
             "/kit/fabric-dashboard.js": ("fabric-dashboard.js", "text/javascript; charset=utf-8")}
CONNECTIONS = [{"id": "snapshot", "kind": "store", "target": "snapshot.json",
                "purpose": "what the person's agent read through the Fabric Dashboards MCP and Project Observatory"}]
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{name}</title>
<link rel="stylesheet" href="/kit/fabric-dashboard.css"><script src="/kit/fabric-dashboard.js" defer></script>
</head><body><div class="fd-chrome"><header class="fd-header"><p class="fd-title">{name}</p>
<span class="fd-chip fd-s-{chip}"><span class="fd-dot"></span>Status: {status}</span></header></div>
<main class="fd-page">{body}</main></body></html>"""


def read_snapshot(path: Path, now: Optional[float] = None) -> Dict[str, Any]:
    """{"sections": [...], "takenAt": str} or {"degraded": reason}: missing, unreadable, invalid, stale."""
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return {"degraded": "too-large"}
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"degraded": "missing"}
    except (OSError, ValueError, RecursionError):
        return {"degraded": "unreadable"}
    sections = doc.get("sections") if isinstance(doc, dict) else None
    taken = doc.get("takenAt") if isinstance(doc, dict) else None
    try:
        at = _dt.datetime.fromisoformat(str(taken).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return {"degraded": "invalid"}
    if not isinstance(sections, list) or not all(isinstance(s, dict) for s in sections):
        return {"degraded": "invalid"}
    if (now if now is not None else time.time()) - at > STALE_SECONDS:
        return {"degraded": "stale", "takenAt": taken}
    return {"sections": sections, "takenAt": taken}


def _cell(value: Any) -> str:
    return html.escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))


def render_sections(snapshot: Dict[str, Any]) -> str:
    if "degraded" in snapshot:
        return ('<section><h2>No data</h2><p class="fd-hint">The snapshot is %s. Ask your agent to read the Fabric '
                'Dashboards MCP and Project Observatory and write snapshot.json.</p></section>' % html.escape(snapshot["degraded"]))
    out = ['<p class="fd-hint">Read at %s.</p>' % _cell(snapshot["takenAt"])]
    for section in snapshot["sections"]:
        columns = section.get("columns") if isinstance(section.get("columns"), list) else []
        rows = section.get("rows") if isinstance(section.get("rows"), list) else []
        head = "".join("<th>%s</th>" % _cell(c) for c in columns)
        body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _cell(c) for c in (r if isinstance(r, list) else [r]))
                       for r in rows[:500])
        out.append('<section><h2>%s</h2><p class="fd-hint">From %s.</p><table><thead><tr>%s</tr></thead><tbody>%s</tbody>'
                   "</table></section>" % (_cell(section.get("title", "")), _cell(section.get("source", "")), head, body))
    return "".join(out)


class Service:
    def __init__(self, descriptor_file: Path):
        d = json.loads(Path(descriptor_file).read_text(encoding="utf-8"))
        problems = fs.validate_descriptor(d)
        if problems:
            raise fs.ServiceError("Descriptor is invalid: %s." % "; ".join(problems))
        self.id, self.instance, self.name = d["id"], d["instance"], d["name"]
        self.port = fs.port_of(d["origin"])
        self.data = Path(d["paths"]["data"])
        self.token_file = Path(d["auth"]["tokenFile"]).expanduser()
        self.started_at = fs.now_iso()
        self.build = {"commit": os.environ.get("FABRIC_BUILD_COMMIT", "0000000"), "builtAt": self.started_at}
        self.drain = fs.Drain()

    def start(self) -> None:
        self.lock = fs.hold_single_instance(self.data)  # the lock before any side effect
        self.token = fs.ensure_token(self.token_file)
        self.log = fs.JsonlEventLog(self.data / "events.jsonl")
        self.codes = fs.LoginCodes(self.data / "auth", token=self.token)
        self.log.append("service.started", "info", "%s started on build %s." % (self.name, self.build["commit"]))

    def snapshot(self) -> Dict[str, Any]:
        return read_snapshot(self.data / "snapshot.json")

    def well_known(self) -> Dict[str, Any]:
        snap = self.snapshot()
        degraded = [{"source": "snapshot", "reason": snap["degraded"]}] if "degraded" in snap else []
        return fs.build_well_known(
            service_id=self.id, instance=self.instance, name=self.name, version=VERSION, build=self.build,
            started_at=self.started_at, status="ready", degraded=degraded,
            summary=[{"label": "Sections", "value": len(snap.get("sections") or [])}],
            surfaces={"dashboard": {"path": "/", "login": True}, "events": {"path": "/fabric/v1/events"}},
            extensions=dict(fs.dashboard_extension() if KIT_DIR is not None else {},
                            **fs.connections_extension(CONNECTIONS, degraded=degraded)))


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fabric-dashboard-only/" + VERSION

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: Any = None, headers: Optional[Dict[str, str]] = None,
                  content_type: str = "application/json") -> None:
            payload = b"" if body is None else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'self'")
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
                    return self._send(200, fs.events_page(svc.log.fetch, (query.get("after") or [None])[0], limit))
                except fs.ServiceError as exc:
                    return self._send(400, {"error": str(exc)})
            if url.path == "/fabric/v1/login":
                cookie = svc.codes.redeem((query.get("code") or [None])[0])
                if not cookie:
                    return self._send(403, "This sign-in link was already used or has expired.", content_type="text/plain")
                return self._send(302, None, {"Location": "/", "Set-Cookie": fs.session_cookie_header(cookie)})
            if url.path in KIT_FILES and KIT_DIR is not None:
                name, kind = KIT_FILES[url.path]
                return self._send(200, (KIT_DIR / name).read_text(encoding="utf-8"), content_type=kind)
            if url.path == "/":
                if not svc.codes.session_valid(fs.cookie_value(self.headers.get("Cookie"))):
                    return self._send(401, "Open this dashboard from Fabric Dashboards.", content_type="text/plain")
                snap = svc.snapshot()
                status, chip = ("degraded", "warn") if "degraded" in snap else ("ready", "ok")
                return self._send(200, PAGE.format(name=html.escape(svc.name), status=status, chip=chip,
                                                   body=render_sections(snap)), content_type="text/html; charset=utf-8")
            self._send(404, {"error": "Not found."})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            url = urlparse(self.path)
            if url.path == "/fabric/v1/login-code":
                if not self._token_ok():
                    return
                return self._send(200, svc.codes.issue())
            if url.path == "/logout":
                if self.headers.get("X-Fabric-Request") != "1":  # another site's form never signs the operator out
                    return self._send(403, {"error": "Missing request header."})
                svc.codes.logout(fs.cookie_value(self.headers.get("Cookie")))
                return self._send(204, None, {"Set-Cookie": fs.expired_session_cookie_header()})
            self._send(404, {"error": "Not found."})

    return Handler


def serve(descriptor_file: Path) -> int:
    svc = Service(descriptor_file)
    svc.start()
    server = fs.LoopbackHTTPServer(("127.0.0.1", svc.port), make_handler(svc))
    svc.drain.install(lambda drained: server.shutdown(),
                      on_stopping=lambda: svc.log.append("service.stopping", "info", "%s is stopping." % svc.name))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        svc.lock.release()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    fs.add_supervisor_argument(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve")
    fs.add_supervisor_argument(p)
    p.add_argument("--descriptor", required=True, help="the path install.py printed")
    args = parser.parse_args(argv)
    try:
        return serve(Path(args.descriptor))
    except (fs.ServiceError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
