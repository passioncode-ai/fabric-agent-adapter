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

import fabric_estate as _estate
import fabric_identifiers as _ids
import fabric_secrets as _secrets
import fabric_service as _fs

RESOLUTION_ORDER = ("request", "agent", "binding", "estate")
# The vendor login each subscription is, and the one runner kind it runs in (DEC-0046, ADR-0147 decision 2).
SUBSCRIPTION_RUNNER = {"claude": "claude-code", "kimi": "kimi-code", "chatgpt": "codex"}
MAX_PROBE_MS = 5000
#: DEC-0083: the model class of a model whose vendor publishes its weights openly — descriptive: a policy admits and
#: excludes nothing by it — and what a lane reads when it reads what a member, a client or the public sends.
OPEN_VENDOR = "open-vendor"
USER_CONTENT = "user-content"
_BARE_BINARY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProfileError(ValueError):
    pass


from fabric_jsvalue import objects as _list  # noqa: E402 - the core's (FAA-65)
from fabric_jsvalue import json_equal as _json_equal  # noqa: E402 - the core's (FAA-65)
from fabric_jsvalue import indexed_objects as _indexed  # noqa: E402 - the core's (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)


_MISSING_KEY = _jsv.MISSING


def _at(value: Any, key: str) -> Any:
    """value[key] as JavaScript reads a member: absent is distinct from null (``_MISSING_KEY``)."""
    return _jsv.get(value, key)




def _without_nan(value: Any) -> Any:
    """A resolution as JSON writes it: NaN and an infinity become null."""
    if isinstance(value, dict):
        return {k: _without_nan(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_nan(v) for v in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value




def _set_key(value: Any) -> Any:
    """A key with JavaScript's Set semantics for a JSON value: 1 and true, null and absent, are different; two objects
    are never the same member however equal."""
    if value is _MISSING_ID:
        return ("undefined",)
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", _jsv.double(value))
    if isinstance(value, str):
        return ("string", value)
    return ("object", id(value))


_MISSING_ID = object()


def _id_of(item: Dict[str, Any]) -> Any:
    return item.get("id", _MISSING_ID)


def _strings(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def resolve_model_profile(*, catalogue: Any = None, profiles: Any = None, choices: Any = None, policy: Any = None) -> Dict[str, Any]:
    """FAC-SEM-060, as JSON writes the contract's answer (a policy revision that is not a number is null)."""
    return _without_nan(_resolve(catalogue=catalogue, profiles=profiles, choices=choices, policy=policy))


def _resolve(*, catalogue: Any = None, profiles: Any = None, choices: Any = None, policy: Any = None) -> Dict[str, Any]:
    """FAC-SEM-060: the request's profile, else the agent's, else the binding's or project's, else the estate default.
    When the project's policy names `modelClasses`, a model stays only if every class the catalogue gives it is
    allowed; the descriptive class `open-vendor` is not checked (DEC-0083), and a model with no other class does not stay.
    An empty result refuses the launch, naming the policy."""
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
    def admitted(model: str) -> bool:
        row = rows.get(json.dumps(model))
        admission = [c for c in _strings(row.get("classes")) if c != OPEN_VENDOR] if row is not None else []
        return bool(admission) and all(c in allowed for c in admission)
    within = [m for m in models if admitted(m)]
    if within:
        return {"from": level, "profile": profile_id, "models": within}
    meta = policy.get("meta") if isinstance(policy.get("meta"), dict) else {}
    return {"refused": "model-classes-empty", "profile": profile_id,
            "policy": {"id": _jsv.show(_at(meta, "id")), "revision": _jsv.js_to_number(_at(meta, "revision"))}}


def _finding(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": path, "message": message}


def _model_catalogue(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings, seen = [], set()
    for row, index in _indexed(value.get("models")):
        if _set_key(_id_of(row)) in seen:
            findings.append(_finding("FAC-SEM-058", "/models/%d/id" % index, "model %s is catalogued more than once" % _show_id(row)))
        seen.add(_set_key(_id_of(row)))
        routing = row.get("provider") if isinstance(row.get("provider"), dict) else {}
        ignored = set(_strings(routing.get("ignore")))
        for slug in _strings(routing.get("order")):
            if slug in ignored or slug.split("/")[0] in ignored:
                findings.append(_finding("FAC-SEM-058", "/models/%d/provider" % index, "model %s both orders and ignores provider %s" % (_show_id(row), slug)))
    return findings


def _model_profiles(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings, seen = [], set()
    for profile, index in _indexed(value.get("profiles")):
        if _set_key(_id_of(profile)) in seen:
            findings.append(_finding("FAC-SEM-058", "/profiles/%d/id" % index, "model profile %s is declared more than once" % _show_id(profile)))
        seen.add(_set_key(_id_of(profile)))
    return findings


def _runner_profile(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings = []
    if value.get("route") == "subscription" and isinstance(value.get("subscription"), dict):
        login = _jsv.show(_at(value["subscription"], "login"))
        runner = SUBSCRIPTION_RUNNER.get(login, _MISSING_KEY)
        if not _jsv.same(runner, _at(value, "runnerKind")):
            findings.append(_finding("FAC-SEM-059", "/runnerKind", "a %s subscription runs only in %s, not in %s; another runner takes the key route"
                                     % (login, runner if runner is not _MISSING_KEY else "its vendor's runner", _jsv.show(_at(value, "runnerKind")))))
    if value.get("route") == "key" and isinstance(value.get("key"), dict):
        key = value["key"]
        if not _jsv.same(_at(key, "modelAllowList"), _at(value, "modelProfile")):
            findings.append(_finding("FAC-SEM-059", "/key/modelAllowList", "the key admits the models of %s, but the profile runs %s"
                                     % (_jsv.show(_at(key, "modelAllowList")), _jsv.show(_at(value, "modelProfile")))))
        if isinstance(key.get("ref"), str) and _secrets.secret_value(key["ref"]):
            findings.append(_finding("FAC-SEM-059", "/key/ref", "the key is named by its secret reference, never by its value"))
    return findings


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _profile_resolution(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings = []
    catalogue = value.get("catalogue")
    catalogued = [row.get("id") for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None)]
    ids = set()
    for profile, i in _indexed(value.get("profiles")):
        if _set_key(_id_of(profile)) in ids:
            findings.append(_finding("FAC-SEM-060", "/profiles/%d/id" % i, "profile id %s is offered more than once to one resolution" % _show_id(profile)))
        ids.add(_set_key(_id_of(profile)))
        # Every model by its index as written; only a string can name a catalogued model.
        for j, model in enumerate(profile.get("models") if isinstance(profile.get("models"), list) else []):
            if isinstance(model, str) and model not in catalogued:
                findings.append(_finding("FAC-SEM-060", "/profiles/%d/models/%d" % (i, j), "profile %s names %s, which the catalogue does not hold" % (_show_id(profile), model)))
    choices = value.get("choices") if isinstance(value.get("choices"), dict) else {}
    expected = _resolve(catalogue=catalogue, profiles=value.get("profiles"), choices=choices, policy=value.get("policy"))
    if not _json_equal(_at(value, "resolved"), expected):
        findings.append(_finding("FAC-SEM-060", "/resolved", "the resolution is %s" % _jsv.json_stringify(_without_nan(expected))))
    return findings


def closed_user_content_route(profile: Any, catalogue: Any) -> Optional[List[str]]:
    """FAC-SEM-112 (DEC-0083) for one profile: the models that run when the lane reads user content and none of them is
    an open-vendor model, or None when the profile does not read user content or its route has one. Under
    ``between-turns`` every model may run; under ``none``, or any other value (failing closed), only the first. A model
    the catalogue does not hold, or whose row is not ``open-vendor``, counts as closed. Never raises."""
    if not isinstance(profile, dict) or USER_CONTENT not in _strings(profile.get("reads")):
        return None
    models = profile.get("models") if isinstance(profile.get("models"), list) else []
    route = models if profile.get("fallback") == "between-turns" else models[:1]
    open_ids = {row["id"] for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None)
                if isinstance(row.get("id"), str) and OPEN_VENDOR in _strings(row.get("classes"))}
    if any(isinstance(model, str) and model in open_ids for model in route):
        return None
    return [_jsv.show(model) for model in route]


def _closed_route(fallback: Any, closed: List[str]) -> str:
    """How a closed route is named in a finding: under ``between-turns`` all of it, otherwise its first model."""
    return "none of its models is" if fallback == "between-turns" else "its first model, %s, is not" % (closed[0] if closed else "none")


def _open_vendor_routes(value: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-112: a profile that reads user content has an open-vendor route, so the lane never runs on closed vendors
    alone, which refuse the content it exists to handle. The resolution's outcome is held to the same test: when the
    resolved profile reads user content and its own route is open, the models the policy leaves must still give one,
    or the policy is named as what leaves the lane closed (one cause, one finding)."""
    findings = []
    profiles = _list(value.get("profiles"))
    for profile, i in _indexed(value.get("profiles")):
        closed = closed_user_content_route(profile, value.get("catalogue"))
        if closed is None:
            continue
        findings.append(_finding("FAC-SEM-112", "/profiles/%d/models" % i, "profile %s reads user content, but %s open-vendor in "
                                 "the catalogue: the lane would run on closed vendors alone" % (_show_id(profile), _closed_route(profile.get("fallback"), closed))))
    choices = value.get("choices") if isinstance(value.get("choices"), dict) else {}
    outcome = resolve_model_profile(catalogue=value.get("catalogue"), profiles=value.get("profiles"), choices=choices, policy=value.get("policy"))
    if "models" not in outcome:
        return findings
    profile = next((item for item in profiles if item.get("id") == outcome["profile"]), None)  # a string: == is ===
    if profile is None or closed_user_content_route(profile, value.get("catalogue")) is not None:
        return findings
    closed = closed_user_content_route(dict(profile, models=outcome["models"]), value.get("catalogue"))
    if closed is None:
        return findings
    policy = value.get("policy")
    meta = policy.get("meta") if isinstance(policy, dict) and isinstance(policy.get("meta"), dict) else {}
    findings.append(_finding("FAC-SEM-112", "/resolved/models", "the policy %s leaves profile %s's lane on closed vendors alone: of the "
                             "models it admits, %s open-vendor in the catalogue" % (_jsv.show(meta["id"]) if "id" in meta else "undefined",
                                                                                    _show_id(profile), _closed_route(profile.get("fallback"), closed))))
    return findings



def _show_id(profile: Dict[str, Any]) -> str:
    """show(profile.id), where an absent id is JavaScript's undefined."""
    return _jsv.show(profile["id"]) if "id" in profile else "undefined"


def profile_problems(kind: str, value: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """The contract's profileRules: findings for a `model-catalogue`, `model-profiles`, `runner-profile` or
    `profile-resolution` document; None for another kind."""
    return {"model-catalogue": _model_catalogue, "model-profiles": _model_profiles, "runner-profile": _runner_profile,
            "profile-resolution": lambda v: _profile_resolution(v) + _open_vendor_routes(v)}.get(kind, lambda v: None)(value)


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
    # The last row of an id wins, as a JavaScript Map built from the rows; only a string id can match a model's name.
    rows = {row["id"]: row for row in _list(catalogue.get("models") if isinstance(catalogue, dict) else None) if isinstance(row.get("id"), str)}
    if not isinstance(model, str) or model not in rows:
        return ["model %s is not in the model catalogue" % _jsv.show(model)]
    if isinstance(policy, dict) and isinstance(policy.get("modelClasses"), list):
        allowed = set(_strings(policy["modelClasses"]))
        meta = policy.get("meta") if isinstance(policy.get("meta"), dict) else {}
        policy_id = _jsv.show(_at(meta, "id"))
        admission = [c for c in _strings(rows[model].get("classes")) if c != OPEN_VENDOR]  # DEC-0083: descriptive
        if not admission:
            return ["model %s has no class but %s, which admits nothing, so policy %s does not allow it" % (model, OPEN_VENDOR, policy_id)]
        outside = [c for c in admission if c not in allowed]
        if outside:
            return ["model %s has class %s, which policy %s does not allow" % (model, ", ".join(outside), policy_id)]
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
    """The contract's show(value[key]): `undefined` for a missing key, `null` for null, and an object whose own
    `toString` is data as its JSON, where String() would throw."""
    return _jsv.show(_at(value, key))


def _object_at(value: Any, key: str) -> Dict[str, Any]:
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, dict) else {}


def _ref_key(ref: Any) -> str:
    """A revision reference compared whole: id, revision and content hash. The id is an identifier, so it enters the key
    in its normal form (DEC-0076)."""
    if not isinstance(ref, dict):
        return ""
    normal = _ids.normal_identifier(ref.get("id"))
    return "%s@%s#%s" % (normal if normal is not None else _field(ref, "id"), _field(ref, "revision"), _field(ref, "contentHash"))


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
                if a.get("state") == "admitted" and _ids.same_identifier(a.get("capability", _MISSING), route.get("capability", _MISSING))}
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

    # DEC-0076: project and capability are identifiers, compared by normal form.
    if not _ids.same_identifier(binding.get("project", _MISSING), route.get("project", _MISSING)):
        disagree("project", "the binding is for %s, the route for %s" % (_field(binding, "project"), _field(route, "project")))
    if not _ids.same_identifier(binding.get("capability", _MISSING), route.get("capability", _MISSING)):
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


def _index_of(ref: Dict[str, Any]) -> float:
    """The contract's indexOf: a JSON number that is an integer, as JavaScript holds it (a double; beyond the double
    range it is Infinity, which is no integer), else -1."""
    index = ref.get("index")
    if isinstance(index, bool) or not isinstance(index, (int, float)):
        return -1
    number = _jsv.double(index)
    return number if math.isfinite(number) and number.is_integer() else -1


def _route_event(value: Dict[str, Any]) -> List[Dict[str, str]]:
    route = _object_at(value, "route")
    event = _object_at(value, "event")
    candidates = _candidates(route)
    findings: List[Dict[str, str]] = []

    def wrong(path: str, message: str) -> None:
        findings.append(_finding("FAC-SEM-034", "/event" + path, message))

    if not _same_ref(event.get("route"), route.get("meta")):
        wrong("/route", "the event names route %s, not %s" % (_ref_key(event.get("route")), _ref_key(route.get("meta"))))
    if not _ids.same_identifier(event.get("project", _MISSING), route.get("project", _MISSING)):
        wrong("/project", "the event is for %s, the route for %s" % (_field(event, "project"), _field(route, "project")))
    if not _ids.same_identifier(event.get("capability", _MISSING), route.get("capability", _MISSING)):
        wrong("/capability", "the event names %s, the route orders %s" % (_field(event, "capability"), _field(route, "capability")))

    def candidate_at(ref: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
        index = _index_of(ref)
        candidate = candidates[int(index)] if 0 <= index < len(candidates) else None
        if (candidate is None or not _jsv.same(_at(candidate, "runnerKind"), _at(ref, "runnerKind"))
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

    def expect_probes(count: float) -> None:
        indexes = [_index_of(p) for p in probes]
        # Compared with 0...count-1 before any list is built, and the message lists at most 64 candidates, so a count from
        # an index of 2**32 allocates nothing (contract route-rules.ts at DEC-0084, from this kit's report).
        if _jsv.same(len(indexes), count) and all(_jsv.same(index, position) for position, index in enumerate(indexes)):
            return
        if count <= 64:  # NaN is not; Array.from({length: count}) takes ToLength
            expected = ", ".join(map(_jsv.js_string, range(int(count) if count > 0 else 0))) or "none"
        else:
            expected = "0 to %s" % _jsv.js_string(count - 1)
        wrong("/probes", "the walk must record candidates %s in order; it records %s"
              % (expected, ", ".join(map(_jsv.js_string, indexes)) or "none"))

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
        if "drive" in chosen and "drive" in selected and not _jsv.same(selected["drive"], chosen["drive"]):
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
