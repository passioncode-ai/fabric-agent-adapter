#!/usr/bin/env python3
"""Run each skill's scenario evals (test/evals/<skill>/scenarios.json) against a real client, judged by a second model
of another family (FAA-339).

Opt-in, like run_evals.py: it calls models only when FABRIC_REAL_CLIENT=1, `claude` is on PATH and the judge's key is
in OPENROUTER_API_KEY (put there for the one command by Observatory, never typed or written down):

  FABRIC_REAL_CLIENT=1 python "$(project-observatory full-path)/tools/use_secret.py" run --vault-only --env local \\
      fabric-agent-adapter OPENROUTER_API_KEY -- python3 test/evals/run_scenarios.py --skill working-with-fabric \\
      --scenario a-session-started-on-a-board-request --record docs/evidence/evals/<date>-scenario-run

Otherwise it prints NOT_RUN and exits 2, so a skipped run never reads as a pass. Hosted CI holds no model credential.

What one case measures: the agent (`claude -p`, the model named by --model) runs with the skill loaded as its
instructions, in a copy of the skill's folder, with read-only tools (Read, Grep, Glob) and no MCP server, no setting
source and no saved session, so it can follow the skill's references and act on nothing. It answers the scenario's
request by stating, in order, what it would do: each tool it would call, with its arguments, and what it would tell the
person. The judge (an OpenRouter model of another family, --judge-model) reads the scenario, its expectations and that
answer, and rules on each expectation with a quote from the answer; an expectation without a quote is not met. A
scenario passes when every expectation is met; a failed call is a failed case, named, never a pass.

Exit: 0 every scenario run passed; 1 one failed; 2 not run.
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
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "test/evals"
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
JUDGE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_JUDGE = "moonshotai/kimi-k3.1-pro"  # another family than the Claude agent (wiki synthesis/llm-models.md)
AGENT_SYSTEM = (
    "You are a coding agent in a session where the skill below is loaded; follow it. The working folder holds the skill's "
    "files: read its references when the skill points to them. You cannot run anything in this session, so do not claim "
    "you ran, sent or changed anything. Answer the request by stating, in order, what you would do: each tool or "
    "command you would call, with its arguments, what you would check before acting, and the words you would say to "
    "the person. Be concrete and complete.\n\n")
JUDGE_SYSTEM = (
    "You judge whether an agent's stated behaviour meets each expectation of a scenario. Rule on every expectation by "
    "its index: met is true only when the answer states that behaviour (or a stricter one), and evidence is a short "
    "verbatim quote from the answer that shows it; with no such quote, met is false and evidence is empty. An answer "
    "that claims to have run something it could not is not evidence. Reply with JSON only: "
    '{"verdicts": [{"index": 0, "met": true, "evidence": "..."}]}')

Agent = Callable[[str, str, Path], str]
Judge = Callable[[str], str]


def skill_text(skill: str) -> str:
    """The skill's SKILL.md without its front matter: the instructions a host loads."""
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return text.strip()


def judge_prompt(scenario: Dict[str, Any], answer: str) -> str:
    expected = "\n".join("%d. %s" % (index, item) for index, item in enumerate(scenario["expected"]))
    return ("Scenario request:\n<<<\n%s\n>>>\n\nExpectations:\n%s\n\nThe agent's answer:\n<<<\n%s\n>>>"
            % (scenario["request"], expected, answer))


def parse_verdicts(text: str, count: int) -> List[Dict[str, Any]]:
    """The judge's verdicts, one per expectation; a missing, malformed or quote-less one is not met."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body[body.find("{"):] if "{" in body else body
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end < start:
        raise ValueError("the judge answered no JSON object")
    doc = json.loads(body[start:end + 1])
    found: Dict[int, Dict[str, Any]] = {}
    for item in doc.get("verdicts") or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int) and 0 <= item["index"] < count:
            evidence = item.get("evidence") if isinstance(item.get("evidence"), str) else ""
            found[item["index"]] = {"index": item["index"], "met": item.get("met") is True and bool(evidence.strip()),
                                    "evidence": evidence.strip()[:300]}
    return [found.get(index, {"index": index, "met": False, "evidence": ""}) for index in range(count)]


def run_case(skill: str, scenario: Dict[str, Any], agent: Agent, judge: Judge) -> Dict[str, Any]:
    result: Dict[str, Any] = {"skill": skill, "id": scenario["id"], "expected": scenario["expected"]}
    workdir = Path(tempfile.mkdtemp(prefix="fabric-scenario-"))
    try:
        shutil.copytree(SKILLS / skill, workdir / skill, ignore=shutil.ignore_patterns("__pycache__"))
        answer = agent(AGENT_SYSTEM + skill_text(skill), scenario["request"], workdir / skill)
        result["answer"] = answer
        result["verdicts"] = parse_verdicts(judge(judge_prompt(scenario, answer)), len(scenario["expected"]))
        result["error"] = None
    except Exception as exc:  # a failed call is a failed case, named, never a pass
        result.setdefault("answer", "")
        result["verdicts"] = []
        result["error"] = "%s: %s" % (exc.__class__.__name__, str(exc)[:200])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    met = sum(v["met"] for v in result["verdicts"])
    result["met"] = "%d/%d" % (met, len(scenario["expected"]))
    result["passed"] = result["error"] is None and met == len(scenario["expected"])
    return result


def run_all(cases: List[Dict[str, Any]], agent: Agent, judge: Judge, jobs: int = 2) -> List[Dict[str, Any]]:
    results: List[Optional[Dict[str, Any]]] = [None] * len(cases)
    work: "queue.Queue[int]" = queue.Queue()
    for index in range(len(cases)):
        work.put(index)

    def worker() -> None:
        while True:
            try:
                index = work.get_nowait()
            except queue.Empty:
                return
            results[index] = run_case(cases[index]["skill"], cases[index]["scenario"], agent, judge)

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(jobs, len(cases))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [r for r in results if r is not None]


def claude_agent(model: str, timeout: float = 600.0) -> Agent:
    """`claude -p` with read-only tools in the skill's copy: no MCP, no settings, no saved session."""
    def call(system: str, request: str, folder: Path) -> str:
        argv = ["claude", "-p", request, "--model", model, "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob",
                "--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": {}}), "--setting-sources", "",
                "--no-session-persistence", "--system-prompt", system, "--output-format", "json"]
        done = subprocess.run(argv, cwd=str(folder), capture_output=True, text=True, timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError("claude exited %d" % done.returncode)
        payload = json.loads(done.stdout)
        with lock:
            call.cost += float(payload.get("total_cost_usd") or 0)  # type: ignore[attr-defined]
        return str(payload.get("result") or "")

    lock = threading.Lock()
    call.cost = 0.0  # type: ignore[attr-defined]
    return call


def openrouter_judge(model: str, key: str, timeout: float = 300.0) -> Judge:
    """One chat completion per case; the key stays in this process's memory."""
    def call(prompt: str) -> str:
        body = json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                           "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}]})
        request = urllib.request.Request(JUDGE_URL, data=body.encode("utf-8"), method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/passioncode-ai/fabric-agent-adapter", "X-Title": "fabric-agent-adapter evals"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as answer:
                    payload = json.loads(answer.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503) or attempt == 2:
                    raise RuntimeError("the judge answered HTTP %d" % exc.code) from None
                time.sleep(5 * (attempt + 1))
        usage = payload.get("usage") or {}
        with lock:
            call.cost += float(usage.get("cost") or 0)  # type: ignore[attr-defined]
        return str(payload["choices"][0]["message"]["content"] or "")

    lock = threading.Lock()
    call.cost = 0.0  # type: ignore[attr-defined]
    return call


def select(skills: Optional[List[str]], ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    names = skills or sorted(p.name for p in EVALS.iterdir() if (p / "scenarios.json").is_file())
    cases = []
    for skill in names:
        doc = json.loads((EVALS / skill / "scenarios.json").read_text(encoding="utf-8"))
        cases += [{"skill": skill, "scenario": s} for s in doc["scenarios"] if not ids or s["id"] in ids]
    missing = sorted(set(ids or ()) - {c["scenario"]["id"] for c in cases})
    if missing:
        raise SystemExit("no scenario named %s in %s" % (", ".join(missing), ", ".join(names)))
    return cases


def record(folder: Path, report: Dict[str, Any]) -> None:
    """The run's JSON and a Markdown summary: every scenario, its verdicts and quotes, the models and the cost."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Scenario run", "", "Agent `%s`, judge `%s`, %s; adapter %s; cost $%.4f (agent) + $%.4f (judge)." % (
        report["agentModel"], report["judgeModel"], report["at"], report["version"], report["agentCostUsd"],
        report["judgeCostUsd"]), "", "| Skill | Scenario | Met | Result |", "|---|---|---|---|"]
    lines += ["| %s | `%s` | %s | %s |" % (r["skill"], r["id"], r["met"], "pass" if r["passed"] else
                                           "error: " + r["error"] if r["error"] else "fail") for r in report["results"]]
    for r in report["results"]:
        lines += ["", "## %s" % r["id"], ""]
        for verdict in r["verdicts"]:
            lines.append("- %s %s%s" % ("met:" if verdict["met"] else "NOT met:", r["expected"][verdict["index"]],
                                        " (\"%s\")" % verdict["evidence"].replace("\n", " ") if verdict["evidence"] else ""))
    (folder / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None, agent: Optional[Agent] = None, judge: Optional[Judge] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill", action="append", help="a skill whose scenarios run; repeat; default every skill")
    parser.add_argument("--scenario", action="append", help="one scenario id; repeat; default every one")
    parser.add_argument("--model", default="sonnet", help="the agent's model (claude -p --model)")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE, help="the judge's OpenRouter model, of another family")
    parser.add_argument("--jobs", type=int, default=2, help="scenarios in flight at once")
    parser.add_argument("--record", type=Path, help="write run.json and README.md into this folder")
    args = parser.parse_args(argv)
    if agent is None or judge is None:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if os.environ.get("FABRIC_REAL_CLIENT") != "1" or not shutil.which("claude") or not key:
            print("NOT_RUN: set FABRIC_REAL_CLIENT=1, put claude on PATH and run under use_secret.py with the judge's "
                  "OPENROUTER_API_KEY; this runner calls two models and spends.")
            return 2
        agent = agent or claude_agent(args.model)
        judge = judge or openrouter_judge(args.judge_model, key)
    cases = select(args.skill, args.scenario)
    results = run_all(cases, agent, judge, jobs=args.jobs)
    for r in results:
        print("%s %s/%s: %s met%s" % ("PASS" if r["passed"] else "FAIL", r["skill"], r["id"], r["met"],
                                      " (%s)" % r["error"] if r["error"] else ""))
        for verdict in r["verdicts"]:
            if not verdict["met"]:
                print("  not met: %s" % r["expected"][verdict["index"]])
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    report = {"agentModel": args.model, "judgeModel": args.judge_model, "version": version,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results,
              "agentCostUsd": round(float(getattr(agent, "cost", 0.0)), 6),
              "judgeCostUsd": round(float(getattr(judge, "cost", 0.0)), 6)}
    print("%d/%d passed; cost $%.4f + $%.4f" % (sum(r["passed"] for r in results), len(results), report["agentCostUsd"],
                                               report["judgeCostUsd"]))
    if args.record:
        record(args.record, report)
    return 0 if results and all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
