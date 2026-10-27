"""working-with-fabric, part of fabric_session.py (FAA-65): reading the folders a Bash command names, for the Stop
hook's repositories (FAA-140, FAA-166, FAA-175). Standard library only."""
from __future__ import annotations

import re
import sys
from pathlib import Path, PurePath
from typing import Any
from typing import List
from typing import Optional


_DRIVE_MOUNT = re.compile(r"/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def _windows_path(token: str) -> Optional[str]:
    """A Git Bash path as this Windows host's (FAA-175): `/c/...` and `/cygdrive/c/...` are drive C, `C:/...` and
    `C:\\...` stay a drive path, `\\\\host\\share` a share. None for another `/...` (Git's own root, which only
    `cygpath` knows) and for a relative path."""
    import ntpath
    mount = _DRIVE_MOUNT.match(token)
    if mount:
        token = mount.group(1).upper() + ":\\" + token[mount.end():].lstrip("/")
    elif token.startswith("/"):
        return None
    if not ntpath.isabs(token) or not (ntpath.splitdrive(token)[0]):
        return None
    return ntpath.normpath(token)


def bash_paths(command: str, cwd: Path, windows: Optional[bool] = None) -> List[str]:
    """The folders a Bash command names as `cd <absolute path>` or `git -C <path>`, in order. A relative `-C` is read
    against the folder the command last changed into with an absolute `cd`, else `cwd`; after a `cd` to a relative or
    unknown folder it is dropped (FAA-166). A `cd` inside `( )`, a pipeline's stage or a list sent to the background
    with `&` moves only a subshell, so the folder after it is the one before; a newline ends a command. Nothing
    else of the command is kept; a command that does not split is [] (FAA-140). On Windows (`windows`, default
    `sys.platform == "win32"`) paths are read as Git Bash writes them, with its quoting: an unquoted `C:\\work` is
    `C:work` there too, so a native path counts when it is quoted (FAA-175); Cygwin and MSYS2 Pythons read their own
    POSIX paths (FAA-177)."""
    import shlex  # only a Stop hook with a transcript needs it
    windows = sys.platform == "win32" if windows is None else windows
    if windows:
        import ntpath as paths
    else:
        import posixpath as paths
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"  # a newline ends a command, as `;` does
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []

    def absolute(token: str) -> Optional[str]:
        if windows:
            return _windows_path(token)
        return paths.normpath(token) if paths.isabs(token) else None

    found: List[str] = []
    separators = set("();&|<>\n")
    # Where a relative -C points: None once a cd went somewhere unknown. POSIX rules read the folder with `/`, whatever
    # the host writes (a test on Windows reads POSIX commands too).
    base: Optional[str] = str(cwd) if windows else PurePath(cwd).as_posix()
    # A cd in a pipeline's stage, in `( )` or in a backgrounded list moves only a subshell: the folder goes back to
    # where that pipeline, subshell or list began.
    pipe_start = list_start = base
    in_pipeline = False
    stack: List[Any] = []

    def end_pipeline() -> None:
        nonlocal base, pipe_start, in_pipeline
        if in_pipeline:
            base = pipe_start
        pipe_start, in_pipeline = base, False

    start = True  # a command word may stand here
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token and set(token) <= separators:
            at = 0
            while at < len(token):
                pair, char = token[at:at + 2], token[at]
                if pair in ("&&", "||"):
                    end_pipeline()
                    at += 2
                    continue
                if char in "<>":  # a redirection: `2>&1` backgrounds nothing
                    at += 2 if token[at + 1:at + 2] == "&" else 1
                    continue
                if pair == "|&" or char == "|":
                    base, in_pipeline = pipe_start, True
                    at += 2 if pair == "|&" else 1
                    continue
                if char in ";\n":
                    end_pipeline()
                    list_start = base
                elif char == "&":
                    end_pipeline()
                    base = pipe_start = list_start
                elif char == "(":
                    stack.append((base, pipe_start, list_start, in_pipeline))
                    pipe_start = list_start = base
                    in_pipeline = False
                elif char == ")":
                    end_pipeline()
                    if stack:
                        base, pipe_start, list_start, in_pipeline = stack.pop()
                at += 1
            start, index = True, index + 1
            continue
        if start and token == "cd":
            target = tokens[index + 1] if index + 1 < len(tokens) and not set(tokens[index + 1]) <= separators else None
            folder = absolute(target) if target else None
            if folder:
                found.append(folder)
            base = folder
        elif start and (paths.basename(token).lower() if windows else paths.basename(token)) in ("git", "git.exe"):
            look = index + 1
            while look < len(tokens) and tokens[look].startswith("-") and not set(tokens[look]) <= separators:
                if tokens[look] == "-C" and look + 1 < len(tokens) and not set(tokens[look + 1]) <= separators:
                    folder = absolute(tokens[look + 1])
                    if folder is None and base is not None and not tokens[look + 1].startswith("/"):
                        folder = paths.normpath(paths.join(base, tokens[look + 1]))
                    if folder:
                        found.append(folder)
                    look += 1
                elif tokens[look] == "-c":
                    look += 1
                look += 1
        start = False
        index += 1
    return found
