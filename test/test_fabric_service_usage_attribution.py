"""DEC-0065 in the Python service kit (FAA-33): OpenRouter attribution, FAC-SEM-025 whole (window, byProject, CT-40,
DEC-0076) and project attribution in the usage report; the twin of fabric-service-usage-attribution.test.mjs. Held to
the contract's answers (test/fixtures/contract/usage-attribution-vectors.json, vendor_vectors.mjs)."""
import datetime as dt
import json
from pathlib import Path
import unittest

from test_fabric_service import load

fs = load("fabric_service")
probe = load("check_service")
V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/usage-attribution-vectors.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)


def receipt(**extra):
    return fs.make_usage_receipt("openrouter", "example-model", input_tokens=10, output_tokens=5, at="2026-10-13T09:00:00Z", **extra)


class Attribution(unittest.TestCase):
    def test_every_case_answers_as_the_contract_does(self):
        self.assertEqual(len(V["attribution"]), 34)
        for c in V["attribution"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.attribution_headers(c["setting"], c["request"]), c["expect"])

    def test_urls_read_as_a_browser_reads_them(self):
        """The WHATWG forms new URL() accepts for openrouter.ai, as Node reads them (checked with node -e)."""
        setting = {"product": "example-agent", "title": "Example Agent"}
        for url in ("https:\\\\openrouter.ai/x", "https:/\\openrouter.ai/x", "  https://openrouter.ai/x  ", "https://open\trouter.ai/x"):
            with self.subTest(url=url):
                self.assertNotIn("none", fs.attribution_headers(setting, {"url": url, "originated": True}))

    def test_off_by_default_and_the_setting_rule(self):
        self.assertEqual(fs.attribution_headers(None, {"url": "https://openrouter.ai/api/v1", "originated": True}), {"headers": {}, "none": "no-setting"})
        self.assertEqual(fs.attribution_setting_findings({"product": "example-agent", "title": "Example Agent"}), [])
        self.assertEqual([f["instancePath"] for f in fs.attribution_setting_findings({"product": "X", "title": " t"})], ["/product", "/title"])


class UsageRules(unittest.TestCase):
    def test_fac_sem_025_answers_as_the_contract_does(self):
        self.assertEqual(len(V["usage"]), 204)
        for c in V["usage"]:
            with self.subTest(c["name"]):
                self.assertEqual([(f["code"], f["instancePath"]) for f in fs.usage_findings(c["report"])],
                                 [(f["code"], f["instancePath"]) for f in c["findings"]])

    def test_the_probe_reads_window_projects_and_routes(self):
        for c in V["usage"]:
            r = c["report"]
            with self.subTest(c["name"]):
                problems = probe.usage_problems(r, r["service"]["id"], r["service"]["instance"])
                self.assertEqual(bool(problems), bool(c["findings"]), problems)
        good = next(c["report"] for c in V["usage"] if c["name"] == "service-usage-platform-metered")
        bad = json.loads(json.dumps(good))
        bad["days"][0]["byModel"][0]["route"] = "metered"
        self.assertTrue(any("route" in p for p in probe.usage_problems(bad, bad["service"]["id"], bad["service"]["instance"])))


class ProjectAttribution(unittest.TestCase):
    def test_the_report_writes_by_project_in_normal_form(self):
        receipts = [receipt(cost_usd=0.5, project_id="urn:project:a", task_run_id="run-1"),
                    receipt(cost_usd=0.25, project_id="URN:PROJECT:a", task_run_id="run-1"),
                    receipt(project_id="urn:project:a", task_run_id="run-2"),
                    receipt(cost_usd=1.0, project_id="urn:project:b"),
                    receipt(cost_usd=2.0)]
        report = fs.usage_report(receipts, service_id="example-agent", now=NOW)
        self.assertEqual([p["projectId"] for p in report["byProject"]], ["urn:project:a", "urn:project:b"])
        a = report["byProject"][0]
        self.assertEqual((a["calls"], a["unpricedCalls"], a["costUsd"]), (3, 1, 0.75))
        self.assertEqual([(r["taskRunId"], r["calls"], r["costUsd"]) for r in a["taskRuns"]], [("run-1", 2, 0.75), ("run-2", 1, None)])
        self.assertNotIn("taskRuns", report["byProject"][1])
        self.assertEqual(fs.usage_findings(report), [], "the kit's own report passes FAC-SEM-025")
        self.assertNotIn("byProject", fs.usage_report([receipt(cost_usd=1.0)], service_id="example-agent", now=NOW))

    def test_unmeasured_tokens_are_counted_never_guessed(self):  # DEC-0091
        at = "2026-10-13T09:00:00Z"
        receipts = [fs.make_usage_receipt("openrouter", "model-a", input_tokens=0, output_tokens=0, at=at, tokens_measured=False),
                    fs.make_usage_receipt("openrouter", "model-a", input_tokens=10, output_tokens=5, at=at, cost_usd=0.1),
                    fs.make_usage_receipt("openrouter", "model-b", input_tokens=7, output_tokens=0, at=at, tokens_measured=False,
                                          project_id="urn:project:a"),
                    fs.make_usage_receipt("openrouter", "model-b", input_tokens=1, output_tokens=1, at=at, tokens_measured=True)]
        self.assertEqual([r.get("tokensMeasured") for r in receipts], [False, None, False, None], "written only when false")
        report = fs.usage_report(receipts, service_id="example-agent", now=NOW)
        day = report["days"][-1]
        self.assertEqual((day["calls"], day["unmeasuredCalls"], day["inputTokens"]), (4, 2, 18))
        self.assertEqual({m["model"]: m.get("unmeasuredCalls") for m in day["byModel"]}, {"model-a": 1, "model-b": 1})
        self.assertNotIn("unmeasuredCalls", report["byProject"][0], "the schema has no unmeasuredCalls on a project")
        self.assertEqual(fs.usage_findings(report), [])
        self.assertEqual(probe.usage_problems(report, "example-agent", "default"), [])
        measured = fs.usage_report(receipts[1:2] + receipts[3:], service_id="example-agent", now=NOW)
        self.assertNotIn("unmeasuredCalls", measured["days"][-1], "absent when every call was measured")
        for bad in (0, 1, None, "false"):
            with self.subTest(tokens_measured=bad), self.assertRaises(fs.ServiceError):
                fs.make_usage_receipt("openrouter", "model-a", input_tokens=0, output_tokens=0, at=at, tokens_measured=bad)

    def test_receipt_refusals(self):
        for bad in (dict(project_id="no uri"), dict(task_run_id="run-1"), dict(project_id="urn:project:a", task_run_id="-bad")):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError):
                receipt(**bad)


if __name__ == "__main__":
    unittest.main()
