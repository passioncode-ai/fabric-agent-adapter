"""One instance per context (FAA-125, organization row N-11; contract DEC-0082, "One instance per context on a machine"):
from a context, ``personal`` or ``org:<orgId>``, the service instance, its folders, descriptor and instance lock. Part of
the service kit (layer L3, after fabric_descriptor); the twin of fabric-context.mjs. Standard library only.

A service started for a context runs as that context's one instance on this machine: its own instance name, descriptor,
data, log and cache folders and instance lock; a second copy for the same context exits 75 as ``hold_single_instance``
does; an organization's instance runs only under a placement of this machine's estate record that names an unrevoked
share grant for that context (FAC-SEM-111), inside the grant's window; a data folder never changes context (its
``fabric-context.json`` marker). A refusal exits 78 (EX_CONFIG) with nothing created. The facade ``fabric_service`` does
not re-export this module, so a service that does not run per context keeps the estate reader out of its closure:
``fabric_kit.py install <dir> --module fabric_context``. Docs: references/estate-record.md (Contexts).

An organization's instance whose context the record does not pin (``organizations``, DEC-0127) still starts: the helper
checks the placement and its share grant, not the pin (decision D5 of 0.52.0). Its tokens are refused instead:
``fabric_estate.hub_key_certified`` reads a context's hub keys only while the record pins that organization (DL-14a,
DEC-0128), so the service passes ``estate_context=info["context"]`` to its delegation gate. The contract lets Fabric
write ``organizations`` only once every reader is pinned at or after DEC-0127, so a refusal at start would stop every
organization instance on today's records."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import ServiceError, _INSTANCE  # noqa: E402
from fabric_descriptor import descriptor_path  # noqa: E402
from fabric_estate import parse_context  # noqa: E402
from fabric_lock import InstanceLock, hold_single_instance  # noqa: E402
from fabric_paths import atomic_write, instance_dirs  # noqa: E402
from fabric_share import instance_share_grant  # noqa: E402
from fabric_time import clock_ms  # noqa: E402

#: EX_CONFIG: the context is refused; 75 stays "already running" (``fabric_lock.EXIT_ALREADY_RUNNING``).
EXIT_CONTEXT_REFUSED = 78
CONTEXT_MARKER = "fabric-context.json"
#: An organization id kept readable in the instance name: lower-case words joined by single hyphens (brief D15).
_READABLE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
#: Only a hashed name ends in a hyphen and 10 hex digits, so a readable and a hashed name never meet.
_HASHED_TAIL = re.compile(r"-[0-9a-f]{10}\Z")
_READABLE_MAX = 28
_SLUG_MAX = 17
#: What each refusal tells the person; the sentence never carries a record or grant value.
_REASONS = {
    "context-invalid": "the context is neither personal nor org:<orgId> as written",
    "record-required": "an organization's instance needs this machine's estate record, its machine id and its agentRef",
    "placement-missing": "the estate record places no such agent on this machine in that context",
    "grant-refused": "its placement names no unrevoked share grant for that context (FAC-SEM-111)",
    "grant-window": "now is outside its share grant's window",
    "context-mismatch": "its data folder belongs to another context or instance (%s)" % CONTEXT_MARKER,
}


class ContextRefused(ServiceError):
    """A context this machine does not run. ``code``: context-invalid, record-required, placement-missing,
    grant-refused, grant-window or context-mismatch."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__("%s: %s." % (code, detail or _REASONS[code]))


def _shown(context: Any) -> str:
    return context if parse_context(context) else "a context that is neither personal nor org:<orgId>"


def context_instance_name(context: Any, *, personal_instance: str = "default") -> str:
    """The instance name of ``context`` (brief D15): ``personal`` is ``personal_instance`` (``default``, so an existing
    install keeps its descriptor, folders and lock); ``org:<orgId>`` is ``org-<orgId>`` when the id is lower-case words
    joined by single hyphens, at most 28 characters, and does not end in a hyphen and 10 hex digits; otherwise
    ``org-<slug>-<first 10 hex digits of sha256(orgId)>``. Every name is a descriptor's instance. Raises ContextRefused."""
    parsed = parse_context(context)
    if parsed is None:
        raise ContextRefused("context-invalid")
    if parsed["kind"] == "personal":
        if not isinstance(personal_instance, str) or not _INSTANCE.match(personal_instance) or personal_instance.startswith("org-"):
            raise ContextRefused("context-invalid", "the personal instance %r is no instance name outside org-" % (personal_instance,))
        return personal_instance
    org = parsed["org"]
    if _READABLE.match(org) and len(org) <= _READABLE_MAX and not _HASHED_TAIL.search(org):
        return "org-" + org
    slug = re.sub(r"[^a-z0-9]+", "-", org.lower()).strip("-")[:_SLUG_MAX].strip("-") or "x"
    return "org-%s-%s" % (slug, hashlib.sha256(org.encode("utf-8")).hexdigest()[:10])


def context_instance(service_id: str, context: Any, *, record: Optional[Dict[str, Any]] = None,
                     machine_id: Optional[str] = None, agent_ref: Optional[str] = None, at: Any = None,
                     personal_instance: str = "default", services_directory: Optional[Path] = None) -> Dict[str, Any]:
    """What ``context`` runs as on this machine; pure (no folder, file or lock). Answers ``{"context", "kind":
    "personal"|"org", "org"?, "instance", "key": "<id>.<instance>", "dirs": {"data", "logs", "cache"},
    "descriptorPath", "grant"?: {"id", "startsAt"?, "expiresAt"?}}``, never the record. Raises ContextRefused.

    ``record`` is the estate record revision this machine applied, already verified (``verify_estate_record``); the
    helper reads it and verifies no signature. ``machine_id`` and ``agent_ref`` come from whoever installed the
    instance, never guessed. ``at`` is the clock (an aware datetime or epoch seconds; now when None)."""
    instance = context_instance_name(context, personal_instance=personal_instance)
    parsed = parse_context(context)
    dirs = instance_dirs(service_id, instance)
    answer: Dict[str, Any] = {"context": context, "kind": parsed["kind"], "instance": instance,
                              "key": "%s.%s" % (service_id, instance), "dirs": dirs,
                              "descriptorPath": descriptor_path(service_id, instance, services_directory)}
    have_place = isinstance(record, dict) and isinstance(machine_id, str) and isinstance(agent_ref, str)
    at_ms = time.time() * 1000.0 if at is None else clock_ms(at)
    if parsed["kind"] == "personal":
        if have_place:  # brief D20: a personal placement that names a grant is refused; no placement is no refusal
            checked = instance_share_grant(record, machine_id, agent_ref, context, at_ms)
            if not checked["ok"] and checked["code"] == "grant-refused":
                raise ContextRefused("grant-refused", checked["detail"])
        return answer
    answer["org"] = parsed["org"]
    if not have_place:
        raise ContextRefused("record-required")
    checked = instance_share_grant(record, machine_id, agent_ref, context, at_ms)
    if not checked["ok"]:
        raise ContextRefused(checked["code"], checked["detail"])
    answer["grant"] = checked["grant"]
    return answer


def _refuse(service_id: Any, context: Any, code: str) -> None:
    print("%s will not run for %s (%s): %s." % (service_id, _shown(context), code, _REASONS[code]), file=sys.stderr, flush=True)
    raise SystemExit(EXIT_CONTEXT_REFUSED)


def _marker_matches(path: Path, expected: Dict[str, str]) -> Optional[bool]:
    """True when the marker names this instance, False when it names another or cannot be read, None when absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return False
    try:
        found = json.loads(text)
    except ValueError:
        return False
    return isinstance(found, dict) and all(found.get(key) == value for key, value in expected.items())


def hold_context_instance(service_id: str, context: Any, *, record: Optional[Dict[str, Any]] = None,
                          machine_id: Optional[str] = None, agent_ref: Optional[str] = None, at: Any = None,
                          personal_instance: str = "default", wait_seconds: Optional[float] = None,
                          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                          env: Optional[Dict[str, str]] = None, argv: Optional[Sequence[str]] = None,
                          services_directory: Optional[Path] = None) -> Tuple[Dict[str, Any], InstanceLock]:
    """Run as ``context``'s one instance, before any side effect (brief D17): ``context_instance`` (a refusal prints one
    sentence naming the code and exits 78, nothing created); then ``hold_single_instance`` on the instance's data
    folder (its markers, its supervised wait, its exit 75); then the marker ``<data>/fabric-context.json``: absent, it
    is written (0600, atomic); equal, it is kept; another context or instance, or unreadable, releases the lock and
    exits 78 (``context-mismatch``). Returns the instance and the held lock."""
    try:
        info = context_instance(service_id, context, record=record, machine_id=machine_id, agent_ref=agent_ref, at=at,
                                personal_instance=personal_instance, services_directory=services_directory)
    except ContextRefused as refused:
        _refuse(service_id, context, refused.code)
    lock = hold_single_instance(info["dirs"]["data"], wait_seconds, sleep=sleep, clock=clock, env=env, argv=argv)
    expected = {"service": service_id, "instance": info["instance"], "context": context}
    marker = Path(info["dirs"]["data"]) / CONTEXT_MARKER
    try:
        matches = _marker_matches(marker, expected)
        if matches is None:
            atomic_write(marker, (json.dumps(expected, indent=1) + "\n").encode("utf-8"), mode=0o600)
    except BaseException:
        lock.release()
        raise
    if matches is False:
        lock.release()
        _refuse(service_id, context, "context-mismatch")
    return info, lock
