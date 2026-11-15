#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""The probe's lifecycle rules (check_service.py's `Probe` takes them as a mixin, split at the line ceiling): the
launchd job's plist, its supervisor marker and priority, one copy per domain, the state folder outside a checkout
and the instance lock. A remote placement reads them NOT_RUN. Standard library only, Python 3.9+."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_git  # noqa: E402 - every git call through one environment (FAA-190 (66))
import fabric_service as fs  # noqa: E402
from check_service_rules import (  # noqa: E402
    _member, in_launch_daemons, marker_problem, other_domain_copy, plist_problems, priority_problems, same_repository,
    shown_repository,
)


class LifecycleRules:
    """Mixed into check_service.Probe: reads `self.d`, `self.wk`, `self.token`, `self.remote` and adds with `self.add`."""

    def lifecycle_rules(self) -> None:
        if self.remote:
            self.add("lifecycle.platform", "NOT_RUN", "a remote placement is supervised by its platform; launchd, lock and state rules do not apply")
            return
        life = _member(self.d, "lifecycle")
        data = fs.expand(str(_member(self.d, "paths").get("data", "~/")))
        inside = fabric_git.run(data, ["rev-parse", "--show-toplevel"], capture_output=True, text=True) if data.is_dir() else None
        self.state_rule(data, inside)
        self.lock_rule(data)
        if life.get("manager") != "launchd":
            self.add("lifecycle.launchd", "NOT_RUN", "lifecycle.manager is %s" % life.get("manager"))
            return
        plist_path = fs.expand(str(life.get("plist")))
        try:
            plist = plistlib.loads(plist_path.read_bytes())
        except (OSError, ValueError) as exc:
            self.add("lifecycle.plist", "FAIL", "cannot read %s: %s" % (plist_path, exc))
            return
        problems = plist_problems(plist, life.get("label"), self.token, system=in_launch_daemons(plist_path), commands=_member(self.d, "commands"))
        self.add("lifecycle.plist", "FAIL" if problems else "PASS", "; ".join(problems) or "%s: RunAtLoad, KeepAlive, no secrets" % plist_path.name)
        marker = marker_problem(plist)
        self.add("lifecycle.supervisor-marker", "FAIL" if marker else "PASS",
                 marker or "%s: %s=launchd, so a copy that finds the lock held backs off" % (plist_path.name, fs.SUPERVISOR_ENV))
        slow = priority_problems(plist)
        self.add("lifecycle.priority", "FAIL" if slow else "PASS",
                 "; ".join(slow) + ". macOS may starve the service under load and hosts then see an outage; use ProcessType Standard"
                 if slow else "%s: scheduled as a standard process" % plist_path.name)
        if sys.platform != "darwin" or not shutil.which("launchctl"):
            self.add("lifecycle.one-copy", "NOT_RUN", "launchctl is not available")
            return
        domain = fs.launchd_domain(plist_path)  # a plist in /Library/LaunchDaemons is a LaunchDaemon (FAA-278)
        out = subprocess.run(["launchctl", "print", "%s/%s" % (domain, life.get("label"))], capture_output=True, text=True)
        match = re.search(r"^\s*pid = (\d+)", out.stdout, re.MULTILINE)
        served = ((self.wk or {}).get("process") or {}).get("pid")
        # a LaunchDaemon's leftover LaunchAgent runs in its UserName's gui/<uid> (FAA-317)
        second = other_domain_copy(life.get("label"), domain, plist.get("UserName")) if out.returncode == 0 and match else None
        if out.returncode != 0:
            self.add("lifecycle.one-copy", "FAIL", "launchd job %s is not loaded in %s" % (life.get("label"), domain))
        elif not match:
            self.add("lifecycle.one-copy", "FAIL", "launchd job loaded but not running")
        elif second:  # loaded in both domains: two copies (FAA-286 item 6)
            self.add("lifecycle.one-copy", "FAIL", "launchd job %s is loaded in %s and in %s: two copies; uninstall one"
                     % (life.get("label"), domain, second))
        else:
            same = int(match.group(1)) == served
            self.add("lifecycle.one-copy", "PASS" if same else "FAIL",
                     "launchd pid %s, answering pid %s" % (match.group(1), served))

    def state_rule(self, data: Path, inside: Optional[subprocess.CompletedProcess]) -> None:
        """State must not live in the service's CODE: its own checkout or a release.

        A repository that exists to version the data itself (a registry, a plan) is
        a store, not code; deleting the service's checkout does not touch it."""
        rule = "state.outside-code"
        if "/releases/" in data.as_posix():   # a Windows path's separators are backslashes
            self.add(rule, "FAIL", "%s is inside a release directory" % data)
            return
        if inside is None:
            self.add(rule, "NOT_RUN", "data directory %s missing or git absent" % data)
            return
        if inside.returncode != 0:
            self.add(rule, "PASS", "%s is not inside a repository" % data)
            return
        top = inside.stdout.strip()
        remote = fabric_git.run(top, ["remote", "get-url", "origin"], trees=[data, top], capture_output=True, text=True)
        own = self.d.get("source")
        source = str(own.get("repository") or "") if isinstance(own, dict) else ""
        if not source:
            self.add(rule, "NOT_RUN", "data is inside repository %s and the descriptor names no source.repository to tell code from data" % top)
        elif remote is not None and remote.returncode == 0 and same_repository(remote.stdout.strip(), source):
            self.add(rule, "FAIL", "data lives in the service's own code checkout %s (%s)" % (top, shown_repository(source)))
        else:
            self.add(rule, "PASS", "data is in repository %s, which is not the service's code (%s)" % (top, shown_repository(remote.stdout.strip()) or "no remote"))

    def lock_rule(self, data: Path) -> None:
        lock = data / "service.lock"
        if not lock.exists():
            self.add("lifecycle.instance-lock", "FAIL", "%s does not exist" % lock)
            return
        if fs.WINDOWS:
            import msvcrt

            # The kit locks one byte at InstanceLock.WINDOWS_LOCK_OFFSET; try the same byte.
            fd = os.open(str(lock), os.O_RDWR | getattr(os, "O_BINARY", 0))
            try:
                os.lseek(fd, fs.InstanceLock.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    self.add("lifecycle.instance-lock", "PASS", "held by the running service")
                else:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    self.lock_free(lock)
            finally:
                os.close(fd)
            return
        try:
            import fcntl
        except ImportError:
            self.add("lifecycle.instance-lock", "NOT_RUN", "fcntl unavailable")
            return
        fd = os.open(str(lock), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            held = exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)
            self.add("lifecycle.instance-lock", "PASS" if held else "FAIL", "held by the running service" if held else str(exc))
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            self.lock_free(lock)
        finally:
            os.close(fd)

    def lock_free(self, lock: Path) -> None:
        """The file lock is free; a Node kit service holds the lock's name instead (fs.lock_name)."""
        if fs.lock_name_held(lock):
            self.add("lifecycle.instance-lock", "PASS", "held by the running service (the lock's name, %s)" % ("a named pipe" if fs.WINDOWS else "an abstract socket"))
        else:
            self.add("lifecycle.instance-lock", "FAIL", "%s exists but nobody holds it" % lock)
