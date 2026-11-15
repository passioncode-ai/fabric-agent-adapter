#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""Git run on a folder the way every reader in the adapter runs it (FAA-190 items 66, 67, 100, 103, 44).

A reader runs Git on a folder it does not trust: a project it adapts or checks, a session's working folder, a service's
checkout. Each call goes through this module, so Git:

- comes from PATH's absolute folders only (on Windows CreateProcess and shutil.which look in the current folder
  first, and on POSIX an empty or relative PATH element is the current folder), never from a folder inside the tree it
  reads (`npm run` puts `<root>/node_modules/.bin` on PATH as an absolute folder), and on Windows only as `git.exe`
  (cmd.exe would read the arguments of a `.cmd`); with PATH unset POSIX's default folders, on Windows none;
- runs no command the folder's own configuration names: `core.fsmonitor` is empty (Git before 2.36 reads `false` as
  a hook named `false`; from 2.36 an empty value is boolean false, so the builtin daemon is not started either) and Git
  for Windows' `core.useBuiltinFSMonitor` is false;
- finds the repository from the folder: a Git location the caller exports (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`
  and the rest; a hook in a linked worktree has two) is not passed, so another repository's index is never read;
- writes nothing: `GIT_TRACE*` is not passed and the trace2 targets are off (`GIT_TRACE2*=0` wins over a
  `trace2.*Target` in the caller's own configuration), and `GIT_OPTIONAL_LOCKS=0` keeps `status` from refreshing the
  index.

The caller's own Git configuration (its global excludes file included) still applies: it is the caller's view of what
it would commit. Standard library only; Python 3.9 floor. A copy of this file stands in adapting-projects-to-fabric,
creating-fabric-agents and working-with-fabric, byte for byte (test/test_fabric_git.py).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

PathLike = Union[str, "os.PathLike[str]"]

#: Where a caller's Git looks for a repository: never passed, the repository is found from the folder.
LOCATION = frozenset(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX"))
#: Settings that keep Git from running or starting a command the folder's configuration names (`-c` wins over the
#: repository's configuration, and over GIT_CONFIG_PARAMETERS a caller exports).
NO_COMMANDS = ("-c", "core.fsmonitor=", "-c", "core.useBuiltinFSMonitor=false")
#: Trace targets off: a non-empty variable wins over the configuration's trace2.*Target, and `0` turns a target off.
TRACE_OFF = {"GIT_TRACE2": "0", "GIT_TRACE2_EVENT": "0", "GIT_TRACE2_PERF": "0"}


def _real(path: PathLike) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _within(folder: str, trees: Sequence[str]) -> bool:
    here = _real(folder)
    for tree in trees:
        try:
            if os.path.commonpath([here, tree]) == tree:
                return True
        except ValueError:  # two drives on Windows: not inside
            continue
    return False


def executable(trees: Iterable[PathLike] = ()) -> Optional[str]:
    """`git` from PATH's absolute folders, skipping any folder inside one of `trees` (the folders it will read)."""
    name = "git.exe" if os.name == "nt" else "git"  # never a .cmd or .bat: cmd.exe would read the arguments
    # with PATH unset, POSIX's default folders (`/bin`, `/usr/bin`); Windows' default (`.;C:\\bin`) is a folder any
    # user may create, so there no PATH means no git
    folders = os.get_exec_path() if os.name != "nt" else os.environ.get("PATH", "").split(os.pathsep)
    real_trees: Optional[List[str]] = None
    for folder in folders:
        if folder and os.path.isabs(folder):
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                if real_trees is None:
                    real_trees = [_real(t) for t in trees]
                if real_trees and _within(folder, real_trees):
                    continue  # the tree's own git (`node_modules/.bin/git`): never run
                return candidate
    return None


def _dropped(name: str) -> bool:
    upper = name.upper()  # Windows' environment is case-insensitive
    return upper in LOCATION or upper.startswith("GIT_TRACE") or upper == "GIT_TEST_FSMONITOR"


def environment(environ: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The environment a Git call runs with: the caller's, without its Git location and traces."""
    source = os.environ if environ is None else environ
    env = {k: v for k, v in source.items() if not _dropped(k)}
    env.update(TRACE_OFF)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def command(folder: PathLike, args: Sequence[str], trees: Optional[Iterable[PathLike]] = None) -> Optional[List[str]]:
    """The argument list that runs Git in `folder` (None: no git), its own folder skipped as a source of git."""
    git = executable([folder] if trees is None else trees)
    if git is None:
        return None
    return [git, *NO_COMMANDS, "-C", os.fspath(folder), *args]


def run(folder: PathLike, args: Sequence[str], timeout: Optional[float] = None,
        trees: Optional[Iterable[PathLike]] = None, **kwargs: Any) -> Optional["subprocess.CompletedProcess[Any]"]:
    """subprocess.run of Git in `folder` with this module's environment; None when no git is found. OSError and
    subprocess's own exceptions (TimeoutExpired) reach the caller, which knows what each means to it."""
    argv = command(folder, args, trees)
    if argv is None:
        return None
    kwargs.setdefault("env", environment())
    return subprocess.run(argv, timeout=timeout, **kwargs)
