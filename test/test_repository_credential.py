"""0.62.0 readings 7 and 8: one rule for a repository's credential (fabric_secrets.repository_credential), read the same
by both Python copies and by Node (test/repository-credential.test.mjs runs the same vectors)."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((Path(__file__).resolve().parent / "repository_vectors.json").read_text(encoding="utf-8"))
KEY = "ghp_" + "Fx9k" * 9  # made up at run time: shaped like a key, never one
LETTERS = {"SKLETTERS": "sk-" + "AbCd" * 10, "GHLETTERS": "ghp_" + "AbCd" * 9, "AKLETTERS": "AKIA" + "ABCD" * 4,  # made up, no digit
           "SKUPPER": "SK-" + "AbCd" * 10, "JWTLETTERS": "eyJ" + "abcd" + ".eyJ" + "efgh" + ".ijkl", "RUN40": "AbCd" * 10,
           "SKNAME": "sk-" + "learn-tutorial-notebooks", "SKWORD": "sk-" + "dictionary-extension",
           "GHREST": "hp_" + "AbCd" * 6, "SKREST": "k-" + "AbCd" * 4, "GLREST": "lpat-" + "AbCd" * 6}  # a real-looking name a key's shape starts (FAA-200 (24))


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
        secrets = load(COPIES[0])
        queries = {n: "a=b&" * n for n in (10000, 40000)}
        best = {}
        for _ in range(3):  # each size's fastest of three, measured in turn (FAA-209's rule)
            for n in (10000, 40000):
                started = time.perf_counter()
                secrets.raw_values(queries[n])
                best[n] = min(best.get(n, float("inf")), time.perf_counter() - started)
        self.assertEqual(len(secrets.raw_values(queries[40000])["a"]), 40000)
        self.assertLess(best[40000] / max(best[10000], 1e-9), 9)


if __name__ == "__main__":
    unittest.main()
