"""Hostile inputs the two package twins must answer alike (FAA-78, findings 40 to 43). The cases live in
test/fixtures/kit-hostile-inputs-package.json; kit-hostile-package.test.mjs runs the same cases through
fabric-package.mjs. Also here: the folder walk's failure paths (finding 41) and the symlink swap (finding 42)."""

import contextlib
import copy
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fp = importlib.import_module("fabric_package")

CASES = json.loads((HERE / "fixtures/kit-hostile-inputs-package.json").read_text(encoding="utf-8"))
V = json.loads((HERE / "fixtures/contract/package-vectors.json").read_text(encoding="utf-8"))["vectors"]


def set_pointer(doc, pointer, value):
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]
    target = doc
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if isinstance(target, list):
        target[int(parts[-1])] = value
    else:
        target[parts[-1]] = value


def refused(pkg):
    """What the kit refuses a package for besides the contract's semantic rules: the schema and the path rule."""
    return fp.schema_problems(pkg) + fp.path_problems(pkg)


def write_agent(root):
    for rel, text in V["folder"]["files"].items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    draft = {k: v for k, v in copy.deepcopy(V["digest"]["package"]).items() if k not in ("agentRef", "files", "digest", "signatures")}
    return draft


def document_bytes(draft, case):
    draft = copy.deepcopy(draft)
    if "member" in case:
        draft["service"][case["member"]] = "@@RAW@@"
    if "nest" in case:
        draft["x"] = "@@NEST@@"
    text = json.dumps(draft, indent=2, ensure_ascii=False)
    for key, value in case.get("addTopLevel", {}).items():
        text = text[: text.rindex("}")].rstrip() + ",\n  %s: %s\n}" % (json.dumps(key), json.dumps(value, ensure_ascii=False))
    data = text.encode("utf-8")
    if "member" in case:
        data = data.replace(b"@@RAW@@", bytes.fromhex(case["rawHex"]))
    if "nest" in case:
        data = data.replace(b'"@@NEST@@"', b"[" * case["nest"] + b"]" * case["nest"])
    return data


class PathRuleTests(unittest.TestCase):
    def test_every_path_case(self):
        for case in CASES["paths"]:
            with self.subTest(case["name"]):
                self.assertEqual(fp.path_problem(case["path"]) is not None, case["refused"])
                pkg = copy.deepcopy(V["digest"]["package"])
                pkg["files"][0]["path"] = case["path"]
                rules = [p for p in fp.path_problems(pkg) if p["instancePath"] == "/files/0/path"]
                self.assertEqual(bool(rules), case["refused"])
                self.assertEqual(bool(refused(pkg)), case["refused"])

    def test_the_path_rule_reads_every_path_the_schema_types_as_a_path(self):
        pkg = copy.deepcopy(V["digest"]["package"])
        bad = "a /../x"
        pkg["provider"] = bad
        pkg["evals"]["suite"] = bad
        pkg["state"][0]["path"] = bad
        pkg["dependencies"][0]["path"] = bad
        self.assertEqual(sorted(p["instancePath"] for p in fp.path_problems(pkg)),
                         ["/dependencies/0/path", "/evals/suite", "/provider", "/state/0/path"])

    def test_the_rule_shows_up_in_pack_answers(self):
        pkg = copy.deepcopy(V["digest"]["package"])
        pkg["files"][0]["path"] = "a /../../etc/passwd"
        self.assertIn("path", [p["rule"] for p in fp._all_problems(pkg, {})])


class SchemaTests(unittest.TestCase):
    def test_every_schema_case(self):
        for case in CASES["schema"]:
            with self.subTest(case["name"]):
                pkg = copy.deepcopy(V["digest"]["package"])
                for pointer, value in case["set"].items():
                    set_pointer(pkg, pointer, value)
                self.assertEqual(bool(refused(pkg)), case["refused"], refused(pkg))


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fabric-hostile-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_every_document_case(self):
        for case in CASES["documents"]:
            with self.subTest(case["name"]):
                root = self.dir / case["name"]
                root.mkdir()
                draft = write_agent(root)
                (root / fp.PACKAGE_FILE).write_bytes(document_bytes(draft, case))
                if case["answer"] == "error":
                    with self.assertRaises(fp.PackageError):
                        fp.pack(root)
                    continue
                answer = fp.pack(root)
                if case["answer"] == "ok":
                    self.assertTrue(answer["ok"], answer["problems"])
                    if "digest" in case:
                        self.assertEqual(answer["digest"], case["digest"])
                else:
                    self.assertIn(case["instancePath"], [p["instancePath"] for p in answer["problems"]])

    def test_the_command_line_answers_a_refusal_not_a_traceback(self):
        root = self.dir / "deep"
        root.mkdir()
        draft = write_agent(root)
        (root / fp.PACKAGE_FILE).write_bytes(document_bytes(draft, {"nest": 200000}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(fp.main(["pack", str(root)]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "error": "fabric.package.json nests deeper than 256 levels."})

    def test_api_callers_get_malformed_not_a_recursion_error(self):
        deep = []
        for _ in range(100000):
            deep = [deep]
        pkg = copy.deepcopy(V["digest"]["package"])
        pkg["x"] = deep
        self.assertEqual(fp.verify_package(pkg, {}), {"ok": False, "problem": "malformed"})
        self.assertIn("/digest", [f["instancePath"] for f in fp.package_findings(pkg)])


class KeyFileTests(unittest.TestCase):
    def test_every_key_file_case(self):
        directory = Path(tempfile.mkdtemp(prefix="fabric-hostile-key-"))
        self.addCleanup(shutil.rmtree, directory, True)
        key = V["keys"]["publisher"]
        for case in CASES["keyFiles"]:
            with self.subTest(case["name"]):
                path = directory / (case["name"] + ".jwk")
                path.write_text(case["prefix"] + json.dumps(dict(key["jwk"], d=fp._b64url(bytes.fromhex(key["seed"])))), encoding="utf-8")
                os.chmod(path, 0o600)
                if case["ok"]:
                    seed, kid = fp.read_signing_key(path)
                    self.assertEqual((seed.hex(), kid), (key["seed"], key["jwk"]["kid"]))
                else:
                    with self.assertRaises(fp.PackageError):
                        fp.read_signing_key(path)


@unittest.skipIf(os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions and a non-root user")
class FolderWalkTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fabric-walk-"))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in self.dir.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                os.chmod(path, 0o700)
        shutil.rmtree(self.dir, True)

    def test_an_unreadable_folder_is_refused_by_name(self):
        write_agent(self.dir)
        hidden = self.dir / "hidden"
        hidden.mkdir()
        (hidden / "unsigned.js").write_text("payload", encoding="utf-8")
        os.chmod(hidden, 0)
        with self.assertRaises(fp.PackageError) as raised:
            fp.read_folder(self.dir)
        self.assertIn("hidden", str(raised.exception))
        self.assertIn("EACCES", str(raised.exception))

    def test_an_unreadable_file_is_refused_by_name(self):
        write_agent(self.dir)
        secret = self.dir / "bin" / "serve.mjs"
        os.chmod(secret, 0)
        self.addCleanup(os.chmod, secret, 0o600)
        with self.assertRaises(fp.PackageError) as raised:
            fp.read_folder(self.dir)
        self.assertIn("bin/serve.mjs", str(raised.exception))

    def test_a_link_swapped_in_after_listing_is_never_read_through(self):
        """Finding 42: the walk opens each file without following a link, so a link that appears between the listing
        and the read is refused, never followed to the outside file's bytes."""
        write_agent(self.dir)
        outside = self.dir.parent / (self.dir.name + "-outside.txt")
        outside.write_text("outside bytes", encoding="utf-8")
        self.addCleanup(outside.unlink)
        target = self.dir / "bin" / "serve.mjs"
        real_open = os.open
        swapped = []

        def swapping_open(path, flags, *args, **kwargs):
            if str(path).endswith("serve.mjs") and not swapped:
                where = target if kwargs.get("dir_fd") is None else Path(path)
                if kwargs.get("dir_fd") is not None:
                    os.unlink(path, dir_fd=kwargs["dir_fd"])
                    os.symlink(str(outside), path, dir_fd=kwargs["dir_fd"])
                else:
                    os.unlink(where)
                    os.symlink(str(outside), where)
                swapped.append(True)
            return real_open(path, flags, *args, **kwargs)

        fp.os.open = swapping_open
        try:
            with self.assertRaises(fp.PackageError) as raised:
                fp.read_folder(self.dir)
        finally:
            fp.os.open = real_open
        self.assertTrue(swapped)
        self.assertIn("bin/serve.mjs", str(raised.exception))

    def test_the_walk_by_path_refuses_alike(self):
        """Where the platform has no openat (Windows), the walk goes by path and answers the same."""
        write_agent(self.dir)
        expected = fp.read_folder(self.dir)
        hidden = self.dir / "hidden"
        hidden.mkdir()
        (hidden / "unsigned.js").write_text("payload", encoding="utf-8")
        os.chmod(hidden, 0)
        real = fp._BY_FOLDER
        fp._BY_FOLDER = False
        try:
            with self.assertRaises(fp.PackageError) as raised:
                fp.read_folder(self.dir)
            self.assertIn("Cannot read hidden: EACCES.", str(raised.exception))
            os.chmod(hidden, 0o700)
            shutil.rmtree(hidden)
            os.symlink(str(self.dir / "bin"), str(self.dir / "linked"))
            with self.assertRaises(fp.PackageError) as raised:
                fp.read_folder(self.dir)
            self.assertIn("linked (a symlink)", str(raised.exception))
            os.unlink(self.dir / "linked")
            self.assertEqual(fp.read_folder(self.dir), expected)
        finally:
            fp._BY_FOLDER = real

    def test_a_fifo_is_refused_without_blocking(self):
        write_agent(self.dir)
        os.mkfifo(self.dir / "pipe")
        with self.assertRaises(fp.PackageError) as raised:
            fp.read_folder(self.dir)
        self.assertIn("pipe (not a regular file)", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
