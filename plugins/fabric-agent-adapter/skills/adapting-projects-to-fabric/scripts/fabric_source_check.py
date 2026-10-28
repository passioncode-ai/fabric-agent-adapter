#!/usr/bin/env python3
"""Find instance data in an agent's source tree, without repeating it (FAA-188 part 1).

An agent's source is what can be handed over (code, skills, prompts, schemas, examples); its instance is what belongs
to one installation (records, logs, keys, the owner's names and paths, its configuration). This check reads the files
the source would carry and reports, by path, line and kind, each place where the instance shows through:

- `home-path`: an absolute path inside a person's home folder: `/Users/<name>/`, `/home/<name>/`, `/var/home/<name>/`,
  `C:\\Users\\<name>\\` (any case, either separator, a JSON-escaped backslash), the dashed form a tool makes of such a
  path (`-Users-<name>-`, DEC-0105) and the URL-encoded one (`%2FUsers%2F<name>`); a neutral name (`example`, `user`,
  `runner`, a container's or a cloud machine's user such as `node` or `ubuntu`), a one-letter name or a placeholder
  (`<name>`, `$USER`) is not a finding;
- `secret`: a value shaped like a credential by the contract's detector (fabric_secrets.py, DEC-0044), read line by
  line: a provider key starting a word, a JWT, a bearer token, or a long run mixing upper case, lower case and digits
  assigned to a name that can only carry a credential (a bare long run, such as an integrity hash, is not); or a
  private key block. A value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) is
  not a finding;
- `instance-string`: a string from the owner's list of instance strings (names, accounts, hosts), kept outside the tree.

It never prints a value it found, a line that holds one, an entry of the owner's list or the folder it checks: a
finding names its path (an entry of the list or a home folder's name in the path is printed as `<entry N>` or
`<home>`), line, kind and rule, and an instance string by its line in the owner's list. It changes nothing. Exit 0:
every file was read and none holds a finding; 1: at least one finding; 2: the check could not run, or a file could not
be read (the summary counts them).

  fabric_source_check.py check [ROOT] [--instance-strings FILE] [--exclude GLOB ...] [--json]

The files read are those Git would commit (`git ls-files --cached --others --exclude-standard`), or, when ROOT is not
in a Git checkout or Git lists nothing in it, every file outside `.git`, `node_modules`, `__pycache__` and virtual
environments. A committed symbolic link is checked by the path it names, never followed. A binary file (a NUL byte in
its first 8 KiB) is not read; the summary counts it. Globs in ROOT's `.fabric-source-ignore` (one per line, `#`
comments) and `--exclude` leave matching paths out. The owner's list is `--instance-strings`, else the file
`FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
(`$XDG_CONFIG_HOME` or `~/.config`; `%APPDATA%` on Windows) when it exists: one string per
line, `#` comments, strings shorter than three characters ignored, matched without regard to case. A list inside ROOT
is refused: it would travel with the source. The summary says whether Git chose the files or every file was read.
Standard library only.
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
from typing import Dict, Iterable, List, NoReturn, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file

IGNORE_FILE = ".fabric-source-ignore"
LIST_NAME = "instance-strings.txt"
WALK_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
#: Names that stand for nobody in a home path: placeholders, CI runners and the system's shared folders.
NEUTRAL_HOMES = {"example", "examples", "user", "username", "you", "me", "name", "someone", "runner", "shared", "public",
                 "default", "guest", "linuxbrew", "alice", "bob", "operator", "owner", "person", "your-name", "yourname",
                 # the users of container images, cloud machines and hosted CI
                 "node", "ubuntu", "ec2-user", "runneradmin", "admin", "vagrant", "debian", "centos", "app", "builder"}
_SEP = r"(?:\\\\|\\|/)+"
HOME_PATHS = (
    re.compile(r"(?<![A-Za-z0-9_.-])(?:/var)?/home/([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII),
    re.compile(r"(?<![A-Za-z0-9_.-])/Users/([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII | re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:%sUsers%s([A-Za-z0-9][A-Za-z0-9._-]*)" % (_SEP, _SEP), re.ASCII | re.IGNORECASE),
    re.compile(r"(?:^|[^A-Za-z0-9])-(?:Users|home)-([A-Za-z0-9][A-Za-z0-9._]*)", re.ASCII | re.IGNORECASE),  # DEC-0105
    re.compile(r"%2F(?:Users|home)%2F([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII | re.IGNORECASE),
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
#: Words a documented or synthetic credential carries (AWS's `...EXAMPLE`, `sk-test-not-a-key`); a random key does not.
SYNTHETIC = ("example", "not-a-key", "notakey", "fake", "dummy", "placeholder", "redacted")
# The detector's provider-key shapes without its first alternative, `^bearer\s.+`, which reads a whole header value: in
# a file it would take prose that starts with the word and hide a key later on the same line. A bearer token is looked
# for as `_BEARER_INSIDE` does: the word, then a run of 12 or more with a digit.
_BEARER_FIRST = "(^bearer["
assert _secrets.SECRET_VALUE.pattern.startswith(_BEARER_FIRST), "fabric_secrets.SECRET_VALUE changed its first branch"
PROVIDER_KEY = re.compile("(" + _secrets.SECRET_VALUE.pattern.split("|", 1)[1], _secrets.SECRET_VALUE.flags)
#: `NAME = value`, `NAME: value` or `"name": "value"`: the long-run rule applies only where the name carries a credential.
#: The name is bounded and starts a word, so a long line is read in linear time.
ASSIGNED = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]{0,63})[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?"
                      r"([A-Za-z0-9+/=_-]{40,})")


class CheckError(Exception):
    pass


def _home_names(text: str) -> List[Tuple[int, int]]:
    """The spans of the names of real people's home folders in a text (neutral and one-letter names left out)."""
    spans = []
    for pattern in HOME_PATHS:
        for match in pattern.finditer(text):
            name = match.group(1).lower()
            if len(name) > 1 and name not in NEUTRAL_HOMES:  # a one-letter home (`/Users/a`) is a test's placeholder
                spans.append(match.span(1))
    return spans


def _real(token: str) -> bool:
    lowered = token.lower()
    return not any(word in lowered for word in SYNTHETIC)


def _secret_finding(line: str) -> Optional[str]:
    if PRIVATE_KEY.search(line):
        return "a private key block"
    if any(_real(m.group(0)) for m in _secrets.JWT_SHAPE.finditer(line)):
        return "a token shaped like a JWT"
    # The detector reads one configuration value; across a line, `sk-` needs a word start of its own, or every name
    # with a segment ending in `sk` (`task-management-service`) would read as a key.
    if any(_real(m.group(0)) and (m.start() == 0 or not line[m.start() - 1].isalnum()) for m in PROVIDER_KEY.finditer(line)):
        return "a value shaped like a provider key"
    if any(_real(m.group(0)) for m in _secrets._BEARER_INSIDE.finditer(line)):
        return "a bearer token"
    for name, value in (ASSIGNED.findall(line) if ":" in line or "=" in line else ()):
        if _secrets.credential_name(name) and _secrets._long_secret(value) and _real(value):
            return "a long random value assigned to a credential's name"
    return None


def read_list(path: Path) -> List[str]:
    """The owner's list, one item per line: an entry casefolded, or '' for a comment, a blank or too short a line."""
    entries = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        entries.append("" if not text or text.startswith("#") or len(text) < 3 else text.casefold())
    return entries


def _entry_spans(text: str, entries: List[str]) -> List[Tuple[int, int, int]]:
    folded = text.casefold()
    spans = []
    if len(folded) != len(text):  # casefolding changed the length (ß, ﬁ): match, but mask the whole text
        return [(0, len(text), n) for n, e in enumerate(entries, 1) if e and e in folded][:1]
    for number, entry in enumerate(entries, 1):
        if entry:
            start = folded.find(entry)
            while start != -1:
                spans.append((start, start + len(entry), number))
                start = folded.find(entry, start + 1)
    return spans


def _instance_finding(text: str, entries: List[str]) -> Optional[str]:
    spans = _entry_spans(text, entries)
    return "a string from the owner's list (line %d)" % spans[0][2] if spans else None


def redact(path: str, entries: List[str]) -> str:
    """A path as it may be printed: each owner's string as `<entry N>`, each real home folder's name as `<home>`."""
    marks = [(s, e, "<entry %d>" % n) for s, e, n in _entry_spans(path, entries)]
    marks += [(s, e, "<home>") for s, e in _home_names(path)]
    out, last = [], 0
    for start, end, label in sorted(marks):
        if start < last:
            continue
        out += [path[last:start], label]
        last = end
    return "".join(out) + path[last:]


def _git_files(root: Path) -> Optional[List[str]]:
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return sorted({p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p})


def _walk_files(root: Path, unreadable: List[str]) -> List[str]:
    found = []
    for folder, dirs, files in os.walk(root, onerror=lambda error: unreadable.append(str(error.filename or ""))):
        dirs[:] = [d for d in dirs if d not in WALK_SKIP]
        for name in files:
            found.append(Path(folder, name).relative_to(root).as_posix())
    return sorted(found)


def ignore_globs(root: Path, extra: Iterable[str]) -> List[str]:
    globs = list(extra)
    ignore = root / IGNORE_FILE
    if ignore.is_file():
        try:
            lines = ignore.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            raise CheckError("%s cannot be read as UTF-8" % IGNORE_FILE)
        globs += [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return globs


def _ignored(path: str, globs: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(path, g.rstrip("/") + "/*") for g in globs)


def _lines(data: bytes) -> Iterable[Tuple[int, str]]:
    """Lines as an editor numbers them: split at LF, a trailing CR dropped (str.splitlines also splits at FF, VT...)."""
    for number, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        yield number, line[:-1] if line.endswith("\r") else line


def _text_findings(text: str, entries: List[str]) -> List[Tuple[str, str]]:
    found = []
    if _home_names(text):
        found.append(("home-path", "a path inside a person's home folder"))
    secret = _secret_finding(text)
    if secret:
        found.append(("secret", secret))
    rule = _instance_finding(text, entries)
    if rule:
        found.append(("instance-string", rule))
    return found


def check(root: Path, entries: List[str], globs: List[str]) -> Dict[str, object]:
    """Read the tree and return {files, skipped, findings}; a finding is {path, line, kind, rule}, its path redacted."""
    unreadable: List[str] = []
    files = _git_files(root)
    mode = "git"
    if not files:  # not a checkout, Git refused it, or a folder Git ignores or holds nothing of: read what is there
        files, mode = _walk_files(root, unreadable), "walk"
    findings: List[Dict[str, object]] = []
    read = 0
    skipped = {"binary": 0, "unreadable": len(unreadable)}

    def add(path: str, line: int, kind: str, rule: str) -> None:
        findings.append({"path": redact(path, entries), "line": line, "kind": kind, "rule": rule})

    for path in files:
        if _ignored(path, globs):
            continue
        rule = _instance_finding(path, entries)
        if rule:
            add(path, 0, "instance-string", rule + " in the file's path")
        full = root / path
        try:
            if full.is_symlink():  # Git commits the path a link names: check it, never follow it
                read += 1
                for kind, rule in _text_findings(os.readlink(full), entries):
                    add(path, 0, kind, rule + " in the link's target")
                continue
            if not full.is_file():
                continue
            with open(full, "rb") as handle:
                data = handle.read()
        except OSError:
            skipped["unreadable"] += 1
            continue
        if b"\0" in data[:8192]:
            skipped["binary"] += 1
            continue
        read += 1
        for number, line in _lines(data):
            for kind, rule in _text_findings(line, entries):
                add(path, number, kind, rule)
    return {"mode": mode, "files": read, "skipped": skipped, "findings": findings}


def default_list(platform: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Path:
    """Where the owner's list is kept when none is named: the user's configuration folder, never a project's."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "win32":
        base = Path(env["APPDATA"]) if env.get("APPDATA") else Path.home() / "AppData" / "Roaming"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "passioncode-fabric" / LIST_NAME


def _list_path(given: Optional[str]) -> Tuple[Optional[Path], bool]:
    """The owner's list and whether it must be read (a named or an existing default list; else no list)."""
    if given:
        return Path(given).expanduser(), True
    if os.environ.get("FABRIC_INSTANCE_STRINGS"):
        return Path(os.environ["FABRIC_INSTANCE_STRINGS"]).expanduser(), True
    default = default_list()
    return (default, True) if default.is_file() else (None, False)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # argparse would repeat the arguments it could not read
        self.print_usage(sys.stderr)
        self.exit(2, "fabric_source_check.py: the arguments cannot be read; see the usage above\n")


def _print(text: str) -> None:
    """Print a line the console may not encode (a name in another script, a byte Git kept as a surrogate)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding, "replace"))


def run(argv: Optional[List[str]] = None) -> int:
    parser = _Parser(prog="fabric_source_check.py", description="Find instance data in an agent's source.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("check", help="read the source tree and report instance data without repeating it")
    cmd.add_argument("root", nargs="?", default=".")
    cmd.add_argument("--instance-strings", metavar="FILE")
    cmd.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    cmd.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, or arguments argparse refused: the exit code, as the command line gives it
        return exc.code if isinstance(exc.code, int) else 2
    try:
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():
            raise CheckError("ROOT is not a folder")
        list_path, named = _list_path(args.instance_strings)
        entries: List[str] = []
        if list_path is not None:
            resolved = list_path.resolve()
            if resolved == root or root in resolved.parents:
                raise CheckError("the owner's list is inside the tree it checks, where it would travel with the source; "
                                 "keep it in your configuration folder (passioncode-fabric/%s)" % LIST_NAME)
            try:
                entries = read_list(resolved)
            except (OSError, UnicodeDecodeError):
                if named:
                    raise CheckError("the owner's list cannot be read as UTF-8")
        result = check(root, entries, ignore_globs(root, args.exclude))
    except CheckError as exc:
        print("fabric_source_check.py: %s" % exc, file=sys.stderr)
        return 2
    findings = result["findings"]
    skipped = result["skipped"]
    listed = sum(1 for e in entries if e)
    complete = not skipped["unreadable"]  # type: ignore[index]
    result.update({"instanceStrings": listed, "blocking": bool(findings), "complete": complete})
    if args.json:
        _print(json.dumps(result, indent=2))
    else:
        for f in findings:  # type: ignore[union-attr]
            _print("%s:%s: %s (%s)" % (f["path"], f["line"], f["kind"], f["rule"]))
        _print("%d file(s) read (%s), %d finding(s); not read: %d binary, %d unreadable; %d instance string(s) listed%s"
               % (result["files"], "what Git would commit" if result["mode"] == "git" else "every file, Git not used",
                  len(findings), skipped["binary"], skipped["unreadable"], listed,  # type: ignore[index]
                  "" if listed else " (no owner's list)"))
    if findings:
        return 1
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(run())

# #endregion source-check
