"""fabric-package/1 in the Python kit (contract DEC-0050, DEC-0051, DEC-0071, DEC-0074; FAA-27a), held to the contract's
vectors as test/fixtures/contract/package-vectors.json vendors them, and pack / sign / verify on real folders. The keys
are the contract's published test keys (their seeds are in the vectors); they sign nothing real."""

import base64
import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fp = importlib.import_module("fabric_package")

VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/contract/package-vectors.json").read_text())
V = VECTORS["vectors"]
PEM_LABEL = "PRIVATE " + "KEY"  # split, so no scanner mistakes this test for a key


def b64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class VectorTests(unittest.TestCase):
    def test_digest_and_signing_input(self):
        self.assertEqual(fp.package_digest(V["digest"]["package"]), V["digest"]["expected"])
        self.assertEqual(fp.package_signing_input(V["signingInput"]["digest"], V["signingInput"]["role"]).decode(), V["signingInput"]["utf8"])
        self.assertEqual(fp.agent_ref_of("example", "inbox-digest"), V["digest"]["package"]["agentRef"])

    def test_the_folder_check(self):
        files = {p: t.encode() for p, t in V["folder"]["files"].items()}
        self.assertEqual(fp.check_package_folder(V["digest"]["package"], files), V["folder"]["expected"])

    def test_every_verifier_case(self):
        for case in V["cases"]:
            with self.subTest(case["name"]):
                got = fp.verify_package(case["package"], case["trust"], bool((case.get("options") or {}).get("countersigned")))
                self.assertEqual(got, case["expected"])

    def test_the_signer_reproduces_every_signature_from_its_seed(self):
        """Ed25519 is deterministic: each vector signature made by a seeded key is the one this signer makes."""
        seeds = {k["jwk"]["kid"]: bytes.fromhex(k["seed"]) for k in V["keys"].values() if "seed" in k}
        for name, key in V["keys"].items():
            if "seed" in key:
                self.assertEqual(b64url(fp.ed25519_public_key(bytes.fromhex(key["seed"]))), key["jwk"]["x"], name)
        checked = 0
        for case in V["cases"]:
            if case["expected"].get("ok") is not True:
                continue
            for entry in case["package"].get("signatures", []):
                if entry["kid"] in seeds:
                    sig = fp.ed25519_sign(seeds[entry["kid"]], fp.package_signing_input(case["package"]["digest"], entry["role"]))
                    self.assertEqual(b64url(sig), entry["sig"], case["name"])
                    checked += 1
        self.assertGreaterEqual(checked, 3)

    def test_the_schema_answers_every_fixture_as_the_catalogue_lists_it(self):
        for fixture in VECTORS["fixtures"]:
            with self.subTest(fixture["name"]):
                problems = fp.schema_problems(fixture["document"])
                self.assertEqual(not problems, fixture["valid"], problems)

    def test_the_rules_answer_every_semantic_fixture(self):
        for fixture in VECTORS["semantic"]:
            with self.subTest(fixture["name"]):
                got = [{"code": f["code"], "instancePath": f["instancePath"]} for f in fp.package_findings(fixture["document"])]
                self.assertEqual(got, fixture["findings"])
        for fixture in VECTORS["fixtures"]:
            if fixture["valid"]:
                self.assertEqual(fp.package_findings(fixture["document"]), [], fixture["name"])

    def test_consumer_placement(self):
        consumer = next(f["document"] for f in VECTORS["fixtures"] if f["name"] == "fabric-package-consumer-agent")
        roles = [r["role"] for r in consumer["requires"]["mcp"]]
        self.assertEqual(fp.consumer_placement(consumer, None), [{"problem": "missing-role", "role": r} for r in roles])
        full = {r["role"]: list(r["tools"]) for r in consumer["requires"]["mcp"]}
        self.assertEqual(fp.consumer_placement(consumer, full), [])
        first = consumer["requires"]["mcp"][0]
        short = dict(full, **{first["role"]: first["tools"][1:]})
        self.assertEqual(fp.consumer_placement(consumer, short), [{"problem": "missing-tool", "role": first["role"], "tool": first["tools"][0]}])
        self.assertEqual(fp.consumer_placement(consumer, {r: t for r, t in full.items() if r != first["role"]}),
                         [{"problem": "missing-role", "role": first["role"]}])


def write_agent(root, **draft_extra):
    """The vector agent's folder, with its author's draft: what pack fills in (agentRef, files, digest) left out."""
    for path, text in V["folder"]["files"].items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    draft = copy.deepcopy(V["digest"]["package"])
    for key in ("agentRef", "files", "digest", "signatures"):
        draft.pop(key, None)
    draft.update(draft_extra)
    (root / fp.PACKAGE_FILE).write_text(json.dumps(draft, indent=2) + "\n")
    return draft


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "inbox-digest"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, name="publisher", mode=0o600, **jwk_extra):
        k = V["keys"][name]
        jwk = dict(k["jwk"], d=b64url(bytes.fromhex(k["seed"])), **jwk_extra)
        path = Path(self.tmp.name) / ("%s.jwk" % name)
        path.write_text(json.dumps(jwk))
        path.chmod(mode)
        return path

    def test_pack_rebuilds_the_vector_package_byte_for_byte(self):
        write_agent(self.root)
        before = (self.root / fp.PACKAGE_FILE).read_bytes()
        answer = fp.pack(self.root)
        self.assertTrue(answer["ok"], answer["problems"])
        self.assertFalse(answer["applied"])
        self.assertEqual((self.root / fp.PACKAGE_FILE).read_bytes(), before, "a dry run writes nothing")
        expected = {k: v for k, v in V["digest"]["package"].items() if k != "signatures"}
        self.assertEqual(answer["package"], expected)
        self.assertEqual(list(answer["package"]), list(expected), "the author's order, agentRef after publisher, files and digest last")
        self.assertEqual(answer["digest"], V["digest"]["expected"])
        self.assertEqual(answer["agentRef"], "urn:fabric:agent:example:inbox-digest")
        self.assertTrue(fp.pack(self.root, apply=True)["applied"])
        written = (self.root / fp.PACKAGE_FILE).read_text()
        self.assertEqual(written, json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
        again = fp.pack(self.root)
        self.assertTrue(again["ok"], "packing a packed folder again is stable")
        self.assertEqual(again["digest"], V["digest"]["expected"])

    def test_pack_refuses_what_must_not_ship(self):
        write_agent(self.root)
        for name in (".env", ".env.local", "deploy.pem", "signing.key", "id_ed25519", ".npmrc", ".DS_Store", "x.pyc"):
            (self.root / name).write_text("x")
            with self.assertRaises(fp.PackageError) as caught:
                fp.pack(self.root)
            self.assertIn(name, str(caught.exception))
            (self.root / name).unlink()
        (self.root / ".env.example").write_text("EXAMPLE_TOKEN_FILE=\n")
        self.assertIn(".env.example", [f["path"] for f in fp.pack(self.root)["package"]["files"]])
        (self.root / ".env.example").unlink()
        for litter in (".git", "__pycache__"):
            (self.root / "bin" / litter).mkdir()
            with self.assertRaisesRegex(fp.PackageError, "bin/%s" % litter):
                fp.pack(self.root)
            (self.root / "bin" / litter).rmdir()
        os.symlink("/etc/hosts", self.root / "hosts")
        with self.assertRaisesRegex(fp.PackageError, "symlink"):
            fp.pack(self.root)
        (self.root / "hosts").unlink()
        self.assertTrue(fp.pack(self.root)["ok"])
        with self.assertRaisesRegex(fp.PackageError, "not a folder"):
            fp.pack(self.root / "nowhere")
        (self.root / fp.PACKAGE_FILE).write_text('{"schema": "fabric-package/1", "schema": "x"}')
        with self.assertRaisesRegex(fp.PackageError, "twice"):
            fp.pack(self.root)
        (self.root / fp.PACKAGE_FILE).unlink()
        with self.assertRaisesRegex(fp.PackageError, "first"):
            fp.pack(self.root)

    def test_pack_names_every_problem_and_writes_nothing(self):
        write_agent(self.root)
        (self.root / fp.PLUGIN_MANIFEST).write_text(json.dumps({"name": "inbox-digest", "version": "9.9.9"}))
        answer = fp.pack(self.root, apply=True)
        self.assertFalse(answer["ok"])
        self.assertFalse(answer["applied"])
        self.assertIn({"rule": "folder", "problem": "plugin-manifest", "instancePath": fp.PLUGIN_MANIFEST, "message": "plugin-manifest"}, answer["problems"])
        self.assertNotIn('"digest": "sha256:', (self.root / fp.PACKAGE_FILE).read_text())
        write_agent(self.root, version="1.2")
        self.assertIn("/version", [p["instancePath"] for p in fp.pack(self.root)["problems"] if p["rule"] == "schema"])
        write_agent(self.root, secrets=[{"name": "INBOX_TOKEN", "purpose": "reads the mailbox"}, {"name": "INBOX_TOKEN", "purpose": "again"}])
        self.assertIn("FAC-SEM-065", [p["rule"] for p in fp.pack(self.root)["problems"]])

    def test_pack_refuses_a_chosen_agent_ref_and_a_stale_receipt(self):
        write_agent(self.root, agentRef="urn:fabric:agent:example:other")
        with self.assertRaisesRegex(fp.PackageError, "urn:fabric:agent:example:inbox-digest"):
            fp.pack(self.root)
        write_agent(self.root, agentRef="urn:fabric:agent:example:inbox-digest")
        self.assertTrue(fp.pack(self.root)["ok"], "the derived value written by hand is accepted")
        write_agent(self.root)
        (self.root / "evals/suite.json").write_text('{"cases": []}\n')
        answer = fp.pack(self.root)
        self.assertFalse(answer["ok"])
        self.assertIn("/evals/receipt/suite", [p.get("instancePath") for p in answer["problems"]])
        self.assertTrue(any("run it again" in n for n in answer["notes"]))

    def test_pack_drops_old_signatures(self):
        write_agent(self.root, signatures=[{"role": "publisher", "alg": "EdDSA", "kid": "x", "sig": "AA"}])
        answer = fp.pack(self.root)
        self.assertNotIn("signatures", answer["package"])
        self.assertTrue(any("dropped 1 signature" in n for n in answer["notes"]))

    def test_sign_then_verify(self):
        write_agent(self.root)
        fp.pack(self.root, apply=True)
        self.assertTrue(fp.sign(self.root, self.key())["ok"])
        self.assertNotIn("signatures", json.loads((self.root / fp.PACKAGE_FILE).read_text()), "a dry run writes nothing")
        signed = fp.sign(self.root, self.key(), apply=True)
        pub = V["keys"]["publisher"]["jwk"]
        self.assertEqual(signed["publicKey"], dict(pub, use="sig"))
        case = next(c for c in V["cases"] if c["name"].startswith("a publisher signature alone"))
        self.assertEqual(signed["signature"], case["package"]["signatures"][0], "the signature is the vector's own")
        trust = {"publisher": [pub]}
        self.assertTrue(fp.verify(self.root, trust)["ok"])
        self.assertTrue(fp.sign(self.root, self.key("organization"), role="organization", apply=True)["ok"])
        full = {"publisher": [pub], "organization": [V["keys"]["organization"]["jwk"]]}
        verdict = fp.verify(self.root, full, countersigned=True)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual([s["role"] for s in verdict["verdict"]["signers"]], ["publisher", "organization"])
        self.assertTrue(fp.sign(self.root, self.key(), apply=True)["ok"])
        sigs = json.loads((self.root / fp.PACKAGE_FILE).read_text())["signatures"]
        self.assertEqual([s["role"] for s in sigs], ["publisher", "organization"], "re-signing keeps one publisher signature")
        self.assertTrue(fp.sign(self.root, self.key("organization"), role="organization", apply=True)["ok"])
        sigs = json.loads((self.root / fp.PACKAGE_FILE).read_text())["signatures"]
        self.assertEqual(len(sigs), 2, "the same organization key is replaced, not added")
        (self.root / "bin/serve.mjs").write_text("// changed after signing\n")
        changed = fp.verify(self.root, full)
        self.assertFalse(changed["ok"])
        self.assertIn("file-digest", [p.get("problem") for p in changed["problems"]])
        refused = fp.sign(self.root, self.key())
        self.assertFalse(refused["ok"], "a folder that no longer matches its package is not signed")
        self.assertFalse(refused["applied"])

    def test_the_key_file(self):
        write_agent(self.root)
        fp.pack(self.root, apply=True)
        if os.name == "posix":
            with self.assertRaisesRegex(fp.PackageError, "chmod 600"):
                fp.sign(self.root, self.key(mode=0o644))
        with self.assertRaisesRegex(fp.PackageError, "disagrees"):
            fp.sign(self.root, self.key(), kid="another")
        with self.assertRaisesRegex(fp.PackageError, "not the public key"):
            fp.sign(self.root, self.key(x=V["keys"]["stranger"]["jwk"]["x"]))
        with self.assertRaisesRegex(fp.PackageError, "EdDSA"):
            fp.sign(self.root, self.key(alg="ES256"))
        with self.assertRaisesRegex(fp.PackageError, "Cannot read"):
            fp.sign(self.root, Path(self.tmp.name) / "absent.jwk")
        seed = bytes.fromhex(V["keys"]["publisher"]["seed"])
        pem = Path(self.tmp.name) / "key.pem"
        der = bytes.fromhex("302e020100300506032b657004220420") + seed
        pem.write_text("-----BEGIN %s-----\n%s\n-----END %s-----\n" % (PEM_LABEL, base64.b64encode(der).decode(), PEM_LABEL))
        pem.chmod(0o600)
        with self.assertRaisesRegex(fp.PackageError, "--kid"):
            fp.sign(self.root, pem)
        by_pem = fp.sign(self.root, pem, kid=V["keys"]["publisher"]["jwk"]["kid"])
        self.assertEqual(by_pem["signature"]["sig"], fp.sign(self.root, self.key())["signature"]["sig"])
        if shutil.which("openssl"):
            made = Path(self.tmp.name) / "made.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(made)], check=True, capture_output=True)
            made.chmod(0o600)
            answer = fp.sign(self.root, made, kid="example-2026")
            pkg = dict(json.loads((self.root / fp.PACKAGE_FILE).read_text()), signatures=[answer["signature"]])
            self.assertTrue(fp.verify_package(pkg, {"publisher": [answer["publicKey"]]})["ok"], "a key openssl made verifies")

    def test_the_command_line(self):
        write_agent(self.root)

        def run(*args):
            return subprocess.run([sys.executable, str(SCRIPTS / "fabric_package.py"), *args], capture_output=True, text=True)

        out = run("pack", str(self.root))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(json.loads(out.stdout)["digest"], V["digest"]["expected"])
        self.assertEqual(run("pack", str(self.root), "--apply").returncode, 0)
        signed = run("sign", str(self.root), "--key", str(self.key()), "--apply")
        self.assertEqual(signed.returncode, 0, signed.stdout)
        trust = Path(self.tmp.name) / "trust.json"
        trust.write_text(json.dumps({"publisher": [V["keys"]["publisher"]["jwk"]]}))
        self.assertEqual(run("verify", str(self.root), "--trust", str(trust)).returncode, 0)
        refused = run("verify", str(self.root), "--trust", str(trust), "--countersigned")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["verdict"]["problem"], "no-countersignature")
        missing = run("pack", str(Path(self.tmp.name) / "nowhere"))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("not a folder", json.loads(missing.stdout)["error"])
        self.assertEqual(run("pack").returncode, 2)
        private = b64url(bytes.fromhex(V["keys"]["publisher"]["seed"]))
        for result in (out, signed, refused):
            self.assertNotIn(private, result.stdout + result.stderr, "the private key never reaches the output")


if __name__ == "__main__":
    unittest.main()
