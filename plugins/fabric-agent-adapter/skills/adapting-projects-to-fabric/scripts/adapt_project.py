#!/usr/bin/env python3
"""Inspect, scaffold, and structurally check a Fabric provider project."""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044, LC-21), beside this file


CONTRACT_VERSION = "0.1.0"
CONTRACT_REPOSITORY = "https://github.com/passioncode-ai/fabric-agent-contract"
CONTRACT_COMMIT = "c55f2d5a11c9a0197e958e87212fca7ae1154769"
# #region supported-contract-revisions — docs: README.md#contract-pin
# Only this declaration may name a legacy revision in live files.
SUPPORTED_CONTRACT_COMMITS = (CONTRACT_COMMIT, "07042181bfae2a481aa0da1a5651f24c76669c48", "d8146cfb0a1c74fc6432284c4356bb0c864b37b5", "82e163665e156a08aa3b92e4711015582c06162c", "1636fa97262f4a26e2086572d540c2ee701e0010", "f00a7685e3861c27f7899c033fb850a145a1708f", "a046f57cf46ea9e3da57ff8ce6a3ed4d26d8774b", "fe55fc67cba1a9e34a736da7d148d4fe2a8fbfa0", "b291bf09e0a9f9fd3c16cf540832cd021203b7d1", "0cacd08b0e95b6abf131eae1206b60792138bc3c", "2eb91c00e852d9c31d804310d38fad91589fcbac", "8e49fbd5fbbf230e32c1969cd24ac3c22422f0a5", "a83bec6b47776af688402c18efec507143061f68", "52da526d7cc1e063d74c5b520dbc03d0ace15246", "78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5", "623bf61358c339cb10297807b3f024b5d9f1f327", "23f9fda4c05f8a3852246ee98d4f2adf74ed0875", "9091d3d6606b0c4b5591a38c3674356a01fd7f55", "df55c8c54a23251342a7ee57ba95642b7eb39e61", "2ce392291c6668598d12cd38327e24696b5ca15c")
# #endregion supported-contract-revisions
INTEROP_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1"
MCP_REVISION = "2026-07-28"
A2A_VERSION = "1.0"
LOCAL_VERSION = "fabric-local-runner/0.1"
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "dist", "build"}
TEXT_SUFFIXES = {".md", ".json", ".toml", ".yaml", ".yml", ".py", ".js", ".ts", ".go", ".rs"}
GENERATED_PATHS = (
    "fabric-agent.json",
    "fabric-contract.lock.json",
    "fabric/schemas/capability-input.schema.json",
    "fabric/schemas/capability-output.schema.json",
    "fabric/fixtures/admission-input.json",
    "fabric/probes/assertions.md",
    "fabric/FABRIC-CONFORMANCE.md",
)


# #region template-sentinels
# Every value the scaffold invents is a sentinel `check` finds: a fixed string, a `$comment` or Markdown mark, or a
# JSON pointer listed under TEMPLATE_KEY in the manifest's extensions (a value that is legal but was not chosen by the
# author, such as dataClasses ["public"]). readyForAdmission stays false while one remains.
TEMPLATE_KEY = "urn:fabric:adapter:template"
TEMPLATE_MARK = "fabric-adapter-template"
AUTHOR_SENTINEL = "urn:fabric:adapter:author"
WEAK_ASSERTION = "returns a typed result without external effects"
FIXTURE_SENTINEL = "Return one bounded, non-publishing test result."
ZERO_HASH = "sha256:" + ("0" * 64)
PLACEHOLDER_TEXT = ("replace-me", ".invalid")
DATA_CLASSES = ("public", "project-internal", "confidential", "personal", "credential", "regulated")
IDENTITY_METHODS = ("tls", "oauth2", "signed-manifest", "local-install")
# #endregion template-sentinels


class AdaptationError(Exception):
    """Expected user-facing adaptation error."""



def _normal_identifier(value: str) -> str:
    """DEC-0076's normal form, from fabric_identifiers.py beside this file (byte-identical to the service kit's)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fabric_identifiers", Path(__file__).resolve().parent / "fabric_identifiers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normal_identifier(value)

def _read_text(path: Path, limit: int = 262_144) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return ""


def _files(root: Path) -> Iterable[Path]:
    count = 0
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            count += 1
            if count > 5000:
                return
            yield Path(current) / name


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def inspect_project(root: Path) -> Dict[str, Any]:
    if not root.is_dir():
        raise AdaptationError("project path is not a directory: %s" % root)

    evidence: Dict[str, List[str]] = {"mcp": [], "a2a": [], "local-runner": [], "autonomous": [], "mcp-client-config": []}
    sampled = 0
    file_count = 0
    for path in _files(root):
        file_count += 1
        rel = _relative(path, root)
        lower_rel = rel.lower()
        if lower_rel.endswith("agent-card.json") or ".well-known/agent-card" in lower_rel:
            evidence["a2a"].append("file:%s" % rel)
        client_config = _is_mcp_client_config(path)
        if client_config:
            # A client's server list (.mcp.json, mcpServers) says what the project CALLS, not what it serves.
            evidence["mcp-client-config"].append("file:%s" % rel)
        elif "mcp" in Path(lower_rel).name:
            evidence["mcp"].append("file:%s" % rel)
        if lower_rel.startswith("bin/") or lower_rel in {"cli.py", "cli.js", "cli.ts"}:
            evidence["local-runner"].append("file:%s" % rel)

        if path.suffix.lower() not in TEXT_SUFFIXES or sampled >= 80:
            continue
        text = _read_text(path)
        if not text:
            continue
        sampled += 1
        lowered = text.lower()
        if not client_config and ("@modelcontextprotocol/sdk" in lowered or "fastmcp" in lowered or "model context protocol" in lowered):
            evidence["mcp"].append("content:%s" % rel)
        if '"a2a"' in lowered or "agent card" in lowered or "/.well-known/agent-card.json" in lowered:
            evidence["a2a"].append("content:%s" % rel)
        if "[project.scripts]" in lowered or ('"bin"' in lowered and path.name == "package.json"):
            evidence["local-runner"].append("content:%s" % rel)
        lifecycle_terms = sum(term in lowered for term in ("start job", "job status", "cancel job", "task lifecycle", "stream progress"))
        if lifecycle_terms >= 2:
            evidence["autonomous"].append("content:%s" % rel)

    for key in evidence:
        evidence[key] = sorted(set(evidence[key]))[:20]

    candidates: List[str] = []
    if evidence["a2a"] or evidence["autonomous"]:
        candidates.append("a2a")
    if evidence["mcp"]:
        candidates.append("mcp")
    if evidence["local-runner"]:
        candidates.append("local-runner")
    candidates = sorted(set(candidates))

    if len(candidates) == 1:
        recommendation = candidates[0]
        question = None
    elif not candidates:
        recommendation = "undetermined"
        question = "Which stable API, MCP/A2A endpoint, or installed CLI will Fabric invoke?"
    else:
        recommendation = "undetermined"
        question = "Which capability is being adapted, and who owns its task lifecycle?"
    if evidence["mcp-client-config"] and "mcp" not in candidates:
        question = ("The project configures MCP clients (%s); that lists servers it calls, not one it serves. "
                    "Does it also serve an MCP server Fabric can call? %s" % (", ".join(evidence["mcp-client-config"][:3]), question or ""))

    return {
        "project": str(root.resolve()),
        "filesInspected": file_count,
        "textFilesSampled": sampled,
        "recommendedProfile": recommendation,
        "candidateProfiles": candidates,
        "evidence": evidence,
        "openQuestion": question,
        "warning": "Static inspection does not execute or trust the target project.",
    }


def _is_mcp_client_config(path: Path) -> bool:
    if path.name.lower() in (".mcp.json", "claude_desktop_config.json"):
        return True
    if path.suffix.lower() not in (".json", ".toml", ".yaml", ".yml"):
        return False
    text = _read_text(path).lower()
    return "mcpservers" in text or "mcp_servers" in text


def _require_absolute_uri(value: str, label: str) -> None:
    parsed = urlparse(value)
    if not parsed.scheme:
        raise AdaptationError("%s must be an absolute URI: %s" % (label, value))
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise AdaptationError("%s must include a host: %s" % (label, value))


def _schema_uri(base: str, name: str) -> str:
    return base.rstrip("/") + "/" + name


def _profile(args: argparse.Namespace, schema_base: str) -> Dict[str, Any]:
    profile = args.profile
    fixture_uri = _schema_uri(schema_base, "fixtures/admission-input.json")
    output_uri = _schema_uri(schema_base, "schemas/capability-output.schema.json")
    probe = {
        "id": "safe-shape-probe",
        "inputFixture": fixture_uri,
        "outputSchema": output_uri,
        "timeoutMs": 30000,
        "sideEffectCeiling": "none",
        "assertions": list(getattr(args, "probe_assertion", None) or [WEAK_ASSERTION]),
    }
    if profile == "mcp":
        if args.mcp_mode == "stdio":
            connection = {
                "mode": "stdio",
                "executableRef": args.executable_ref,
                "args": args.runtime_arg,
            }
        else:
            connection = {"mode": "streamable-http", "url": args.mcp_url}
        return {
            "kind": "mcp",
            "protocolRevision": MCP_REVISION,
            "connection": connection,
            # fabric-interop/0.1 C3.1: the capability is served as the MCP tool of its own name.
            "requiredFeatures": ["tool:%s" % args.capability_name],
            "probes": [probe],
        }
    if profile == "a2a":
        return {
            "kind": "a2a",
            "protocolVersion": A2A_VERSION,
            "agentCardUrl": args.agent_card_url,
            "skillIds": ["replace-me"],
            "binding": "REST",
            "streaming": False,
            "pushNotifications": False,
            "probes": [probe],
        }
    if profile == "local-runner":
        return {
            "kind": "local-runner",
            "profileVersion": LOCAL_VERSION,
            "runnerKind": args.runner_kind,
            "executableRef": args.executable_ref,
            "args": args.runtime_arg or ["--input", "{inputFile}"],
            "inputMode": "file-json",
            "resultUriTemplate": "file:{worktree}/.fabric/result.json",
            "cancellation": "signal",
            "heartbeatSeconds": 30,
            "probes": [probe],
        }
    raise AdaptationError("unsupported profile: %s" % profile)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _generated_files(args: argparse.Namespace) -> Dict[str, str]:
    effect, idempotency = _declared_effect(args)
    for value, label in (
        (args.provider_id, "provider ID"),
        (args.capability_id, "capability ID"),
        (args.schema_base, "schema base"),
    ):
        _require_absolute_uri(value, label)
    if "?" in args.schema_base or "#" in args.schema_base:
        raise AdaptationError("schema base must not contain a query or fragment")
    _require_absolute_uri(args.executable_ref, "executable reference")
    _require_absolute_uri(args.mcp_url, "MCP URL")
    _require_absolute_uri(args.agent_card_url, "Agent Card URL")
    if urlparse(args.agent_card_url).scheme != "https":
        raise AdaptationError("Agent Card URL must use HTTPS")
    if getattr(args, "job", False) and args.profile != "mcp":
        raise AdaptationError("--job marks an MCP capability as a job (fabric-interop/0.1); %s has no job handle" % args.profile)
    for runtime_arg in args.runtime_arg:
        lowered = runtime_arg.lower().replace("_", "").replace("-", "")
        if any(term in lowered for term in ("password", "apikey", "accesstoken", "clientsecret")):
            raise AdaptationError("runtime arguments must not contain secret-like values or names")
        if _secrets.secret_argument(runtime_arg):
            raise AdaptationError("a runtime argument carries a credential; argv is visible to every process (LC-21): read it from a secret reference instead")

    defaulted: List[str] = []
    created_by = getattr(args, "created_by", None)
    if created_by:
        _require_absolute_uri(created_by, "created-by")
    else:
        created_by = AUTHOR_SENTINEL
        defaulted.append("/provider/createdBy")
    local = args.profile == "local-runner" or (args.profile == "mcp" and args.mcp_mode == "stdio")
    identity_method = getattr(args, "identity_method", None)
    if not identity_method:
        identity_method = "local-install" if local else "tls"
        if not local:
            defaulted.append("/provider/identity/method")
    elif identity_method not in IDENTITY_METHODS:
        raise AdaptationError("unknown identity method %r (%s)" % (identity_method, ", ".join(IDENTITY_METHODS)))
    data_classes = list(dict.fromkeys(getattr(args, "data_class", None) or []))
    if any(c not in DATA_CLASSES for c in data_classes):
        raise AdaptationError("unknown data class (%s)" % ", ".join(DATA_CLASSES))
    if not data_classes:
        data_classes = ["public"]
        defaulted.append("/capabilities/0/dataClasses")
    if not getattr(args, "probe_assertion", None):
        defaulted.append("/capabilities/0/profile/probes/0/assertions")
    created_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # DEC-0076: a writer emits identifiers in their normal form, so every reader finds them under one spelling.
    provider_id = _normal_identifier(args.provider_id)
    capability_id = _normal_identifier(args.capability_id)
    manifest = {
        "contractVersion": CONTRACT_VERSION,
        "provider": {
            "id": provider_id,
            "revision": 1,
            "contentHash": "sha256:" + ("0" * 64),
            "createdAt": created_at,
            "createdBy": created_by,
            "name": args.provider_name,
            "identity": {
                "subject": provider_id,
                "method": identity_method,
            },
            "supportedContractVersions": [CONTRACT_VERSION],
        },
        "capabilities": [
            {
                "id": capability_id,
                "name": args.capability_name,
                "inputSchema": _schema_uri(args.schema_base, "schemas/capability-input.schema.json"),
                "outputSchema": _schema_uri(args.schema_base, "schemas/capability-output.schema.json"),
                "effect": effect,
                "idempotency": idempotency,
                "dataClasses": data_classes,
                "profile": _profile(args, args.schema_base),
            }
        ],
    }
    if getattr(args, "job", False):
        manifest["capabilities"][0]["extensions"] = {INTEROP_KEY: {"job": True}}
    presets = _cost_presets(args)
    if presets:
        manifest["costPresets"] = presets
    if defaulted:
        manifest["extensions"] = {TEMPLATE_KEY: {
            "defaulted": defaulted,
            "note": "The scaffold chose these values. Confirm or replace each one, remove it from this list, and remove this block when the list is empty; check keeps readyForAdmission false while it remains.",
        }}
    lock = {
        "contract": "fabric-agent-contract",
        "version": CONTRACT_VERSION,
        "repository": CONTRACT_REPOSITORY,
        "commit": CONTRACT_COMMIT,
        "profile": args.profile,
    }
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _schema_uri(args.schema_base, "schemas/capability-input.schema.json"),
        "title": "Capability input",
        "$comment": TEMPLATE_MARK + ": a generic placeholder; replace it with the capability's real input schema.",
        "type": "object",
        "additionalProperties": False,
        "properties": {"request": {"type": "string", "minLength": 1}},
        "required": ["request"],
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _schema_uri(args.schema_base, "schemas/capability-output.schema.json"),
        "title": "Capability output",
        "$comment": TEMPLATE_MARK + ": a generic placeholder; replace it with the capability's real output schema.",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string", "format": "uri"}},
        },
        "required": ["summary", "evidence"],
    }
    fixture = {"request": FIXTURE_SENTINEL}
    assertions = "<!-- " + TEMPLATE_MARK + ": generic assertions; replace them with what this capability's probe proves. -->\n" + """# Admission probe assertions

- The result validates against `capability-output.schema.json`.
- Every claimed fact has a resolvable evidence URI.
- The probe does not publish, message, charge, mutate production, or expose secrets.
- Timeout and cancellation return a typed partial or stopped result.
"""
    conformance = """# Fabric conformance

Contract: `fabric-agent-contract` 0.1.0 at `%s`

| Gate | Status | Receipt / next action |
|---|---|---|
| Declaration shape | NOT_VERIFIED | Run `adapt_project.py check . --contract /path/to/fabric-agent-contract`. |
| Protocol revision and connection | NOT_VERIFIED | Replace profile placeholders, then negotiate the exact pinned revision. |
| Semantic probes | NOT_VERIFIED | Implement and run the bounded fixture and assertions against the provider. |
| Project binding readiness | NOT_VERIFIED | Requires an admitted capability and Fabric host runtime. |

The zero content hash, `replace-me` values, and `.invalid` endpoints are deliberate
placeholders. Scaffolding is not admission and must not be presented as compatibility.
""" % CONTRACT_COMMIT
    return {
        "fabric-agent.json": _json_text(manifest),
        "fabric-contract.lock.json": _json_text(lock),
        "fabric/schemas/capability-input.schema.json": _json_text(input_schema),
        "fabric/schemas/capability-output.schema.json": _json_text(output_schema),
        "fabric/fixtures/admission-input.json": _json_text(fixture),
        "fabric/probes/assertions.md": assertions,
        "fabric/FABRIC-CONFORMANCE.md": conformance,
    }


EFFECT_CLASSES = ("none", "draft", "publish", "send", "reply", "charge", "delete", "merge", "deploy", "change-policy")
IDEMPOTENCY = ("required", "supported", "none")
_PRESET_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}\Z")  # \Z, not `$`: `$` also matches before a trailing newline (R1)


def _cost_presets(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """DEC-0037: the fixed options a launcher offers for a task whose cost varies, each for this capability."""
    presets: List[Dict[str, Any]] = []
    seen = set()
    for raw in getattr(args, "cost_preset", None) or []:
        preset_id, max_usd, label = (list(raw) + ["", "", ""])[:3]
        if not _PRESET_ID.match(preset_id or ""):
            raise AdaptationError("cost preset id %r must match ^[a-z][a-z0-9-]{0,39}$" % preset_id)
        if preset_id in seen:
            raise AdaptationError("cost preset %s is named twice" % preset_id)
        try:
            amount = float(max_usd)
        except ValueError:
            raise AdaptationError("cost preset %s: maxUsd %r is not a number" % (preset_id, max_usd)) from None
        if not math.isfinite(amount) or amount < 0:
            raise AdaptationError("cost preset %s: maxUsd must be a finite amount of at least 0" % preset_id)
        if not label.strip():
            raise AdaptationError("cost preset %s needs a label a person reads at launch" % preset_id)
        seen.add(preset_id)
        presets.append({"id": preset_id, "capability": args.capability_name, "label": label.strip(), "maxUsd": amount})
    default = getattr(args, "default_cost_preset", None)
    if default:
        if default not in seen:
            raise AdaptationError("--default-cost-preset %s names no --cost-preset" % default)
        next(p for p in presets if p["id"] == default)["default"] = True
    return presets


def _declared_effect(args: argparse.Namespace) -> Tuple[str, str]:
    """The capability's effect class is declared by the author, never defaulted (target architecture v4, Stage 0)."""
    effect = getattr(args, "effect", None)
    if effect not in EFFECT_CLASSES:
        raise AdaptationError("declare the capability's effect with --effect (%s); it is never defaulted"
                              % ", ".join(EFFECT_CLASSES) if not effect else "unknown effect class %r (%s)" % (effect, ", ".join(EFFECT_CLASSES)))
    idempotency = getattr(args, "idempotency", None) or "none"
    if idempotency not in IDEMPOTENCY:
        raise AdaptationError("unknown idempotency %r (%s)" % (idempotency, ", ".join(IDEMPOTENCY)))
    return effect, idempotency


def scaffold_project(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if not root.is_dir():
        raise AdaptationError("project path is not a directory: %s" % root)
    generated = _generated_files(args)
    collisions = [rel for rel in generated if (root / rel).exists()]
    if getattr(args, "dry_run", False):
        diffs: Dict[str, str] = {}
        for rel in collisions:
            try:
                old = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            except OSError as exc:
                old = ["<unreadable: %s>\n" % exc.__class__.__name__]
            diffs[rel] = "".join(difflib.unified_diff(old, generated[rel].splitlines(keepends=True), fromfile=rel, tofile=rel))
        return {
            "project": str(root.resolve()),
            "profile": args.profile,
            "dryRun": True,
            "wouldCreate": sorted(set(generated) - set(collisions)),
            "wouldReplace": sorted(collisions),
            "needsForce": bool(collisions) and not args.force,
            "diffs": diffs,
        }
    if collisions and not args.force:
        raise AdaptationError("refusing to overwrite existing paths: %s" % ", ".join(collisions))
    for rel, content in generated.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return {
        "project": str(root.resolve()),
        "profile": args.profile,
        "created": sorted(generated),
        "replaced": sorted(collisions),
        "next": "Replace all placeholders, implement the adapter, then run check with the pinned contract checkout.",
    }


def _load_json(path: Path, errors: List[str]) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append("missing:%s" % path.name)
    except (OSError, ValueError) as exc:  # ValueError: JSONDecodeError and UnicodeDecodeError (a non-UTF-8 file)
        errors.append("invalid-json:%s:%s" % (path.name, exc.__class__.__name__ if isinstance(exc, UnicodeError) else exc))
    return None


def _walk_keys(value: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            here = "%s.%s" % (prefix, key) if prefix else key
            yield here, item
            yield from _walk_keys(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            here = "%s[%d]" % (prefix, index)
            yield here, item
            yield from _walk_keys(item, here)


def _contract_shape(manifest: Path, contract: Path, selected_commit: str) -> Tuple[str, List[str]]:
    if selected_commit not in SUPPORTED_CONTRACT_COMMITS:
        return "FAIL", ["unsupported selected contract revision"]
    if not contract.is_dir():
        return "NOT_RUN", ["contract checkout is not a directory: %s" % contract]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(contract), check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return "NOT_RUN", ["cannot read contract commit: %s" % exc]
    if head != selected_commit:
        return "FAIL", ["contract checkout is %s; selected lock requires %s" % (head, selected_commit)]
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=str(contract), check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return "NOT_RUN", ["cannot verify clean contract checkout: %s" % exc]
    if dirty:
        return "FAIL", ["contract checkout has modifications; exact selected schema is required"]
    tsx = contract / "node_modules/.bin/tsx"
    if not tsx.is_file():
        return "NOT_RUN", ["pinned contract dependencies are missing; run pnpm install --frozen-lockfile in the contract checkout"]

    code = """import {readFile} from 'node:fs/promises';
import {createValidator,validateDocument} from './src/validator.ts';
import {SCHEMA_PREFIX} from './src/contract.ts';
(async () => {
  const value=JSON.parse(await readFile(process.argv[1],'utf8'));
  const result=validateDocument(await createValidator(),SCHEMA_PREFIX+'schemas/manifest.schema.json',value);
  console.log(JSON.stringify(result));
  process.exit(result.valid?0:3);
})().catch((error) => { console.error(error); process.exit(4); });"""
    try:
        # The checkout's own tsx, called directly: `pnpm exec` may decide the modules folder is stale and purge and
        # reinstall a checkout that is not this tool's to change (ERR_PNPM_UNSAFE_MODULES_DIR).
        run = subprocess.run(
            [str(tsx), "-e", code, str(manifest.resolve())],
            cwd=str(contract), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=120,
        )
    except OSError as exc:
        return "NOT_RUN", ["the contract checkout's tsx could not start (%s); is node on PATH?" % exc.__class__.__name__]
    except subprocess.TimeoutExpired:
        return "NOT_RUN", ["contract shape validation timed out"]
    if run.returncode != 0:
        detail = (run.stdout + "\n" + run.stderr).strip()
        if run.returncode != 3:
            return "NOT_RUN", [detail[-4000:] or "contract validator could not run"]
        return "FAIL", [detail[-4000:] or "contract validator failed"]
    return "PASS", ["manifest validated by selected contract schema at %s" % selected_commit]


def _credential_problems(manifest: Dict[str, Any]) -> List[str]:
    """LC-21 (FAA-23): no credential in a launch argument or in a URL the manifest names."""
    problems: List[str] = []
    for index, capability in enumerate(manifest.get("capabilities") or []):
        connection = ((capability or {}).get("profile") or {}).get("connection") if isinstance(capability, dict) else None
        if not isinstance(connection, dict):
            continue
        for arg in connection.get("args") or []:
            if isinstance(arg, str) and _secrets.secret_argument(arg):
                problems.append("LC-21: capability[%d] passes a credential in a launch argument; argv is visible to every process" % index)
        for field in ("url", "agentCardUrl"):
            if isinstance(connection.get(field), str) and _secrets.secret_url(connection[field]):
                problems.append("LC-21: capability[%d].%s carries a credential in the URL; a query lands in every log" % (index, field))
    return problems


_PLUGIN_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".worktrees"}


def _plugin_problems(root: Path) -> List[str]:
    """LC-19 (FAA-22) and LC-21 for the Claude Code plugins in the project: a plugin's stdio MCP server starts in
    every session that enables the plugin; serve it over HTTP from one resident process, or register it at project
    scope instead. No server entry carries a credential in its argv, URL or env."""
    problems: List[str] = []
    for top, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _PLUGIN_SKIP]
        here = Path(top)
        if here.name != ".claude-plugin" or "plugin.json" not in files:
            continue
        plugin = here.parent
        name = plugin.relative_to(root).as_posix() or "."
        servers: Dict[str, Any] = {}
        for source in (here / "plugin.json", plugin / ".mcp.json"):
            try:
                doc = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else {}
            except (OSError, ValueError):
                continue
            block = doc.get("mcpServers") if isinstance(doc, dict) else None
            if isinstance(block, dict):
                servers.update({k: v for k, v in block.items() if isinstance(v, dict)})
        for server, entry in sorted(servers.items()):
            if "command" in entry:
                problems.append("LC-19: plugin %s declares the stdio MCP server %s, which starts in every session that enables the plugin; serve it over HTTP from one resident process or register it at project scope" % (name, server))
            argv = [entry.get("command")] + list(entry.get("args") or [])
            if any(isinstance(a, str) and _secrets.secret_argument(a) for a in argv) or (isinstance(entry.get("url"), str) and _secrets.secret_url(entry["url"])):
                problems.append("LC-21: plugin %s's MCP server %s carries a credential in its argv or URL" % (name, server))
            env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
            if any(isinstance(v, str) and _secrets.secret_value(v) for v in env.values()):
                problems.append("LC-21: plugin %s's MCP server %s writes a credential value in env; reference it instead" % (name, server))
    return problems


def _template_block_warnings(manifest: Dict[str, Any], errors: List[str]) -> List[str]:
    """The pointers the scaffold recorded as its own choices (TEMPLATE_KEY); each stays a warning until removed."""
    extensions = manifest.get("extensions")
    block = extensions.get(TEMPLATE_KEY) if isinstance(extensions, dict) else None
    if block is None:
        return []
    pointers = block.get("defaulted") if isinstance(block, dict) else None
    if not isinstance(pointers, list) or not all(isinstance(p, str) for p in pointers):
        errors.append("extensions.%s must be {\"defaulted\": [JSON pointers]}" % TEMPLATE_KEY)
        return []
    if not pointers:
        return ["template-default:extensions.%s is empty; remove the block" % TEMPLATE_KEY]
    return ["template-default:%s (chosen by the scaffold; confirm or replace it, then remove it from extensions.%s)" % (p, TEMPLATE_KEY)
            for p in pointers]


def _template_file_warnings(root: Path) -> List[str]:
    """Sentinels in the generated files other than the manifest: placeholder text, the template mark, the generic
    schemas and fixture (also recognised by shape when the mark was removed but the schema was not replaced)."""
    warnings: List[str] = []
    for rel in GENERATED_PATHS[1:]:
        if rel == "fabric/FABRIC-CONFORMANCE.md":
            continue  # the status page names the placeholders to explain them; it is the author's to keep
        path = root / rel
        if not path.is_file():
            continue
        text = _read_text(path)
        if TEMPLATE_MARK in text:
            warnings.append("placeholder:%s (the scaffold's generic template)" % rel)
        elif any(marker in text for marker in PLACEHOLDER_TEXT):
            warnings.append("placeholder:%s" % rel)
    generic_shapes = {
        "fabric/schemas/capability-input.schema.json": {"request"},
        "fabric/schemas/capability-output.schema.json": {"summary", "evidence"},
    }
    for rel, keys in generic_shapes.items():
        try:
            schema = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict) and set(properties) == keys and TEMPLATE_MARK not in json.dumps(schema):
            warnings.append("placeholder:%s (still the scaffold's generic shape)" % rel)
    try:
        fixture = json.loads((root / "fabric/fixtures/admission-input.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fixture = None
    if isinstance(fixture, dict) and FIXTURE_SENTINEL in fixture.values():
        warnings.append("placeholder:fabric/fixtures/admission-input.json (the scaffold's generic fixture)")
    return warnings


def check_project(root: Path, contract: Optional[Path]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    for rel in GENERATED_PATHS:
        if not (root / rel).is_file():
            errors.append("missing:%s" % rel)

    manifest_path = root / "fabric-agent.json"
    manifest = _load_json(manifest_path, errors)
    lock = _load_json(root / "fabric-contract.lock.json", errors)
    profile_kind = None
    lock_errors: List[str] = []
    if isinstance(lock, dict):
        if lock.get("contract") != "fabric-agent-contract":
            lock_errors.append("contract lock contract must be fabric-agent-contract")
        if lock.get("repository") != CONTRACT_REPOSITORY:
            lock_errors.append("contract lock repository must be %s" % CONTRACT_REPOSITORY)
        if lock.get("version") != CONTRACT_VERSION:
            lock_errors.append("contract lock version must be %s" % CONTRACT_VERSION)
        if lock.get("commit") not in SUPPORTED_CONTRACT_COMMITS:
            lock_errors.append("contract lock commit must be an explicitly supported immutable revision")
    else:
        lock_errors.append("contract lock must be an object")
    errors.extend(lock_errors)

    if isinstance(manifest, dict):
        if manifest.get("contractVersion") != CONTRACT_VERSION:
            errors.append("manifest contractVersion must be %s" % CONTRACT_VERSION)
        capabilities = manifest.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append("manifest must declare at least one capability")
        else:
            for index, capability in enumerate(capabilities):
                profile = capability.get("profile") if isinstance(capability, dict) else None
                if not isinstance(profile, dict):
                    errors.append("capability[%d] has no profile" % index)
                    continue
                kind = profile.get("kind")
                profile_kind = kind
                expected = {
                    "mcp": ("protocolRevision", MCP_REVISION),
                    "a2a": ("protocolVersion", A2A_VERSION),
                    "local-runner": ("profileVersion", LOCAL_VERSION),
                }.get(kind)
                if expected is None:
                    errors.append("capability[%d] has unsupported profile %r" % (index, kind))
                elif profile.get(expected[0]) != expected[1]:
                    errors.append("capability[%d] must pin %s=%s" % (index, expected[0], expected[1]))
                if not profile.get("probes"):
                    errors.append("capability[%d] must declare probes" % index)
                block = (capability.get("extensions") or {}).get(INTEROP_KEY)
                if block is not None:
                    if not isinstance(block, dict) or set(block) - {"job"} or not isinstance(block.get("job", False), bool):
                        errors.append("capability[%d] interop block must be {\"job\": true|false}" % index)
                    elif kind != "mcp":
                        errors.append("capability[%d] interop block is for an mcp capability, not %s" % (index, kind))
                for field in ("inputSchema", "outputSchema"):
                    value = capability.get(field)
                    try:
                        _require_absolute_uri(value, "capability[%d].%s" % (index, field))
                    except (AdaptationError, TypeError):
                        errors.append("capability[%d].%s must be an absolute URI" % (index, field))

        for key, value in _walk_keys(manifest):
            normalized = key.lower().replace("_", "").replace("-", "")
            if any(secret in normalized for secret in ("password", "apikey", "accesstoken", "clientsecret", "privatekey")):
                errors.append("secret-like field is forbidden in manifest: %s" % key)
            if isinstance(value, str) and any(text in value for text in PLACEHOLDER_TEXT):
                warnings.append("placeholder:%s" % key)
            if value == AUTHOR_SENTINEL:
                warnings.append("placeholder:%s" % key)
            if value == WEAK_ASSERTION:
                warnings.append("placeholder:%s (a generic probe assertion; state what the probe proves)" % key)
        errors.extend(_credential_problems(manifest))
        provider = manifest.get("provider")
        if isinstance(provider, dict) and provider.get("contentHash") == ZERO_HASH:
            warnings.append("placeholder:provider.contentHash")
        warnings.extend(_template_block_warnings(manifest, errors))
    warnings.extend(_template_file_warnings(root))

    shape_status = "NOT_RUN"
    shape_receipts = ["pass --contract PATH pointing at the pinned checkout"]
    if lock_errors:
        shape_status, shape_receipts = "FAIL", lock_errors
    elif contract is not None and manifest_path.is_file():
        shape_status, shape_receipts = _contract_shape(manifest_path, contract, lock["commit"])

    errors.extend(_plugin_problems(root))
    local_status = "PASS" if not errors else "FAIL"
    ready = local_status == "PASS" and shape_status == "PASS" and not warnings
    return {
        "project": str(root.resolve()),
        "profile": profile_kind,
        "gates": {
            "localStructure": {"status": local_status, "receipts": sorted(set(errors))},
            "declarationShape": {"status": shape_status, "receipts": shape_receipts},
            "protocolNegotiation": {"status": "NOT_VERIFIED", "receipts": ["requires a live provider and Fabric host"]},
            "semanticProbes": {"status": "NOT_VERIFIED", "receipts": ["requires bounded live probe execution"]},
            "bindingReadiness": {"status": "NOT_VERIFIED", "receipts": ["requires admission and Fabric host runtime"]},
        },
        "warnings": sorted(set(warnings)),
        "readyForAdmission": ready,
    }


def _print(value: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(_json_text(value), end="")
        return
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            print("%s: %s" % (key, json.dumps(item, ensure_ascii=False, sort_keys=True)))
        else:
            print("%s: %s" % (key, item))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="inspect a project without executing it")
    inspect.add_argument("project", type=Path)
    inspect.add_argument("--json", action="store_true")

    scaffold = sub.add_parser("scaffold", help="create a contract-pinned provider bundle")
    scaffold.add_argument("project", type=Path)
    scaffold.add_argument("--profile", choices=("mcp", "a2a", "local-runner"), required=True)
    scaffold.add_argument("--provider-id", required=True)
    scaffold.add_argument("--provider-name", default="Fabric capability provider")
    scaffold.add_argument("--capability-id", required=True)
    scaffold.add_argument("--capability-name", required=True)
    scaffold.add_argument("--schema-base", required=True)
    scaffold.add_argument("--mcp-mode", choices=("streamable-http", "stdio"), default="streamable-http")
    scaffold.add_argument("--mcp-url", default="https://replace.invalid/mcp")
    scaffold.add_argument("--agent-card-url", default="https://replace.invalid/.well-known/agent-card.json")
    scaffold.add_argument("--runner-kind", default="replace-me")
    scaffold.add_argument("--executable-ref", default="urn:executable:replace-me")
    scaffold.add_argument("--runtime-arg", action="append", default=[])
    scaffold.add_argument("--effect", required=True, choices=EFFECT_CLASSES,
                          help="the capability's effect class (governance): what it does outside itself; never defaulted")
    scaffold.add_argument("--idempotency", choices=IDEMPOTENCY, default="none")
    scaffold.add_argument("--cost-preset", nargs=3, action="append", default=[], metavar=("ID", "MAX_USD", "LABEL"),
                          help="a fixed cost option a launcher offers (DEC-0037 costPresets); repeat for each")
    scaffold.add_argument("--default-cost-preset", metavar="ID", help="the preset preselected at launch")
    scaffold.add_argument("--job", action="store_true", help="the capability's work may outlive one request (fabric-interop/0.1 job)")
    scaffold.add_argument("--created-by", metavar="URI", help="the manifest author (provider.createdBy); a sentinel until given")
    scaffold.add_argument("--identity-method", choices=IDENTITY_METHODS, help="provider.identity.method; a remote default of tls is a sentinel until given")
    scaffold.add_argument("--data-class", action="append", choices=DATA_CLASSES, default=[],
                          help="a data class the capability handles; repeat. Without it [public] is written as a sentinel")
    scaffold.add_argument("--probe-assertion", action="append", default=[], help="what the admission probe proves; repeat. Without it a generic sentinel is written")
    scaffold.add_argument("--force", action="store_true", help="replace the generated paths that exist; see --dry-run first")
    scaffold.add_argument("--dry-run", action="store_true", help="print the planned writes and a unified diff of each existing path; write nothing")
    scaffold.add_argument("--json", action="store_true")

    check = sub.add_parser("check", help="check generated structure and optional pinned schema")
    check.add_argument("project", type=Path)
    check.add_argument("--contract", type=Path)
    check.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_project(args.project)
        elif args.command == "scaffold":
            result = scaffold_project(args.project, args)
        else:
            result = check_project(args.project, args.contract)
        if result.get("dryRun") and not args.json:
            diffs = result.pop("diffs")
            _print(result, False)
            for rel in sorted(diffs):
                print(diffs[rel], end="" if diffs[rel].endswith("\n") or not diffs[rel] else "\n")
        else:
            _print(result, args.json)
        if args.command == "check":
            gates = result["gates"]
            if gates["localStructure"]["status"] == "FAIL" or gates["declarationShape"]["status"] == "FAIL":
                return 1
        return 0
    except AdaptationError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
