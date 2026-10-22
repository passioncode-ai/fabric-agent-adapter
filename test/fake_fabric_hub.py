#!/usr/bin/env python3
"""A fake Fabric hub for the board kits' tests (FAA-12b): `hub.json` and its door token in a temporary registry root,
the door's and a binding's tools (stateless MCP over HTTP, as Fabric's `agentSurface.handleExternal` serves them), and
board sessions (`fabric.board.join`: a one-session bearer, spent by one MCP initialize, then `mcp-session-id`) whose
server has the seventeen `com.*` tools and nothing else.

The board is a small model of Fabric's migration 87 (`supabase/migrations/20261012000104_project_board_responders.sql`)
built for tests, not a second implementation: one slot per (Project, capability) with a generation that only grows,
one live attempt per request, the fence checked in Fabric's order (request, authority, idempotency, digest, generation
and holder, attempt, leases, revision), receipts kept per (operation, key), the replacement effects and the release on
the session's DELETE. Its clock is a number the test moves (`advance`), never the wall clock. Knobs the tests turn:
`fail_next[tool] = code` (one refusal), `drop_next[tool]` (the call commits but its answer is lost), `down` (every call
503), `omit_transferred` (a board pinned before DEC-0078), `revoked` (the operator revoked the grant), `holds` (an
operator's hold, DEC-0079: `{threads, projects, slots: [{project, capability}]}`, refused `held` at call time and named
in `com.status`), `lift_holds_after` (a tool name: the board lifts every hold right after it refuses that tool
`held` once, so a test waits on the call itself, never on the wall clock).

Python tests use it in-process (`FakeHub(root)`); the Node tests run it as a process (`python3 fake_fabric_hub.py
serve --root DIR`), which prints one JSON line `{port, control}` and takes test commands as JSON on POST /_control (`forget-sessions` ends every board session without its DELETE, so
the slots it held lapse on their own).
Standard library only."""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import socketserver
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

PROJECT = "3f2a6b1c-0d4e-4f5a-8b6c-7d8e9f0a1b2c"
OTHER_PROJECT = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
LEASE = 60.0
#: What a board session (`fabric.board.join`) is served after Fabric's fix round narrowed it to respond scope: never
#: com.submit, com.cancel, com.read_ack or com.directory (those belong to a Project session).
RESPOND_TOOLS = {"com.status", "com.list", "com.get", "com.reply", "com.enroll", "com.claim", "com.renew", "com.accept",
                 "com.progress", "com.effect_begin", "com.complete", "com.reconcile", "com.responder_replace"}
BASE_TIME = 1_791_892_800.0  # 2026-10-13T08:00:00Z


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(op: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(("fabric-project-comms/0.1\0%s\0%s" % (op, canonical(value))).encode()).hexdigest()


def iso(t: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % int((t % 1) * 1000)


def oid(prefix: str) -> str:
    return "%s_%s" % (prefix, secrets.token_hex(6))


def refusal(code: str, message: str = "refused", retryable: bool = False) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


class Board:
    def __init__(self, project: str = PROJECT):
        self.project = project
        self.now = BASE_TIME
        self.epoch = 1
        self.slots: Dict[str, Dict[str, Any]] = {}
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.order: List[str] = []
        self.receipts: Dict[Tuple[str, int, str], Tuple[str, Dict[str, Any]]] = {}
        self.notes: List[Dict[str, Any]] = []
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.fail_next: Dict[str, str] = {}
        self.drop_next: Dict[str, int] = {}
        self.omit_transferred = False
        self.revoked = False
        self.status_protocol = "fabric-project-comms/0.1"
        self.status_epoch = True  # Fabric before the fix round tells a board session no epoch
        self.replies: List[Dict[str, Any]] = []
        self.directory_page: Optional[Dict[str, Any]] = None
        self.holds: Dict[str, Any] = {}
        self.lift_holds_after: Optional[str] = None

    # -- test setup ----------------------------------------------------------------------------------------------
    def queue(self, capability: str, text: str = "Render the attached composition.", sender: str = OTHER_PROJECT,
              message_digest: Optional[str] = None) -> str:
        rid = oid("req")
        mid = oid("msg")
        body = {"text": text}
        d = digest("com.submit", {"body": body, "request": {"target": self.project, "capability": capability}})
        self.requests[rid] = {"id": rid, "message": mid, "capability": capability, "state": "queued", "effect": "not_started",
                              "revision": 1, "digest": d, "message_digest": message_digest or d, "body": body,
                              "sender": sender, "attempt": None, "thread": oid("thr")}
        self.order.append(rid)
        return rid

    def advance(self, seconds: float) -> None:
        self.now += seconds

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _slot(self, capability: str) -> Dict[str, Any]:
        return self.slots.setdefault(capability, {"generation": 0, "holder": None, "lease": 0.0})

    def _slot_json(self, capability: str) -> Dict[str, Any]:
        s = self._slot(capability)
        return {"project": self.project, "capability": capability, "generation": s["generation"], "leaseExpiresAt": iso(s["lease"])}

    def _req_json(self, r: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": r["id"], "state": r["state"], "effect": r["effect"], "revision": r["revision"]}

    def _attempt_json(self, r: Dict[str, Any]) -> Dict[str, Any]:
        a = r["attempt"]
        return {"id": a["id"], "generation": a["generation"], "digest": r["digest"], "leaseExpiresAt": iso(a["lease"])}

    def _move(self, r: Dict[str, Any], state: str, effect: Optional[str] = None) -> None:
        r["state"] = state
        if effect:
            r["effect"] = effect
        r["revision"] += 1

    def _gate(self, op: str, args: Dict[str, Any], d: str, store: bool) -> Optional[Dict[str, Any]]:
        idem = args.get("idempotency") or {}
        if not isinstance(idem, dict) or not isinstance(idem.get("key"), str) or not isinstance(idem.get("epoch"), int):
            return refusal("invalid_arguments", "idempotency is required")
        if idem["epoch"] != self.epoch:
            return refusal("idempotency_window_expired", "that epoch is closed")
        if not store:
            return None
        seen = self.receipts.get((op, idem["epoch"], idem["key"]))
        if seen:
            if seen[0] != d:
                return refusal("idempotency_conflict", "another call under that key")
            return dict(seen[1], repeated=True)
        return None

    def _store(self, op: str, args: Dict[str, Any], d: str, receipt: Dict[str, Any]) -> Dict[str, Any]:
        idem = args["idempotency"]
        self.receipts[(op, idem["epoch"], idem["key"])] = (d, receipt)
        return receipt

    def _holder(self, session: str, capability: str) -> Optional[Dict[str, Any]]:
        s = self._slot(capability)
        if s["holder"] != session:
            return refusal("fenced", "This session does not hold the responder slot; call com.enroll first.")
        if self.revoked:
            return refusal("authority_changed", "The operator's grant was revoked.")
        if s["lease"] <= self.now:
            return refusal("lease_expired", "Your responder lease lapsed; call com.enroll again.")
        return None

    def _replacement(self, capability: str, generation: int, returning_claimed: bool, transfer: Optional[List[str]] = None,
                     session: Optional[str] = None) -> List[Dict[str, Any]]:
        moved = []
        for rid in self.order:
            r = self.requests[rid]
            if r["capability"] != capability:
                continue
            a = r["attempt"]
            if r["state"] == "in_progress" and a and a["generation"] < generation:
                self._move(r, "outcome_unknown", "unknown")
                r["attempt"] = None
            elif r["state"] == "claimed" and returning_claimed:
                self._move(r, "queued")
                r["attempt"] = None
            elif r["state"] == "accepted" and transfer and rid in transfer:
                r["attempt"] = {"id": oid("att"), "generation": generation, "session": session, "lease": self.now + LEASE}
                moved.append({"request": rid, "revision": r["revision"], "attempt": self._attempt_json(r)})
        return moved

    # DEC-0079's matrix, from the board's own records (never the payload): what each tool may be refused for.
    HOLD_SCOPES = {"com.submit": ("thread",), "com.reply": ("thread",), "com.enroll": ("project", "slot"),
                   "com.responder_replace": ("project", "slot"), "com.claim": ("thread", "project", "slot"),
                   "com.accept": ("thread", "project", "slot"), "com.effect_begin": ("thread", "project", "slot")}

    def _slot_held(self, capability: Any) -> bool:
        h = self.holds or {}
        return self.project in (h.get("projects") or []) or any(
            s.get("project") == self.project and s.get("capability") == capability for s in h.get("slots") or [])

    def _held(self, tool: str, args: Dict[str, Any]) -> bool:
        scopes = self.HOLD_SCOPES.get(tool)
        if not scopes or not self.holds:
            return False
        fence = args.get("fence") if isinstance(args.get("fence"), dict) else {}
        r = self.requests.get(fence.get("request") or args.get("request"))
        capability = r["capability"] if r else args.get("capability")
        if r and "thread" in scopes and r["thread"] in (self.holds.get("threads") or []):
            return True
        if tool == "com.claim" and not r:
            # a plain claim is refused for a held slot; a held thread's request is simply not handed out
            return self._slot_held(capability)
        return ("project" in scopes or "slot" in scopes) and self._slot_held(capability)

    def _claimable(self, r: Dict[str, Any]) -> bool:
        return r["thread"] not in ((self.holds or {}).get("threads") or [])

    # -- the tools ---------------------------------------------------------------------------------------------
    def call(self, session: str, capabilities: List[str], tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((tool, args))
        if tool in self.fail_next:
            code = self.fail_next.pop(tool)
            return refusal(code, "a refusal the test asked for", retryable=code == "held")
        if self._held(tool, args):
            if tool == self.lift_holds_after:
                self.holds, self.lift_holds_after = {}, None
            return refusal("held", "The operator holds this work; try again later.", retryable=True)
        handler = getattr(self, "op_" + tool.split(".", 1)[1], None)
        if handler is None:
            return refusal("unsupported_capability", "This board does not serve %s." % tool)
        return handler(session, capabilities, args)

    def op_status(self, session, caps, args):
        responders = []
        for cap in caps:
            s = self._slot(cap)
            live = s["holder"] is not None and s["lease"] > self.now
            entry = {"capability": cap, "state": "active" if live else ("stale" if s["holder"] else "absent"), "generation": s["generation"]}
            if self.holds:
                entry["held"] = self._slot_held(cap)
            if s["holder"]:
                entry["leaseExpiresAt"], entry["provenance"] = iso(s["lease"]), "trusted"
            responders.append(entry)
        out = {"protocol": self.status_protocol, "board": {"state": "ready"}, "project": self.project, "responders": responders,
               "transport": {"telegram": "off"}, "unread": 0}
        if self.status_epoch:
            out["idempotency"] = {"epoch": self.epoch}
        return out

    def op_directory(self, session, caps, args):
        if self.directory_page is not None:
            return self.directory_page
        return {"protocol": "fabric-project-comms/0.1", "snapshot": {"readAt": iso(self.now)},
                "projects": [{"id": OTHER_PROJECT, "name": "Requester", "capabilities": []}], "cursor": None}

    def op_get(self, session, caps, args):
        for r in self.requests.values():
            if r["message"] == args.get("message"):
                return {"id": r["message"], "thread": r["thread"], "kind": "request",
                        "sender": {"project": r["sender"], "principal": {"kind": "agent", "id": "s-1", "provenance": "trusted"}},
                        "at": iso(BASE_TIME), "digest": r["message_digest"], "body": r["body"],
                        "request": {"id": r["id"], "target": self.project, "capability": r["capability"], "state": r["state"],
                                    "effect": r["effect"], "revision": r["revision"]}}
        return refusal("not_authorized", "This Project cannot read that message.")

    def op_enroll(self, session, caps, args):
        cap = args.get("capability")
        if cap not in caps:
            return refusal("not_authorized", "Ask the operator to let you answer %s requests for this project." % cap)
        if self.revoked:
            return refusal("authority_changed", "The operator's grant was revoked.")
        d = digest("com.enroll", args)
        g = self._gate("com.enroll", args, d, True)
        if g:
            return g
        s = self._slot(cap)
        if s["holder"] == session:
            s["lease"] = self.now + LEASE
        elif s["holder"] is not None and s["lease"] > self.now:
            return refusal("fenced", "Another responder holds this slot; use com.responder_replace.")
        else:
            s["generation"] += 1
            s["holder"], s["lease"] = session, self.now + LEASE
            self._replacement(cap, s["generation"], returning_claimed=False)
        return self._store("com.enroll", args, d, {"ok": True, "repeated": False, "slot": self._slot_json(cap)})

    def op_claim(self, session, caps, args):
        cap = args.get("capability")
        bad = self._holder(session, cap)
        if bad:
            return bad
        d = digest("com.claim", args)
        g = self._gate("com.claim", args, d, True)
        if g:
            return g
        pick = None
        if "request" in args:
            r = self.requests.get(args["request"])
            if not r or r["capability"] != cap:
                return refusal("not_authorized", "This Project cannot claim that request.")
            if r["state"] == "accepted":
                return refusal("invalid_transition", "This request is accepted; it cannot be claimed.")
            pick = r
        else:
            for rid in self.order:
                r = self.requests[rid]
                lapsed = r["state"] == "claimed" and (r["attempt"] is None or r["attempt"]["lease"] <= self.now)
                if r["capability"] == cap and (r["state"] == "queued" or lapsed) and self._claimable(r):
                    pick = r
                    break
        if pick is None:
            return {"ok": True, "repeated": False}
        s = self._slot(cap)
        self._move(pick, "claimed")
        pick["attempt"] = {"id": oid("att"), "generation": s["generation"], "session": session, "lease": self.now + LEASE}
        s["lease"] = self.now + LEASE
        return self._store("com.claim", args, d, {"ok": True, "repeated": False, "message": pick["message"],
                                                    "request": self._req_json(pick), "attempt": self._attempt_json(pick)})

    def _fence(self, session: str, op: str, args: Dict[str, Any], store: bool):
        f = args.get("fence") or {}
        r = self.requests.get(f.get("request"))
        if r is None:
            return None, refusal("not_authorized", "This Project cannot act on that request.")
        if self.revoked:
            return None, refusal("authority_changed", "The operator's grant was revoked.")
        d = digest(op, args)
        g = self._gate(op, f, d, store)
        if g:
            return None, g
        s = self._slot(r["capability"])
        if f.get("digest") != r["digest"]:
            return None, refusal("digest_conflict", "The fence names another digest than this request's.")
        if f.get("generation") != s["generation"] or s["holder"] != session:
            return None, refusal("fenced", "A newer responder holds this slot; this call was not committed.")
        a = r["attempt"]
        if not a or a["id"] != f.get("attempt") or a.get("session") != session:
            return None, refusal("fenced", "This attempt is no longer the request's; this call was not committed.")
        if s["lease"] <= self.now or a["lease"] <= self.now:
            return None, refusal("lease_expired", "Your lease lapsed; this call was not committed.")
        if "expectedRevision" in f and f["expectedRevision"] != r["revision"]:
            return None, refusal("revision_conflict", "The request is at another revision.")
        return (r, d), None

    def _extend(self, r):
        r["attempt"]["lease"] = self.now + LEASE
        self._slot(r["capability"])["lease"] = self.now + LEASE

    def op_renew(self, session, caps, args):
        got, bad = self._fence(session, "com.renew", args, store=False)
        if bad:
            return bad
        r, _ = got
        self._extend(r)
        return {"ok": True, "repeated": False, "slot": self._slot_json(r["capability"]), "attempt": self._attempt_json(r)}

    def op_progress(self, session, caps, args):
        got, bad = self._fence(session, "com.progress", args, store=False)
        if bad:
            return bad
        r, _ = got
        self._extend(r)
        out = {"ok": True, "repeated": False, "slot": self._slot_json(r["capability"]), "attempt": self._attempt_json(r)}
        if "note" in args:
            key = (r["attempt"]["id"], args["fence"]["idempotency"]["key"])
            prior = [n for n in self.notes if n["key"] == key]
            if prior:
                out.update(message=prior[0]["message"], repeated=True)
            else:
                mid = oid("msg")
                self.notes.append({"key": key, "message": mid, "text": args["note"]["text"]})
                out["message"] = mid
        return out

    def op_reply(self, session, caps, args):
        if "fence" not in args or "replyTo" in args or "idempotency" in args:
            return refusal("not_authorized", "A board session replies only in the responder's fenced form.")
        got, bad = self._fence(session, "com.reply", args, store=True)
        if bad:
            return bad
        if isinstance(got, dict):
            return got
        r, d = got
        mid = oid("msg")
        self.replies.append({"request": r["id"], "message": mid, "body": args.get("body"), "artifacts": args.get("artifacts")})
        return self._store("com.reply", args["fence"], d, {"ok": True, "repeated": False, "message": mid, "thread": r["thread"], "at": iso(self.now)})

    def op_accept(self, session, caps, args):
        got, bad = self._fence(session, "com.accept", args, store=True)
        if bad:
            return bad
        if isinstance(got, dict):
            return got
        r, d = got
        if r["state"] != "claimed":
            return refusal("invalid_transition", "This request is not claimed.")
        self._move(r, "accepted")
        self._extend(r)
        return self._store("com.accept", args["fence"], d, {"ok": True, "repeated": False, "request": self._req_json(r)})

    def op_effect_begin(self, session, caps, args):
        got, bad = self._fence(session, "com.effect_begin", args, store=True)
        if bad:
            return bad
        r, d = got
        if r["state"] != "accepted":
            return refusal("invalid_transition", "This request is not accepted.")
        self._move(r, "in_progress", "started")
        return self._store("com.effect_begin", args["fence"], d, {"ok": True, "repeated": False, "request": self._req_json(r)})

    def op_complete(self, session, caps, args):
        got, bad = self._fence(session, "com.complete", args, store=True)
        if bad:
            return bad
        r, d = got
        outcome = args.get("outcome") or {}
        if r["state"] == "in_progress" and outcome.get("observed") is not True:
            return refusal("observation_required", "After an effect began, only an observed result settles it.")
        if r["state"] not in ("accepted", "in_progress"):
            return refusal("invalid_transition", "This request cannot complete.")
        effect = r["effect"] if r["state"] == "accepted" else ("succeeded_observed" if outcome["state"] == "completed" else "failed_observed")
        self._move(r, outcome["state"], effect)
        r["outcome"] = outcome
        r["attempt"] = None
        return self._store("com.complete", args["fence"], d, {"ok": True, "repeated": False, "request": self._req_json(r)})

    def op_reconcile(self, session, caps, args):
        r = self.requests.get(args.get("request"))
        if r is None:
            return refusal("not_authorized", "This Project cannot act on that request.")
        bad = self._holder(session, r["capability"])
        if bad:
            return bad
        d = digest("com.reconcile", args)
        g = self._gate("com.reconcile", args, d, True)
        if g:
            return g
        if args.get("digest") != r["digest"]:
            return refusal("digest_conflict", "That digest is not this request's.")
        if r["state"] != "outcome_unknown":
            return refusal("invalid_transition", "This request's outcome is not unknown.")
        outcome = args["outcome"]
        self._move(r, outcome["state"], "succeeded_observed" if outcome["state"] == "completed" else "failed_observed")
        r["outcome"] = outcome
        return self._store("com.reconcile", args, d, {"ok": True, "repeated": False, "request": self._req_json(r)})

    def op_responder_replace(self, session, caps, args):
        cap = args.get("capability")
        if cap not in caps:
            return refusal("not_authorized", "Ask the operator to let you answer %s requests for this project." % cap)
        d = digest("com.responder_replace", args)
        g = self._gate("com.responder_replace", args, d, True)
        if g:
            return g
        s = self._slot(cap)
        if args.get("expectedGeneration") != s["generation"]:
            return refusal("revision_conflict", "The slot is at another generation.")
        transfer = (args.get("transfer") or {}).get("requests") or []
        for rid in transfer:
            r = self.requests.get(rid)
            if not r or r["capability"] != cap or r["state"] != "accepted":
                return refusal("invalid_arguments", "A transferred request must be an accepted request of this Project and capability.")
        s["generation"] += 1
        s["holder"], s["lease"] = session, self.now + LEASE
        moved = self._replacement(cap, s["generation"], returning_claimed=True, transfer=transfer, session=session)
        receipt: Dict[str, Any] = {"ok": True, "repeated": False, "slot": self._slot_json(cap)}
        if moved and not self.omit_transferred:
            receipt["transferred"] = moved
        return self._store("com.responder_replace", args, d, receipt)

    def release(self, session: str) -> None:
        for s in self.slots.values():
            if s["holder"] == session:
                s["holder"], s["lease"] = None, 0.0
        for r in self.requests.values():
            if r["attempt"] and r["attempt"].get("session") == session:
                r["attempt"]["lease"] = 0.0
                r["attempt"]["session"] = None


class FakeHub:
    """hub.json + door token in `root`, an HTTP server on 127.0.0.1, one Board."""

    def __init__(self, root: Path, project: str = PROJECT, capabilities: Tuple[str, ...] = ("video.render",),
                 agent_id: str = "example-agent", pid: Optional[int] = None):
        self.root = Path(root)
        self.board = Board(project)
        self.capabilities = list(capabilities)
        self.agent_id = agent_id
        self.door = secrets.token_urlsafe(32)
        self.credential = secrets.token_urlsafe(32)
        self.down = False
        self.grant = True
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.bindings_seen: List[str] = []
        self.door_calls: List[Tuple[str, Dict[str, Any]]] = []
        self.access_requests: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, status: int, body: Any = None, headers: Optional[Dict[str, str]] = None) -> None:
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_DELETE(self) -> None:  # noqa: N802
                with hub.lock:
                    token = (self.headers.get("authorization") or "")[7:]
                    st = hub.sessions.get(token)
                    if st and st["mcp"] == self.headers.get("mcp-session-id"):
                        hub.board.release(st["id"])
                        del hub.sessions[token]
                        self._send(200)
                    else:
                        self._send(401, {"error": "unknown or revoked credential"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                if self.path == "/_control":
                    with hub.lock:
                        self._send(200, hub.control(json.loads(raw or b"{}")))
                    return
                with hub.lock:
                    if hub.down:
                        self._send(503, {"error": "hub down"})
                        return
                    if self.path != "/mcp":
                        self._send(404)
                        return
                    token = (self.headers.get("authorization") or "")
                    token = token[7:] if token.startswith("Bearer ") else ""
                    body = json.loads(raw or b"{}")
                    status, answer, headers = hub.dispatch(token, body, self.headers.get("mcp-session-id"))
                    drop = answer is not None and answer.get("_drop")
                if drop:
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                self._send(status, answer, headers)

        class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def server_bind(self) -> None:  # no resolver between bind and listen
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = self.server_address[:2]

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.publish(pid if pid is not None else os.getpid())

    # -- hub.json ------------------------------------------------------------------------------------------------
    def publish(self, pid: int, **override: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        token_file = self.root / "hub-door-token"
        token_file.write_text(self.door)
        os.chmod(token_file, 0o600)
        doc = {"protocol": "fabric-hub/0.1", "origin": "http://127.0.0.1:%d" % self.port, "mcp": "/mcp",
               "doorTokenFile": str(token_file), "pid": pid, "startedAt": iso(BASE_TIME), "features": ["session-hooks/1"]}
        doc.update(override)
        (self.root / "hub.json").write_text(json.dumps(doc, indent=2))
        os.chmod(self.root / "hub.json", 0o600)

    def withdraw(self) -> None:
        for name in ("hub.json", "hub-door-token"):
            try:
                (self.root / name).unlink()
            except FileNotFoundError:
                pass

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # -- MCP --------------------------------------------------------------------------------------------------------
    @staticmethod
    def _result(rpc_id: Any, value: Dict[str, Any], structured: bool) -> Dict[str, Any]:
        result: Dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(value)}]}
        if structured:
            result["structuredContent"] = value
        if "error" in value:
            result["isError"] = True
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def dispatch(self, token: str, body: Dict[str, Any], mcp_session: Optional[str]):
        method, rpc_id, params = body.get("method"), body.get("id"), body.get("params") or {}
        st = self.sessions.get(token)
        if st is not None:  # a board session
            if method == "initialize":
                if st["mcp"] is not None:
                    return 401, {"error": "credential already claimed by an initialised session"}, None
                st["mcp"] = secrets.token_hex(16)
                return 200, {"jsonrpc": "2.0", "id": rpc_id, "result": {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                             "capabilities": {"tools": {}}, "serverInfo": {"name": "fabric", "version": "0.0.0-test"}}}, {"mcp-session-id": st["mcp"]}
            if st["mcp"] is None or mcp_session != st["mcp"]:
                return 401, {"error": "mcp-session-id does not match this credential"}, None
            if method == "notifications/initialized":
                return 202, None, None
            if method != "tools/call":
                return 200, {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "unknown method"}}, None
            tool = params.get("name", "")
            if tool not in RESPOND_TOOLS:
                return 200, {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Tool %s not found" % tool}}, None
            answer = self.board.call(st["id"], st["capabilities"], tool, params.get("arguments") or {})
            if self.board.drop_next.get(tool):
                self.board.drop_next[tool] -= 1
                return 200, {"_drop": True}, None
            return 200, self._result(rpc_id, answer, structured=False), None
        if token == self.door:
            principal = "door"
        elif token == self.credential:
            principal = "binding"
            self.bindings_seen.append(params.get("name", method))
        else:
            return 401, {"error": "unknown or revoked credential"}, None
        if method != "tools/call":
            return 200, {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "stateless hub: tools/call only"}}, None
        tool, args = params.get("name"), params.get("arguments") or {}
        self.door_calls.append((tool, args))
        return 200, self._result(rpc_id, self.hub_tool(principal, tool, args), structured=True), None

    def hub_tool(self, principal: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "fabric.access.request":
            rid = "req-%s" % secrets.token_hex(4)
            poll = secrets.token_urlsafe(32)
            self.access_requests[rid] = {"poll": poll, "status": "pending", "args": args, "collected": False}
            return {"requestId": rid, "status": "pending", "expiresAt": iso(BASE_TIME + 600), "pollSecret": poll, "note": "asked"}
        if tool == "fabric.access.status":
            r = self.access_requests.get(args.get("requestId"))
            if not r or (principal == "door" and args.get("pollSecret") != r["poll"]):
                return {"error": {"code": "unknown-request", "message": "unknown request"}}
            out = {"requestId": args["requestId"], "status": r["status"], "expiresAt": iso(BASE_TIME + 600), "note": "read"}
            if r["status"] == "allowed" and not r["collected"]:
                r["collected"] = True
                out.update(credential=self.credential, bindingId="b-1",
                           grants=[{"capability": "board.respond", "resource": res, "expiresAt": iso(BASE_TIME + 3e7)} for res in r["args"].get("resources", [])])
            return out
        if tool == "fabric.board.join" and principal == "binding":
            if not self.grant:
                return {"error": {"code": "not_authorized", "message": "Ask the operator to let you answer requests for this project."}}
            project = str(args.get("projectId", "")).lower()
            if project != self.board.project:
                return {"error": {"code": "not_authorized", "message": "Ask the operator to let you answer requests for this project."}}
            bearer = secrets.token_urlsafe(32)
            sid = "s-%s" % secrets.token_hex(4)
            self.sessions[bearer] = {"id": sid, "mcp": None, "capabilities": list(self.capabilities)}
            return {"session": {"bearer": bearer, "sessionId": sid, "projectId": project, "capabilities": list(self.capabilities)}}
        return {"error": {"code": "hub-unavailable", "message": "this fake does not serve %s" % tool}}

    # -- the Node tests' commands ------------------------------------------------------------------------------
    def control(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        op = cmd.get("op")
        b = self.board
        if op == "queue":
            return {"request": b.queue(cmd["capability"], cmd.get("text", "Render the attached composition."),
                                       message_digest=cmd.get("messageDigest"))}
        if op == "advance":
            b.advance(float(cmd["seconds"]))
        elif op == "set":
            for key, value in cmd.get("values", {}).items():
                if key in ("down", "grant"):
                    setattr(self, key, value)
                else:
                    setattr(b, key, value)
        elif op == "fail":
            b.fail_next[cmd["tool"]] = cmd["code"]
        elif op == "drop":
            b.drop_next[cmd["tool"]] = int(cmd.get("times", 1))
        elif op == "allow":
            for r in self.access_requests.values():
                r["status"] = "allowed"
        elif op == "publish":
            self.publish(int(cmd.get("pid", os.getpid())), **cmd.get("override", {}))
        elif op == "withdraw":
            self.withdraw()
        elif op == "release":
            for st in list(self.sessions.values()):
                b.release(st["id"])
        elif op == "end-sessions":
            for st in list(self.sessions.values()):
                b.release(st["id"])
            self.sessions.clear()
        elif op == "requeue":  # a claim that lapsed returns to the queue (the board's own claimed -> queued)
            req = b.requests[cmd["request"]]
            if req["state"] != "claimed":
                return {"error": "only a claimed request returns to the queue"}
            b._move(req, "queued")
            req["attempt"] = None
        elif op == "answer":  # the board's pass: the target Project's participant reply answered it (DEC-0098, DEC-0102)
            req = b.requests[cmd["request"]]
            if req["state"] != "queued":
                return {"error": "only a queued request is answered (project-comms: queued -> answered)"}
            b._move(req, "answered")
        elif op == "forget-sessions":  # the sessions end but no DELETE arrives: their slots lapse on their own (FAA-77)
            self.sessions.clear()
        elif op != "state":
            return {"error": "unknown op %r" % op}
        return {"requests": b.requests, "slots": b.slots, "calls": [c[0] for c in b.calls], "callArgs": [c[1] for c in b.calls],
                "notes": b.notes, "replies": b.replies, "bindingsSeen": self.bindings_seen, "sessions": len(self.sessions), "credential": self.credential,
                "doorCalls": [c[0] for c in self.door_calls]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--capability", action="append")
    args = parser.parse_args(argv)
    hub = FakeHub(Path(args.root), capabilities=tuple(args.capability or ["video.render"]))
    print(json.dumps({"port": hub.port, "project": hub.board.project, "credential": hub.credential}), flush=True)
    try:
        sys.stdin.read()  # until the test closes our stdin
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
