"""FAA-203: every annotation in the shipped scripts resolves. Under `from __future__ import annotations` a name the
module never imported is harmless at run time, but `typing.get_type_hints` raises NameError on it, and a vendoring
project's linter reports it (board finding, thread 9fd84d47: `fabric_estate.placement_trust` named `Optional`)."""
from __future__ import annotations

import importlib
import inspect
import sys
import typing
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
FOLDERS = [SKILLS / "building-fabric-services/scripts", SKILLS / "working-with-fabric/scripts",
           SKILLS / "adapting-projects-to-fabric/scripts", SKILLS / "building-fabric-services/recipes/support-agent",
           SKILLS / "creating-fabric-agents/scripts", SKILLS / "working-with-fabric/scripts/hosts/hermes"]
#: Modules that run inside their host and import it (the Hermes adapter takes hermes_cli from the running Hermes).
HOST_MODULES = {"hermes_cli"}


def modules():
    for folder in FOLDERS:
        for path in sorted(folder.glob("*.py")):
            yield folder, path.stem


def callables(module):
    for _, value in vars(module).items():
        if inspect.isfunction(value) and value.__module__ == module.__name__:
            yield value.__qualname__, value
        elif inspect.isclass(value) and value.__module__ == module.__name__:
            for name, member in vars(value).items():
                member = getattr(member, "__func__", member)
                if inspect.isfunction(member):
                    yield "%s.%s" % (value.__qualname__, name), member


class Annotations(unittest.TestCase):
    def test_every_annotation_resolves(self):
        unresolved, checked = [], 0
        for folder, name in modules():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            try:
                module = importlib.import_module(name)
            except ModuleNotFoundError as exc:
                if (exc.name or "").split(".")[0] in HOST_MODULES:
                    continue
                unresolved.append("%s: import %s" % (name, exc.__class__.__name__))
                continue
            except Exception as exc:  # noqa: BLE001 - a script that needs its host is not this test's subject
                unresolved.append("%s: import %s" % (name, exc.__class__.__name__))
                continue
            if Path(getattr(module, "__file__", "")).parent != folder:
                continue  # a same-named module from another folder: read once, from its own folder
            for qualname, function in callables(module):
                checked += 1
                try:
                    typing.get_type_hints(function)
                except (NameError, TypeError) as exc:  # TypeError: `X | Y` on Python 3.9
                    unresolved.append("%s.%s: %s" % (name, qualname, exc))
        self.assertGreater(checked, 500, "the scan reached the scripts")
        self.assertEqual(unresolved, [])


if __name__ == "__main__":
    unittest.main()
