"""FAA-75 (audit finding 34): a reference two skills share is one text, kept byte-identical in each skill so each
skill stays self-contained when installed alone."""

from pathlib import Path
import unittest

SKILLS = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills"
SHARED = {
    "references/operator-channel-and-repository.md": ("adapting-projects-to-fabric", "creating-fabric-agents"),
}


class SharedReferenceTests(unittest.TestCase):
    def test_each_shared_reference_is_identical_in_every_skill(self):
        for relative, skills in SHARED.items():
            contents = {name: (SKILLS / name / relative).read_bytes() for name in skills}
            self.assertEqual(len(set(contents.values())), 1, relative)

    def test_each_skill_links_its_copy(self):
        for relative, skills in SHARED.items():
            for name in skills:
                self.assertIn("](%s)" % relative, (SKILLS / name / "SKILL.md").read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
