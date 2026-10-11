#!/usr/bin/env python3
"""The dashboard kit (fabric-dashboard/0.1, Fabric Agent Contract DEC-0036): status, install, build, notice.

  dashboard_kit.py status [REPO] [--json]       # kit copies in a repository: version, state, what differs
  dashboard_kit.py install DIR [--force] [--dry-run]
                                               # copy fabric-dashboard.css and .js into DIR; a copy the
                                               # service changed is never overwritten without --force
  dashboard_kit.py build [--check]             # regenerate the theme block from themes.json, refresh kit.json
  dashboard_kit.py notice                      # the plugin's SessionStart hook: one line, or nothing

The kit lives next to this script in ../assets/dashboard-kit/. Standard library only; nothing here
reads a token, opens a port or writes outside the directory it is given. `notice` never writes and
always exits 0: a hook that fails would cost every session, in every repository.
"""

from __future__ import annotations

# argparse, hashlib and tempfile are imported where they are used: the SessionStart notice runs in
# every session, so its path imports only what it needs.
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

KIT_DIR = Path(__file__).resolve().parent.parent / "assets" / "dashboard-kit"
KIT_NAME = "fabric-dashboard-kit"
COPIED = ("fabric-dashboard.css", "fabric-dashboard.js")
MARKER = re.compile(r"fabric-dashboard-kit@(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?")
CSS_BEGIN, CSS_END = "/* fabric-dashboard-kit:themes:begin */", "/* fabric-dashboard-kit:themes:end */"
JS_BEGIN, JS_END = "/* fabric-dashboard-kit:theme-ids:begin */", "/* fabric-dashboard-kit:theme-ids:end */"
TOKEN_ORDER = ("bg", "panel", "panel-2", "ink", "muted", "border", "border-strong", "edge", "accent",
               "accent-weak", "accent-ink", "ok", "ok-weak", "warn", "warn-weak", "danger", "danger-weak",
               "info", "info-weak")
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".next", "out"}
EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"


class KitError(Exception):
    pass


# --- the kit itself ------------------------------------------------------------

def load_manifest(kit_dir: Path = KIT_DIR) -> Dict[str, Any]:
    return json.loads((kit_dir / "kit.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_tuple(text: str) -> Optional[Tuple[int, int, int]]:
    m = MARKER.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def claimed_version(path: Path) -> Optional[str]:
    """The kit version a copied file says it is, from the marker in its first lines."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(600)
    except OSError:
        return None
    m = MARKER.search(head)
    return m.group(0).split("@", 1)[1] if m else None


def parse_version(text: str) -> Tuple[int, int, int]:
    found = version_tuple(KIT_NAME + "@" + text)
    if not found:
        raise KitError("%r is not a semantic version." % text)
    return found


def theme_css(themes: Dict[str, Any]) -> str:
    """The generated theme block: graphite is the default for :root; every theme has a light rule,
    a [data-scheme=dark] rule and a prefers-color-scheme rule that a data-scheme="light" opts out of."""
    default = themes["default"]
    entries = themes["themes"]
    if default not in entries:
        raise KitError("themes.json: the default theme %r is not defined." % default)

    def decls(palette: Dict[str, str], scheme: str) -> str:
        missing = [t for t in TOKEN_ORDER if t not in palette]
        if missing:
            raise KitError("themes.json: %s %s misses %s." % (scheme, palette, ", ".join(missing)))
        return "color-scheme: %s; " % scheme + " ".join("--%s: %s;" % (t, palette[t]) for t in TOKEN_ORDER)

    lines, media = [], []
    for theme_id, theme in entries.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", theme_id):
            raise KitError("themes.json: %r is not a theme id." % theme_id)
        own = ':root[data-theme="%s"]' % theme_id
        if theme_id == default:
            lines.append(":root, %s { %s }" % (own, decls(theme["light"], "light")))
            lines.append(':root[data-scheme="dark"], %s[data-scheme="dark"] { %s }' % (own, decls(theme["dark"], "dark")))
            media.insert(0, '  :root:not([data-scheme="light"]) { %s }' % decls(theme["dark"], "dark"))
        else:
            lines.append("%s { %s }" % (own, decls(theme["light"], "light")))
            lines.append('%s[data-scheme="dark"] { %s }' % (own, decls(theme["dark"], "dark")))
            media.append('  %s:not([data-scheme="light"]) { %s }' % (own, decls(theme["dark"], "dark")))
    return "\n".join(lines + ["@media (prefers-color-scheme: dark) {"] + media + ["}"])


def replace_between(text: str, begin: str, end: str, body: str, name: str) -> str:
    start, stop = text.find(begin), text.find(end)
    if start < 0 or stop < start:
        raise KitError("%s has lost its %s … %s markers." % (name, begin, end))
    return text[: start + len(begin)] + "\n" + body + "\n" + text[stop:]


def build(kit_dir: Path = KIT_DIR, check: bool = False) -> List[str]:
    """Regenerate the theme block and the theme ids from themes.json and refresh kit.json.
    Returns the files that changed (with check=True: that would change, and nothing is written)."""
    themes = json.loads((kit_dir / "themes.json").read_text(encoding="utf-8"))
    css_path, js_path = kit_dir / "fabric-dashboard.css", kit_dir / "fabric-dashboard.js"
    css = css_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")
    ids = list(themes["themes"])
    new_css = replace_between(css, CSS_BEGIN, CSS_END, theme_css(themes), css_path.name)
    new_js = replace_between(js, JS_BEGIN, JS_END, "  var THEMES = %s;" % json.dumps(ids).replace('"', "'"), js_path.name)
    manifest = load_manifest(kit_dir)
    version = manifest["version"]
    for text, name in ((new_css, css_path.name), (new_js, js_path.name)):
        if claimed_version_text(text) != version:
            raise KitError("%s says %s, kit.json says %s; raise them together." % (name, claimed_version_text(text), version))
    import hashlib
    changed = []
    for path, text in ((css_path, new_css), (js_path, new_js)):
        if text != path.read_text(encoding="utf-8"):
            changed.append(path.name)
            if not check:
                atomic_write(path, text)
    digest = {name: hashlib.sha256((new_css if name.endswith(".css") else new_js).encode("utf-8")).hexdigest() for name in COPIED}
    digest["themes.json"] = sha256(kit_dir / "themes.json")
    new_manifest = dict(manifest)
    new_manifest["themes"] = ids
    new_manifest["files"] = digest
    history = dict(manifest.get("history") or {})
    history[version] = {name: digest[name] for name in COPIED}
    new_manifest["history"] = history
    if new_manifest != manifest:
        changed.append("kit.json")
        if not check:
            atomic_write(kit_dir / "kit.json", json.dumps(new_manifest, indent=2) + "\n")
    return changed


def claimed_version_text(text: str) -> Optional[str]:
    m = MARKER.search(text[:600])
    return m.group(0).split("@", 1)[1] if m else None


def atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- copies in a repository -------------------------------------------------------

def is_kit_source(path: Path) -> bool:
    """The kit's own directory (this repository, or an installed copy of the plugin) is not a copy."""
    manifest = path.parent / "kit.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("name") == KIT_NAME
    except (OSError, ValueError, AttributeError):
        return False


def git(repo: Path, *args: str, timeout: float = 2.0) -> Optional[str]:
    try:
        done = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def repo_root(start: Path) -> Optional[Path]:
    out = git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out and out.strip() else None


def find_copies(repo: Path) -> List[Path]:
    listed = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                 "*fabric-dashboard.css", "*fabric-dashboard.js")
    if listed is not None:
        paths = [repo / p for p in listed.split("\0") if p]
    else:
        paths = []
        for top, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if len(Path(top).relative_to(repo).parts) > 6:
                dirs[:] = []
            paths += [Path(top) / f for f in files if f in COPIED]
    return sorted(p for p in paths if p.name in COPIED and p.is_file() and not is_kit_source(p))


def copy_state(path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    current = manifest["version"]
    version = claimed_version(path)
    digest = sha256(path)
    known = ((manifest.get("history") or {}).get(version or "") or {}).get(path.name)
    if version is None:
        state = "unmarked"
    elif parse_version(version) > parse_version(current):
        state = "newer"
    elif known is not None and digest != known:
        state = "changed"
    elif parse_version(version) < parse_version(current):
        state = "older"
    else:
        state = "current"
    return {"path": str(path), "file": path.name, "version": version, "state": state, "current": current}


def services_dir() -> Path:
    override = os.environ.get("FABRIC_SERVICES_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric/services"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData/Local")
        return Path(base) / "passioncode-fabric" / "services"
    return Path(os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")) / "passioncode-fabric/services"


def same_repository(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        u = u.strip().lower()
        u = re.sub(r"^git@([^:]+):", r"\1/", u)
        u = re.sub(r"^[a-z+]+://", "", u)
        u = re.sub(r"^[^@/]+@", "", u)
        return re.sub(r"\.git$", "", u).rstrip("/")
    return bool(a and b) and norm(a) == norm(b)


def services_of(repo: Path, directory: Optional[Path] = None) -> List[str]:
    """The services whose descriptor names this repository as its source (`source.repository`)."""
    origin = (git(repo, "config", "--get", "remote.origin.url") or "").strip()
    if not origin:
        return []
    found = []
    try:
        entries = sorted((directory or services_dir()).glob("*.json"))
    except OSError:
        return []
    for path in entries:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source = str(((d.get("source") or {}) if isinstance(d, dict) else {}).get("repository") or "")
        if same_repository(source, origin):
            found.append("%s.%s" % (d.get("id"), d.get("instance", "default")))
    return found


def declares_dashboard(repo: Path) -> bool:
    """Whether the repository's code declares a dashboard surface (a quick git grep, no network)."""
    out = git(repo, "grep", "--untracked", "-l", "-I", "-E", r"""["']?dashboard["']?[[:space:]]*[:=][[:space:]]*\{?[[:space:]]*["']?path""", "--",
              "*.py", "*.mjs", "*.js", "*.ts", "*.json", timeout=2.0)
    return bool(out and out.strip())


def status(repo: Path, manifest: Optional[Dict[str, Any]] = None, directory: Optional[Path] = None) -> Dict[str, Any]:
    manifest = manifest or load_manifest()
    copies = [copy_state(p, manifest) for p in find_copies(repo)]
    services = services_of(repo, directory)
    return {"repository": str(repo), "kit": "%s@%s" % (KIT_NAME, manifest["version"]), "copies": copies,
            "services": services, "dashboard": bool(copies) or (bool(services) and declares_dashboard(repo))}


def notice_line(report: Dict[str, Any], script: Path) -> Optional[str]:
    """One line for the session, or None. Only an older (or unmarked) copy, or a service of this
    repository with a dashboard and no kit at all, earns it."""
    current = report["kit"].split("@", 1)[1]
    stale = [c for c in report["copies"] if c["state"] in ("older", "unmarked")]
    where = ", ".join(report["services"]) or "this repository's dashboard"
    command = 'python3 "%s" status' % script
    tail = ("fabric-dashboard/0.1, contract DEC-0036. Do not change it on your own: tell the operator, and with "
            "their go-ahead run `%s`, then follow building-fabric-services references/dashboard-kit.md, "
            "\"Upgrading an existing dashboard\"." % command)
    if stale:
        versions = sorted({c["version"] or "unmarked" for c in stale})
        return "[fabric-agent-adapter] %s is built from %s %s; %s is current (%s" % (
            where, KIT_NAME, " and ".join(versions), current, tail + ")")
    if not report["copies"] and report["dashboard"] and report["services"]:
        return "[fabric-agent-adapter] %s has a dashboard without %s; %s is current (%s" % (
            where, KIT_NAME, current, tail + ")")
    return None


def install(target: Path, force: bool = False, dry_run: bool = False, kit_dir: Path = KIT_DIR) -> List[str]:
    """Copy the kit's page files into target. Returns one sentence per file. Raises KitError, writing
    nothing, when a copy there was changed by the service and force is not given."""
    if not target.is_dir():
        raise KitError("%s is not a directory." % target)
    manifest = load_manifest(kit_dir)
    history = manifest.get("history") or {}
    refused, plan = [], []
    for name in COPIED:
        source, dest = kit_dir / name, target / name
        if not dest.exists():
            plan.append((source, dest, "added %s %s" % (name, manifest["version"])))
            continue
        digest, version = sha256(dest), claimed_version(dest)
        if digest == manifest["files"][name]:
            plan.append((None, dest, "%s is already %s" % (name, manifest["version"])))
            continue
        known = (history.get(version or "") or {}).get(name)
        if known != digest and not force:
            refused.append("%s was changed after it was copied (it says %s); move the page's own rules into its own "
                           "stylesheet or script, or pass --force to replace it" % (name, version or "no version"))
            continue
        plan.append((source, dest, "replaced %s %s with %s" % (name, version or "(unmarked)", manifest["version"])))
    if refused:
        raise KitError("; ".join(refused) + ". Nothing was written.")
    out = []
    for source, dest, sentence in plan:
        if source is not None and not dry_run:
            atomic_write(dest, source.read_text(encoding="utf-8"))
        out.append(("would be " + sentence) if dry_run and source is not None else sentence)
    return out


def declaration(manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest = manifest or load_manifest()
    return {EXTENSION_KEY: {"minWidth": 360, "appearance": ["scheme", "theme"], "themes": manifest["themes"],
                            "kit": "%s@%s" % (KIT_NAME, manifest["version"])}}


# --- command line --------------------------------------------------------------

def hook_cwd(stdin_text: str) -> Path:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
    except ValueError:
        cwd = None
    return Path(cwd or os.getcwd())


def notice() -> int:
    try:
        stdin_text = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read(65536)
        root = repo_root(hook_cwd(stdin_text))
        if root is not None:
            line = notice_line(status(root), Path(__file__).resolve())
            if line:
                print(line)
    except Exception:  # noqa: BLE001 — a hook never breaks a session
        pass
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv == ["notice"]:
        return notice()
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    p_status = sub.add_parser("status", help="kit copies in a repository")
    p_status.add_argument("repo", nargs="?", default=".")
    p_status.add_argument("--json", action="store_true")
    p_install = sub.add_parser("install", help="copy the kit into a directory")
    p_install.add_argument("dir")
    p_install.add_argument("--force", action="store_true")
    p_install.add_argument("--dry-run", action="store_true")
    p_build = sub.add_parser("build", help="regenerate the theme block from themes.json")
    p_build.add_argument("--check", action="store_true")
    sub.add_parser("notice", help="the SessionStart hook")
    args = parser.parse_args(argv)

    if args.command == "notice":
        return notice()
    try:
        if args.command == "status":
            start = Path(args.repo).expanduser().resolve()
            report = status(repo_root(start) or start)
            if args.json:
                print(json.dumps(report, indent=2))
                return 0
            print("%s: current kit %s" % (report["repository"], report["kit"]))
            for c in report["copies"]:
                print("  %-8s %s (%s)" % (c["state"], c["path"], c["version"] or "no version marker"))
            if not report["copies"]:
                print("  no kit copy" + (" — services %s declare a dashboard" % ", ".join(report["services"])
                                         if report["dashboard"] and report["services"] else ""))
            if report["services"]:
                print("  services from this repository: %s" % ", ".join(report["services"]))
            print("  declaration: %s" % json.dumps(declaration()))
            return 0
        if args.command == "install":
            for sentence in install(Path(args.dir).expanduser(), force=args.force, dry_run=args.dry_run):
                print(sentence)
            print("Next: link both files same-origin, declare %s" % json.dumps(declaration()))
            print("in the well-known document's extensions, and run check_dashboard_layout.mjs.")
            return 0
        if args.command == "build":
            changed = build(check=args.check)
            if args.check:
                if changed:
                    print("out of date: %s (run dashboard_kit.py build)" % ", ".join(changed))
                    return 1
                print("up to date")
                return 0
            print("rebuilt: %s" % (", ".join(changed) or "nothing changed"))
            return 0
    except KitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
