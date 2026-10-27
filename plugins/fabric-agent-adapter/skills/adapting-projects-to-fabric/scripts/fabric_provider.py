#!/usr/bin/env python3
"""Write and remove fabric-provider/0.1 entries: agents that are not services.

An agent reached as a CLI or a stdio MCP server announces itself with one entry in
the providers directory, beside the services directory. Only its installer writes the
entry and only its uninstaller removes it; the entry grants no Project access.
Standard library only; it does not import the service kit, so this skill stands alone.

  fabric_provider.py write --id ID --provider-id URI --name NAME --manifest PATH --installed-by TEXT
                           [--summary TEXT] [--repository URI]
                           (--url http://127.0.0.1:PORT/mcp | [--env NAME=secret-ref:REF ...] --stdio [--] EXECUTABLE [ARG ...])

--stdio is last: it takes the rest of the line. A writer option after it is refused; write `--stdio --` when the server
itself takes an option of the same name. --env is for a stdio server only and is refused with --url.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044, LC-21), beside this file

PROTOCOL = "fabric-provider/0.1"
# Copied from the pinned schemas (provider.schema.json, service-common.schema.json, common.schema.json) and applied
# with fullmatch, so a trailing newline never passes. test_provider.SchemaParityTests compares them with the pin.
URL_PATTERN = r"^http://127\.0\.0\.1:([1-9][0-9]{2,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])/mcp$"
LOCAL_PATH_PATTERN = "^(~[\\\\/]|/(?![\\\\/])|[A-Za-z]:[\\\\/])[^\\u0000]*$"
LOCAL_PATH_MAX = 1024
# DEC-0145 (CT-192): the manifest is named fabric-agent.json after either separator, so a Windows path names it too. The
# schema's pattern is a search, not a whole-value match; it is applied with its `$` read as \Z (R1, below).
MANIFEST_PATTERN = r"(^|[\\/])fabric-agent\.json$"
ARGV_MAX_ITEMS = 32
ARGV_MAX_ITEM = 1024
ENV_MAX = 64
# Whole-value patterns end in \Z, never `$` (R1: `$` also matches before a trailing newline).
_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}\Z")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*\Z")
# A special scheme (http, https, ws, wss, ftp) reads a user:password@ after any run of slashes, none included, as
# `new URL` does: https:bot:pw@host carries the password too (0.56.0 seam r7).
_URI_PASSWORD = re.compile(r"^(?:(?:[Hh][Tt][Tt][Pp][Ss]?|[Ww][Ss][Ss]?|[Ff][Tt][Pp]):[/\\]*[^/\\?#]*:[^/\\?#]*@"
                           # any other scheme: a backslash belongs to the user information (seam r8)
                           r"|(?![Hh][Tt][Tt][Pp][Ss]?:|[Ww][Ss][Ss]?:|[Ff][Tt][Pp]:)[A-Za-z][A-Za-z0-9+.-]*://[^/?#]*:[^/?#]*@)")
_SECRET_REF = re.compile(r"^secret-ref:([A-Za-z0-9][A-Za-z0-9._/:@-]{0,255})\Z")
_LOCAL_PATH = re.compile(LOCAL_PATH_PATTERN)
_URL = re.compile(URL_PATTERN)
_MANIFEST = re.compile(MANIFEST_PATTERN[:-1] + r"\Z")
# The manifest's name after a backslash: valid since DEC-0145, but no writer emits it until every reader accepts it.
_MANIFEST_AFTER_BACKSLASH = re.compile(r"\\fabric-agent\.json\Z")
# format: uri (RFC 3986 absolute URI): a scheme, a colon, then no whitespace or control character.
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x1f\x7f]+\Z")
# format: date-time (RFC 3339).
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})\Z")
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


WRITER_OPTIONS = {"--id", "--provider-id", "--name", "--summary", "--manifest", "--installed-by", "--repository", "--env", "--url", "--stdio"}


class ProviderError(Exception):
    """An entry was refused; the message is one readable sentence and never quotes a value."""


def services_dir() -> Path:
    override = os.environ.get("FABRIC_SERVICES_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric/services"
    if sys.platform == "win32":
        # provider.md "Where the directory is" (DEC-0032): LOCALAPPDATA, never the roaming APPDATA.
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "passioncode-fabric" / "services"
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
    if not isinstance(entry["id"], str) or not _ID.fullmatch(entry["id"]):
        problems.append("id must match %s" % _ID.pattern)
    if not _is_uri(entry["providerId"]):
        problems.append("providerId is the absolute URI of the manifest's provider.id")
    if not isinstance(entry["name"], str) or not 1 <= len(entry["name"]) <= 80:
        problems.append("name is 1 to 80 characters")
    if "summary" in entry and (not isinstance(entry["summary"], str) or len(entry["summary"]) > 200):
        problems.append("summary is at most 200 characters")
    manifest = entry["manifest"]
    if (not isinstance(manifest, str) or len(manifest) > LOCAL_PATH_MAX or not _LOCAL_PATH.fullmatch(manifest)
            or not _MANIFEST.search(manifest)):
        problems.append("manifest is an absolute, ~/ or ~\\ path to fabric-agent.json (the name after either separator), at most %d characters, "
                        "never a network share" % LOCAL_PATH_MAX)
    if "source" in entry:
        source = entry["source"]
        if not isinstance(source, dict) or not set(source) <= {"repository"}:
            problems.append("source is {repository?}")
        elif "repository" in source and not _is_uri(source["repository"]):
            problems.append("source.repository is an absolute URI")
        elif "repository" in source and (_URI_PASSWORD.match(source["repository"]) or _secrets.secret_argument(source["repository"])):
            # FAA-120, as the service kit: a repository is named, never reached with a credential in its URI.
            problems.append("source.repository carries no password or credential: it names the repository")
    if not isinstance(entry["installedAt"], str) or not _TIMESTAMP.fullmatch(entry["installedAt"]):
        problems.append("installedAt is an RFC 3339 date-time")
    if not isinstance(entry["installedBy"], str) or not 1 <= len(entry["installedBy"]) <= 200:
        problems.append("installedBy is 1 to 200 characters")
    if "extensions" in entry and (not isinstance(entry["extensions"], dict) or not all(_is_uri(k) for k in entry["extensions"])):
        problems.append("extensions is an object whose keys are URIs")
    problems.extend(_run_problems(entry["run"]))
    return problems


def _is_uri(value: Any) -> bool:
    return isinstance(value, str) and bool(_URI.fullmatch(value))


def _run_problems(run: Any) -> List[str]:
    mcp = run.get("mcp") if isinstance(run, dict) and set(run) == {"mcp"} else None
    if not isinstance(mcp, dict) or len(mcp) != 1 or not set(mcp) <= {"stdio", "url"}:
        return ["run is {mcp: {stdio: ...}} or {mcp: {url: ...}}, exactly one"]
    if "url" in mcp:
        url = mcp["url"]
        return [] if isinstance(url, str) and _URL.fullmatch(url) else ["run.mcp.url is http://127.0.0.1:<port>/mcp with a port from 100 to 65535"]
    stdio = mcp["stdio"]
    problems: List[str] = []
    if not isinstance(stdio, dict) or not set(stdio) <= {"command", "env", "scope"} or "command" not in stdio:
        return ["run.mcp.stdio is {command, env?, scope?}"]
    # DEC-0044, LC-19: where a host starts the server. A server started in every session is refused (FAC-SEM-056).
    if "scope" in stdio and stdio["scope"] not in ("project", "on-demand"):
        problems.append("run.mcp.stdio.scope is project or on-demand; a stdio server started in every session is refused (FAC-SEM-056, LC-19)")
    command = stdio["command"]
    if not isinstance(command, list) or not 1 <= len(command) <= ARGV_MAX_ITEMS or not all(isinstance(a, str) and a for a in command):
        problems.append("run.mcp.stdio.command is an argument array of 1 to %d non-empty strings, never a shell string" % ARGV_MAX_ITEMS)
    elif any(len(a) > ARGV_MAX_ITEM for a in command):
        problems.append("run.mcp.stdio.command has an argument over %d characters" % ARGV_MAX_ITEM)
    elif any(_secrets.secret_argument(a) for a in command):
        problems.append("run.mcp.stdio.command carries a credential in an argument; argv is visible to every process (LC-21, FAC-SEM-057): pass it as a secret reference in env")
    env = stdio.get("env", {})
    if not isinstance(env, dict):
        return problems + ["run.mcp.stdio.env is an object"]
    if len(env) > ENV_MAX:
        problems.append("run.mcp.stdio.env has at most %d names" % ENV_MAX)
    for name, value in env.items():
        if not _ENV_NAME.fullmatch(name):
            problems.append("env name %s is not an environment variable name" % name)
        reference = _SECRET_REF.fullmatch(value) if isinstance(value, str) else None
        if not reference or looks_like_credential(reference.group(1)):
            problems.append("env %s must be a secret reference (secret-ref:<name>), never a secret value (FAC-SEM-015)" % name)
    return problems


def manifest_problems(entry: Dict[str, Any]) -> List[str]:
    """FAC-SEM-014 (DEC-0017), URI half: the manifest resolves and its provider.id equals providerId, compared by normal
    form (DEC-0076)."""
    try:
        manifest = json.loads(Path(os.path.expanduser(str(entry["manifest"]))).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["the manifest %s does not resolve (FAC-SEM-014)" % entry["manifest"]]
    provider = manifest.get("provider") if isinstance(manifest, dict) else None
    if not isinstance(provider, dict) or not isinstance(manifest.get("capabilities"), list):
        return ["%s is not a provider manifest (FAC-SEM-014)" % entry["manifest"]]
    import fabric_identifiers  # noqa: E402 - beside this file; DEC-0076: URIs compared by normal form
    if not fabric_identifiers.same_identifier(provider.get("id"), entry["providerId"]):
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
    if problems:
        raise ProviderError("Provider entry is invalid: %s." % "; ".join(problems))
    if _MANIFEST_AFTER_BACKSLASH.search(entry["manifest"]):
        # provider.md (DEC-0145): a reader before DEC-0145, Fabric's registry among them, refuses this entry until it
        # re-pins (CT-192), so the writer does not emit it yet.
        raise ProviderError("The manifest's name follows a backslash, which a reader that has not re-pinned to DEC-0145 refuses (CT-192). "
                            "Write the path with / before the name, as C:/.../fabric-agent.json, which every reader accepts.")
    problems = manifest_problems(entry)
    if problems:
        raise ProviderError("Provider entry is invalid: %s." % "; ".join(problems))
    clash = _service_ids(services or services_dir()).get(entry["id"])
    if clash:
        raise ProviderError("%s is already a service (%s); an id is a service or a provider, never both (FAC-SEM-013)." % (entry["id"], clash))
    import fabric_identifiers  # noqa: E402 - beside this file
    # DEC-0076: written in its normal form, so a reader that looks it up finds one spelling.
    entry = dict(entry, providerId=fabric_identifiers.normal_identifier(entry["providerId"]))
    target = (directory or providers_dir()) / ("%s.json" % entry["id"])
    _atomic_write(target, (json.dumps(entry, indent=2, ensure_ascii=False) + "\n").encode())
    return target


def remove_provider_entry(provider_id: str, directory: Optional[Path] = None) -> bool:
    """Uninstaller-only. Returns whether there was an entry to remove."""
    if not _ID.fullmatch(provider_id):
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
    transport.add_argument("--stdio", action="store_true", help="the executable and its arguments follow, last on the line")
    remove = sub.add_parser("remove")
    remove.add_argument("id")
    check = sub.add_parser("validate")
    check.add_argument("path", type=Path)
    argv = list(sys.argv[1:] if argv is None else argv)
    # --stdio takes the rest of the line. It is split off here rather than by argparse, whose REMAINDER handling of
    # a leading `--` differs between Python versions.
    stdio_tail: Optional[List[str]] = None
    if argv[:1] == ["write"] and "--stdio" in argv:
        at = argv.index("--stdio")
        argv, stdio_tail = argv[:at + 1], argv[at + 1:]
    args = parser.parse_args(argv)
    try:
        if args.command == "remove":
            print("removed" if remove_provider_entry(args.id) else "no entry for %s" % args.id)
            return 0
        if args.command == "validate":
            entry = json.loads(args.path.read_text(encoding="utf-8"))
            problems = validate_provider_entry(entry)
            # CT-193 (FAC-SEM-014): the stem is what follows the last / or \ and loses .json, on every platform.
            stem = re.sub(r"\.json\Z", "", re.sub(r"^.*[\\/]", "", str(args.path), flags=re.S))
            if isinstance(entry, dict) and entry.get("id") != stem:
                problems.append("the file name %s is not <id>.json for %s (FAC-SEM-014)" % (args.path.name, entry.get("id")))
            if not problems:
                problems = manifest_problems(entry)
            print("; ".join(problems) if problems else "valid")
            return 1 if problems else 0
        if args.env and args.url:
            raise ProviderError("--env applies only to a stdio server; a --url server reads its own environment. Drop --env or use --stdio.")
        command = list(stdio_tail or [])
        if command and command[0] == "--":
            command = command[1:]  # everything after -- belongs to the server, its own --name included
        else:
            misplaced = [a for a in command if a.split("=", 1)[0] in WRITER_OPTIONS]
            if misplaced:
                raise ProviderError("%s came after --stdio, which takes the rest of the line as the server's command. Put writer options before --stdio, "
                                    "or write --stdio -- EXECUTABLE ... when the server itself takes that option." % misplaced[0].split("=", 1)[0])
        if args.stdio and not command:
            raise ProviderError("--stdio needs the executable and its arguments.")
        env: Dict[str, str] = {}
        for pair in args.env:
            name, sep, value = pair.partition("=")
            if not sep:
                raise ProviderError("--env takes NAME=secret-ref:REF.")
            env[name] = value
        run: Dict[str, Any] = {"mcp": {"url": args.url}} if args.url else {"mcp": {"stdio": {"command": command}}}
        if env:
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
