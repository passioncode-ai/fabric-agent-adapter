"""The Python kit's delegation verifier (DEC-0039) against the shared vectors, whose expected answers come from
the contract's own verifier at the pin (test/fixtures/delegation/make_vectors.mjs)."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from test_fabric_service import SCRIPTS, load

dl = load("fabric_delegation")
fc = load("fabric_crypto")
fi = load("fabric_interop")
VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/delegation/vectors.json").read_text())


def options(raw, store=None):
    o = {"audience": raw["audience"], "jwks": raw.get("jwks"), "now": raw["now"]}
    for key, name in (("capability", "capability"), ("effect", "effect"), ("issuer", "issuer"),
                      ("readOnly", "read_only"), ("actionDigest", "action_digest")):
        if key in raw:
            o[name] = raw[key]
    if "jtiStore" in raw:
        o["jti_store"] = None if raw["jtiStore"] == "none" else store
    return o


def answer(result):
    if result["ok"]:
        return {k: result[k] for k in ("ok", "principal", "caller", "chain", "kid", "approver", "method") if k in result}
    out = {"ok": False, "code": result["code"], "detail": result["detail"]}
    if result.get("data"):
        out["data"] = result["data"]
    return out


class Ed25519Tests(unittest.TestCase):
    def test_matches_openssl_and_rfc_8032(self):
        for case in VECTORS["ed25519"]:
            with self.subTest(kind=case["kind"], pub=case["pub"][:12]):
                got = dl.ed25519_verify(bytes.fromhex(case["pub"]), bytes.fromhex(case["msg"]), bytes.fromhex(case["sig"]))
                self.assertIs(got, case["valid"])
        self.assertGreaterEqual(len(VECTORS["ed25519"]), 300)

    def test_wrong_lengths_and_a_key_that_is_not_a_point(self):
        case = next(c for c in VECTORS["ed25519"] if c["valid"])
        pub, msg, sig = (bytes.fromhex(case[k]) for k in ("pub", "msg", "sig"))
        self.assertFalse(dl.ed25519_verify(pub[:31], msg, sig))
        self.assertFalse(dl.ed25519_verify(pub, msg, sig[:63]))
        self.assertFalse(dl.ed25519_verify(b"\xff" * 32, msg, sig))  # y >= p is not a canonical point
        # The identity point (0, 1) decodes; the same point written as y = p + 1 is not canonical and is refused.
        self.assertIsNotNone(fc._ed_decode_point((1).to_bytes(32, "little")))
        self.assertIsNone(fc._ed_decode_point((2 ** 255 - 19 + 1).to_bytes(32, "little")))


class VerifierVectorTests(unittest.TestCase):
    def test_every_delegation_case_answers_as_the_contract_does(self):
        for case in VECTORS["delegation"]:
            with self.subTest(case["name"]):
                o = options(case["options"])
                o.setdefault("issuer", None)
                got = dl.verify_delegation(case["token"], **o)
                # Every expected answer is the contract's own; the contract no longer throws on any case (CT-31).
                self.assertNotIn("contractThrew", case)
                self.assertEqual(answer(got), case["expected"])
        self.assertGreaterEqual(len(VECTORS["delegation"]), 60)

    def test_every_approval_case_answers_as_the_contract_does(self):
        for case in VECTORS["approvals"]:
            store = dl.MemoryJtiStore()
            for i, step in enumerate(case["steps"]):
                with self.subTest(case["name"], step=i):
                    o = options(step["options"], store)
                    o.setdefault("issuer", None)
                    got = dl.verify_approval(step["approval"], **o)
                    self.assertEqual(answer(got), step["expected"])

    def test_headers(self):
        for case in VECTORS["headers"]:
            with self.subTest(case["headers"]):
                self.assertEqual(dl.read_delegation_token(case["headers"]), case["expected"])
        message = __import__("email.message").message.Message()
        message["Fabric-Delegation"] = VECTORS["headers"][0]["headers"]["fabric-delegation"]
        self.assertEqual(dl.read_delegation_token(message)["via"], "fabric-delegation")
        self.assertEqual(dl.read_delegation_token({"authorization": ["Bearer " + VECTORS["headers"][0]["headers"]["fabric-delegation"]]})["via"], "authorization")


class CanonicalJsonTests(unittest.TestCase):
    def test_rfc_8785_and_ecmascript_numbers(self):
        for case in VECTORS["jcs"]:
            with self.subTest(case["input"][:40]):
                self.assertEqual(dl.jcs(json.loads(case["input"])), case["expected"])
        for case in VECTORS["digests"]:
            self.assertEqual(dl.action_digest(json.loads(case["input"])), case["expected"])

    def test_chain_depth_takes_a_partner_innermost_only(self):  # DEC-0090
        for case in VECTORS["chainDepths"]:
            depth = dl.chain_depth(dl._MISSING if case["act"] is None else case["act"])
            self.assertEqual(None if depth == float("inf") else depth, case["expected"], case["name"])

    def test_the_contracts_canonical_vectors(self):
        """DEC-0043: fixtures/vectors/canonical.json at the pin, copied to test/fixtures/contract/."""
        import struct
        doc = json.loads((Path(__file__).resolve().parent / "fixtures/contract/canonical.json").read_text())["rfc8785"]
        for v in doc["vectors"]:
            value = json.loads(v["inputJson"]) if "inputJson" in v else v["input"]
            with self.subTest(v["name"]):
                self.assertEqual(dl.jcs(value), v["expected"])
                if "utf8Hex" in v:
                    self.assertEqual(dl.jcs(value).encode("utf-8").hex(), v["utf8Hex"])
        for v in doc["numbers"]:
            with self.subTest(v.get("note", v["ieee754"])):
                self.assertEqual(dl.jcs(struct.unpack(">d", bytes.fromhex(v["ieee754"]))[0]), v["expected"])
        for v in doc["refuses"]:
            with self.subTest(v["name"]), self.assertRaises(TypeError):
                dl.jcs(json.loads(v["inputJson"]) if "inputJson" in v else struct.unpack(">d", bytes.fromhex(v["ieee754"]))[0])

    def test_refuses_what_has_no_canonical_form(self):
        for bad in (float("nan"), float("inf"), "\ud800", {1: "x"}, object(), b"bytes", (1, 2)):
            with self.subTest(repr(bad)), self.assertRaises(TypeError):
                dl.jcs(bad)
        self.assertEqual(dl.jcs("\U0001f600"), '"\U0001f600"')
        self.assertEqual(dl.jcs(2 ** 64), "18446744073709552000")  # a JSON number is a double, as in JavaScript
        self.assertEqual(dl.jcs(-0.0), "0")


class JtiStoreTests(unittest.TestCase):
    def test_memory_store_consumes_once_and_prunes(self):
        store = dl.MemoryJtiStore()
        self.assertTrue(store.consume("a", 100, 50))
        self.assertFalse(store.consume("a", 100, 60))
        self.assertTrue(store.consume("b", 100, 50))
        self.assertTrue(store.consume("a", 300, 100 + dl.LEEWAY_SECONDS + 1))  # pruned after its life

    def test_file_store_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "jti.json"
            self.assertTrue(dl.FileJtiStore(path).consume("a", 1000, 10))
            self.assertFalse(dl.FileJtiStore(path).consume("a", 1000, 20))
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            self.assertTrue(dl.FileJtiStore(path).consume("a", 2000, 1000 + dl.LEEWAY_SECONDS + 1))

    def test_file_store_writes_with_the_kits_private_writer(self):
        """FAA-85: the consumed ids go through fabric_paths.atomic_write, so on Windows the file gets the owner-only
        ACL before its bytes (DEC-0032), and a failed write leaves no temporary file behind."""
        writer = dl._atomic_write.__globals__  # the fabric_paths the store calls, whichever copy that is
        self.assertTrue(writer["__file__"].endswith("fabric_paths.py"))
        protected = []
        saved = (writer["WINDOWS"], writer["_win_protect"])
        try:
            writer["WINDOWS"] = True
            writer["_win_protect"] = lambda path, folder: protected.append((Path(path).name, folder))
            with tempfile.TemporaryDirectory() as temp:
                self.assertTrue(dl.FileJtiStore(Path(temp) / "jti.json").consume("a", 1000, 10))
        finally:
            writer["WINDOWS"], writer["_win_protect"] = saved
        self.assertEqual(len(protected), 1, protected)
        self.assertTrue(protected[0][0].startswith(".jti.json.") and protected[0][1] is False, protected)

    def test_a_failed_acl_step_closes_the_temporary_file_and_raises_its_own_error(self):
        """FAA-85 round 2: on Windows the ACL step runs before the bytes; when it fails the temporary file's handle is
        closed (else Windows cannot delete it), nothing is left, and the ACL error is what the caller sees."""
        import os
        writer = dl._atomic_write.__globals__
        opened = []
        real_mkstemp = writer["tempfile"].mkstemp

        def mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            opened.append(fd)
            return fd, name

        def refuse(path, folder):
            raise RuntimeError("acl refused")
        saved = (writer["WINDOWS"], writer["_win_protect"])
        writer["WINDOWS"], writer["_win_protect"] = True, refuse
        writer["tempfile"].mkstemp = mkstemp
        try:
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(RuntimeError, "acl refused"):
                    dl.FileJtiStore(Path(temp) / "jti.json").consume("a", 1000, 10)
                self.assertEqual(len(opened), 1)
                with self.assertRaises(OSError):  # checked at once, before anything else can reuse the number
                    os.fstat(opened[0])
                self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), [])
        finally:
            writer["tempfile"].mkstemp = real_mkstemp
            writer["WINDOWS"], writer["_win_protect"] = saved

    def test_a_failed_cleanup_does_not_replace_the_error_that_caused_it(self):
        import os
        writer = dl._atomic_write.__globals__

        def refuse(path, folder):
            raise RuntimeError("acl refused")
        saved = (writer["WINDOWS"], writer["_win_protect"], os.unlink)
        writer["WINDOWS"], writer["_win_protect"] = True, refuse
        os.unlink = lambda path: (_ for _ in ()).throw(PermissionError("refused remove"))
        try:
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(RuntimeError, "acl refused"):
                    dl.FileJtiStore(Path(temp) / "jti.json").consume("a", 1000, 10)
                os.unlink = saved[2]
        finally:
            writer["WINDOWS"], writer["_win_protect"], os.unlink = saved

    def test_a_failed_file_store_write_leaves_no_temporary_file(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            replace = os.replace
            def refuse(src, dst):
                raise PermissionError("refused")
            os.replace = refuse
            try:
                with self.assertRaises(PermissionError):
                    dl.FileJtiStore(Path(temp) / "jti.json").consume("a", 1000, 10)
            finally:
                os.replace = replace
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), [])

    def test_file_store_consumes_once_under_threads(self):
        with tempfile.TemporaryDirectory() as temp:
            store = dl.FileJtiStore(Path(temp) / "jti.json")
            wins = []
            threads = [threading.Thread(target=lambda: wins.append(store.consume("same", 1000, 10))) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(wins.count(True), 1)

    def test_the_store_is_required(self):
        case = VECTORS["approvals"][0]["steps"][0]
        o = options(case["options"])
        o["jti_store"] = None
        self.assertEqual(dl.verify_approval(case["approval"], **o)["code"], "unknown-state")
        o["jti_store"] = dl.UNSAFE_NO_JTI_STORE
        self.assertTrue(dl.verify_approval(case["approval"], **o)["ok"])


class JwksCacheTests(unittest.TestCase):
    """DL-15: cache the set at most 10 minutes; on an unknown kid, re-read at most once a minute."""

    def setUp(self):
        self.now = [1000.0]
        self.calls = []
        self.answer = [VECTORS["jwks"]]

    def fetch(self, source):
        self.calls.append(self.now[0])
        if isinstance(self.answer[0], Exception):
            raise self.answer[0]
        return self.answer[0]

    def cache(self):
        return dl.JwksCache("https://hub.example/.well-known/jwks.json", fetch=self.fetch, clock=lambda: self.now[0])

    def test_reads_once_and_refreshes_after_ten_minutes(self):
        c = self.cache()
        self.assertEqual(c.get("estate-new"), VECTORS["jwks"])
        self.now[0] += 599
        c.get("estate-new")
        self.assertEqual(len(self.calls), 1)
        self.now[0] += 2
        c.get("estate-new")
        self.assertEqual(len(self.calls), 2)

    def test_an_unknown_kid_re_reads_at_most_once_a_minute(self):
        c = self.cache()
        c.get("estate-new")
        c.get("estate-next")
        self.assertEqual(len(self.calls), 2)
        self.now[0] += 30
        c.get("estate-next")
        self.assertEqual(len(self.calls), 2)
        self.now[0] += 31
        c.get("estate-next")
        self.assertEqual(len(self.calls), 3)

    def test_an_unreadable_set_is_kept_ten_minutes_then_dropped(self):
        c = self.cache()
        c.get("estate-new")
        self.answer[0] = OSError("down")
        self.now[0] += 601
        self.assertIsNone(c.get("estate-new"))
        self.assertEqual(dl.verify_delegation(VECTORS["delegation"][0]["token"], audience="example-writer", jwks=c.get("estate-new"),
                                              now=1, capability="writer.write", effect="draft", issuer="urn:fabric:estate:example")["code"], "issuer-unavailable")

    def test_sources(self):
        for bad in ("http://hub.example/jwks.json", "ftp://x/jwks.json", "https://user:pw@hub.example/j", ""):
            with self.subTest(bad), self.assertRaises(ValueError):
                dl.JwksCache(bad)
        dl.JwksCache("http://127.0.0.1:7777/.well-known/jwks.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "jwks.json"
            path.write_text(json.dumps(VECTORS["jwks"]))
            self.assertEqual(dl.JwksCache(str(path)).get("estate-new"), VECTORS["jwks"])
            path.write_text("[]")
            self.assertIsNone(dl.JwksCache(str(path)).get("estate-new"))


class GateTests(unittest.TestCase):
    """The gate a service puts in front of its tools, and McpToolServer(authorize=)."""

    def setUp(self):
        self.case = VECTORS["delegation"][0]
        o = self.case["options"]
        self.gate = dl.delegation_gate(audience=o["audience"], jwks=VECTORS["jwks"], effects={"writer.write": "draft", "writer.publish": "publish"},
                                       issuer="urn:fabric:estate:example", clock=lambda: o["now"])

    def test_accepts_and_refuses(self):
        token = self.case["token"]
        ok = self.gate("writer.write", {"Authorization": "Bearer " + token})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["caller"], "example-media")
        missing = self.gate("writer.write", {})
        self.assertEqual((missing["code"], missing["detail"]), ("unauthenticated", "no-token"))
        undeclared = self.gate("writer.other", {"Authorization": "Bearer " + token})
        self.assertEqual((undeclared["code"], undeclared["detail"]), ("unknown-state", "no-declared-effect"))
        above = self.gate("writer.publish", {"Fabric-Delegation": token})
        self.assertEqual(above["code"], "scope-not-granted")
        empty = self.gate("writer.write", {"Fabric-Delegation": ""})
        self.assertEqual(empty["code"], "unauthenticated")

    def test_tiers_dl_26(self):
        """A T0 or T1 caller is never required to present a token; a present one is verified at every tier."""
        token = self.case["token"]
        for tier in ("T0", "T1"):
            passed = self.gate("writer.write", {}, tier=tier)
            self.assertEqual((passed["ok"], passed["tier"], passed["principal"]), (True, tier, None))
            self.assertEqual(self.gate("writer.write", {"Fabric-Delegation": "junk"}, tier=tier)["code"], "unauthenticated")
            self.assertEqual(self.gate("writer.write", {"Authorization": "Bearer " + token}, tier=tier)["caller"], "example-media")
        self.assertEqual(self.gate("writer.write", {}, tier="T9")["code"], "unauthenticated")
        self.assertEqual(self.gate("writer.write", {})["detail"], "no-token")
        self.assertEqual(self.gate("writer.other", {}, tier="T0")["detail"], "no-declared-effect")
        with self.assertRaises(ValueError):
            dl.delegation_gate(audience="a", jwks=VECTORS["jwks"], effects={}, issuer="")

    def test_refusal_from_a_meter_denial(self):
        doc = dl.refusal_from_denial({"decision": "denied", "level": "L1", "code": "limit-reached", "reason": "the day window is spent",
                                      "checkedAt": "2026-10-12T00:00:00Z", "window": "day"})
        self.assertEqual(doc, {"error": {"code": "limit-reached", "message": "the meter denied the spend: the day window is spent",
                                         "data": {"window": "day", "level": "L1"}}})
        bare = dl.refusal_from_denial({"decision": "denied", "level": None, "code": "no-grant", "reason": "x", "checkedAt": "t"})
        self.assertNotIn("data", bare["error"])

    def test_refusal_shapes(self):
        refusal = self.gate("writer.write", {})
        result = dl.refusal_tool_result(refusal)
        self.assertTrue(result["isError"])
        error = result["structuredContent"]["error"]
        self.assertEqual(error["code"], "unauthenticated")
        self.assertTrue(error["message"])
        self.assertEqual(error["data"], {"detail": "no-token"})
        status, headers, body = dl.refusal_http(refusal)
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], 'Bearer error="invalid_token"')
        self.assertEqual(json.loads(body)["error"]["code"], "unauthenticated")
        for code in VECTORS["constants"]["refusalCodes"]:
            self.assertIn(dl.refusal_http({"ok": False, "code": code, "detail": "x"})[0], (401, 403, 503))
        # DL-19 (DEC-0106): profile-forbids is the callee's refusal, 403 with no challenge.
        status, headers, body = dl.refusal_http({"ok": False, "code": "profile-forbids", "detail": "target-view"})
        self.assertEqual(status, 403)
        self.assertNotIn("WWW-Authenticate", headers)
        self.assertEqual(json.loads(body)["error"]["message"], "The caller's or the target's machine profile does not allow this call.")
        self.assertNotIn(self.case["token"], json.dumps(result))

    def test_mcp_tool_server_runs_the_gate_before_the_handler(self):
        seen = []
        server = fi.McpToolServer("example-writer", "0.1.0", authorize=self.gate)
        server.add_tool({"name": "writer.write", "inputSchema": {"type": "object"}},
                        lambda args, ctx: seen.append(ctx.delegation["caller"]) or {"ok": True})
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "writer.write", "arguments": {}}}
        refused = server.handle(call, {"Mcp-Method": "tools/call", "Mcp-Name": "writer.write"})
        self.assertTrue(refused["result"]["isError"])
        self.assertEqual(refused["result"]["structuredContent"]["error"]["code"], "unauthenticated")
        self.assertEqual(seen, [])
        accepted = server.handle(call, {"Mcp-Method": "tools/call", "Mcp-Name": "writer.write", "Authorization": "Bearer " + self.case["token"]})
        self.assertFalse(accepted["result"]["isError"])
        self.assertEqual(seen, ["example-media"])
        seen.clear()
        server.add_tool({"name": "writer.local", "inputSchema": {"type": "object"}}, lambda args, ctx: seen.append(ctx.delegation["tier"]) or {"ok": True})
        local = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "writer.local", "arguments": {}}},
                              {"Mcp-Method": "tools/call", "Mcp-Name": "writer.local"}, tier="T0")
        self.assertTrue(local["result"]["isError"])  # writer.local has no declared effect in this gate
        passed = server.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "writer.write", "arguments": {}}},
                               {"Mcp-Method": "tools/call", "Mcp-Name": "writer.write"}, tier="T0")
        self.assertFalse(passed["result"]["isError"])  # DL-26: a local caller needs no token
        self.assertEqual(seen, [None])  # the handler ran, and a T0 call without a token names no caller

        plain = fi.McpToolServer("x", "0.1.0")
        plain.add_tool({"name": "writer.write", "inputSchema": {"type": "object"}}, lambda args, ctx: {"d": ctx.delegation})
        self.assertEqual(plain.handle(call)["result"]["structuredContent"], {"d": None})


ACTIONS = json.loads((Path(__file__).resolve().parent / "fixtures/contract/actions-vectors.json").read_text())
HUMAN_STEPS = ("sign-in", "consent", "payment", "secret", "spend-above-limit", "passkey")


def dl19_problems(body):
    """delegation-refusal.schema.json's rules, by hand: what makes `body` not a DL-19 refusal (empty when it is one)."""
    problems = []
    error = body.get("error") if isinstance(body, dict) and list(body) == ["error"] else None
    if not isinstance(error, dict) or set(error) - {"code", "message", "data"}:
        return ["shape"]
    if error.get("code") not in VECTORS["constants"]["refusalCodes"]:
        problems.append("code")
    if not (isinstance(error.get("message"), str) and 1 <= len(error["message"]) <= 500):
        problems.append("message")
    data = error.get("data", {})
    if not isinstance(data, dict) or not (isinstance(data.get("detail"), str) and 1 <= len(data["detail"]) <= 80):
        problems.append("detail")
    if error.get("code") == "approval-required" and not str(data.get("actionDigest", "")).startswith("sha256:"):
        problems.append("actionDigest")
    if error.get("code") == "human-step-required":
        url = data.get("url")
        if data.get("humanStep") not in HUMAN_STEPS:
            problems.append("humanStep")
        if not (isinstance(url, str) and 1 <= len(url) <= 2048 and (url.startswith("https://") or url.startswith("/"))):
            problems.append("url")
    return problems


class RefusalCodeSetTests(unittest.TestCase):
    """DL-19 (DEC-0039, DEC-0121): the kit's one code set is the contract's, each code answers with its own sentence,
    and the refusals of an action call (fabric_actions) are DL-19 bodies."""

    def test_the_code_set_is_the_contracts(self):
        self.assertEqual(list(dl.REFUSAL_CODES), VECTORS["constants"]["refusalCodes"])
        self.assertEqual(len(dl.REFUSAL_CODES), 21)

    def test_every_code_has_its_sentence_and_status(self):
        for code in dl.REFUSAL_CODES:
            with self.subTest(code):
                self.assertIn(code, dl.REFUSAL_MESSAGES)
                self.assertNotEqual(dl.REFUSAL_MESSAGES[code], "Refused.")
                data = {"actionDigest": "sha256:" + "0" * 64, "humanStep": "consent", "url": "/x"}
                self.assertEqual(dl19_problems(dl.refusal_error({"ok": False, "code": code, "detail": "x", "data": data})), [])
        for code in ("operator-decision-required", "decision-invalid", "human-step-required"):
            status, headers, _ = dl.refusal_http({"ok": False, "code": code, "detail": "x"})
            self.assertEqual(status, 403, code)
            self.assertNotIn("WWW-Authenticate", headers)

    def test_the_decision_refusal_names_the_routes_without_meta(self):
        # D13 of the 0.51.0 brief: DL-19 leaves the message free (at most 500 characters), so the kit's names the
        # three routes the contract's owner confirmed for a client that cannot set _meta, in their order.
        message = dl.REFUSAL_MESSAGES["operator-decision-required"]
        self.assertLessEqual(len(message), 500)
        routes = ["_meta.decision", "agent.call", "call.decision", "elicitation", "Fabric Dashboards", "open_link"]
        places = [message.find(route) for route in routes]
        self.assertNotIn(-1, places, message)
        self.assertEqual(places, sorted(places))
        self.assertNotIn("—", message)
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not on PATH")
        script = ("import('" + (SCRIPTS / "fabric-delegation.mjs").as_uri() + "').then((d) => process.stdout.write("
                  "JSON.stringify(d.REFUSAL_MESSAGES['operator-decision-required'])))")
        twin = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(twin.returncode, 0, twin.stderr)
        self.assertEqual(json.loads(twin.stdout), message)

    def test_an_action_refusal_is_a_dl19_body(self):
        refused = 0
        for case in ACTIONS["cases"]:
            with self.subTest(case["name"]):
                answer = case["expected"]
                refusal = dl.refusal_from_action(answer)
                if answer.get("ok") is True:
                    self.assertIsNone(refusal)
                    continue
                refused += 1
                result = dl.refusal_tool_result(refusal, "00-" + "a" * 32 + "-" + "b" * 16 + "-01")
                self.assertTrue(result["isError"])
                body = result["structuredContent"]
                self.assertEqual(json.loads(result["content"][0]["text"]), body)
                self.assertEqual(dl19_problems(body), [])
                if "fault" in answer:  # the service's own fault is never sent: the caller reads an unknown state
                    self.assertEqual(body["error"]["code"], "unknown-state")
                    self.assertEqual(body["error"]["data"], {"detail": "service-fault"})
                    self.assertNotIn(answer["fault"], json.dumps(body))
                    continue
                self.assertEqual(body["error"]["code"], answer["code"])
                detail = {"operator-decision-required": "no-decision", "decision-invalid": "invalid-decision",
                          "human-step-required": "human-step", "approval-required": "no-approval"}[answer["code"]]
                self.assertEqual(body["error"]["data"], dict(answer.get("data", {}), detail=detail))
                self.assertEqual(dl.refusal_http(refusal)[0], 403)
        self.assertGreater(refused, 30)

    def test_a_human_step_carries_its_step_and_link(self):
        refusal = dl.refusal_from_action({"ok": False, "code": "human-step-required",
                                          "data": {"humanStep": "payment", "url": "https://store.example/pay"}})
        self.assertEqual(refusal, {"ok": False, "code": "human-step-required", "detail": "human-step",
                                   "data": {"humanStep": "payment", "url": "https://store.example/pay"}})
        error = dl.refusal_error(refusal)["error"]
        self.assertEqual(error["data"], {"detail": "human-step", "humanStep": "payment", "url": "https://store.example/pay"})
        self.assertEqual(error["message"], dl.REFUSAL_MESSAGES["human-step-required"])

    def test_what_is_not_an_answer_is_an_unknown_state(self):
        for value in (None, [], "x", {}, {"ok": False}, {"ok": False, "code": "no-such-code"}, {"ok": "true"},
                      {"ok": False, "code": "toString"}):
            with self.subTest(value=repr(value)):
                refusal = dl.refusal_from_action(value)
                self.assertEqual((refusal["code"], refusal["detail"]), ("unknown-state", "service-fault"))


class ReviewRegressionTests(unittest.TestCase):
    """Findings of the independent review of the port, each a test that failed first."""

    def test_a_deeply_nested_duplicate_is_a_refusal_not_a_crash(self):
        import base64 as b64
        deep = '{"x":{"a":1,"a":2},"y":' + "[" * 5000 + "]" * 5000 + "}"
        seg = b64.urlsafe_b64encode(deep.encode()).decode().rstrip("=")
        token = seg + "." + seg + ".AAAA"
        self.assertEqual(dl.verify_delegation(token, audience="a", jwks=VECTORS["jwks"], now=0, capability="c", effect="none",
                                              issuer="urn:fabric:estate:example")["code"], "unauthenticated")
        self.assertIsNone(dl.read_delegation_token({"Authorization": "Bearer " + token}))

    def test_an_unreadable_jti_file_refuses_instead_of_forgetting(self):
        import os
        step = VECTORS["approvals"][0]["steps"][0]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "jti.json"
            store = dl.FileJtiStore(path)
            o = options(step["options"], store)
            self.assertTrue(dl.verify_approval(step["approval"], **o)["ok"])
            path.write_text("{")  # truncated
            self.assertEqual(dl.verify_approval(step["approval"], **o)["code"], "unknown-state")
            path.write_text("{}")
            if os.geteuid() != 0:
                os.chmod(path, 0)
                try:
                    self.assertEqual(dl.verify_approval(step["approval"], **o)["code"], "unknown-state")
                finally:
                    os.chmod(path, 0o600)

    def test_the_key_set_fetch_follows_no_redirect(self):
        import http.server
        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/real":
                    body = json.dumps(VECTORS["jwks"]).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/real" % self.server.server_address[1])
                self.end_headers()
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertIsNone(dl.JwksCache("http://127.0.0.1:%d/jwks" % server.server_address[1]).get("estate-new"))
        finally:
            server.shutdown()

    def test_a_failed_read_is_not_retried_on_every_call(self):
        now, calls = [1000.0], []
        def fetch(source):
            calls.append(now[0])
            raise OSError("down")
        cache = dl.JwksCache("https://hub.example/j", fetch=fetch, clock=lambda: now[0])
        cache.get("k"); cache.get("k")
        self.assertEqual(len(calls), 1)
        now[0] += dl.JWKS_RETRY_SECONDS
        cache.get("k")
        self.assertEqual(len(calls), 2)

    def test_header_trimming_follows_javascript(self):
        token = VECTORS["delegation"][0]["token"]
        self.assertEqual(dl.read_delegation_token({"Fabric-Delegation": "\x1c" + token})["token"], "\x1c" + token)
        self.assertEqual(dl.read_delegation_token({"Fabric-Delegation": "\ufeff " + token + "\n"})["token"], token)
        with self.assertRaises(TypeError):
            dl.jcs(10 ** 400)


class GatedJobTests(unittest.TestCase):
    """Review finding: a job started under a delegation is read, cancelled and answered only by the same
    principal and caller, with a token that still covers the job's capability."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.case = VECTORS["delegation"][0]
        self.other = next(c for c in VECTORS["delegation"] if c["name"] == "chain of four")
        o = self.case["options"]
        gate = dl.delegation_gate(audience=o["audience"], jwks=VECTORS["jwks"], effects={"writer.write": "draft"},
                                  issuer="urn:fabric:estate:example", clock=lambda: o["now"])
        self.answered = []
        self.server = fi.McpToolServer("example-writer", "0.1.0", jobs=fi.JobStore(Path(self.temp.name)), authorize=gate,
                                       on_input=lambda job_id, matched, ctx: self.answered.append(ctx.delegation and ctx.delegation["caller"]))
        self.server.add_tool({"name": "writer.write", "inputSchema": {"type": "object"}}, lambda args, ctx: ctx.start_job())

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, arguments, token=None):
        headers = {"Mcp-Method": "tools/call", "Mcp-Name": name}
        if token:
            headers["Authorization"] = "Bearer " + token
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}, headers)["result"]

    def test_job_tools_are_gated_by_the_job_owner(self):
        job = self.call("writer.write", {}, self.case["token"])["structuredContent"]["job"]["id"]
        self.assertEqual(self.call("fabric.job.get", {"id": job})["structuredContent"]["error"]["code"], "unauthenticated")
        self.assertEqual(self.call("fabric.job.get", {"id": job}, self.other["token"])["structuredContent"]["error"]["code"], "scope-not-granted")
        self.assertEqual(self.call("fabric.job.cancel", {"id": job}, self.other["token"])["structuredContent"]["error"]["code"], "scope-not-granted")
        self.assertEqual(self.call("fabric.job.get", {"id": job}, self.case["token"])["structuredContent"]["job"]["id"], job)
        self.assertTrue(self.call("fabric.job.get", {"id": "job_" + "0" * 24}, self.case["token"])["isError"])


def _certifying_record(case):
    """An estate revision that certifies the vector token's kid and key at its clock (DL-14)."""
    import copy
    import datetime as dt
    estate = json.loads((Path(__file__).resolve().parent / "fixtures/contract/estate-vectors.json").read_text())
    jwks = case["options"].get("jwks") or VECTORS["jwks"]
    kid = case["expected"]["kid"]
    now = case["options"]["now"]
    iso = lambda seconds: dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = copy.deepcopy(estate["digests"][0]["record"])
    record["issuedAt"], record["validUntil"] = iso(now - 3600), iso(now + 3600)
    record["machines"][0]["hubKey"] = {**record["machines"][0]["hubKey"], "kid": kid,
                                       "x": next(k["x"] for k in jwks["keys"] if k.get("kid") == kid)}
    return record


class EstateNullFailsClosed(unittest.TestCase):
    """D3 (FAA-78, finding 44): an omitted estate option skips DL-14; an explicit null fails closed, as in Node."""

    def setUp(self):
        self.case = next(c for c in VECTORS["delegation"] if c["expected"].get("ok"))
        self.record = _certifying_record(self.case)

    def verify(self, **estate):
        o = self.case["options"]
        return dl.verify_delegation(self.case["token"], audience=o["audience"], jwks=o.get("jwks") or VECTORS["jwks"],
                                    now=o["now"], capability=o["capability"], effect=o["effect"], issuer=o["issuer"], **estate)

    def test_omitted_options_skip_the_rule_and_a_record_certifies(self):
        self.assertTrue(self.verify()["ok"])
        self.assertTrue(self.verify(estate=self.record)["ok"])
        self.assertTrue(self.verify(estate=self.record, estate_applied={"revision": self.record["revision"]})["ok"])
        self.assertTrue(self.verify(estate=self.record, estate_revocations=[])["ok"])

    def test_an_explicit_null_is_unreadable(self):
        for name, estate in (("estate", {"estate": None}),
                             ("estate source", {"estate": lambda: None}),
                             ("applied", {"estate": self.record, "estate_applied": None}),
                             ("revocations", {"estate": self.record, "estate_revocations": None})):
            with self.subTest(name):
                got = self.verify(**estate)
                self.assertEqual((got["ok"], got.get("code"), got.get("detail")), (False, "issuer-unavailable", "estate-unreadable"))


class JwksKeyIsStrictBase64url(unittest.TestCase):
    """D4 (FAA-78, finding 44): a published `x` is exactly 43 base64url characters that re-encode to themselves."""

    def test_a_loose_x_is_unusable(self):
        case = next(c for c in VECTORS["delegation"] if c["expected"].get("ok"))
        o = case["options"]
        jwks = o.get("jwks") or VECTORS["jwks"]
        kid = case["expected"]["kid"]
        x = next(k["x"] for k in jwks["keys"] if k.get("kid") == kid)
        last = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        noncanonical = x[:-1] + last[last.index(x[-1]) ^ 1]  # the same 32 bytes with a non-zero trailing bit
        for loose in (x + "=", x + "\n", x.replace(x[0], "+", 1) if x[0] in "-_" else "+" + x[1:], noncanonical, " " + x):
            with self.subTest(x=loose):
                keys = {"keys": [dict(k, x=loose) if k.get("kid") == kid else k for k in jwks["keys"]]}
                got = dl.verify_delegation(case["token"], audience=o["audience"], jwks=keys, now=o["now"],
                                           capability=o["capability"], effect=o["effect"], issuer=o["issuer"])
                self.assertEqual((got["ok"], got.get("code"), got.get("detail")), (False, "issuer-unavailable", "unusable-key"))


class TrailingNewline(unittest.TestCase):
    """R1 (finding 14): a token or header with a trailing newline is refused as Node refuses it."""

    def test_a_token_with_a_trailing_newline_is_malformed(self):
        case = VECTORS["delegation"][0]
        o = case["options"]
        got = dl.verify_delegation(case["token"] + "\n", audience=o["audience"], jwks=o.get("jwks") or VECTORS["jwks"],
                                   now=o["now"], capability=o["capability"], effect=o["effect"], issuer=o["issuer"])
        self.assertEqual((got["ok"], got.get("code"), got.get("detail")), (False, "unauthenticated", "malformed"))


class JwksFetchIsBounded(unittest.TestCase):
    """Finding 13: the key set fetch has one deadline for the whole answer, runs outside the cache lock, and a garbage
    answer is issuer-unavailable (None), never an exception out of the gate."""

    def serve(self, mode):
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        self.addCleanup(srv.close)
        stop = threading.Event()
        self.addCleanup(stop.set)

        def handle(conn):
            try:
                conn.recv(4096)
                if mode == "garbage":
                    conn.sendall(b"GARBAGE\r\n\r\n")
                elif mode == "slow-headers":
                    for ch in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        if stop.wait(0.3):
                            break
                        conn.sendall(bytes([ch]))
                else:  # a body trickled one byte at a time, each well inside a per-read timeout
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
                    while not stop.wait(0.3):
                        conn.sendall(b" ")
            except OSError:
                pass
            finally:
                conn.close()

        def accept():
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                threading.Thread(target=handle, args=(conn,), daemon=True).start()
        threading.Thread(target=accept, daemon=True).start()
        return "http://127.0.0.1:%d/jwks" % srv.getsockname()[1]

    def test_a_slow_or_garbage_issuer_answers_none_within_the_deadline(self):
        import time
        saved = dl.JWKS_FETCH_SECONDS
        dl.JWKS_FETCH_SECONDS = 1.0
        self.addCleanup(setattr, dl, "JWKS_FETCH_SECONDS", saved)
        for mode in ("garbage", "slow-headers", "trickle"):
            with self.subTest(mode):
                cache = dl.JwksCache(self.serve(mode))
                start = time.monotonic()
                self.assertIsNone(cache.get("k"))
                self.assertLess(time.monotonic() - start, 4.0)

    def test_the_fetch_runs_outside_the_lock(self):
        now = [1000.0]
        release, entered = threading.Event(), threading.Event()
        def fetch(source):
            if entered.is_set():
                release.wait(5)
            entered.set()
            return VECTORS["jwks"]
        cache = dl.JwksCache("https://hub.example/j", fetch=fetch, clock=lambda: now[0])
        self.assertEqual(cache.get("estate-new"), VECTORS["jwks"])
        self.assertTrue(entered.is_set())
        slow = threading.Thread(target=cache.get, args=("a-kid-it-does-not-hold",))
        slow.start()
        try:
            got = []
            reader = threading.Thread(target=lambda: got.append(cache.get("estate-new")))
            reader.start()
            reader.join(1.0)
            self.assertFalse(reader.is_alive(), "a get for a held kid waited on another caller's fetch")
            self.assertEqual(got, [VECTORS["jwks"]])
        finally:
            release.set()
            slow.join(5)


if __name__ == "__main__":
    unittest.main()
