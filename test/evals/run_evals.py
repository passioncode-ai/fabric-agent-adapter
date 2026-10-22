#!/usr/bin/env python3
"""Run each skill's trigger evals (test/evals/<skill>/triggers.json) against a real client.

Opt-in, like test/test_real_client.py: it calls a model only when FABRIC_REAL_CLIENT=1 and `claude` is on PATH,
and otherwise prints NOT_RUN and exits 2, so a skipped run never reads as a pass. Hosted CI holds no model
credential and does not run it (decision D7 of the 2026-10-22 audit brief).

What one case measures: the client sees the four skills' front matter descriptions (the text a host routes on),
plus "none", and the request; it answers with one name. A positive passes when it names the skill under test, a
negative when it names anything else. So a negative that belongs to a sibling also checks the sibling boundary.
The client runs with no tools, no MCP servers, no setting sources and no saved session, in an empty directory.

Scenario evals (scenarios.json) need a judge of free-form behaviour; this runner does not run them and says so.

  FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill adapting-projects-to-fabric --model haiku
  python3 test/evals/run_evals.py --json result.json ...    write every case and answer as JSON

Exit: 0 every evaluated skill at or above THRESHOLD; 1 one below it; 2 not run.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "test/evals"
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
THRESHOLD = 0.85  # the share of a skill's trigger cases that must pass; below it the run exits 1
NONE = "none"
SYSTEM = ("You route one user request to at most one skill. You never answer the request itself. "
          "Reply with exactly one skill name from the list, or none, and nothing else.")

Client = Callable[[str], str]


def read_description(skill_md: Path) -> str:
    """The `description:` of a SKILL.md front matter, single-line or a folded block (>-)."""
    lines = skill_md.read_text(encoding="utf-8").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("%s has no front matter" % skill_md)
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            value = line[len("description:"):].strip()
            if value not in (">-", ">", "|", "|-"):
                return value.strip("'\"")
            folded = []
            for more in lines[index + 1:]:
                if not more.startswith(" "):
                    break
                folded.append(more.strip())
            return " ".join(folded)
    raise ValueError("%s has no description" % skill_md)


def load_skills(root: Path = SKILLS) -> Dict[str, str]:
    return {path.parent.name: read_description(path) for path in sorted(root.glob("*/SKILL.md"))}


def build_prompt(skills: Dict[str, str], query: str) -> str:
    listing = "\n".join("- %s: %s" % (name, description) for name, description in sorted(skills.items()))
    return ("Skills:\n%s\n- %s: no skill above fits the request.\n\nRequest:\n<<<\n%s\n>>>\n\n"
            "Which one skill should handle this request? Reply with only its name." % (listing, NONE, query))


def parse_answer(text: str, names: List[str]) -> str:
    """The skill the answer names: the first known name in it, longest first so no name hides inside another."""
    lowered = (text or "").strip().lower()
    found = [(lowered.find(name), name) for name in sorted(names, key=len, reverse=True) if name in lowered]
    if found:
        return min(found)[1]
    return NONE


def run_cases(skill: str, queries: List[Dict[str, Any]], skills: Dict[str, str], client: Client,
              jobs: int = 4) -> List[Dict[str, Any]]:
    names = list(skills)
    results: List[Optional[Dict[str, Any]]] = [None] * len(queries)
    work: "queue.Queue[int]" = queue.Queue()
    for index in range(len(queries)):
        work.put(index)

    def worker() -> None:
        while True:
            try:
                index = work.get_nowait()
            except queue.Empty:
                return
            case = queries[index]
            try:
                answer = client(build_prompt(skills, case["query"]))
                error = None
            except Exception as exc:  # a failed call is a failed case, named, never a pass
                answer, error = "", "%s: %s" % (exc.__class__.__name__, exc)
            chosen = parse_answer(answer, names)
            expected = bool(case["shouldTrigger"])
            passed = error is None and ((chosen == skill) if expected else (chosen != skill))
            results[index] = {"query": case["query"], "shouldTrigger": expected, "chosen": chosen,
                              "answer": answer.strip()[:200], "passed": passed, "error": error}

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(jobs, len(queries))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [r for r in results if r is not None]


def summarize(skill: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    positives = [r for r in results if r["shouldTrigger"]]
    negatives = [r for r in results if not r["shouldTrigger"]]
    passed = sum(r["passed"] for r in results)
    rate = passed / len(results) if results else 0.0
    return {"skill": skill, "cases": len(results), "passed": passed, "passRate": round(rate, 4),
            "positivesPassed": "%d/%d" % (sum(r["passed"] for r in positives), len(positives)),
            "negativesPassed": "%d/%d" % (sum(r["passed"] for r in negatives), len(negatives)),
            "errors": sum(1 for r in results if r["error"]), "aboveThreshold": bool(results) and rate >= THRESHOLD}


def claude_client(model: str, timeout: float = 300.0) -> Client:
    """`claude -p` with nothing loaded but the prompt: no tools, no MCP, no settings, no saved session."""
    workdir = tempfile.mkdtemp(prefix="fabric-evals-")

    def call(prompt: str) -> str:
        argv = ["claude", "-p", prompt, "--model", model, "--tools", "", "--strict-mcp-config", "--mcp-config",
                json.dumps({"mcpServers": {}}), "--setting-sources", "", "--no-session-persistence",
                "--system-prompt", SYSTEM, "--output-format", "json"]
        done = subprocess.run(argv, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError("claude exited %d" % done.returncode)
        payload = json.loads(done.stdout)
        call.cost += float(payload.get("total_cost_usd") or 0)  # type: ignore[attr-defined]
        return str(payload.get("result") or "")

    call.cost = 0.0  # type: ignore[attr-defined]
    return call


def main(argv: Optional[List[str]] = None, client: Optional[Client] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill", action="append", help="a skill to evaluate; repeat; default every skill with triggers.json")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--jobs", type=int, default=4, help="cases in flight at once")
    parser.add_argument("--json", type=Path, help="write every case, answer and summary here")
    args = parser.parse_args(argv)
    if client is None:
        if os.environ.get("FABRIC_REAL_CLIENT") != "1" or not shutil.which("claude"):
            print("NOT_RUN: set FABRIC_REAL_CLIENT=1 and put claude on PATH; this runner calls a model and spends.")
            return 2
        client = claude_client(args.model)
    skills = load_skills()
    chosen = args.skill or sorted(p.name for p in EVALS.iterdir() if (p / "triggers.json").is_file())
    report: Dict[str, Any] = {"model": args.model, "threshold": THRESHOLD, "skills": [], "cases": {},
                              "scenarios": "NOT_RUN: scenario evals need a judge of free-form behaviour"}
    failing = False
    for skill in chosen:
        triggers = json.loads((EVALS / skill / "triggers.json").read_text(encoding="utf-8"))
        results = run_cases(skill, triggers["queries"], skills, client, jobs=args.jobs)
        summary = summarize(skill, results)
        report["skills"].append(summary)
        report["cases"][skill] = results
        failing = failing or not summary["aboveThreshold"]
        print("%s: %d/%d passed (%.1f%%; positives %s, negatives %s, errors %d) %s" % (
            skill, summary["passed"], summary["cases"], summary["passRate"] * 100, summary["positivesPassed"],
            summary["negativesPassed"], summary["errors"], "PASS" if summary["aboveThreshold"] else "BELOW %.0f%%" % (THRESHOLD * 100)))
        for result in results:
            if not result["passed"]:
                print("  miss: %s -> %s%s" % (result["query"], result["chosen"], " (%s)" % result["error"] if result["error"] else ""))
    cost = getattr(client, "cost", None)
    if cost is not None:
        report["costUsd"] = round(cost, 6)
        print("cost: $%.4f" % cost)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
