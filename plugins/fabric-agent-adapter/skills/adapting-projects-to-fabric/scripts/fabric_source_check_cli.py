"""The command line of fabric_source_check.py (FAA-190 (104)): where the owner's list is found, the arguments, and the
printed report. It sits beside fabric_source_check.py, which imports it inside its import guard and keeps the entry
point (`fabric_source_check.py check ...`, `fabric_source_check.run`); run the check by path, never this file.
Standard library only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable, Dict, List, NoReturn, Optional, Tuple

from fabric_source_ignore import CheckError

LIST_NAME = "instance-strings.txt"


def _absolute(path: str, platform: str) -> bool:
    return bool(re.match(r"[A-Za-z]:[\\/]|[\\/]{2}", path)) if platform == "win32" else path.startswith("/")


def default_list(platform: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Path:
    """Where the owner's list is kept when none is named: the user's configuration folder, never a project's."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    # a relative value is ignored, as the XDG spec says (a quoted `~/.config` is relative too): never "no list"
    if platform == "win32":
        appdata = env.get("APPDATA", "")
        base = Path(appdata) if appdata and _absolute(appdata, platform) else Path.home() / "AppData" / "Roaming"
    else:
        xdg = env.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg.startswith("/") else Path.home() / ".config"
    return base / "passioncode-fabric" / LIST_NAME


def _list_path(given: Optional[str]) -> Tuple[Optional[Path], bool]:
    """The owner's list and whether it must be read (a named or an existing default list; else no list)."""
    named = given or os.environ.get("FABRIC_INSTANCE_STRINGS")
    if named:
        try:
            return Path(named).expanduser(), True
        except (RuntimeError, KeyError):  # `~user` with no such user (KeyError on 3.9): never "no finding"
            raise CheckError("the owner's list cannot be read")
    try:
        default = default_list()
    except (RuntimeError, KeyError):  # no HOME and no account entry (a container's arbitrary user)
        raise CheckError("there is no home folder to find the owner's list in: set an absolute XDG_CONFIG_HOME (APPDATA on "
                         "Windows) or name the list with --instance-strings")
    try:
        os.stat(str(default))
    except (FileNotFoundError, NotADirectoryError):
        # a link to a list, its folder or the configuration folder on a volume not mounted: there, but not reachable
        if any(os.path.lexists(str(p)) and not os.path.exists(str(p)) for p in (default, *default.parents)):
            raise CheckError("the owner's list in your configuration folder cannot be read")
        return None, False
    except OSError:  # a list that is there but cannot be reached is not "no list": that would fail open
        raise CheckError("the owner's list cannot be read")
    return default, True


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # argparse would repeat the arguments it could not read
        self.print_usage(sys.stderr)
        self.exit(2, "fabric_source_check.py: the arguments cannot be read; see the usage above\n")


def _print(text: str) -> None:
    """Print a line the console may not encode (a name in another script, a byte Git kept as a surrogate)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding, "replace"))


def run_check(argv: Optional[List[str]], check: Callable[..., Dict[str, object]], read_list: Callable[[Path], List[str]],
              ignore_globs: Callable[[Path, List[str]], List[str]], home_entry: str) -> int:
    """The command line, run with the check's own functions (fabric_source_check.run passes them)."""
    parser = _Parser(prog="fabric_source_check.py", description="Find instance data in an agent's source.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("check", help="read the source tree and report instance data without repeating it")
    cmd.add_argument("root", nargs="?", default=".", help="the folder to check (default: the current folder)")
    cmd.add_argument("--instance-strings", metavar="FILE", help="the owner's list (default: FABRIC_INSTANCE_STRINGS, else "
                     "passioncode-fabric/%s in the user's configuration folder)" % LIST_NAME)
    cmd.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                     help="leave matching paths out, as a .fabric-source-ignore line does (repeatable)")
    cmd.add_argument("--json", action="store_true", help="one JSON object: mode, files, findings, notRead, skipped, "
                     "dependencies, instanceStrings, ownerHomes, instanceList, blocking, complete; exit 0 clean and "
                     "complete, 1 a finding, 2 a file not read or no run")
    cmd.add_argument("--every-file", action="store_true", help="read every file, not only what Git would commit")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, or arguments argparse refused: the exit code, as the command line gives it
        return exc.code if isinstance(exc.code, int) else 2
    try:
        try:
            root = Path(args.root).expanduser().resolve()
            is_folder = root.is_dir()
        except (OSError, RuntimeError, KeyError):  # a parent it cannot search, a symlink loop, `~` with no home
            raise CheckError("the folder cannot be read")
        if not is_folder:
            raise CheckError("ROOT is not a folder")
        list_path, _ = _list_path(args.instance_strings)  # may raise CheckError
        entries: List[str] = []
        if list_path is not None:
            try:
                resolved = list_path.resolve()
            except (OSError, RuntimeError):  # RuntimeError: Python 3.9's symlink loop
                raise CheckError("the owner's list cannot be read")
            if resolved == root or root in resolved.parents:
                raise CheckError("the owner's list is inside the tree it checks, where it would travel with the source; "
                                 "keep it in your configuration folder (passioncode-fabric/%s)" % LIST_NAME)
            try:
                present = resolved.is_file()
            except OSError:
                raise CheckError("the owner's list cannot be read")
            if not present:
                raise CheckError("the owner's list named by --instance-strings or FABRIC_INSTANCE_STRINGS does not exist or is "
                                 "not a regular file"
                                 if args.instance_strings or os.environ.get("FABRIC_INSTANCE_STRINGS")
                                 else "the owner's list in your configuration folder is not a file")
            try:
                entries = read_list(resolved)
            except UnicodeDecodeError:
                raise CheckError("the owner's list is not UTF-8")
            except OSError:
                raise CheckError("the owner's list cannot be read")
        result = check(root, entries, ignore_globs(root, args.exclude), args.every_file)
    except CheckError as exc:
        print("fabric_source_check.py: %s" % exc, file=sys.stderr)
        return 2
    if result.get("manifest"):  # under fabric.source.json: its own report (fabric_source_tree.print_run)
        return sys.modules["fabric_source_tree"].print_run(result, entries, list_path is not None, args.json, _print)
    findings = result["findings"]
    skipped = result["skipped"]
    listed = sum(1 for e in entries if e and not e.startswith(home_entry))
    homes = sum(1 for e in entries if e.startswith(home_entry))
    # a binary file is not read either: it is complete only when every one is named as source in the ignore file
    complete = not (skipped["unreadable"] or skipped["binary"] or skipped["nested"])  # type: ignore[index]
    result.update({"instanceStrings": listed, "ownerHomes": homes, "instanceList": list_path is not None, "blocking": bool(findings),
                   "complete": complete})
    if args.json:
        _print(json.dumps(result, indent=2))
    else:
        for f in findings:  # type: ignore[union-attr]
            _print("%s:%s: %s (%s)" % (f["path"], f["line"], f["kind"], f["rule"]))
        for n in result["notRead"]:  # type: ignore[union-attr]
            _print("%s: not read (%s)" % (n["path"], n["why"]))
        for folder in result["dependencies"]:  # type: ignore[union-attr]
            _print("%s: not read (a dependency folder; --every-file reads it)" % folder)
        if skipped["dependencies"]:  # type: ignore[index]
            _print("%d dependency folder(s) not read (node_modules, virtual environments, caches); --every-file reads "
                   "them" % skipped["dependencies"])  # type: ignore[index]
        _print("%d file(s) read (%s), %d finding(s); not read: %d binary, %d unreadable, %d nested repository; "
               "%d left out by name; %d instance string(s) listed%s%s"
               % (result["files"], "what Git would commit" if result["mode"] == "git" else
                  "every file, as pack reads them" if args.every_file else "every file but dependency folders, Git not used",
                  len(findings), skipped["binary"], skipped["unreadable"], skipped["nested"],  # type: ignore[index]
                  skipped["excluded"], listed,  # type: ignore[index]
                  "" if listed or homes else (" (the owner's list holds no string of three or more characters)"
                                              if list_path else " (no owner's list)"),
                  "; %d home name(s) declared" % homes if homes else ""))
    if findings:
        return 1
    return 0 if complete else 2
