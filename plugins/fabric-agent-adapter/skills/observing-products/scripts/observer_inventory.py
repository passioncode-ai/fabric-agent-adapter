#!/usr/bin/env python3
"""Check an observer's channel inventory (docs/observer/channels.md) and its state file (docs/observer/state.json).

The inventory is a Markdown file in the product's own repository: a few `- Key: value` lines (authority, interval,
budget) and one table, one row per channel. This script reads it, refuses what the observing-products skill forbids
(a credential written as a value, a channel counted as connected without the date of a proven read, an unknown kind,
state or placement) and prints how many channels are connected out of named. The state file holds what a session
started in place of a dead one reads first (cursors, waits, promises, checked branch heads, long sessions); `state`
checks its shape and refuses a secret written in it. Each command reads at most two files and writes nothing.

  python3 observer_inventory.py check docs/observer/channels.md            # text report
  python3 observer_inventory.py check docs/observer/channels.md --json     # machine-readable report
  python3 observer_inventory.py template --project example-app             # an empty inventory to start from
  python3 observer_inventory.py state docs/observer/state.json --channels docs/observer/channels.md
  python3 observer_inventory.py state-template --project example-app       # an empty state file to start from

Exit: 0 the inventory is valid; 1 it has problems (each one printed); 2 usage error or the file cannot be read.
Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

KINDS = ("ops-log", "errors", "analytics", "funnel", "revenue", "store", "uptime", "ci", "board", "support",
         "agent-session", "work-queue", "consumer-repo", "board-thread", "other")
PLACEMENTS = ("local", "remote")
STATES = ("connected", "missing", "blocked", "not-applicable")
AUTHORITIES = ("observe", "fix", "ship")
COLUMNS = ("channel", "kind", "placement", "read", "credential", "cursor", "baseline", "thresholds", "owner", "state")
# A vault slot is named <project>/<env>/<NAME>; the value itself never appears in the inventory.
SLOT = re.compile(r"[a-z0-9][a-z0-9._-]*/(?:local|stage|prod)/[A-Z][A-Z0-9_]*")
CONNECTED = re.compile(r"connected (\d{4}-\d{2}-\d{2})")
WITH_STEP = re.compile(r"(missing|blocked|not-applicable): *(\S.*)")
KEY_LINE = re.compile(r"- *(Project|Authority|Interval|Budget): *(.*)")
INTERVAL = re.compile(r"(\d+)(m|h)")
BUDGET = re.compile(r"USD (\d+(?:\.\d+)?) */ *month")

TEMPLATE = """# Observer channels: {project}

- Project: {project}
- Authority: observe
- Interval: 30m
- Budget: USD 100 / month

| Channel | Kind | Placement | Read | Credential | Cursor | Baseline | Thresholds | Owner | State |
|---|---|---|---|---|---|---|---|---|---|
| ci | ci | remote | `gh run list --branch main --limit 20 --json conclusion,databaseId,createdAt` | none | last run id | none: any red run is a finding | a red run on main | the repository | missing: run the read once and record its date |
"""


def _cell(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        return text[1:-1].strip()
    return text


def _split_row(line: str) -> List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells, current, in_code = [], [], False
    index = 0
    while index < len(body):
        ch = body[index]
        if ch == "\\" and body[index + 1:index + 2] == "|":
            current.append("|")
            index += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        index += 1
    cells.append("".join(current))
    return [c.strip() for c in cells]


def _is_separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


def parse(text: str) -> Tuple[Dict[str, str], List[Dict[str, Any]], List[str]]:
    """The key lines, the channel rows (each with its line number) and the structural problems."""
    keys: Dict[str, str] = {}
    rows: List[Dict[str, Any]] = []
    problems: List[str] = []
    lines = text.splitlines()
    header: Optional[List[str]] = None
    index = 0
    while index < len(lines):
        line = lines[index]
        key = KEY_LINE.fullmatch(line.strip())
        if key and header is None:
            keys[key.group(1).lower()] = key.group(2).strip()
        if line.strip().startswith("|") and header is None and index + 1 < len(lines):
            cells = [c.lower() for c in _split_row(line)]
            if "channel" in cells and _is_separator(_split_row(lines[index + 1])):
                header = cells
                missing = [c for c in COLUMNS if c not in header]
                if missing:
                    problems.append("line %d: the table lacks the column(s) %s" % (index + 1, ", ".join(missing)))
                    return keys, rows, problems
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    cells = _split_row(lines[index])
                    if len(cells) != len(header):
                        problems.append("line %d: %d cells, the header has %d" % (index + 1, len(cells), len(header)))
                    else:
                        row = {name: _cell(value) for name, value in zip(header, cells)}
                        row["line"] = index + 1
                        rows.append(row)
                    index += 1
                break
        index += 1
    if header is None:
        problems.append("no channel table: a header row naming %s, then a separator row" % ", ".join(COLUMNS))
    return keys, rows, problems


def check_keys(keys: Dict[str, str]) -> List[str]:
    problems = []
    authority = keys.get("authority", "")
    if authority not in AUTHORITIES:
        problems.append("Authority must be one of %s, found %r" % ("/".join(AUTHORITIES), authority))
    interval = INTERVAL.fullmatch(keys.get("interval", ""))
    if not interval or int(interval.group(1)) == 0:
        problems.append("Interval must read like 30m or 1h, found %r" % keys.get("interval", ""))
    if "budget" in keys and not BUDGET.fullmatch(keys["budget"]):
        problems.append("Budget must read like 'USD 100 / month', found %r" % keys["budget"])
    return problems


def check_row(row: Dict[str, Any], today: datetime.date) -> Tuple[str, List[str]]:
    """The row's state and its problems."""
    where = "line %d (%s)" % (row["line"], row.get("channel") or "unnamed")
    problems = []
    for column in COLUMNS:
        if not row.get(column):
            problems.append("%s: %s is empty" % (where, column))
    if row.get("kind") and row["kind"] not in KINDS:
        problems.append("%s: kind %r is not one of %s" % (where, row["kind"], ", ".join(KINDS)))
    if row.get("placement") and row["placement"] not in PLACEMENTS:
        problems.append("%s: placement must be local or remote, found %r" % (where, row["placement"]))
    credential = row.get("credential", "")
    if credential and credential != "none" and not SLOT.fullmatch(credential):
        problems.append("%s: credential must be a vault slot name (<project>/<env>/<NAME>) or none; never a value"
                        % where)
    state_text = row.get("state", "")
    state = ""
    connected = CONNECTED.fullmatch(state_text)
    with_step = WITH_STEP.fullmatch(state_text)
    if connected:
        state = "connected"
        try:
            read_on = datetime.date.fromisoformat(connected.group(1))
        except ValueError:
            problems.append("%s: %r is not a date" % (where, connected.group(1)))
            state = ""
        else:
            if read_on > today:
                problems.append("%s: the proven read is dated in the future (%s)" % (where, read_on))
                state = ""
    elif with_step:
        state = with_step.group(1)
    elif state_text.split(" ", 1)[0].rstrip(":") in STATES:
        problems.append("%s: state %r needs %s" % (where, state_text, "the date of its proven read (connected YYYY-MM-DD)"
                                                    if state_text.startswith("connected") else "its step or gate after a colon"))
    elif state_text:
        problems.append("%s: state %r is not one of %s" % (where, state_text, ", ".join(STATES)))
    return state, problems


def check(text: str, today: Optional[datetime.date] = None) -> Dict[str, Any]:
    today = today or datetime.date.today()
    keys, rows, problems = parse(text)
    if rows or keys:
        problems = check_keys(keys) + problems
    counts = {state: 0 for state in STATES}
    seen: Dict[str, int] = {}
    by_placement = {placement: 0 for placement in PLACEMENTS}
    for row in rows:
        state, row_problems = check_row(row, today)
        problems.extend(row_problems)
        if state:
            counts[state] += 1
        name = row.get("channel", "")
        if name in seen:
            problems.append("line %d: channel %r is named twice (first on line %d)" % (row["line"], name, seen[name]))
        elif name:
            seen[name] = row["line"]
        if state == "connected" and row.get("placement") in by_placement:
            by_placement[row["placement"]] += 1
    if not rows and not problems:
        problems.append("the table names no channel")
    named = len(rows) - counts["not-applicable"]
    return {
        "valid": not problems,
        "project": keys.get("project"),
        "authority": keys.get("authority"),
        "interval": keys.get("interval"),
        "named": named,
        "connected": counts["connected"],
        "states": counts,
        "connectedByPlacement": by_placement,
        "problems": problems,
    }


# ---------------------------------------------------------------------------------------------------------------------
# The state file: docs/observer/state.json, schema observer-state/1 (a project may prefix it: <name>.observer-state/1).

STATE_SCHEMA = re.compile(r"(?:[a-z0-9][a-z0-9._-]*\.)?observer-state/1")
# Each required field may go by one of its names (the first is the canonical one).
WAIT_FIELDS = (("id",), ("what",), ("watch", "watcher"), ("then", "next"), ("source", "owner"))
WAIT_STATES = ("open", "paused", "done", "dropped")
PROMISE_FIELDS = (("id",), ("to",), ("what",), ("source",))
PROMISE_STATES = ("open", "kept", "broken", "dropped")
SHA = re.compile(r"[0-9a-f]{7,40}")
SECRET_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)
SECRET_KEYS = re.compile(r"(?i)(?:^|[_-])(?:token|secret|password|passwd|api[_-]?key|private[_-]?key)\Z")
STATE_TEMPLATE = {
    "schema": "observer-state/1",
    "project": "",
    "updated": None,
    "cursors": {},
    "heads": {},
    "sessions": {},
    "waits": [],
    "promises": [],
}


def _parse_time(text: Any) -> Optional[datetime.datetime]:
    if not isinstance(text, str) or not text:
        return None
    try:
        value = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value


def _walk_secrets(value: Any, where: str, problems: List[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and SECRET_KEYS.search(key) and isinstance(item, str) and item \
                    and not SLOT.fullmatch(item):
                problems.append("%s.%s: a credential is named by its vault slot (<project>/<env>/<NAME>), never a value"
                                % (where, key))
            _walk_secrets(item, "%s.%s" % (where, key), problems)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_secrets(item, "%s[%d]" % (where, index), problems)
    elif isinstance(value, str):
        for shape in SECRET_SHAPES:
            if shape.search(value):
                problems.append("%s: holds what looks like a secret; name its vault slot instead" % where)
                break


def _status(entry: Dict[str, Any], default: str) -> Any:
    return entry.get("status", entry.get("state", default))


def _check_entries(entries: Any, name: str, fields: Sequence[Sequence[str]], states: Sequence[str], default: str,
                   problems: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        problems.append("%s must be a list" % name)
        return []
    seen: Dict[str, int] = {}
    kept = []
    for index, entry in enumerate(entries):
        where = "%s[%d]" % (name, index)
        if not isinstance(entry, dict):
            problems.append("%s must be an object" % where)
            continue
        for names in fields:
            if not any(isinstance(entry.get(field), str) and entry[field].strip() for field in names):
                problems.append("%s: %s is missing or empty" % (where, " or ".join(names)))
        status = _status(entry, default)
        if status not in states:
            problems.append("%s: status %r is not one of %s" % (where, status, ", ".join(states)))
        elif status not in (default, "paused") and not (isinstance(entry.get(status), str) and entry[status].strip()):
            problems.append("%s: status %s needs a %r field saying when and how (date and evidence)"
                            % (where, status, status))
        ident = entry.get("id")
        if isinstance(ident, str) and ident:
            if ident in seen:
                problems.append("%s: id %r is used twice (first at %s[%d])" % (where, ident, name, seen[ident]))
            else:
                seen[ident] = index
        kept.append(entry)
    return kept


def check_state(text: str, channels: Optional[Sequence[str]] = None,
                now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Check an observer state file; with the inventory's channel names, also check what each wait watches."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    problems: List[str] = []
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {"valid": False, "problems": ["not JSON: %s" % exc.__class__.__name__], "openWaits": 0,
                "openPromises": 0, "cursors": 0, "heads": 0, "project": None}
    if not isinstance(data, dict):
        return {"valid": False, "problems": ["the state file must be a JSON object"], "openWaits": 0,
                "openPromises": 0, "cursors": 0, "heads": 0, "project": None}
    schema = data.get("schema")
    if not isinstance(schema, str) or not STATE_SCHEMA.fullmatch(schema):
        problems.append("schema must be observer-state/1 (or <name>.observer-state/1), found %r" % (schema,))
    updated = data.get("updated")
    if updated is not None:
        when = _parse_time(updated)
        if when is None:
            problems.append("updated must be a date-time with its zone (2026-11-20T06:00:00Z), found %r" % (updated,))
        elif when > now + datetime.timedelta(minutes=5):
            problems.append("updated is in the future (%s)" % updated)
    cursors = data.get("cursors", {})
    if not isinstance(cursors, dict) or not all(isinstance(v, (str, int)) and not isinstance(v, bool)
                                                for v in cursors.values()):
        problems.append("cursors must map a channel name to its cursor (a string or a number)")
        cursors = {}
    heads = data.get("heads", {})
    head_count = 0
    if not isinstance(heads, dict):
        problems.append("heads must map a repository to {branch: checked commit}")
    else:
        for repo, branches in heads.items():
            if not isinstance(branches, dict):
                problems.append("heads.%s must map a branch to its checked commit" % repo)
                continue
            for branch, sha in branches.items():
                head_count += 1
                if not isinstance(sha, str) or not SHA.fullmatch(sha):
                    problems.append("heads.%s.%s: %r is not a commit id (7 to 40 lowercase hex)" % (repo, branch, sha))
    sessions = data.get("sessions", {})
    if not isinstance(sessions, dict):
        problems.append("sessions must map a name to {session, relaunch}")
    else:
        for name, session in sessions.items():
            if not isinstance(session, dict) or not all(isinstance(session.get(k), str) and session[k].strip()
                                                        for k in ("session", "relaunch")):
                problems.append("sessions.%s needs session (its id) and relaunch (the exact route that restarts it)"
                                % name)
    waits = _check_entries(data.get("waits", []), "waits", WAIT_FIELDS, WAIT_STATES, "open", problems)
    promises = _check_entries(data.get("promises", []), "promises", PROMISE_FIELDS, PROMISE_STATES, "open", problems)
    if channels is not None:
        known = set(channels)
        for name in cursors:
            if name not in known:
                problems.append("cursors.%s: no channel of that name in the inventory" % name)
    _walk_secrets(data, "state", problems)
    return {
        "valid": not problems,
        "project": data.get("project") if isinstance(data.get("project"), str) else None,
        "cursors": len(cursors),
        "heads": head_count,
        "openWaits": sum(1 for w in waits if _status(w, "open") in ("open", "paused")),
        "openPromises": sum(1 for p in promises if _status(p, "open") == "open"),
        "problems": problems,
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Check an observer's channel inventory.")
    sub = parser.add_subparsers(dest="command", required=True)
    check_cmd = sub.add_parser("check", help="validate docs/observer/channels.md and count what is watched")
    check_cmd.add_argument("path")
    check_cmd.add_argument("--json", action="store_true")
    check_cmd.add_argument("--today", help="YYYY-MM-DD, for a reproducible check")
    template_cmd = sub.add_parser("template", help="print an empty inventory")
    template_cmd.add_argument("--project", default="example-app")
    state_cmd = sub.add_parser("state", help="validate docs/observer/state.json")
    state_cmd.add_argument("path")
    state_cmd.add_argument("--channels", help="the inventory, to check that every cursor names one of its channels")
    state_cmd.add_argument("--json", action="store_true")
    state_cmd.add_argument("--now", help="an ISO date-time with its zone, for a reproducible check")
    state_template_cmd = sub.add_parser("state-template", help="print an empty state file")
    state_template_cmd.add_argument("--project", default="example-app")
    args = parser.parse_args(list(argv))

    if args.command in ("template", "state-template") and \
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.project):
        print("error: --project takes a plain name", file=sys.stderr)
        return 2
    if args.command == "state-template":
        sys.stdout.write(json.dumps(dict(STATE_TEMPLATE, project=args.project), indent=2) + "\n")
        return 0
    if args.command == "state":
        return _state_main(args)

    if args.command == "template":
        sys.stdout.write(TEMPLATE.format(project=args.project))
        return 0

    try:
        today = datetime.date.fromisoformat(args.today) if args.today else None
    except ValueError:
        print("error: --today takes YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        text = Path(args.path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("error: cannot read %s: %s" % (args.path, exc.__class__.__name__), file=sys.stderr)
        return 2
    report = check(text, today)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("%s: %d of %d named channels connected (local %d, remote %d); missing %d, blocked %d, not-applicable %d"
              % (report["project"] or args.path, report["connected"], report["named"],
                 report["connectedByPlacement"]["local"], report["connectedByPlacement"]["remote"],
                 report["states"]["missing"], report["states"]["blocked"], report["states"]["not-applicable"]))
        for problem in report["problems"]:
            print("problem: %s" % problem)
    return 0 if report["valid"] else 1


def _state_main(args: argparse.Namespace) -> int:
    now = None
    if args.now:
        now = _parse_time(args.now)
        if now is None:
            print("error: --now takes an ISO date-time with its zone", file=sys.stderr)
            return 2
    try:
        text = Path(args.path).read_text(encoding="utf-8")
        channels = None
        if args.channels:
            _, rows, _ = parse(Path(args.channels).read_text(encoding="utf-8"))
            channels = [row.get("channel", "") for row in rows]
    except (OSError, UnicodeDecodeError) as exc:
        print("error: cannot read a file: %s" % exc.__class__.__name__, file=sys.stderr)
        return 2
    report = check_state(text, channels, now)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("%s: %d cursors, %d checked heads, %d open waits, %d open promises"
              % (report["project"] or args.path, report["cursors"], report["heads"], report["openWaits"],
                 report["openPromises"]))
        for problem in report["problems"]:
            print("problem: %s" % problem)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
