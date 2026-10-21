"""The probe's rules that read one thing and need no running service (FAA-65): a plist's marker and priority, the
network guard's verdict, the board responder's fixture conversation, a session cookie's lifetime, a usage report, and
whether two repository URLs name one repository. ``check_service.py`` runs them against a live service.
Standard library only, Python 3.9+."""
from __future__ import annotations

import email.utils
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as fs  # noqa: E402 - beside this file


def plist_problems(plist: dict, label: object, token: object = None) -> list:
    """What makes a service's launchd job unfit to stay up: identity, restart, secrets."""
    problems = []
    if plist.get("Label") != label:
        problems.append("Label %r" % plist.get("Label"))
    if plist.get("RunAtLoad") is not True:
        problems.append("RunAtLoad is not true")
    if plist.get("KeepAlive") is not True:
        problems.append("KeepAlive is %r, not true" % plist.get("KeepAlive"))
    for key, value in (plist.get("EnvironmentVariables") or {}).items():
        if re.search(r"(TOKEN|SECRET|PASSWORD|KEY)$", key) and not key.endswith("_FILE"):
            problems.append("secret-like variable %s in the plist" % key)
        if token and token in str(value):
            problems.append("the service token itself is in the plist")
    return problems


def marker_problem(plist: dict) -> Optional[str]:
    """What is wrong with the job's supervisor marker (DEC-0057; FAA-05), read the way the copy it starts reads it.

    Without ``FABRIC_SERVICE_SUPERVISOR=launchd`` (or ``--fabric-supervisor launchd``) a copy that finds the
    lock held exits 75 at once, and KeepAlive starts it again every ThrottleInterval."""
    env = plist.get("EnvironmentVariables")
    env = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    argv = plist.get("ProgramArguments")
    argv = [str(a) for a in argv] if isinstance(argv, list) else []
    marker = fs.supervisor_marker(env, argv)
    if marker["kind"] == "supervised" and marker["manager"] == "launchd":
        return None
    fix = ("a copy that finds the lock held exits 75 at once and KeepAlive respawns it every ThrottleInterval; "
           "regenerate the plist with launchd_plist / launchdPlist and reinstall")
    if marker["kind"] == "conflict":
        return "%s: %s" % (fs.marker_conflict_message(marker), fix)
    if marker["kind"] == "supervised":
        return "the marker names %s, not launchd: %s" % (marker["manager"], fix)
    if marker.get("unreadable") is not None:
        return "the marker %r names no supervisor: %s" % (marker["unreadable"], fix)
    return "no %s=launchd: %s" % (fs.SUPERVISOR_ENV, fix)


def priority_problems(plist: dict) -> list:
    """A service that answers hosts and agents must not be scheduled as background work."""
    out = []
    if plist.get("ProcessType", "Standard") in ("Background", "Adaptive"):
        out.append("ProcessType is %s" % plist.get("ProcessType"))
    if isinstance(plist.get("Nice"), int) and plist["Nice"] > 0:
        out.append("Nice is %d" % plist["Nice"])
    if plist.get("LowPriorityIO") is True or plist.get("LowPriorityBackgroundIO") is True:
        out.append("low-priority I/O")
    return out


# A platform router (Heroku, Fly, Render, a CDN) routes by Host, so a request naming a foreign
# Host never reaches an online service: the router itself answers, typically 404 or 421. That is
# still a refusal — the service disclosed nothing — so for a remote placement the host check
# accepts it, as long as the body is not the well-known document. Every other guard request names
# the right Host, reaches the service, and must be the service's own 403.
PLATFORM_HOST_REFUSALS = (400, 404, 421)


def guard_verdict(rule: str, remote: bool, status: int, body: bytes) -> Tuple[str, str]:
    if status == 403:
        return "PASS", "HTTP 403"
    disclosed = b"fabric-service/" in (body or b"")
    if rule == "network.host-check" and remote and status in PLATFORM_HOST_REFUSALS and not disclosed:
        return "PASS", "HTTP %d from the platform router: a foreign Host never reaches the service" % status
    return "FAIL", "HTTP %d%s" % (status, ", and the body is the well-known document" if disclosed else "")


def board_responder_verdict(wk: Any, kit: Optional[str] = None) -> Tuple[str, str]:
    """board.responder: NOT_RUN when the well-known document declares no fabric-project-comms revision; FAIL when it
    declares one this kit does not read or the kit's fixture conversation finds a problem; PASS otherwise. `kit` is the
    service's own copy (a .py or .mjs path); by default the kit beside this probe."""
    protocols = wk.get("protocols") if isinstance(wk, dict) else None
    declared = [p for p in protocols if isinstance(p, str) and p.startswith("fabric-project-comms/")] if isinstance(protocols, list) else []
    if not declared:
        return "NOT_RUN", "the service declares no board participation (no fabric-project-comms revision in protocols)"
    accepted = fs.accepted_revisions("fabric-project-comms")
    unread = [p for p in declared if "error" in fs.negotiate_revision(p, accepted)]
    if unread:
        return "FAIL", "declares %s, which this kit does not read (it reads %s)" % (", ".join(unread), ", ".join(accepted))
    try:
        if kit and kit.endswith(".mjs"):
            if not shutil.which("node"):
                return "NOT_RUN", "node is not installed to run %s's fixture conversation" % kit
            url = Path(kit).resolve().as_uri()
            out = subprocess.run(["node", "--input-type=module", "-e",
                                  "import(process.env.FABRIC_BOARD_KIT).then(async (m) => console.log(JSON.stringify(await m.selfCheck())))"],
                                 env=dict(os.environ, FABRIC_BOARD_KIT=url), capture_output=True, text=True, timeout=60)
            problems = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 and out.stdout.strip() else ["the Node kit did not run: %s" % out.stderr.strip()[:200]]
        else:
            # A clean interpreter: the kit is several modules (FAA-65), and modules this probe already imported from
            # beside it would stand in for the copy under test.
            path = Path(kit) if kit else Path(__file__).resolve().parent / "fabric_board.py"
            code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import %s as board; "
                    "print(json.dumps(board.self_check()))" % path.stem)
            out = subprocess.run([sys.executable, "-E", "-s", "-c", code, str(path.resolve().parent)], capture_output=True,
                                 text=True, timeout=60, cwd=str(path.resolve().parent))
            problems = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 and out.stdout.strip() else ["the kit did not run: %s" % out.stderr.strip()[-200:]]
    except Exception as exc:  # noqa: BLE001 - a kit that cannot run its conversation fails the rule
        return "FAIL", "the kit's fixture conversation did not run: %s" % exc.__class__.__name__
    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", "declares %s; the kit%s answers the fixture conversation (whole, fenced, no epoch)" % (
        ", ".join(declared), " at %s" % kit if kit else " beside this probe")


def session_lifetime_problem(set_cookie: str, now: Optional[float] = None) -> Optional[str]:
    """DEC-0039: a session cookie set at sign-in lives at most 7 days. Max-Age wins over Expires (RFC 6265
    §5.3); a cookie with neither ends with the browser session. None when it is within the bound."""
    attrs = {}
    for part in set_cookie.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        attrs[name.strip().lower()] = value.strip()
    bound = fs.OPERATOR_SESSION_MAX_SECONDS
    if "max-age" in attrs:
        if not re.fullmatch(r"-?\d+", attrs["max-age"]):
            return "the session cookie's Max-Age %r is not a number" % attrs["max-age"]
        if int(attrs["max-age"]) > bound:
            return "the session cookie's Max-Age %s outlives 7 days (%d s, DEC-0039)" % (attrs["max-age"], bound)
        return None
    if "expires" in attrs:
        try:
            at = email.utils.parsedate_to_datetime(attrs["expires"]).timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            return "the session cookie's Expires %r is not a date" % attrs["expires"]
        if at - (time.time() if now is None else now) > bound:
            return "the session cookie's Expires %s outlives 7 days (DEC-0039)" % attrs["expires"]
    return None


def _semver(text: str) -> Tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def usage_problems(report: Any, service_id: str, instance: str) -> List[str]:
    """What makes this not a DEC-0021 usage report of the service: shape, identity and the sums of
    FAC-SEM-025. An unknown cost must be null; a day's totals are the sums of its models."""
    if not isinstance(report, dict):
        return ["not an object"]
    out: List[str] = []
    if report.get("protocol") != fs.PROTOCOL:
        out.append("protocol is %r" % report.get("protocol"))
    if report.get("service") != {"id": service_id, "instance": instance}:
        out.append("reports for %r, not %s.%s" % (report.get("service"), service_id, instance))
    if report.get("currency") != "USD":
        out.append("currency is not USD")
    days = report.get("days")
    if not isinstance(days, list) or len(days) > fs.USAGE_DAYS:
        return out + ["days is not a list of at most 31"]
    # The arithmetic of FAC-SEM-025 is the kit's `usage_findings`, the contract's `usageRules` held to its vectors: one
    # implementation, so the probe never disagrees with the kit and never throws on a count that is not a number.
    for i, day in enumerate(days):
        if not isinstance(day, dict):
            out.append("days[%d]: not an object" % i)
            continue
        if not isinstance(day.get("byModel"), list):
            out.append("days[%d]: byModel missing" % i)
            continue
        for row, at in [(day, "days[%d]" % i)] + [(m, "days[%d].byModel[%d]" % (i, j)) for j, m in enumerate(day["byModel"]) if isinstance(m, dict)]:
            cost = row.get("costUsd")
            if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0):
                out.append("%s: costUsd is not a non-negative number" % at)
        for j, m in enumerate(day["byModel"]):
            # DEC-0046, DEC-0061: a row's route is a login in its vendor's runner, an issued key, or the platform's
            # own metered models (a listing in the cloud).
            if isinstance(m, dict) and "route" in m and m["route"] not in fs.USAGE_ROUTES:
                out.append("days[%d].byModel[%d]: route %r is not subscription, key or platform-metered" % (i, j, m["route"]))
    for finding in fs.usage_findings(report):
        out.append("%s: %s" % (finding["instancePath"] or "/", finding["message"]))
    return out


def same_repository(a: str, b: str) -> bool:
    """git@github.com:o/r.git, https://github.com/o/r and github.com/o/r are one repository."""
    def norm(u: str) -> str:
        u = u.strip().lower()
        u = re.sub(r"^git@([^:]+):", r"\1/", u)
        u = re.sub(r"^[a-z+]+://", "", u)
        u = re.sub(r"^[^@/]+@", "", u)
        return re.sub(r"\.git$", "", u).rstrip("/")
    return bool(a and b) and norm(a) == norm(b)
