#!/usr/bin/env python3
"""A support agent on the service kit: it answers one inbound question from a knowledge file, or hands it to a person.

    support_agent.py answer --config config.json --message-id m-1 --text "How do I reset my password?"

For each message it:

1. returns the decision it already made for that message id (idempotent: a repeat costs nothing and never sends a
   second reply);
2. finds the knowledge entries the question shares words with; none found is a handoff (`no-knowledge`);
3. drafts a reply through fabric_openrouter (its own key, the spend ceiling, a usage receipt per call, a fallback of
   another vendor); no answer, the ceiling or a refused key is a handoff (`model:<kind>`);
4. accepts the draft only when code proves it: it cites at least one entry, every cited entry was given to it, it
   carries no em dash (U+2014) and no dash substitute, it is written in the question's script, and it fits the length
   limit. Anything else is a handoff, with the failed checks named;
5. records the decision (0600, atomic) and, for a handoff, appends it to the outbox the operator's channel reads.

What the agent does not do: send the reply anywhere (the service that calls it owns its channel), judge facts with a
model, or answer outside the knowledge file. The model's text is data: a citation it invents fails the check.

The kit modules (fabric_openrouter and its closure) sit beside this file in a service
(`fabric_kit.py install <dir> --module fabric_openrouter`); in this repository they are read from ../../scripts.
Standard library only. FAA-65 REQ-09.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

try:
    import fabric_openrouter
except ImportError:  # in the adapter's repository: the kit is two folders up
    sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))
    import fabric_openrouter
import fabric_paths
import fabric_usage

EM_DASH = "\u2014"
_DASHES = re.compile(r"\u2014|--|(?<=\w) [-\u2013] (?=\w)")
_CITATION = re.compile(r"\[KB:([A-Za-z0-9][A-Za-z0-9._-]{0,63})\]")
_WORD = re.compile(r"\w+", re.UNICODE)
_URL = re.compile(r"https?://\S+")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
SCRIPTS = (
    ("latin", ((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0x1E00, 0x1EFF))),
    ("cyrillic", ((0x400, 0x52F),)),
    ("greek", ((0x370, 0x3FF),)),
    ("hebrew", ((0x590, 0x5FF),)),
    ("arabic", ((0x600, 0x6FF), (0x750, 0x77F))),
    ("devanagari", ((0x900, 0x97F),)),
    ("thai", ((0xE00, 0xE7F),)),
    ("cjk", ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF))),
)
STOPWORDS = frozenset("a an and are as at be by can do does for from how i in is it my of on or the to what when "
                      "where which who why will with you your и в во на не что как я мой моя мне с по для из к "
                      "у о а но ли же это".split())


class RecipeError(Exception):
    pass


def script_of(text: str) -> Optional[str]:
    """The script most of a text's letters are written in (citations and URLs left out), or None without letters."""
    counts: Dict[str, int] = {}
    for ch in _URL.sub(" ", _CITATION.sub(" ", text)):
        code = ord(ch)
        for name, ranges in SCRIPTS:
            if any(lo <= code <= hi for lo, hi in ranges):
                counts[name] = counts.get(name, 0) + 1
                break
    return max(counts, key=lambda k: (counts[k], k)) if counts else None


def words(text: str) -> set:
    return {w for w in (m.lower() for m in _WORD.findall(text)) if len(w) > 1 and w not in STOPWORDS}


class Knowledge:
    """Entries `{id, question, answer, tags?}` from a JSON file (`{"entries": [...]}`); ids are unique."""

    def __init__(self, entries: List[Mapping[str, Any]]):
        self.entries: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not _ID.fullmatch(entry["id"]):
                raise RecipeError("every knowledge entry has an id of letters, digits, '.', '_', ':' or '-'")
            if not isinstance(entry.get("answer"), str) or not entry["answer"].strip():
                raise RecipeError("knowledge entry %s has no answer" % entry["id"])
            if entry["id"] in self.entries:
                raise RecipeError("knowledge entry %s appears twice" % entry["id"])
            self.entries[entry["id"]] = dict(entry)

    @classmethod
    def load(cls, path: Path) -> "Knowledge":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("entries", []) if isinstance(data, dict) else [])

    def lookup(self, question: str, limit: int = 3) -> List[Dict[str, Any]]:
        """The entries sharing the most words with the question (its words against each entry's question, tags and
        answer), best first, ties by id; entries sharing none are left out."""
        asked = words(question)
        scored = []
        for entry in self.entries.values():
            text = " ".join([str(entry.get("question", "")), " ".join(map(str, entry.get("tags", []))),
                             str(entry["answer"])])
            score = len(asked & words(text))
            if score:
                scored.append((-score, entry["id"], entry))
        return [entry for _, _, entry in sorted(scored)[:limit]]


def check_reply(draft: str, question: str, given: List[str], *, max_chars: int) -> Dict[str, Any]:
    """What code can prove about a draft: `{ok, problems, citations, reply}`; `reply` is the text without markers."""
    problems = []
    cited = list(dict.fromkeys(_CITATION.findall(draft)))
    if not cited:
        problems.append("no-citation")
    unknown = [c for c in cited if c not in given]
    if unknown:
        problems.append("unknown-citation:" + ",".join(unknown))
    if _DASHES.search(draft):
        problems.append("dash")
    reply = re.sub(r"[ \t]+", " ", _CITATION.sub("", draft)).replace(" .", ".").replace(" ,", ",").strip()
    if not reply:
        problems.append("empty")
    elif len(reply) > max_chars:
        problems.append("too-long")
    wanted, written = script_of(question), script_of(reply)
    if wanted and written and wanted != written:
        problems.append("script:%s-not-%s" % (written, wanted))
    return {"ok": not problems, "problems": problems, "citations": cited, "reply": reply}


SYSTEM = (
    "You are a support agent. Answer the customer's question using only the knowledge entries given below. "
    "Cite every entry you rely on as [KB:<id>] right after the sentence it supports. If the entries do not answer "
    "the question, reply exactly: HANDOFF. Write in the language of the question. Write plainly and briefly. "
    "Never use an em dash or any dash between clauses: use a full stop, a comma, a colon or parentheses."
)


def build_messages(question: str, entries: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    kb = "\n\n".join("[KB:%s]\nQ: %s\nA: %s" % (e["id"], e.get("question", ""), e["answer"]) for e in entries)
    return [{"role": "system", "content": SYSTEM + "\n\nKnowledge entries:\n\n" + kb},
            {"role": "user", "content": question}]


class SupportAgent:
    def __init__(self, *, knowledge: Knowledge, client: Any, model: str, fallback: str, state_dir: Path,
                 max_tokens: int = 600, max_chars: int = 1200, lookup_limit: int = 3,
                 on_handoff: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.knowledge, self.client = knowledge, client
        self.model, self.fallback = model, fallback
        self.state_dir = Path(state_dir)
        self.max_tokens, self.max_chars, self.lookup_limit = max_tokens, max_chars, lookup_limit
        self.on_handoff = on_handoff or self._outbox
        self._lock = threading.Lock()

    @property
    def decisions_file(self) -> Path:
        return self.state_dir / "decisions.json"

    def _decisions(self) -> Dict[str, Any]:
        try:
            return json.loads(self.decisions_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _outbox(self, decision: Dict[str, Any]) -> None:
        fabric_paths.ensure_private_dir(self.state_dir)
        line = json.dumps(decision, ensure_ascii=False, separators=(",", ":")) + "\n"
        fd = os.open(str(self.state_dir / "handoffs.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def answer(self, message_id: str, text: str, *, task_run_id: Optional[str] = None) -> Dict[str, Any]:
        """The decision for one message: `{messageId, action: reply|handoff, reply?, citations, reasons, costUsd}`."""
        if not isinstance(message_id, str) or not _ID.fullmatch(message_id):
            raise RecipeError("message id: letters, digits, '.', '_', ':' or '-', up to 128")
        if not isinstance(text, str) or not text.strip():
            raise RecipeError("the message has no text")
        with self._lock:  # one decision per message id, in this process; the service's instance lock covers others
            done = self._decisions().get(message_id)
            if done is not None:
                return dict(done, repeated=True)
            decision = self._decide(message_id, text, task_run_id)
            if decision["action"] == "handoff":  # before the decision is saved: a crash repeats a handoff, never loses one
                self.on_handoff(dict(decision, question=text))
            decisions = self._decisions()
            decisions[message_id] = decision
            fabric_paths.ensure_private_dir(self.state_dir)
            fabric_paths.atomic_write(self.decisions_file,
                                      json.dumps(decisions, ensure_ascii=False, indent=1).encode("utf-8"))
        return dict(decision, repeated=False)

    def _decide(self, message_id: str, text: str, task_run_id: Optional[str]) -> Dict[str, Any]:
        base = {"messageId": message_id, "citations": [], "costUsd": None}
        entries = self.knowledge.lookup(text, self.lookup_limit)
        if not entries:
            return dict(base, action="handoff", reasons=["no-knowledge"])
        try:
            got = self.client.chat(build_messages(text, entries), model=self.model, fallback=self.fallback,
                                   max_tokens=self.max_tokens, temperature=0, task_run_id=task_run_id)
        except fabric_openrouter.OpenRouterError as err:
            return dict(base, action="handoff", reasons=["model:" + err.kind])
        base["costUsd"] = got["receipt"].get("costUsd")
        if got["content"].strip() == "HANDOFF":
            return dict(base, action="handoff", reasons=["model-unsure"])
        checked = check_reply(got["content"], text, [e["id"] for e in entries], max_chars=self.max_chars)
        if not checked["ok"]:
            return dict(base, action="handoff", reasons=checked["problems"], citations=checked["citations"])
        return dict(base, action="reply", reply=checked["reply"], citations=checked["citations"], reasons=[])


def from_config(config_path: Path, **overrides: Any) -> SupportAgent:
    """An agent from a config file (see config.example.json): paths are relative to the config's folder."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    home = Path(config_path).resolve().parent
    state = (home / config.get("stateDir", "state")).resolve()
    prices = config.get("prices") or {}
    if config.get("catalog"):
        prices = dict(fabric_openrouter.prices_from_catalog(json.loads((home / config["catalog"]).read_text("utf-8"))),
                      **prices)
    client = fabric_openrouter.Client(ceiling_usd=float(config["ceilingUsd"]), window=config.get("window", "day"),
                                      ledger=fabric_usage.JsonlUsageLedger(state / "usage.jsonl"), prices=prices,
                                      key_env=config.get("keyEnv", "OPENROUTER_API_KEY"),
                                      project_id=config.get("projectId"), **overrides)
    return SupportAgent(knowledge=Knowledge.load(home / config["knowledge"]), client=client, model=config["model"],
                        fallback=config["fallback"], state_dir=state, max_tokens=int(config.get("maxTokens", 600)),
                        max_chars=int(config.get("maxChars", 1200)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("answer", help="decide one message and print the decision as JSON")
    ask.add_argument("--config", required=True, type=Path)
    ask.add_argument("--message-id", required=True)
    ask.add_argument("--text", help="the question; read from stdin when absent")
    args = parser.parse_args(argv)
    try:
        agent = from_config(args.config)
        text = args.text if args.text is not None else sys.stdin.read()
        decision = agent.answer(args.message_id, text)
    except (RecipeError, fabric_openrouter.OpenRouterError, OSError, ValueError, KeyError) as err:
        print(json.dumps({"error": type(err).__name__, "message": str(err)}), file=sys.stderr)
        return 1
    print(json.dumps(decision, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
