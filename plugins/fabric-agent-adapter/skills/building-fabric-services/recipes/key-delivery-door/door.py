#!/usr/bin/env python3
"""A key-delivery door template (FAA-238): ask an issuer for one key, print it sealed as the DEC-0111 envelope.

  python3 door.py --slot NAME --provider SLUG --agent-ref URN --recipient KID#kem --context personal|org:<id>
                  [--request-id UUID] --issuer-command "CMD ..." --seal-command "CMD ..." [--timeout 60]

The door prints exactly one `fabric-credential-envelope/1` (contract DEC-0111) on stdout and writes into no store: the
receiver puts it in the recipient's slot (Project Observatory's `vault.py receive PROJECT ENV NAME --from-command --
door.py ...`, its V2 spec, until its OBS-360 ships). The value is never in argv, the environment, a file or stderr.

The two commands are the door owner's (a value travels only over their stdin and stdout, held in memory):
- the issuer command reads the request (`{slot, provider, agentRef, context, requestId?}`, no secret) on stdin and
  prints `{"value": "<key>", "credentialExpiresAt"?: "<RFC 3339>"}` or `{"refused": {"code": "<code>"}}`; exit 75
  (EX_TEMPFAIL) is a transport failure, any other non-zero exit a refusal;
- the seal command reads `{"value", "header"}` on stdin (the header's fields the door fixes) and prints the envelope,
  sealed with HPKE and signed as DEC-0111 says (the contract's `sealCredential`); the standard library seals nothing.

Exit codes, as Observatory's `receive --from-command` maps them: 0 delivered (the envelope on stdout), 2 usage,
3 the issuer refused, 4 no key in the issuer's answer, 5 the store refused (the envelope cannot be sealed for the
recipient's store: the sealer refused, or its envelope fails the checks below), 1 a transport failure that outlived
its retries. Only a transport failure is retried, at most twice.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ENVELOPE = "fabric-credential-envelope/1"
MAX_ANSWER = 65536
RETRIES = 2
TRANSPORT_EXIT = 75
_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z\Z")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+\Z")
_SIG = re.compile(r"^[A-Za-z0-9_-]{86}\Z")
_KEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}#kem\Z")
_SIGNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}(?:#sig)?\Z")
_CONTEXT = re.compile(r"^(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})\Z")
_AGENT_REF = re.compile(r"^urn:fabric:agent:[a-z][a-z0-9]*(?:-[a-z0-9]+)*:[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_SLOT = re.compile(r"^[A-Z][A-Z0-9_]{0,63}\Z")
_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,62}\Z")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_REQUIRED = ("type", "alg", "suite", "recipient", "signer", "context", "agentRef", "slot", "provider", "sequence",
             "iat", "exp", "enc")
_ORG_ONLY = ("requestId", "credentialExpiresAt")


class Refusal(Exception):
    """An exit the door answers with: code and a message that never holds the value."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class Transport(Exception):
    """The issuer could not be reached: the one failure worth another try."""


def _when(text: str) -> float:
    return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def envelope_problems(envelope: Any, want: Dict[str, Any]) -> List[str]:
    """What keeps an envelope from the DEC-0111 shape (credential-envelope.schema.json at the adapter's pin) and from the
    request it answers. Never decrypts or verifies a signature: that is the target's checkCredentialEnvelope."""
    if not isinstance(envelope, dict) or set(envelope) != {"header", "ct", "sig"}:
        return ["not {header, ct, sig}"]
    h, out = envelope["header"], []
    if not isinstance(h, dict):
        return ["header is not an object"]
    out += ["header misses %s" % k for k in _REQUIRED if k not in h]
    out += ["header has no member %s" % k for k in sorted(set(h) - set(_REQUIRED) - set(_ORG_ONLY))]
    if out:
        return out
    checks = [("type", h["type"] == ENVELOPE), ("suite", h["suite"] == [16, 1, 1]),
              ("recipient", isinstance(h["recipient"], str) and bool(_KEM.match(h["recipient"]))),
              ("signer", isinstance(h["signer"], str) and bool(_SIGNER.match(h["signer"]))),
              ("context", isinstance(h["context"], str) and bool(_CONTEXT.match(h["context"]))),
              ("agentRef", isinstance(h["agentRef"], str) and len(h["agentRef"]) <= 146 and bool(_AGENT_REF.match(h["agentRef"]))),
              ("slot", isinstance(h["slot"], str) and bool(_SLOT.match(h["slot"]))),
              ("provider", isinstance(h["provider"], str) and bool(_SLUG.match(h["provider"]))),
              ("sequence", type(h["sequence"]) is int and 1 <= h["sequence"] <= 9007199254740991),
              ("iat", isinstance(h["iat"], str) and bool(_TIME.match(h["iat"]))),
              ("exp", isinstance(h["exp"], str) and bool(_TIME.match(h["exp"]))),
              ("enc", isinstance(h["enc"], str) and bool(_B64URL.match(h["enc"]))),
              ("ct", isinstance(envelope["ct"], str) and bool(_B64URL.match(envelope["ct"]))),
              ("sig", isinstance(envelope["sig"], str) and bool(_SIG.match(envelope["sig"])))]
    out += ["%s does not read" % name for name, ok in checks if not ok]
    if out:
        return out
    org = h["context"] != "personal"
    if h["alg"] != ("EdDSA" if org else "ES256"):
        out.append("alg is EdDSA in an organization's context, ES256 in the personal one")
    if org and not all(k in h for k in _ORG_ONLY):
        out.append("an organization's envelope names requestId and credentialExpiresAt")
    if not org and any(k in h for k in _ORG_ONLY):
        out.append("a personal envelope names no requestId or credentialExpiresAt")
    if org and "requestId" in h and not (isinstance(h["requestId"], str) and _UUID.match(h["requestId"])):
        out.append("requestId does not read")
    iat, exp = _when(h["iat"]), _when(h["exp"])
    if not 0 < exp - iat <= 24 * 3600:
        out.append("exp is after iat and at most 24 hours later")
    if org and "credentialExpiresAt" in h:
        end = h["credentialExpiresAt"]
        if not (isinstance(end, str) and _TIME.match(end) and iat < _when(end) <= iat + 30 * 86400):
            out.append("credentialExpiresAt is after iat and at most 30 days later")
    for key in ("recipient", "context", "agentRef", "slot", "provider", "requestId"):
        if key in want and h.get(key) != want[key]:
            out.append("header %s is not the one asked for" % key)
    return out


def scrub(text: str, value: Optional[str]) -> str:
    return text.replace(value, "[value hidden]") if value else text


def run_child(argv: Sequence[str], payload: bytes, timeout: float) -> Tuple[int, bytes, str]:
    """A child with the payload on stdin; its stdout in memory (at most 64 KiB), its stderr as text."""
    try:
        done = subprocess.run(list(argv), input=payload, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Transport("%s did not answer in %g s" % (argv[0], timeout))
    except OSError as exc:
        raise Refusal(2, "%s cannot be run: %s" % (argv[0], exc.strerror or exc))
    if len(done.stdout) > MAX_ANSWER:
        return done.returncode, b"", "its answer is over %d bytes" % MAX_ANSWER
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


def command_issuer(argv: Sequence[str], timeout: float) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def issue(request: Dict[str, Any]) -> Dict[str, Any]:
        code, out, err = run_child(argv, json.dumps(request).encode(), timeout)
        if code == TRANSPORT_EXIT:
            raise Transport("the issuer could not be reached")
        if code != 0:
            raise Refusal(3, "the issuer refused (exit %d)" % code)
        try:
            return json.loads(out.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refusal(4, "the issuer's answer is not JSON")
    return issue


def command_sealer(argv: Sequence[str], timeout: float) -> Callable[[str, Dict[str, Any]], Any]:
    def seal(value: str, header: Dict[str, Any]) -> Any:
        try:
            code, out, _err = run_child(argv, json.dumps({"value": value, "header": header}).encode(), timeout)
        except Transport:
            raise Refusal(5, "the sealer did not answer")
        if code != 0:
            raise Refusal(5, "the sealer refused (exit %d)" % code)
        try:
            return json.loads(out.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refusal(5, "the sealer's answer is not JSON")
    return seal


def deliver(want: Dict[str, Any], issue: Callable[[Dict[str, Any]], Dict[str, Any]],
            seal: Callable[[str, Dict[str, Any]], Any], *, sleep: Callable[[float], None] = time.sleep) -> str:
    """The envelope's one line, or a Refusal. `want` names slot, provider, agentRef, recipient, context, requestId?."""
    request = {k: want[k] for k in ("slot", "provider", "agentRef", "context", "requestId") if k in want}
    for attempt in range(RETRIES + 1):
        try:
            answer = issue(request)
            break
        except Transport as exc:
            if attempt == RETRIES:
                raise Refusal(1, "transport failure after %d tries: %s" % (RETRIES + 1, exc))
            sleep(1.0 * (attempt + 1))
    if isinstance(answer, dict) and isinstance(answer.get("refused"), dict):
        code = answer["refused"].get("code")
        raise Refusal(3, "the issuer refused: %s" % (code if isinstance(code, str) and _SLUG.match(code) else "no code"))
    value = answer.get("value") if isinstance(answer, dict) else None
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise Refusal(4, "the issuer's answer holds no key")
    header = {"type": ENVELOPE, "recipient": want["recipient"], "context": want["context"], "agentRef": want["agentRef"],
              "slot": want["slot"], "provider": want["provider"]}
    if want["context"] != "personal":
        header["requestId"] = want["requestId"]
        if isinstance(answer.get("credentialExpiresAt"), str):
            header["credentialExpiresAt"] = answer["credentialExpiresAt"]
    envelope = seal(value, header)
    problems = envelope_problems(envelope, want)
    line = json.dumps(envelope, separators=(",", ":"))
    if not problems and value in line:
        problems = ["the envelope carries the value in clear"]
    if problems:
        raise Refusal(5, "the sealed envelope is refused: %s" % "; ".join(scrub(p, value) for p in problems))
    return line


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("--slot", "--provider", "--agent-ref", "--recipient", "--context", "--issuer-command", "--seal-command"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    want = {"slot": args.slot, "provider": args.provider, "agentRef": args.agent_ref, "recipient": args.recipient,
            "context": args.context}
    usage = [name for name, pattern, value in (("--slot", _SLOT, args.slot), ("--provider", _SLUG, args.provider),
                                               ("--agent-ref", _AGENT_REF, args.agent_ref), ("--recipient", _KEM, args.recipient),
                                               ("--context", _CONTEXT, args.context)) if not pattern.match(value)]
    if args.context != "personal":
        if not (args.request_id and _UUID.match(args.request_id)):
            usage.append("--request-id (an organization's context answers a credential-request/1)")
        want["requestId"] = args.request_id
    elif args.request_id:
        usage.append("--request-id (a personal envelope names none)")
    try:
        issuer, sealer = shlex.split(args.issuer_command), shlex.split(args.seal_command)
    except ValueError as exc:
        usage.append("a command that does not split: %s" % exc)
        issuer = sealer = []
    if usage or not issuer or not sealer:
        print("door.py: usage: %s" % ", ".join(usage or ["an empty command"]), file=sys.stderr)
        return 2
    try:
        line = deliver(want, command_issuer(issuer, args.timeout), command_sealer(sealer, args.timeout))
    except Refusal as exc:
        print("door.py: %s" % exc, file=sys.stderr)
        return exc.code
    sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
