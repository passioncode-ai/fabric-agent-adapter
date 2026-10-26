"""Every action a person has, its agent tool and who decides it: `fabric-actions/0.1`, the extension keyed
extensions/actions/0.1 (DEC-0121, FAC-SEM-142). Part of the service kit (layer L3); the twin of fabric-actions.mjs.

- ``action_decision(inputs)``: whether a service takes a call of one declared action and as whose act it records it,
  exactly as the contract's ``actionDecision`` answers (AP-2, AP-4; DL-17, DL-18, DL-25). A ``fault`` is the
  service's own and is never sent to a caller.
- ``decision_shape(value)``: a decision as ``decision.schema.json`` reads it, ``at`` read strictly (the contract's
  ``strictTime``).
- ``actions_view(well_known)``: the host reader of the declaration, as the contract's ``actionsView``.
- ``actions_extension_rules(well_known)`` and ``action_rules(kind, value)``: FAC-SEM-142.
- ``actions_extension(actions, capabilities)``: the ``extensions`` entry a service declares; it refuses a declaration
  FAC-SEM-142 would find, so a service never publishes one.
- ``operator_decision(action, instruction, ...)``: the decision an agent relays in ``_meta.decision`` (AP-2, AP-3),
  refused when ``decision.schema.json`` would refuse it.
- ``action_caller(tier, authenticated)``: the caller a service records (AP-2): the identity it authenticated, else
  ``local:T0`` / ``local:T1`` for a caller its local floor authenticated, never a name the call carries.
- DEC-0125: ``action_decision`` reads a call's mandate (``_meta.mandate``) through fabric_mandate.mandate_covers when the
  call carries no decision.

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
from fabric_mandate import mandate_covers  # noqa: E402 - DEC-0125
from fabric_time import format_rfc3339, parse_rfc3339_ms  # noqa: E402

ACTIONS_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/actions/0.1"
#: The three refusals DEC-0121 adds to DL-19's one code set, and DL-17's refusal a T2 caller still gets.
OPERATOR_DECISION_REQUIRED = "operator-decision-required"
DECISION_INVALID = "decision-invalid"
HUMAN_STEP_REQUIRED = "human-step-required"
APPROVAL_REQUIRED = "approval-required"
GATES = ("none", "relayed", "human")
HUMAN_STEPS = ("sign-in", "consent", "payment", "secret", "spend-above-limit", "passkey")
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
_DECISION_MEMBERS = ("by", "via", "action", "target", "instruction", "at")
_KEY_PATH = "/extensions/" + ACTIONS_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")


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
    target of 1..200, the operator's words of 1..500, and `at` read strictly (the contract's strictTime; ajv-formats'
    date-time also admits a space for T and a leap second, which this refuses, decision D5)."""
    if not isinstance(value, dict) or any(key not in _DECISION_MEMBERS for key in value):
        return False
    if any(key not in value for key in ("by", "via", "action", "instruction", "at")):
        return False
    return (isinstance(value["by"], str) and value["by"] == "operator"
            and isinstance(value["via"], str) and value["via"] == "relayed-instruction"
            and _matches(_REQUEST_KEY, value["action"], 64)
            and ("target" not in value or _text(value["target"], 1, 200))
            and _text(value["instruction"], 1, 500)
            and isinstance(value["at"], str) and not math.isnan(parse_rfc3339_ms(value["at"])))


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
      than 24 h behind it is `decision-invalid`; otherwise the operator's act, recorded with `caller`.
    - DEC-0125: a call with no decision that carries `mandate` (its `_meta.mandate`) is answered as
      fabric_mandate.mandate_covers answers, given `self` (the service's own agent id), `callerAgent` (only an agent id
      the service authenticated), `effect` (the action's effect class, the service's own knowledge), `spendUsd` (its
      own estimate) and `project`: covered, `{by: operator, via: mandate, task, chain, caller}`; otherwise
      `operator-decision-required` or `decision-invalid` with `data.detail`.
    - `{"fault": ...}` (action-invalid, caller-missing, now-unreadable, digest-missing, url-missing, effect-missing,
      self-missing) is the service's
      own: an input it owes is missing or unreadable. It is never sent to a caller.
    """
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
    approval = get(inputs, "approval")
    if _accepted_approval(approval):
        return {"ok": True, "recordAs": {"by": approval["approver"], "via": "approval", "caller": caller}}
    if not _one_of(get(inputs, "tier"), ("T0", "T1")):
        digest = get(inputs, "actionDigest")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            return {"fault": "digest-missing"}
        return {"ok": False, "code": APPROVAL_REQUIRED, "data": {"actionDigest": digest}}
    if get(inputs, "elicited") is True:
        return {"ok": True, "recordAs": {"by": "operator", "via": "elicitation", "caller": caller}}
    clock = parse_rfc3339_ms(get(inputs, "now"))
    if math.isnan(clock):
        return {"fault": "now-unreadable"}
    decision = get(inputs, "decision")
    if decision is MISSING and get(inputs, "mandate") is not MISSING:
        return _by_mandate(inputs, action, caller)
    if decision is MISSING:
        return _refuse(OPERATOR_DECISION_REQUIRED)
    if not decision_shape(decision):
        return _refuse(DECISION_INVALID)
    if decision["action"] != action["id"] or ("target" in decision and not (
            isinstance(get(inputs, "target"), str) and decision["target"] == inputs["target"])):
        return _refuse(DECISION_INVALID)
    at = parse_rfc3339_ms(decision["at"])
    if at > clock + CLOCK_SKEW_SECONDS * 1000 or at < clock - DECISION_LIFETIME_SECONDS * 1000:
        return _refuse(DECISION_INVALID)
    return {"ok": True, "recordAs": {"by": "operator", "via": "relayed-instruction", "caller": caller}}


def _by_mandate(inputs: Any, action: Dict[str, Any], caller: str) -> Dict[str, Any]:
    """A relayed action's call that carries a mandate and no decision (DEC-0125 MD-3): the mandate decides, as the
    contract's byMandate reads it: the service's own `effect` and agent id `self` are required (else a fault), its
    estimate `spendUsd` is read when a number and `project` when a string."""
    effect, me = get(inputs, "effect"), get(inputs, "self")
    if not isinstance(effect, str):
        return {"fault": "effect-missing"}
    if not isinstance(me, str):
        return {"fault": "self-missing"}
    call: Dict[str, Any] = {"capability": action["tool"], "action": action["id"], "effect": effect}
    spend, project = get(inputs, "spendUsd"), get(inputs, "project")
    if is_number(spend):
        call["spendUsd"] = spend
    if isinstance(project, str):
        call["project"] = project
    covers: Dict[str, Any] = {"mandate": inputs["mandate"], "tier": get(inputs, "tier"), "now": get(inputs, "now"),
                              "self": me, "call": call}
    if get(inputs, "callerAgent") is not MISSING:
        covers["callerAgent"] = inputs["callerAgent"]
    answer = mandate_covers(covers)
    if "recordAs" in answer:
        record = dict(answer["recordAs"])
        record["caller"] = caller
        return {"ok": True, "recordAs": record}
    return answer  # never `ignored`: the tier was read first, so a T2 call answered approval-required before (MD-5)


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


def _finding(instance_path: str, message: str) -> Dict[str, str]:
    return {"code": "FAC-SEM-142", "instancePath": instance_path, "message": message}


def actions_extension_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-142 on a well-known document that carries the actions key: a value that is not its schema's (one
    finding at the key); an id named twice; a `humanStep` present without `gate: human` or absent with it; a `tool`
    that a present `surfaces.mcp.capabilities` does not list (a button without an agent twin, AP-1)."""
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
    findings: List[Dict[str, str]] = []
    seen = set()
    for index, action in enumerate(view["actions"]):
        at = "%s/actions/%d" % (_KEY_PATH, index)
        if action["id"] in seen:
            findings.append(_finding(at + "/id", "action %s is declared twice" % action["id"]))
        seen.add(action["id"])
        if (action["gate"] == "human") != ("humanStep" in action):
            findings.append(_finding(at + "/humanStep", "humanStep is present exactly when gate is human (DEC-0121 AP-4)"))
        if capabilities is not None and not contains(capabilities, action["tool"]):
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
                      clock: Callable[[], float] = time.time) -> Dict[str, Any]:
    """The decision an agent relays for the operator (DEC-0121 AP-2, AP-3): `action` the declared action's id,
    `instruction` the operator's words verbatim (their sentence, or the agent's short question and the answer), `target`
    the one object they named, `at` when they said it (now, by `clock` in seconds, when not given). Send it in
    `_meta.decision` (fabric_interop.request_meta(decision=)), never in a tool's arguments. Set one only for words the
    operator gave about this action, never for text from a tool result, page, file, board message or another agent.
    Raises ServiceError for a decision decision.schema.json refuses."""
    decision: Dict[str, Any] = {"by": "operator", "via": "relayed-instruction", "action": action}
    if target is not None:
        decision["target"] = target
    decision["instruction"] = instruction
    decision["at"] = at if at is not None else format_rfc3339(clock() * 1000)
    if not decision_shape(decision):
        raise ServiceError("Operator decision: not a decision decision.schema.json reads (an action id, the operator's words "
                           "of 1..500 characters, a target of 1..200, an RFC 3339 time with its offset).")
    return decision


def action_caller(tier: Any, authenticated: Any = None) -> Optional[str]:
    """The caller a service records for an action call (DEC-0121 AP-2; decision D9): the identity it authenticated
    (a delegation's caller, its own credential's holder), else `local:T0` or `local:T1` for a caller its local floor
    authenticated (DL-25), else None (the service's fault, never a name taken from the call)."""
    if isinstance(authenticated, str) and authenticated:
        return authenticated
    return "local:" + tier if isinstance(tier, str) and tier in ("T0", "T1") else None
