"""working-with-fabric, part of fabric_session.py (FAA-65): reading the folders a Bash command names, for the Stop
hook's repositories (FAA-140, FAA-166, FAA-175). Standard library only."""
from __future__ import annotations

import re
import sys
from pathlib import Path, PurePath
from typing import Any
from typing import List
from typing import Optional
from typing import Tuple


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


_OPERATORS = frozenset("();&|<>")


def _heredoc_word(command: str, at: int) -> Tuple[str, int]:
    """A here-document's delimiter word from `at` (blanks first), its quotes taken off as bash does, and where it ends."""
    while at < len(command) and command[at] in " \t":
        at += 1
    word, quote = [], None
    while at < len(command):
        char = command[at]
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
        elif char in "'\"":
            quote = char
        elif char == "\\" and at + 1 < len(command):
            at += 1
            word.append(command[at])
        elif char in " \t\n" or char in _OPERATORS:
            break
        else:
            word.append(char)
        at += 1
    return "".join(word), at


def prepare(command: str) -> str:
    """The command as bash reads its words, before the lexer (FAA-187): a `\\` and newline outside single quotes and
    outside a comment joins the lines (an escaped backslash before a newline joins nothing, (7)); a comment, a `#` that
    starts a word, is cut to its line's end (a `#` inside a word is the word's, (2)); a here-document's body and its
    terminator line are cut out and the redirection left as a here-string, so a quote in a body never breaks the lexer
    (5), with bash's own terminator rules: the delimiter word as written, its quotes taken off, `<<-` stripping leading
    tabs, a plain `<<` matching only the bare line, and `<<` inside `((` `))` a shift (9); and a quoted word made only of
    operator characters (`'&'`, `")"`) becomes a plain word, so the lexer never reads it as an operator (1)."""
    out: List[str] = []
    at, size, quote, word_start, arithmetic = 0, len(command), None, True, 0
    pending: List[Tuple[str, bool]] = []
    while at < size:
        char = command[at]
        if quote == "'":
            out.append(char)
            quote = None if char == "'" else quote
            at += 1
            continue
        if char == "\\":
            if command[at + 1:at + 2] == "\n":
                at += 2  # a line continuation (outside single quotes)
                continue
            out.append(command[at:at + 2])
            at, word_start = at + 2, False
            continue
        if quote == '"':
            out.append(char)
            quote = None if char == '"' else quote
            at += 1
            continue
        if char in "'\"":
            end = command.find(char, at + 1) if char == "'" else -1
            if char == '"':
                look = at + 1
                while look < size and command[look] != '"':
                    look += 2 if command[look] == "\\" else 1
                end = look if look < size else -1
            inner = command[at + 1:end] if end > at else ""
            after = command[end + 1:end + 2] if end > at else ""
            if word_start and inner and set(inner) <= _OPERATORS and (after == "" or after in " \t\n" or after in _OPERATORS):
                out.append("_")  # a quoted operator is a word, never an operator (1)
                at, word_start = end + 1, False
                continue
            quote, word_start = char, False
            out.append(char)
            at += 1
            continue
        if char == "#" and word_start:
            while at < size and command[at] != "\n":
                at += 1  # a comment, to its line's end; the newline stays
            continue
        if command.startswith("((", at):
            arithmetic += 1
        elif command.startswith("))", at) and arithmetic:
            arithmetic -= 1
        if command.startswith("<<<", at):  # a here-string: its word is text, no body follows
            out.append("<<<")
            at, word_start = at + 3, True
            continue
        if command.startswith("<<", at) and not arithmetic:
            strip = command[at + 2:at + 3] == "-"
            word, end = _heredoc_word(command, at + 3 if strip else at + 2)
            if word:
                pending.append((word, strip))
                out.append("<<< _ ")  # the body is text for the command: a here-string stands in for it
                at, word_start = end, True
                continue
        if char == "\n" and pending:
            out.append("\n")
            line_start = at + 1
            for delimiter, strip in pending:
                while line_start <= size:
                    line_end = command.find("\n", line_start)
                    line_end = size if line_end < 0 else line_end
                    line = command[line_start:line_end]
                    line_start = line_end + 1
                    if (line.lstrip("\t") if strip else line) == delimiter:
                        break
            pending = []
            at, word_start = line_start - 1, True  # at the terminator line's newline: it ends the command
            if at >= size:
                break
            continue
        out.append(char)
        word_start = char in " \t\n" or char in _OPERATORS
        at += 1
    return "".join(out)


#: Words after which a command word may still stand (reserved words and the prefixes that run their command here).
KEYWORDS = frozenset(("{", "!", "then", "do", "else", "elif", "if", "while", "until", "time", "command", "builtin"))
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def bash_paths(command: str, cwd: Path, windows: Optional[bool] = None,
               ends: Optional[List[Optional[str]]] = None, fold_case: Optional[bool] = None) -> List[str]:
    """The folders a Bash command names as `cd <absolute path>` or `git -C <path>`, in order. A relative `-C` is read
    against the folder the command last changed into with an absolute `cd`, else `cwd`; after a `cd` to a relative or
    unknown folder it is dropped (FAA-166). A `cd` inside `( )`, a pipeline's stage or a list sent to the background
    with `&` moves only a subshell, so the folder after it is the one before; a newline ends a command, a here-document's
    body is text, `{`, `then`, `x=1` and the like still leave a command word to come, and `pushd` moves like `cd`. Nothing
    else of the command is kept; a command that does not split is [] (FAA-140). On Windows (`windows`, default
    `sys.platform == "win32"`) paths are read as Git Bash writes them, with its quoting: an unquoted `C:\\work` is
    `C:work` there too, so a native path counts when it is quoted (FAA-175); Cygwin and MSYS2 Pythons read their own
    POSIX paths (FAA-177). With `ends`, the folder the command leaves the shell in is appended to it: an absolute path,
    or None when it is not known (a relative cd, popd, an unclosed subshell, a command that does not split; FAA-184).
    `prepare` reads comments, line continuations, here-documents and quoted operators first (FAA-187); a line ending
    in `|`, `|&`, `&&` or `||` goes on on the next, as in bash (6); a `-C` word bash would expand (`$`, a backtick, a
    leading `~`) is a folder not known here (8), and `-C ""` runs where the shell is; `git` is matched without case on
    Windows and, with `fold_case` (default: on macOS), where the file system finds `GIT` as git (11). A `case`
    pattern's `)` inside a subshell is still read as closing it."""
    import shlex  # only a Stop hook with a transcript needs it
    windows = sys.platform == "win32" if windows is None else windows
    fold_case = windows or (sys.platform == "darwin" if fold_case is None else fold_case)
    if windows:
        import ntpath as paths
    else:
        import posixpath as paths
    try:
        lexer = shlex.shlex(prepare(command), posix=True, punctuation_chars="();<>|&\n")
        lexer.commenters = ""  # prepare cut the comments, where bash reads them (a `#` inside a word is the word's)
        lexer.whitespace = " \t\r"  # a newline ends a command, as `;` does
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        if ends is not None:
            ends.append(None)
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
    continued = False  # the last operator was `|`, `|&`, `&&` or `||`: a newline after it goes on (FAA-187 (6))
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token and set(token) <= separators:
            at, ends_command = 0, False
            while at < len(token):
                pair, char = token[at:at + 2], token[at]
                if char == "\n" and continued:
                    at += 1  # the line ended in a pipe or a list operator: the command goes on
                    continue
                if pair in ("&&", "||"):
                    end_pipeline()
                    at, ends_command, continued = at + 2, True, True
                    continue
                if token.startswith("<<<", at):  # a here-string (prepare leaves one for a here-document): its word is text
                    at += 3
                    continue
                if pair == "&>":  # `&>` and `&>>` redirect, they background nothing
                    at += 3 if token[at + 2:at + 3] == ">" else 2
                    continue
                if char in "<>":  # a redirection: `2>&1` backgrounds nothing, `>|` pipes nothing
                    at += 2 if token[at + 1:at + 2] in ("&", "|") else 1
                    continue
                ends_command, continued = True, False
                if pair == "|&" or char == "|":
                    base, in_pipeline, continued = pipe_start, True, True
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
            start = start or ends_command  # a redirection alone starts no command
            index += 1
            continue
        continued = False
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
        elif start and (paths.basename(token).lower() if fold_case else paths.basename(token)) in ("git", "git.exe"):
            look, at, moved = index + 1, base, False
            while look < len(tokens) and tokens[look].startswith("-") and not set(tokens[look]) <= separators:
                if tokens[look] == "-C" and look + 1 < len(tokens) and (tokens[look + 1] == "" or not set(tokens[look + 1]) <= separators):
                    # git reads each relative -C against the one before it and runs in the last; `-C ""` where it is
                    word = tokens[look + 1]
                    expands = "$" in word or "`" in word or word.startswith("~")  # a folder not known here (FAA-187 (8))
                    folder = None if expands else absolute(word)
                    if folder is None and not expands and at is not None and not word.startswith("/"):
                        folder = paths.normpath(paths.join(at, word))
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
    if ends is not None:
        end_pipeline()
        ends.append(None if stack else base)
    return found
