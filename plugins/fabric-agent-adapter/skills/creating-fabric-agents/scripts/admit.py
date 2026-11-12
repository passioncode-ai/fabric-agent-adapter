#!/usr/bin/env python3
"""The admission check a new agent passes before it runs (FAA-271, North Star G27, the adapter's part): one command
that chains the checks this plugin ships and reports each as PASS, FAIL or NOT_RUN.

    python3 admit.py <project-root> [--service ID[.INSTANCE]] [--services-dir DIR] [--template FOLDER ...]
                     [--private-terms FILE] [--json]

1. `source`: adapting-projects-to-fabric's `fabric_source_check.py check <project-root>`: no instance data in what
   Git would commit (exit 1 a finding, 2 a file not read; both are no admission).
2. `probe`: building-fabric-services' `check_service.py <service>` with `--service`: the running service against
   fabric-service/0.1; NOT_RUN for an agent that is no service.
3. `template`: this skill's `template_check.py` (strict) on each `--template` folder; NOT_RUN with none.
4. `private-terms`: the tracked files against the operator's private-terms list (the organization's rule P1:
   `--private-terms`, else `$PASSIONCODE_PRIVATE_TERMS`, else `~/.config/passioncode/private-terms.txt`); NOT_RUN where
   there is no list, which is not a pass.

It reads only and writes nothing; it never prints a value a check found, a term of the list or a line holding one (the
checks it runs print paths, lines and kinds). Exit 0: no FAIL and the source check read every file; 1: a FAIL; 2: a
usage error or a check that could not run. Who runs it and when (Observatory's security role) is not decided here.
Standard library only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Dict, List, Optional

SKILLS = Path(__file__).resolve().parent.parent.parent
SOURCE_CHECK = SKILLS / "adapting-projects-to-fabric/scripts/fabric_source_check.py"
PROBE = SKILLS / "building-fabric-services/scripts/check_service.py"
TEMPLATE_CHECK = Path(__file__).resolve().parent / "template_check.py"
PRIVATE_TERMS_ENV = "PASSIONCODE_PRIVATE_TERMS"
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def _run(command: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, "-B"] + command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _result(step: str, verdict: str, evidence: str, lines: Optional[List[str]] = None) -> Dict[str, object]:
    return {"step": step, "verdict": verdict, "evidence": evidence, "lines": lines or []}


def source_step(root: Path) -> Dict[str, object]:
    done = _run([str(SOURCE_CHECK), "check", str(root)])
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else (done.stderr.strip().splitlines() or ["no output"])[-1]
    if done.returncode == 0:
        return _result("source", "PASS", summary)
    if done.returncode == 1:
        return _result("source", "FAIL", summary, lines[:-1])
    return _result("source", "NOT_RUN", "the source check did not read every file or could not run: %s" % summary,
                   lines[:-1])


def probe_step(service: Optional[str], services_dir: Optional[str]) -> Dict[str, object]:
    if not service:
        return _result("probe", "NOT_RUN", "no --service: an agent that is no service has no descriptor to probe")
    command = [str(PROBE), service, "--json"] + (["--services-dir", services_dir] if services_dir else [])
    done = _run(command)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        reason = (done.stderr.strip().splitlines() or ["no report"])[-1]
        return _result("probe", "FAIL", "the probe gave no report for %s: %s" % (service, reason))
    failed = [r for r in report.get("results", []) if r.get("verdict") == "FAIL"]
    not_run = sum(r.get("verdict") == "NOT_RUN" for r in report.get("results", []))
    evidence = "%d rule(s), %d FAIL, %d NOT_RUN" % (len(report.get("results", [])), len(failed), not_run)
    return _result("probe", "FAIL" if failed else "PASS", evidence, ["%s: %s" % (r["rule"], r["evidence"]) for r in failed])


def template_step(folders: List[str]) -> Dict[str, object]:
    if not folders:
        return _result("template", "NOT_RUN", "no --template folder named")
    done = _run([str(TEMPLATE_CHECK), "--json"] + folders)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        return _result("template", "FAIL", "the template check gave no report (exit %d)" % done.returncode)
    errors = ["%s: %s %s: %s" % (folder, f["file"], f["path"], f["message"])
              for folder, findings in report.get("folders", {}).items() for f in findings if f.get("level") == "error"]
    return _result("template", "PASS" if report.get("ok") else "FAIL",
                   "%d folder(s), %d error(s)" % (len(folders), len(errors)), errors)


def _terms_file(named: Optional[str]) -> Path:
    named = named or os.environ.get(PRIVATE_TERMS_ENV)
    return Path(named).expanduser() if named else Path.home() / ".config/passioncode/private-terms.txt"


def _files(root: Path) -> List[str]:
    if (root / ".git").exists():
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, check=False)
        if listed.returncode == 0:
            return sorted({rel for rel in listed.stdout.decode("utf-8", "replace").split("\0") if rel})
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and not SKIP.intersection(p.relative_to(root).parts))


def private_terms_step(root: Path, named: Optional[str]) -> Dict[str, object]:
    path = _terms_file(named)
    if not path.is_file():
        return _result("private-terms", "NOT_RUN", "no private-terms list on this machine (set %s): not a pass"
                       % PRIVATE_TERMS_ENV)
    lines = path.read_text(encoding="utf-8").splitlines()
    terms = sorted({t.strip() for t in lines if t.strip() and not t.strip().startswith("#")}, key=len, reverse=True)
    if not terms:
        return _result("private-terms", "PASS", "the list holds no term")
    pattern = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![A-Za-z0-9])",
                         re.IGNORECASE)
    hits: List[str] = []
    files = _files(root)
    for rel in files:
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        found = [str(n) for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1) if pattern.search(line)]
        if found:
            hits.append("%s: line%s %s" % (rel, "s" if len(found) > 1 else "", ", ".join(found)))
    return _result("private-terms", "FAIL" if hits else "PASS",
                   "%d file(s) read, %d naming a term of the list (paths and lines only)" % (len(files), len(hits)), hits)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="admit.py", description="The admission check a new agent passes before it runs.")
    parser.add_argument("root", help="the agent's project root")
    parser.add_argument("--service", help="the service to probe, ID or ID.INSTANCE")
    parser.add_argument("--services-dir", help="the services folder the probe reads (default: Fabric's)")
    parser.add_argument("--template", action="append", default=[], metavar="FOLDER", help="a template folder to check")
    parser.add_argument("--private-terms", metavar="FILE", help="the operator's private-terms list")
    parser.add_argument("--json", action="store_true", help="one JSON object: steps, admitted")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print("admit.py: %s is not a folder" % root, file=sys.stderr)
        return 2
    steps = [source_step(root), probe_step(args.service, args.services_dir), template_step(args.template),
             private_terms_step(root, args.private_terms)]
    failed = any(s["verdict"] == "FAIL" for s in steps)
    source_ran = steps[0]["verdict"] != "NOT_RUN"
    admitted = not failed and source_ran
    if args.json:
        print(json.dumps({"steps": steps, "admitted": admitted}, indent=2, ensure_ascii=False))
    else:
        for step in steps:
            print("%-8s %-14s %s" % (step["verdict"], step["step"], step["evidence"]))
            for line in step["lines"]:  # type: ignore[union-attr]
                print("         %s" % line)
        print("admitted" if admitted else "not admitted")
    return 1 if failed else (0 if source_ran else 2)


if __name__ == "__main__":
    raise SystemExit(main())
