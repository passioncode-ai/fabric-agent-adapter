#!/usr/bin/env python3
"""How fabric_source_check.py reads `.fabric-source-ignore` and `--exclude` (FAA-188 part 1): a line is a path from the
tree's root, matched byte by byte as Git matches (`*`, `?` and `[...]` inside one folder, `**` as a whole segment
across folders), and a line Git would read otherwise is refused. Beside fabric_source_check.py, which imports it.
Standard library only.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import warnings
from typing import Dict, Iterable, List, Optional

IGNORE_FILE = ".fabric-source-ignore"


class CheckError(Exception):
    pass


_GLOBS: Dict[str, "re.Pattern[str]"] = {}


def _as_bytes(text: str) -> str:
    """A path or a line as Git compares it: its UTF-8 bytes, one character each. An unpaired surrogate (a Windows file
    name may hold one) is written as Git for Windows writes it (WTF-8), never a crash."""
    if os.name == "nt":  # Windows names are UTF-16: every surrogate in one is a character of the name, as WTF-8
        return text.encode("utf-8", "surrogatepass").decode("latin-1")
    try:  # POSIX names are bytes: a surrogate here is one Python escaped, and surrogateescape gives that byte back
        return text.encode("utf-8", "surrogateescape").decode("latin-1")
    except UnicodeEncodeError:
        return text.encode("utf-8", "surrogatepass").decode("latin-1")


def _name_bytes(name: str) -> str:
    """A file name as Git compares it, one byte each: on POSIX the bytes on disk, encoded back with the file system's
    own codec (os.walk and `_git_files` decoded it with that codec, so a name in any locale comes back exact); on
    Windows its UTF-8 (WTF-8) bytes, as `_as_bytes` writes them. The ignore file is read as UTF-8 and stays `_as_bytes`."""
    if os.name == "nt":
        return _as_bytes(name)
    try:
        return os.fsencode(name).decode("latin-1")
    except UnicodeEncodeError:  # not a name os.walk or Git gave (a surrogate outside the escapes): read as `_as_bytes`
        return _as_bytes(name)


def _glob(glob: str) -> "re.Pattern[str]":
    """A line of the ignore file read from the tree's root: `*`, `?` and `[...]` stay inside one folder, and `**` as a
    whole segment crosses folders (`**/` also matches none); any other run of stars is one `*`. Not a `.gitignore`
    line: a line with no `/` matches at the root only, and `\\` or `//` is refused (`_line`).
    fnmatch's `*` would cross `/`, so `vectors/*.json` would leave out `vectors/private/live.json`. Raises re.error
    for a class Python cannot read (`[9-0]`)."""
    key = glob
    if key not in _GLOBS:
        glob = _as_bytes(glob)  # Git matches bytes: `?` and a class read one byte of a UTF-8 name, never a letter
        out, i = [], 0
        while i < len(glob):
            c = glob[i]
            if c == "*":
                end = i
                while end < len(glob) and glob[end] == "*":
                    end += 1
                whole = end - i >= 2 and (i == 0 or glob[i - 1] == "/") and (end == len(glob) or glob[end] == "/")
                if whole and end < len(glob):
                    out.append("(?:.*/)?")
                    end += 1
                else:
                    out.append(".*" if whole else "[^/]*")
                i = end
                continue
            elif c == "?":
                out.append("[^/]")
            elif c == "[":
                j = i + 1 + (glob[i + 1:i + 2] in ("!", "^"))
                j += glob[j:j + 1] == "]"
                end = glob.find("]", j)
                if end < 0 or "[:" in glob[i + 1:end + 1]:
                    # Git matches nothing for an unclosed `[` and reads `[:digit:]` as a POSIX class: refused
                    raise re.error("a class Git reads otherwise")
                else:
                    inner = glob[i + 1:end].replace("\\", "\\\\")
                    negated = inner[:1] in ("!", "^")  # Git reads both as a negated class
                    body = inner[negated:]
                    if body[:1] in ("^", "["):  # a literal right after the negation
                        body = "\\" + body
                    for mark in "&~|":  # literals, never the set operations a later Python may read there
                        body = body.replace(mark, "\\" + mark)
                    out.append("(?!/)[%s%s]" % ("^" if negated else "", body))
                    i = end
            else:
                out.append(re.escape(c))
            i += 1
        with warnings.catch_warnings():  # a FutureWarning (`--` in a class) would print the script's own path
            warnings.simplefilter("error")
            try:
                _GLOBS[key] = re.compile("(?s:%s)\\Z" % "".join(out))
            except Warning:
                raise re.error("a class Python may read as a set operation")
    return _GLOBS[key]


def _readable_glob(glob: str) -> bool:
    """Whether every form `_ignored` tries can be read: a reversed range (`[9-0]`) is refused on every Python."""
    try:
        for form in (glob, glob.rstrip("/")):
            _glob(form)  # every form, whether `_ignored` tries it for this line or not
    except re.error:
        return False
    return True


def _line(glob: str, where: str) -> str:
    """An ignore line as it is matched: a leading `/` is the root (it changes nothing); a `!` exception is refused, since a
    file it would bring back is left out here (it fails open), and so is a glob that cannot be read."""
    if glob.startswith("!"):
        raise CheckError("%s is an exception (`!`), which the check does not read: name the files to leave out" % where)
    # `//` and `\` mean something else to Git (no match, an escape): refused, never read as a wider line
    if "//" in glob or "\\" in glob:
        raise CheckError("%s holds `\\` or `//`: write the path from the root with single `/`" % where)
    glob = glob[1:] if glob.startswith("/") else glob
    if not glob or not _readable_glob(glob):
        raise CheckError("%s is not a glob it can read" % where)
    return glob


def ignore_globs(root: Path, extra: Iterable[str]) -> List[str]:
    globs = [_line(g.rstrip(" "), "an --exclude glob") for g in extra]
    ignore = root / IGNORE_FILE
    try:
        present = ignore.is_file()
    except OSError:
        raise CheckError("the folder cannot be read")
    if present:
        try:
            data = ignore.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            raise CheckError("%s cannot be read as UTF-8" % IGNORE_FILE)
        # as Git splits it: at LF, a trailing CR dropped, trailing spaces trimmed; a tab or a leading space is the line's
        for number, line in enumerate(data.split("\n"), 1):
            glob = (line[:-1] if line.endswith("\r") else line).rstrip(" ")
            if glob and not glob.startswith("#"):
                globs.append(_line(glob, "line %d of %s" % (number, IGNORE_FILE)))
    return globs


def _takes_folder(glob: str) -> bool:
    """A line that names a folder takes all it holds: one ending in `/`, or a path with no wildcard (`vendor/lib`). A
    wildcard line takes only what it matches: `vectors/*` the files in `vectors`, never `vectors/live/config.json`."""
    return glob.endswith("/") or not any(c in glob for c in "*?[")


def _under(path: str, glob: str) -> bool:
    """Whether a folder above the path matches the line, read as a folder: `src/**/` takes `src/pkg/x`, never
    `src/main.py` (joining the line with `/**` would read `**/` as no folder at all)."""
    folder = _glob(glob.rstrip("/"))
    return any(folder.match(path[:i]) for i, c in enumerate(path) if c == "/")


def _ignored(path: str, globs: List[str], root: Optional[Path] = None) -> bool:
    """Whether a line leaves the path out. A folder (a nested repository, which Git lists as `vendor/sub/`, or a
    submodule, listed as `vendor/sub`) is left out only by a line that names it as a folder (`vendor/sub/`,
    `vendor/sub`, or a wildcard folder line such as `vendor/*/`, which takes every one it reaches): a wildcard line
    without the `/` takes files, so `vendor/*` reports a nested repository until it is checked in its own tree and
    named. A line ending in `/` never takes a file of that name."""
    on_disk = path.rstrip("/")
    name = _name_bytes(on_disk)  # matched as Git matches: byte by byte, the bytes on disk
    known: List[bool] = []

    def folder() -> bool:
        if not known:
            known.append(path.endswith("/") or (root is not None and os.path.isdir(str(root / on_disk))
                                                and not os.path.islink(str(root / on_disk))))
        return known[0]

    for g in globs:
        if _takes_folder(g):
            if _under(name, g):
                return True
            if _glob(g.rstrip("/")).match(name) and (not g.endswith("/") or folder()):
                return True
        elif _glob(g).match(name) and not folder():
            return True
    return False
