"""The Python kit's delegation verifier (DEC-0039) against the shared vectors, whose expected answers come from
the contract's own verifier at the pin (test/fixtures/delegation/make_vectors.mjs)."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

from test_fabric_service import SCRIPTS, load

dl = load("fabric_delegation")
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
        self.assertIsNotNone(dl._decode_point((1).to_bytes(32, "little")))
        self.assertIsNone(dl._decode_point((2 ** 255 - 19 + 1).to_bytes(32, "little")))


class VerifierVectorTests(unittest.TestCase):
    def test_every_delegation_case_answers_as_the_contract_does(self):
        for case in VECTORS["delegation"]:
            with self.subTest(case["name"]):
                got = dl.verify_delegation(case["token"], **options(case["options"]))
                self.assertEqual(answer(got), case["expected"])
        self.assertGreaterEqual(len(VECTORS["delegation"]), 60)

    def test_every_approval_case_answers_as_the_contract_does(self):
        for case in VECTORS["approvals"]:
            store = dl.MemoryJtiStore()
            for i, step in enumerate(case["steps"]):
                with self.subTest(case["name"], step=i):
                    got = dl.verify_approval(step["approval"], **options(step["options"], store))
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
                                              now=1, capability="writer.write", effect="draft")["code"], "issuer-unavailable")

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
        plain = fi.McpToolServer("x", "0.1.0")
        plain.add_tool({"name": "writer.write", "inputSchema": {"type": "object"}}, lambda args, ctx: {"d": ctx.delegation})
        self.assertEqual(plain.handle(call)["result"]["structuredContent"], {"d": None})


if __name__ == "__main__":
    unittest.main()
