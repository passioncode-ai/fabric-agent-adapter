#!/usr/bin/env python3
"""Inspect, scaffold, and structurally check a Fabric provider project."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


CONTRACT_VERSION = "0.1.0"
CONTRACT_REPOSITORY = "https://github.com/passioncode-ai/fabric-agent-contract"
CONTRACT_COMMIT = "df55c8c54a23251342a7ee57ba95642b7eb39e61"
# #region supported-contract-revisions — docs: README.md#contract-pin
# Only this declaration may name a legacy revision in live files.
SUPPORTED_CONTRACT_COMMITS = (CONTRACT_COMMIT, "2ce392291c6668598d12cd38327e24696b5ca15c")
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


class AdaptationError(Exception):
    """Expected user-facing adaptation error."""


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

    evidence: Dict[str, List[str]] = {"mcp": [], "a2a": [], "local-runner": [], "autonomous": []}
    sampled = 0
    file_count = 0
    for path in _files(root):
        file_count += 1
        rel = _relative(path, root)
        lower_rel = rel.lower()
        if lower_rel.endswith("agent-card.json") or ".well-known/agent-card" in lower_rel:
            evidence["a2a"].append("file:%s" % rel)
        if "mcp" in Path(lower_rel).name:
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
        if "@modelcontextprotocol/sdk" in lowered or "fastmcp" in lowered or "model context protocol" in lowered:
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
        "assertions": ["returns a typed result without external effects"],
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

    created_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "contractVersion": CONTRACT_VERSION,
        "provider": {
            "id": args.provider_id,
            "revision": 1,
            "contentHash": "sha256:" + ("0" * 64),
            "createdAt": created_at,
            "createdBy": "urn:fabric:adapter:author",
            "name": args.provider_name,
            "identity": {
                "subject": args.provider_id,
                "method": "local-install" if args.profile == "local-runner" or (args.profile == "mcp" and args.mcp_mode == "stdio") else "tls",
            },
            "supportedContractVersions": [CONTRACT_VERSION],
        },
        "capabilities": [
            {
                "id": args.capability_id,
                "name": args.capability_name,
                "inputSchema": _schema_uri(args.schema_base, "schemas/capability-input.schema.json"),
                "outputSchema": _schema_uri(args.schema_base, "schemas/capability-output.schema.json"),
                "effect": "none",
                "idempotency": "none",
                "dataClasses": ["public"],
                "profile": _profile(args, args.schema_base),
            }
        ],
    }
    if getattr(args, "job", False):
        manifest["capabilities"][0]["extensions"] = {INTEROP_KEY: {"job": True}}
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
        "type": "object",
        "additionalProperties": False,
        "properties": {"request": {"type": "string", "minLength": 1}},
        "required": ["request"],
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _schema_uri(args.schema_base, "schemas/capability-output.schema.json"),
        "title": "Capability output",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string", "format": "uri"}},
        },
        "required": ["summary", "evidence"],
    }
    fixture = {"request": "Return one bounded, non-publishing test result."}
    assertions = """# Admission probe assertions

- The result validates against `capability-output.schema.json`.
- Every claimed fact has a resolvable evidence URI.
- The probe does not publish, message, charge, mutate production, or expose secrets.
- Timeout and cancellation return a typed partial or stopped result.
"""
    conformance = """# Fabric conformance

Contract: `fabric-agent-contract` 0.1.0 at `%s`

| Gate | Status | Receipt / next action |
|---|---|---|
| Declaration shape | NOT VERIFIED | Run `adapt_project.py check . --contract /path/to/fabric-agent-contract`. |
| Protocol revision and connection | NOT VERIFIED | Replace profile placeholders, then negotiate the exact pinned revision. |
| Semantic probes | NOT VERIFIED | Implement and run the bounded fixture and assertions against the provider. |
| Project binding readiness | NOT VERIFIED | Requires an admitted capability and Fabric host runtime. |

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


def scaffold_project(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if not root.is_dir():
        raise AdaptationError("project path is not a directory: %s" % root)
    generated = _generated_files(args)
    collisions = [rel for rel in generated if (root / rel).exists()]
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
    except (OSError, json.JSONDecodeError) as exc:
        errors.append("invalid-json:%s:%s" % (path.name, exc))
    return None


def _walk_keys(value: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            here = "%s.%s" % (prefix, key) if prefix else key
            yield here, item
            yield from _walk_keys(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_keys(item, "%s[%d]" % (prefix, index))


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
    if not (contract / "node_modules/.bin/tsx").is_file():
        return "NOT_RUN", ["pinned contract dependencies are missing; run pnpm install --frozen-lockfile"]

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
        run = subprocess.run(
            ["pnpm", "exec", "tsx", "-e", code, str(manifest.resolve())],
            cwd=str(contract), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return "NOT_RUN", ["pnpm is unavailable; install the pinned contract dependencies"]
    except subprocess.TimeoutExpired:
        return "NOT_RUN", ["contract shape validation timed out"]
    if run.returncode != 0:
        detail = (run.stdout + "\n" + run.stderr).strip()
        if run.returncode != 3:
            return "NOT_RUN", [detail[-4000:] or "contract validator could not run"]
        return "FAIL", [detail[-4000:] or "contract validator failed"]
    return "PASS", ["manifest validated by selected contract schema at %s" % selected_commit]


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
            if isinstance(value, str) and ("replace-me" in value or ".invalid" in value):
                warnings.append("placeholder:%s" % key)
        provider = manifest.get("provider")
        if isinstance(provider, dict) and provider.get("contentHash") == "sha256:" + ("0" * 64):
            warnings.append("placeholder:provider.contentHash")

    shape_status = "NOT_RUN"
    shape_receipts = ["pass --contract PATH pointing at the pinned checkout"]
    if lock_errors:
        shape_status, shape_receipts = "FAIL", lock_errors
    elif contract is not None and manifest_path.is_file():
        shape_status, shape_receipts = _contract_shape(manifest_path, contract, lock["commit"])

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
    scaffold.add_argument("--job", action="store_true", help="the capability's work may outlive one request (fabric-interop/0.1 job)")
    scaffold.add_argument("--force", action="store_true")
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
