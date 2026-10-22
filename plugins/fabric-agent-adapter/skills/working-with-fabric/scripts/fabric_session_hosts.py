"""working-with-fabric, part of fabric_session.py (FAA-65): install-host-hooks for Codex and Kimi Code, which writes
only with --apply and refuses what it cannot read safely. Standard library only."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from fabric_session_env import (  # noqa: E402 - the kit (FAA-65)
    CONFIG_CAP,
    HOSTS,
    NATIVE_PLUGIN_HOSTS,
    _home,
)


try:  # Python 3.11+; only install-host-hooks --host kimi needs it, and refuses to write without it
    import tomllib
except ImportError:  # pragma: no cover — exercised by a test that removes it
    tomllib = None  # type: ignore[assignment]


class Refused(Exception):
    pass


def default_hook_script(env: Optional[Dict[str, str]] = None) -> Path:
    """The skills install (stable across updates) when present, else this script's own path, symlinks kept."""
    installed = _home(env) / ".agents" / "skills" / "working-with-fabric" / "scripts" / "fabric_session.py"
    return installed if installed.is_file() else Path(__file__).absolute().with_name("fabric_session.py")  # the entry point


def hook_command(script: str, host: str) -> str:
    import shlex
    quoted = '"%s"' % script if sys.platform == "win32" else shlex.quote(script)
    return "python3 -S %s hook session-start --host %s" % (quoted, host)


def _is_ours(command: Any, host: str) -> bool:
    return isinstance(command, str) and "fabric_session.py" in command and \
        command.rstrip().endswith("hook session-start --host %s" % host)


def _digest(data: Optional[bytes]) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else "absent"


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return None
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode) or st.st_size > CONFIG_CAP:
        raise Refused("%s is not a regular file of a reasonable size; nothing was changed" % path)
    with open(str(path), "rb") as handle:
        return handle.read()


def _codex_doc(data: Optional[bytes]) -> Dict[str, Any]:
    if data is None:
        return {"hooks": {}}
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("the file is not JSON, so its shape cannot be checked; nothing was changed")
    shaped = isinstance(doc, dict) and isinstance(doc.get("hooks", {}), dict) and all(
        isinstance(groups, list) and all(isinstance(g, dict) and isinstance(g.get("hooks", []), list)
                                         and all(isinstance(h, dict) for h in g.get("hooks", [])) for g in groups)
        for groups in doc.get("hooks", {}).values())
    if not shaped:
        raise Refused('the file has another shape than {"hooks": {"<Event>": [{"hooks": [...]}]}}; nothing was changed')
    return doc


def _codex_has(doc: Dict[str, Any], host: str) -> bool:
    return any(_is_ours(h.get("command"), host) for g in doc.get("hooks", {}).get("SessionStart", [])
               for h in g.get("hooks", []))


def _kimi_hooks(data: Optional[bytes]) -> List[Any]:
    if tomllib is None:
        raise Refused("reading config.toml safely needs Python 3.11 (tomllib); nothing was changed; "
                      "add the block above by hand, or run this with Python 3.11 or later")
    try:
        doc = tomllib.loads((data or b"").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Refused("the file is not valid TOML (%s); nothing was changed" % type(exc).__name__)
    hooks = doc.get("hooks", [])
    if not isinstance(hooks, list) or not all(isinstance(h, dict) for h in hooks):
        raise Refused("`hooks` has another shape than an array of [[hooks]] tables; nothing was changed")
    return hooks


def _kimi_block(command: str) -> str:
    return ("\n# fabric-agent-adapter (working-with-fabric): the Fabric session-start preamble. Remove it with\n"
            "# fabric_session.py install-host-hooks --host kimi --remove\n"
            "[[hooks]]\nevent = \"SessionStart\"\ncommand = %s\ntimeout = 5\n" % json.dumps(command))


_KIMI_COMMENT = _kimi_block("").split("[[hooks]]", 1)[0].lstrip("\n").splitlines(True)  # our two comment lines


def _kimi_spans(text: str, host: str) -> List[Tuple[int, int]]:
    """Where each `[[hooks]]` table whose command is ours sits in `text`, as line ranges [header, end). A table ends at
    the next header; trailing blank and comment lines belong to what follows. Each table is read on its own with
    tomllib, so a hand-touched table (another order, a comment, another timeout) is still found by what it runs."""
    lines = text.splitlines(True)
    headers = [i for i, line in enumerate(lines) if line.startswith("[")]
    spans = []
    for n, start in enumerate(headers):
        if not re.match(r"\[\[\s*hooks\s*\]\]\s*(#.*)?\Z", lines[start].rstrip("\r\n")):
            continue
        end = headers[n + 1] if n + 1 < len(headers) else len(lines)
        while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        try:
            table = tomllib.loads("".join(lines[start:end]))["hooks"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if isinstance(table, dict) and _is_ours(table.get("command"), host):
            spans.append((start, end))
    return spans


def _kimi_edit(text: str, host: str, command: Optional[str]) -> str:
    """`text` with our one `[[hooks]]` table pointed at `command`, or taken out (None) with the comment lines and the
    blank line `_kimi_block` put before it. Refused when there is not exactly one."""
    spans = _kimi_spans(text, host)
    if len(spans) != 1:
        raise Refused("found %d Fabric hook tables to edit; remove the extra ones by hand" % len(spans))
    lines = text.splitlines(True)
    start, end = spans[0]
    if command is not None:
        found = [i for i in range(start + 1, end) if re.match(r"\s*command\s*=", lines[i])]
        if len(found) != 1:
            raise Refused("the Fabric hook's command could not be found line by line; edit it by hand")
        lines[found[0]] = "command = %s\n" % json.dumps(command)
        return "".join(lines)
    if lines[max(0, start - len(_KIMI_COMMENT)):start] == _KIMI_COMMENT:
        start -= len(_KIMI_COMMENT)
    if start > 0 and lines[start - 1] == "\n":
        start -= 1
    return "".join(lines[:start] + lines[end:])


def _replace_file(path: Path, data: bytes, seen: Optional[bytes]) -> Optional[Path]:
    """Back the file up, then write `data` atomically with the file's own mode. Refused when the file changed
    since it was read. Returns the backup."""
    if _read_bytes(path) != seen:
        raise Refused("%s changed while this ran; nothing was changed" % path)
    backup = None
    mode = 0o600
    if seen is not None:
        mode = os.stat(str(path)).st_mode & 0o777
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        for n in range(100):  # never overwrite an earlier backup, even one made the same second
            backup = path.with_name("%s.%s%s.bak" % (path.name, stamp, "-%d" % n if n else ""))
            if not os.path.lexists(str(backup)):
                break
        fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(seen)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(str(tmp), mode)
    os.replace(str(tmp), str(path))
    return backup


def install_host_hooks_cli(argv: Sequence[str], env: Optional[Dict[str, str]] = None,
                           out: Callable[[str], None] = print,
                           err: Callable[[str], None] = lambda line: sys.stderr.write(line + "\n")) -> int:
    import argparse
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="fabric_session.py install-host-hooks",
                                     description="Add (or remove) the Fabric session-start preamble hook in Codex or "
                                                 "Kimi Code. A dry run unless --apply or --remove.")
    parser.add_argument("--host", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show the edit and write nothing (the default)")
    mode.add_argument("--apply", action="store_true", help="make the edit, after backing the file up")
    mode.add_argument("--remove", action="store_true", help="take this hook out again, after backing the file up")
    parser.add_argument("--config", default=None, help="the file to edit (default: the host's own)")
    parser.add_argument("--script", default=None, help="the fabric_session.py the hook runs")
    parser.add_argument("--expect-sha256", default=None, help="refuse unless the file still has this digest")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)
    if args.host in NATIVE_PLUGIN_HOSTS:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_fabric_native_installer", Path(__file__).with_name("host_hooks.py"))
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        return installer.main(list(argv), env=env, out=out, err=err)
    if args.host not in ("codex", "kimi"):
        err("install-host-hooks: --host must be codex, kimi, hermes, opencode, openclaw or pi (Claude uses its plugin)")
        return 2
    if args.config:
        path = Path(args.config).expanduser()
    elif args.host == "codex":
        path = Path(env.get("CODEX_HOME") or str(_home(env) / ".codex")) / "hooks.json"
    else:
        path = _home(env) / ".kimi-code" / "config.toml"
    script = Path(args.script).expanduser().absolute() if args.script else default_hook_script(env)
    command = hook_command(str(script), args.host)
    shifted = 0  # Codex hook groups after ours, whose position a removal moves
    updated = False  # our own hook was there with another command, and is rewritten (FAA-69)
    try:
        if not args.remove and not script.is_file():
            # A hook pointing at nothing fails at every session start; removal needs no script.
            raise Refused("--script %s is not a file; pass the fabric_session.py of a complete installed skill" % script)
        data = _read_bytes(path)
        digest = _digest(data)
        if args.expect_sha256 and args.expect_sha256 != digest:
            raise Refused("%s changed since the dry run (sha256 now %s); nothing was changed" % (path, digest))
        if args.host == "codex":
            doc = _codex_doc(data)
            present = _codex_has(doc, args.host)
            entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
            if args.remove:
                if not present:
                    out("install-host-hooks: no Fabric preamble hook in %s; nothing to change" % path)
                    return 0
                groups, dropped = [], None
                for index, group in enumerate(doc["hooks"]["SessionStart"]):
                    kept = [h for h in group.get("hooks", []) if not _is_ours(h.get("command"), args.host)]
                    if kept or not group.get("hooks"):
                        groups.append(dict(group, hooks=kept) if kept != group.get("hooks") else group)
                    elif dropped is None:
                        dropped = index  # a group that held only our hook goes; the groups after it move up
                if dropped is not None:
                    shifted = len(doc["hooks"]["SessionStart"]) - dropped - 1
                if groups:
                    doc["hooks"]["SessionStart"] = groups
                else:
                    del doc["hooks"]["SessionStart"]
                new = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
            elif present:
                owned = [h for g in doc["hooks"]["SessionStart"] for h in g.get("hooks", [])
                         if _is_ours(h.get("command"), args.host)]
                if len(owned) != 1:
                    raise Refused("multiple Fabric hooks are configured; preserve their matchers and resolve duplicates before updating")
                if owned[0]["command"] == command:
                    out("install-host-hooks: the Fabric preamble hook is already in %s; nothing to change" % path)
                    return 0
                owned[0]["command"] = command
                updated = True
                new = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
            else:
                doc.setdefault("hooks", {}).setdefault("SessionStart", []).append(entry)
                new = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
            change = ("remove from" if args.remove else "update in" if updated else "add to") + " hooks.SessionStart"
            shown = json.dumps(entry, indent=2)
        else:
            block = _kimi_block(command)
            text = (data or b"").decode("utf-8", "replace")
            # Our table is found by what it runs (_is_ours), not by its exact text, so a stale path is repaired and a
            # hand-touched table is still removed (FAA-69). A dry run without a TOML reader shows the plain append.
            readable = tomllib is not None or args.apply or args.remove
            owned = [h for h in _kimi_hooks(data) if _is_ours(h.get("command"), args.host)] if readable else []
            if len(owned) > 1:
                raise Refused("multiple Fabric hooks are configured in %s; remove the extra ones by hand" % path)
            if args.remove:
                if not owned:
                    out("install-host-hooks: no Fabric preamble hook in %s; nothing to change" % path)
                    return 0
                new_text = _kimi_edit(text, args.host, None)
            elif owned and owned[0].get("command") == command:
                out("install-host-hooks: the Fabric preamble hook is already in %s; nothing to change" % path)
                return 0
            elif owned:
                new_text = _kimi_edit(text, args.host, command)
                updated = True
            else:
                new_text = text + ("" if not text or text.endswith("\n") else "\n") + block
            new = new_text.encode("utf-8")
            if args.apply or args.remove:
                after = _kimi_hooks(new)
                mine = [h.get("command") for h in after if _is_ours(h.get("command"), args.host)]
                growth = -1 if args.remove else 0 if updated else 1
                if len(after) != len(_kimi_hooks(data)) + growth or mine != ([] if args.remove else [command]):
                    raise Refused("the edited file would not read back as expected; nothing was changed")
            change = "remove from" if args.remove else "update in" if updated else "append to"
            shown = block.strip("\n")
        if not (args.apply or args.remove):
            out("install-host-hooks: dry run, nothing is written.")
            out("file: %s" % path)
            out("sha256: %s" % digest)
            out("would %s:" % change)
            out(shown)
            out("Apply it, on the person's go-ahead: fabric_session.py install-host-hooks --host %s --apply "
                "--expect-sha256 %s" % (args.host, digest))
            out("The hook only prints the preamble at session start (no turn observation, no unread count: %s "
                "cannot rejoin its Fabric session yet). It is silent in a session Fabric launched.%s" % (
                    HOSTS[args.host], " Codex may ask you to trust the new hook (/hooks) before it runs."
                    if args.host == "codex" else ""))
            return 0
        backup = _replace_file(path, new, data)
        out("install-host-hooks: %s %s %s." % ("removed the Fabric preamble hook from" if args.remove
                                              else "updated the Fabric preamble hook in" if updated
                                              else "added the Fabric preamble hook to", path,
                                              "(backup: %s)" % backup if backup else "(new file)"))
        out("Undo: fabric_session.py install-host-hooks --host %s %s" % (args.host, "--apply" if args.remove else "--remove"))
        if shifted:
            # Codex keys a hook's trust by its event, group and index: the groups after ours moved up one, so Codex asks
            # the person to trust them again in /hooks before they run.
            out("Codex trusts a hook by its position: %d SessionStart hook group(s) after the removed one moved, and "
                "Codex will ask you to approve them again in /hooks." % shifted)
        return 0
    except Refused as exc:
        err("install-host-hooks: refused: %s" % exc)
        return 1
    except OSError as exc:
        err("install-host-hooks: %s could not be written (%s); nothing was changed" % (path, type(exc).__name__))
        return 1
