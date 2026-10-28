#!/usr/bin/env python3
"""Find instance data in an agent's source tree, without repeating it (FAA-188 part 1).

An agent's source is what can be handed over (code, skills, prompts, schemas, examples); its instance is what belongs
to one installation (records, logs, keys, the owner's names and paths, its configuration). This check reads the files
the source would carry and reports, by path, line and kind, each place where the instance shows through:

- `home-path`: an absolute path inside a person's home folder (`/Users/<name>/`, `/home/<name>/`, `C:\\Users\\<name>\\`);
  a neutral name (`example`, `user`, `runner`, ...), a one-letter name or a placeholder (`<name>`, `$USER`) is not a
  finding;
- `secret`: a value shaped like a credential, by the contract's detector (fabric_secrets.py, DEC-0044), or a private
  key block; a value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) is not a finding;
- `instance-string`: a string from the owner's list of instance strings (names, accounts, hosts), kept outside the tree.

It never prints a value it found, a line that holds one, or an entry of the owner's list: a finding names its path,
line, kind and rule, and an instance string by its entry number. It changes nothing. Exit 0: no finding; 1: at least
one; 2: the check could not run.

  fabric_source_check.py check [ROOT] [--instance-strings FILE] [--exclude GLOB ...] [--json]

The files read are those Git would commit (`git ls-files --cached --others --exclude-standard`), or every file outside
`.git`, `node_modules`, `__pycache__` and virtual environments when ROOT is not a Git checkout. Globs in ROOT's
`.fabric-source-ignore` (one per line, `#` comments) and `--exclude` leave matching paths out. The owner's list is
`--instance-strings`, else the file `FABRIC_INSTANCE_STRINGS` names, else
`~/.config/passioncode-fabric/instance-strings.txt` when it exists: one string per line, `#` comments, strings shorter
than three characters ignored, matched without regard to case. A list inside ROOT is refused: it would travel with
the source. Standard library only.
"""

# #region source-check — docs: plugins/fabric-agent-adapter/skills/creating-fabric-agents/references/source-and-instance.md#the-check

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file

IGNORE_FILE = ".fabric-source-ignore"
DEFAULT_LIST = Path("~/.config/passioncode-fabric/instance-strings.txt")
MAX_BYTES = 1 << 20
WALK_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
#: Names that stand for nobody in a home path: placeholders, CI runners and the system's shared folders.
NEUTRAL_HOMES = {"example", "examples", "user", "username", "you", "me", "name", "someone", "runner", "shared", "public",
                 "default", "guest", "linuxbrew", "alice", "bob", "operator", "owner", "person", "your-name", "yourname"}
HOME_PATH = re.compile(r"(?<![A-Za-z0-9_.-])(?:/Users/|/home/|[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+)"
                       r"([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
#: Words a documented or synthetic credential carries (AWS's `...EXAMPLE`, `sk-test-not-a-key`); a random key does not.
SYNTHETIC = ("example", "not-a-key", "notakey", "fake", "dummy", "placeholder", "redacted")


class CheckError(Exception):
    pass


def _home_finding(line: str) -> Optional[str]:
    for match in HOME_PATH.finditer(line):
        name = match.group(1).lower()
        if len(name) > 1 and name not in NEUTRAL_HOMES:  # a one-letter home (`/Users/a`) is a test's placeholder
            return "a path inside a person's home folder"
    return None


def _real(token: str) -> bool:
    lowered = token.lower()
    return not any(word in lowered for word in SYNTHETIC)


def _secret_finding(line: str) -> Optional[str]:
    if PRIVATE_KEY.search(line):
        return "a private key block"
    if any(_real(m.group(0)) for m in _secrets.JWT_SHAPE.finditer(line)):
        return "a token shaped like a JWT"
    # The detector's own `^bearer ...` reads a whole header value; in a file it would take prose that starts with the
    # word, so a bearer token is looked for as `_BEARER_INSIDE` does: the word, then a run of 12 or more with a digit.
    if any(not m.group(0).lower().startswith("bearer") and _real(m.group(0)) for m in _secrets.SECRET_VALUE.finditer(line)):
        return "a value shaped like a provider key"
    if any(_real(m.group(0)) for m in _secrets._BEARER_INSIDE.finditer(line)):
        return "a bearer token"
    return None


def read_list(path: Path) -> List[str]:
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        entries.append("" if not text or text.startswith("#") or len(text) < 3 else text.casefold())
    return entries


def _instance_finding(text: str, entries: List[str]) -> Optional[str]:
    folded = text.casefold()
    for number, entry in enumerate(entries, 1):
        if entry and entry in folded:
            return "a string from the owner's list (entry %d)" % number
    return None


def _git_files(root: Path) -> Optional[List[str]]:
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return sorted({p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p})


def _walk_files(root: Path) -> List[str]:
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in WALK_SKIP]
        for name in files:
            found.append(Path(folder, name).relative_to(root).as_posix())
    return sorted(found)


def ignore_globs(root: Path, extra: Iterable[str]) -> List[str]:
    globs = list(extra)
    ignore = root / IGNORE_FILE
    if ignore.is_file():
        globs += [line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.strip().startswith("#")]
    return globs


def _ignored(path: str, globs: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(path, g.rstrip("/") + "/*") for g in globs)


def check(root: Path, entries: List[str], globs: List[str]) -> Dict[str, object]:
    """Read the tree and return {files, skipped, findings}; a finding is {path, line, kind, rule} and never a value."""
    files = _git_files(root)
    if files is None:
        files = _walk_files(root)
    findings: List[Dict[str, object]] = []
    read = 0
    skipped = {"large": 0, "binary": 0, "unreadable": 0}
    for path in files:
        if _ignored(path, globs):
            continue
        rule = _instance_finding(path, entries)
        if rule:
            findings.append({"path": path, "line": 0, "kind": "instance-string", "rule": rule + " in the file's path"})
        full = root / path
        try:
            if full.is_symlink() or not full.is_file():
                continue
            if full.stat().st_size > MAX_BYTES:
                skipped["large"] += 1
                continue
            data = full.read_bytes()
        except OSError:
            skipped["unreadable"] += 1
            continue
        if b"\0" in data[:8192]:
            skipped["binary"] += 1
            continue
        read += 1
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for kind, rule in (("home-path", _home_finding(line)), ("secret", _secret_finding(line)),
                               ("instance-string", _instance_finding(line, entries))):
                if rule:
                    findings.append({"path": path, "line": number, "kind": kind, "rule": rule})
    return {"files": read, "skipped": skipped, "findings": findings}


def _list_path(given: Optional[str]) -> Tuple[Optional[Path], bool]:
    """The owner's list and whether it was named (a named list that is missing is an error; the default is optional)."""
    if given:
        return Path(given).expanduser(), True
    if os.environ.get("FABRIC_INSTANCE_STRINGS"):
        return Path(os.environ["FABRIC_INSTANCE_STRINGS"]).expanduser(), True
    default = DEFAULT_LIST.expanduser()
    return (default, False) if default.is_file() else (None, False)


def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="fabric_source_check.py", description="Find instance data in an agent's source.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("check", help="read the source tree and report instance data without repeating it")
    cmd.add_argument("root", nargs="?", default=".")
    cmd.add_argument("--instance-strings", metavar="FILE")
    cmd.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    cmd.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():
            raise CheckError("%s is not a folder" % args.root)
        list_path, named = _list_path(args.instance_strings)
        entries: List[str] = []
        if list_path is not None:
            resolved = list_path.resolve()
            if resolved == root or root in resolved.parents:
                raise CheckError("the owner's list is inside the tree it checks, where it would travel with the source; "
                                 "keep it outside, for example in ~/.config/passioncode-fabric/instance-strings.txt")
            try:
                entries = read_list(resolved)
            except (OSError, UnicodeDecodeError):
                if named:
                    raise CheckError("the owner's list cannot be read")
        result = check(root, entries, ignore_globs(root, args.exclude))
    except CheckError as exc:
        print("fabric_source_check.py: %s" % exc, file=sys.stderr)
        return 2
    findings = result["findings"]
    result.update({"root": str(root), "instanceStrings": sum(1 for e in entries if e), "blocking": bool(findings)})
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for f in findings:  # type: ignore[union-attr]
            print("%s:%s: %s (%s)" % (f["path"], f["line"], f["kind"], f["rule"]))
        skipped = result["skipped"]
        print("%d file(s) read, %d finding(s); skipped %d large, %d binary, %d unreadable; %d instance string(s) listed%s"
              % (result["files"], len(findings), skipped["large"], skipped["binary"], skipped["unreadable"],  # type: ignore[index]
                 result["instanceStrings"], "" if result["instanceStrings"] else " (no owner's list)"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(run())

# #endregion source-check
