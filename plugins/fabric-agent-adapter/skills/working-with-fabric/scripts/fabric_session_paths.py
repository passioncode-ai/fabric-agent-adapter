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


#: Words after which a command word may still stand (reserved words and the prefixes that run their command here).
KEYWORDS = frozenset(("{", "!", "then", "do", "else", "elif", "if", "while", "until", "time", "command", "builtin"))
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def bash_paths(command: str, cwd: Path, windows: Optional[bool] = None) -> List[str]:
    """The folders a Bash command names as `cd <absolute path>` or `git -C <path>`, in order. A relative `-C` is read
    against the folder the command last changed into with an absolute `cd`, else `cwd`; after a `cd` to a relative or
    unknown folder it is dropped (FAA-166). A `cd` inside `( )`, a pipeline's stage or a list sent to the background
    with `&` moves only a subshell, so the folder after it is the one before; a newline ends a command, a here-document's
    body is text, `{`, `then`, `x=1` and the like still leave a command word to come, and `pushd` moves like `cd`. Nothing
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
        # A `\` before a newline joins the lines, as in bash; a `;` and a second newline after each newline keep a `#`
        # comment, which the lexer reads to the end of its line, newline included, from swallowing the next command or
        # the line end a here-document counts.
        command = command.replace("\\\n", "").replace("\n", "\n;\n")
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

    heredocs: List[str] = []  # the delimiters of here-documents whose bodies start at the next newline

    def past_heredocs(at: int) -> int:
        """The index of the newline ending the last pending here-document's delimiter line (or the end): the body is
        text for a command, never commands of its own."""
        while heredocs and at < len(tokens):
            line_end = at
            while line_end < len(tokens) and "\n" not in tokens[line_end]:
                line_end += 1
            if tokens[at:line_end] == [heredocs[0]]:
                heredocs.pop(0)
                if not heredocs:
                    return line_end
            at = line_end + 1
        heredocs.clear()
        return len(tokens)

    start = True  # a command word may stand here
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token and set(token) <= separators:
            at, ends_command, newline = 0, False, False
            while at < len(token):
                pair, char = token[at:at + 2], token[at]
                if pair in ("&&", "||"):
                    end_pipeline()
                    at, ends_command = at + 2, True
                    continue
                if token.startswith("<<<", at):  # a here-string: its word is text, no body follows
                    at += 3
                    continue
                if pair == "<<" and index + 1 < len(tokens):
                    delimiter = tokens[index + 1]  # <<EOF, <<'EOF', <<-EOF: shlex has taken the quotes off
                    if delimiter == "-" and index + 2 < len(tokens):
                        index, delimiter = index + 1, tokens[index + 2]
                    heredocs.append(delimiter[1:] if delimiter.startswith("-") and len(delimiter) > 1 else delimiter)
                    index += 1  # the delimiter is no command word
                    at += 2
                    continue
                if pair == "&>":  # `&>` and `&>>` redirect, they background nothing
                    at += 3 if token[at + 2:at + 3] == ">" else 2
                    continue
                if char in "<>":  # a redirection: `2>&1` backgrounds nothing, `>|` pipes nothing
                    at += 2 if token[at + 1:at + 2] in ("&", "|") else 1
                    continue
                ends_command = True
                if pair == "|&" or char == "|":
                    base, in_pipeline = pipe_start, True
                    at += 2 if pair == "|&" else 1
                    continue
                if char in ";\n":
                    end_pipeline()
                    list_start = base
                    newline = newline or char == "\n"
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
            start = start or ends_command  # a redirection alone starts no command
            index = past_heredocs(index + 1) if newline and heredocs else index + 1
            continue
        if start and (token in KEYWORDS or ASSIGNMENT.match(token)):
            index += 1  # `{ cd /a; }`, `then cd`, `x=1 cd`, `command cd`: a command word may still follow
            continue
        if start and token in ("pushd", "popd"):
            target = tokens[index + 1] if token == "pushd" and index + 1 < len(tokens) else None
            folder = absolute(target) if target and not set(target) <= separators else None
            if folder:
                found.append(folder)
            base = folder  # popd, or pushd somewhere not known here: the folder is not known
        elif start and token == "cd":
            target = tokens[index + 1] if index + 1 < len(tokens) and not set(tokens[index + 1]) <= separators else None
            folder = absolute(target) if target else None
            if folder:
                found.append(folder)
            base = folder
        elif start and (paths.basename(token).lower() if windows else paths.basename(token)) in ("git", "git.exe"):
            look, at, moved = index + 1, base, False
            while look < len(tokens) and tokens[look].startswith("-") and not set(tokens[look]) <= separators:
                if tokens[look] == "-C" and look + 1 < len(tokens) and not set(tokens[look + 1]) <= separators:
                    # git reads each relative -C against the one before it and runs in the last
                    folder = absolute(tokens[look + 1])
                    if folder is None and at is not None and not tokens[look + 1].startswith("/"):
                        folder = paths.normpath(paths.join(at, tokens[look + 1]))
                        if windows and not (paths.isabs(folder) and paths.splitdrive(folder)[0]):
                            folder = None  # `C:work`, a drive-relative path: not known here
                    at, moved = folder, True
                    look += 1
                elif tokens[look] == "-c":
                    look += 1
                look += 1
            if moved and at:
                found.append(at)
        start = False
        index += 1
    return found
