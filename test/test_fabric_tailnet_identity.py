"""FAA-324: fabric_tailnet_identity.py, a person's identity at every door of a service behind `tailscale serve`, on the
vectors its Node twin answers too (test/fixtures/tailnet-identity/vectors.json)."""
import http.client
import http.server
import importlib
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
ti = importlib.import_module("fabric_tailnet_identity")

FIXTURE = json.loads((Path(__file__).parent / "fixtures/tailnet-identity/vectors.json").read_text(encoding="utf-8"))
L = "Tailscale-User-Login"


def _groups_for(vector):
    problem = vector.get("groupsProblem")
    return ti.GroupsError(problem, "test") if problem else ti.load_groups(FIXTURE["groups"])


class Vectors(unittest.TestCase):
    def test_the_groups_file_normalizes(self):
        self.assertEqual(ti.load_groups(FIXTURE["groups"]), dict(FIXTURE["normalized"], schema="tailnet-groups/1"))

    def test_every_vector(self):
        for v in FIXTURE["vectors"]:
            with self.subTest(v["name"]):
                got = ti.decide(groups=_groups_for(v), bound=v["bound"], peer=v["peer"],
                                headers=[tuple(h) for h in v["headers"]], door=v["door"], capability=v["capability"])
                expect = v["expect"]
                self.assertEqual(got["code"], expect["code"])
                self.assertEqual(got["status"], expect["status"])
                self.assertEqual(got["allowed"], expect["code"] == "ok")
                self.assertEqual(got["login"], expect["login"])
                self.assertEqual(got["name"], expect["name"])
                self.assertEqual(got["groups"], expect["groups"])
                self.assertEqual(got["reason"], FIXTURE["reasons"][expect["code"]])
                self.assertEqual((got["door"], got["capability"]), (v["door"], v["capability"]))

    def test_every_refusal_code_is_exercised_and_has_its_sentence(self):
        self.assertEqual({v["expect"]["code"] for v in FIXTURE["vectors"]} - {"ok"}, set(ti.REFUSALS))
        self.assertEqual(ti.REASONS, FIXTURE["reasons"])
        self.assertTrue(all(status == 403 for status in ti.REFUSALS.values()))

    def test_bad_groups_files_are_invalid_and_name_the_field(self):
        for case in FIXTURE["badGroups"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ti.GroupsError) as caught:
                    ti.load_groups(case["doc"])
                self.assertEqual(caught.exception.code, "groups-invalid")
                self.assertEqual(caught.exception.where, case["where"])

    def test_good_groups_files_load(self):
        for case in FIXTURE["goodGroups"]:
            with self.subTest(case["name"]):
                ti.load_groups(case["doc"])

    def test_the_bases_door_groups_file_is_read_for_one_service(self):
        dg = FIXTURE["doorGroups"]
        self.assertEqual(ti.load_groups(dg["doc"], service=dg["service"]), dict(dg["normalized"], schema="door-groups/1"))

    def test_door_groups_vectors(self):
        dg = FIXTURE["doorGroups"]
        groups = ti.load_groups(dg["doc"], service=dg["service"])
        for v in dg["vectors"]:
            with self.subTest(v["name"]):
                got = ti.decide(groups=groups, bound="127.0.0.1", peer="127.0.0.1", headers=[(L, v["login"])],
                                door=v["door"], capability=v["capability"])
                self.assertEqual(got["code"], v["code"])

    def test_bad_door_groups_files_are_invalid_and_name_the_field(self):
        for case in FIXTURE["badDoorGroups"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ti.GroupsError) as caught:
                    ti.load_groups(case["doc"], service=case["service"])
                self.assertEqual(caught.exception.code, "groups-invalid")
                self.assertEqual(caught.exception.where, case["where"])

    def test_the_service_reads_the_bases_file_through_tailnet_identity(self):
        dg = FIXTURE["doorGroups"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "door-groups.json"
            path.write_text(json.dumps(dg["doc"]), encoding="utf-8")
            lines = []
            got = ti.TailnetIdentity(path, service=dg["service"], log=lines.append).decide(
                bound="127.0.0.1", peer="127.0.0.1", headers=[(L, "dee@example.org")], door="mcp", capability="cve.scan")
            self.assertEqual(got["code"], "ok")
            closed = ti.TailnetIdentity(path, log=lines.append).decide(
                bound="127.0.0.1", peer="127.0.0.1", headers=[(L, "dee@example.org")], door="mcp", capability="cve.scan")
            self.assertEqual(closed["code"], "groups-invalid")

    def test_the_door_and_capability_are_the_services_own_arguments(self):
        groups = ti.load_groups(FIXTURE["groups"])
        with self.assertRaises(ValueError):
            ti.decide(groups=groups, bound="127.0.0.1", peer="127.0.0.1", headers=[], door="a2a", capability="x")
        for capability in ("", "*", "Scan Now", None):
            with self.assertRaises(ValueError):
                ti.decide(groups=groups, bound="127.0.0.1", peer="127.0.0.1", headers=[], door="mcp",
                          capability=capability)


class Headers(unittest.TestCase):
    def setUp(self):
        self.groups = ti.load_groups(FIXTURE["groups"])

    def decide(self, headers):
        return ti.decide(groups=self.groups, bound="127.0.0.1", peer="127.0.0.1", headers=headers, door="dashboard",
                         capability="vitals")

    def test_a_mapping(self):
        self.assertEqual(self.decide({"tailscale-user-login": "ana@example.com"})["code"], "ok")
        self.assertEqual(self.decide({L: ["ana@example.com", "bo@example.com"]})["code"], "login-ambiguous")

    def test_a_parsed_message_with_a_repeated_header(self):
        message = http.client.parse_headers(__import__("io").BytesIO(
            b"Tailscale-User-Login: ana@example.com\r\ntailscale-user-login: bo@example.com\r\n\r\n"))
        self.assertEqual(self.decide(message)["code"], "login-ambiguous")

    def test_no_answer_carries_a_header_other_than_the_login_and_name(self):
        got = self.decide([(L, "ana@example.com"), ("Authorization", "Bearer example-secret"),
                           ("Tailscale-User-Profile-Pic", "https://example.com/p.png")])
        self.assertNotIn("example-secret", json.dumps(got))
        self.assertNotIn("p.png", json.dumps(got))


class Reload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "groups.json"
        self.lines = []
        self.now = [0.0]

    def tearDown(self):
        self.tmp.cleanup()

    def identity(self, **kw):
        return ti.TailnetIdentity(self.path, log=self.lines.append, clock=lambda: self.now[0], **kw)

    def write(self, doc):
        text = doc if isinstance(doc, str) else json.dumps(doc)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)  # a new inode, as an organization's writer replaces the file

    def ask(self, identity, login="ana@example.com", door="dashboard", capability="vitals"):
        return identity.decide(bound="127.0.0.1", peer="127.0.0.1", headers=[(L, login)], door=door,
                               capability=capability)

    def test_a_missing_file_closes_every_door_and_logs_once(self):
        identity = self.identity()
        self.assertEqual(self.ask(identity)["code"], "groups-unreadable")
        self.assertEqual(self.ask(identity)["code"], "groups-unreadable")
        self.assertEqual(len(self.lines), 1, self.lines)
        self.assertIn("groups-unreadable", self.lines[0])

    def test_the_file_is_read_again_on_change_without_a_restart(self):
        identity = self.identity()
        self.write(FIXTURE["groups"])
        self.assertEqual(self.ask(identity)["code"], "ok")
        changed = json.loads(json.dumps(FIXTURE["groups"]))
        changed["groups"]["ops"] = ["bo@example.com"]
        self.write(changed)
        self.assertEqual(self.ask(identity)["code"], "unknown-login")
        self.assertEqual(self.ask(identity, "bo@example.com")["code"], "ok")
        self.assertEqual(sum("loaded" in line for line in self.lines), 2, self.lines)

    def test_an_in_place_rewrite_is_seen(self):
        identity = self.identity()
        self.path.write_text(json.dumps(FIXTURE["groups"]), encoding="utf-8")
        self.assertEqual(self.ask(identity)["code"], "ok")
        changed = json.loads(json.dumps(FIXTURE["groups"]))
        changed["groups"]["ops"] = ["bo@example.com", "zed@example.com"]  # another size
        self.path.write_text(json.dumps(changed), encoding="utf-8")
        self.assertEqual(self.ask(identity)["code"], "unknown-login")

    def test_a_same_size_rewrite_within_one_timestamp_tick_is_seen(self):
        # Windows' runner left every stat field as it was for a rewrite of the same size (0.83.0's release run): the
        # stat is pinned here, mtime now, so only the content can tell
        import time as clock
        identity = self.identity()
        self.path.write_text(json.dumps(FIXTURE["groups"]), encoding="utf-8")
        pinned = (1, 2, 3, clock.time_ns(), 4)
        identity._stat = lambda: pinned
        self.assertEqual(self.ask(identity)["code"], "ok")
        changed = json.loads(json.dumps(FIXTURE["groups"]))
        changed["groups"]["ops"] = ["bo@example.com", "zed@example.com"]  # "zed" for "Ana": the same size
        self.path.write_text(json.dumps(changed), encoding="utf-8")
        self.assertEqual(self.ask(identity)["code"], "unknown-login")

    def test_an_old_unchanged_stat_is_not_read_again(self):
        identity = self.identity()
        self.path.write_text(json.dumps(FIXTURE["groups"]), encoding="utf-8")
        pinned = (1, 2, 3, 0, 4)  # mtime long ago: the stat alone decides
        identity._stat = lambda: pinned
        self.assertEqual(self.ask(identity)["code"], "ok")
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.ask(identity)["code"], "ok")

    def test_an_invalid_file_closes_every_door_and_its_content_is_never_logged(self):
        identity = self.identity()
        self.write(FIXTURE["groups"])
        self.assertEqual(self.ask(identity)["code"], "ok")
        self.write('{"schema": "tailnet-groups/1", "groups": {"ops": ["secret-login@example.com"]}, ')
        for _ in range(3):
            self.assertEqual(self.ask(identity)["code"], "groups-invalid")
        bad = [line for line in self.lines if "groups-invalid" in line]
        self.assertEqual(len(bad), 1, self.lines)
        self.assertNotIn("secret-login", "\n".join(self.lines))
        self.write(FIXTURE["groups"])
        self.assertEqual(self.ask(identity)["code"], "ok")

    def test_a_valid_json_that_breaks_the_schema_names_its_field(self):
        identity = self.identity()
        self.write({"schema": "tailnet-groups/1", "groups": {"ops": ["ana"]}, "rules": []})
        self.assertEqual(self.ask(identity)["code"], "groups-invalid")
        self.assertIn("groups.ops", self.lines[-1])
        self.assertNotIn('"ana"', self.lines[-1])

    def test_non_finite_numbers_and_bad_encoding_are_invalid(self):
        identity = self.identity()
        self.write('{"schema": "tailnet-groups/1", "groups": {}, "rules": [], "about": NaN}')
        self.assertEqual(self.ask(identity)["code"], "groups-invalid")
        self.path.write_bytes(b'{"schema": "tailnet-groups/1", "about": "\xff", "groups": {}, "rules": []}')
        self.assertEqual(self.ask(identity)["code"], "groups-invalid")

    def test_an_oversized_file_is_invalid(self):
        identity = self.identity()
        doc = dict(FIXTURE["groups"], about="x" * 10)
        text = json.dumps(doc)
        self.write(text + " " * (ti.MAX_GROUPS_BYTES + 1 - len(text)))
        self.assertEqual(self.ask(identity)["code"], "groups-invalid")
        self.assertIn("size", self.lines[-1])

    def test_a_folder_in_place_of_the_file_is_unreadable(self):
        self.path.mkdir()
        self.assertEqual(self.ask(self.identity())["code"], "groups-unreadable")

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "file modes do not stop root, and Windows has no chmod 000")
    def test_a_file_this_account_cannot_read_is_unreadable(self):
        self.write(FIXTURE["groups"])
        os.chmod(self.path, 0)
        try:
            self.assertEqual(self.ask(self.identity())["code"], "groups-unreadable")
        finally:
            os.chmod(self.path, 0o600)

    def test_a_recheck_interval_reads_at_most_that_often(self):
        identity = self.identity(recheck_seconds=5)
        self.write(FIXTURE["groups"])
        self.assertEqual(self.ask(identity)["code"], "ok")
        changed = json.loads(json.dumps(FIXTURE["groups"]))
        changed["groups"]["ops"] = []
        self.write(changed)
        self.now[0] = 4.0
        self.assertEqual(self.ask(identity)["code"], "ok")
        self.now[0] = 5.0
        self.assertEqual(self.ask(identity)["code"], "unknown-login")

    def test_a_negative_interval_is_refused(self):
        with self.assertRaises(ValueError):
            self.identity(recheck_seconds=-1)


class Http(unittest.TestCase):
    """The request helpers on a real loopback server: the bound address and the peer are read from the connection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "groups.json"
        path.write_text(json.dumps(FIXTURE["groups"]), encoding="utf-8")
        identity = ti.TailnetIdentity(path, log=lambda line: None)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                decision = identity.decide_request(self, door="dashboard", capability="vitals")
                if not decision["allowed"]:
                    ti.send_refusal(self, decision)
                    return
                body = json.dumps({"login": decision["login"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.tmp.cleanup()

    def get(self, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.request("GET", "/", headers=headers)
            res = conn.getresponse()
            return res.status, dict(res.getheaders()), json.loads(res.read() or b"{}")
        finally:
            conn.close()

    def test_an_allowed_login(self):
        status, _, body = self.get({L: "Ana@example.com"})
        self.assertEqual((status, body), (200, {"login": "ana@example.com"}))

    def test_a_refusal_is_a_403_with_its_code_and_sentence(self):
        status, headers, body = self.get({})
        self.assertEqual(status, 403)
        self.assertEqual(body, {"error": {"code": "no-login", "message": FIXTURE["reasons"]["no-login"]}})
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertTrue(headers.get("Content-Type", "").startswith("application/json"))

    def test_a_service_bound_beyond_loopback_is_refused_whatever_the_peer(self):
        class Fake:
            client_address = ("127.0.0.1", 50000)
            headers = http.client.parse_headers(__import__("io").BytesIO(b"Tailscale-User-Login: ana@example.com\r\n\r\n"))

            class server:
                server_address = ("0.0.0.0", 8080)

        path = Path(self.tmp.name) / "groups.json"
        decision = ti.TailnetIdentity(path, log=lambda line: None).decide_request(Fake(), door="dashboard",
                                                                                  capability="vitals")
        self.assertEqual(decision["code"], "bind-not-loopback")
        Fake.server.server_address = ("127.0.0.1", 8080)
        identity = ti.TailnetIdentity(path, log=lambda line: None)
        self.assertEqual(identity.decide_request(Fake(), door="dashboard", capability="vitals")["code"], "ok")
        self.assertEqual(identity.decide_request(Fake(), door="dashboard", capability="vitals", bound="::")["code"],
                         "bind-not-loopback")

    def test_refusal_body_refuses_an_allowed_decision(self):
        with self.assertRaises(ValueError):
            ti.refusal_body({"allowed": True, "code": "ok"})


class Schema(unittest.TestCase):
    """The shipped JSON Schema says what load_groups enforces."""

    def setUp(self):
        self.schema = json.loads((SCRIPTS / "tailnet-groups.schema.json").read_text(encoding="utf-8"))

    def test_marker_doors_and_patterns_agree(self):
        props = self.schema["properties"]
        self.assertEqual(props["schema"]["const"], ti.GROUPS_SCHEMA)
        rule = props["rules"]["items"]["properties"]
        self.assertEqual(rule["door"]["enum"], list(ti.DOORS))
        self.assertEqual(props["groups"]["propertyNames"]["pattern"], ti.NAME_PATTERN)
        self.assertEqual(props["groups"]["additionalProperties"]["items"]["pattern"], ti.LOGIN_PATTERN)
        caps = [alt for alt in rule["capabilities"]["oneOf"] if alt.get("type") == "array"][0]
        self.assertEqual(caps["items"]["pattern"], ti.NAME_PATTERN)
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(sorted(self.schema["required"]), ["groups", "rules", "schema"])

    def test_it_ships_with_both_twins(self):
        kit = json.loads((SCRIPTS / "kit.json").read_text(encoding="utf-8"))
        for entry in kit["python"] + kit["node"]:
            if entry["module"] in ("fabric_tailnet_identity", "fabric-tailnet-identity"):
                self.assertEqual(entry.get("data"), ["tailnet-groups.schema.json"])


if __name__ == "__main__":
    unittest.main()
