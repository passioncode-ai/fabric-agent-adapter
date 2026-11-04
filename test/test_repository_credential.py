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
           "SKUPPER": "SK-" + "AbCd" * 10, "JWTLETTERS": "eyJ" + "abcd" + ".eyJ" + "efgh" + ".ijkl", "RUN40": "AbCd" * 10}


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


if __name__ == "__main__":
    unittest.main()
