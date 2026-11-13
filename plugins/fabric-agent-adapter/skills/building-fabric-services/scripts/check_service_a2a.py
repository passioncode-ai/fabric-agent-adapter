#!/usr/bin/env python3
"""The A2A rules of the probe (FAA-10): what a service that declares `surfaces.a2a` (DEC-0122) serves, read from the
outside. `a2a_rules(wk, origin, ...)` returns (rule, verdict, evidence) rows, verdicts PASS, FAIL or NOT_RUN:

- `a2a.surface`: `surfaces.a2a` is the schema's (`fabric_a2a.a2a_view`); NOT_RUN when the service declares none;
- `a2a.card`: the card at `surfaces.a2a.path` answers 200 with a JSON object `agent_card_findings` finds nothing in;
- `a2a.interface`: the card names an A2A 1.0 JSON-RPC interface on the service origin (local) or on https (remote);
- `a2a.task-not-found`: `GetTask` of an id nobody made answers JSON-RPC -32001 (TaskNotFound);
- `a2a.cancel-not-found`: `CancelTask` of that id answers -32001 too;
- `a2a.method-not-found`: an unknown method answers -32601;
- `a2a.task-states`: with `probe_text` (a message the service names as safe to send), `SendMessage` answers a message,
  or a task whose state is an A2A 1.0 state that `GetTask` reads back and `CancelTask` moves to TASK_STATE_CANCELED
  (or refuses with -32002 when it has already ended); NOT_RUN without one, since a message may start real work.

An interface that answers HTTP 401 makes the binding rules NOT_RUN with the reason: it takes its own key, never the
descriptor's token (DEC-0122 item 3); give the key through `--key-env` under `use_secret.py run`. It is a command of
its own beside check_service.py, whose `a2a.card` never calls the card's interfaces (D5); the two say one verdict for the
card: an unreadable `surfaces.a2a`, and a remote card that answers 401 or 403, are NOT_RUN, never a failure (DEC-0122
item 2). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_a2a import A2A_PROTOCOL_VERSION, a2a_view, agent_card_findings  # noqa: E402
from fabric_http import HttpError, request as http_request  # noqa: E402

STATES = ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED",
          "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_REJECTED", "TASK_STATE_AUTH_REQUIRED")
Row = Tuple[str, str, str]
Fetch = Callable[[str, str, Mapping[str, str], Optional[Dict[str, Any]]], Tuple[int, Any]]


def http_fetch(method: str, url: str, headers: Mapping[str, str], body: Optional[Dict[str, Any]]) -> Tuple[int, Any]:
    """One bounded request (10 s, 1 MiB, no retry); the answer's JSON or None."""
    response = http_request(method, url, headers=dict(headers), body=body, deadline_s=10, retries=0, max_bytes=1 << 20)
    try:
        return response.status, response.json()
    except ValueError:
        return response.status, None


def _rpc(fetch: Fetch, url: str, headers: Mapping[str, str], method: str, params: Dict[str, Any]) -> Tuple[int, Any]:
    return fetch("POST", url, dict(headers, **{"A2A-Version": A2A_PROTOCOL_VERSION, "Content-Type": "application/json"}),
                 {"jsonrpc": "2.0", "id": secrets.token_hex(4), "method": method, "params": params})


def _code(answer: Any) -> Optional[int]:
    return answer["error"].get("code") if isinstance(answer, dict) and isinstance(answer.get("error"), dict) else None


def a2a_rules(wk: Any, origin: str, *, fetch: Fetch = http_fetch, headers: Optional[Mapping[str, str]] = None,
              remote: bool = False, descriptor_header: str = "Authorization", probe_text: Optional[str] = None) -> List[Row]:
    """The A2A rows for one service read at `origin`; `headers` carries the interface's own key, never the token."""
    rows: List[Row] = []
    view = a2a_view(wk)
    if not view["declared"]:
        return [("a2a.surface", "NOT_RUN", "the service declares no surfaces.a2a")]
    if not view["valid"]:  # as check_service_rules.a2a_card_verdict: a host does not know where the card is
        return [("a2a.surface", "NOT_RUN", "surfaces.a2a is not readable (well-known.a2a): "
                 + "; ".join(f["message"] for f in view["findings"]))]
    rows.append(("a2a.surface", "PASS", "surfaces.a2a at %s" % view["path"]))
    try:
        status, card = fetch("GET", origin.rstrip("/") + view["path"], {"Accept": "application/json"}, None)
    except (HttpError, OSError) as exc:
        return rows + [("a2a.card", "FAIL", "the card did not answer: %s" % exc)]
    if remote and status in (401, 403):
        return rows + [("a2a.card", "NOT_RUN", "HTTP %d: a card that is not open, gated by the service's own credentials "
                        "or an identity proxy; a refusal is not nonconformance (DEC-0122 item 2)" % status)]
    if status != 200 or not isinstance(card, dict):
        return rows + [("a2a.card", "FAIL", "the card answered HTTP %d%s" % (status, "" if isinstance(card, dict) else ", not a JSON object"))]
    findings = agent_card_findings(card, origin=None if remote else origin.rstrip("/"), remote=remote,
                                   descriptor_header=descriptor_header)
    rows.append(("a2a.card", "FAIL" if findings else "PASS", "; ".join(f["message"] for f in findings) or "%d skills" % len(card.get("skills") or [])))
    url = next((i.get("url") for i in card.get("supportedInterfaces") or [] if isinstance(i, dict)
                and i.get("protocolBinding") == "JSONRPC" and i.get("protocolVersion") == A2A_PROTOCOL_VERSION
                and isinstance(i.get("url"), str)), None)
    if url is None:
        return rows + [("a2a.interface", "FAIL", "the card names no A2A %s JSON-RPC interface" % A2A_PROTOCOL_VERSION)]
    rows.append(("a2a.interface", "PASS", url))
    sent = dict(headers or {})
    nobody = "probe-" + secrets.token_hex(12)
    checks = (("a2a.task-not-found", "GetTask", {"id": nobody}, -32001), ("a2a.cancel-not-found", "CancelTask", {"id": nobody}, -32001),
              ("a2a.method-not-found", "ProbeNoSuchMethod", {}, -32601))
    for rule, method, params, want in checks:
        try:
            status, answer = _rpc(fetch, url, sent, method, params)
        except (HttpError, OSError) as exc:
            rows.append((rule, "FAIL", "%s did not answer: %s" % (method, exc)))
            continue
        if status in (401, 403):
            rows.append((rule, "NOT_RUN", "the interface answered HTTP %d: it takes its own key (DEC-0122 item 3); pass it with --key-env" % status))
        else:
            got = _code(answer)
            rows.append((rule, "PASS" if got == want else "FAIL", "%s answered %s, A2A 1.0 says %d" % (method, got if got is not None else "HTTP %d" % status, want)))
    rows.append(_task_states(fetch, url, sent, probe_text))
    return rows


def _task_states(fetch: Fetch, url: str, headers: Mapping[str, str], probe_text: Optional[str]) -> Row:
    if not probe_text:
        return ("a2a.task-states", "NOT_RUN", "no probe message: a message may start real work; pass --probe-text the service names as safe")
    message = {"role": "ROLE_USER", "parts": [{"text": probe_text}], "messageId": "probe-" + secrets.token_hex(8)}
    status, answer = _rpc(fetch, url, headers, "SendMessage", {"message": message})
    result = answer.get("result") if isinstance(answer, dict) else None
    if status != 200 or not isinstance(result, dict) or not ({"task", "message"} & set(result)):
        return ("a2a.task-states", "FAIL", "SendMessage answered neither a task nor a message (HTTP %d, code %s)" % (status, _code(answer)))
    if "message" in result:
        return ("a2a.task-states", "PASS", "SendMessage answered a message with no task")
    task = result["task"]
    if not isinstance(task, dict) or (task.get("status") or {}).get("state") not in STATES:
        return ("a2a.task-states", "FAIL", "the task's state is not an A2A 1.0 TaskState")
    read = _rpc(fetch, url, headers, "GetTask", {"id": task.get("id")})[1]
    if not isinstance(read, dict) or ((read.get("result") or {}).get("status") or {}).get("state") not in STATES:
        return ("a2a.task-states", "FAIL", "GetTask did not read the task back")
    cancelled = _rpc(fetch, url, headers, "CancelTask", {"id": task.get("id")})[1]
    state = (((cancelled or {}).get("result") or {}).get("status") or {}).get("state") if isinstance(cancelled, dict) else None
    if state == "TASK_STATE_CANCELED" or _code(cancelled) == -32002:
        return ("a2a.task-states", "PASS", "SendMessage, GetTask and CancelTask agree")
    return ("a2a.task-states", "FAIL", "CancelTask answered neither TASK_STATE_CANCELED nor -32002")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("origin", help="the service origin, http://127.0.0.1:<port> or its https origin")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--key-env", help="an environment variable holding the A2A interface's own key (use_secret.py run fills it)")
    parser.add_argument("--header", default="Authorization")
    parser.add_argument("--scheme", default="Bearer")
    parser.add_argument("--probe-text")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status, wk = http_fetch("GET", args.origin.rstrip("/") + "/.well-known/fabric-service", {"Accept": "application/json"}, None)
    headers: Dict[str, str] = {}
    if args.key_env:
        value = os.environ.get(args.key_env)
        if not value:
            print("%s is empty: run under use_secret.py run" % args.key_env, file=sys.stderr)
            return 2
        headers[args.header] = "%s %s" % (args.scheme, value) if args.scheme else value
    rows = a2a_rules(wk if status == 200 else None, args.origin, headers=headers, remote=args.remote, probe_text=args.probe_text)
    if args.json:
        print(json.dumps([{"rule": r, "verdict": v, "evidence": e} for r, v, e in rows], indent=1))
    else:
        for r, v, e in rows:
            print("%-8s %-22s %s" % (v, r, e))
    return 1 if any(v == "FAIL" for _, v, _ in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
