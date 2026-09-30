#!/usr/bin/env python3
"""Write and remove fabric-provider/0.1 entries: agents that are not services.

An agent reached as a CLI or a stdio MCP server announces itself with one entry in
the providers directory, beside the services directory. Only its installer writes the
entry and only its uninstaller removes it; the entry grants no Project access.
Standard library only; it does not import the service kit, so this skill stands alone.

  fabric_provider.py write --id ID --provider-id URI --name NAME --manifest PATH --installed-by TEXT
                           (--url http://127.0.0.1:PORT/mcp | --stdio EXECUTABLE [ARG ...])
                           [--env NAME=secret-ref:REF ...] [--summary TEXT] [--repository URL]
  fabric_provider.py remove ID
  fabric_provider.py validate PATH

Normative source: fabric-agent-contract docs/specification/provider.md (DEC-0016, rulings DEC-0017).
"""

# #region provider-writer — docs: plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/references/provider-entry.md#the-writer

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional

PROTOCOL = "fabric-provider/0.1"
_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SECRET_REF = re.compile(r"^secret-ref:([A-Za-z0-9][A-Za-z0-9._/:@-]{0,255})$")
_LOCAL_PATH = re.compile(r"^(~/|/)[^\x00]*$")
_URL = re.compile(r"^http://127\.0\.0\.1:([0-9]{1,5})/mcp$")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
FIELDS = {"protocol", "id", "providerId", "name", "summary", "manifest", "run", "source", "installedAt", "installedBy", "extensions"}
# FAC-SEM-015 reads a credential by its SHAPE: a reference named after a key is fine.
CREDENTIAL_SHAPES = [re.compile(p) for p in (
    r"^(sk|pk|rk)[-_](live|test|proj|or|ant)?[-_]?[A-Za-z0-9_-]{16,}",
    r"^(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
    r"^github_pat_[A-Za-z0-9_]{20,}",
    r"^xox[abprs]-[A-Za-z0-9-]{10,}",
    r"^(AKIA|ASIA)[A-Z0-9]{16}$",
    r"^lin_api_[A-Za-z0-9]{20,}",
    r"^AIza[0-9A-Za-z_-]{30,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])[A-Za-z0-9+=_-]{32,}$",
)]


class ProviderError(Exception):
    """An entry was refused; the message is one readable sentence and never quotes a value."""


def services_dir() -> Path:
    override = os.environ.get("FABRIC_SERVICES_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric/services"
    return Path(os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")) / "passioncode-fabric/services"


def providers_dir() -> Path:
    """FABRIC_PROVIDERS_DIR, else `providers/` in the same root as `services/`."""
    override = os.environ.get("FABRIC_PROVIDERS_DIR")
    if override:
        return Path(override).expanduser()
    return services_dir().parent / "providers"


def looks_like_credential(value: str) -> bool:
    return any(shape.search(value) for shape in CREDENTIAL_SHAPES)


def validate_provider_entry(entry: Any) -> List[str]:
    """Mirrors provider.schema.json and FAC-SEM-015 (the schema stays normative)."""
    if not isinstance(entry, dict):
        return ["an entry is a JSON object"]
    problems: List[str] = []
    for key in ("protocol", "id", "providerId", "name", "manifest", "run", "installedAt", "installedBy"):
        if key not in entry:
            problems.append("missing %s" % key)
    for key in sorted(set(entry) - FIELDS):
        problems.append("unknown field %s" % key)
    if problems:
        return problems
    if entry["protocol"] != PROTOCOL:
        problems.append("protocol must be %s" % PROTOCOL)
    if not _ID.match(str(entry["id"])):
        problems.append("id must match %s" % _ID.pattern)
    if not _URI.match(str(entry["providerId"])):
        problems.append("providerId is the absolute URI of the manifest's provider.id")
    if not isinstance(entry["name"], str) or not 1 <= len(entry["name"]) <= 80:
        problems.append("name is 1 to 80 characters")
    if "summary" in entry and (not isinstance(entry["summary"], str) or len(entry["summary"]) > 200):
        problems.append("summary is at most 200 characters")
    manifest = str(entry["manifest"])
    if not _LOCAL_PATH.match(manifest) or not re.search(r"(^|/)fabric-agent\.json$", manifest):
        problems.append("manifest is an absolute or ~/ path to fabric-agent.json")
    problems.extend(_run_problems(entry["run"]))
    return problems


def _run_problems(run: Any) -> List[str]:
    mcp = run.get("mcp") if isinstance(run, dict) and set(run) == {"mcp"} else None
    if not isinstance(mcp, dict) or len(mcp) != 1 or not set(mcp) <= {"stdio", "url"}:
        return ["run is {mcp: {stdio: ...}} or {mcp: {url: ...}}, exactly one"]
    if "url" in mcp:
        match = _URL.match(str(mcp["url"]))
        return [] if match and 1 <= int(match.group(1)) <= 65535 else ["run.mcp.url is http://127.0.0.1:<port>/mcp"]
    stdio = mcp["stdio"]
    problems: List[str] = []
    if not isinstance(stdio, dict) or not set(stdio) <= {"command", "env"} or "command" not in stdio:
        return ["run.mcp.stdio is {command, env?}"]
    command = stdio["command"]
    if not isinstance(command, list) or not 1 <= len(command) <= 32 or not all(isinstance(a, str) and a for a in command):
        problems.append("run.mcp.stdio.command is an argument array, never a shell string")
    env = stdio.get("env", {})
    if not isinstance(env, dict):
        return problems + ["run.mcp.stdio.env is an object"]
    for name, value in env.items():
        if not _ENV_NAME.match(name):
            problems.append("env name %s is not an environment variable name" % name)
        reference = _SECRET_REF.match(value) if isinstance(value, str) else None
        if not reference or looks_like_credential(reference.group(1)):
            problems.append("env %s must be a secret reference (secret-ref:<name>), never a secret value (FAC-SEM-015)" % name)
    return problems


def manifest_problems(entry: Dict[str, Any]) -> List[str]:
    """FAC-SEM-014 (DEC-0017), URI half: the manifest resolves and its provider.id equals providerId."""
    try:
        manifest = json.loads(Path(os.path.expanduser(str(entry["manifest"]))).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["the manifest %s does not resolve (FAC-SEM-014)" % entry["manifest"]]
    provider = manifest.get("provider") if isinstance(manifest, dict) else None
    if not isinstance(provider, dict) or not isinstance(manifest.get("capabilities"), list):
        return ["%s is not a provider manifest (FAC-SEM-014)" % entry["manifest"]]
    if provider.get("id") != entry["providerId"]:
        return ["providerId %s is not the manifest's provider.id %s (FAC-SEM-014)" % (entry["providerId"], provider.get("id"))]
    return []


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _service_ids(directory: Path) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                ids.setdefault(str(json.loads(path.read_text(encoding="utf-8")).get("id")), path.name)
            except (OSError, ValueError, AttributeError):
                continue
    return ids


def write_provider_entry(entry: Dict[str, Any], directory: Optional[Path] = None, services: Optional[Path] = None) -> Path:
    """Installer-only. Refuses an invalid entry and an id that is already a service (FAC-SEM-013)."""
    problems = validate_provider_entry(entry)
    if not problems:
        problems = manifest_problems(entry)
    if problems:
        raise ProviderError("Provider entry is invalid: %s." % "; ".join(problems))
    clash = _service_ids(services or services_dir()).get(entry["id"])
    if clash:
        raise ProviderError("%s is already a service (%s); an id is a service or a provider, never both (FAC-SEM-013)." % (entry["id"], clash))
    target = (directory or providers_dir()) / ("%s.json" % entry["id"])
    _atomic_write(target, (json.dumps(entry, indent=2, ensure_ascii=False) + "\n").encode())
    return target


def remove_provider_entry(provider_id: str, directory: Optional[Path] = None) -> bool:
    """Uninstaller-only. Returns whether there was an entry to remove."""
    if not _ID.match(provider_id):
        raise ProviderError("Provider id %s does not match %s." % (provider_id, _ID.pattern))
    try:
        ((directory or providers_dir()) / ("%s.json" % provider_id)).unlink()
        return True
    except FileNotFoundError:
        return False


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("--id", required=True)
    write.add_argument("--provider-id", required=True, help="the manifest's provider.id (a URI)")
    write.add_argument("--name", required=True)
    write.add_argument("--summary")
    write.add_argument("--manifest", required=True)
    write.add_argument("--installed-by", required=True)
    write.add_argument("--repository")
    write.add_argument("--env", action="append", default=[], help="NAME=secret-ref:REF (a reference, never a value)")
    transport = write.add_mutually_exclusive_group(required=True)
    transport.add_argument("--url")
    transport.add_argument("--stdio", nargs=argparse.REMAINDER, help="the executable and its arguments, last on the line")
    remove = sub.add_parser("remove")
    remove.add_argument("id")
    check = sub.add_parser("validate")
    check.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "remove":
            print("removed" if remove_provider_entry(args.id) else "no entry for %s" % args.id)
            return 0
        if args.command == "validate":
            entry = json.loads(args.path.read_text(encoding="utf-8"))
            problems = validate_provider_entry(entry)
            if isinstance(entry, dict) and entry.get("id") != args.path.stem:
                problems.append("the file name %s is not <id>.json for %s (FAC-SEM-014)" % (args.path.name, entry.get("id")))
            if not problems:
                problems = manifest_problems(entry)
            print("; ".join(problems) if problems else "valid")
            return 1 if problems else 0
        env: Dict[str, str] = {}
        for pair in args.env:
            name, sep, value = pair.partition("=")
            if not sep:
                raise ProviderError("--env takes NAME=secret-ref:REF.")
            env[name] = value
        run: Dict[str, Any] = {"mcp": {"url": args.url}} if args.url else {"mcp": {"stdio": {"command": args.stdio}}}
        if env and args.stdio:
            run["mcp"]["stdio"]["env"] = env
        entry: Dict[str, Any] = {"protocol": PROTOCOL, "id": args.id, "providerId": args.provider_id, "name": args.name, "manifest": args.manifest,
                                 "run": run, "installedAt": _now(), "installedBy": args.installed_by}
        if args.summary:
            entry["summary"] = args.summary
        if args.repository:
            entry["source"] = {"repository": args.repository}
        print(write_provider_entry(entry))
        return 0
    except (ProviderError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
# #endregion provider-writer
