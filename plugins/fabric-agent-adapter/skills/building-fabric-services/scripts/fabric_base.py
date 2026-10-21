"""What every module of the service kit shares (FAA-65, layer L3): the protocol name, ServiceError, the
platform, ids and now_iso. Standard library only."""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path


PROTOCOL = "fabric-service/0.1"


EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/service/0.1"


# Lifecycle rules: references/lifecycle.md, the rule for this kit's users, which implements the public
# contract's service specification (Lifecycle). A launchd-supervised copy that finds the lock held backs
# off in-process for this long before its exit 75 (LC-03, F8): under KeepAlive with ThrottleInterval 10
# that is a few starts an hour instead of one every 10 s.
SUPERVISOR_ENV = "FABRIC_SERVICE_SUPERVISOR"


# LC-01: SIGTERM reaches exit in at most 10 s with work in flight — drain 8 s, then hand over,
# and a hard exit 2 s later if the hand-over itself hangs. ExitTimeOut sits above both.
DRAIN_SECONDS = 8.0


_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


_INSTANCE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


# DEC-0032: a local path is POSIX (`/…`, `~/…`) or Windows (`C:\…`, `C:/…`, `~\…`); a network
# share (`\\server\…`, `\\?\…`) is never a local path.
# DEC-0057: `//server/…` and `/\\server…` are shares on Windows too, so a leading slash is followed by neither.
_LOCAL_PATH = re.compile(r"^(~[\\/]|/(?![\\/])|[A-Za-z]:[\\/])")


_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,250}\.service$")


_TASK = re.compile(r"^\\[A-Za-z0-9 ._\\-]{1,254}$")


WINDOWS = os.name == "nt"


# Without O_BINARY a Windows descriptor is in text mode and every LF written becomes CRLF.
_O_BINARY = getattr(os, "O_BINARY", 0)


class ServiceError(Exception):
    """A rule of the extension was violated; the message is one readable sentence."""


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expand(path: str) -> Path:
    """Paths in a descriptor may start with ~/ (or ~\\ on Windows); everything else must be
    absolute, and a network share is never a local path (DEC-0032)."""
    if not _LOCAL_PATH.match(str(path)):
        raise ServiceError("Path %r must be absolute or start with ~/." % path)
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        raise ServiceError("Path %r must be absolute or start with ~/." % path)
    return p


def _require_id(service_id: str) -> None:
    if not (isinstance(service_id, str) and _ID.fullmatch(service_id)):
        raise ServiceError("Service id %r must match %s." % (service_id, _ID.pattern))


__all__ = [name for name in dir() if not name.startswith("_")]
