"""A fixture conversation for the probe (check_service.py, rule board.responder): a scripted board that a responder
can be run against without Fabric. Part of the board connector (FAA-65, layer L4)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List

import fabric_hub as _hub
from fabric_board_shapes import (  # noqa: E402 - the kit (FAA-65)
    COMMS_PROTOCOL,
    RESPOND_TOOLS,
)
from fabric_board_session import (  # noqa: E402 - the kit (FAA-65)
    BoardSession,
    Responder,
)


_FIXTURE_PROJECT = "3f2a6b1c-0d4e-4f5a-8b6c-7d8e9f0a1b2c"


_FIXTURE_DIGEST = "sha256:" + "a" * 64


def _fixture_answers(variant: str) -> Dict[str, Any]:
    """Scripted board answers in the contract's receipt shapes (fixtures comms-receipt-enroll, comms-receipt-claim)."""
    lease = "2026-10-13T10:02:00Z"
    status: Dict[str, Any] = {"protocol": COMMS_PROTOCOL, "board": {"state": "ready"}, "project": _FIXTURE_PROJECT, "responders": [],
                              "transport": {"telegram": "off"}, "unread": 0, "idempotency": {"epoch": 3}}
    if variant == "no-epoch":
        del status["idempotency"]
    request = {"id": "req_A1b2C3d4E5", "state": "claimed", "effect": "not_started", "revision": 2}
    return {
        "com.status": status,
        "com.enroll": {"ok": True, "repeated": False, "slot": {"project": _FIXTURE_PROJECT, "capability": "fixture.render", "generation": 2, "leaseExpiresAt": lease}},
        "com.claim": {"ok": True, "repeated": False, "message": "msg_K9j8H7g6F5", "request": request,
                      "attempt": {"id": "att_Zx9Cv8Bn7M", "generation": 2, "digest": _FIXTURE_DIGEST, "leaseExpiresAt": lease}},
        "com.get": {"id": "msg_K9j8H7g6F5", "thread": "thr_8Hc2kQ9xA1", "kind": "request", "at": "2026-10-13T10:00:00Z", "digest": _FIXTURE_DIGEST,
                    "sender": {"project": "proj-requester", "principal": {"kind": "agent", "id": "s-1", "provenance": "trusted"}},
                    "body": {"text": "Render the fixture."},
                    "request": {"id": "req_A1b2C3d4E5", "target": _FIXTURE_PROJECT, "capability": "fixture.render", "state": "claimed", "effect": "not_started", "revision": 2}},
        "com.accept": ({"error": {"code": "fenced", "message": "A newer responder holds this slot; this call was not committed.", "retryable": False}}
                       if variant == "fenced" else {"ok": True, "repeated": False, "request": dict(request, state="accepted", revision=3)}),
        "com.complete": {"ok": True, "repeated": False, "request": dict(request, state="completed", revision=4)},
    }


def self_check() -> List[str]:
    """One scripted conversation per path through this kit, with no Fabric: the whole conversation, a `fenced` accept
    and a board session without an epoch. Answers the problems found; an empty list means this kit answers the fixture
    conversation as the contract asks. Writes only in a temporary folder it removes."""
    import os
    import tempfile
    problems: List[str] = []
    for variant in ("whole", "fenced", "no-epoch"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fabric"
            root.mkdir(mode=0o700)
            door = root / "hub-door-token"
            door.write_text("d" * 43)
            os.chmod(door, 0o600)
            (root / "hub.json").write_text(json.dumps({"protocol": _hub.HUB_PROTOCOL, "origin": "http://127.0.0.1:47070", "mcp": "/mcp",
                                                       "doorTokenFile": str(door), "pid": os.getpid(), "startedAt": "2026-10-13T10:00:00Z"}))
            cred = Path(tmp) / "credential"
            cred.write_text("c" * 43)
            os.chmod(cred, 0o600)
            answers, calls, handled = _fixture_answers(variant), [], []

            def post(origin, body, bearer, session=None, timeout=15.0, method="POST", protocol_version=None):
                if method == "DELETE":
                    return 200, {}, None
                rpc = body.get("method")
                if rpc == "initialize":
                    return 200, {"mcp-session-id": "fixture-session"}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"protocolVersion": _hub.MCP_PROTOCOL_VERSION}}
                if rpc != "tools/call":
                    return 202, {}, None
                tool = body["params"]["name"]
                calls.append((tool, body["params"]["arguments"]))
                if tool == "fabric.board.join":
                    value = {"session": {"bearer": "b" * 43, "sessionId": "s-fixture", "projectId": _FIXTURE_PROJECT, "capabilities": ["fixture.render"]}}
                    return 200, {}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"structuredContent": value}}
                value = answers.get(tool, {"error": {"code": "unsupported_capability", "message": "not in the fixture", "retryable": False}})
                return 200, {}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(value)}]}}

            responder = Responder(hub=_hub.HubClient(root, post=post), project_id=_FIXTURE_PROJECT, capabilities=["fixture.render"],
                                  credential_file=cred, checkpoint_file=Path(tmp) / "checkpoint.json",
                                  handler=lambda request, ctx: handled.append(request.body) or {"state": "completed", "summary": "Rendered."},
                                  admit=lambda request: None, now=lambda: 0.0, rand=lambda: 0.5, spawn=lambda fn: fn(),
                                  session_factory=lambda grant: BoardSession(grant, post=post))
            responder.step()
            tools = [t for t, _ in calls]
            if any(t not in RESPOND_TOOLS and t != "fabric.board.join" for t in tools):
                problems.append("%s: a tool outside the respond scope was sent" % variant)
            if variant == "whole":
                if tools != ["fabric.board.join", "com.status", "com.enroll", "com.claim", "com.get", "com.accept", "com.complete"]:
                    problems.append("whole: the calls were %s" % ", ".join(tools))
                accept = dict(calls).get("com.accept", {}).get("fence", {})
                if (accept.get("digest"), accept.get("generation"), accept.get("attempt")) != (_FIXTURE_DIGEST, 2, "att_Zx9Cv8Bn7M"):
                    problems.append("whole: com.accept did not carry the claim's exact fence")
                if handled != ["Render the fixture."]:
                    problems.append("whole: the handler did not see the request once")
                if responder.checkpoint.entries:
                    problems.append("whole: the checkpoint kept a settled request")
            elif variant == "fenced":
                if handled or "com.complete" in tools:
                    problems.append("fenced: the kit kept acting after com.accept answered fenced")
            elif "com.enroll" in tools or responder.state != "down":
                problems.append("no-epoch: the kit did not fail closed without an idempotency epoch")
    return problems
