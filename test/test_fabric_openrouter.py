"""FAA-65 REQ-07: fabric_openrouter, on the cases fabric-openrouter.mjs reads too
(test/fixtures/kit-openrouter-cases.json). No test opens the network or holds a real key."""
import json
import threading
import unittest
from pathlib import Path

from test_fabric_service import load  # noqa: E402

fo = load("fabric_openrouter")
fu = load("fabric_usage")

CASES = json.loads((Path(__file__).parent / "fixtures/kit-openrouter-cases.json").read_text(encoding="utf-8"))
NOW = 1792584000.0  # 2026-10-21T12:00:00Z
KEY = "sk-or-v1-test-only-not-a-key"
MESSAGES = [{"role": "user", "content": "hi"}]


class Ledger:
    def __init__(self, receipts=()):
        self.rows = list(receipts)

    def record(self, receipt):
        self.rows.append(receipt)

    def receipts(self):
        return list(self.rows)


def scripted(steps, seen):
    steps = list(steps)

    def transport(method, url, headers, body, timeout_s, max_bytes):
        seen.append({"url": url, "headers": headers, "body": json.loads(body)})
        step = steps.pop(0)
        if step.get("error") == "timeout":
            raise TimeoutError("slow")
        if step.get("error") == "connection":
            raise ConnectionRefusedError("refused")
        raw = step["raw"].encode("utf-8") if "raw" in step else json.dumps(step.get("body", {})).encode("utf-8")
        return step["status"], step.get("headers", {}), raw
    return transport


def client(case, seen, ledger, **extra):
    sleeps, now = [], [0.0]

    def sleep(s):
        sleeps.append(s)
        now[0] += s
    c = fo.Client(ceiling_usd=case.get("ceilingUsd", 1.0), ledger=ledger, prices=dict(CASES["prices"], **case.get("prices", {})),
                  environ={} if case.get("noKey") else {"OPENROUTER_API_KEY": KEY},
                  transport=scripted(case.get("steps", []), seen), sleep=sleep, clock=lambda: now[0],
                  now=lambda: NOW, rand=lambda: 0.5, **extra)
    return c, sleeps


def run(case):
    seen, ledger = [], Ledger(case.get("ledger", []))
    c, sleeps = client(case, seen, ledger)
    try:
        answer = c.chat(MESSAGES, model=case.get("model", "a/one"), fallback=case.get("fallback", "b/two"),
                        max_tokens=100, **case.get("params", {}))
        got = {"content": answer["content"], "model": answer["model"],
               "outcomes": [a["outcome"] for a in answer["attempts"]], "sleeps": sleeps}
    except fo.OpenRouterError as err:
        got = {"error": err.kind, "outcomes": [a["outcome"] for a in err.attempts], "message": str(err)}
    return got, ledger, seen


def same_receipt(test, actual, expected):
    for key, value in expected.items():
        if key == "costUsd" and value is not None:
            test.assertAlmostEqual(actual[key], value, places=12)
        else:
            test.assertEqual(actual.get(key), value, key)


class Cases(unittest.TestCase):
    def test_prompt_bound_and_catalog(self):
        for messages, expected in CASES["promptBound"]:
            self.assertEqual(fo.prompt_tokens_bound(messages), expected)
        self.assertEqual(fo.prices_from_catalog(CASES["catalog"]["in"]), CASES["catalog"]["out"])
        self.assertEqual(fo.prices_from_catalog(None), {})

    def test_scenarios(self):
        for case in CASES["scenarios"]:
            with self.subTest(case["name"]):
                got, ledger, _ = run(case)
                expect = dict(case["expect"])
                receipts = expect.pop("receipts", None)
                count = expect.pop("receiptCount", None)
                got.pop("message", None)
                self.assertEqual(got, expect)
                if receipts is not None:
                    self.assertEqual(len(ledger.rows), len(receipts))
                    for actual, wanted in zip(ledger.rows, receipts):
                        same_receipt(self, actual, wanted)
                        self.assertEqual(fu.make_usage_receipt(actual["provider"], actual["model"],
                                                               input_tokens=actual["inputTokens"],
                                                               output_tokens=actual["outputTokens"],
                                                               cache_read_tokens=actual["cacheReadTokens"],
                                                               cache_write_tokens=actual["cacheWriteTokens"],
                                                               cost_usd=actual["costUsd"],
                                                               cost_basis=actual["costBasis"], at=actual["at"],
                                                               route=actual["route"],
                                                               tokens_measured=actual.get("tokensMeasured", True)),
                                         actual, "a receipt the kit itself would build")
                if count is not None:
                    self.assertEqual(len(ledger.rows), count)


class Rules(unittest.TestCase):
    def test_the_request_and_no_key_in_an_error(self):
        case = {"steps": [{"status": 503}, {"status": 503}, {"status": 400}]}
        got, _, seen = run(case)
        self.assertEqual(got["error"], "failed")
        self.assertNotIn(KEY, got["message"])
        self.assertEqual(seen[0]["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(seen[0]["headers"]["Authorization"], "Bearer " + KEY)
        self.assertEqual(seen[0]["body"], {"model": "a/one", "messages": MESSAGES, "max_tokens": 100,
                                           "usage": {"include": True}})
        self.assertEqual(seen[2]["body"]["model"], "b/two")
        for header in seen[0]["headers"]:
            self.assertNotIn(header.lower(), ("http-referer", "x-openrouter-title", "x-title"),
                             "attribution is off by default")

    def test_attribution_only_with_a_setting(self):
        seen = []
        setting = {"product": "example-agent", "title": "Example Agent", "categories": ["cloud-agent"]}
        c, _ = client({"steps": [{"status": 200, "body": {"choices": [{"finish_reason": "stop",
                                                                      "message": {"content": "x"}}]}}]},
                      seen, Ledger(), attribution=setting)
        c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100)
        self.assertEqual(seen[0]["headers"]["HTTP-Referer"], "https://passioncode.ai/example-agent/")

    def test_params_pass_through_and_reserved_ones_are_refused(self):
        seen = []
        c, _ = client({"steps": [{"status": 200, "body": {"choices": [{"finish_reason": "stop",
                                                                      "message": {"content": "x"}}]}}]},
                      seen, Ledger())
        c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100, temperature=0,
               reasoning={"effort": "low"})
        self.assertEqual(seen[0]["body"]["temperature"], 0)
        with self.assertRaises(fo.OpenRouterError) as caught:
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100, task_run_id="run-1")
        self.assertEqual((caught.exception.kind, len(seen)), ("config", 1), "refused before anything is sent")
        self.assertEqual(seen[0]["body"]["reasoning"], {"effort": "low"})
        for bad in ({"stream": True}, {"usage": {}}):
            with self.assertRaises(fo.OpenRouterError):
                c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100, **bad)
        for kwargs in ({"max_tokens": 0}, {"max_tokens": True}, {"fallback": "nofallback"}):
            args = dict(model="a/one", fallback="b/two", max_tokens=100)
            args.update(kwargs)
            with self.assertRaises(fo.OpenRouterError):
                c.chat(MESSAGES, **args)
        with self.assertRaises(fo.OpenRouterError):
            c.chat([], model="a/one", fallback="b/two", max_tokens=100)

    def test_a_project_is_named_on_the_receipt(self):
        ledger = Ledger()
        c, _ = client({"steps": [{"status": 200, "body": {"choices": [{"finish_reason": "stop",
                                                                      "message": {"content": "x"}}]}}]},
                      [], ledger, project_id="urn:example:project")
        c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100, task_run_id="run-1")
        self.assertEqual(ledger.rows[0]["projectId"], "urn:example:project")
        self.assertEqual(ledger.rows[0]["taskRunId"], "run-1")

    def test_an_unmeasured_call_counts_toward_the_ceiling(self):
        unmeasured = {"at": "2026-10-21T01:00:00Z", "provider": "openrouter", "model": "a/one", "inputTokens": 0,
                      "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0, "costUsd": None,
                      "costBasis": "unknown", "tokensMeasured": False}
        # worst case of one a/one attempt is 0.001016: one unmeasured call counted at it leaves no room under 0.002
        got, _, _ = run({"ceilingUsd": 0.002, "ledger": [unmeasured], "steps": []})
        self.assertEqual(got["error"], "ceiling")
        seen = []
        c, _ = client({"ceilingUsd": 0.002, "steps": [{"status": 200, "body": {"choices": [
            {"finish_reason": "stop", "message": {"content": "x"}}]}}]}, seen, Ledger([unmeasured]),
            unmeasured_call_usd=0.0)
        self.assertEqual(c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100)["content"], "x")

    def test_calls_in_flight_are_reserved(self):
        started, release = threading.Event(), threading.Event()
        ok = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "x"}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0}}).encode()

        def slow(method, url, headers, body, timeout_s, max_bytes):
            started.set()
            release.wait(5)
            return 200, {}, ok
        c = fo.Client(ceiling_usd=0.0015, ledger=Ledger(), prices=CASES["prices"],
                      environ={"OPENROUTER_API_KEY": KEY}, transport=slow, now=lambda: NOW)
        out = {}
        worker = threading.Thread(target=lambda: out.setdefault("a", c.chat(MESSAGES, model="a/one",
                                                                              fallback="b/two", max_tokens=100)))
        worker.start()
        self.assertTrue(started.wait(5))
        with self.assertRaises(fo.OpenRouterError) as caught:
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100)
        self.assertEqual(caught.exception.kind, "ceiling", "the first call's worst case is held while it runs")
        release.set()
        worker.join(5)
        self.assertEqual(out["a"]["content"], "x")
        self.assertEqual(c._in_flight, 0.0)

    def test_the_month_window(self):
        old = {"at": "2026-10-02T01:00:00Z", "costUsd": 0.0015}
        got, _, _ = run({"ceilingUsd": 0.002, "ledger": [old], "steps": [{"status": 200, "body": {"choices": [
            {"finish_reason": "stop", "message": {"content": "x"}}]}}]})
        self.assertEqual(got["content"], "x", "a day window does not count the 2nd")
        c, _ = client({"ceilingUsd": 0.002, "steps": []}, [], Ledger([old]), window="month")
        with self.assertRaises(fo.OpenRouterError):
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100)

    def test_config_refusals(self):
        for kwargs in ({"ceiling_usd": -1}, {"ceiling_usd": float("nan")}, {"ceiling_usd": True}, {"window": "week"},
                       {"retries": 9}, {"ledger": object()}, {"base_url": "http://openrouter.ai/api/v1"}):
            args = dict(ceiling_usd=1.0, ledger=Ledger(), prices={})
            args.update(kwargs)
            with self.assertRaises(Exception, msg=kwargs):
                fo.Client(**args)

    def test_unencodable_requests_are_refused_before_sending(self):
        seen = []
        c, _ = client({"steps": []}, seen, Ledger())
        with self.assertRaises(fo.OpenRouterError) as caught:
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100, temperature=float("nan"))
        self.assertEqual((caught.exception.kind, seen), ("config", []))
        lone = [{"role": "user", "content": "x\ud800y"}]
        c, _ = client({"steps": [{"status": 200, "body": {"choices": [{"finish_reason": "stop",
                                                                      "message": {"content": "ok"}}]}}]}, seen, Ledger())
        self.assertEqual(c.chat(lone, model="a/one", fallback="b/two", max_tokens=100)["content"], "ok")
        self.assertEqual(seen[0]["body"]["messages"], lone, "a lone surrogate is sent escaped, as JSON.stringify does")

    def test_an_answer_over_the_size_cap_may_be_billed(self):
        ledger = Ledger()
        huge = b"x" * (fo.fabric_http.DEFAULT_MAX_BYTES + 1)
        steps = [lambda: (200, {}, huge),
                 lambda: (200, {}, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "b"}}]}).encode())]
        c = fo.Client(ceiling_usd=1.0, ledger=ledger, prices=CASES["prices"], environ={"OPENROUTER_API_KEY": KEY},
                      transport=lambda *a: steps.pop(0)(), now=lambda: NOW)
        got = c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=100)
        self.assertEqual([a["outcome"] for a in got["attempts"]], ["refused", "answered"])
        self.assertEqual(ledger.rows[0]["tokensMeasured"], False)
        self.assertIsNone(ledger.rows[0]["costUsd"])

    def test_an_unmeasured_attempt_counts_at_its_own_worst_case(self):
        steps = [{"error": "timeout"}]
        c, _ = client({"ceilingUsd": 0.0021, "steps": steps}, [], Ledger(), retries=0)
        with self.assertRaises(fo.OpenRouterError):
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=200)  # a/one up to 0.002016, then timed out
        with self.assertRaises(fo.OpenRouterError) as caught:
            c.chat(MESSAGES, model="a/one", fallback="b/two", max_tokens=10)  # up to 0.000116 more
        self.assertEqual(caught.exception.kind, "ceiling", "the timed-out call is counted at 0.002016, not 0.000116")

    def test_totals(self):
        self.assertEqual(fo.totals([{"costUsd": 0.5}, {"costUsd": None}, {"costUsd": 0.25}]),
                         {"calls": 3, "spentUsd": 0.75, "unpricedCalls": 1})
        self.assertEqual(fo.totals([{"costUsd": None}]), {"calls": 1, "spentUsd": None, "unpricedCalls": 1})


if __name__ == "__main__":
    unittest.main()
