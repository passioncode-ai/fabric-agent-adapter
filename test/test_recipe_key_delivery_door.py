"""FAA-238: the key-delivery door template. Both twins run against a fake issuer and a test sealer that encrypts nothing
(the standard library has no HPKE): the envelope on stdout, no value anywhere else, the exit codes Observatory's
`receive --from-command` maps, and only a transport failure retried."""
import base64
import hashlib
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"
RECIPE = SKILL / "recipes/key-delivery-door"
NODE = shutil.which("node")
VALUE = "test-only-key-value-0123456789abcdef"  # not a key: a fixed test string the door must never print
spec = importlib.util.spec_from_file_location("key_delivery_door", RECIPE / "door.py")
door = importlib.util.module_from_spec(spec)
spec.loader.exec_module(door)

# The contract's positive fixture at the adapter's pin (fixtures/positive/credential-envelope-org.json, DEC-0111).
ORG_FIXTURE = {"header": {"type": "fabric-credential-envelope/1", "suite": [16, 1, 1], "sequence": 1,
                          "iat": "2026-10-23T09:59:00Z", "exp": "2026-10-23T21:59:00Z", "provider": "cloudflare",
                          "slot": "CLOUDFLARE_API_TOKEN", "agentRef": "urn:fabric:agent:passioncode:dns-agent", "alg": "EdDSA",
                          "recipient": "m-a#kem", "signer": "org-7f3a.policy-2026-10", "context": "org:org-7f3a",
                          "requestId": "5b1f0c4e-8a2d-4f3b-9c6e-1d7a2b3c4d5e", "credentialExpiresAt": "2026-10-30T09:59:00Z",
                          "enc": "BBf9Oz3fV5rqvAKG1My9E4dTuLauzl7QehYDHyg0vZKqI8PdrDNsDlfq9hoX7iQbiczsnEg-bxJHAN0VTBOcEdE"},
               "ct": "KQonsrRvBVbRfqRafJ8-BVOB_3MSniityQSpND14It7zPmKOjIL3yJ5ra-Vm",
               "sig": "cG4jA54mYV2T075af4KVrn2LoZDKQAKgweZ861-AmD9Cu92aNxMAwXnAMWQ8xWV-0vbaERujFQ4LzWgQo2gkBw"}

FAKES = r'''
import base64, datetime, hashlib, json, os, sys
mode, state = sys.argv[1], sys.argv[2]
data = json.loads(sys.stdin.read() or "{}")
VALUE = "test-only-key-value-0123456789abcdef"
def count():
    n = int(open(state).read()) if os.path.exists(state) else 0
    open(state, "w").write(str(n + 1))
    return n + 1
if mode.startswith("issuer"):
    n = count()
    if mode == "issuer-refuses": print(json.dumps({"refused": {"code": "over-limit"}})); sys.exit(0)
    if mode == "issuer-exit": print("refused " + VALUE, file=sys.stderr); sys.exit(1)
    if mode == "issuer-empty": print("{}"); sys.exit(0)
    if mode == "issuer-down": sys.exit(75)
    if mode == "issuer-flaky" and n < 3: sys.exit(75)
    answer = {"value": VALUE}
    if data.get("context", "personal") != "personal": answer["credentialExpiresAt"] = "2099-01-05T00:00:00Z"
    print(json.dumps(answer)); sys.exit(0)
# the test sealer: shape only, it encrypts and signs nothing
if mode == "seal-refuses": sys.exit(1)
h = dict(data["header"])
org = h["context"] != "personal"
# a fixed clock: the twins are compared byte for byte, so a second boundary between their runs must not show (0.80.0 seam)
iat = datetime.datetime(2099, 1, 1) if org else datetime.datetime(2026, 11, 12, 9, 0, 0)
h.update({"alg": "EdDSA" if org else "ES256", "suite": [16, 1, 1], "signer": "m-a#sig", "sequence": 1,
          "iat": iat.isoformat() + "Z", "exp": (iat + datetime.timedelta(hours=12)).isoformat() + "Z",
          "enc": base64.urlsafe_b64encode(b"\x04" + b"e" * 64).decode().rstrip("=")})
if mode == "seal-wrong-slot": h["slot"] = "OTHER_SLOT"
ct = data["value"] if mode == "seal-clear" else base64.urlsafe_b64encode(hashlib.sha256(data["value"].encode()).digest()).decode().rstrip("=")
print(json.dumps({"header": h, "ct": ct, "sig": "s" * 86}))
'''


class Door(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="key-door-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.fakes = self.dir / "fakes.py"
        self.fakes.write_text(FAKES)

    def cmd(self, mode, twin):
        return "%s %s %s %s" % (shlex.quote(sys.executable), shlex.quote(str(self.fakes)), mode,
                                shlex.quote(str(self.dir / ("%s-%s.count" % (mode, twin)))))

    def run_twin(self, twin, issuer="issuer", sealer="seal", context="personal", extra=()):
        args = ["--slot", "EXAMPLE_KEY", "--provider", "example-issuer", "--agent-ref", "urn:fabric:agent:example:example-agent",
                "--recipient", "m-b#kem", "--context", context, "--issuer-command", self.cmd(issuer, twin),
                "--seal-command", self.cmd(sealer, twin), *extra]
        if context != "personal" and "--request-id" not in extra:
            args += ["--request-id", "5b1f0c4e-8a2d-4f3b-9c6e-1d7a2b3c4d5e"]
        exe = [sys.executable, str(RECIPE / "door.py")] if twin == "py" else [NODE, str(RECIPE / "door.mjs")]
        return subprocess.run(exe + args, capture_output=True, text=True, timeout=60)

    def both(self, *a, **k):
        runs = {"py": self.run_twin("py", *a, **k)}
        if NODE:
            runs["node"] = self.run_twin("node", *a, **k)
        for twin, run in runs.items():
            self.assertNotIn(VALUE, run.stdout + run.stderr, twin)
        if NODE:
            self.assertEqual((runs["node"].returncode, runs["node"].stdout), (runs["py"].returncode, runs["py"].stdout))
        return runs["py"]

    def test_a_delivery_prints_one_envelope_and_nothing_else(self):
        for context in ("personal", "org:example-org"):
            run = self.both(context=context)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(run.stdout.splitlines()), 1)
            envelope = json.loads(run.stdout)
            self.assertEqual(door.envelope_problems(envelope, {"slot": "EXAMPLE_KEY", "context": context}), [])
            self.assertEqual(envelope["header"]["recipient"], "m-b#kem")
            self.assertEqual("credentialExpiresAt" in envelope["header"], context != "personal")
            self.assertEqual(sorted(p.name for p in self.dir.iterdir() if not p.name.endswith(".count")), ["fakes.py"])

    def test_each_refusal_has_its_exit_code(self):
        for issuer, sealer, code in (("issuer-refuses", "seal", 3), ("issuer-exit", "seal", 3), ("issuer-empty", "seal", 4),
                                     ("issuer", "seal-refuses", 5), ("issuer", "seal-wrong-slot", 5), ("issuer", "seal-clear", 5)):
            run = self.both(issuer=issuer, sealer=sealer)
            self.assertEqual((run.returncode, run.stdout), (code, ""), (issuer, sealer, run.stderr))

    def test_usage_is_exit_2(self):
        self.assertEqual(self.both(extra=("--slot", "lower")).returncode, 2)
        self.assertEqual(self.both(context="org:example-org", extra=("--request-id", "nope")).returncode, 2)
        self.assertEqual(self.both(extra=("--request-id", "5b1f0c4e-8a2d-4f3b-9c6e-1d7a2b3c4d5e")).returncode, 2)

    def test_only_a_transport_failure_is_retried(self):
        run = self.run_twin("py", issuer="issuer-flaky")  # two failures, then the key: three tries
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual((self.dir / "issuer-flaky-py.count").read_text(), "3")
        self.assertEqual(self.run_twin("py", issuer="issuer-refuses").returncode, 3)
        self.assertEqual((self.dir / "issuer-refuses-py.count").read_text(), "1")
        slept = []
        calls = []

        def down(request):
            calls.append(request)
            raise door.Transport("down")
        with self.assertRaises(door.Refusal) as caught:
            door.deliver({"slot": "EXAMPLE_KEY", "provider": "x-y", "agentRef": "a", "recipient": "m#kem",
                          "context": "personal"}, down, lambda v, h: None, sleep=slept.append)
        self.assertEqual((caught.exception.code, len(calls), slept), (1, 3, [1.0, 2.0]))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_node_twin_gives_up_after_three_tries_too(self):
        run = self.run_twin("node", issuer="issuer-down")
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual((self.dir / "issuer-down-node.count").read_text(), "3")


class Shape(unittest.TestCase):
    def test_the_contracts_fixture_reads_and_its_breaks_do_not(self):
        self.assertEqual(door.envelope_problems(ORG_FIXTURE, {}), [])
        broken = json.loads(json.dumps(ORG_FIXTURE))
        del broken["header"]["requestId"]
        self.assertIn("an organization's envelope names requestId and credentialExpiresAt", door.envelope_problems(broken, {}))
        broken = json.loads(json.dumps(ORG_FIXTURE))
        broken["header"]["exp"] = "2026-10-25T09:59:00Z"
        self.assertIn("exp is after iat and at most 24 hours later", door.envelope_problems(broken, {}))
        self.assertIn("header slot is not the one asked for", door.envelope_problems(ORG_FIXTURE, {"slot": "OTHER"}))
        self.assertEqual(door.envelope_problems({"header": {}, "ct": "x", "sig": "y", "value": VALUE}, {}), ["not {header, ct, sig}"])


class Prose(unittest.TestCase):
    def test_the_readme_states_the_door_rules(self):
        text = (RECIPE / "README.md").read_text(encoding="utf-8")
        for needed in ("writes into no store", "fabric-credential-envelope/1", "vault.py\" receive", "--from-command",
                       "| 0 |", "| 2 |", "| 3 |", "| 4 |", "| 5 |", "Only a transport failure is retried", "OBS-360"):
            self.assertIn(needed, text)
        self.assertIn("recipes/key-delivery-door/README.md", (SKILL / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
