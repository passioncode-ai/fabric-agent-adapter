#!/usr/bin/env python3
"""Live conformance probe for a fabric-service/0.1 service.

  check_service.py <id>[.<instance>]          # find the descriptor in the services directory
  check_service.py --descriptor PATH
  options: --services-dir DIR  --json  --skip-login
           --ca-file PEM  --connect HOST:PORT     (remote placement: trust a test CA; dial another address)
           --board-kit PATH                       (board.responder: the service's own fabric_board.py or fabric-board.mjs)
           --repo PATH                            (dashboard.opens-in-host: the service's checkout)

A remote placement (DEC-0019 — an online agent or dashboard at an https origin) is probed over
TLS with the certificate verified: the well-known document must refuse a request without the
token (401 with none of the service's data: an empty body, or an identity proxy's page, DEC-0109), the guards must refuse a foreign Host/Origin and cross-site requests,
and the session cookie must be __Host- and Secure. Loopback, launchd, lock and state rules do
not apply to it and are reported NOT_RUN with that reason.

Every rule gets PASS, FAIL or NOT_RUN with its evidence. Exit 0 when nothing
FAILs, 1 when something does, 2 on a usage error. The probe only reads, except
that it redeems one login code it asked for itself (that creates one session).

The interop.* rules (fabric-interop/0.1) read the manifest the descriptor names and
the service's MCP surface: tools/list, and fabric.job.get for an id that does not
exist. They never call a capability.

board.responder (fabric-project-comms/0.1, FAA-12b): a service that lists a fabric-project-comms revision in its
well-known `protocols` declares that it answers board requests. The rule checks that this kit reads that revision and
runs the kit's fixture conversation (`fabric_board.self_check`, or `selfCheck` of a Node copy given with --board-kit):
the whole conversation, a fenced accept and a board session without an epoch, with no Fabric. A live board is never
touched; that smoke needs a disposable Fabric and is reported separately.

Actions (fabric-actions/0.1, DEC-0121): `well-known.actions` holds a declared extensions/actions/0.1 to FAC-SEM-142,
`interop.action-tools` fails a declared action whose tool tools/list does not serve (and a local service that declares
actions with no MCP surface; a remote one there is NOT_RUN, its twin may be on A2A), and `dashboard.actions-declared`
is NOT_RUN, never FAIL, for a dashboard that declares none (a read-only dashboard cannot declare an empty list).

dashboard.opens-in-host (FAA-118, the operator rule of 2026-10-24): the service's checkout (--repo, else the one of
the descriptor's source.repository that holds its commands, manifest or launchd job) opens the service's pages only
through Fabric Dashboards. Tracked text files only, within a time budget; a browser opener aimed at its pages outside
the confirmed not_installed fallback is a FAIL (the matcher: check_service_rules.py, "dashboard.opens-in-host").
"""

from __future__ import annotations

import argparse
import email.utils
import errno
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import stat
import subprocess
import sys
import socket
import ssl
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as fs  # noqa: E402
import fabric_connections as fcn  # noqa: E402
import fabric_interop as fi  # noqa: E402

Result = Dict[str, str]


from check_service_rules import PLATFORM_HOST_REFUSALS  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import plist_problems  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import marker_problem  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import priority_problems  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import guard_verdict, no_token_verdict  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import board_responder_verdict  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import session_lifetime_problem  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import _semver  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import usage_problems  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import same_repository  # noqa: E402,F401 - moved (FAA-65)
from check_service_rules import merge_headers, session_cookie  # noqa: E402,F401 - FAA-115
from check_service_rules import well_known_actions_verdict, action_tools_verdict, actions_declared_verdict  # noqa: E402 - DEC-0121
from check_service_rules import opens_in_host_verdict, service_checkout  # noqa: E402 - FAA-118
from check_service_rules import well_known_a2a_verdict, a2a_card_verdict  # noqa: E402 - DEC-0122
import fabric_a2a as fa2  # noqa: E402 - DEC-0122


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to the origin's name (SNI, certificate, Host) over a socket dialled elsewhere."""

    def __init__(self, name: str, port: int, dial: Tuple[str, int], context: ssl.SSLContext, timeout: float):
        super().__init__(name, port, context=context, timeout=timeout)
        self._dial = dial
        self._ctx = context

    def connect(self) -> None:
        raw = socket.create_connection(self._dial, timeout=self.timeout)
        self.sock = self._ctx.wrap_socket(raw, server_hostname=self.host)


class Probe:
    remote = False  # a probe built without __init__ (the tests' Probe.__new__) reads as local

    def __init__(self, descriptor_path: Path, descriptor: Dict[str, Any], services_dir: Path, skip_login: bool,
                 ca_file: Optional[str] = None, connect: Optional[str] = None, board_kit: Optional[str] = None,
                 repo: Optional[str] = None):
        self.board_kit = board_kit
        self.repo = repo
        self.remote = fs.placement_of(descriptor) == "remote"
        self.ca_file = ca_file
        self.connect = connect
        self.path = descriptor_path
        self.d = descriptor
        self.dir = services_dir
        self.skip_login = skip_login
        self.results: List[Result] = []
        self.wk: Optional[Dict[str, Any]] = None
        self.token: Optional[str] = None
        self.events: Optional[List[Dict[str, Any]]] = None
        self.sent_traceparent: Optional[str] = None
        self.netloc = ""
        if self.remote:
            parts = urllib.parse.urlsplit(str(descriptor.get("origin", "")))
            self.netloc = parts.netloc
            self.host_name = parts.hostname or ""
            self.port = (parts.port or 443) if not fs.remote_origin_problems(descriptor.get("origin")) else 0
            return
        try:
            self.port = fs.port_of(str(descriptor.get("origin", "")))
        except fs.ServiceError:
            self.port = 0

    def add(self, rule: str, verdict: str, evidence: str) -> None:
        self.results.append({"rule": rule, "verdict": verdict, "evidence": evidence})

    def request(self, method: str, path: str, headers: Optional[Dict[str, str]] = None,
                body: Optional[bytes] = None) -> Tuple[int, Dict[str, str], bytes]:
        if self.remote:
            context = ssl.create_default_context(cafile=self.ca_file) if self.ca_file else ssl.create_default_context()
            if self.connect:
                host, _, port = self.connect.rpartition(":")
                conn = _PinnedHTTPS(self.host_name, self.port, (host, int(port)), context, 8)
            else:
                conn = http.client.HTTPSConnection(self.host_name, self.port, context=context, timeout=8)
            base = {"Host": self.netloc}
        else:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            base = {"Host": "127.0.0.1:%d" % self.port}
        base.update(headers or {})
        try:
            conn.request(method, path, body=body, headers=base)
            resp = conn.getresponse()
            return resp.status, merge_headers(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def auth_headers(self) -> Dict[str, str]:
        # The header and form the descriptor declares, never an assumed `Authorization: Bearer` (FAC-SEM-036).
        name, value = fs.token_header(self.d.get("auth"), self.token or "")
        return {name: value}

    # descriptor ------------------------------------------------------------
    def descriptor_rules(self) -> None:
        problems = fs.validate_descriptor(self.d)
        self.add("descriptor.valid", "FAIL" if problems else "PASS", "; ".join(problems) or str(self.path))
        if fs.WINDOWS:
            # DEC-0032: on Windows the file's ACL is its privacy.
            owner, aces = fs.windows_acl(self.path)
            info = os.lstat(self.path)
            problem = fs.windows_token_acl_problem({"isRegularFile": stat.S_ISREG(info.st_mode), "isReparsePoint": stat.S_ISLNK(info.st_mode),
                                                    "realPathInProfile": True, "ownerSid": owner, "aces": aces}, fs.windows_user_sid())
            problem = problem and problem["message"]
            self.add("descriptor.private", "FAIL" if problem else "PASS", problem or "owner-only ACL")
        else:
            mode = stat.S_IMODE(os.stat(self.path).st_mode)
            self.add("descriptor.private", "PASS" if mode & 0o077 == 0 else "FAIL", "mode %o" % mode)
        me = "%s.%s" % (self.d.get("id"), self.d.get("instance", "default"))
        clashes = []
        for path, other in fs.read_descriptors(self.dir):
            key = "%s.%s" % (other.get("id"), other.get("instance", "default"))
            if path.resolve() == self.path.resolve():
                continue
            if key == me:
                clashes.append("%s declared again in %s" % (me, path.name))
            # DEC-0069: a descriptor without an origin (an app's) claims no port, so two of them never clash.
            elif (not self.remote and "origin" in self.d and fs.placement_of(other) != "remote"
                  and other.get("origin") == self.d.get("origin")):
                clashes.append("port %d also claimed by %s" % (self.port, key))
        if self.remote:
            unique = "a remote origin claims no port here"
        elif "origin" not in self.d:
            unique = "an app's descriptor names no origin, so it claims no port (FAC-SEM-010)"
        else:
            unique = "port %d is unique" % self.port
        self.add("descriptor.port-claim", "FAIL" if clashes else "PASS", "; ".join(clashes) or unique)
        if (self.d.get("lifecycle") or {}).get("manager") == "person":
            # DEC-0069: installed, never running — a reader checks the app is still there; liveness is the app's own file.
            present = fs.app_present(self.d)
            self.add("descriptor.app-installed", "PASS" if present else "FAIL",
                     "%s is installed" % self.d["lifecycle"].get("app") if present
                     else "%s is gone: a reader treats this descriptor as stale" % self.d["lifecycle"].get("app"))

    # well-known ----------------------------------------------------------------
    def well_known_rules(self) -> None:
        protected: Dict[str, str] = {}
        if self.remote:
            try:
                status, _, body = self.request("GET", "/.well-known/fabric-service")
            except (OSError, ssl.SSLError) as exc:
                self.add("well-known.answers", "FAIL", "no TLS answer on %s: %s" % (self.d.get("origin"), exc))
                return
            no_token = (status, body)  # judged once the document names the identity values (DEC-0109)
            self.read_token()
            if not self.token:
                self.add_no_token(no_token, None)
                self.add("well-known.answers", "NOT_RUN", "no readable token to ask with")
                return
            protected = self.auth_headers()
        try:
            timings = []
            for _ in range(3):
                started = time.perf_counter()
                status, headers, body = self.request("GET", "/.well-known/fabric-service", protected)
                timings.append((time.perf_counter() - started) * 1000)
        except OSError as exc:
            if self.remote:
                self.add_no_token(no_token, None)
            self.add("well-known.answers", "FAIL", "no answer on %s: %s" % (self.d.get("origin"), exc))
            return
        if status != 200:
            if self.remote:
                self.add_no_token(no_token, None)
            self.add("well-known.answers", "FAIL", "HTTP %d" % status)
            return
        try:
            self.wk = json.loads(body)
        except ValueError:
            if self.remote:
                self.add_no_token(no_token, None)
            self.add("well-known.answers", "FAIL", "body is not JSON")
            return
        if self.remote:
            self.add_no_token(no_token, self.wk)
        self.add("well-known.answers", "PASS", "HTTP 200")
        median = sorted(timings)[1]
        if self.remote:
            self.add("well-known.fast", "PASS" if median < 8000 else "FAIL", "median %.1f ms (remote: no 100 ms budget)" % median)
        else:
            self.add("well-known.fast", "PASS" if median < 100 else "FAIL", "median %.1f ms" % median)
        wk = self.wk
        problems = []
        if wk.get("protocol") != fs.PROTOCOL:
            problems.append("protocol %r" % wk.get("protocol"))
        if "degraded" not in wk:
            problems.append("degraded missing")
        build = (wk.get("service") or {}).get("build") or {}
        if not (build.get("commit") or build.get("digest")):
            problems.append("build has neither commit nor digest")
        if wk.get("status") not in fs.STATUSES:
            problems.append("status %r" % wk.get("status"))
        if "events" not in (wk.get("surfaces") or {}):
            problems.append("surfaces.events missing")
        self.add("well-known.shape", "FAIL" if problems else "PASS", "; ".join(problems) or "protocol, build, status, degraded, surfaces")
        if "protocols" in wk:
            # DEC-0067, FAC-SEM-099: the revisions it accepts, N and N−1 per protocol, each once.
            findings = fs.protocols_findings(wk["protocols"])
            self.add("well-known.protocols", "FAIL" if findings else "PASS",
                     "; ".join("%s %s" % (f["instancePath"], f["message"]) for f in findings) or ", ".join(wk["protocols"]))
        extensions = wk.get("extensions") if isinstance(wk.get("extensions"), dict) else {}
        if fcn.CONNECTIONS_EXTENSION_KEY in extensions:
            # DEC-0096, FAC-SEM-127: what it uses, valid, each id once, no credential; a host hides an invalid list.
            view = fcn.connections_view(wk)
            failing = sum(1 for c in view["connections"] if c["failing"])
            self.add("well-known.connections", "FAIL" if view["reported"] else "PASS",
                     "; ".join(f["message"] for f in fcn.connections_rules(wk)[:5]) or
                     "%d connection(s), %d named in degraded[]" % (len(view["connections"]), failing))
        # DEC-0121, FAC-SEM-142: every button's agent twin, declared; no declaration is NOT_RUN (D10).
        self.add("well-known.actions", *well_known_actions_verdict(wk))
        # DEC-0122: where the public Agent Card is; no member is NOT_RUN.
        self.add("well-known.a2a", *well_known_a2a_verdict(wk))
        self.configuration_rule()
        svc = wk.get("service") or {}
        answered = "%s.%s" % (svc.get("id"), svc.get("instance"))
        expected = "%s.%s" % (self.d.get("id"), self.d.get("instance", "default"))
        self.add("well-known.identity", "PASS" if answered == expected else "FAIL",
                 "answers as %s" % answered + ("" if answered == expected else ", descriptor says %s" % expected))
        ready_bad = wk.get("status") == "ready" and bool(wk.get("degraded"))
        self.add("well-known.ready-means-healthy", "FAIL" if ready_bad else "PASS",
                 "status %s, %d degraded" % (wk.get("status"), len(wk.get("degraded") or [])))

    def add_no_token(self, answer: Tuple[int, bytes], wk: Any) -> None:
        """`well-known.requires-token` (DEC-0109): the no-token answer, against the identity values the descriptor
        names and, when the document was read, its build and pid."""
        status, body = answer
        sid, instance = str(self.d.get("id") or ""), str(self.d.get("instance") or "default")
        values = [sid, "%s.%s" % (sid, instance)]
        if isinstance(wk, dict):
            svc = wk.get("service") if isinstance(wk.get("service"), dict) else {}
            build = svc.get("build") if isinstance(svc.get("build"), dict) else {}
            process = wk.get("process") if isinstance(wk.get("process"), dict) else {}
            if svc.get("id"):
                values.append(str(svc["id"]))
                values.append("%s.%s" % (svc["id"], svc.get("instance") or instance))
            values += [str(build[k]) for k in ("commit", "digest") if build.get(k)]
            if isinstance(process.get("pid"), int) and not isinstance(process.get("pid"), bool):
                values.append(str(process["pid"]))
        verdict, evidence = no_token_verdict(status, body, list(dict.fromkeys(values)), self.host_name)
        self.add("well-known.requires-token", verdict, evidence)

    # network ------------------------------------------------------------------
    def network_rules(self) -> None:
        for rule, headers in (
            ("network.host-check", {"Host": "evil.example"}),
            ("network.origin-check", {"Origin": "http://evil.example"}),
            ("network.cross-site-check", {"Sec-Fetch-Site": "cross-site"}),
        ):
            try:
                sent = dict(headers)
                if self.remote:
                    sent.update(self.auth_headers())
                    if "Origin" in sent:
                        sent["Origin"] = "https://evil.example"
                status, _, body = self.request("GET", "/.well-known/fabric-service", sent)
                verdict, evidence = guard_verdict(rule, self.remote, status, body)
                self.add(rule, verdict, evidence)
            except (OSError, ssl.SSLError) as exc:
                self.add(rule, "NOT_RUN", str(exc))
        if self.remote:
            self.add("network.loopback-only", "NOT_RUN", "a remote placement is reached over https, not loopback")
            return
        if not shutil.which("lsof"):
            self.add("network.loopback-only", "NOT_RUN", "lsof is not installed")
            return
        out = subprocess.run(["lsof", "-nP", "-iTCP:%d" % self.port, "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        names = re.findall(r"TCP (\S+) \(LISTEN\)", out)
        wide = [n for n in names if not n.startswith(("127.0.0.1:", "[::1]:", "localhost:"))]
        self.add("network.loopback-only", "FAIL" if wide or not names else "PASS",
                 ", ".join(names) or "nothing listens on %d" % self.port)

    # auth, events, login ----------------------------------------------------------
    def read_token(self) -> None:
        if any(r["rule"] == "auth.token-file" for r in self.results):
            return
        token_file = str((self.d.get("auth") or {}).get("tokenFile", ""))
        try:
            self.token = fs.read_token(fs.expand(token_file))
            self.add("auth.token-file", "PASS", "%s is 0600 and owned by you" % token_file)
        except (fs.ServiceError, OSError) as exc:
            self.add("auth.token-file", "FAIL", str(exc))

    def auth_rules(self) -> None:
        self.read_token()
        events_path = ((self.wk or {}).get("surfaces") or {}).get("events", {}).get("path", "/fabric/v1/events")
        try:
            status, _, _ = self.request("GET", events_path + "?limit=1")
            self.add("events.requires-token", "PASS" if status == 401 else "FAIL", "HTTP %d without a token" % status)
        except OSError as exc:
            self.add("events.requires-token", "NOT_RUN", str(exc))
        if not self.token:
            self.add("events.page", "NOT_RUN", "no readable token")
            return
        try:
            status, _, body = self.request("GET", events_path + "?limit=5", self.auth_headers())
        except OSError as exc:
            self.add("events.page", "NOT_RUN", str(exc))
            return
        if status != 200:
            self.add("events.page", "FAIL", "HTTP %d with the token" % status)
            return
        try:
            page = json.loads(body)
            events = page["events"]
            assert "cursor" in page
        except (ValueError, KeyError, AssertionError):
            self.add("events.page", "FAIL", "not an events page")
            return
        self.events = events
        bad = []
        for e in events:
            if e.get("level") not in fs.LEVELS or not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\Z", str(e.get("kind", ""))):
                bad.append(str(e.get("id")))
            elif " " not in str(e.get("text", "")).strip():
                bad.append("%s (text is not a sentence)" % e.get("id"))
        self.add("events.page", "FAIL" if bad else "PASS",
                 ("bad events: " + ", ".join(bad)) if bad else "%d event(s), cursor %r" % (len(events), page["cursor"]))
        # DEC-0070, FAC-SEM-101: an event's data never carries a credential; the finding names the place, never the value.
        leaks = fs.feed_data_findings(page)
        if any(isinstance(e, dict) and "data" in e for e in events) or leaks:
            self.add("events.data", "FAIL" if leaks else "PASS",
                     "; ".join("%s: %s" % (f["instancePath"], f["message"]) for f in leaks) or "every event's data is free of credentials")

    def usage_rules(self) -> None:
        """DEC-0021: a declared usage report requires the token and adds up (FAC-SEM-025)."""
        usage = ((self.wk or {}).get("surfaces") or {}).get("usage")
        if not usage:
            self.add("usage.report", "NOT_RUN", "surfaces.usage not declared (optional; a service that calls paid models should offer it)")
            return
        path = str(usage.get("path", ""))
        if not path.startswith("/") or path.startswith("//"):
            self.add("usage.report", "FAIL", "surfaces.usage.path %r is not a path on the origin" % path)
            return
        try:
            status, _, _ = self.request("GET", path)
            self.add("usage.requires-token", "PASS" if status == 401 else "FAIL", "HTTP %d without a token" % status)
        except OSError as exc:
            self.add("usage.requires-token", "NOT_RUN", str(exc))
        if not self.token:
            self.add("usage.report", "NOT_RUN", "no readable token")
            return
        try:
            status, _, body = self.request("GET", path, self.auth_headers())
        except OSError as exc:
            self.add("usage.report", "NOT_RUN", str(exc))
            return
        if status != 200:
            self.add("usage.report", "FAIL", "HTTP %d with the token" % status)
            return
        try:
            report = json.loads(body)
        except ValueError:
            self.add("usage.report", "FAIL", "not JSON")
            return
        problems = usage_problems(report, str(self.d.get("id")), str(self.d.get("instance", "default")))
        days = report.get("days") if isinstance(report, dict) else None
        self.add("usage.report", "FAIL" if problems else "PASS",
                 "; ".join(problems[:5]) if problems else "%d day(s), unknown cost kept null" % len(days or []))

    # A2A (DEC-0122) ---------------------------------------------------------------
    def a2a_rules(self) -> None:
        """`a2a.card`: the public card read with no Authorization header and never the descriptor's token (D5); its
        interfaces are never called. The verdict is check_service_rules.a2a_card_verdict."""
        view = fa2.a2a_view(self.wk)
        status, body, error = 0, b"", None
        if view["valid"]:
            # Non-ASCII and control characters the schema's path admits are sent percent-encoded.
            target = urllib.parse.quote(view["path"], safe="".join(chr(c) for c in range(0x21, 0x7F)))
            try:
                status, _, body = self.request("GET", target)  # Host only: no token header is added here
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                error = str(exc) or type(exc).__name__
        header, _ = fs.token_header(self.d.get("auth"), "")
        self.add("a2a.card", *a2a_card_verdict(self.wk, status, body, remote=self.remote, origin=str(self.d.get("origin") or ""),
                                               descriptor_header=header, error=error))

    # dashboard (fabric-dashboard/0.1, DEC-0036) --------------------------------
    def dashboard_rules(self) -> None:
        wk = self.wk or {}
        if not (wk.get("surfaces") or {}).get("dashboard"):
            self.add("dashboard.declared", "NOT_RUN", "no surfaces.dashboard: nothing to declare")
            return
        extensions = wk.get("extensions") if isinstance(wk.get("extensions"), dict) else {}
        if fs.DASHBOARD_EXTENSION_KEY not in extensions:
            self.add("dashboard.declared", "NOT_RUN", "a legacy dashboard: no extensions dashboard/0.1 declaration (ED-9 SHOULD); "
                     "a host still gives it 480 px (ED-7). Build it from the dashboard kit and declare it")
            return
        value = extensions[fs.DASHBOARD_EXTENSION_KEY]
        problems = fs.dashboard_extension_problems(value)
        if problems:
            self.add("dashboard.declared", "FAIL", "; ".join(problems))
            return
        note = "minWidth %d, host floor %d" % (value["minWidth"], max(480, value["minWidth"]))
        if value.get("kit"):
            note += ", " + value["kit"]
            name, _, version = str(value["kit"]).partition("@")
            current = fs.DASHBOARD_KIT.partition("@")[2]
            if name == fs.DASHBOARD_KIT.partition("@")[0] and _semver(version) < _semver(current):
                note += " (kit %s is current: dashboard_kit.py status)" % current
        self.add("dashboard.declared", "PASS", note + "; the page itself: check_dashboard_layout.mjs")

    def dashboard_page_rules(self) -> None:
        """DEC-0121 and FAA-118: what a person can do on the dashboard, and where its pages open."""
        self.add("dashboard.actions-declared", *actions_declared_verdict(self.wk or {}))  # D10: never a FAIL for absence
        self.opens_in_host_rule()

    def opens_in_host_rule(self) -> None:
        """FAA-118: the checkout opens the service's pages only through Fabric Dashboards (decision D13)."""
        dashboard = ((self.wk or {}).get("surfaces") or {}).get("dashboard")
        if not isinstance(dashboard, dict):
            self.add("dashboard.opens-in-host", "NOT_RUN", "no surfaces.dashboard: no page to open")
            return
        checkout, why = service_checkout(self.d, self.repo)
        if checkout is None:
            self.add("dashboard.opens-in-host", "NOT_RUN", why)
            return
        self.add("dashboard.opens-in-host", *opens_in_host_verdict(checkout, 0 if self.remote else self.port,
                                                                   str(self.d.get("origin") or ""), str(dashboard.get("path") or "/")))

    def login_rules(self) -> None:
        dashboard = ((self.wk or {}).get("surfaces") or {}).get("dashboard")
        if not dashboard or not dashboard.get("login"):
            self.add("login.single-use", "NOT_RUN", "dashboard declares no login")
            return
        if self.skip_login or not self.token:
            self.add("login.single-use", "NOT_RUN", "--skip-login" if self.skip_login else "no readable token")
            return
        try:
            status, _, body = self.request("POST", "/fabric/v1/login-code", self.auth_headers())
            code = json.loads(body)
            url = code["url"]
            status1, headers1, _ = self.request("GET", url)
            status2, _, _ = self.request("GET", url)
        except (OSError, ValueError, KeyError) as exc:
            self.add("login.single-use", "FAIL", "login-code flow broke: %s" % exc)
            return
        cookie = session_cookie(headers1.get("set-cookie", ""), self.remote)
        ok = status1 in (302, 303) and "HttpOnly" in cookie and "SameSite=Strict" in cookie and status2 not in (302, 303)
        if self.remote:
            host_bound = cookie.startswith("__Host-") and "Secure" in cookie and "Path=/" in cookie and "domain=" not in cookie.lower()
            self.add("login.cookie-host-bound", "PASS" if host_bound else "FAIL",
                     "the session cookie is __Host-, Secure, Path=/, no Domain" if host_bound else "cookie: %s" % cookie.split(";", 1)[0].split("=")[0])
        self.add("login.single-use", "PASS" if ok else "FAIL",
                 "first redeem HTTP %d (%s), second HTTP %d" % (status1, "cookie ok" if "HttpOnly" in cookie else "no HttpOnly cookie", status2))
        if cookie:
            problem = session_lifetime_problem(cookie)
            self.add("login.session-lifetime", "FAIL" if problem else "PASS",
                     problem or "the session cookie lives at most 7 days (DEC-0039); the server's own bounds are not observable from here")
        else:
            self.add("login.session-lifetime", "NOT_RUN", "no session cookie was set")

    # interop (fabric-interop/0.1) ----------------------------------------------------
    # #region probe-interop — docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#what-the-probe-checks
    def mcp_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """One JSON-RPC request to the MCP surface, as a child of a fresh probe trace."""
        path = (((self.wk or {}).get("surfaces") or {}).get("mcp") or {}).get("path", "/mcp")
        self.sent_traceparent = fi.child_traceparent(None)
        body = dict(params)
        body["_meta"] = {"io.modelcontextprotocol/protocolVersion": fi.MCP_REVISION,
                         "io.modelcontextprotocol/clientCapabilities": {}, "traceparent": self.sent_traceparent}
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   **fi.mcp_request_headers(method, params)}
        headers.update(self.auth_headers())
        message = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": body}).encode()
        status, resp_headers, raw = self.request("POST", path, headers, message)
        if status != 200:
            raise OSError("HTTP %d from %s" % (status, path))
        if resp_headers.get("content-type", "").startswith("text/event-stream"):
            data = [line[5:].strip() for line in raw.decode().splitlines() if line.startswith("data:")]
            raw = (data[-1] if data else "null").encode()
        return json.loads(raw)

    def load_manifest(self) -> Tuple[Optional[Dict[str, Any]], Optional[Path], str]:
        named = self.d.get("fabricManifest")
        if not named:
            return None, None, "the descriptor names no fabricManifest"
        try:
            path = fs.expand(str(named))
            return json.loads(path.read_text(encoding="utf-8")), path, str(path)
        except (fs.ServiceError, OSError, ValueError) as exc:
            return None, None, "manifest %s does not resolve: %s" % (named, exc)

    def resolve_schema(self, manifest_path: Path, uri: str) -> Optional[Dict[str, Any]]:
        """A schema named by URI, found by its $id among the JSON files beside the manifest. Nothing is fetched."""
        for candidate in sorted(manifest_path.parent.glob("fabric/schemas/*.json")) + sorted(manifest_path.parent.glob("*.schema.json")):
            try:
                doc = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and doc.get("$id") == uri:
                return doc
        return None

    def interop_rules(self) -> None:
        manifest, manifest_path, where = self.load_manifest()
        me = "%s.%s" % (self.d.get("id"), self.d.get("instance", "default"))
        if manifest is None:
            self.add("interop.manifest-link", "NOT_RUN" if not self.d.get("fabricManifest") else "FAIL", where)
        else:
            block = ((manifest.get("provider") or {}).get("extensions") or {}).get(fs.EXTENSION_KEY) or {}
            named = block.get("descriptor")
            self.add("interop.manifest-link", "PASS" if named == me else "FAIL",
                     "%s names %s" % (where, named) if named else "%s carries no %s block naming %s" % (where, fs.EXTENSION_KEY, me))
        capabilities = [c for c in (manifest or {}).get("capabilities", []) if isinstance(c, dict)]
        names = {c.get("name") for c in capabilities}
        mcp_surface = ((self.wk or {}).get("surfaces") or {}).get("mcp")
        listed = (mcp_surface or {}).get("capabilities")
        if listed is None or manifest is None:
            self.add("interop.well-known-capabilities", "NOT_RUN", "no capability list on the MCP surface" if listed is None else where)
        else:
            extra = sorted(set(listed) - names)
            self.add("interop.well-known-capabilities", "FAIL" if extra else "PASS",
                     ("listed but not in the manifest: " + ", ".join(extra)) if extra else "%d listed, all in the manifest" % len(listed))
        auth = (mcp_surface or {}).get("auth")
        # DEC-0024 own, and DEC-0039 DL-16 delegation: the descriptor's token is not an MCP credential.
        own = bool(mcp_surface) and auth in ("own", "delegation")
        why = "DL-16, DEC-0039" if auth == "delegation" else "DEC-0024"
        self.delegation_declared_rule(mcp_surface)
        if own and self.token:
            # The MCP surface has credentials of its own and must refuse the host's token.
            try:
                self.mcp_call("tools/list", {})
                self.add("interop.mcp-own-auth", "FAIL", "surfaces.mcp.auth is %s, yet the MCP surface accepted the descriptor's token (%s)" % (auth, why))
            except OSError as exc:
                refused = any(code in str(exc) for code in ("HTTP 401", "HTTP 403"))
                self.add("interop.mcp-own-auth", "PASS" if refused else "NOT_RUN",
                         ("the MCP surface refuses the host's token (%s), as auth: %s says (%s)" % (exc, auth, why)) if refused else str(exc))
            except ValueError as exc:
                self.add("interop.mcp-own-auth", "NOT_RUN", str(exc))
        if not mcp_surface or not self.token or own:
            reason = ("no MCP surface" if not mcp_surface
                      else "surfaces.mcp.auth is %s: the MCP surface takes its callers' credentials, not the host's token (%s)" % (auth, why) if own
                      else "no readable token")
            for rule in ("interop.output-schema-object", "interop.tools-match", "interop.job-tools", "interop.unknown-job", "interop.trace-propagation"):
                self.add(rule, "NOT_RUN", reason)
            self.add("interop.action-tools", *action_tools_verdict(self.wk, None, reason, no_surface=not mcp_surface,
                                                                    remote=self.remote))
        else:
            try:
                listing = self.mcp_call("tools/list", {})
            except (OSError, ValueError) as exc:
                self.add("interop.tools-match", "FAIL", "tools/list failed: %s" % exc)
                self.add("interop.action-tools", *action_tools_verdict(self.wk, None, "tools/list failed: %s" % exc))
                listing = None
            if listing is not None:
                sent = self.sent_traceparent
                tools = {t.get("name"): t for t in (listing.get("result") or {}).get("tools", []) if isinstance(t, dict)}
                self.object_root_rule(tools)
                self.tools_match_rule(capabilities, manifest_path, tools)
                self.job_tools_rule(capabilities, tools)
                self.add("interop.action-tools", *action_tools_verdict(self.wk, tools))  # DEC-0121 AP-1: the live twin
                self.unknown_job_rule(list(tools))
                self.trace_rule(listing, sent)
        self.events_trace_rule(self.events)

    def configuration_rule(self) -> None:
        """DEC-0046: a well-known `configuration` is {slots, resolved} as the schema types it; absent is NOT_RUN."""
        if not isinstance(self.wk, dict) or "configuration" not in self.wk:
            self.add("configuration.declared", "NOT_RUN", "the service declares no runner or model configuration")
            return
        problems = fs.configuration_problems(self.wk["configuration"])
        self.add("configuration.declared", "FAIL" if problems else "PASS", "; ".join(problems) or
                 "slots %s; resolved from %s" % (", ".join(self.wk["configuration"].get("slots") or []) or "none",
                                                 (self.wk["configuration"].get("resolved") or {}).get("from", "not stated")))

    def delegation_declared_rule(self, mcp_surface: Optional[Dict[str, Any]]) -> None:
        """DL-16 (DEC-0039): a service that accepts delegation tokens names the issuer it trusts and its JWKS
        in auth.delegation; with surfaces.mcp.auth delegation that declaration is required."""
        auth = (self.wk or {}).get("auth")
        declared = auth.get("delegation") if isinstance(auth, dict) else None
        required = bool(mcp_surface) and mcp_surface.get("auth") == "delegation"
        if declared is None and not required:
            self.add("auth.delegation-declared", "NOT_RUN", "the service declares no delegation")
            return
        if not isinstance(declared, dict):
            self.add("auth.delegation-declared", "FAIL", "surfaces.mcp.auth is delegation, yet auth.delegation is missing (DL-16)")
            return
        missing = [k for k in ("issuer", "jwks") if not isinstance(declared.get(k), str) or not declared.get(k)]
        self.add("auth.delegation-declared", "FAIL" if missing else "PASS",
                 ("auth.delegation lacks %s (DL-16)" % ", ".join(missing)) if missing
                 else "auth.delegation names its issuer and JWKS (DL-16)")

    def object_root_rule(self, tools: Dict[str, Any]) -> None:
        """FAC-SEM-023 (DEC-0018): every listed tool's outputSchema, when present, has root type object —
        a client may refuse the whole tools/list otherwise, whatever the SDK in the tests accepted."""
        bad = sorted(n for n, t in tools.items() if "outputSchema" in t and (t.get("outputSchema") or {}).get("type") != "object")
        with_schema = sum(1 for t in tools.values() if "outputSchema" in t)
        self.add("interop.output-schema-object", "FAIL" if bad else "PASS",
                 ("outputSchema root is not type object: " + ", ".join(bad)) if bad else "%d outputSchemas, every root type object" % with_schema)

    def tools_match_rule(self, capabilities: List[Dict[str, Any]], manifest_path: Optional[Path], tools: Dict[str, Any]) -> None:
        """FAC-SEM-017: each mcp capability is served as the tool of its name, with its schemas and derived annotations."""
        served = [c for c in capabilities if (c.get("profile") or {}).get("kind") == "mcp"]
        if manifest_path is None or not served:
            self.add("interop.tools-match", "NOT_RUN", "no manifest with an mcp capability")
            return
        problems, unresolved = [], []
        for cap in served:
            name = cap.get("name")
            tool = tools.get(name)
            if tool is None:
                problems.append("%s is not served as a tool" % name)
                continue
            for side in ("inputSchema", "outputSchema"):
                schema = self.resolve_schema(manifest_path, str(cap.get(side)))
                if schema is None:
                    unresolved.append("%s %s" % (name, cap.get(side)))
                elif side == "outputSchema" and fi.is_job_capability(cap):
                    if tool.get(side) != fi.job_tool_output_schema(schema):
                        problems.append("%s is a job: its outputSchema must be oneOf[result envelope, job handle] around %s (DEC-0017)" % (name, cap.get(side)))
                elif tool.get(side) != schema:
                    problems.append("%s serves an %s that differs from %s" % (name, side, cap.get(side)))
            annotations = tool.get("annotations") or {}
            for hint, value in fi.expected_annotations(cap.get("effect", ""), cap.get("idempotency", "")).items():
                if annotations.get(hint) is not value:
                    problems.append("%s lacks %s (effect %s, idempotency %s)" % (name, hint, cap.get("effect"), cap.get("idempotency")))
        if problems:
            self.add("interop.tools-match", "FAIL", "; ".join(problems))
        elif unresolved:
            self.add("interop.tools-match", "NOT_RUN", "schemas not found beside the manifest: " + ", ".join(unresolved))
        else:
            self.add("interop.tools-match", "PASS", "%d capabilities served with their schemas and annotations" % len(served))

    def job_tools_rule(self, capabilities: List[Dict[str, Any]], tools: Dict[str, Any]) -> None:
        jobs = [c.get("name") for c in capabilities if ((c.get("extensions") or {}).get(fi.EXTENSION_KEY) or {}).get("job") is True]
        if not jobs:
            self.add("interop.job-tools", "NOT_RUN", "no capability declares job: true")
            return
        missing = [n for n in ("fabric.job.get", "fabric.job.cancel") if n not in tools]
        self.add("interop.job-tools", "FAIL" if missing else "PASS",
                 ("job capabilities %s, but %s not served" % (", ".join(jobs), " and ".join(missing))) if missing else "fabric.job.get and fabric.job.cancel served")

    def unknown_job_rule(self, tool_names: List[str]) -> None:
        """C3.2: an unknown id answers isError with unknown-job, never a fresh job."""
        if "fabric.job.get" not in tool_names:
            self.add("interop.unknown-job", "NOT_RUN", "fabric.job.get is not served")
            return
        probe_id = "probe-unknown-" + secrets.token_hex(6)
        try:
            answer = self.mcp_call("tools/call", {"name": "fabric.job.get", "arguments": {"id": probe_id}})
        except (OSError, ValueError) as exc:
            self.add("interop.unknown-job", "FAIL", "fabric.job.get failed: %s" % exc)
            return
        result = answer.get("result") or {}
        ok = result.get("isError") is True and "unknown-job" in json.dumps(result)
        self.add("interop.unknown-job", "PASS" if ok else "FAIL",
                 "isError with unknown-job for %s" % probe_id if ok else "an unknown id did not answer isError with unknown-job")

    def trace_rule(self, answer: Dict[str, Any], sent: Optional[str]) -> None:
        """C3.4: work runs as a child span of the caller — same trace, new span."""
        answered = fi.parse_traceparent(((answer.get("result") or {}).get("_meta") or {}).get("traceparent"))
        mine = fi.parse_traceparent(sent)
        if answered is None or mine is None:
            self.add("interop.trace-propagation", "NOT_RUN", "the answer carries no _meta.traceparent (C3.4 does not require it)")
        elif answered["trace_id"] == mine["trace_id"] and answered["span_id"] != mine["span_id"]:
            self.add("interop.trace-propagation", "PASS", "answered as a child span of trace %s" % mine["trace_id"])
        else:
            self.add("interop.trace-propagation", "FAIL", "answered with trace %s span %s to a call in trace %s span %s"
                     % (answered["trace_id"], answered["span_id"], mine["trace_id"], mine["span_id"]))

    def events_trace_rule(self, events: Optional[List[Dict[str, Any]]]) -> None:
        """C3.4 c: an event about traced work carries traceId and spanId together, well formed."""
        if events is None:
            self.add("interop.events-trace", "NOT_RUN", "no events page was read")
            return
        bad, traced = [], 0
        for e in events:
            has = ("traceId" in e, "spanId" in e)
            if has == (False, False):
                continue
            traced += 1
            if has != (True, True) or not fi.parse_traceparent("00-%s-%s-01" % (e.get("traceId"), e.get("spanId"))):
                bad.append(str(e.get("id")))
        self.add("interop.events-trace", "FAIL" if bad else "PASS",
                 ("events with a broken trace pair: " + ", ".join(bad)) if bad else "%d of %d events traced, every pair whole" % (traced, len(events)))
    # #endregion probe-interop

    # lifecycle ----------------------------------------------------------------
    def lifecycle_rules(self) -> None:
        if self.remote:
            self.add("lifecycle.platform", "NOT_RUN", "a remote placement is supervised by its platform; launchd, lock and state rules do not apply")
            return
        life = self.d.get("lifecycle") or {}
        data = fs.expand(str((self.d.get("paths") or {}).get("data", "~/")))
        inside = subprocess.run(["git", "-C", str(data), "rev-parse", "--show-toplevel"], capture_output=True, text=True) if data.is_dir() and shutil.which("git") else None
        self.state_rule(data, inside)
        self.lock_rule(data)
        if life.get("manager") != "launchd":
            self.add("lifecycle.launchd", "NOT_RUN", "lifecycle.manager is %s" % life.get("manager"))
            return
        plist_path = fs.expand(str(life.get("plist")))
        try:
            plist = plistlib.loads(plist_path.read_bytes())
        except (OSError, ValueError) as exc:
            self.add("lifecycle.plist", "FAIL", "cannot read %s: %s" % (plist_path, exc))
            return
        problems = plist_problems(plist, life.get("label"), self.token)
        self.add("lifecycle.plist", "FAIL" if problems else "PASS", "; ".join(problems) or "%s: RunAtLoad, KeepAlive, no secrets" % plist_path.name)
        marker = marker_problem(plist)
        self.add("lifecycle.supervisor-marker", "FAIL" if marker else "PASS",
                 marker or "%s: %s=launchd, so a copy that finds the lock held backs off" % (plist_path.name, fs.SUPERVISOR_ENV))
        slow = priority_problems(plist)
        self.add("lifecycle.priority", "FAIL" if slow else "PASS",
                 "; ".join(slow) + ". macOS may starve the service under load and hosts then see an outage; use ProcessType Standard"
                 if slow else "%s: scheduled as a standard process" % plist_path.name)
        if sys.platform != "darwin" or not shutil.which("launchctl"):
            self.add("lifecycle.one-copy", "NOT_RUN", "launchctl is not available")
            return
        out = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), life.get("label"))], capture_output=True, text=True)
        match = re.search(r"^\s*pid = (\d+)", out.stdout, re.MULTILINE)
        served = ((self.wk or {}).get("process") or {}).get("pid")
        if out.returncode != 0:
            self.add("lifecycle.one-copy", "FAIL", "launchd job %s is not loaded" % life.get("label"))
        elif not match:
            self.add("lifecycle.one-copy", "FAIL", "launchd job loaded but not running")
        else:
            same = int(match.group(1)) == served
            self.add("lifecycle.one-copy", "PASS" if same else "FAIL",
                     "launchd pid %s, answering pid %s" % (match.group(1), served))

    def state_rule(self, data: Path, inside: Optional[subprocess.CompletedProcess]) -> None:
        """State must not live in the service's CODE: its own checkout or a release.

        A repository that exists to version the data itself (a registry, a plan) is
        a store, not code; deleting the service's checkout does not touch it."""
        rule = "state.outside-code"
        if "/releases/" in data.as_posix():   # a Windows path's separators are backslashes
            self.add(rule, "FAIL", "%s is inside a release directory" % data)
            return
        if inside is None:
            self.add(rule, "NOT_RUN", "data directory %s missing or git absent" % data)
            return
        if inside.returncode != 0:
            self.add(rule, "PASS", "%s is not inside a repository" % data)
            return
        top = inside.stdout.strip()
        remote = subprocess.run(["git", "-C", top, "remote", "get-url", "origin"], capture_output=True, text=True)
        own = self.d.get("source")
        source = str(own.get("repository") or "") if isinstance(own, dict) else ""
        if not source:
            self.add(rule, "NOT_RUN", "data is inside repository %s and the descriptor names no source.repository to tell code from data" % top)
        elif remote.returncode == 0 and same_repository(remote.stdout.strip(), source):
            self.add(rule, "FAIL", "data lives in the service's own code checkout %s (%s)" % (top, source))
        else:
            self.add(rule, "PASS", "data is in repository %s, which is not the service's code (%s)" % (top, remote.stdout.strip() or "no remote"))

    def lock_rule(self, data: Path) -> None:
        lock = data / "service.lock"
        if not lock.exists():
            self.add("lifecycle.instance-lock", "FAIL", "%s does not exist" % lock)
            return
        if fs.WINDOWS:
            import msvcrt

            # The kit locks one byte at InstanceLock.WINDOWS_LOCK_OFFSET; try the same byte.
            fd = os.open(str(lock), os.O_RDWR | getattr(os, "O_BINARY", 0))
            try:
                os.lseek(fd, fs.InstanceLock.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    self.add("lifecycle.instance-lock", "PASS", "held by the running service")
                else:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    self.lock_free(lock)
            finally:
                os.close(fd)
            return
        try:
            import fcntl
        except ImportError:
            self.add("lifecycle.instance-lock", "NOT_RUN", "fcntl unavailable")
            return
        fd = os.open(str(lock), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            held = exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)
            self.add("lifecycle.instance-lock", "PASS" if held else "FAIL", "held by the running service" if held else str(exc))
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            self.lock_free(lock)
        finally:
            os.close(fd)

    def lock_free(self, lock: Path) -> None:
        """The file lock is free; a Node kit service holds the lock's name instead (fs.lock_name)."""
        if fs.lock_name_held(lock):
            self.add("lifecycle.instance-lock", "PASS", "held by the running service (the lock's name, %s)" % ("a named pipe" if fs.WINDOWS else "an abstract socket"))
        else:
            self.add("lifecycle.instance-lock", "FAIL", "%s exists but nobody holds it" % lock)

    def run(self) -> List[Result]:
        self.descriptor_rules()
        if "origin" not in self.d and not self.remote:
            self.add("well-known.answers", "NOT_RUN",
                     "an app's descriptor says it is installed, never that it runs; its live origin is in its own liveness file (DEC-0069)")
            return self.results
        if not self.port:
            return self.results
        self.well_known_rules()
        if self.wk is not None:
            self.network_rules()
            self.auth_rules()
            self.usage_rules()
            self.a2a_rules()
            self.dashboard_rules()
            self.dashboard_page_rules()
            self.login_rules()
            self.interop_rules()
            verdict, evidence = board_responder_verdict(self.wk, self.board_kit)
            self.add("board.responder", verdict, evidence)
        self.lifecycle_rules()
        return self.results


def locate(target: Optional[str], descriptor: Optional[str], services_dir: Path) -> Path:
    if descriptor:
        return Path(descriptor).expanduser()
    if not target:
        raise SystemExit(2)
    service_id, _, instance = target.partition(".")
    return fs.descriptor_path(service_id, instance or "default", services_dir)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="<id> or <id>.<instance>")
    parser.add_argument("--descriptor")
    parser.add_argument("--services-dir")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--ca-file", help="remote placement: trust this CA bundle instead of the system store (tests)")
    parser.add_argument("--connect", help="remote placement: dial HOST:PORT while speaking TLS to the origin's name (tests)")
    parser.add_argument("--board-kit", help="board.responder: the service's own fabric_board.py or fabric-board.mjs")
    parser.add_argument("--repo", help="dashboard.opens-in-host: the service's checkout (default: found by source.repository)")
    args = parser.parse_args(argv)
    if not args.target and not args.descriptor:
        parser.print_usage(sys.stderr)
        return 2
    services_dir = Path(args.services_dir).expanduser() if args.services_dir else fs.services_dir()
    path = locate(args.target, args.descriptor, services_dir)
    try:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("No readable descriptor at %s: %s" % (path, exc), file=sys.stderr)
        return 1
    results = Probe(path, descriptor, services_dir, args.skip_login, args.ca_file, args.connect, args.board_kit, args.repo).run()
    failed = sum(r["verdict"] == "FAIL" for r in results)
    if args.json:
        print(json.dumps({"descriptor": str(path), "results": results, "failed": failed}, indent=2))
    else:
        width = max(len(r["rule"]) for r in results)
        for r in results:
            print("%-8s %-*s  %s" % (r["verdict"], width, r["rule"], r["evidence"]))
        print("\n%d rule(s), %d FAIL, %d NOT_RUN" % (len(results), failed, sum(r["verdict"] == "NOT_RUN" for r in results)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
