"""Settings backups (DEC-0025, FAC-SEM-035): the canonical form, the digest, writing, listing, checking and
restoring them. Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fabric_base import (
    ServiceError,
    _ID,
    _INSTANCE,
    _require_id,
)
from fabric_paths import (
    atomic_write,
    ensure_private_dir,
)
from fabric_usage import (
    _is_timestamp,
)


SETTINGS_BACKUP_FORMAT = "fabric-settings-backup/1"


SETTINGS_BACKUP_KEEP = 14


SETTINGS_BACKUP_MAX_AGE_SECONDS = 24 * 60 * 60


_STALE_TEMP_SECONDS = 60 * 60


_SAFE_INTEGER = 2 ** 53 - 1


_TABLE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


_SECRET_TABLE = re.compile(r"^((.+_)?(account_connections?|account_connection_drafts?|tokens?|secrets?|credentials?|passwords?|login_codes?)|(operator_)?sessions?)$")


_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


_SECRET_COLUMN = re.compile(r"^(?:.+_)?(?:[Tt]oken|[Ss]ecret|[Pp]assword|[Pp]assphrase|[Aa]pi_?[Kk]ey|[Pp]rivate_[Kk]ey|[Cc]ookie|[Ll]ogin_[Cc]ode|[Oo]tp|[Cc]redential)s?$")


_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


_SURROGATE = re.compile("[\ud800-\udfff]")


_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\S*")


_MAX_CELL_CHARS = 1048576


_MAX_ROW_VALUES = 512


def _canonical_check(value: Any, at: str = "") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        # CT-25 (DEC-0052): Python cannot encode a lone surrogate as UTF-8, so no two languages agree on its bytes.
        if _SURROGATE.search(value):
            raise ServiceError("%s: a lone surrogate has no canonical form" % (at or "/"))
        return
    if isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise ServiceError("%s: %d is outside ±(2^53 − 1) and has no canonical form; store it as a string" % (at or "/", value))
        return
    if isinstance(value, float):
        raise ServiceError("%s: a fraction has no canonical form; a settings backup stores it as its decimal string" % (at or "/"))
    if isinstance(value, list):
        for i, item in enumerate(value):
            _canonical_check(item, "%s/%d" % (at, i))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ServiceError("%s: object keys are strings" % (at or "/"))
            _canonical_check(key, "%s (a key)" % (at or "/"))
            _canonical_check(item, "%s/%s" % (at, key))
        return
    raise ServiceError("%s: %s is not a JSON value" % (at or "/", type(value).__name__))


def settings_canonical_json(value: Any) -> str:
    """The settings canonical form (DEC-0025, DEC-0043): keys sorted by code point at every level, ", " and ": ",
    strings escaped as JSON requires and nothing else, integers in decimal — Python's
    ``json.dumps(value, sort_keys=True, ensure_ascii=False)``. Refuses a fraction, an integer outside ±(2^53 − 1)
    and anything that is not JSON."""
    _canonical_check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def settings_backup_digest(tables: Any) -> str:
    """The ``sha256`` a settings backup carries: SHA-256 of the UTF-8 canonical JSON of ``tables``."""
    return hashlib.sha256(settings_canonical_json(tables).encode("utf-8")).hexdigest()


def settings_backup_problems(doc: Any) -> List[str]:
    """Why a reader refuses this settings backup: its shape (``settings-backup.schema.json``) and FAC-SEM-035 —
    the checksum is the digest of the tables, counts name exactly the tables and their rows, every row is as wide as
    its columns, and every value has a canonical form. Empty means intact."""
    if not isinstance(doc, dict):
        return ["a settings backup is a JSON object"]
    problems: List[str] = []
    if doc.get("format") != SETTINGS_BACKUP_FORMAT:
        problems.append("format must be %s, not %r: a reader refuses a format it does not know" % (SETTINGS_BACKUP_FORMAT, doc.get("format")))
    for key in ("format", "service", "created_at", "reason", "sha256", "counts", "tables"):
        if key not in doc:
            problems.append("missing %s" % key)
    for key in doc:
        if key not in ("format", "service", "created_at", "reason", "sha256", "counts", "tables", "extensions"):
            problems.append("%s is not a settings backup field" % key)
    if "extensions" in doc:
        if not isinstance(doc["extensions"], dict):
            problems.append("extensions is an object")
        else:
            for key in doc["extensions"]:
                if not _URI.fullmatch(key):
                    problems.append("extensions key %r is not a URI" % key)
    service = doc.get("service")
    if "service" in doc:
        if not isinstance(service, dict) or set(service) != {"id", "instance", "version", "schema"}:
            problems.append("service is {id, instance, version, schema}")
        else:
            if not _ID.fullmatch(str(service["id"])):
                problems.append("service.id must match %s" % _ID.pattern)
            if not _INSTANCE.fullmatch(str(service["instance"])):
                problems.append("service.instance must match %s" % _INSTANCE.pattern)
            if not (isinstance(service["version"], str) and len(service["version"]) <= 64):
                problems.append("service.version is a string of at most 64 characters")
            schema = service["schema"]
            if not ((isinstance(schema, int) and not isinstance(schema, bool) and schema >= 0)
                    or (isinstance(schema, str) and 1 <= len(schema) <= 64)):
                problems.append("service.schema is a whole number or a short string")
    if "created_at" in doc and not _is_timestamp(doc["created_at"]):
        problems.append("created_at is a UTC timestamp")
    if "reason" in doc and not (isinstance(doc["reason"], str) and _REASON.fullmatch(doc["reason"])):
        problems.append("reason must match %s" % _REASON.pattern)
    if "sha256" in doc and not (isinstance(doc["sha256"], str) and _SHA256.fullmatch(doc["sha256"])):
        problems.append("sha256 is 64 lowercase hex digits")
    tables = doc.get("tables") if isinstance(doc.get("tables"), dict) else {}
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    if "tables" in doc and not isinstance(doc.get("tables"), dict):
        problems.append("tables is an object")
    if "counts" in doc and not isinstance(doc.get("counts"), dict):
        problems.append("counts is an object")
    for name in list(tables) + [n for n in counts if n not in tables]:
        if not _TABLE.fullmatch(name) or _SECRET_TABLE.fullmatch(name):
            problems.append("table %s is never backed up: it can only hold connections, tokens, secrets, credentials, "
                            "passwords, login codes or sessions (or its name is not a table name)" % name)
    for name, count in counts.items():
        if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0):
            problems.append("counts.%s is a whole number" % name)
    canonical = True
    for name, table in tables.items():
        if not isinstance(table, dict) or set(table) != {"columns", "rows"}:
            problems.append("tables.%s is {columns, rows}" % name)
            continue
        columns, rows = table["columns"], table["rows"]
        if not (isinstance(columns, list) and 1 <= len(columns) <= 512 and len(set(map(str, columns))) == len(columns)):
            problems.append("tables.%s.columns is 1 to 512 distinct names" % name)
            columns = columns if isinstance(columns, list) else []
        for column in columns:
            if not (isinstance(column, str) and _COLUMN.fullmatch(column)) or _SECRET_COLUMN.fullmatch(str(column)):
                problems.append("column %s.%s is refused: its name says it holds a credential value (name the secret, "
                                "never store it: secret_name, token_slot)" % (name, column))
        if not isinstance(rows, list):
            problems.append("tables.%s.rows is a list" % name)
            continue
        width = len(columns)
        for i, row in enumerate(rows):
            at = "/tables/%s/rows/%d" % (name, i)
            if not isinstance(row, list):
                problems.append("%s is a list of values" % at)
                continue
            if len(row) != width:
                problems.append("FAC-SEM-035 %s: row has %d values for %d columns" % (at, len(row), width))
            if len(row) > _MAX_ROW_VALUES:
                problems.append("%s holds more than %d values" % (at, _MAX_ROW_VALUES))
            for j, cell in enumerate(row):
                if isinstance(cell, float) or (isinstance(cell, int) and not isinstance(cell, bool) and abs(cell) > _SAFE_INTEGER):
                    canonical = False
                    problems.append("FAC-SEM-035 %s/%d: a fraction or an unsafe integer has no canonical form; store it as a string" % (at, j))
                elif isinstance(cell, str) and _SURROGATE.search(cell):
                    canonical = False
                    problems.append("FAC-SEM-035 %s/%d: a string with a lone surrogate cannot be encoded as UTF-8" % (at, j))
                elif isinstance(cell, str) and len(cell) > _MAX_CELL_CHARS:
                    problems.append("%s/%d is longer than %d characters" % (at, j, _MAX_CELL_CHARS))
                elif not (cell is None or isinstance(cell, (bool, int, str))):
                    canonical = False
                    problems.append("%s/%d is not a JSON scalar" % (at, j))
        if counts.get(name) != len(rows):
            problems.append("FAC-SEM-035 /counts/%s: counts says %s for %d rows" % (name, counts.get(name, "nothing"), len(rows)))
    for name in counts:
        if name not in tables:
            problems.append("FAC-SEM-035 /counts/%s: counts names %s, which the backup does not carry" % (name, name))
    if canonical and isinstance(doc.get("tables"), dict):
        try:
            digest: Optional[str] = settings_backup_digest(tables)
        except (ServiceError, UnicodeError, TypeError, ValueError) as exc:  # a name no canonical form can carry
            digest = None
            problems.append("FAC-SEM-035 /tables: the tables have no canonical form (%s)" % exc)
        if digest is not None and doc.get("sha256") != digest:
            problems.append("FAC-SEM-035 /sha256: the checksum does not match the tables: the file is damaged and a reader refuses it")
    return problems


def settings_backup_root(platform: str = sys.platform) -> Path:
    """Where every service keeps its settings backups — outside its data directory (DEC-0025)."""
    if platform == "darwin":
        return Path.home() / "Library/Application Support/PassionCode"
    if platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "PassionCode"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "PassionCode"


def settings_backup_dir(service_id: str, instance: str = "default", root: Optional[Path] = None) -> Path:
    _require_id(service_id)
    if not (isinstance(instance, str) and _INSTANCE.fullmatch(instance)):
        raise ServiceError("instance must match %s" % _INSTANCE.pattern)
    return (root or settings_backup_root()) / "settings-backups" / service_id / instance


def make_settings_backup(*, service_id: str, instance: str = "default", version: str, schema: Any,
                         tables: Dict[str, Dict[str, Any]], reason: str, now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """A snapshot of the operator's decisions and bindings: the tables on the service's allow-list, each
    ``{"columns": [...], "rows": [[...], ...]}`` of JSON scalars (a fraction as its decimal string). Refuses a file a
    reader would refuse."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    doc = {"format": SETTINGS_BACKUP_FORMAT,
           "service": {"id": service_id, "instance": instance, "version": version, "schema": schema},
           "created_at": now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "reason": reason,
           "sha256": "", "counts": {name: len(table.get("rows") or []) for name, table in tables.items()}, "tables": tables}
    try:
        doc["sha256"] = settings_backup_digest(tables)
    except ServiceError as exc:
        raise ServiceError("this snapshot has no canonical form: %s" % exc) from None
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("this snapshot would be refused: " + "; ".join(problems))
    return doc


def _backup_name(doc: Dict[str, Any]) -> str:
    stamp = doc["created_at"].replace("-", "").replace(":", "")
    head, _, frac = stamp.rstrip("Z").partition(".")
    return "settings-%s%sZ.json" % (head, (frac + "000000")[:6])


def settings_backups(directory: Path) -> List[Path]:
    """The snapshot files, newest first (their names sort in time order)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if re.fullmatch(r"settings-[0-9]{8}T[0-9]{12}Z\.json", p.name)), reverse=True)


def _no_constant(name: str) -> Any:
    raise ValueError("%s is not JSON" % name)


def read_settings_backup(path: Path) -> Dict[str, Any]:
    """A snapshot a reader may trust, or ServiceError naming why it is refused (FAC-SEM-035)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_no_constant)
    except (OSError, ValueError) as exc:
        raise ServiceError("settings backup %s cannot be read: %s" % (path, exc)) from None
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("settings backup %s is refused: %s" % (path, "; ".join(problems)))
    return doc


def write_settings_backup(doc: Dict[str, Any], directory: Path, *, keep: int = SETTINGS_BACKUP_KEEP) -> Optional[Path]:
    """Write a snapshot made by ``make_settings_backup``: atomically, 0600 in a 0700 directory, named by its time.
    A temporary file an interrupted write left is removed first; a snapshot whose checksum equals the newest file's
    is not written again (None). After a write, all but the ``keep`` newest are removed (at least 14)."""
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("this snapshot would be refused: " + "; ".join(problems))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ensure_private_dir(directory)
    stale = time.time() - _STALE_TEMP_SECONDS
    for left in directory.iterdir():
        # Only a temporary file an interrupted write left: one a concurrent writer is still filling is younger.
        try:
            if left.name.startswith(".settings-") and left.stat().st_mtime < stale:
                left.unlink()
        except OSError:
            pass
    existing = settings_backups(directory)
    if existing:
        try:
            if read_settings_backup(existing[0])["sha256"] == doc["sha256"]:
                return None
        except Exception:  # noqa: BLE001 - a damaged newest file is no reason to skip a good snapshot
            pass
    path = directory / _backup_name(doc)
    atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8") + b"\n", 0o600)
    # The newest by name, but never the one just written: a clock that stepped back must not delete it.
    for old in [p for p in settings_backups(directory) if p != path][max(keep, SETTINGS_BACKUP_KEEP) - 1:]:
        old.unlink()
    return path


def backup_due(directory: Path, now: Optional[_dt.datetime] = None) -> bool:
    """True when there is no snapshot or the newest is older than 24 hours: take one at start or on the daily tick."""
    newest = settings_backups(directory)
    if not newest:
        return True
    try:
        stamp = _dt.datetime.strptime(newest[0].name[len("settings-"):-len("Z.json")], "%Y%m%dT%H%M%S%f").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return True  # a name no calendar has: take a fresh snapshot rather than trust it
    return ((now or _dt.datetime.now(_dt.timezone.utc)) - stamp).total_seconds() > SETTINGS_BACKUP_MAX_AGE_SECONDS


def newest_intact_backup(directory: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]], List[Tuple[Path, str]]]:
    """The source of an automatic restore: the newest snapshot that is intact and has content. Damaged ones are
    skipped and returned with the reason, for the restore report."""
    skipped: List[Tuple[Path, str]] = []
    for path in settings_backups(directory):
        try:
            doc = read_settings_backup(path)
        except Exception as exc:  # noqa: BLE001 - one damaged file never stops the scan
            skipped.append((path, str(exc)))
            continue
        if any(doc["counts"].values()):
            return path, doc, skipped
    return None, None, skipped


def restore_plan(doc: Dict[str, Any], current: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What restoring ``doc`` would do — it adds and never overwrites (DEC-0025). ``current`` describes the database
    now, per table: ``columns`` (all of them), ``key`` (the primary key columns), ``required`` (columns without a
    default) and ``existing`` (the primary keys present, as tuples). Per table: the rows to insert (dicts over the
    columns both sides have), how many are already present, the snapshot columns dropped, the current columns left
    to their defaults, the required columns the snapshot lacks, and every row refused with its key and reason.
    ``unknownTables`` names snapshot tables the service no longer has. The service applies ``insert`` and adds any
    row its database refuses to ``refused``; a manual restore shows this plan first and applying it is the operator's act."""
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("a damaged snapshot is never restored: " + "; ".join(problems))
    plan: Dict[str, Any] = {"source": {"created_at": doc["created_at"], "sha256": doc["sha256"]}, "tables": {}, "unknownTables": []}
    for name, table in doc["tables"].items():
        now_table = current.get(name)
        if now_table is None:
            plan["unknownTables"].append(name)
            continue
        columns = list(now_table.get("columns") or [])
        key = list(now_table.get("key") or [])
        required = list(now_table.get("required") or [])
        existing = {tuple(k) for k in now_table.get("existing") or []}
        shared = [c for c in table["columns"] if c in columns]
        missing = [c for c in required if c not in table["columns"]]
        entry = {"insert": [], "present": 0, "droppedColumns": [c for c in table["columns"] if c not in columns],
                 "defaultedColumns": [c for c in columns if c not in table["columns"]], "missingRequired": missing, "refused": []}
        planned = set()
        for row in table["rows"]:
            values = dict(zip(table["columns"], row))
            ident = [values.get(c) for c in key]
            if any(c not in table["columns"] for c in key):
                entry["refused"].append({"key": ident, "reason": "the primary key is not in the snapshot"})
            elif tuple(ident) in planned:
                entry["refused"].append({"key": ident, "reason": "the snapshot holds this key twice"})
            elif tuple(ident) in existing:
                entry["present"] += 1
            elif missing:
                entry["refused"].append({"key": ident, "reason": "required column %s is not in the snapshot" % ", ".join(missing)})
            else:
                planned.add(tuple(ident))
                entry["insert"].append({c: values[c] for c in shared})
        plan["tables"][name] = entry
    return plan
