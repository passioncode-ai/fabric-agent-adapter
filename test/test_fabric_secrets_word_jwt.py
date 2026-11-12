"""FAA-321: fabric_secrets.repository_name reads a JWT's shape at a word's start (the start of a segment, or after a
`.`, `_` or `-`) in one pass, as jwt_spans does (FAA-313): the answers of the old look-behind expression, in linear
time, in both Python copies (the Node twin: test/fabric-secrets.test.mjs)."""
import importlib.util
import random
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIES = [ROOT / "plugins/fabric-agent-adapter/skills" / skill / "scripts/fabric_secrets.py"
          for skill in ("building-fabric-services", "adapting-projects-to-fabric")]
START = "ey" + "J"  # a JWT's start, put together at run time so no line of this file is shaped like a token


def load(path):
    spec = importlib.util.spec_from_file_location("fabric_secrets_w_%s" % path.parent.parent.name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def texts():
    cases = [case.replace("@", START) for case in (
        "", "@", "@ab.cd.", "@ab.cd.ef", "x-@ab.cd.ef", "x@ab.cd.ef", "a@xx-@ab.cd.e", "a@xx_@ab.cd.e", "a@xx.@ab.cd.e",
        "@a.bc.d", "-@@ab.cd.e", "q@ab.c.@cd.ef.g", "@ab..cd", "_@ab.cd", "a.@ab.cd.ef.@gh.ij.kl", "--@ab.cd.ef--")]
    rand = random.Random(321)
    for _ in range(4000):
        cases.append("".join(rand.choice([START, "e", "y", "J", "a", "_", "-", ".", "b", "Q"])
                             for _ in range(rand.randint(0, 14))))
    return cases


class JwtAtAWord(unittest.TestCase):
    def test_the_answers_of_the_look_behind_expression(self):
        for path in COPIES:
            secrets = load(path)
            old = re.compile(r"(?:\A|(?<=[._-]))%s" % secrets.JWT_SHAPE.pattern)
            for text in texts():
                with self.subTest(copy=path.parent.parent.name, text=text):
                    self.assertEqual(secrets.jwt_at_a_word(text), bool(old.search(text)))

    def test_a_long_segment_of_word_starts_is_read_in_linear_time(self):
        secrets = load(COPIES[0])
        segments = {n: (START + "-") * n for n in (4000, 16000)}
        best = {}
        for _ in range(3):  # each size's fastest of three, measured in turn (FAA-209's rule)
            for n in (4000, 16000):
                started = time.perf_counter()
                self.assertTrue(secrets.repository_name(segments[n]))
                best[n] = min(best.get(n, float("inf")), time.perf_counter() - started)
        # four times the segment costs about four times as much; the look-behind expression cost sixteen
        self.assertLess(best[16000] / max(best[4000], 1e-9), 9)


if __name__ == "__main__":
    unittest.main()
