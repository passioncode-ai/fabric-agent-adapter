"""Logs and stopping (LC-01, LC-12): a rotating log, a capped stdout log, the stop signal and the drain.
Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from fabric_base import (
    DRAIN_SECONDS,
    ServiceError,
    _O_BINARY,
    now_iso,
)
from fabric_paths import (
    ensure_private_dir,
)


DRAIN_GRACE_SECONDS = 2.0


EXIT_HARD_STOP = 70


# LC-12: logs rotate by size, 5 x 5 MB by default.
LOG_MAX_BYTES = 5 * 1024 * 1024


LOG_BACKUPS = 5


class RotatingLog:
    """One structured log: JSON lines rotated by size (5 x 5 MB by default), files 0600 in a
    0700 directory. ``service.jsonl`` -> ``.1`` ... ``.<backups>``; the oldest falls off.

    Never pass a token, a cookie, a login code or a request body that may carry one."""

    def __init__(self, path: Path, max_bytes: int = LOG_MAX_BYTES, backups: int = LOG_BACKUPS):
        if max_bytes < 256 or backups < 1:
            raise ServiceError("A rotating log needs max_bytes >= 256 and at least one backup.")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()

    def _line(self, record: Dict[str, Any]) -> bytes:
        data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
        if len(data) <= self.max_bytes:
            return data
        record = dict(record, truncated=True)
        message = str(record.get("message", ""))
        while message:
            message = message[: len(message) // 2]
            record["message"] = message
            data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            if len(data) <= self.max_bytes:
                return data
        return (json.dumps({"at": record.get("at"), "level": record.get("level"), "message": "",
                            "truncated": True}) + "\n").encode()

    def write(self, level: str, message: str, **fields: Any) -> None:
        record: Dict[str, Any] = {"at": now_iso(), "level": str(level), "message": str(message)}
        record.update(fields)
        data = self._line(record)
        with self._lock:
            ensure_private_dir(self.path.parent)
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size and size + len(data) > self.max_bytes:
                self._rotate()
            fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)

    def _rotate(self) -> None:
        for index in range(self.backups - 1, 0, -1):
            older = Path("%s.%d" % (self.path, index))
            if older.exists():
                os.replace(older, "%s.%d" % (self.path, index + 1))
        os.replace(self.path, "%s.1" % self.path)


def cap_stdout_log(path: Path, max_bytes: int = LOG_MAX_BYTES) -> bool:
    """Call once at start: a launchd stdout file over ``max_bytes`` is copied to ``<path>.1`` and
    truncated in place. launchd holds the file open for append, so a rename would leave it
    writing to the old name; truncation keeps its descriptor valid. Returns True when capped."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size <= max_bytes:
        return False
    backup = Path("%s.1" % path)
    shutil.copyfile(path, backup)
    os.chmod(backup, 0o600)
    with open(path, "r+b") as handle:
        handle.truncate(0)
    return True


class Stopping(ServiceError):
    """The service is stopping and takes no new work."""


class Drain:
    """SIGTERM/SIGINT: stop taking new work, drain in-flight work until ``deadline``, then hand
    over with ``on_stop(drained)``. A hand-over that hangs is cut by a hard exit
    (``EXIT_HARD_STOP``) ``grace`` seconds later, so quit reaches exit inside the lifecycle bound.

        drain = fs.Drain()
        drain.install(lambda drained: server.shutdown(),
                      on_stopping=lambda: log.append("service.stopping", "info", "Stopping."))
        with drain.work():          # raises fs.Stopping once a stop has begun
            ...
    """

    def __init__(self, deadline: float = DRAIN_SECONDS, grace: float = DRAIN_GRACE_SECONDS):
        self.deadline = deadline
        self.grace = grace
        self._cond = threading.Condition()
        self._inflight = 0
        self._stopping = False

    @property
    def stopping(self) -> bool:
        return self._stopping

    @property
    def inflight(self) -> int:
        return self._inflight

    @contextlib.contextmanager
    def work(self):
        with self._cond:
            if self._stopping:
                raise Stopping("The service is stopping and takes no new work.")
            self._inflight += 1
        try:
            yield
        finally:
            with self._cond:
                self._inflight -= 1
                self._cond.notify_all()

    def request_stop(self) -> bool:
        """Refuse new work from now on; False when a stop had already begun."""
        with self._cond:
            if self._stopping:
                return False
            self._stopping = True
            return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for in-flight work to finish; True when it did inside ``timeout``."""
        end = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._inflight > 0:
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(left)
            return True

    def install(self, on_stop: Callable[[bool], None], *, on_stopping: Optional[Callable[[], None]] = None,
                signals: Sequence[int] = (signal.SIGTERM, signal.SIGINT)) -> "Drain":
        """Install the handlers (main thread only). A second signal changes nothing: the hard-exit
        timer already holds the deadline."""
        def handler(_signum: int, _frame: Any) -> None:
            if self.request_stop():
                threading.Thread(target=self._stop, args=(on_stopping, on_stop), daemon=True).start()

        for sig in signals:
            signal.signal(sig, handler)
        return self

    def _stop(self, on_stopping: Optional[Callable[[], None]], on_stop: Callable[[bool], None]) -> None:
        hard = threading.Timer(self.deadline + self.grace, os._exit, args=(EXIT_HARD_STOP,))
        hard.daemon = True
        hard.start()
        if on_stopping is not None:
            try:
                on_stopping()
            except Exception:  # a failing stop notice must not stop the drain
                traceback.print_exc()
        on_stop(self.wait(self.deadline))
