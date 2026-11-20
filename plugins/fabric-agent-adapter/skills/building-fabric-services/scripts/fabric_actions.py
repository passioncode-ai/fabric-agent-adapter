# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""Every action a person has, its agent tool and who decides it: `fabric-actions/0.1`, the extension keyed
extensions/actions/0.1 (DEC-0121, FAC-SEM-142). Part of the service kit (layer L3); the twin of fabric-actions.mjs.

- ``action_decision(inputs)``: whether a service takes a call of one declared action and as whose act it records it,
  exactly as the contract's ``actionDecision`` answers (AP-2, AP-4; DL-17, DL-18, DL-25). A ``fault`` is the
  service's own and is never sent to a caller as such; ``action_gate`` answers ``mandate-capability-missing`` as
  operator-decision-required (DEC-0141 MJ-1).
- ``JOB_STEP_TOOL`` and ``job_capability(value)``: the tool a job's answer comes through, and whether a job's
  capability can read its step under a mandate (a capability name other than ``fabric.job.get``).
- ``decision_shape(value)``: a decision as ``decision.schema.json`` reads it, ``at`` read strictly (the contract's
  ``strictTime``).
- ``actions_view(well_known)``: the host reader of the declaration, as the contract's ``actionsView``.
- ``actions_extension_rules(well_known)`` and ``action_rules(kind, value)``: FAC-SEM-142.
- ``agent_surface_rules(well_known)``: FAC-SEM-176 (DEC-0169 RP-3), as the contract's ``agentSurfaceRules``.
- ``actions_extension(actions, capabilities)``: the ``extensions`` entry a service declares; it refuses a declaration
  FAC-SEM-142 would find, so a service never publishes one.
- ``operator_decision(action, instruction, ..., source=None)``: the decision an agent relays in ``_meta.decision``
  (AP-2, AP-3), refused when ``decision.schema.json`` would refuse it.
- ``action_caller(tier, authenticated)``: the caller a service records (AP-2): the identity it authenticated, else
  ``local:T0`` / ``local:T1`` for a caller its local floor authenticated, never a name the call carries.
- DEC-0125: ``action_decision`` reads a call's mandate (``_meta.mandate``) through fabric_mandate.mandate_covers when the
  call carries no decision.
- DEC-0126: a decision may carry ``source`` (where the operator said the words, OA-2); ``action_decision`` returns it
  in ``recordAs`` (OA-6). A service that reads it lists ``operator-source/1`` and keeps it, as ``instruction``, in its
  own audit record only: never an event, a usage report, a log line or a page another party reads (OA-7).

The kit has no JSON Schema validator: the two shapes are written here from the schemas, lengths in code points and
patterns over the whole string, as the contract's validator reads them. Never raises on what it reads. Standard library
only.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_jsvalue import MISSING, contains, get, is_number, json_equal, json_stringify  # noqa: E402
from fabric_mandate import EFFECT_CLASSES, mandate_covers, source_shape  # noqa: E402 - DEC-0125, DEC-0126
import fabric_levels as _levels  # noqa: E402 - DEC-0162
from fabric_time import format_rfc3339, parse_rfc3339_ms  # noqa: E402

ACTIONS_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/actions/0.1"
#: The authority extension (DEC-0162 LV-5, LV-7; DEC-0166 AU-3): the organizations whose levels a service reads, the
#: level each relayed action needs and whether it reads standing mandates.
AUTHORITY_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/authority/0.1"
ACTION_LEVELS = _levels.ACTION_LEVELS
#: The three refusals DEC-0121 adds to DL-19's one code set, and DL-17's refusal a T2 caller still gets.
OPERATOR_DECISION_REQUIRED = "operator-decision-required"
DECISION_INVALID = "decision-invalid"
HUMAN_STEP_REQUIRED = "human-step-required"
APPROVAL_REQUIRED = "approval-required"
GATES = ("none", "relayed", "human")
#: AP-4's steps a person takes; `comparison` (DEC-0142) is a comparison of codes between two people.
HUMAN_STEPS = ("sign-in", "consent", "payment", "secret", "spend-above-limit", "passkey", "comparison")
MAX_ACTIONS = 128
#: How far ahead of the service's clock a decision's `at` may be (the contract's CLOCK_SKEW_SECONDS).
CLOCK_SKEW_SECONDS = 60
#: How long after the operator decided a relayed decision still stands: approval/1's lifetime (DL-17, FAC-SEM-051).
DECISION_LIFETIME_SECONDS = 24 * 60 * 60

_REQUEST_KEY = re.compile(r"[A-Za-z0-9_.-]{1,64}", re.ASCII)  # interop-common.schema.json#/$defs/requestKey
_CAPABILITY = re.compile(r"[a-z][a-z0-9._-]{1,127}", re.ASCII)  # common.schema.json#/$defs/capabilityName
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
_STEP_URL = re.compile(r"https://|/")  # a prefix, as the contract's /^(https:\/\/|\/)/ tests it
_ACTION_MEMBERS = ("id", "title", "tool", "gate", "humanStep")
_DECISION_MEMBERS = ("by", "via", "action", "target", "instruction", "at", "source")
_LEVEL_DECISION_MEMBERS = ("by", "via", "level", "org", "project", "action", "target", "instruction", "at", "membership")
_ORG = re.compile(r"org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_AUDIENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}", re.ASCII)
_KEY_PATH = "/extensions/" + ACTIONS_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")
_AUTHORITY_PATH = "/extensions/" + AUTHORITY_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")


def _text(value: Any, low: int, high: int) -> bool:
    """A string of low..high code points, as the validator counts them (Python counts code points)."""
    return isinstance(value, str) and low <= len(value) <= high


def _matches(pattern: "re.Pattern[str]", value: Any, high: int) -> bool:
    return isinstance(value, str) and len(value) <= high and pattern.fullmatch(value) is not None


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _one_of(value: Any, choices: Iterable[str]) -> bool:
    return isinstance(value, str) and value in choices


def _action_errors(value: Any, at: str) -> List[str]:
    """`service-actions-extension.schema.json#/$defs/action`: the errors at `at`, empty for a valid entry."""
    if not isinstance(value, dict):
        return ["%s type" % at]
    errors = ["%s/%s additionalProperties" % (at, key) for key in value if key not in _ACTION_MEMBERS]
    errors += ["%s required %s" % (at, key) for key in ("id", "title", "tool", "gate") if key not in value]
    if "id" in value and not _matches(_REQUEST_KEY, value["id"], 64):
        errors.append("%s/id pattern" % at)
    if "title" in value and not _text(value["title"], 1, 80):
        errors.append("%s/title maxLength" % at)
    if "tool" in value and not _matches(_CAPABILITY, value["tool"], 128):
        errors.append("%s/tool pattern" % at)
    if "gate" in value and not _one_of(value["gate"], GATES):
        errors.append("%s/gate enum" % at)
    if "humanStep" in value and not _one_of(value["humanStep"], HUMAN_STEPS):
        errors.append("%s/humanStep enum" % at)
    return errors


def _extension_errors(value: Any) -> List[str]:
    """`service-actions-extension.schema.json`: the errors, empty for a valid declaration."""
    if not isinstance(value, dict):
        return ["/ type"]
    errors = ["/%s additionalProperties" % key for key in value if key != "actions"]
    if "actions" not in value:
        return errors + ["/ required actions"]
    actions = value["actions"]
    if not isinstance(actions, list):
        return errors + ["/actions type"]
    if not 1 <= len(actions) <= MAX_ACTIONS:
        errors.append("/actions %s" % ("minItems" if not actions else "maxItems"))
    for index, action in enumerate(actions):
        errors += _action_errors(action, "/actions/%d" % index)
    return errors


def readable_action(action: Any) -> bool:
    """One valid `actions[]` entry whose `humanStep` is present exactly when `gate` is `human`."""
    return not _action_errors(action, "") and (action["gate"] == "human") == ("humanStep" in action)


def decision_shape(value: Any) -> bool:
    """`decision.schema.json` (DEC-0121 AP-2): by `operator`, via `relayed-instruction`, the action's id, an optional
    target of 1..200, the operator's words of 1..500, `at` read strictly (the contract's strictTime; ajv-formats'
    date-time also admits a space for T and a leap second, which this refuses, decision D5), and an optional `source`
    as mandate.schema.json#/$defs/source reads it (DEC-0126)."""
    if isinstance(value, dict) and value.get("by") == "level":
        return _level_decision_shape(value)
    if not isinstance(value, dict) or any(key not in _DECISION_MEMBERS for key in value):
        return False
    if any(key not in value for key in ("by", "via", "action", "instruction", "at")):
        return False
    return (isinstance(value["by"], str) and value["by"] == "operator"
            and isinstance(value["via"], str) and value["via"] == "relayed-instruction"
            and _matches(_REQUEST_KEY, value["action"], 64)
            and ("target" not in value or _text(value["target"], 1, 200))
            and _text(value["instruction"], 1, 500)
            and isinstance(value["at"], str) and not math.isnan(parse_rfc3339_ms(value["at"]))
            and ("source" not in value or source_shape(value["source"])))


def _level_decision_shape(value: Dict[str, Any]) -> bool:
    """`decision.schema.json#/$defs/level` (DEC-0162 LV-3): a level holder's decision, its attestation an object the
    service verifies (fabric_levels), never this shape; `project` required for an architect."""
    if any(key not in _LEVEL_DECISION_MEMBERS for key in value):
        return False
    if any(key not in value for key in ("by", "via", "level", "org", "action", "instruction", "at", "membership")):
        return False
    if value["level"] == "architect" and "project" not in value:
        return False
    return (value["via"] == "level-command" and isinstance(value["level"], str) and value["level"] in _levels.DECIDING_LEVELS
            and _text(value["org"], 0, 132) and _ORG.fullmatch(value["org"]) is not None
            and ("project" not in value or (_text(value["project"], 1, 128) and _PROJECT.fullmatch(value["project"]) is not None))
            and _matches(_REQUEST_KEY, value["action"], 64)
            and ("target" not in value or _text(value["target"], 1, 200))
            and _text(value["instruction"], 1, 500)
            and isinstance(value["at"], str) and not math.isnan(parse_rfc3339_ms(value["at"]))
            and isinstance(value["membership"], dict))


def _accepted_approval(approval: Any) -> bool:
    return isinstance(approval, dict) and approval.get("ok") is True and _non_empty(approval.get("approver"))


def _refuse(code: str) -> Dict[str, Any]:
    return {"ok": False, "code": code}


def action_decision(inputs: Any) -> Dict[str, Any]:
    """Whether a service takes a call of one declared action, and as whose act it records it (DEC-0121 AP-2, AP-4;
    DL-17, DL-18, DL-25, DL-26), as the contract's actionDecision answers. `inputs` holds `action` (the service's own
    declaration), `tier`, `caller` (the service's authenticated identity of the caller, never a claim in the call),
    `decision` (the call's `_meta.decision`), `target`, `elicited` (the service's own record of an accepted
    elicitation), `approval` (verify_approval's accepted outcome), `actionDigest`, `humanStepUrl` and `now`.

    - `none`: the caller's own act. `human`: `human-step-required` with the step and its link, at every tier.
    - `relayed`: an accepted approval is the approver's; a T2 caller without one gets `approval-required` with the
      digest; an accepted elicitation is the operator's; no decision is `operator-decision-required`; a decision that
      is not the schema's, is for another action or object, or whose `at` is more than 60 s ahead of `now` or more
      than 24 h behind it is `decision-invalid`; otherwise the operator's act, recorded with `caller` and, when the
      decision carries one, its `source` (DEC-0126 OA-6).
    - DEC-0125: a call with no decision that carries `mandate` (its `_meta.mandate`) is answered as
      fabric_mandate.mandate_covers answers, given `self` (the service's own agent id), `callerAgent` (only an agent id
      the service authenticated), `effect` (the action's effect class, the service's own knowledge), `spendUsd` (its
      own estimate) and `project`: covered, `{by: operator, via: mandate, task, chain, source?, caller}`; otherwise
      `operator-decision-required` or `decision-invalid` with `data.detail`.
    - DEC-0141 MJ-1: a job's input request (tool `fabric.job.get`) under a mandate is read under `mandateCapability`,
      the job's own capability (the tool its start call named), its action the request key; any other action reads
      its own tool.
    - `{"fault": ...}` (action-invalid, caller-missing, now-unreadable, digest-missing, url-missing, effect-missing,
      self-missing, mandate-capability-missing) is the service's own: an input it owes is missing or unreadable. It is
      never sent to a caller (action_gate answers mandate-capability-missing as operator-decision-required)."""
    action = get(inputs, "action")
    if not readable_action(action):
        return {"fault": "action-invalid"}
    if action["gate"] == "none":
        return {"ok": True, "recordAs": "caller"}
    if action["gate"] == "human":
        url = get(inputs, "humanStepUrl")
        if not _non_empty(url) or not _STEP_URL.match(url):
            return {"fault": "url-missing"}
        return {"ok": False, "code": HUMAN_STEP_REQUIRED, "data": {"humanStep": action["humanStep"], "url": url}}
    caller = get(inputs, "caller")
    if not _non_empty(caller):
        return {"fault": "caller-missing"}
    levels, action_level = get(inputs, "levels"), get(inputs, "actionLevel")
    # The service's level contexts are a map by organization; an array (the declaration itself) is its fault.
    if levels is not MISSING and not _levels.level_contexts_well_formed(levels):
        return {"fault": "levels-invalid"}
    if action_level is not MISSING and not (isinstance(action_level, str) and action_level in ACTION_LEVELS):
        return {"fault": "action-level-invalid"}
    decision, mandate, approval = get(inputs, "decision"), get(inputs, "mandate"), get(inputs, "approval")
    level_decision = isinstance(decision, dict) and decision.get("by") == "level"
    inside = _one_of(get(inputs, "tier"), ("T0", "T1"))
    reads_levels = isinstance(levels, dict)
    # LV-7: at a service that reads levels the effect decides whether `change-policy` raises the action to `admin`.
    if reads_levels and not (isinstance(get(inputs, "effect"), str) and inputs["effect"] in EFFECT_CLASSES):
        return {"fault": "effect-missing"}
    least = _min_level_of(inputs)
    level_act = reads_levels and least in ("owner", "admin")
    context = get(inputs, "context")
    context_ok = isinstance(context, str) and _levels.CALL_CONTEXT.fullmatch(context) is not None
    if level_act and not context_ok:
        return {"fault": "context-missing"}
    # LV-7: in an organization's context an act declared `owner` or `admin` is decided only at that level.
    level_only = level_act and context.startswith("org:")
    level_mandate = ((decision is MISSING or ((not inside or level_only) and not level_decision))
                     and isinstance(mandate, dict) and mandate.get("by") == "level")
    if _accepted_approval(approval) and not level_only:
        return {"ok": True, "recordAs": {"by": approval["approver"], "via": "approval", "caller": caller}}
    if inside and get(inputs, "elicited") is True and not level_only:
        return {"ok": True, "recordAs": {"by": "operator", "via": "elicitation", "caller": caller}}
    level_read = level_decision and reads_levels
    # DEC-0166 AU-3: a standing mandate is read at every tier by a service that declares `standing`.
    standing_mandate = (not level_only and (decision is MISSING or (not inside and not level_read))
                        and get(inputs, "standing") is True and isinstance(mandate, dict) and isinstance(mandate.get("standing"), dict))
    digest = get(inputs, "actionDigest")
    digest_ok = isinstance(digest, str) and _SHA256.fullmatch(digest) is not None
    if (reads_levels and (level_decision or level_mandate)) or standing_mandate:
        clock = parse_rfc3339_ms(get(inputs, "now"))
        if math.isnan(clock):
            return {"fault": "now-unreadable"}
        if not context_ok:
            return {"fault": "context-missing"}
        if not inside and not digest_ok:
            return {"fault": "digest-missing"}
        read = _by_level(inputs, action, caller, clock) if level_read else _by_mandate(inputs, action, caller)
        if "ignored" in read:
            return _refuse(OPERATOR_DECISION_REQUIRED) if inside else {"ok": False, "code": APPROVAL_REQUIRED, "data": {"actionDigest": digest}}
        if not inside and read.get("ok") is False and read.get("code") in (OPERATOR_DECISION_REQUIRED, DECISION_INVALID):
            return dict(read, data=dict(read.get("data") or {}, actionDigest=digest))
        return read
    if not inside:
        if not digest_ok:
            return {"fault": "digest-missing"}
        if level_only:  # no approval decides an act only a level decides (LV-7)
            return {"ok": False, "code": OPERATOR_DECISION_REQUIRED, "data": {"detail": "level-insufficient: %s" % least, "actionDigest": digest}}
        return {"ok": False, "code": APPROVAL_REQUIRED, "data": {"actionDigest": digest}}
    clock = parse_rfc3339_ms(get(inputs, "now"))
    if math.isnan(clock):
        return {"fault": "now-unreadable"}
    if level_only:
        return {"ok": False, "code": OPERATOR_DECISION_REQUIRED, "data": {"detail": "level-insufficient: %s" % least}}
    # A level decision at a service that reads no levels is as if absent (LV-10), so a mandate the call carries is read.
    if (decision is MISSING or level_decision) and mandate is not MISSING:
        answer = _by_mandate(inputs, action, caller)
        return _refuse(OPERATOR_DECISION_REQUIRED) if "ignored" in answer else answer
    if decision is MISSING or level_decision:
        return _refuse(OPERATOR_DECISION_REQUIRED)
    if not decision_shape(decision):
        return _refuse(DECISION_INVALID)
    if decision["action"] != action["id"] or ("target" in decision and not (
            isinstance(get(inputs, "target"), str) and decision["target"] == inputs["target"])):
        return _refuse(DECISION_INVALID)
    at = parse_rfc3339_ms(decision["at"])
    if at > clock + CLOCK_SKEW_SECONDS * 1000 or at < clock - DECISION_LIFETIME_SECONDS * 1000:
        return _refuse(DECISION_INVALID)
    record: Dict[str, Any] = {"by": "operator", "via": "relayed-instruction", "caller": caller}
    if "source" in decision:  # a decision relayed from another of the operator's agents keeps where they said it (OA-6)
        record["source"] = dict(decision["source"])
    return {"ok": True, "recordAs": record}


#: The tool of a job's input request (interop C3.3, AP-2): the call that answers it is fabric.job.get (DEC-0141 MJ-1).
JOB_STEP_TOOL = "fabric.job.get"


def job_capability(value: Any) -> bool:
    """A job's capability a mandate can read a step under (MJ-1): a capability name, never fabric.job.get itself."""
    return isinstance(value, str) and _CAPABILITY.fullmatch(value) is not None and value != JOB_STEP_TOOL


def _by_mandate(inputs: Any, action: Dict[str, Any], caller: str) -> Dict[str, Any]:
    """A relayed action's call that carries a mandate and no decision (DEC-0125 MD-3): the mandate decides, as the
    contract's byMandate reads it: the service's own `effect` and agent id `self` are required (else a fault), its
    estimate `spendUsd` is read when a number and `project` when a string."""
    effect, me = get(inputs, "effect"), get(inputs, "self")
    if not isinstance(effect, str):
        return {"fault": "effect-missing"}
    if not isinstance(me, str):
        return {"fault": "self-missing"}
    # MJ-1: a job's step is read under the job's capability, never under the transport fabric.job.get itself.
    capability = get(inputs, "mandateCapability") if action["tool"] == JOB_STEP_TOOL else action["tool"]
    if not job_capability(capability):
        return {"fault": "mandate-capability-missing"}
    call: Dict[str, Any] = {"capability": capability, "action": action["id"], "effect": effect}
    spend, project, context = get(inputs, "spendUsd"), get(inputs, "project"), get(inputs, "context")
    if is_number(spend):
        call["spendUsd"] = spend
    if isinstance(project, str):
        call["project"] = project
    if isinstance(context, str):
        call["context"] = context
    least = _min_level_of(inputs)
    if least is not None:
        call["minLevel"] = least
    covers: Dict[str, Any] = {"mandate": inputs["mandate"], "tier": get(inputs, "tier"), "now": get(inputs, "now"),
                              "self": me, "call": call}
    if get(inputs, "callerAgent") is not MISSING:
        covers["callerAgent"] = inputs["callerAgent"]
    if isinstance(get(inputs, "levels"), dict):
        covers["levels"] = inputs["levels"]
        if get(inputs, "tokenMem") is not MISSING:
            covers["tokenMem"] = inputs["tokenMem"]
    if get(inputs, "standing") is True:
        covers["standing"] = True
        if get(inputs, "tokenProf") is not MISSING:
            covers["tokenProf"] = inputs["tokenProf"]
    answer = mandate_covers(covers)
    if "recordAs" in answer:
        record = dict(answer["recordAs"])
        record["caller"] = caller
        return {"ok": True, "recordAs": record}
    # `ignored`: a T2 operator mandate (MD-5), or a level mandate at a service that reads no levels (LV-10); the
    # caller answers as if the call carried no mandate.
    return answer


def _min_level_of(inputs: Any) -> Optional[str]:
    """The lowest level that decides the action: the service's declaration, raised to `admin` for an action whose effect
    is `change-policy`, which an owner or an admin decides and never an architect (DEC-0162 LV-7)."""
    declared = get(inputs, "actionLevel")
    declared = None if declared is MISSING else declared
    return "admin" if get(inputs, "effect") == "change-policy" and declared in (None, "architect") else declared


def _by_level(inputs: Any, action: Dict[str, Any], caller: str, clock: float) -> Dict[str, Any]:
    """A relayed action's call that carries a level decision, at a service that reads levels (DEC-0162 LV-3 to LV-6,
    LV-10, LV-11), at any tier, as the contract's byLevel reads it."""
    decision = inputs["decision"]
    if not decision_shape(decision):
        return _refuse(DECISION_INVALID)
    if decision["action"] != action["id"] or ("target" in decision and not (
            isinstance(get(inputs, "target"), str) and decision["target"] == inputs["target"])):
        return _refuse(DECISION_INVALID)
    at = parse_rfc3339_ms(decision["at"])
    if at > clock + CLOCK_SKEW_SECONDS * 1000 or at < clock - DECISION_LIFETIME_SECONDS * 1000:
        return _refuse(DECISION_INVALID)
    project = get(inputs, "project")
    project = project if isinstance(project, str) else None
    if "project" in decision and decision["project"] != project:  # a decision for one project decides nothing elsewhere
        return _refuse(DECISION_INVALID)
    standing_inputs: Dict[str, Any] = {"membership": decision["membership"], "org": decision["org"], "level": decision["level"],
                                       "at": decision["at"], "context": inputs["context"], "contexts": inputs["levels"],
                                       "tokenMem": None if get(inputs, "tokenMem") is MISSING else inputs["tokenMem"], "now": clock}
    if project is not None:
        standing_inputs["project"] = project
    least = _min_level_of(inputs)
    if least is not None:
        standing_inputs["minLevel"] = least
    standing = _levels.level_standing(standing_inputs)
    if not standing["ok"]:
        if "invalid" in standing:
            return {"ok": False, "code": DECISION_INVALID, "data": {"detail": standing["invalid"]}}
        return {"ok": False, "code": OPERATOR_DECISION_REQUIRED, "data": {"detail": standing["insufficient"]}}
    record: Dict[str, Any] = {"by": "level", "via": "level-command", "level": standing["level"], "org": standing["org"]}
    if project is not None:
        record["project"] = project
    record.update({"approver": standing["approver"], "membershipDigest": standing["membershipDigest"],
                   "revision": standing["revision"], "caller": caller})
    return {"ok": True, "recordAs": record}


def actions_view(well_known: Any) -> Dict[str, Any]:
    """The host reader of extensions/actions/0.1 (DEC-0121 AP-1), as the contract's actionsView: `{declared: False}`,
    `{declared: True, valid: False, errors}` or `{declared: True, valid: True, actions}`. Never raises."""
    extensions = get(well_known, "extensions")
    if not isinstance(extensions, dict) or ACTIONS_EXTENSION_KEY not in extensions:
        return {"declared": False}
    value = extensions[ACTIONS_EXTENSION_KEY]
    errors = _extension_errors(value)
    if errors:
        return {"declared": True, "valid": False, "errors": errors}
    return {"declared": True, "valid": True, "actions": value["actions"]}


def _authority_errors(value: Any) -> List[str]:
    """`service-authority-extension.schema.json` (DEC-0162, DEC-0166): an open object of at least one member whose
    `standing` is true, `levels` 1 to 16 {org, audience} and `actionLevels` 1 to 128 levels keyed by action id. Each
    error is `<path> <keyword>`; the wording is not part of a vector (0.50.0 brief D6)."""
    if not isinstance(value, dict):
        return ["/ type"]
    if not value:
        return ["/ minProperties"]
    errors: List[str] = []
    if "standing" in value and value["standing"] is not True:
        errors.append("/standing const")
    if "levels" in value:
        levels = value["levels"]
        if not isinstance(levels, list) or not 1 <= len(levels) <= 16:
            errors.append("/levels " + ("type" if not isinstance(levels, list) else "minItems" if not levels else "maxItems"))
        else:
            for index, entry in enumerate(levels):
                if not (isinstance(entry, dict) and sorted(entry) == ["audience", "org"] and _text(entry["org"], 0, 132)
                        and _ORG.fullmatch(entry["org"]) is not None and isinstance(entry["audience"], str)
                        and _AUDIENCE.fullmatch(entry["audience"]) is not None):
                    errors.append("/levels/%d schema" % index)
    if "actionLevels" in value:
        levels = value["actionLevels"]
        if not isinstance(levels, dict) or not 1 <= len(levels) <= 128:
            errors.append("/actionLevels " + ("type" if not isinstance(levels, dict) else "minProperties" if not levels else "maxProperties"))
        else:
            for key, level in levels.items():
                if _REQUEST_KEY.fullmatch(key) is None:
                    errors.append("/actionLevels propertyNames")
                if not (isinstance(level, str) and level in ACTION_LEVELS):
                    errors.append("/actionLevels/%s enum" % key)
    return errors


def authority_view(well_known: Any) -> Dict[str, Any]:
    """The host reader of extensions/authority/0.1 (DEC-0162 LV-5, LV-7; DEC-0166 AU-3), as the contract's
    authorityView: `{declared: False}`, `{declared: True, valid: False, errors}` or `{declared: True, valid: True,
    levels?, actionLevels?, standing?}`. A service passes `levels` and `actionLevels` on to action_decision: the level
    contexts it holds for those organizations and the entry for the called action. Never raises."""
    extensions = get(well_known, "extensions")
    if not isinstance(extensions, dict) or AUTHORITY_EXTENSION_KEY not in extensions:
        return {"declared": False}
    value = extensions[AUTHORITY_EXTENSION_KEY]
    errors = _authority_errors(value)
    if errors:
        return {"declared": True, "valid": False, "errors": errors}
    view: Dict[str, Any] = {"declared": True, "valid": True}
    for name in ("levels", "actionLevels", "standing"):
        if name in value:
            view[name] = value[name]
    return view


def agent_surface_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-176 (DEC-0169 RP-3), as the contract's agentSurfaceRules: a service that serves a dashboard serves an agent
    surface beside it (`surfaces.mcp` or `surfaces.a2a`), and a present `surfaces.mcp.capabilities` names a tool."""
    surfaces = get(well_known, "surfaces")
    surfaces = surfaces if isinstance(surfaces, dict) else {}
    findings: List[Dict[str, str]] = []
    if "dashboard" in surfaces and "mcp" not in surfaces and "a2a" not in surfaces:
        findings.append({"code": "FAC-SEM-176", "instancePath": "/surfaces", "message": "a service that serves a dashboard "
                         "serves an agent surface beside it: surfaces.mcp, or surfaces.a2a (DEC-0169 RP-3)"})
    mcp = surfaces.get("mcp") if isinstance(surfaces.get("mcp"), dict) else {}
    if isinstance(mcp.get("capabilities"), list) and not mcp["capabilities"]:
        findings.append({"code": "FAC-SEM-176", "instancePath": "/surfaces/mcp/capabilities", "message": "an MCP surface "
                         "serves at least one tool: an empty list is an agent surface an agent cannot use (DEC-0169 RP-3)"})
    return findings


def authority_extension_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-142 on the authority key of a well-known document (DEC-0162 LV-5, LV-7): a value that is not its schema's,
    an organization named twice in `levels`, a level for an id that is not a relayed action of the actions declaration."""
    view = authority_view(well_known)
    if not view["declared"]:
        return []
    if not view["valid"]:
        return [_finding(_AUTHORITY_PATH, "the authority declaration is invalid (%s); a reader treats it as not declared and "
                                          "reports it (DEC-0162)" % "; ".join(view["errors"]))]
    findings: List[Dict[str, str]] = []
    orgs = set()
    for index, entry in enumerate(view.get("levels", [])):
        if entry["org"] in orgs:
            findings.append(_finding("%s/levels/%d/org" % (_AUTHORITY_PATH, index), "organization %s is named twice (DEC-0162 LV-5)" % entry["org"]))
        orgs.add(entry["org"])
    actions = actions_view(well_known)
    relayed = {a["id"] for a in actions["actions"] if a["gate"] == "relayed"} if actions.get("valid") else set()
    for key in view.get("actionLevels", {}):
        if key not in relayed:
            findings.append(_finding("%s/actionLevels/%s" % (_AUTHORITY_PATH, key.replace("~", "~0").replace("/", "~1")),
                                     "%s is not a relayed action of the actions declaration: a level is declared only for one "
                                     "(DEC-0162 LV-7)" % key))
    return findings


def _finding(instance_path: str, message: str) -> Dict[str, str]:
    return {"code": "FAC-SEM-142", "instancePath": instance_path, "message": message}


def actions_extension_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-142 on a well-known document that carries the actions key: a value that is not its schema's (one
    finding at the key); an id named twice; a `humanStep` present without `gate: human` or absent with it; a `tool`
    that a present `surfaces.mcp.capabilities` does not list (a button without an agent twin, AP-1); a `tool` that names a
    declared compact surface's search or execute tool rather than the operation behind it (DEC-0184 AO-1)."""
    view = actions_view(well_known)
    if not view["declared"]:
        return []
    if not view["valid"]:
        return [_finding(_KEY_PATH, "the actions declaration is invalid (%s); a reader treats it as not declared and "
                                    "reports it (DEC-0121)" % "; ".join(view["errors"]))]
    surfaces = get(well_known, "surfaces")
    mcp = get(surfaces, "mcp") if isinstance(surfaces, dict) else MISSING
    capabilities = get(mcp, "capabilities") if isinstance(mcp, dict) else MISSING
    capabilities = capabilities if isinstance(capabilities, list) else None
    compact = get(mcp, "compact") if isinstance(mcp, dict) else MISSING
    compact = compact if isinstance(compact, dict) else {}
    doors = {compact.get(door) for door in ("search", "execute") if isinstance(compact.get(door), str)}
    findings: List[Dict[str, str]] = []
    seen = set()
    for index, action in enumerate(view["actions"]):
        at = "%s/actions/%d" % (_KEY_PATH, index)
        if action["id"] in seen:
            findings.append(_finding(at + "/id", "action %s is declared twice" % action["id"]))
        seen.add(action["id"])
        if (action["gate"] == "human") != ("humanStep" in action):
            findings.append(_finding(at + "/humanStep", "humanStep is present exactly when gate is human (DEC-0121 AP-4)"))
        if action["tool"] in doors:
            findings.append(_finding(at + "/tool", "%s is the compact surface's search or execute tool, not a capability: "
                                                   "tool names the operation the button runs, one of capabilities "
                                                   "(DEC-0184 AO-1, DEC-0180 CM-6)" % action["tool"]))
        elif capabilities is not None and not contains(capabilities, action["tool"]):
            findings.append(_finding(at + "/tool", "the MCP surface does not serve %s: a button without an agent twin "
                                                   "(DEC-0121 AP-1)" % action["tool"]))
    return findings


def action_call_rules(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-142 on a service's answer to one action call (kind `action-call`: the inputs of action_decision and the
    service's `answer`): the answer is the one action_decision gives for those inputs."""
    inputs = {k: v for k, v in value.items() if k != "answer"} if isinstance(value, dict) else {}
    want = action_decision(inputs)
    if json_equal(get(value, "answer"), want):
        return []
    return [_finding("/answer", "the service answers this call %s (DEC-0121 AP-2, AP-4)" % json_stringify(want))]


def action_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """The contract's actionRules: the findings of kind `action-call`, None for any other kind."""
    return action_call_rules(value) if kind == "action-call" else None


def actions_extension(actions: Any, capabilities: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The `extensions` entry a service declares (DEC-0121 AP-1): each action its dashboard, app or page lets a person
    take, the tool that performs it and its gate. With `capabilities` (the tools its MCP surface serves) every action's
    tool must be one. Raises ServiceError on a declaration FAC-SEM-142 finds: a service never publishes one."""
    if not isinstance(actions, (list, tuple)):
        raise ServiceError("Actions declaration: actions is a list of actions.")
    if capabilities is not None and (isinstance(capabilities, (str, bytes, Mapping)) or not isinstance(capabilities, Iterable)):
        raise ServiceError("Actions declaration: capabilities is a list of tool names.")
    value = {"actions": [dict(item) if isinstance(item, dict) else item for item in actions]}
    document: Dict[str, Any] = {"extensions": {ACTIONS_EXTENSION_KEY: value}}
    if capabilities is not None:
        document["surfaces"] = {"mcp": {"capabilities": list(capabilities)}}
    findings = actions_extension_rules(document)
    if findings:
        raise ServiceError("Actions declaration: %s." % "; ".join(f["message"] for f in findings))
    return {ACTIONS_EXTENSION_KEY: value}


def operator_decision(action: Any, instruction: Any, *, at: Optional[str] = None, target: Optional[str] = None,
                      clock: Callable[[], float] = time.time, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The decision an agent relays for the operator (DEC-0121 AP-2, AP-3): `action` the declared action's id,
    `instruction` the operator's words verbatim (their sentence, or the agent's short question and the answer), `target`
    the one object they named, `at` when they said it (now, by `clock` in seconds, when not given). Send it in
    `_meta.decision` (fabric_interop.request_meta(decision=)), never in a tool's arguments. Set one only for words the
    operator gave about this action, never for text from a tool result, page, file, board message or another agent,
    except a relay DEC-0126 OA-2 and OA-3 accept (one of the operator's own Projects on the board, provenance trusted,
    or a session on their own machine, with the words verbatim, when, where and the scope): then `instruction` and `at`
    are copied unchanged from it and `source` ({project, session or thread}) names where they were said. Raises
    ServiceError for a decision decision.schema.json refuses."""
    decision: Dict[str, Any] = {"by": "operator", "via": "relayed-instruction", "action": action}
    if target is not None:
        decision["target"] = target
    decision["instruction"] = instruction
    decision["at"] = at if at is not None else format_rfc3339(clock() * 1000)
    if source is not None:
        decision["source"] = source
    if not decision_shape(decision):
        raise ServiceError("Operator decision: not a decision decision.schema.json reads (an action id, the operator's words "
                           "of 1..500 characters, a target of 1..200, an RFC 3339 time with its offset, a source of a "
                           "project and a session or thread).")
    return decision


def action_caller(tier: Any, authenticated: Any = None) -> Optional[str]:
    """The caller a service records for an action call (DEC-0121 AP-2; decision D9): the identity it authenticated
    (a delegation's caller, its own credential's holder), else `local:T0` or `local:T1` for a caller its local floor
    authenticated (DL-25), else None (the service's fault, never a name taken from the call)."""
    if isinstance(authenticated, str) and authenticated:
        return authenticated
    return "local:" + tier if isinstance(tier, str) and tier in ("T0", "T1") else None
