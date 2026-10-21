#!/usr/bin/env python3
"""The service kit as a versioned set of modules: build its manifest, install it into a service, report a copy's state.

The kit is not one file. ``kit.json`` beside this script lists every module in dependency order, per language, with
the kit modules it imports and its sha256, and ``history`` keeps the sha256 of every earlier release, so a copy in a
service can be told apart: ``current``, ``older`` (with the release it came from), or ``modified``.

    fabric_kit.py install <service-dir> [--lang py|node] [--module NAME ...] [--all] [--dry-run] [--force]
    fabric_kit.py status <service-dir> [--json]
    fabric_kit.py build [--check]          # maintainers: refresh kit.json from the sources

``install`` copies the closure of the named modules (default ``fabric_service`` / ``fabric-service``) and nothing else.
It refuses to overwrite a file it does not recognise (a ``modified`` copy) unless ``--force``. ``status`` also names a
module a present module imports that is missing from the folder: the copy would fail when that code path runs.
Standard library only. Exit codes: 0 done or all current, 1 a problem (missing, modified, refused), 2 usage.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "kit.json"
LANGS = {"py": "python", "node": "node"}
DEFAULT_ROOT = {"python": "fabric_service", "node": "fabric-service"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_imports(path: Path, modules: List[str]) -> List[str]:
    """The kit modules a Python file imports, at any depth of its code (a lazy import is a dependency too)."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name in modules)
        elif isinstance(node, ast.ImportFrom) and node.module in modules:
            found.add(node.module)
    found.discard(path.stem)
    return sorted(found)


def node_imports(path: Path, modules: List[str]) -> List[str]:
    """The kit modules an ES module imports (static `from './x.mjs'` and dynamic `import('./x.mjs')`)."""
    text = path.read_text(encoding="utf-8")
    found = set(re.findall(r"""(?:from|import\()\s*['"]\./([A-Za-z0-9_-]+)\.mjs['"]""", text)) & set(modules)
    found.discard(path.stem)
    return sorted(found)


def load_manifest() -> Dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def build(check: bool = False) -> List[str]:
    """Refresh every module's imports and sha256 in kit.json, and record this release's digests in its history.
    Returns what changed (with check=True nothing is written)."""
    manifest = load_manifest()
    changed = []
    for lang, entries in (("python", manifest["python"]), ("node", manifest["node"])):
        names = [e["module"] for e in entries]
        for entry in entries:
            path = HERE / entry["file"]
            imports = (python_imports if lang == "python" else node_imports)(path, names)
            digest = _sha256(path)
            if entry.get("imports") != imports or entry.get("sha256") != digest:
                changed.append(entry["file"])
                entry["imports"], entry["sha256"] = imports, digest
    data = sorted({d for e in manifest["python"] + manifest["node"] for d in e.get("data", [])})
    digests = {d: _sha256(HERE / d) for d in data}
    if manifest.get("data") != digests:
        changed.append("data files")
        manifest["data"] = digests
    current = {e["file"]: e["sha256"] for e in manifest["python"] + manifest["node"]}
    current.update(digests)
    if manifest.setdefault("history", {}).get(manifest["version"]) != current:
        manifest["history"][manifest["version"]] = current
        changed.append("kit.json history %s" % manifest["version"])
    if changed and not check:
        MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return changed


def closure(entries: List[Dict], roots: List[str]) -> List[Dict]:
    """The named modules and everything they import, in the manifest's (dependency) order."""
    by_name = {e["module"]: e for e in entries}
    unknown = [r for r in roots if r not in by_name]
    if unknown:
        raise SystemExit("unknown kit module: %s (the manifest lists %s)" % (", ".join(unknown), ", ".join(by_name)))
    wanted, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name not in wanted:
            wanted.add(name)
            stack.extend(by_name[name]["imports"])
    return [e for e in entries if e["module"] in wanted]


def state_of(path: Path, manifest: Dict) -> Dict:
    """`current`, `older` with the release a copy came from, or `modified` (a digest no release had)."""
    digest = _sha256(path)
    if any(e["file"] == path.name and e["sha256"] == digest for e in manifest["python"] + manifest["node"]) or \
            manifest.get("data", {}).get(path.name) == digest:
        return {"state": "current", "version": manifest["version"]}
    for version, files in sorted(manifest.get("history", {}).items(), key=lambda kv: [int(x) for x in re.findall(r"[0-9]+", kv[0])], reverse=True):
        if files.get(path.name) == digest:
            return {"state": "older", "version": version}
    return {"state": "modified", "version": None}


def status(service_dir: Path) -> Dict:
    manifest = load_manifest()
    report = {"kit": manifest["version"], "files": [], "missing": []}
    for lang in ("python", "node"):
        entries = manifest[lang]
        present = [e for e in entries if (service_dir / e["file"]).is_file()]
        for e in present:
            report["files"].append({"file": e["file"], **state_of(service_dir / e["file"], manifest)})
        names = {e["module"] for e in present}
        by_name = {e["module"]: e for e in entries}
        reader = python_imports if lang == "python" else node_imports
        # What each copy imports is read from the copy itself (an older release imports other modules than this one);
        # a module it lacks would be installed at this release, so that module's own imports are followed too.
        queue = [(e["file"], reader(service_dir / e["file"], list(by_name))) for e in present]
        reported = set()
        for e in present:
            for d in e.get("data", []):
                if (service_dir / d).is_file():
                    if d not in [f["file"] for f in report["files"]]:
                        report["files"].append({"file": d, **state_of(service_dir / d, manifest)})
                elif d not in reported:
                    reported.add(d)
                    report["missing"].append({"file": e["file"], "needs": d})
        while queue:
            importer, deps = queue.pop(0)
            for dep in deps:
                if dep in names or dep in reported:
                    continue
                reported.add(dep)
                report["missing"].append({"file": importer, "needs": by_name[dep]["file"]})
                queue.append((by_name[dep]["file"], by_name[dep]["imports"]))
    return report


def install(service_dir: Path, lang: str, modules: List[str], dry_run: bool = False, force: bool = False) -> Dict:
    manifest = load_manifest()
    entries = manifest[lang]
    roots = modules or [DEFAULT_ROOT[lang]]
    plan = closure(entries, roots)
    result = {"kit": manifest["version"], "copied": [], "kept": [], "refused": []}
    files = []
    for e in plan:
        files.append(e["file"])
        files.extend(d for d in e.get("data", []) if d not in files)
    for name in files:
        target = service_dir / name
        if target.is_file():
            st = state_of(target, manifest)
            if st["state"] == "current":
                result["kept"].append(name)
                continue
            if st["state"] == "modified" and not force:
                result["refused"].append(name)
                continue
        result["copied"].append(name)
    if not dry_run and not result["refused"]:
        service_dir.mkdir(parents=True, exist_ok=True)
        for name in result["copied"]:
            tmp = service_dir / (".%s.tmp" % name)
            shutil.copyfile(HERE / name, tmp)
            os.replace(tmp, service_dir / name)
    return result


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="fabric_kit.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser("install", help="copy a module's closure into a service")
    p_install.add_argument("dir", type=Path)
    p_install.add_argument("--lang", choices=sorted(LANGS), default="py")
    p_install.add_argument("--module", action="append", default=[])
    p_install.add_argument("--all", action="store_true", help="every module of the language")
    p_install.add_argument("--dry-run", action="store_true")
    p_install.add_argument("--force", action="store_true", help="overwrite a copy the kit does not recognise")
    p_status = sub.add_parser("status", help="the state of the kit copies in a service")
    p_status.add_argument("dir", type=Path)
    p_status.add_argument("--json", action="store_true")
    p_build = sub.add_parser("build", help="refresh kit.json from the sources (maintainers)")
    p_build.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        changed = build(args.check)
        print(("kit.json is out of date: " if args.check else "rebuilt: ") + ", ".join(changed) if changed else "kit.json is up to date")
        return 1 if (changed and args.check) else 0
    if args.cmd == "status":
        report = status(args.dir)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for f in report["files"]:
                print("%-9s %s%s" % (f["state"], f["file"], " (%s)" % f["version"] if f["state"] == "older" else ""))
            for m in report["missing"]:
                print("missing   %s, which %s imports" % (m["needs"], m["file"]))
            if not report["files"]:
                print("no kit module in %s" % args.dir)
        bad = report["missing"] or any(f["state"] != "current" for f in report["files"])
        return 1 if bad else 0
    lang = LANGS[args.lang]
    known = [e["module"] for e in load_manifest()[lang]]
    modules = known if args.all else args.module
    unknown = [m for m in modules if m not in known]
    if unknown:
        print("no such %s kit module: %s (kit.json lists %s)" % (lang, ", ".join(unknown), ", ".join(known)), file=sys.stderr)
        return 2
    result = install(args.dir, lang, modules, args.dry_run, args.force)
    for name in result["copied"]:
        print(("would copy " if args.dry_run else "copied     ") + name)
    for name in result["kept"]:
        print("current    " + name)
    for name in result["refused"]:
        print("refused    %s: the copy there is not one the kit released; --force overwrites it" % name)
    return 1 if result["refused"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
