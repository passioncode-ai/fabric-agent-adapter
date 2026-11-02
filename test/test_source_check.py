"""fabric_source_check.py: instance data in an agent's source, found and never repeated (FAA-188 part 1)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
spec = importlib.util.spec_from_file_location("fabric_source_check", SCRIPTS / "fabric_source_check.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

# Every value the check must find is assembled at run time, so none sits in this file as a literal.
HOME_NAME = "jdoe" + "smith"
MAC_HOME = "/Users/" + HOME_NAME + "/projects/notes"
LINUX_HOME = "/home/" + HOME_NAME + "/.config/agent"
WIN_HOME = "C:\\" + "Users\\" + HOME_NAME + "\\agent\\data"
WIN_HOME_JSON = "C:\\\\" + "Users\\\\" + HOME_NAME + "\\\\agent"
WIN_HOME_SLASH = "C:/" + "Users/" + HOME_NAME + "/agent"
FAKE_GITHUB = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"
FAKE_OPENAI = "sk" + "-" + "proj" + "Abcdefghijklmnop0123456789"
LONG_RANDOM = "Ab3" * 14  # 42 characters mixing upper case, lower case and digits
FAKE_JWT = "ey" + "J" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
OWNER = "Acme" + "Holdings"
ACCOUNT = "owner-" + "account-77"


def _package_module():
    """The kit's packer, to show the check reads every file `pack` carries."""
    import sys
    kit = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
    if str(kit) not in sys.path:
        sys.path.insert(0, str(kit))  # its sibling modules import each other by name
    found = importlib.util.spec_from_file_location("fabric_package", kit / "fabric_package.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sc.run(argv)
    return code, out.getvalue(), err.getvalue()


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "agent"
        self.root.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        home = str(self.tmp / "home")
        self.env = mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home, "XDG_CONFIG_HOME": home + "/cfg",
                                                "APPDATA": home + "/cfg"})
        self.env.start()
        os.environ.pop("FABRIC_INSTANCE_STRINGS", None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text, mode="w"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "wb":
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def owner_list(self, *lines):
        path = self.outside / "instance-strings.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def json_check(self, *extra):
        code, out, err = run(["check", str(self.root), "--json", *extra])
        return code, json.loads(out) if out else None, out + err


class Findings(Tree):
    def test_a_clean_tree_exits_zero(self):
        self.write("README.md", "# example-agent\n\nData lives in ~/.local/share/example-agent or $EXAMPLE_AGENT_DATA_DIR.\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["blocking"])

    def test_home_paths_on_every_platform(self):
        forms = (MAC_HOME, LINUX_HOME, WIN_HOME, WIN_HOME_JSON, WIN_HOME_SLASH, WIN_HOME.lower(),
                 "/var" + "/home/" + HOME_NAME + "/x", "cwd: -" + "Users-" + HOME_NAME + "-DATA-proj",
                 "url=file:%2F" + "Users%2F" + HOME_NAME + "%2Fx", "cwd: C--" + "Users-" + HOME_NAME + "-DATA-proj",
                 "c--" + "Users-" + HOME_NAME + "-x", "c--" + "users-" + HOME_NAME + "-x", "/c/" + "Users/" + HOME_NAME + "/x", "/mnt/c/" + "Users/" + HOME_NAME,
                 "C%3A%5C" + "Users%5C" + HOME_NAME + "%5Cx", "cwd: -var-" + "home-" + HOME_NAME + "-proj",
                 "x -mnt-c-" + "Users-" + HOME_NAME + "-proj", "x -c-" + "Users-" + HOME_NAME + "-proj")
        for i, value in enumerate(forms):
            self.write("cfg%d.txt" % i, "path = %s\n" % value)
        code, result, _ = self.json_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(f["path"] for f in result["findings"]), sorted("cfg%d.txt" % i for i in range(len(forms))))
        self.assertTrue(all(f["kind"] == "home-path" and f["line"] == 1 for f in result["findings"]))

    def test_neutral_homes_and_placeholders_are_not_findings(self):
        u, h = "/" + "Users/", "/" + "home/"
        self.write("doc.md", "\n".join([u + "example/agent", h + "runner/work", u + "Shared/x", h + "<you>/x",
                                         "C:\\" + "Users\\example\\x", u + "$USER/x", "~/agent", h + "user/x",
                                         h + "node/app", h + "ubuntu/x", h + "ec2-user/x", "C:\\" + "Users\\runneradmin\\x"]) + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_synthetic_values_and_one_letter_homes_are_not_findings(self):
        self.write("doc.md", "\n".join(["AKIA" + "IOSFODNN7" + "EXAMPLE", "sk" + "-or-v1-test-only-not-a-key",
                                         "sk" + "-fake0123456789abcdef", "/" + "Users/a/Library", "C:/" + "Users/b/x"]) + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_web_routes_flags_and_css_are_not_home_paths(self):
        self.write("app.js", "\n".join(['fetch("/" + "users/profile")', 'login("/login?next=%2F' + 'users%2Fsettings")', "router.push('/" + "users/settings')",
                                          "cli --" + "home-dir ./x", 'add_argument("--' + 'users-file")',
                                          "color: var(--" + "home-hero-bg);", "Option B--" + "home-grown",
                                          ".a--" + "home-hero {}", "-x--" + "home-dir"]) + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_a_run_of_backslashes_is_read_in_linear_time(self):
        import time
        line = '{"p": "C:' + "\\" * 5000 + 'Program Files"}'
        started = time.monotonic()
        self.assertEqual(sc._home_names(line), [])
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(sc._home_names(WIN_HOME_JSON))

    def test_secret_shapes(self):
        self.write("a.py", "TOKEN = '%s'\n" % FAKE_GITHUB)
        self.write("b.env.txt", "key=%s\n" % FAKE_OPENAI)
        self.write("c.json", '{"jwt": "%s"}\n' % FAKE_JWT)
        self.write("d.pem.txt", PEM + "\n")
        self.write("e.sh", "curl -H 'Authorization: Bearer abcdef0123456789abcd' x\n")
        self.write("f.md", "Bearer token for CI: %s\n" % FAKE_GITHUB)  # a key after prose that starts with the word
        self.write("g.env", "X_API_TOKEN=%s\n" % LONG_RANDOM)
        self.write("h.txt", "checksum = %s\n" % LONG_RANDOM)  # a long run under a name that carries no credential
        code, result, _ = self.json_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(f["path"] for f in result["findings"] if f["kind"] == "secret"),
                         ["a.py", "b.env.txt", "c.json", "d.pem.txt", "e.sh", "f.md", "g.env"])

    def test_a_provider_key_a_dropped_run_swallowed_is_found(self):
        key = "sk" + "-" + "Zq7Wm4" * 4
        for line in ("runner: task-runner-" + key, "risk-" + key, "sk" + "-test-not-a-key-" + key):
            self.assertEqual(sc._secret_finding(line), "a value shaped like a provider key", line[:8])
            self.assertTrue(sc._secret_spans(line), line[:8])
        self.assertIsNone(sc._secret_finding("task-management-service"))
        self.write("a.yaml", "runner: task-runner-%s\n" % key)
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 1)
        self.assertNotIn(key[3:11], out + err)
        start = time.perf_counter()  # a long run of dropped starts is read once, not once a start
        self.assertIsNone(sc._secret_finding(("sk" + "-not-a-key-") * 200000))
        crafted = "a" + "xo" + "xb-" + ("sk" + "-") * 300000 + "_fa" + "ke"  # each inner start ran to the end once
        self.assertIsNone(sc._secret_finding(crafted))
        self.assertEqual(sc._secret_spans(crafted), [])
        self.assertLess(time.perf_counter() - start, 5)

    def test_a_narrow_key_before_a_synthetic_word_is_found(self):
        # a key whose class ends before the synthetic word (ghp_, AKIA, xox) is read by its own end
        for line in ("sk" + "-" + "Zq7W" * 4 + "_" + "gh" + "p_" + "Zq7W" * 9 + "_fa" + "ke",
                     "sk" + "-cfg-" + "AK" + "IA" + "ZQ7WM4ZQ7WM4ZQ7W" + "-fa" + "ke",
                     "sk" + "-" + "Zq7W" * 4 + "_" + "xo" + "xb-" + "Zq7W" * 5 + "_fa" + "ke"):
            self.assertEqual(sc._secret_finding(line), "a value shaped like a provider key", line[:24].count("_"))
            self.assertTrue(sc._secret_spans(line))

    def test_a_provider_key_in_a_query_value_is_judged_by_its_own_word(self):
        key = "sk" + "-" + "Zq7Wm4" * 5
        for url in ("https://h.example/v?keys=%s%%2C%s" % ("sk" + "-test-not-a-key", key),
                    "https://h.example/v?note=fa%ske%%20%s" % ("", key)):
            self.assertEqual(sc._secret_finding(url), "a URL that carries a credential", url[:20])

    def test_a_package_signature_is_public(self):
        sig = ("Ab3" * 29)[:86]  # an Ed25519 signature in base64url: 86 characters mixing cases and digits
        self.write("fabric.package.json", '{"signatures": [{"kid": "publisher", "sig": "%s"}]}\n' % sig)
        self.write("b.json", '{"signature": "%s"}\n' % sig)
        self.assertEqual(self.json_check()[0], 0)
        self.write("c.json", '{"api_key": "%s"}\n' % sig)
        # a storage URL's `sig=` is an HMAC that grants access, not a public signature
        self.write("d.env", "BLOB_URL=https://example.blob.core.windows.net/c?sv=2022&sig=%s%%3D\n" % LONG_RANDOM)
        self.assertEqual([f["path"] for f in self.json_check()[1]["findings"]], ["c.json", "d.env"])

    def test_a_signature_that_holds_a_provider_keys_shape_is_public(self):
        sig = ("Ab3" * 12 + "-sk-" + "Cd4" * 16)[:86]
        self.assertIsNone(sc._secret_finding('{"signatures": [{"kid": "p", "sig": "%s"}]}' % sig))

    def test_a_signature_in_a_url_or_an_env_line_is_a_credential(self):
        sig = ("Ab3" * 29)[:86]  # the shape of a public signature, where only a JSON member is public
        self.write("a.env", "BLOB=https://example.blob.core.windows.net/c?sv=1&sig=%s\n" % sig)
        self.write("b.env", "SIG=%s\n" % sig)
        self.write("c.sh", 'curl -d "sig=%s" https://example.com\n' % sig)  # quoted before, but not a JSON member
        self.write("d.json", '{"query": "signature=%s&sv=1"}\n' % sig)
        self.assertEqual(sorted(f["path"] for f in self.json_check()[1]["findings"]), ["a.env", "b.env", "c.sh", "d.json"])

    def test_a_package_the_kit_signed_passes(self):
        """The seam with `sign`: the vector agent packed and signed by the kit itself, its signatures public."""
        import base64
        packer = _package_module()
        vectors = json.loads((ROOT / "test/fixtures/contract/package-vectors.json").read_text())["vectors"]
        folder = self.root / "inbox-digest"
        for path, text in vectors["folder"]["files"].items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(text.encode("utf-8"))  # bytes: text mode writes CRLF on Windows
        draft = dict(vectors["digest"]["package"])
        for key in ("agentRef", "files", "digest", "signatures"):
            draft.pop(key, None)
        (folder / packer.PACKAGE_FILE).write_bytes((json.dumps(draft, indent=2) + "\n").encode("utf-8"))
        packed = packer.pack(folder, apply=True)
        self.assertTrue(packed["ok"], packed["problems"])
        for role in ("publisher", "organization"):
            k = vectors["keys"][role]
            jwk = dict(k["jwk"], d=base64.urlsafe_b64encode(bytes.fromhex(k["seed"])).decode().rstrip("="))
            key = self.outside / ("%s.jwk" % role)  # the key stays outside the folder, as package.md says
            key.write_text(json.dumps(jwk))
            key.chmod(0o600)
            self.assertTrue(packer.sign(folder, key, role=role, apply=True)["ok"], role)
        self.assertIn('"sig"', (folder / packer.PACKAGE_FILE).read_text())
        for extra in ([], ["--every-file"]):
            code, out, err = run(["check", str(folder), *extra])
            self.assertEqual(code, 0, out + err)

    def test_private_keys_in_every_form(self):
        self.write("a.asc", "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\n")
        self.write("publisher.jwk", '{"kty": "OKP", "crv": "Ed25519", "x": "%s", "d": "%s"}\n' % (LONG_RANDOM, LONG_RANDOM + "Xy9"))  # `d`: 32 bytes, 43 characters
        self.write("env.json", '{"PRIVATE_JWK": "{\\"kty\\":\\"OKP\\",\\"d\\":\\"%s\\"}"}\n' % (LONG_RANDOM + "Xy9"))
        self.write("key.py", "KEY = {'kty': 'OKP', 'd': '%s'}\n" % (LONG_RANDOM + "Xy9"))
        self.write("public.jwk", '{"kty": "OKP", "crv": "Ed25519", "x": "%s"}\n' % LONG_RANDOM)
        code, result, out = self.json_check("--every-file")
        self.assertEqual(sorted(f["path"] for f in result["findings"]), ["a.asc", "env.json", "key.py", "publisher.jwk"])
        self.assertNotIn(LONG_RANDOM, out)

    def test_credential_files_by_name_as_pack_refuses_them(self):
        import secrets as rnd
        if shutil.which("git") is None:
            self.skipTest("git")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".env", "X=1\n")
        self.write(".npmrc", "x\n")
        self.write("data/session.key", rnd.token_bytes(32), mode="wb")
        self.write("data/service.token", rnd.token_urlsafe(32))
        self.write("data/board.credential", rnd.token_urlsafe(32))
        self.write(".env.example", "X=\n")
        for extra in ([], ["--every-file"]):
            code, result, _ = self.json_check(*extra)
            self.assertEqual(code, 1, result)
            named = sorted(f["path"] for f in result["findings"] if f["line"] == 0 and f["kind"] == "secret")
            self.assertEqual(named, [".env", ".npmrc", "data/board.credential", "data/service.token", "data/session.key"],
                             extra)

    def test_the_credential_file_rule_is_packs(self):
        packer = _package_module()
        self.assertEqual(sc.SECRET_FILE.pattern, packer.SECRET_FILE.pattern)
        self.assertEqual(sc.SECRET_FILE_OK.pattern, packer.SECRET_FILE_OK.pattern)

    def test_a_url_that_carries_a_credential(self):
        import base64, secrets as rnd
        from urllib.parse import quote
        sig = ""
        while "%2B" not in sig and "%2F" not in sig:  # Azure writes a SAS signature percent-encoded
            sig = quote(base64.b64encode(rnd.token_bytes(32)).decode(), safe="")
        self.write("a.env", "BLOB_URL=https://a.blob.core.windows.net/c/f?sv=2022-11-02&sig=%s\n" % sig)
        self.write("b.env", "DATABASE_URL=postgres://app:%s@db.internal/app\n" % (LONG_RANDOM[:12] + "9"))
        # what says it is synthetic is the value, never the host: a real signature on an `examples` container
        self.write("c.env", "U=https://examples.blob.core.windows.net/c/f?sv=1&sig=x%%2F%s\n" % sig)
        self.write("doc.md", "See https://example.com/?token=abc and https://user:hunter2@host.example/x\n")
        # outside a URL: a bare SAS token, a YAML key, a connection string, an HTML attribute
        self.write("d.env", "AZURE_STORAGE_SAS_TOKEN=sv=2022-11-02&sig=%s\n" % sig)
        self.write("e.yaml", "sas_token: sv=2022-11-02&sig=%s\n" % sig)
        self.write("f.txt", "BlobEndpoint=https://a.blob.core.windows.net/;SharedAccessSignature=sv=1&sig=%s\n" % sig)
        self.write("g.html", '<a href="https://a.blob.core.windows.net/c?sv=1&amp;sig=%s">x</a>\n' % sig)
        code, result, out = self.json_check()
        self.assertEqual(sorted(f["path"] for f in result["findings"]),
                         ["a.env", "b.env", "c.env", "d.env", "e.yaml", "f.txt", "g.html"])
        self.assertNotIn(sig, out)

    def test_json_escapes_and_a_nested_url_do_not_hide_a_credential(self):
        import base64, secrets as rnd
        from urllib.parse import quote
        sig = quote(base64.b64encode(rnd.token_bytes(32)).decode(), safe="")
        pw = LONG_RANDOM[:15] + "7"
        lines = ('{"sas": "?sv=1\\u0026sig=%s"}' % sig,  # Go's encoding/json writes & as \u0026
                 '{"u": "https://a.blob.core.windows.net/c?sv=1\\u0026sig=%s"}' % sig,
                 '{"db": "postgres:\\/\\/app:%s@h\\/app"}' % pw,  # PHP's json_encode writes / as \/
                 "https://login.example.org/cb?next=" + quote("https://a.blob.core.windows.net/c?sv=1&sig=" + sig, safe=""))
        lines += ('{"u": "https://a.blob.core.windows.net/c?sv=1\\u0026sig\\u003d%s"}' % sig,
                  "https://login.example.org/cb?next=" + quote("https://examples.blob.core.windows.net/c?sig=" + sig, safe=""))
        for line in lines:
            self.assertIsNotNone(sc._secret_finding(line), line)
        # a word that says it is synthetic is read decoded
        self.assertIsNone(sc._secret_finding("postgres://app:not%2Da%2Dkey9x@h/db"))
        self.assertIsNone(sc._secret_finding("API_TOKEN=%s%%66ake" % LONG_RANDOM))

    @unittest.skipIf(os.name == "nt", "a backslash is a separator on Windows")
    def test_a_path_found_only_with_escapes_undone_is_masked_by_segment(self):
        pw = LONG_RANDOM[:15] + "7"
        self.write("d0/https:\\/\\/app:%s@db\\/x.txt" % pw, "x\n")
        self.write("d1/API_TOKEN=%s/https:\\/\\/app:%s@db\\/x.txt" % (LONG_RANDOM, pw), "x\n")  # a spanned one beside it
        self.write("d2/https:\\/\\/app:%s@db/y.txt" % pw, "x\n")  # the password's own segment holds no escape
        self.write("-" + "Users-" + HOME_NAME + "-x/API_TOKEN\\u003d" + LONG_RANDOM, "x\n")  # a home mark beside it
        for extra in ([], ["--json"], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertEqual(code, 1, extra)
            self.assertNotIn(pw, out + err, extra)
            self.assertNotIn(LONG_RANDOM, out + err, extra)
        found = sorted(f["path"] for f in self.json_check()[1]["findings"] if f["path"].startswith("d"))
        self.assertEqual([f[:3] for f in found], ["d0/", "d1/", "d2/"], found)  # each still names its folder

    def test_a_credential_after_another_long_run_on_a_line(self):
        self.assertIsNotNone(sc._secret_finding("build_id=%s/SESSION_TOKEN=%s" % ("a1b2" * 10, LONG_RANDOM)))

    def test_a_url_in_a_shell_default_value(self):
        pw = LONG_RANDOM[:12] + "7"
        for line in ("X=${DATABASE_URL:-postgres://app:%s@db:5432/app}" % pw, "${A:+amqp://guest:%s@mq/}" % pw,
                     "see ...https://u:%s@h.internal/x" % pw):
            self.assertEqual(sc._secret_finding(line), "a URL that carries a credential", line)

    def test_a_long_run_before_a_url_is_read_in_linear_time(self):
        import time
        line = "0x" + "ab" * 40000 + " bzz-raw://x"
        started = time.monotonic()
        sc._secret_finding(line)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_minified_json_line_of_quoted_members_is_read_in_linear_time(self):
        def cost(members):
            line = "{" + ",".join('"f%d":"%s"' % (i, "0123456789abcdef" * 4) for i in range(members)) + "}"
            best = None
            for _ in range(2):
                started = time.perf_counter()
                self.assertIsNone(sc._secret_finding(line))
                took = time.perf_counter() - started
                best = took if best is None else min(best, took)
            return best
        # four times the line costs about four times as much; copying the rest of the line per member cost nine
        self.assertLess(cost(56000) / cost(14000), 6.5)

    def test_the_litter_files_the_check_skips_are_packs(self):
        packer = _package_module()
        self.assertTrue(packer.JUNK.pattern.endswith("|" + sc._PACK_JUNK_FILE.pattern), packer.JUNK.pattern)
        for name in (".DS_Store", "m.pyc", "a\r.pyc", "a\u2028.pyc", "a\n.pyc", "x.pyc.txt", "DS_Store"):
            self.assertEqual(bool(sc._PACK_JUNK_FILE.fullmatch(name)), bool(packer.JUNK.fullmatch(name)), repr(name))

    def test_every_folder_the_check_skips_is_one_pack_refuses(self):
        packer = _package_module()
        for name in sc.PACK_REFUSES:
            self.assertTrue(packer.JUNK.fullmatch(name), name)

    def test_prose_about_bearer_tokens_is_not_a_secret(self):
        self.write("doc.md", "Bearer tokens are never written to a file.\nbearer <token> goes in the header.\n"
                   "The task-management-service handles retries; see risk-assessment-report-2026.md and\n"
                   "disk-encryption-settings or the cross-project-ask-through-com-submit scenario.\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_owner_strings_without_regard_to_case_and_in_paths(self):
        listed = self.owner_list("# my names", OWNER, ACCOUNT, "ab")
        self.write("notes.md", "Built for %s.\n" % OWNER.upper())
        self.write("data/%s.json" % ACCOUNT, "{}\n")
        code, result, _ = self.json_check("--instance-strings", str(listed))
        self.assertEqual(code, 1)
        rules = {(f["path"], f["line"]): f["rule"] for f in result["findings"]}
        self.assertIn("(line 2)", rules[("notes.md", 1)])
        self.assertIn("(line 3)", rules[("data/<line 3>.json", 0)])  # the path is printed with the entry masked
        self.assertEqual(result["instanceStrings"], 2)  # the comment and the two-letter line are not entries

    def test_the_list_comes_from_the_environment_or_the_default(self):
        self.write("notes.md", "Built for %s.\n" % OWNER)
        listed = self.owner_list(OWNER)
        with mock.patch.dict(os.environ, {"FABRIC_INSTANCE_STRINGS": str(listed)}):
            self.assertEqual(self.json_check()[0], 1)
        default = sc.default_list()
        self.assertEqual(default, self.tmp / "home/cfg/passioncode-fabric/instance-strings.txt")
        default.parent.mkdir(parents=True)
        default.write_text(OWNER + "\n", encoding="utf-8")
        self.assertEqual(self.json_check()[0], 1)
        default.unlink()
        self.assertEqual(self.json_check()[0], 0)


class NeverRepeated(Tree):
    def test_paths_and_the_root_are_printed_without_them(self):
        listed = self.owner_list(OWNER, ACCOUNT)
        self.root = self.tmp / HOME_NAME / OWNER.lower() / "agent"  # a root under a home name and a listed folder
        self.root.mkdir(parents=True)
        self.write("data/%s.json" % ACCOUNT, "k = %s\n" % FAKE_GITHUB)
        self.write("%s/notes.md" % OWNER, "x\n")
        os.symlink("/" + "Users/" + HOME_NAME + "/secret.json", str(self.root / "link.json")) if hasattr(os, "symlink") and os.name != "nt" else None
        for extra in ([], ["--json"]):
            code, out, err = run(["check", str(self.root), "--instance-strings", str(listed), *extra])
            self.assertEqual(code, 1)
            for value in (HOME_NAME, OWNER, ACCOUNT, OWNER.casefold(), ACCOUNT.casefold(), FAKE_GITHUB):
                self.assertNotIn(value, out + err, extra)
        self.assertIn("data/<line 2>.json", out)
        self.assertNotIn('"root"', out)

    def test_a_secret_or_a_home_in_a_file_name_is_a_finding_and_masked(self):
        self.write("cache_%s.json" % FAKE_GITHUB, "{}\n")
        self.write("-" + "Users-" + HOME_NAME + "-proj/notes.md", "x\n")
        for extra in ([], ["--json"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertEqual(code, 1)
            self.assertNotIn(FAKE_GITHUB, out + err)
            self.assertNotIn(HOME_NAME, out + err)
        text = run(["check", str(self.root)])[1]
        self.assertIn("<secret>:0: secret", text)  # the segment that holds it, whole
        self.assertIn("-Users-<home>-proj/notes.md:0: home-path", text)

    def test_overlapping_marks_print_no_part_of_either(self):
        first = HOME_NAME[:5]
        full = first + "-smith-" + "consulting"
        listed = self.owner_list(first, full, HOME_NAME + "-acme" + "corp")
        self.write(full + "-notes.md", "x\n")
        self.write("-" + "Users-" + HOME_NAME + "-acme" + "corp/a.md", "x\n")
        for argv in (["check", str(self.root), "--instance-strings", str(listed)],
                     ["check", str(self.root), "--instance-strings", str(listed), "--json"]):
            out = run(argv)[1]
            for part in ("smith", "consulting", "acme", "corp", first):
                self.assertNotIn(part, out, argv)

    @unittest.skipIf(os.name == "nt", "a backslash and a colon in a name need a POSIX file system")
    def test_two_credentials_in_one_path_print_neither(self):
        k1, k2 = LONG_RANDOM, ("Zq7" * 14)
        key = PEM.replace("RSA ", "") + "MC4CAQAwBQYDK2VwBCIEI" + ("Ab3" * 10)
        self.write("API_TOKEN=%s/SESSION_TOKEN=%s.txt" % (k1, k2), "x\n")
        self.write("e/API_TOKEN\\u003d%s_SESSION_TOKEN\\u003d%s.txt" % (k1, k2), "x\n")
        self.write("b/Bearer %s/Bearer %s.txt" % (k1 + "1", k2 + "2"), "x\n")
        self.write("p/k\\x%s.txt" % key, "x\n")
        self.write("q/%s.txt" % key, "x\n")
        for extra in ([], ["--json"], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertEqual(code, 1, extra)
            for value in (k1, k2, "MC4CAQAw"):
                self.assertNotIn(value, out + err, (extra, value))

    @unittest.skipIf(os.name == "nt", "a backslash and a colon in a name need a POSIX file system")
    def test_a_value_that_runs_across_a_folder_prints_no_part(self):
        a, b = ("Ab3" * 12), ("Zq7" * 6)
        pw = LONG_RANDOM[:15] + "7"
        self.write("SESSION_TOKEN=%s/config.json" % a, "x\n")
        self.write("c/API_TOKEN=%s/%s.txt" % (a[:32], b), "x\n")
        self.write("d/Bearer %s/%s.txt" % (a[:32] + "1", b[:17]), "x\n")
        self.write("e/https:\\/\\/h\\/x?access_token=%s/%s" % (a[:32], b), "x\n")
        self.write("f/sk-%s_https:\\/\\/app:%s@db\\/x.txt" % (a[:24], pw), "x\n")
        self.write("g/Bearer %s/Bearer x/%s/notes.md" % (b + "1", a[:24] + "9"), "x\n")  # a second token in the first
        for extra in ([], ["--json"], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertEqual(code, 1, extra)
            for value in (a, b, pw):
                for i in range(0, len(value) - 7):
                    self.assertNotIn(value[i:i + 8], out + err, (extra, value[:3], i))

    @unittest.skipIf(os.name == "nt", "a symbolic link")
    def test_a_path_never_repeats_a_value_found_elsewhere_in_the_tree(self):
        key = "Zq7Wm4" * 5
        self.write("notes/%s-todo.md" % HOME_NAME, "see %s\n" % MAC_HOME)
        (self.root / "people").mkdir()
        (self.root / "people" / (HOME_NAME + ".md")).write_bytes(b"\0binary")
        os.symlink("/" + "Users/" + HOME_NAME + "/.config/x", str(self.root / ("cfg-" + HOME_NAME)))
        self.write("cache/%s.json" % key, "token = sk" + "-" + key + "\n")
        for extra in ([], ["--json"], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertNotIn(HOME_NAME, out + err, extra)
            for i in range(0, len(key) - 7):
                self.assertNotIn(key[i:i + 8], out + err, (extra, i))

    def test_a_path_repeats_no_run_of_a_long_value_or_one_cut_across_folders(self):
        jwt = "ey" + "J" + ("Zq7Wm4" * 900) + "." + "eyJ" + ("Ab3Xy9" * 50) + "." + ("Qw8Er2" * 10)  # over 4096
        token = "Zq7W/" + "m4Zq/" + "7Wm4/" + "Rt5Yu6" * 7  # a value under a credential's name may hold a `/`
        self.write("conf.txt", "auth = %s\nAPI_TOKEN=%s\n" % (jwt, token))
        (self.root / "notes").mkdir()
        (self.root / "notes" / (jwt[5000:5040] + ".md")).write_bytes(b"\0binary")
        cut = self.root / "x" / token[:4] / token[5:9] / token[10:14]
        cut.mkdir(parents=True)
        (cut / "y.md").write_bytes(b"\0binary")
        for extra in ([], ["--json"], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertNotIn(jwt[5000:5040], out + err, extra)
            self.assertNotIn(token[:14], out + err, extra)

    def test_a_line_of_overlapping_key_starts_is_remembered_in_linear_time(self):
        seen = sc._Seen()
        line = "sk" + "-" + ("sk" + "-") * 13333
        start = time.perf_counter()
        seen.add_values(line)
        self.assertLess(time.perf_counter() - start, 3)  # 14 s when each overlapping span was read apart
        self.assertEqual(seen.grams, {line[i:i + 8] for i in range(len(line) - 7)})

    def test_names_found_across_a_large_tree_cost_one_pass_a_path(self):
        for i in range(1500):
            self.write("records/r%04d.txt" % i, "home: /" + "home/u%05dname/x\n" % i)
        start = time.perf_counter()
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 1)
        self.assertLess(time.perf_counter() - start, 20)  # 37 s for 2000 when each name was searched in each path

    def test_every_occurrence_of_a_found_home_name_is_masked(self):
        path = "-" + "Users-" + HOME_NAME + "-proj/x_/" + "Users/" + HOME_NAME + "/p"
        self.assertNotIn(HOME_NAME, sc.redact(path, []))
        self.assertNotIn(HOME_NAME, sc.redact("\u0130" * 8 + "/" + "Users/" + HOME_NAME + "/x", []))  # İ lowers to two
        self.write("\u0130" * 10 + "-" + "Users-" + HOME_NAME + "-proj/notes.md", "x\n")
        for extra in ([], ["--json"], ["--every-file"]):
            out = run(["check", str(self.root), *extra])[1]
            self.assertNotIn(HOME_NAME, out, extra)

    def test_a_home_name_spelled_with_a_letter_that_folds_to_ascii_is_masked(self):
        other = HOME_NAME.replace("s", "\u017f")  # LATIN SMALL LETTER LONG S folds to `s`, as U+212A folds to `k`
        self.assertNotIn(other, sc.redact("/" + "Users/" + HOME_NAME + "/x/" + other, []))
        self.write("-" + "Users-" + HOME_NAME + "-proj/" + other + ".md", "x\n")
        for extra in ([], ["--json"], ["--every-file"]):
            out = run(["check", str(self.root), *extra])[1]
            self.assertNotIn(other, out, extra)
            self.assertNotIn(HOME_NAME, out, extra)

    def test_a_bearer_token_inside_a_synthetic_token_run_is_found(self):
        real = LONG_RANDOM[:20] + "9"
        line = "Authorization: Bearer fake-token-1234/Bearer " + real
        self.assertIsNotNone(sc._secret_finding(line))
        self.write("a.sh", "curl -H '%s' x\n" % line)
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("a bearer token", out)
        self.assertNotIn(real[:8], out + err)

    def test_the_guard_masks_what_the_rest_still_holds(self):
        key, pw = "sk-" + ("Zq7" * 10), LONG_RANDOM[:15] + "7"
        # the span branch: what is left after the first masks still holds the password, folders after it
        out = sc.redact("docs/place/https://proxy/%s/https://app:%s@db/x/y/z" % (key, pw), [])
        self.assertTrue(out.startswith("docs/place/"), out)
        for value in (key, pw):
            for i in range(0, len(value) - 7):
                self.assertNotIn(value[i:i + 8], out, (value[:3], i))

    def test_a_long_path_through_the_guard_stays_fast(self):
        key, pw = "sk-" + ("Zq7" * 10), LONG_RANDOM[:15] + "7"
        head = "https:\\/\\/proxy\\/%s\\/https:\\/\\/app:%s@db\\/" % (key, pw)
        path = head + "folder-abc/" * ((4096 - len(head)) // 11)  # an escaped nested URL, then folders: 4 KB
        start = time.perf_counter()
        out = sc.redact(path, [])
        self.assertLess(time.perf_counter() - start, 5)  # quadratic at worst; read per folder it took 18 s
        for value in (key, pw):
            for i in range(0, len(value) - 7):
                self.assertNotIn(value[i:i + 8], out, (value[:3], i))
        path = head + "x/" * ((4096 - len(head)) // 2)  # one-letter folders: the guard once masked one a pass
        start = time.perf_counter()
        out = sc.redact(path, [])
        self.assertLess(time.perf_counter() - start, 1)  # 2 s when the guard read only the raw spans
        for value in (key, pw):
            for i in range(0, len(value) - 7):
                self.assertNotIn(value[i:i + 8], out, (value[:3], i))

    def test_an_error_does_not_echo_the_root(self):
        code, out, err = run(["check", str(self.tmp / OWNER / "absent")])
        self.assertEqual(code, 2)
        self.assertNotIn(OWNER, out + err)
        code, out, err = run(["check", str(self.root), str(self.tmp / OWNER)])  # an argument argparse cannot read
        self.assertEqual(code, 2)
        self.assertNotIn(OWNER, out + err)

    def test_no_value_and_no_list_entry_reaches_the_output(self):
        listed = self.owner_list(OWNER, ACCOUNT)
        self.write("all.txt", "\n".join([MAC_HOME, WIN_HOME, FAKE_GITHUB, FAKE_OPENAI, FAKE_JWT, PEM, OWNER, ACCOUNT]) + "\n")
        for extra in ([], ["--json"]):
            code, out, err = run(["check", str(self.root), "--instance-strings", str(listed), *extra])
            self.assertEqual(code, 1)
            for value in (HOME_NAME, FAKE_GITHUB, FAKE_OPENAI, FAKE_JWT, "PRIVATE KEY-----", OWNER, ACCOUNT,
                          OWNER.casefold(), ACCOUNT.casefold()):
                self.assertNotIn(value, out + err, extra)
            self.assertIn("all.txt:1: home-path", out) if not extra else None

    def test_text_output_names_path_line_and_kind(self):
        self.write("a.py", "x = 1\nTOKEN = '%s'\n" % FAKE_GITHUB)
        code, out, _ = run(["check", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("a.py:2: secret (a value shaped like a provider key)", out)
        self.assertIn("not read: 0 binary, 0 unreadable", out)
        self.assertIn("1 finding(s)", out)
        self.assertIn("(no owner's list)", out)


class WhatIsRead(Tree):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_submodule_named_as_a_folder_in_the_ignore_file_is_left_out(self):
        self.git("init", "-q")
        self.write("src/app.py", "print('hi')\n")
        (self.root / "vendor" / "sub").mkdir(parents=True)
        self.git("update-index", "--add", "--cacheinfo", "160000,%s,vendor/sub" % ("1" * 40))
        self.write(sc.IGNORE_FILE, "vendor/sub/\n")
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 0, out[-300:])

    @unittest.skipIf(os.name == "nt" or shutil.which("git") is None, "a POSIX script as Git's fsmonitor")
    def test_git_runs_no_command_the_checked_tree_configures(self):
        marker = self.tmp / "fsmonitor-ran"
        script = self.tmp / "fsmonitor.sh"
        script.write_text("#!/bin/sh\necho ran >> '%s'\n" % marker)
        script.chmod(0o755)
        self.git("init", "-q")
        self.git("config", "core.fsmonitor", str(script))
        self.write("src/app.py", "print('hi')\n")
        bin_dir = self.tmp / "bin"  # Git before 2.36 reads `core.fsmonitor=false` as a hook named `false`
        bin_dir.mkdir()
        (bin_dir / "false").write_text("#!/bin/sh\necho ran >> '%s'\nexit 1\n" % marker)
        (bin_dir / "false").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}):
            code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 0, out[-300:])
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt" or shutil.which("git") is None, "a symbolic link and git")
    def test_a_folder_line_in_the_ignore_file_leaves_out_no_file_or_link_of_that_name(self):
        self.git("init", "-q")
        self.write("build", "path = %s\n" % MAC_HOME)
        self.write("src/mycache", "path = %s\n" % MAC_HOME)
        os.symlink(MAC_HOME, str(self.root / "vendor"))
        self.write(sc.IGNORE_FILE, "build/\nvendor/\n*cache/\n")
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 1, out[-300:])
        for path in ("build:1", "src/mycache:1", "vendor:0"):
            self.assertIn(path + ": home-path", out)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_star_in_an_ignore_line_stays_in_its_folder(self):
        key = "sk" + "-" + "Zq7Wm4" * 5
        self.git("init", "-q")
        self.write("test/vectors/v1.json", "{}\n")
        self.write("test/vectors/private/live.json", '{"token": "%s"}\n' % key)
        self.write("test/deep/a/b.json", "{}\n")
        self.write(sc.IGNORE_FILE, "test/vectors/*.json\ntest/deep/**/*.json\n")
        for extra in ([], ["--every-file"]):
            code, out, err = run(["check", str(self.root), *extra])
            self.assertEqual(code, 1, (extra, out[-300:]))
            self.assertIn("test/vectors/private/live.json:1: secret", out)
            self.assertIn("2 left out by name", out)

    def test_an_ignore_line_takes_only_what_it_matches(self):
        cases = (("test/vectors/*", "test/vectors/v1.json", "test/vectors/live/config.json"),
                 ("test/**.json", "test/a.json", "test/b/c.json"), ("foo**/bar", "foo1/bar", "foobar"),
                 ("test/[^z]*.json", "test/a.json", "test/za.json"), ("/vec.json", "vec.json", "test/vec.json"),
                 ("vectors", "vectors/a/b.json", "other/vectors/x.json"), ("a/**/d.json", "a/d.json", "a/d.jsonx"))
        for glob, left_out, kept in cases:
            line = sc._line(glob, "a line")
            self.assertTrue(sc._ignored(left_out, [line]), (glob, left_out))
            self.assertFalse(sc._ignored(kept, [line]), (glob, kept))

    def test_a_folder_line_takes_what_its_folders_hold_never_a_file_beside_them(self):
        for glob, path, left_out in (("src/**/", "src/main.py", False), ("src/**/", "src/pkg/x.py", True),
                                     ("**/", "main.py", False), ("**/", "a/b.py", True), ("a**/b", "ab", False),
                                     ("a**/b", "ax/b", True), ("test/fixtures/", "test/fixtures/a/b", True)):
            self.assertEqual(sc._ignored(path, [sc._line(glob, "a line")]), left_out, (glob, path))

    def test_a_class_holding_set_operators_reads_them_as_letters(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # a FutureWarning names the script's path, which can be under a home folder
            pattern = sc._glob("[a&&b]x")
            for glob in ("[+--]x", "x[a-z--]y"):  # `--` warns as a set difference: refused, so nothing prints
                self.assertFalse(sc._readable_glob(glob), glob)
        self.assertTrue(pattern.match("&x"))

    def test_a_line_git_reads_otherwise_is_refused_or_read_narrowly(self):
        for glob in ("//top.txt", "vendor//", "a\\*b", "[a--b]x", "x[a-z--]y", "notes[draft.md", "[/",
                     "v/[[:digit:]].json"):  # Git: no match, an escape, no match, a POSIX class
            with self.assertRaises(sc.CheckError, msg=glob):
                sc._line(glob, "a line")
        self.assertTrue(sc._ignored("t/bx", [sc._line("t/[^]a]x", "l")]))
        self.assertFalse(sc._ignored("t/ax", [sc._line("t/[^]a]x", "l")]))
        self.write("top.txt", "path = %s\n" % MAC_HOME)
        for line in ("\ttop.txt", "top.txt\t", "top.txt\x0cbar", "top.txt\u2028bar"):
            self.write(sc.IGNORE_FILE, line + "\n")
            code, out, err = run(["check", str(self.root)])
            self.assertEqual(code, 1, repr(line))  # Git reads each as a name no file has
        (self.root / sc.IGNORE_FILE).write_bytes(b"top.txt  \r\n")  # trailing spaces and a CR: Git trims them
        self.assertEqual(run(["check", str(self.root)])[0], 0)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_nested_repository_is_left_out_only_by_a_line_naming_its_folder(self):
        self.git("init", "-q")
        self.write("src/app.py", "print('hi')\n")
        nested = self.root / "vendor" / "sub"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        (nested / "x.txt").write_text("x\n")
        for line, expected in (("vendor/*", 2), ("**/sub", 2), ("vendor/*/", 0), ("vendor/sub", 0), ("**/sub/", 0)):
            self.write(sc.IGNORE_FILE, line + "\n")
            code, out, err = run(["check", str(self.root)])
            self.assertEqual(code, expected, (line, out[-200:]))
            if expected:  # a wildcard takes files: the repository is reported until it is checked and named
                self.assertIn("vendor/sub/: not read (a nested repository)", out)
        self.write(sc.IGNORE_FILE, "vendor/sub/*\n")  # names the files inside it, never the repository itself
        self.assertEqual(run(["check", str(self.root)])[0], 2)
        self.assertFalse(sc._ignored("vendor/sub", ["vendor/*"], self.root))  # a submodule, as Git lists it
        self.assertTrue(sc._ignored("vendor/sub", ["vendor/sub/"], self.root))

    def test_two_names_that_overlap_in_a_path_are_both_masked(self):
        first, second = "ann" + "bob", "bbel" + "lequinn"  # the second starts with the first's last letter
        self.write("one.txt", "cd /" + "Users/" + first + "/x\n")
        self.write("two.txt", "cd /" + "home/" + second + "/x\n")
        (self.root / "notes").mkdir()
        (self.root / "notes" / (first + second[1:] + ".bin")).write_bytes(b"\0binary")
        for extra in ([], ["--json"]):
            out = run(["check", str(self.root), *extra])[1]
            for name in (first, second):
                for i in range(0, len(name) - 7):
                    self.assertNotIn(name[i:i + 8], out, (extra, name[:3], i))
            self.assertNotIn(second[1:], out, extra)

    def test_a_wildcard_reads_one_byte_of_a_name_as_git_does(self):
        for glob, path in (("vectors/?.json", "vectors/\u00e9.json"), ("vectors/[!b].json", "vectors/\u00f1.json")):
            self.assertFalse(sc._ignored(path, [sc._line(glob, "a line")]), (glob, path))  # two bytes in UTF-8
        self.assertTrue(sc._ignored("vectors/a.json", [sc._line("vectors/?.json", "a line")]))
        self.assertTrue(sc._ignored("vectors/\u00e9.json", [sc._line("vectors/??.json", "a line")]))
        self.assertTrue(sc._ignored("caf\u00e9/x.json", [sc._line("caf\u00e9/", "a line")]))  # a literal, as bytes
        self.assertTrue(sc._ignored("b\ud800.txt", [sc._line("*.txt", "a line")]))  # a Windows name: no crash
        self.write("docs", "x\n")
        self.assertFalse(sc._ignored("docs", ["docs/"], self.root))  # a line ending in `/` takes no file

    def test_an_exception_line_is_refused_not_dropped(self):
        self.write("test/vectors/live.json", "path = %s\n" % MAC_HOME)
        self.write(sc.IGNORE_FILE, "test/vectors/*\n!test/vectors/live.json\n")
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 2, err[-200:])
        self.assertIn("line 2 of %s is an exception" % sc.IGNORE_FILE, err)

    def test_a_file_prints_under_one_name_for_its_finding_and_its_not_read_line(self):
        key = "Zq7Wm4" * 5
        (self.root / "cache").mkdir()
        (self.root / "cache" / ("sk" + "-" + key + ".bin")).write_bytes(b"\0binary")
        listing = self.tmp / "cfg" / "list.txt"
        listing.parent.mkdir()
        listing.write_text("secret\nhome\n")
        code, out, err = run(["check", str(self.root), "--instance-strings", str(listing), "--json"])
        result = json.loads(out)
        printed = {e["path"] for e in result["notRead"]} | {f["path"] for f in result["findings"]}
        self.assertEqual(printed, {"cache/<secret>"})

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_folder_glob_in_the_ignore_file_leaves_out_no_file(self):
        key = "sk" + "-" + "Zq7Wm4" * 5
        for glob, source in (("src/*/", "src/app.py"), ("*/", "app.py"), ("test/fixtures*/", "test/fixtures.json")):
            with self.subTest(glob=glob):  # a glob that names folders reaches no file beside them
                shutil.rmtree(self.root)
                self.root.mkdir()
                self.git("init", "-q")
                self.write("src/vectors/v.txt", "synthetic\n")
                self.write(source, "token = %s\n" % key)
                self.write(sc.IGNORE_FILE, glob + "\n")
                code, out, err = run(["check", str(self.root)])
                self.assertEqual(code, 1, glob)
                self.assertIn(source + ":1: secret", out)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_copy_inside_the_checked_tree_writes_no_bytecode(self):
        tools = self.root / "tools"
        tools.mkdir()
        for name in ("fabric_source_check.py", "fabric_secrets.py"):
            shutil.copy(SCRIPTS / name, tools / name)
        self.git("init", "-q")
        self.git("add", "-A")
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        done = subprocess.run([sys.executable, str(tools / "fabric_source_check.py"), "check", str(self.root)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stdout[-300:])
        self.assertFalse((tools / "__pycache__").exists())

    def test_git_ignored_files_are_not_read(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        self.git("init", "-q")
        self.write(".gitignore", "instance/\n")
        self.write("instance/state.json", '{"home": "%s"}\n' % MAC_HOME)
        self.write("src/app.py", "print('hi')\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])
        self.write("src/leak.py", "P = '%s'\n" % MAC_HOME)  # untracked, not ignored: it would be committed
        code, result, _ = self.json_check()
        self.assertEqual([f["path"] for f in result["findings"]], ["src/leak.py"])

    def test_without_git_the_walk_skips_dependency_folders(self):
        self.write("node_modules/dep/index.js", "x = '%s'\n" % MAC_HOME)
        self.write("__pycache__/m.txt", "x\n")
        self.write(".git/config", "url = %s\n" % MAC_HOME)
        self.write("app.js", "ok\n")
        with mock.patch.object(sc, "_git_files", return_value=None):
            code, result, _ = self.json_check()
            text = run(["check", str(self.root)])[1]
        self.assertIn("Git not used", text)
        self.assertIn("1 dependency folder(s) not read", text)  # named, never a silent `every file`
        self.assertIn("node_modules: not read (a dependency folder", text)
        self.assertEqual(result["dependencies"], ["node_modules"])  # never `__pycache__`, which --every-file leaves too
        self.assertEqual(result["skipped"]["dependencies"], 1)
        self.assertEqual(code, 0, result["findings"])
        self.assertEqual(result["mode"], "walk")
        code, result, _ = self.json_check("--every-file")
        self.assertEqual(code, 1)  # what pack carries: node_modules read, `.git` still not
        self.assertEqual([f["path"] for f in result["findings"]], ["node_modules/dep/index.js"])

    def test_ignore_file_and_exclude(self):
        self.write("fixtures/keys.txt", FAKE_GITHUB + "\n")
        self.write("vectors/v.json", FAKE_OPENAI + "\n")
        self.write("app.py", "ok\n")
        self.write(sc.IGNORE_FILE, "# test vectors\nfixtures/\n")
        code, result, _ = self.json_check("--exclude", "vectors/*.json")
        self.assertEqual(code, 0, result["findings"])

    def test_binary_files_are_listed_and_large_files_read(self):
        self.write("records.sqlite", b"SQLite format 3\0" + MAC_HOME.encode(), mode="wb")
        self.write("big.log", "a" * (2 << 20) + "\n" + MAC_HOME + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 1)
        self.assertEqual(result["skipped"]["binary"], 1)
        self.assertEqual(result["notRead"], [{"path": "records.sqlite", "why": "binary"}])
        self.assertIn("records.sqlite: not read (binary)", run(["check", str(self.root)])[1])
        self.assertEqual([(f["path"], f["line"]) for f in result["findings"]], [("big.log", 2)])

    def test_a_binary_file_not_named_as_source_makes_the_check_incomplete(self):
        self.write("records.sqlite", b"SQLite format 3\0" + MAC_HOME.encode(), mode="wb")
        self.write("utf16.txt", MAC_HOME.encode("utf-16"), mode="wb")
        code, result, _ = self.json_check()
        self.assertEqual(code, 2)
        self.assertFalse(result["complete"])
        self.assertEqual(result["skipped"]["binary"], 2)
        self.write(sc.IGNORE_FILE, "# the icon is source\nicon.png\n")
        self.write("icon.png", b"\x89PNG\0", mode="wb")
        for name in ("records.sqlite", "utf16.txt"):
            (self.root / name).unlink()
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["skipped"]["excluded"], 1)

    def test_files_left_out_are_counted(self):
        self.write("a.txt", "x\n")
        self.write("b.txt", "x\n")
        code, result, _ = self.json_check("--exclude", "*")
        self.assertEqual((code, result["files"], result["skipped"]["excluded"]), (0, 0, 2))
        self.assertIn("2 left out by name", run(["check", str(self.root), "--exclude", "*"])[1])

    def test_every_file_reads_what_pack_carries(self):
        if shutil.which("git") is None:
            self.skipTest("git")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write("pkg/.gitignore", "config/*.json\nnode_modules/\n")  # a package folder inside a checkout, its instance ignored
        self.write("pkg/config/agent.json", '{"data": "%s"}\n' % MAC_HOME)
        self.write("pkg/node_modules/x/index.js", MAC_HOME + "\n")
        self.write("pkg/main.py", "pass\n")
        pkg = str(self.root / "pkg")
        self.assertEqual(run(["check", pkg])[0], 0)
        code, out, _ = run(["check", pkg, "--every-file", "--json"])
        result = json.loads(out)
        self.assertEqual(code, 1)
        found = sorted(f["path"] for f in result["findings"])
        self.assertEqual(found, ["config/agent.json", "node_modules/x/index.js"])
        packs = set(_package_module().read_folder(pkg))
        self.assertLessEqual(packs, set(found) | {".gitignore", "main.py"})

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_link_to_a_folder_is_checked_without_git(self):
        target = self.outside / ("-" + "Users-" + HOME_NAME + "-data")
        target.mkdir()
        os.symlink(str(target), str(self.root / "d"))
        code, result, _ = self.json_check()
        self.assertEqual(result["mode"], "walk")
        self.assertEqual([(f["path"], f["line"]) for f in result["findings"]], [("d", 0)])

    def test_a_tracked_file_deleted_here_is_named_as_such(self):
        if shutil.which("git") is None:
            self.skipTest("git")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write("old.txt", "x\n")
        subprocess.run(["git", "-C", str(self.root), "add", "old.txt"], check=True)
        (self.root / "old.txt").unlink()
        code, result, _ = self.json_check()
        self.assertEqual(code, 2)
        self.assertEqual(result["notRead"], [{"path": "old.txt", "why": "not in the work tree"}])

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_tracked_folder_replaced_by_a_link_is_not_followed(self):
        if shutil.which("git") is None:
            self.skipTest("git")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write("dir/a.txt", "x\n")
        subprocess.run(["git", "-C", str(self.root), "add", "dir/a.txt"], check=True)
        shutil.rmtree(str(self.root / "dir"))
        (self.outside / "a.txt").write_text(MAC_HOME + "\n", encoding="utf-8")
        os.symlink(str(self.outside), str(self.root / "dir"))
        code, result, _ = self.json_check()
        self.assertEqual(code, 2)
        self.assertNotIn(("dir/a.txt", 1), [(f["path"], f["line"]) for f in result["findings"]])
        self.assertIn({"path": "dir/a.txt", "why": "under a symbolic link"}, result["notRead"])

    def test_every_file_leaves_out_a_worktrees_git_file(self):
        self.write(".git", "gitdir: %s/.git/worktrees/x\n" % MAC_HOME)
        self.write("main.py", "pass\n")
        self.assertEqual(self.json_check("--every-file")[0], 0)

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_dangling_link_above_the_default_list_is_an_error(self):
        cfg = Path(os.environ["XDG_CONFIG_HOME"])
        cfg.mkdir(parents=True)
        os.symlink(str(self.tmp / "absent"), str(cfg / "passioncode-fabric"))
        self.write("a.txt", "x\n")
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 2, out + err)
        self.assertNotIn(str(self.tmp), out + err)

    def test_the_walk_reads_litter_git_would_commit(self):
        """Without Git the walk stands in for what Git would commit: a .pyc is read (pack refuses it, but a source
        handed over by Git carries it), so only --every-file leaves litter out."""
        self.write("pkg/settings.pyc", b"\x61\x0d\x0d\x0a\0API_TOKEN", mode="wb")
        self.write("pkg/notes.pyc", "API_TOKEN=%s\n" % LONG_RANDOM)
        self.write("main.py", "pass\n")
        with mock.patch.object(sc, "_git_files", return_value=None):
            code, result, _ = self.json_check()
        self.assertEqual(code, 1, result)
        self.assertEqual(result["notRead"], [{"path": "pkg/settings.pyc", "why": "binary"}])

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_dangling_link_anywhere_above_the_default_list(self):
        os.symlink(str(self.tmp / "unmounted"), str(self.tmp / "vol"))
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp / "vol" / "cfg")}):
            code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 2, out + err)

    def test_every_file_leaves_out_what_pack_refuses_as_litter(self):
        self.write(".DS_Store", b"\0\0\0\1Bud1", mode="wb")
        self.write("pkg/m.cpython-39.pyc", b"\x61\x0d\x0d\x0a\0", mode="wb")
        self.write("main.py", "pass\n")
        code, result, _ = self.json_check("--every-file")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["notRead"], [])

    def test_line_numbers_are_an_editors(self):
        self.write("a.txt", "one\fstill one\r\ntwo %s\n" % MAC_HOME)
        self.assertEqual([f["line"] for f in self.json_check()[1]["findings"]], [2])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissions")
    def test_an_unreadable_file_makes_the_check_incomplete(self):
        locked = self.write("locked.txt", "x\n")
        locked.chmod(0)
        try:
            code, result, _ = self.json_check()
        finally:
            locked.chmod(0o644)
        self.assertEqual(code, 2)
        self.assertEqual(result["skipped"]["unreadable"], 1)
        self.assertFalse(result["complete"])

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_link_is_checked_by_the_path_it_names(self):
        os.symlink(MAC_HOME, str(self.root / "home-link"))
        os.symlink("relative/example", str(self.root / "neutral-link"))
        code, result, _ = self.json_check()
        self.assertEqual([(f["path"], f["kind"]) for f in result["findings"]], [("home-link", "home-path")])

    def test_a_folder_git_ignores_is_walked(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True, capture_output=True)
        (self.tmp / ".gitignore").write_text("agent/\n", encoding="utf-8")
        self.write("a.py", "P = '%s'\n" % MAC_HOME)
        self.assertEqual(self.json_check()[0], 1)

    def test_a_list_and_an_ignore_file_with_a_byte_order_mark(self):
        listed = self.outside / "bom.txt"
        listed.write_bytes(b"\xef\xbb\xbf" + OWNER.encode() + b"\n")
        self.write("n.md", OWNER + "\n")
        self.assertEqual(self.json_check("--instance-strings", str(listed))[0], 1)
        self.write(sc.IGNORE_FILE, b"\xef\xbb\xbfn.md\n", mode="wb")
        self.assertEqual(self.json_check("--instance-strings", str(listed))[0], 0)

    def test_an_ignore_file_that_is_not_utf8_is_an_error(self):
        self.write(sc.IGNORE_FILE, b"caf\xe9/\n", mode="wb")
        self.assertEqual(self.json_check()[0], 2)

    def test_a_console_that_cannot_encode_a_name(self):
        self.write("\u0434\u0430\u043d\u043d\u044b\u0435.txt", MAC_HOME + "\n")
        out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with contextlib.redirect_stdout(out):
            code = sc.run(["check", str(self.root)])
        out.flush()
        text = out.buffer.getvalue().decode("cp1252")
        self.assertEqual(code, 1)
        self.assertIn("1 finding(s)", text)


class Refusals(Tree):

    def test_a_list_under_a_user_with_no_home_is_an_error(self):
        for argv, env in ((["--instance-strings", "~nosuchuser" + "4242/l.txt"], {}),
                          ([], {"FABRIC_INSTANCE_STRINGS": "~nosuchuser" + "4242/l.txt"})):
            with mock.patch.dict(os.environ, env):
                code, out, err = run(["check", str(self.root), *argv])
            self.assertEqual(code, 2, (argv, err[-200:]))
            self.assertIn("owner's list cannot be read", err)
            self.assertNotIn("Traceback", err)
    def test_a_glob_it_cannot_read_is_an_error_not_a_traceback(self):
        expected = 2  # a reversed range: Python 3.9's fnmatch raised, 3.14's read it as empty; refused on both
        self.write("a.txt", "x\n")
        for argv, ignore in ((["check", str(self.root)], "[9-0]*.txt\n"), (["check", str(self.root), "--exclude", "x/[9-0]*"], "")):
            self.write(sc.IGNORE_FILE, ignore)
            code, out, err = run(argv)
            self.assertEqual(code, expected, err[-200:])
            self.assertNotIn("Traceback", err)

    @unittest.skipIf(os.name == "nt", "a POSIX account database")
    def test_no_home_at_all_is_an_error_not_a_traceback(self):
        env = {k: v for k, v in os.environ.items() if k not in ("HOME", "XDG_CONFIG_HOME", "FABRIC_INSTANCE_STRINGS")}
        for argv in ([str(self.root)], [str(self.root), "--instance-strings", "~/l.txt"], ["~/r"]):
            with mock.patch.dict(os.environ, env, clear=True), mock.patch("pwd.getpwuid", side_effect=KeyError("uid")):
                code, out, err = run(["check", *argv])
            self.assertEqual(code, 2, (argv, err[-200:]))
            self.assertNotIn("Traceback", err)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("pwd.getpwuid", side_effect=KeyError("uid")):
            err = run(["check", str(self.root)])[2]
        self.assertIn("XDG_CONFIG_HOME", err)  # the way through, named

    def test_git_on_windows_is_taken_from_an_absolute_folder_of_path_only(self):
        here, there = self.tmp / "here", self.tmp / "there"
        for folder in (here, there):
            folder.mkdir()
            (folder / "git.exe").write_text("")
        with mock.patch.object(sc.os, "name", "nt"):
            with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", "relative", str(there)])}):
                self.assertEqual(sc._git(), os.path.join(str(there), "git.exe"))
            with mock.patch.dict(os.environ, {"PATH": "."}):
                self.assertIsNone(sc._git())  # never the current folder's
            (here / "git.exe").unlink()
            (here / "git.cmd").write_text("")
            with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(here), str(there)])}):
                self.assertEqual(sc._git(), os.path.join(str(there), "git.exe"))  # a .cmd would run through cmd.exe

    @unittest.skipIf(os.name == "nt", "a POSIX executable")
    def test_git_on_posix_is_taken_from_an_absolute_folder_of_path_only(self):
        fake = self.root / "git"
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
        real = shutil.which("git")
        here = os.getcwd()
        os.chdir(str(self.root))  # a relative PATH element would find the tree's own `git` here
        try:
            with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(["", ".", "relative"] + ([os.path.dirname(real)] if real else []))}):
                found = sc._git()
        finally:
            os.chdir(here)
        self.assertEqual(found, os.path.join(os.path.dirname(real), "git") if real else None)

    @unittest.skipIf(os.name == "nt" or shutil.which("git") is None, "a POSIX default path holding git")
    def test_git_is_found_with_path_unset(self):
        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        with mock.patch.dict(os.environ, env, clear=True):
            found = sc._git()
        if any(os.path.isfile(os.path.join(d, "git")) for d in os.defpath.split(os.pathsep) if d):
            self.assertTrue(found and os.path.isabs(found), found)  # the walk would skip dependency folders

    def test_git_output_on_windows_is_read_back_as_the_walk_reads_a_name(self):
        name = "\udc80.txt"
        listed = name.encode("utf-8", "surrogatepass") + b"\0"
        done = subprocess.CompletedProcess([], 0, listed, b"")
        with mock.patch.object(sc.os, "name", "nt"), mock.patch.object(sc, "_git", return_value="git.exe"), \
                mock.patch.object(sc.subprocess, "run", return_value=done):
            self.assertEqual(sc._git_files(self.root), [name])

    def test_a_lone_surrogate_in_a_windows_name_is_one_wtf8_character(self):
        with mock.patch.object(sc.os, "name", "nt"):
            self.assertEqual(sc._as_bytes("\udc80.txt"), sc._as_bytes("\udc80") + ".txt")
            self.assertEqual(len(sc._as_bytes("\udc80")), 3)  # WTF-8, as Git for Windows writes it
            self.assertFalse(sc._ignored("\udc80.txt", [sc._line("?.txt", "a line")]))

    def test_the_owners_list_is_split_at_line_feeds_only(self):
        listing = self.tmp / "cfg" / "list.txt"
        listing.parent.mkdir()
        listing.write_bytes(b"# owner terms\x0c page two\nzqcorpx\n")
        self.write("a.txt", "zqcorpx\n")
        code, out, err = run(["check", str(self.root), "--instance-strings", str(listing)])
        self.assertEqual(code, 1)
        self.assertIn("(line 2)", out)
        self.assertIn("1 instance string(s) listed", out)
        listing.write_bytes(b"zqcorpa\rzqcorpx\r")  # CR alone ends a line too
        code, out, err = run(["check", str(self.root), "--instance-strings", str(listing)])
        self.assertEqual(code, 1)
        self.assertIn("(line 2)", out)
        self.assertIn("2 instance string(s) listed", out)

    def test_a_list_inside_the_tree_is_refused(self):
        inside = self.write("instance-strings.txt", OWNER + "\n")
        code, out, err = run(["check", str(self.root), "--instance-strings", str(inside)])
        self.assertEqual(code, 2)
        self.assertIn("inside the tree", err)
        self.assertNotIn(OWNER, out + err)

    def test_a_named_list_that_is_missing_is_an_error(self):
        code, _, err = run(["check", str(self.root), "--instance-strings", str(self.outside / "absent.txt")])
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)
        bad = self.outside / "latin1.txt"
        bad.write_bytes(b"caf\xe9\n")
        code, _, err = run(["check", str(self.root), "--instance-strings", str(bad)])
        self.assertEqual(code, 2)
        self.assertIn("is not UTF-8", err)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissions")
    def test_a_tracked_file_below_a_folder_it_cannot_search(self):
        if shutil.which("git") is None:
            self.skipTest("git")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write("locked/sub/a.txt", "x\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        (self.root / "locked").chmod(0o600)
        try:
            code, out, err = run(["check", str(self.root)])
        finally:
            (self.root / "locked").chmod(0o755)
        self.assertEqual(code, 2, out + err)
        self.assertIn("locked/sub/a.txt: not read (unreadable)", out)
        self.assertNotIn(str(self.tmp), out + err)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissions")
    def test_a_root_below_a_folder_it_cannot_search(self):
        self.write("a.txt", "x\n")
        self.tmp.chmod(0o600)
        try:
            code, out, err = run(["check", str(self.root)])
        finally:
            self.tmp.chmod(0o755)
        self.assertEqual(code, 2, out + err)
        self.assertNotIn(str(self.tmp), out + err)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissions")
    def test_a_root_it_cannot_read_is_an_error_without_its_path(self):
        self.write("a.txt", "x\n")
        self.root.chmod(0o600)
        try:
            code, out, err = run(["check", str(self.root)])
        finally:
            self.root.chmod(0o755)
        self.assertEqual(code, 2, out + err)
        self.assertNotIn(str(self.tmp), out + err)

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_root_that_is_a_symlink_loop(self):
        loop = self.tmp / "loop"
        os.symlink(str(loop), str(loop))
        code, out, err = run(["check", str(loop)])
        self.assertEqual(code, 2, out + err)
        self.assertNotIn(str(self.tmp), out + err)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "permissions")
    def test_a_default_list_it_cannot_reach_is_an_error(self):
        folder = Path(os.environ["XDG_CONFIG_HOME"]) / "passioncode-fabric"
        folder.mkdir(parents=True)
        (folder / sc.LIST_NAME).write_text(OWNER + "\n", encoding="utf-8")
        self.write("n.md", OWNER + "\n")
        folder.chmod(0)
        try:
            code, out, err = run(["check", str(self.root)])
        finally:
            folder.chmod(0o755)
        self.assertEqual(code, 2, out + err)  # never "no owner's list", which would pass the string
        self.assertNotIn(str(self.tmp), out + err)

    def test_a_list_with_no_usable_string_says_so(self):
        listed = self.owner_list("ab")
        out = run(["check", str(self.root), "--instance-strings", str(listed)])[1]
        self.assertIn("the owner's list holds no string of three or more characters", out)
        self.assertTrue(self.json_check("--instance-strings", str(listed))[1]["instanceList"])
        self.assertFalse(self.json_check()[1]["instanceList"])

    @unittest.skipIf(os.name == "nt", "a symbolic link needs a privilege on Windows")
    def test_a_list_that_is_a_symlink_loop_or_a_dangling_default(self):
        loop = self.outside / "loop.txt"
        os.symlink(str(loop), str(loop))
        code, out, err = run(["check", str(self.root), "--instance-strings", str(loop)])
        self.assertEqual(code, 2, out + err)
        self.assertNotIn(str(self.tmp), out + err)
        folder = Path(os.environ["XDG_CONFIG_HOME"]) / "passioncode-fabric"
        folder.mkdir(parents=True)
        os.symlink(str(self.tmp / "absent" / "list.txt"), str(folder / sc.LIST_NAME))  # a volume not mounted
        code, out, err = run(["check", str(self.root)])
        self.assertEqual(code, 2, out + err)  # never "no owner's list"
        self.assertNotIn(str(self.tmp), out + err)

    def test_a_root_that_is_not_a_folder(self):
        code, _, err = run(["check", str(self.root / "absent")])
        self.assertEqual(code, 2)
        self.assertIn("not a folder", err)

    def test_the_cli_exits_with_the_check(self):
        self.write("a.py", "TOKEN = '%s'\n" % FAKE_GITHUB)
        proc = subprocess.run([__import__("sys").executable, str(SCRIPTS / "fabric_source_check.py"), "check", str(self.root)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn(FAKE_GITHUB, proc.stdout + proc.stderr)


SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"


def flat(relative):
    return " ".join((SKILLS / relative).read_text(encoding="utf-8").split())


class TheSkillsTeachIt(unittest.TestCase):
    def test_the_default_list_is_in_the_users_configuration_folder(self):
        home = Path.home()
        self.assertEqual(sc.default_list("linux", {"XDG_CONFIG_HOME": "/cfg"}), Path("/cfg/passioncode-fabric/instance-strings.txt"))
        self.assertEqual(sc.default_list("darwin", {}), home / ".config/passioncode-fabric/instance-strings.txt")
        self.assertEqual(sc.default_list("win32", {"APPDATA": "C:\\R"}), Path("C:\\R") / "passioncode-fabric" / "instance-strings.txt")
        # a relative value is ignored, as the XDG spec says: the list in the home folder is still read
        self.assertEqual(sc.default_list("linux", {"XDG_CONFIG_HOME": "rel/cfg"}), home / ".config/passioncode-fabric/instance-strings.txt")
        self.assertEqual(sc.default_list("linux", {"XDG_CONFIG_HOME": "~/.config"}), home / ".config/passioncode-fabric/instance-strings.txt")
        self.assertEqual(sc.default_list("win32", {"APPDATA": "R"}), home / "AppData" / "Roaming" / "passioncode-fabric" / "instance-strings.txt")
        self.assertEqual(sc.default_list("win32", {}), home / "AppData" / "Roaming" / "passioncode-fabric" / "instance-strings.txt")

    def test_creating_lays_out_source_and_instance_from_the_first_commit(self):  # source-apart-from-instance
        step = flat("creating-fabric-agents/SKILL.md").split("## Step 2: the project skeleton")[1].split("## Step 3")[0]
        for words in ("The source stays apart from the instance", "references/source-and-instance.md",
                      "fabric_source_check.py check", "exits 0", "Handing the source over stays the owner's act"):
            self.assertIn(words, step)

    def test_adapting_checks_first_then_moves_values_out(self):  # move-instance-data-out-of-an-existing-agent
        step = flat("adapting-projects-to-fabric/SKILL.md").split("### 4c. Keep the instance out of the source")[1].split("### 5.")[0]
        for words in ("First run", "fabric_source_check.py", "never repeating a value", "Run the check again until it exits 0",
                      "a fresh history is the owner's act"):
            self.assertIn(words, step)

    def test_the_reference_names_the_rules_the_script_keeps(self):
        ref = flat("creating-fabric-agents/references/source-and-instance.md")
        for words in ("never repeats", "Exit `0`: no finding and every file read; `1`: at least one finding",
                      "a file was not read", "a nested repository", "`--every-file`", "named in the ignore file", "A list inside the tree is refused", sc.IGNORE_FILE,
                      "passioncode-fabric/" + sc.LIST_NAME, "FABRIC_INSTANCE_STRINGS", "`$XDG_CONFIG_HOME` when it is absolute, else `~/.config`",
                      "`<line N>`", "`<home>`", "`<secret>`", "every text file read", "listed by its path", "its line in the owner's list", "never followed", "Git was not used", "but `.git`, `__pycache__`, `.DS_Store` and `*.pyc`", "The check finds the forms the table names, and only those", "dependency folders", "check a nested repository in its own tree", "a web route under `/home/`",
                      "`fabric_paths.service_dirs`", "`<id>.<instance>`", "(LC-09)", "FAA-188 part 2",
                      "private-terms.txt"):
            self.assertIn(words, ref)


class TheAdapterChecksItself(unittest.TestCase):
    def test_this_repository_has_no_instance_data(self):
        """The adapter's own tree passes, with its test vectors left out by its .fabric-source-ignore."""
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder, "instance-strings.txt")
            empty.write_text("", encoding="utf-8")
            code, out, err = run(["check", str(ROOT), "--instance-strings", str(empty)])
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
