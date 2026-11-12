"""0.62.0 readings 7 and 8: one rule for a repository's credential (fabric_secrets.repository_credential), read the same
by both Python copies and by Node (test/repository-credential.test.mjs runs the same vectors)."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((Path(__file__).resolve().parent / "repository_vectors.json").read_text(encoding="utf-8"))
KEY = "ghp_" + "Fx9k" * 9  # made up at run time: shaped like a key, never one
LETTERS = {"SKSTRONG": "sk-" + "Ab1d" * 10, "SKLETTERS": "sk-" + "AbCd" * 10, "GHLETTERS": "ghp_" + "AbCd" * 9, "AKLETTERS": "AKIA" + "ABCD" * 4,  # made up, no digit
           "SKUPPER": "SK-" + "AbCd" * 10, "JWTLETTERS": "eyJ" + "abcd" + ".eyJ" + "efgh" + ".ijkl", "RUN40": "AbCd" * 10,
           "SKNAME": "sk-" + "learn-tutorial-notebooks", "SKWORD": "sk-" + "dictionary-extension",
           "GHREST": "hp_" + "AbCd" * 6, "SKREST": "k-" + "Ab1d" * 4, "GLREST": "lpat-" + "AbCd" * 6}  # a real-looking name a key's shape starts (FAA-200 (24))


def made(value):
    for mark, key in LETTERS.items():
        value = value.replace(mark, key)
    return value.replace("KEY", KEY)
COPIES = [ROOT / "plugins/fabric-agent-adapter/skills" / skill / "scripts/fabric_secrets.py"
          for skill in ("building-fabric-services", "adapting-projects-to-fabric")]


def load(path):
    spec = importlib.util.spec_from_file_location("fabric_secrets_%s" % path.parent.parent.name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryCredential(unittest.TestCase):
    def test_each_copy_reads_the_vectors_alike(self):
        for path in COPIES:
            secrets = load(path)
            for value in VECTORS["credential"]:
                with self.subTest(copy=path.parent.parent.name, credential=value):
                    self.assertTrue(secrets.repository_credential(made(value)))
            for value in VECTORS["name"]:
                with self.subTest(copy=path.parent.parent.name, name=value):
                    self.assertFalse(secrets.repository_credential(made(value)))
            for value in VECTORS["password"]:  # repository_password read alone, as the Node twin's export is (readings 12)
                with self.subTest(copy=path.parent.parent.name, password=value):
                    self.assertTrue(secrets.repository_password(value))
            for value in VECTORS["no_password"]:
                with self.subTest(copy=path.parent.parent.name, no_password=value):
                    self.assertFalse(secrets.repository_password(value))


class RawValues(unittest.TestCase):
    """FAA-245: raw_values reads a query in linear time, the Node twin (fabric-secrets.mjs rawValues) the same."""

    def test_the_values_of_a_name_keep_their_order(self):
        secrets = load(COPIES[0])
        self.assertEqual(secrets.raw_values("a=1&b=x+y&a=2&a&=v&a=%zz"), {"a": ["1", "2", "", "%zz"], "b": ["x+y"], "": ["v"]})

    def test_many_pieces_of_one_name_are_read_in_linear_time(self):
        import time
        # FAA-308: this thread's CPU time, so the time it waits for a core under load does not count. 2026-11-12 on 14
        # cores: the wall-clock ratio read 15.2 against the bound of 9 under 90 busy processes; in CPU time, under a load
        # average of 150 to 187, it read 3.6 to 4.8 in ten rounds, and values copied per piece (quadratic) 16.0 and 16.2.
        # Windows keeps the wall clock: its thread time moves in scheduler ticks (about 15.6 ms), coarser than the work.
        clock = time.perf_counter if sys.platform == "win32" else time.thread_time
        secrets = load(COPIES[0])
        queries = {n: "a=b&" * n for n in (10000, 40000)}
        best = {}
        for _ in range(3):  # each size's fastest of three, measured in turn (FAA-209's rule)
            for n in (10000, 40000):
                started = clock()
                secrets.raw_values(queries[n])
                best[n] = min(best.get(n, float("inf")), clock() - started)
        self.assertEqual(len(secrets.raw_values(queries[40000])["a"]), 40000)
        self.assertLess(best[40000] / max(best[10000], 1e-9), 9)


class OnePassJwt(unittest.TestCase):
    """FAA-313: has_jwt and jwt_spans, the contract's one-pass JWT read (src/secret-shape.ts `jwtSpans`, `hasJwt`):
    the answers JWT_SHAPE gives, in linear time, in both copies and the Node twin (test/fabric-secrets.test.mjs)."""

    # "@" stands for a JWT's start, put in at run time so no line of this file is shaped like a token
    CASES = tuple(case.replace("@", "ey" + "J") for case in (
        "", "@", "@ab.cd.", "@ab.cd.ef", "x @ab.c.d", "@a.bc.d", "@@ab.cd.e", "@ab.c.@cd.ef.g", "@ab..cd", "@ab.cd",
        "a.@ab.cd.ef.@gh.ij.kl", "@ab.cd.ef.gh", "@_-.-_.", "@ab.cd.e\\nf", "@\\u00e9b.cd.ef", "--@ab.cd.ef--"))

    def test_the_answers_of_the_regular_expression(self):
        import random
        texts = list(self.CASES)
        rand = random.Random(313)
        for _ in range(3000):
            texts.append("".join(rand.choice(["eyJ", "e", "y", "J", "a", "_", "-", ".", " ", "b"])
                                 for _ in range(rand.randint(0, 14))))
        for path in COPIES:
            secrets = load(path)
            for text in texts:
                with self.subTest(copy=path.parent.parent.name, text=text):
                    self.assertEqual(secrets.has_jwt(text), bool(secrets.JWT_SHAPE.search(text)))
                    self.assertEqual(secrets.jwt_spans(text), [m.span() for m in secrets.JWT_SHAPE.finditer(text)])
                    self.assertEqual(secrets.jwt_spans(text, first=True),
                                     [m.span() for m in secrets.JWT_SHAPE.finditer(text)][:1])

    def test_a_long_run_of_jwt_starts_is_read_in_linear_time(self):
        import time
        secrets = load(COPIES[0])
        texts = {n: "eyJ" * n for n in (4000, 16000)}
        for read in (secrets.has_jwt, secrets.secret_value, secrets.secret_argument):
            best = {}
            for _ in range(3):  # each size's fastest of three, measured in turn (FAA-209's rule)
                for n in (4000, 16000):
                    started = time.perf_counter()
                    self.assertFalse(read(texts[n]))
                    best[n] = min(best.get(n, float("inf")), time.perf_counter() - started)
            # four times the text costs about four times as much; the regular expression cost sixteen
            self.assertLess(best[16000] / max(best[4000], 1e-9), 9, read.__name__)


if __name__ == "__main__":
    unittest.main()
