"""Where a service's things live (fabric-service/0.1): the services directory, a service's data, config, logs and run
directories per OS, private directories and atomic writes. Part of the service kit (FAA-65, layer L1)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import (
    WINDOWS,
    ServiceError,
    _INSTANCE,
    _require_id,
)
from fabric_platform import (
    _win_protect,
)


def services_dir() -> Path:
    """Descriptor directory: FABRIC_SERVICES_DIR, else the per-user OS location."""
    override = os.environ.get("FABRIC_SERVICES_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric/services"
    if sys.platform == "win32":
        # DEC-0032: LOCALAPPDATA, not APPDATA, so token files never roam with the profile.
        return _local_app_data() / "passioncode-fabric" / "services"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")
    return Path(base) / "passioncode-fabric/services"


def service_dirs(service_id: str) -> Dict[str, Path]:
    """State lives outside code: data+config, logs and cache in per-user OS directories."""
    _require_id(service_id)
    home = Path.home()
    if sys.platform == "darwin":
        return {
            "data": home / "Library/Application Support" / service_id,
            "logs": home / "Library/Logs" / service_id,
            "cache": home / "Library/Caches" / service_id,
        }
    if sys.platform == "win32":
        data = _local_app_data() / service_id
        return {"data": data, "logs": data / "Logs", "cache": data / "Cache"}
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / service_id
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / service_id
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / service_id
    return {"data": data, "logs": state / "logs", "cache": cache}


def instance_dirs(service_id: str, instance: str = "default") -> Dict[str, Path]:
    """One instance's folders (FAA-125, brief D16): the ``default`` instance keeps ``service_dirs`` (an existing install
    keeps its data, logs and lock); any other is a sibling named as its descriptor, ``<id>.<instance>``, never inside
    the default tree, so one instance's purge, prune or backup never reaches another's."""
    _require_id(service_id)
    if not isinstance(instance, str) or not _INSTANCE.match(instance):
        raise ServiceError("Instance %r must match %s." % (instance, _INSTANCE.pattern))
    if instance == "default":
        return service_dirs(service_id)
    folder, personal = "%s.%s" % (service_id, instance), service_dirs(service_id)
    if sys.platform == "win32":
        data = personal["data"].parent / folder
        return {"data": data, "logs": data / "Logs", "cache": data / "Cache"}
    if sys.platform == "darwin":
        return {key: path.parent / folder for key, path in personal.items()}
    return {"data": personal["data"].parent / folder, "logs": personal["logs"].parent.parent / folder / "logs",
            "cache": personal["cache"].parent / folder}


def _read_at(fd: int, n: int, offset: int) -> bytes:
    """`os.pread` where it exists; Windows has none, so seek and read (the descriptor's appends
    still go to the end: O_APPEND moves to it before every write)."""
    if hasattr(os, "pread"):
        return os.pread(fd, n, offset)
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, n)


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        _win_protect(path, folder=True)
    else:
        os.chmod(path, 0o700)
    return path


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Temporary file in the same directory, fsync, rename: a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:  # closed on every path: Windows cannot delete a file still open
            if WINDOWS:
                # The file's ACL is its privacy (DEC-0032): set explicitly and protected — before the bytes go in —
                # so it does not depend on what the folder hands down. A rename keeps it.
                _win_protect(Path(tmp), folder=False)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not WINDOWS:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # the error that got us here is the one to report, not a failed cleanup (FAA-85)
        raise
