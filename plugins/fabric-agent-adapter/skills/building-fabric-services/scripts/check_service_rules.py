"""The probe's rules that read one thing and need no running service (FAA-65): a plist's marker and priority, the
network guard's verdict, the board responder's fixture conversation, a session cookie's lifetime, a usage report,
whether two repository URLs name one repository, a service's actions declaration (DEC-0121) and whether its checkout
opens its pages in a browser (FAA-118). ``check_service.py`` runs them against a live service.
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
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as fs  # noqa: E402 - beside this file
import fabric_actions as fa  # noqa: E402 - beside this file (DEC-0121)


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
        if re.search(r"(TOKEN|SECRET|PASSWORD|KEY)\Z", key) and not key.endswith("_FILE"):
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


def _body_carries_document(body: bytes) -> bool:
    """Whether a raw answer body parses as JSON that carries the well-known document or a part of it."""
    try:
        return _carries_document(json.loads((body or b"").decode("utf-8", "replace")))
    except RecursionError:
        return True
    except ValueError:
        return False


def guard_verdict(rule: str, remote: bool, status: int, body: bytes) -> Tuple[str, str]:
    """A guard refuses with the service's own 403, and no refusal carries the well-known document (a 403 whose body is
    the document refused nothing). Elsewhere the substring `fabric-service/` alone already counts as disclosure."""
    if status == 403:
        if _body_carries_document(body):
            return "FAIL", "HTTP 403, and the body carries the well-known document"
        return "PASS", "HTTP 403"
    disclosed = b"fabric-service/" in (body or b"") or _body_carries_document(body)
    if rule == "network.host-check" and remote and status in PLATFORM_HOST_REFUSALS and not disclosed:
        return "PASS", "HTTP %d from the platform router: a foreign Host never reaches the service" % status
    return "FAIL", "HTTP %d%s" % (status, ", and the body is the well-known document" if disclosed else "")


def _carries_document(value: Any, depth: int = 0) -> bool:
    """Whether a parsed body is, or holds anywhere inside it, an object that reads as the well-known document or a part
    of it: its `protocol` is the extension's, its `service` is an object with an `id`, or its `process` an object with
    a `pid` (D3 of FAA-109). A proxy's own error with a `service` string is none of these."""
    if depth > 64:
        return True  # nothing honest nests that deep; refuse rather than recurse without bound
    if isinstance(value, dict):
        service, process = value.get("service"), value.get("process")
        if value.get("protocol") == fs.PROTOCOL or (isinstance(service, dict) and "id" in service) \
                or (isinstance(process, dict) and "pid" in process):
            return True
        return any(_carries_document(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_carries_document(v, depth + 1) for v in value)
    return False


def no_token_verdict(status: int, body: bytes, identities: List[str], host: str = "") -> Tuple[str, str]:
    """DEC-0109 (`well-known.requires-token` on a remote placement): the no-token answer is `401` and carries none of
    the service's data. An empty body passes; so does an identity proxy's page in front of the service, as long as it
    neither parses as the well-known document nor names one of the service's own identity values (its id, its
    `id.instance`, its build or its pid, as whole words). The service's own host name is taken out first: a sign-in page
    names the address it guards, and the address is not the document's data. A value shorter than four characters
    names nothing on its own (a platform's pid is often 1) and is not looked for."""
    if status != 401:
        return "FAIL", "HTTP %d without a token" % status
    if not body:
        return "PASS", "HTTP 401 without a token, an empty body"
    text = body.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except RecursionError:
        return "FAIL", "HTTP 401, and the body nests deeper than any page does"
    except ValueError:
        doc = None
    if _carries_document(doc):
        return "FAIL", "HTTP 401, and the body carries the well-known document"
    if host:
        text = re.sub(re.escape(host), " ", text, flags=re.IGNORECASE)
    for value in identities:
        if len(value) >= 4 and re.search(r"(?<![A-Za-z0-9_.-])%s(?![A-Za-z0-9_-])" % re.escape(value), text):
            return "FAIL", "HTTP 401, and the %d-byte body names the service's identity value %r" % (len(body), value)
    return "PASS", "HTTP 401 without a token, a %d-byte page that is not the service's (an identity proxy's, DEC-0109)" % len(body)


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


def merge_headers(pairs: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    """Response headers by lower-case name. Every Set-Cookie is kept, one per line (a header value never holds a
    newline): an edge in front of a service adds its own (FAA-115), so the last or the first is not the service's."""
    merged: Dict[str, str] = {}
    for name, value in pairs:
        key = name.lower()
        merged[key] = merged[key] + "\n" + value if key == "set-cookie" and key in merged else value
    return merged


def session_cookie(set_cookie: str, remote: bool) -> str:
    """The service's session cookie among the Set-Cookie lines merge_headers kept: the one named as the kit names it
    (`__Host-fabric_session` remote, `fabric_session` local, either accepted), else the first a CDN edge does not
    set, so a service that names its cookie otherwise is still judged on its own cookie. "" when none was set."""
    lines = [line.strip() for line in set_cookie.split("\n") if line.strip()]
    names = (fs.REMOTE_SESSION_COOKIE, fs.SESSION_COOKIE) if remote else (fs.SESSION_COOKIE, fs.REMOTE_SESSION_COOKIE)
    for wanted in names:
        for line in lines:
            if line.split("=", 1)[0].strip() == wanted:
                return line
    for line in lines:
        if line.split("=", 1)[0].strip() not in EDGE_COOKIES:
            return line
    return lines[0] if lines else ""


# Cookies CDN edges add on their own (Cloudflare, AWS load balancers, Akamai); never a service's session.
EDGE_COOKIES = frozenset({"__cf_bm", "_cfuvid", "cf_clearance", "__cflb", "AWSALB", "AWSALBCORS", "ak_bmsc", "bm_sv"})


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


# actions (fabric-actions/0.1, DEC-0121, FAC-SEM-142) ----------------------------------------
_ACTIONS_KEY_PATH = "/extensions/" + fa.ACTIONS_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")


def _actions_place(instance_path: str) -> str:
    """A finding's place inside the declaration (`/actions/1/id`), or the declaration itself."""
    inner = instance_path[len(_ACTIONS_KEY_PATH):] if instance_path.startswith(_ACTIONS_KEY_PATH) else instance_path
    return inner or "extensions/actions/0.1"


def well_known_actions_verdict(wk: Any) -> Tuple[str, str]:
    """`well-known.actions`: a declared extensions/actions/0.1 is FAC-SEM-142's (the kit's actions_extension_rules, the
    contract's reader): its schema's, each id once, humanStep exactly when gate is human, every tool in a present
    surfaces.mcp.capabilities. No declaration is NOT_RUN: dashboard.actions-declared says what that means."""
    view = fa.actions_view(wk)
    if not view["declared"]:
        return "NOT_RUN", "no extensions/actions/0.1 declaration (DEC-0121 AP-1)"
    findings = fa.actions_extension_rules(wk)
    if findings:
        return "FAIL", "; ".join("FAC-SEM-142 %s: %s" % (_actions_place(f["instancePath"]), f["message"]) for f in findings[:5])
    gates: Dict[str, int] = {}
    for action in view["actions"]:
        gates[action["gate"]] = gates.get(action["gate"], 0) + 1
    return "PASS", "%d action(s) (%s), FAC-SEM-142 holds" % (
        len(view["actions"]), ", ".join("%d %s" % (n, g) for g, n in sorted(gates.items())))


def action_tools_verdict(wk: Any, tools: Optional[Dict[str, Any]], why_not: str = "tools/list was not read") -> Tuple[str, str]:
    """`interop.action-tools`: every declared action's tool is served by tools/list, the live surface (FAC-SEM-142
    checks only the list the document names). `tools` None means no listing was read; `why_not` says why."""
    view = fa.actions_view(wk)
    if not view["declared"]:
        return "NOT_RUN", "no extensions/actions/0.1 declaration"
    if not view["valid"]:
        return "NOT_RUN", "the actions declaration is not readable (well-known.actions): a reader treats it as not declared"
    if tools is None:
        return "NOT_RUN", why_not
    missing = ["%s (%s)" % (a["tool"], a["id"]) for a in view["actions"] if a["tool"] not in tools]
    if missing:
        return "FAIL", ("tools/list does not serve %s: a button without an agent twin (DEC-0121 AP-1)" % ", ".join(missing))
    return "PASS", "%d declared action(s), every tool served by tools/list" % len(view["actions"])


def actions_declared_verdict(wk: Any) -> Tuple[str, str]:
    """`dashboard.actions-declared` (decision D10): a dashboard whose declaration FAC-SEM-142 accepts passes, one it
    finds (unreadable, a repeated id, a step that disagrees with the gate, a tool the surface does not list) fails,
    and one with none is NOT_RUN, never FAIL: a read-only dashboard cannot declare an empty list
    (minItems 1), so absence proves no page-only button. Fabric Dashboards reports it (CT-126)."""
    surfaces = wk.get("surfaces") if isinstance(wk, dict) else None
    if not (isinstance(surfaces, dict) and surfaces.get("dashboard")):
        return "NOT_RUN", "no surfaces.dashboard"
    view = fa.actions_view(wk)
    if not view["declared"]:
        return "NOT_RUN", ("a dashboard with no extensions/actions/0.1 declaration: a read-only dashboard declares none "
                           "(the list needs minItems 1), so its absence proves no page-only button; a dashboard with a "
                           "button declares it and its agent twin (DEC-0121 AP-1). Fabric Dashboards reports it (CT-126)")
    if not view["valid"]:
        return "FAIL", "the dashboard's actions declaration is not readable, so a host treats it as not declared (well-known.actions)"
    findings = fa.actions_extension_rules(wk)
    if findings:
        return "FAIL", "the dashboard's actions declaration breaks FAC-SEM-142 in %d place(s) (well-known.actions)" % len(findings)
    return "PASS", "the dashboard declares %d action(s) with their tools (DEC-0121 AP-1)" % len(view["actions"])


# dashboard.opens-in-host (FAA-118; the operator rule of 2026-10-24; decision D13) ----------------------------------
# A service's own pages open only through Fabric Dashboards: the `open_link` of the fabric-dashboards MCP `link` tool,
# opened with the host's `open` and `fallback=never`; a browser only on a confirmed `not_installed` host. The rule reads
# the service's checkout, tracked text files only (`git grep -I`, no untracked file, no binary), within a time budget,
# and reports a line that opens a browser at the service's pages. The matcher, kept precise on purpose:
#
# 1. An opener (`_OPENERS`): macOS `open -a <browser>` / `open -b <browser bundle id>` / `open <http(s) URL>` /
#    `open $<...url|link|origin|dashboard|page...>`; `xdg-open`, `gio open`, `sensible-browser`, `x-www-browser`,
#    `wslview`; Windows `start [""] <URL>`, `explorer <URL>`, `url.dll,FileProtocolHandler`; Python
#    `webbrowser.open|open_new|open_new_tab|get(`; Electron `openExternal(`; a process call whose argv starts with one
#    of those programs (`subprocess.run(["open", ...])`, `spawn("xdg-open", ...)`); and in a JavaScript or TypeScript
#    file that imports the npm package `open`, a call of the name it was bound to (`open(...)`, never `x.open(...)`).
#    Python's builtin `open(` and a page's `window.open(` are files and tabs, never an opener.
# 2. Aimed at the service's pages: in code, the opener's line or one of the 5 lines before it (where a URL is built)
#    names a loopback host (127.0.0.1, localhost, [::1], 0.0.0.0), the service's port as a whole number, its origin's
#    host, its dashboard path (when it is not just "/") or its login path; or the opener's line names an identifier
#    built on "dashboard" (`dashboard_url`, `openDashboard`; never the host app's name "Fabric Dashboards"). In prose
#    the aim is on the opener's own line. An opener with no such aim (a docs site, a report file) is not this rule's.
# 3. In prose (Markdown and the like) only code counts: a fenced block, or an inline code span (`open -a Safari ...`);
#    "then open `http://localhost:3000`" is a sentence for a person. A prose line that forbids it (never, not, avoid,
#    instead of, ...) is not a finding either.
# 4. Not a finding: the host's own route (`fabric-dashboards://`, the "Fabric Dashboards" app, `open_link`,
#    `native_link` on the line); the allowed fallback (`not_installed` on the line or the 5 before, or the gate's
#    `browser_link` on the line); a comment line in code; and test, spec and fixture files, which plant raw opens on
#    purpose.
_BROWSERS = (r"(?:Safari(?: Technology Preview)?|Google Chrome(?: Canary| Dev| Beta)?|Chrome|Chromium|"
             r"Firefox(?: Developer Edition| Nightly)?|Arc|Dia|Brave Browser|Brave|Microsoft Edge|Opera|Vivaldi|Orion|Zen)")
_BUNDLES = (r"(?:com\.apple\.Safari\w*|com\.google\.Chrome\w*|org\.chromium\.Chromium|org\.mozilla\.firefox\w*|"
            r"company\.thebrowser\.\w+|com\.brave\.Browser\w*|com\.microsoft\.edgemac\w*|com\.operasoftware\.Opera\w*|"
            r"com\.vivaldi\.Vivaldi|com\.kagi\.kagimacOS)")
_PROGRAMS = r"(?:open|xdg-open|wslview|sensible-browser|x-www-browser|gio|start|explorer(?:\.exe)?)"
#: Where a shell command starts: a line, a separator, `$(`, a Makefile's `@`, `then`, `do`, `else` or cmd's `/c`, or
#: right after an opening quote or backtick (a string a process call runs). `playwright-cli open <url>` is that tool's
#: own subcommand, and `--proxy "http://..." open` an argument after a closing quote.
_CMD = r"(?:(?:^|[;&|({@]|\$\(|\bthen\b|\bdo\b|\belse\b|/[cC]\b)\s*|[`'\"])"
_OPENERS = re.compile("|".join((
    _CMD + r"open\s+(?:-[a-zA-Z]+\s+)*-a\s+[\"']?" + _BROWSERS + r"(?![\w-])",
    _CMD + r"open\s+(?:-[a-zA-Z]+\s+)*-b\s+[\"']?" + _BUNDLES,
    _CMD + r"open\s+(?:-[gnF]\s+)*[\"'`]?(?:https?://|\$\{?\w*(?i:url|link|origin|dashboard|page)\w*)",
    r"(?<![\w.$/-])(?:xdg-open|gio\s+open|sensible-browser|x-www-browser|wslview)(?![\w-])",
    _CMD + r"start\s+(?:\"\"\s+)?[\"']?https?://",
    _CMD + r"explorer(?:\.exe)?\s+[\"']?https?://",
    r"url\.dll,\s*FileProtocolHandler",
    r"\bwebbrowser\.(?:open|open_new|open_new_tab|get)\(",  # a call, never "webbrowser.open (the default)" in prose
    r"\bopenExternal\(",
    r"(?:spawn|spawnSync|execFile|execFileSync|exec|execSync|Popen|run|call|check_call|check_output)\s*\(\s*\[?\s*"
    r"[\"'`]" + _PROGRAMS + r"[\"'`]\s*[,)\]]",
)))
_OPEN_PACKAGE = re.compile(r"""import\s+(\w+)\s+from\s+["']open["']|(?:const|let|var)\s+(\w+)\s*=\s*require\(\s*["']open["']\s*\)""")
_JS_FILES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
_PROSE_FILES = (".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc", ".org")
_LOOPBACK = re.compile(r"(?:127\.0\.0\.1|\blocalhost\b|\[::1\]|0\.0\.0\.0)")
_HOST_ROUTE = re.compile(r"fabric-dashboards://|Fabric Dashboards|\b(?:open_link|openLink|native_link|nativeLink)\b")
_FALLBACK = re.compile(r"\bnot[_-]installed\b|\bnotInstalled\b|\bNOT_INSTALLED\b")
_GATE_LINK = re.compile(r"\b(?:browser_link|browserLink)\b")
_NEGATION = re.compile(r"(?i)\b(?:never|not|don't|doesn't|avoid|instead of|forbidden|refused?|wrong|no longer|nonconformant)\b")
_COMMENT = re.compile(r"\s*(?:#(?!!)|//|/\*|\*|<!--|REM\s|::)")
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__|specs?|fixtures|testdata|e2e)/|(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.\w+|"
                        r"[^/]*\.(?:test|spec)\.\w+|conftest\.py)\Z")
_WINDOW = 5  # lines before an opener that may hold its aim or the not_installed branch
OPENS_IN_HOST_BUDGET = 3.0  # seconds for git and reading, as the session-start notice budgets its own git calls
_MAX_CANDIDATES = 2000
_MAX_FILE_BYTES = 1 << 20
_COARSE = (r"open[[:space:]]+-[ab][[:space:]]|open[[:space:]]+[\"'`]?(https?://|\$)|xdg-open|gio[[:space:]]+open|"
           r"sensible-browser|x-www-browser|wslview|start[[:space:]]+(\"\"[[:space:]]+)?[\"']?https?://|"
           r"explorer(\.exe)?[[:space:]]+[\"']?https?://|FileProtocolHandler|webbrowser\.|openExternal|"
           r"[\"'`](open|xdg-open|wslview|start|explorer)[\"'`]")


def _aims(lines: List[str], port: int, host: str, dashboard_path: str) -> bool:
    text = "\n".join(lines)
    if _LOOPBACK.search(text) or "/fabric/v1/login" in text:
        return True
    if port and re.search(r"(?<!\d)%d(?!\d)" % port, text):
        return True
    if host and host in text:
        return True
    return bool(dashboard_path and dashboard_path != "/" and re.search(re.escape(dashboard_path) + r"(?![\w-])", text))


#: Text before an opener that makes it a message for a person: `echo "... open http://..."`, print, a log call.
_MESSAGE = re.compile(r"\b(?:echo|printf|print|puts|say)\b|\bconsole\.\w+\s*\(|\blog(?:ger)?\.\w+\s*\(|\blog\s*\(")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FENCE = re.compile(r"\s*(?:```|~~~)")


def _names_dashboard(line: str) -> bool:
    """An identifier built on "dashboard" (dashboard_url, openDashboard), never the word alone or the host's name."""
    return any("dashboard" in word.lower() and word.lower() not in ("dashboard", "dashboards")
               for word in _IDENTIFIER.findall(line.split("://", 1)[0]))


def _prose_code(lines: List[str]) -> List[str]:
    """Each line of a prose file reduced to its code: whole inside a fenced block, else its inline code spans."""
    out, fenced = [], False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            out.append("")
        elif fenced:
            out.append(line)
        else:
            out.append(" ; ".join(re.findall(r"`([^`]+)`", line)))  # each span its own command
    return out


def opener_findings(path: str, text: str, port: int, origin: Optional[str], dashboard_path: Optional[str]) -> List[Tuple[int, str]]:
    """The lines of one file (repository-relative `path`, its `text`) that open a browser at the service's pages, as
    (line number, line); the matcher is described above. Never raises on what it reads."""
    path = (path or "").replace("\\", "/")
    if not isinstance(text, str) or _TEST_PATH.search(path):
        return []
    prose = path.lower().endswith(_PROSE_FILES)
    calls = None
    if path.lower().endswith(_JS_FILES):
        names = [a or b for a, b in _OPEN_PACKAGE.findall(text)]
        if names:
            calls = re.compile(r"(?<![\w.$])(?:%s)\s*\(" % "|".join(re.escape(n) for n in names))
    host = ""
    if isinstance(origin, str) and "://" in origin:
        host = origin.split("://", 1)[1].split("/", 1)[0].rsplit("@", 1)[-1]
        if _LOOPBACK.fullmatch(host.rsplit(":", 1)[0]):
            host = ""  # a loopback origin is covered by the loopback hosts and the port
    original = text.splitlines()
    lines = _prose_code(original) if prose else original
    out: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _OPENERS.search(line) or (calls.search(line) if calls is not None and not _OPEN_PACKAGE.search(line) else None)
        if match is None or _MESSAGE.search(line[:match.start()]):
            continue
        if _HOST_ROUTE.search(line) or _GATE_LINK.search(line):
            continue
        if (prose and _NEGATION.search(original[index])) or _COMMENT.match(line):
            continue
        window = lines[max(0, index - _WINDOW):index + 1]
        if any(_FALLBACK.search(w) for w in window):
            continue
        aim = [line] if prose else window
        if _aims(aim, port, host, str(dashboard_path or "")) or _names_dashboard(line):
            out.append((index + 1, original[index].strip()))
    return out


def opens_in_host_verdict(repo: Path, port: int, origin: Optional[str], dashboard_path: Optional[str],
                          budget: float = OPENS_IN_HOST_BUDGET) -> Tuple[str, str]:
    """`dashboard.opens-in-host` over one checkout: FAIL with the places a tracked text file opens a browser at the
    service's pages, PASS when none does, NOT_RUN when the checkout or git cannot be read or the budget runs out."""
    until = time.monotonic() + max(0.0, budget)
    if not shutil.which("git"):
        return "NOT_RUN", "git is not installed"

    def left() -> float:
        return until - time.monotonic()

    if left() <= 0:
        return "NOT_RUN", "the %.1f s budget ran out before the checkout was read" % budget
    try:
        top = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=max(0.05, left()))
        if top.returncode != 0 or not top.stdout.strip():
            return "NOT_RUN", "%s is not a Git checkout" % repo
        root = Path(top.stdout.strip())
        if left() <= 0:
            return "NOT_RUN", "the %.1f s budget ran out before the checkout was read" % budget
        listed = subprocess.run(["git", "-C", str(root), "grep", "-I", "-l", "-z", "-E", _COARSE], capture_output=True,
                                timeout=max(0.05, left()))
    except subprocess.TimeoutExpired:
        return "NOT_RUN", "the %.1f s budget ran out while git read %s" % (budget, repo)
    except OSError as exc:
        return "NOT_RUN", "git could not read %s: %s" % (repo, exc)
    if listed.returncode not in (0, 1):  # 1: nothing matched
        return "NOT_RUN", "git grep could not read %s" % root
    candidates = [p for p in listed.stdout.decode("utf-8", "surrogateescape").split("\0") if p]
    if len(candidates) > _MAX_CANDIDATES:
        return "NOT_RUN", "%d candidate files in %s, more than the %d this rule reads" % (len(candidates), root, _MAX_CANDIDATES)
    found: List[str] = []
    for name in candidates:
        if left() <= 0:
            return "NOT_RUN", "the %.1f s budget ran out after reading part of %s" % (budget, root)
        try:
            with open(root / name, "rb") as handle:
                text = handle.read(_MAX_FILE_BYTES).decode("utf-8", "replace")
        except OSError:
            continue
        found += ["%s:%d %s" % (name, line, snippet[:100]) for line, snippet in opener_findings(name, text, port, origin, dashboard_path)]
    if found:
        return "FAIL", ("%s. Open the service's pages through Fabric Dashboards: the open_link of the fabric-dashboards MCP "
                        "link tool, opened with fallback=never; a browser only on a confirmed not_installed host "
                        "(operator rule of 2026-10-24)" % "; ".join(found[:5] + (["and %d more" % (len(found) - 5)] if len(found) > 5 else [])))
    return "PASS", ("%d tracked text file(s) in %s name a possible opener; none opens a browser at the service's pages: "
                    "they open through Fabric Dashboards" % (len(candidates), root))


def _git_out(cwd: Path, *args: str) -> Optional[str]:
    try:
        done = subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, timeout=2.0)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def service_checkout(descriptor: Any, repo: Optional[str]) -> Tuple[Optional[Path], str]:
    """The service's checkout: `repo` (the probe's --repo) when given, else the checkout holding one of the
    descriptor's paths (its commands, its fabricManifest, its launchd job's program and working directory) whose origin
    is the descriptor's `source.repository`. (None, why) when there is none."""
    if repo:
        top = _git_out(Path(repo).expanduser(), "rev-parse", "--show-toplevel")
        return (Path(top), "--repo") if top else (None, "--repo %s is not a Git checkout" % repo)
    d = descriptor if isinstance(descriptor, dict) else {}
    own = d.get("source")
    source = own.get("repository") if isinstance(own, dict) else None
    if not isinstance(source, str) or not source:
        return None, "the descriptor names no source.repository to find the service's checkout by; pass --repo"
    places: List[str] = []
    commands = d.get("commands")
    for argv in (commands.values() if isinstance(commands, dict) else []):
        places += [a for a in argv if isinstance(a, str)] if isinstance(argv, list) else []
    if isinstance(d.get("fabricManifest"), str):
        places.append(d["fabricManifest"])
    life = d.get("lifecycle") if isinstance(d.get("lifecycle"), dict) else {}
    if isinstance(life.get("plist"), str):
        try:
            import plistlib
            plist = plistlib.loads(Path(life["plist"]).expanduser().read_bytes())
            places += [a for a in (plist.get("ProgramArguments") or []) if isinstance(a, str)]
            places += [plist["WorkingDirectory"]] if isinstance(plist.get("WorkingDirectory"), str) else []
        except (OSError, ValueError, AttributeError, TypeError, plistlib.InvalidFileException):
            pass
    seen = set()
    for place in places:
        if not (place.startswith(("/", "~")) or re.match(r"[A-Za-z]:[\\/]", place)):
            continue
        start = Path(os.path.expanduser(place))
        while not start.is_dir() and start != start.parent:
            start = start.parent
        top = _git_out(start, "rev-parse", "--show-toplevel")
        if not top or top in seen:
            continue
        seen.add(top)
        if same_repository(_git_out(Path(top), "remote", "get-url", "origin") or "", source):
            return Path(top), "the checkout of %s that holds %s" % (source, place)
    return None, "no checkout of %s holds the descriptor's commands, manifest or launchd job; pass --repo" % source
