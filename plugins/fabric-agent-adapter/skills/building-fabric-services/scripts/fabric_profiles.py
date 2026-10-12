#!/usr/bin/env python3
"""Runner and model profiles in the kit (Fabric Agent Contract DEC-0046, Fabric ADR-0147). A port of the contract's
`src/profile-rules.ts` at the pin — `resolve_model_profile` and the FAC-SEM-058…060 checks — held to the contract's own
answers by test/fixtures/contract/profile-vectors.json; plus what a service does with them: the doctor's runner and
model checks (runners.md C2) and the well-known `configuration` with its summary tiles ("Runner & model").

    import fabric_profiles as fp
    resolution = fp.resolve_model_profile(catalogue=catalogue, profiles=profiles, choices={"binding": "default"}, policy=policy)
    configuration = fp.configuration(["runner", "model"], resolution, runner_profile)   # well-known `configuration`
    summary += fp.configuration_summary(configuration)                                    # the dashboard's tiles
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Sequence

import fabric_secrets as _secrets
import fabric_service as _fs

RESOLUTION_ORDER = ("request", "agent", "binding", "estate")
# The vendor login each subscription is, and the one runner kind it runs in (DEC-0046, ADR-0147 decision 2).
SUBSCRIPTION_RUNNER = {"claude": "claude-code", "kimi": "kimi-code", "chatgpt": "codex"}
MAX_PROBE_MS = 5000
_BARE_BINARY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProfileError(ValueError):
    pass


def _list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _js_string(value: Any) -> str:
    """JavaScript's String(value), which the contract's messages and policy ids use."""
    if value is None:
        return "undefined"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return "[object Object]" if isinstance(value, dict) else ",".join(_js_string(v) for v in value)
    return str(value)


def _js_number(value: Any) -> Optional[float]:
    """JavaScript's Number(value); NaN is None (JSON writes it as null)."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value if not (isinstance(value, float) and math.isnan(value)) else None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return 0
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def resolve_model_profile(*, catalogue: Any, profiles: Any, choices: Any, policy: Any = None) -> Dict[str, Any]:
    """FAC-SEM-060: the request's profile, else the agent's, else the binding's or project's, else the estate default.
    When the project's policy names `modelClasses`, a model stays only if every class the catalogue gives it is
    allowed; an empty result refuses the launch, naming the policy."""
    choices = choices if isinstance(choices, dict) else {}
    level = next((name for name in RESOLUTION_ORDER if isinstance(choices.get(name), str)), None)
    if level is None:
        return {"refused": "no-profile"}
    profile_id = choices[level]
    profile = next((item for item in _list(profiles) if item.get("id") == profile_id), None)
    if profile is None:
        return {"refused": "unknown-profile", "profile": profile_id}
    models = _strings(profile.get("models"))
    if not isinstance(policy, dict) or not isinstance(policy.get("modelClasses"), list):
        return {"from": level, "profile": profile_id, "models": models}
    allowed = set(_strings(policy["modelClasses"]))
    rows = {}
    for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None):
        rows[json.dumps(row.get("id"))] = row
    within = [m for m in models if json.dumps(m) in rows and all(c in allowed for c in _strings(rows[json.dumps(m)].get("classes")))]
    if within:
        return {"from": level, "profile": profile_id, "models": within}
    meta = policy.get("meta") if isinstance(policy.get("meta"), dict) else {}
    return {"refused": "model-classes-empty", "profile": profile_id, "policy": {"id": _js_string(meta.get("id")), "revision": _js_number(meta.get("revision"))}}


def _finding(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": path, "message": message}


def _model_catalogue(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings, seen = [], []
    for index, row in enumerate(_list(value.get("models"))):
        if row.get("id") in seen:
            findings.append(_finding("FAC-SEM-058", "/models/%d/id" % index, "model %s is catalogued more than once" % _js_string(row.get("id"))))
        seen.append(row.get("id"))
        routing = row.get("provider") if isinstance(row.get("provider"), dict) else {}
        ignored = set(_strings(routing.get("ignore")))
        for slug in _strings(routing.get("order")):
            if slug in ignored or slug.split("/")[0] in ignored:
                findings.append(_finding("FAC-SEM-058", "/models/%d/provider" % index, "model %s both orders and ignores provider %s" % (_js_string(row.get("id")), slug)))
    return findings


def _model_profiles(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings, seen = [], []
    for index, profile in enumerate(_list(value.get("profiles"))):
        if profile.get("id") in seen:
            findings.append(_finding("FAC-SEM-058", "/profiles/%d/id" % index, "model profile %s is declared more than once" % _js_string(profile.get("id"))))
        seen.append(profile.get("id"))
    return findings


def _runner_profile(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings = []
    if value.get("route") == "subscription" and isinstance(value.get("subscription"), dict):
        login = _js_string(value["subscription"].get("login"))
        runner = SUBSCRIPTION_RUNNER.get(login)
        if runner != value.get("runnerKind"):
            findings.append(_finding("FAC-SEM-059", "/runnerKind", "a %s subscription runs only in %s, not in %s; another runner takes the key route"
                                     % (login, runner if runner is not None else "its vendor's runner", _js_string(value.get("runnerKind")))))
    if value.get("route") == "key" and isinstance(value.get("key"), dict):
        key = value["key"]
        if key.get("modelAllowList") != value.get("modelProfile") or ("modelAllowList" in key) != ("modelProfile" in value):
            findings.append(_finding("FAC-SEM-059", "/key/modelAllowList", "the key admits the models of %s, but the profile runs %s"
                                     % (_js_string(key.get("modelAllowList")), _js_string(value.get("modelProfile")))))
        if isinstance(key.get("ref"), str) and _secrets.secret_value(key["ref"]):
            findings.append(_finding("FAC-SEM-059", "/key/ref", "the key is named by its secret reference, never by its value"))
    return findings


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _profile_resolution(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings = []
    catalogue = value.get("catalogue")
    catalogued = [row.get("id") for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None)]
    ids: List[Any] = []
    for i, profile in enumerate(_list(value.get("profiles"))):
        if profile.get("id") in ids:
            findings.append(_finding("FAC-SEM-060", "/profiles/%d/id" % i, "profile id %s is offered more than once to one resolution" % _js_string(profile.get("id"))))
        ids.append(profile.get("id"))
        for j, model in enumerate(_strings(profile.get("models"))):
            if model not in catalogued:
                findings.append(_finding("FAC-SEM-060", "/profiles/%d/models/%d" % (i, j), "profile %s names %s, which the catalogue does not hold" % (_js_string(profile.get("id")), model)))
    choices = value.get("choices") if isinstance(value.get("choices"), dict) else {}
    expected = resolve_model_profile(catalogue=catalogue, profiles=value.get("profiles"), choices=choices, policy=value.get("policy"))
    if "resolved" not in value or value["resolved"] != expected:
        findings.append(_finding("FAC-SEM-060", "/resolved", "the resolution is %s" % _compact(expected)))
    return findings


def profile_problems(kind: str, value: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """The contract's profileRules: findings for a `model-catalogue`, `model-profiles`, `runner-profile` or
    `profile-resolution` document; None for another kind."""
    return {"model-catalogue": _model_catalogue, "model-profiles": _model_profiles, "runner-profile": _runner_profile,
            "profile-resolution": _profile_resolution}.get(kind, lambda v: None)(value)


# --- the doctor's checks ----------------------------------------------------------------------------------------

def _argv(value: Any, label: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
        raise ProfileError("%s is an argument array, never a shell string" % label)
    return list(value)


def runner_check(entry: Dict[str, Any], *, path: Optional[str] = None,
                 run: Callable[..., Any] = subprocess.run) -> Dict[str, Any]:
    """runners.md C2: is the catalogued runner installed, which version answers, and is it signed in. Only a bare
    catalogued binary found on PATH is run, only with the catalogued version argv (and `auth` argv), without a shell,
    within its timeout (at most 5 s). A catalogue entry outside these rules is refused and nothing runs.

    ``probe`` is the contract's closed probe result for a walk (DEC-0026): ``not-installed`` (no catalogued binary on
    PATH), ``not-responding`` (the version probe did not answer, failed or did not match the catalogue's pattern),
    ``not-connected`` (it answers, but the ``auth`` probe says signed out), or None when the runner can serve."""
    kind = entry.get("kind")
    binaries = entry.get("binaries")
    if not isinstance(binaries, list) or not binaries or not all(isinstance(b, str) and _BARE_BINARY.match(b) and ".." not in b for b in binaries):
        raise ProfileError("binaries are bare executable names, never paths")
    version = entry.get("version") if isinstance(entry.get("version"), dict) else {}
    version_argv = _argv(version.get("argv"), "version.argv")
    pattern = version.get("pattern")
    if not isinstance(pattern, str):
        raise ProfileError("version.pattern is a regular expression")
    timeout_ms = version.get("timeoutMs", MAX_PROBE_MS)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 0 < timeout_ms <= MAX_PROBE_MS:
        raise ProfileError("version.timeoutMs is at most %d" % MAX_PROBE_MS)
    auth_argv = _argv(entry["auth"], "auth") if "auth" in entry else None
    out: Dict[str, Any] = {"kind": kind, "installed": False, "binary": None, "version": None, "signedIn": None,
                           "probe": "not-installed", "problems": []}
    binary = next((found for found in (shutil.which(name, path=path) for name in binaries) if found), None)
    if binary is None:
        out["problems"].append("%s is not installed: none of %s is on PATH" % (kind, ", ".join(binaries)))
        return out
    out["probe"] = "not-responding"
    out.update(installed=True, binary=binary)

    def probe(argv: List[str]) -> Optional[Any]:
        try:
            return run([binary] + argv, capture_output=True, text=True, timeout=timeout_ms / 1000.0, shell=False)
        except subprocess.TimeoutExpired:
            out["problems"].append("%s %s did not answer within %d ms" % (kind, " ".join(argv), timeout_ms))
        except OSError as exc:
            out["problems"].append("%s could not be run: %s" % (kind, exc.__class__.__name__))
        return None

    answered = probe(version_argv)
    if answered is not None:
        match = re.search(pattern, answered.stdout or "") or re.search(pattern, answered.stderr or "")
        if match and match.groups():
            out["version"] = match.group(1)
        else:
            out["problems"].append("%s answered, but its version did not match the catalogue's pattern" % kind)
    signed = probe(auth_argv) if auth_argv is not None else None
    if signed is not None:
        out["signedIn"] = signed.returncode == 0
        if not out["signedIn"]:
            out["problems"].append("%s is installed but not signed in" % kind)
    # The walk's order (runners.md): installed, then responding, then connected. The doctor still reports every problem.
    if out["version"] is None or (auth_argv is not None and signed is None):
        out["probe"] = "not-responding"
    elif out["signedIn"] is False:
        out["probe"] = "not-connected"
    else:
        out["probe"] = None
    return out


def model_usable(model: str, catalogue: Any, policy: Any = None) -> List[str]:
    """Problems with running `model` here: not in the catalogue, or a class the project's policy does not allow."""
    rows = {row.get("id"): row for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None)}
    if model not in rows:
        return ["model %s is not in the model catalogue" % model]
    if isinstance(policy, dict) and isinstance(policy.get("modelClasses"), list):
        allowed = set(_strings(policy["modelClasses"]))
        outside = [c for c in _strings(rows[model].get("classes")) if c not in allowed]
        if outside:
            meta = policy.get("meta") if isinstance(policy.get("meta"), dict) else {}
            return ["model %s has class %s, which policy %s does not allow" % (model, ", ".join(outside), _js_string(meta.get("id")))]
    return []


# --- the well-known `configuration` and its tiles --------------------------------------------------------------

def configuration(slots: Sequence[str], resolution: Dict[str, Any], runner_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The well-known `configuration` (DEC-0046): the configurable slots, and the profiles that apply now. Read-only:
    a change is made in Fabric and reaches the agent through its binding."""
    if "refused" in resolution:
        raise ProfileError("the resolution was refused (%s); a refused resolution is not a configuration" % resolution["refused"])
    resolved: Dict[str, Any] = {"from": resolution.get("from")}
    if runner_profile:
        resolved.update(runnerProfile=runner_profile.get("id"), runnerKind=runner_profile.get("runnerKind"), route=runner_profile.get("route"))
    resolved.update(modelProfile=resolution.get("profile"), models=list(resolution.get("models") or []))
    doc = {"slots": list(slots), "resolved": {k: v for k, v in resolved.items() if v is not None}}
    problems = _fs.configuration_problems(doc)
    if problems:
        raise ProfileError("; ".join(problems))
    return doc


def configuration_summary(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Summary tiles for the well-known document and the dashboard — "Runner & model"."""
    resolved = doc.get("resolved") or {}
    tiles = []
    if resolved.get("runnerKind"):
        tiles.append({"label": "Runner", "value": " · ".join(x for x in (resolved.get("runnerKind"), resolved.get("route")) if x)})
    if resolved.get("modelProfile"):
        first = (resolved.get("models") or [None])[0]
        tiles.append({"label": "Model", "value": " · ".join(x for x in (resolved["modelProfile"], first) if x)})
    return tiles


# --- runner routes (DEC-0026, DEC-0029; FAC-SEM-028…034) ----------------------------------------------------------
# The contract's routeRules (src/route-rules.ts), ported finding for finding: code, path and message.

#: The closed probe results a walk records for a candidate it passed over (runner-route-event.schema.json).
PROBE_RESULTS = ("not-catalogued", "not-admitted", "not-installed", "not-responding", "not-connected", "no-held-session",
                 "quota-unknown", "refused", "spawn-failed")
_MISSING = object()


def _field(value: Dict[str, Any], key: str) -> str:
    """String(value[key]) as JavaScript writes it: `undefined` for a missing key, `null` for null."""
    found = value.get(key, _MISSING) if isinstance(value, dict) else _MISSING
    if found is _MISSING:
        return "undefined"
    if found is None:
        return "null"
    return _js_string(found)


def _object_at(value: Any, key: str) -> Dict[str, Any]:
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, dict) else {}


def _ref_key(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    return "%s@%s#%s" % (_field(ref, "id"), _field(ref, "revision"), _field(ref, "contentHash"))


def _same_ref(a: Any, b: Any) -> bool:
    return _ref_key(a) != "" and _ref_key(a) == _ref_key(b)


def _candidates(value: Any) -> List[Dict[str, Any]]:
    return _list(value.get("candidates") if isinstance(value, dict) else None)


def _runner_route(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings, kinds = [], set()
    for index, candidate in enumerate(_candidates(value)):
        kind = _field(candidate, "runnerKind")
        if kind in kinds:
            findings.append(_finding("FAC-SEM-028", "/candidates/%d/runnerKind" % index, "runner kind %s appears in the route more than once" % kind))
        kinds.add(kind)
        session = _object_at(candidate, "session")
        if session.get("attach") == "never" and session.get("spawn") == "never":
            findings.append(_finding("FAC-SEM-029", "/candidates/%d/session" % index, 'candidate %s can never run: attach and spawn are both "never"' % kind))
    return findings


def _route_bundle(value: Dict[str, Any]) -> List[Dict[str, str]]:
    route = _object_at(value, "route")
    admitted = {_ref_key(a.get("provider")) for a in _list(value.get("admissions"))
                if a.get("state") == "admitted" and a.get("capability", _MISSING) == route.get("capability", _MISSING)}
    findings = []
    for index, candidate in enumerate(_candidates(route)):
        key = _ref_key(candidate.get("provider"))
        if key not in admitted:
            findings.append(_finding("FAC-SEM-030", "/route/candidates/%d/provider" % index, "candidate %s names provider %s, which is not a revision admitted for %s"
                                     % (_field(candidate, "runnerKind"), key, _field(route, "capability"))))
    if isinstance(value.get("binding"), dict):
        findings.extend(_binding_agreement(value["binding"], route))
    if isinstance(value.get("catalogue"), list):
        findings.extend(_catalogue_agreement(_list(value["catalogue"]), route))
    return findings


def _binding_agreement(binding: Dict[str, Any], route: Dict[str, Any]) -> List[Dict[str, str]]:
    findings = []

    def disagree(path: str, message: str) -> None:
        findings.append(_finding("FAC-SEM-032", "/binding/" + path, message))

    if binding.get("project", _MISSING) != route.get("project", _MISSING):
        disagree("project", "the binding is for %s, the route for %s" % (_field(binding, "project"), _field(route, "project")))
    if binding.get("capability", _MISSING) != route.get("capability", _MISSING):
        disagree("capability", "the binding binds %s, the route orders %s" % (_field(binding, "capability"), _field(route, "capability")))
    if binding.get("profileKind") != "local-runner":
        disagree("profileKind", "a runner route serves the local-runner profile, not %s" % _field(binding, "profileKind"))
    if not any(_same_ref(c.get("provider"), binding.get("provider")) for c in _candidates(route)):
        disagree("provider", "the binding's provider %s is not a candidate of the route" % _ref_key(binding.get("provider")))
    if "runnerRoute" in binding and not _same_ref(binding["runnerRoute"], route.get("meta")):
        disagree("runnerRoute", "the binding pins %s, not this route %s" % (_ref_key(binding["runnerRoute"]), _ref_key(route.get("meta"))))
    return findings


def _catalogue_agreement(catalogue: List[Dict[str, Any]], route: Dict[str, Any]) -> List[Dict[str, str]]:
    by_kind = {_field(entry, "kind"): entry for entry in catalogue}
    findings = []
    for index, candidate in enumerate(_candidates(route)):
        kind = _field(candidate, "runnerKind")
        entry = by_kind.get(kind)
        if entry is None:
            findings.append(_finding("FAC-SEM-033", "/route/candidates/%d/runnerKind" % index, "runner kind %s has no entry in the host's catalogue" % kind))
            continue
        if "drive" in candidate and _field(candidate, "drive") not in _object_at(entry, "drives"):
            findings.append(_finding("FAC-SEM-033", "/route/candidates/%d/drive" % index, "the catalogue entry for %s offers no drive %s" % (kind, _field(candidate, "drive"))))
    return findings


def _index_of(ref: Dict[str, Any]) -> int:
    index = ref.get("index")
    if isinstance(index, bool) or not isinstance(index, (int, float)) or not float(index).is_integer():
        return -1
    return int(index)


def _route_event(value: Dict[str, Any]) -> List[Dict[str, str]]:
    route = _object_at(value, "route")
    event = _object_at(value, "event")
    candidates = _candidates(route)
    findings: List[Dict[str, str]] = []

    def wrong(path: str, message: str) -> None:
        findings.append(_finding("FAC-SEM-034", "/event" + path, message))

    if not _same_ref(event.get("route"), route.get("meta")):
        wrong("/route", "the event names route %s, not %s" % (_ref_key(event.get("route")), _ref_key(route.get("meta"))))
    if event.get("project", _MISSING) != route.get("project", _MISSING):
        wrong("/project", "the event is for %s, the route for %s" % (_field(event, "project"), _field(route, "project")))
    if event.get("capability", _MISSING) != route.get("capability", _MISSING):
        wrong("/capability", "the event names %s, the route orders %s" % (_field(event, "capability"), _field(route, "capability")))

    def candidate_at(ref: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
        index = _index_of(ref)
        candidate = candidates[index] if 0 <= index < len(candidates) else None
        if (candidate is None or candidate.get("runnerKind", _MISSING) != ref.get("runnerKind", _MISSING)
                or ("provider" in ref and not _same_ref(candidate.get("provider"), ref["provider"]))):
            wrong(path, "candidate %s (%s) is not that position of the route" % (_field(ref, "index"), _field(ref, "runnerKind")))
            return None
        return candidate

    probes = _list(event.get("probes"))
    for position, probe in enumerate(probes):
        candidate = candidate_at(probe, "/probes/%d" % position)
        if candidate is not None and probe.get("result") == "no-held-session" and _object_at(candidate, "session").get("spawn") != "never":
            wrong("/probes/%d/result" % position, "%s may spawn, so finding no held session does not pass it over" % _field(probe, "runnerKind"))
        if candidate is not None and probe.get("result") == "spawn-failed" and _object_at(candidate, "session").get("spawn") != "allowed":
            wrong("/probes/%d/result" % position, "%s has spawn: never, so it cannot have failed to spawn" % _field(probe, "runnerKind"))

    def expect_probes(count: int) -> None:
        indexes = [_index_of(p) for p in probes]
        expected = list(range(max(count, 0)))
        if indexes != expected:
            wrong("/probes", "the walk must record candidates %s in order; it records %s"
                  % (", ".join(map(str, expected)) or "none", ", ".join(map(str, indexes)) or "none"))

    if event.get("kind") == "runner-exhausted":
        expect_probes(len(candidates))
        if event.get("answer") == "held" and route.get("exhausted") != "hold":
            wrong("/answer", "the route does not declare exhausted: hold, so an exhausted walk answers capability-unavailable")
        return findings

    selected = _object_at(event, "selected")
    chosen = candidate_at(selected, "/selected")
    if chosen is not None:
        session = _object_at(chosen, "session")
        if selected.get("session") == "attached" and session.get("attach") != "preferred":
            wrong("/selected/session", "%s has attach: never, so the host cannot attach it" % _field(selected, "runnerKind"))
        if selected.get("session") == "spawned" and session.get("spawn") != "allowed":
            wrong("/selected/session", "%s has spawn: never, so the host cannot spawn it" % _field(selected, "runnerKind"))
        if "drive" in chosen and "drive" in selected and selected["drive"] != chosen["drive"]:
            wrong("/selected/drive", "the route runs %s through %s, not %s" % (_field(selected, "runnerKind"), _field(chosen, "drive"), _field(selected, "drive")))
        if event.get("sticky") is True:
            # A sticky relaunch keeps the conversation's runner and walks nothing above it.
            if route.get("recovery") == "reprobe":
                wrong("/sticky", "a route with recovery: reprobe walks from the top at every launch")
            if "conversation" not in event:
                wrong("/sticky", "only a conversation can keep its runner")
            expect_probes(0)
        else:
            expect_probes(_index_of(selected))

    if event.get("kind") == "runner-switched":
        source = _object_at(event, "from")
        candidate_at(source, "/from")
        if _index_of(source) == _index_of(selected):
            wrong("/from", "a switch moves to another candidate")
        if event.get("reason") == "preferred-available":
            if route.get("recovery") != "reprobe":
                wrong("/reason", "only a route with recovery: reprobe moves a conversation back to a preferred runner")
            if not _index_of(selected) < _index_of(source):
                wrong("/reason", "preferred-available moves to a higher-preference candidate")
    return findings


def route_problems(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """The contract's routeRules: findings for a `runner-route` (FAC-SEM-028, 029), a `route-bundle`
    `{route, admissions, binding?, catalogue?}` (030, 032, 033) or a `route-event` `{route, event}` (034); None for
    another kind or a value that is not an object."""
    if not isinstance(value, dict):
        return None
    rules = {"runner-route": _runner_route, "route-bundle": _route_bundle, "route-event": _route_event}.get(kind)
    return rules(value) if rules else None
