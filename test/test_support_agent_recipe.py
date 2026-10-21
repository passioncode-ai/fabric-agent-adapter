"""FAA-65 REQ-09: the support-agent recipe over a fake model (fabric_openrouter with a scripted transport). No test opens
the network or holds a real key."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/support-agent"
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("support_agent", RECIPE / "support_agent.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)
fo = sa.fabric_openrouter  # the very module the recipe imported

KEY = "sk-or-v1-test-only-not-a-key"
PRICES = {"a/one": {"prompt": 0.000001, "completion": 0.00001}, "b/two": {"prompt": 0.000002, "completion": 0.00002}}


def model_says(*contents, status=200):
    """A transport that answers each call with the next content (None: a 503)."""
    queue = list(contents)
    calls = []

    def transport(method, url, headers, body, timeout_s, max_bytes):
        calls.append(json.loads(body))
        content = queue.pop(0)
        if content is None:
            return 503, {}, b"{}"
        answer = {"model": "a/one", "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                  "usage": {"prompt_tokens": 50, "completion_tokens": 20, "cost": 0.0003}}
        return status, {}, json.dumps(answer).encode()
    transport.calls = calls
    return transport


class Recipe(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="support-agent-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.knowledge = sa.Knowledge.load(RECIPE / "knowledge.example.json")

    def agent(self, transport, *, ceiling=1.0, **kwargs):
        client = fo.Client(ceiling_usd=ceiling, ledger=sa.fabric_usage.JsonlUsageLedger(self.dir / "usage.jsonl"),
                           prices=PRICES, environ={"OPENROUTER_API_KEY": KEY}, transport=transport,
                           sleep=lambda s: None)
        handoffs = []
        agent = sa.SupportAgent(knowledge=self.knowledge, client=client, model="a/one", fallback="b/two",
                                state_dir=self.dir, on_handoff=handoffs.append, **kwargs)
        return agent, handoffs

    def test_a_grounded_reply(self):
        model = model_says("Open Settings, then Account, then Reset password [KB:password-reset].")
        agent, handoffs = self.agent(model)
        got = agent.answer("m-1", "How do I reset my password?")
        self.assertEqual(got["action"], "reply")
        self.assertEqual(got["reply"], "Open Settings, then Account, then Reset password.")
        self.assertEqual(got["citations"], ["password-reset"])
        self.assertAlmostEqual(got["costUsd"], 0.0003)
        self.assertEqual(handoffs, [])
        sent = model.calls[0]
        self.assertIn("[KB:password-reset]", sent["messages"][0]["content"])
        self.assertEqual(sent["temperature"], 0)
        receipts = [json.loads(l) for l in (self.dir / "usage.jsonl").read_text().splitlines()]
        self.assertEqual(len(receipts), 1, "one usage receipt for the one call")

    def test_idempotent_per_message(self):
        model = model_says("Open Settings [KB:password-reset].")
        agent, _ = self.agent(model)
        first = agent.answer("m-1", "How do I reset my password?")
        again = agent.answer("m-1", "How do I reset my password?")
        self.assertEqual(len(model.calls), 1, "a repeat never calls the model again")
        self.assertTrue(again["repeated"])
        self.assertEqual({k: v for k, v in again.items() if k != "repeated"},
                         {k: v for k, v in first.items() if k != "repeated"})
        fresh, _ = self.agent(model_says())
        self.assertEqual(fresh.answer("m-1", "anything")["reply"], first["reply"], "the decision survives a restart")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.dir / "decisions.json").stat().st_mode), 0o600)

    def test_handoffs(self):
        cases = [
            ("no knowledge", "What is the weather on Mars?", [], ["no-knowledge"]),
            ("the model is unsure", "How do I reset my password?", ["HANDOFF"], ["model-unsure"]),
            ("no citation", "How do I reset my password?", ["Open Settings."], ["no-citation"]),
            ("an invented citation", "How do I reset my password?", ["Open Settings [KB:made-up]."],
             ["unknown-citation:made-up"]),
            ("an entry it was not given", "How do I reset my password?", ["Refunds [KB:refund-window]."],
             ["unknown-citation:refund-window"]),
            ("an em dash", "How do I reset my password?", ["Open Settings \u2014 then Account [KB:password-reset]."],
             ["dash"]),
            ("a horizontal bar", "How do I reset my password?", ["Open Settings \u2015 then Account [KB:password-reset]."],
             ["dash"]),
            ("a spaced hyphen", "How do I reset my password?", ["Open Settings - then Account [KB:password-reset]."],
             ["dash"]),
            ("another script", "Как сбросить пароль?", ["Open Settings, then Account [KB:password-reset-ru]."],
             ["script:latin-not-cyrillic"]),
            ("the model fails twice on both", "How do I reset my password?", [None, None, None, None], ["model:failed"]),
        ]
        for name, question, said, reasons in cases:
            with self.subTest(name):
                shutil.rmtree(self.dir, ignore_errors=True)
                agent, handoffs = self.agent(model_says(*said))
                got = agent.answer("m-" + str(abs(hash(name))), question)
                self.assertEqual((got["action"], got["reasons"]), ("handoff", reasons))
                self.assertEqual(len(handoffs), 1)
                self.assertEqual(handoffs[0]["question"], question)

    def test_the_ceiling_hands_off_without_a_call(self):
        model = model_says("unused")
        agent, handoffs = self.agent(model, ceiling=0.0)
        got = agent.answer("m-1", "How do I reset my password?")
        self.assertEqual(got["reasons"], ["model:ceiling"])
        self.assertEqual(model.calls, [])

    def test_too_long_and_a_reply_in_russian(self):
        agent, _ = self.agent(model_says("x" * 50 + " [KB:password-reset]"), max_chars=20)
        self.assertEqual(agent.answer("m-1", "How do I reset my password?")["reasons"], ["too-long"])
        shutil.rmtree(self.dir, ignore_errors=True)
        agent, _ = self.agent(model_says("Откройте Настройки, затем Аккаунт [KB:password-reset-ru]."))
        got = agent.answer("m-2", "Как сбросить пароль?")
        self.assertEqual((got["action"], got["reply"]), ("reply", "Откройте Настройки, затем Аккаунт."))

    def test_a_lone_surrogate_is_not_fatal(self):
        agent, handoffs = self.agent(model_says("Open Settings [KB:password-reset]."))
        got = agent.answer("m-1", "\udcff reset my password")
        self.assertEqual(got["action"], "reply")
        self.assertTrue((self.dir / "decisions.json").read_text(encoding="utf-8"))

    def test_the_default_outbox(self):
        client = fo.Client(ceiling_usd=1.0, ledger=sa.fabric_usage.JsonlUsageLedger(self.dir / "usage.jsonl"),
                           prices=PRICES, environ={"OPENROUTER_API_KEY": KEY}, transport=model_says())
        agent = sa.SupportAgent(knowledge=self.knowledge, client=client, model="a/one", fallback="b/two",
                                state_dir=self.dir)
        agent.answer("m-1", "What is the weather on Mars?")
        rows = [json.loads(l) for l in (self.dir / "handoffs.jsonl").read_text().splitlines()]
        self.assertEqual([(r["messageId"], r["reasons"]) for r in rows], [("m-1", ["no-knowledge"])])

    def test_checks_and_lookup(self):
        self.assertEqual(sa.script_of("Привет, world"), "cyrillic")
        self.assertEqual(sa.script_of("hello [KB:пароль] https://пример.рф"), "latin")
        self.assertIsNone(sa.script_of("123 !?"))
        for text, dash in (("a \u2013 b", True), ("a\u00a0\u2013\u00a0b", True), ("a \u2e3a b", True), ("1 - 2", False),
                           ("well-known", False), ("a - b", True)):
            self.assertEqual(bool(sa._DASHES.search(text)), dash, text)
        ids = [e["id"] for e in self.knowledge.lookup("reset password please")]
        self.assertEqual(ids[0], "password-reset")
        self.assertEqual(self.knowledge.lookup("the of and"), [])
        with self.assertRaises(sa.RecipeError):
            sa.Knowledge([{"id": "a", "answer": "x"}, {"id": "a", "answer": "y"}])
        with self.assertRaises(sa.RecipeError):
            sa.Knowledge([{"id": "bad id", "answer": "x"}])
        agent, _ = self.agent(model_says())
        for bad_id, text in (("", "hi"), ("bad id", "hi"), ("m-1", "  ")):
            with self.assertRaises(sa.RecipeError):
                agent.answer(bad_id, text)

    def test_the_command_line(self):
        config = json.loads((RECIPE / "config.example.json").read_text())
        config.update(knowledge=str(RECIPE / "knowledge.example.json"), stateDir=str(self.dir / "state"))
        (self.dir / "config.json").write_text(json.dumps(config))
        env = dict(os.environ)
        env.pop("OPENROUTER_API_KEY", None)
        out = subprocess.run([sys.executable, "-E", "-s", str(RECIPE / "support_agent.py"), "answer", "--config",
                              str(self.dir / "config.json"), "--message-id", "m-1", "--text", "Mars weather?"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["reasons"], ["no-knowledge"], "no key is needed to hand off")
        out = subprocess.run([sys.executable, "-E", "-s", str(RECIPE / "support_agent.py"), "answer", "--config",
                              str(self.dir / "config.json"), "--message-id", "m-2", "--text", "reset my password"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(json.loads(out.stdout)["reasons"], ["model:config"], "no key: handed off, never a crash")


if __name__ == "__main__":
    unittest.main()
