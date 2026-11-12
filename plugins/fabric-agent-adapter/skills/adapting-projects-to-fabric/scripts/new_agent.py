#!/usr/bin/env python3
"""Create a Fabric agent project with the contract built in, in one command (FAA-270, North Star G21).

  python3 new_agent.py <folder> --id <agent-id> [--profile mcp|a2a|local-runner] [--service]
                       [--capability NAME] [--effect CLASS] [--force] [--json]

It writes, into an empty (or new) folder:

- the provider bundle `adapt_project.py scaffold` writes, pinned to the contract (`fabric-agent.json`,
  `fabric-contract.lock.json`, `fabric/`), every value it invents a sentinel `adapt_project.py check` names;
- `fabric.source.json`, the agent's source manifest (DEC-0149, `fabric-source/1`): what is source, default deny, and the
  slots an installation fills (the publisher's URI behind `provider.createdBy`, the placement record and, for a
  service, its supervisor label and port), never a value;
- the placement guard (`src/placement.py`, with its tests in `tests/`): at start the agent reads Project Observatory's
  placement record (`observatory-placement/1`) and refuses to start where the record places it on another machine,
  starts degraded when it cannot read it, and starts when there is none; `config/placement.example.json` shows the
  record's shape on neutral values;
- `README.md`, `LICENSE` (all rights reserved until the owner names the terms), `.gitignore`;
- with `--service`: `service/`, the service kit's sample (`service.py`, a fabric-service/0.1 service with one capability
  and a job) and the kit modules it imports, copied by `fabric_kit.py install`, whose digests `fabric_kit.py status`
  checks later.

A repeat with the same arguments in a folder this command made changes nothing and answers the same line. A folder that
holds anything else is refused unless `--force`, which writes the planned files over it and leaves every other file as
it is. The last stdout line is `{"folder": "<path>", "id": "<id>", "profile": "<profile>", "service": <bool>,
"created": [<paths>], "repeated": <bool>}` (`--json` prints only it). Exit 0 made or already made, 1 refused (the
reason on stderr), 2 usage. Writes nothing outside the folder; reads no key and no instance data. Standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import adapt_project as ap  # noqa: E402 - the scaffolder and the source manifest, beside this file

VERSION = "0.1.0"
RECORD = "fabric/new-agent.json"
#: The agent's id: the package's `name` grammar (`fabric-package.schema.json#/$defs/name`), kebab case.
AGENT_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
CAPABILITY = re.compile(r"[a-z][a-z0-9._-]{1,127}\Z")
KIT = HERE.parent.parent / "building-fabric-services" / "scripts"
#: What the sample service imports; `fabric_kit.py install` copies each one's closure.
SERVICE_MODULES = ("fabric_service", "fabric_interop", "fabric_board", "fabric_hub")


class Refused(Exception):
    """The folder cannot be made as asked; the reason is printed, never a value."""


PLACEMENT_PY = '''"""The placement guard: at start, before the agent polls, schedules or listens, it reads Project Observatory's
placement record and runs only on the machine that record names (creating-fabric-agents, where-agents-run.md).

    verdict(service_id, label) -> {"state": "ok" | "placed-elsewhere" | "placement-unreadable", "machine"?}

`placed-elsewhere`: the record's `elsewhere` list names this agent (its `serviceId` or its supervisor `label`) on a
machine that is not this one: refuse to start, log one line, report it as degraded. `placement-unreadable`: the file is
there and cannot be read, or is of another schema: start, and report it as degraded. No file: start.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "observatory-placement/1"


def placement_path(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or ""
    root = Path(base) if os.path.isabs(base) else Path.home() / ".local" / "share"
    return root / "project-observatory" / "placement.json"


def verdict(service_id: str, label: str, path: Optional[Path] = None) -> Dict[str, Any]:
    path = placement_path() if path is None else path
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return {"state": "ok"}
    except OSError:
        return {"state": "placement-unreadable"}
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        return {"state": "placement-unreadable"}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("elsewhere"), list):
        return {"state": "placement-unreadable"}
    for entry in doc["elsewhere"]:
        if not isinstance(entry, dict):
            continue
        ours = (service_id and entry.get("serviceId") == service_id) or (label and entry.get("label") == label)
        if ours and entry.get("placedOn") and entry.get("placedOn") != doc.get("machine"):
            return {"state": "placed-elsewhere", "machine": entry.get("placedOn")}
    return {"state": "ok"}
'''

PLACEMENT_TEST = '''"""The placement guard: one copy placed elsewhere refuses, one with no file and one with a malformed file start."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import placement  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "placement.example.json"


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "placement.json"

    def test_placed_elsewhere_refuses(self):
        self.path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        found = placement.verdict("{service_id}", "{label}", self.path)
        self.assertEqual(found["state"], "placed-elsewhere")

    def test_no_file_starts(self):
        self.assertEqual(placement.verdict("{service_id}", "{label}", self.path), {{"state": "ok"}})

    def test_a_malformed_file_starts_degraded(self):
        self.path.write_text("{{not json", encoding="utf-8")
        self.assertEqual(placement.verdict("{service_id}", "{label}", self.path), {{"state": "placement-unreadable"}})
        self.path.write_text(json.dumps({{"schema": "another/1"}}), encoding="utf-8")
        self.assertEqual(placement.verdict("{service_id}", "{label}", self.path)["state"], "placement-unreadable")

    def test_placed_on_this_machine_starts(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["machine"] = doc["elsewhere"][0]["placedOn"]
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(placement.verdict("{service_id}", "{label}", self.path), {{"state": "ok"}})


if __name__ == "__main__":
    unittest.main()
'''

README = '''# {agent_id}

A Fabric agent made with the Fabric Agent Adapter's `new` command, contract `{contract}` at `{commit}`.

## Layout

- `fabric-agent.json`, `fabric-contract.lock.json`, `fabric/`: the provider bundle, pinned to the contract. Every value
  the scaffold invented is a sentinel: `adapt_project.py check` names each one until it is replaced.
- `fabric.source.json`: the agent's source manifest (DEC-0149): what is source, and the slots an installation fills,
  never a value. `fabric_source_check.py check .` reads the source under it (exit 0 before every release).
- `src/placement.py`: the placement guard the agent runs at start, before it polls, schedules or listens.
{service_line}
## Configure

Keys are read by name from the environment or the secret store, never from a file of this repository. Slots:
{slots}

## Data

The agent's data lives apart from this source, in its data home (`<agent>-data`, or the service kit's folders), from
the first commit.
'''

GITIGNORE = """# the instance: real configuration, keys and what running the agent leaves
config/*.json
!config/*.example.json
.env
.env.*
!.env.example
*.token
*.credential
__pycache__/
*.pyc
"""


def _placement_example(service_id: str, label: str) -> str:
    return ap._json_text({"schema": "observatory-placement/1", "machine": "example-machine-a", "updatedAt": "2026-01-01T00:00:00Z",
                          "elsewhere": [{"label": label, "serviceId": service_id, "placedOn": "example-machine-b",
                                         "since": "2026-01-01T00:00:00Z", "by": "full machine-move leave"}]})


def plan(args: argparse.Namespace) -> Dict[str, str]:
    """Every file the command writes, by its path, with its text (the scaffold's own included)."""
    agent_id = args.id
    capability = args.capability or "%s.run" % agent_id.replace("-", "_")
    if not CAPABILITY.match(capability):
        raise Refused("--capability %r is not a capability name (lower case, `domain.action`)" % capability)
    scaffold = argparse.Namespace(
        profile=args.profile, provider_id="urn:fabric:provider:%s" % agent_id, provider_name=agent_id,
        capability_id="urn:fabric:capability:%s" % capability, capability_name=capability,
        schema_base="https://replace.invalid/%s/schemas" % agent_id, mcp_mode="streamable-http",
        mcp_url="https://replace.invalid/mcp", agent_card_url="https://replace.invalid/.well-known/agent-card.json",
        runner_kind="replace-me", executable_ref="urn:executable:replace-me", runtime_arg=[], effect=args.effect,
        idempotency="none", cost_preset=[], default_cost_preset=None, job=False, created_by=None, identity_method=None,
        data_class=[], probe_assertion=[])
    files = dict(ap._generated_files(scaffold))
    service_id = "%s.default" % agent_id
    label = "com.example.%s" % agent_id
    include = ["README.md", "LICENSE", ".gitignore", "src/", "tests/", "config/placement.example.json",
               "fabric-agent.json", "fabric-contract.lock.json", "fabric/"] + (["service/"] if args.service else [])
    manifest = ap.source_manifest(include, "%s, a Fabric agent" % agent_id, service=args.service)
    slots = "\n".join("- `%s` (%s%s): %s" % (s["name"], s["kind"], ", optional" if s.get("optional") else "", s["purpose"])
                      for s in manifest["slots"])
    files.update({
        ap.SOURCE_FILE: ap._json_text(manifest),
        "README.md": README.format(agent_id=agent_id, contract=ap.CONTRACT_VERSION, commit=ap.CONTRACT_COMMIT[:12], slots=slots,
                                   service_line="- `service/`: the service kit's sample, run as `python3 service/service.py "
                                   "serve --id %s --port <port> --data-dir <data>`, and the kit modules it imports.\n" % agent_id
                                   if args.service else ""),
        "LICENSE": "Copyright (c) the owner of %s. All rights reserved, until the owner names other terms.\n" % agent_id,
        ".gitignore": GITIGNORE,
        "src/placement.py": PLACEMENT_PY,
        "tests/test_placement.py": PLACEMENT_TEST.format(service_id=service_id, label=label),
        "config/placement.example.json": _placement_example(service_id, label),
    })
    record = {"tool": "fabric-agent-adapter new %s" % VERSION, "id": agent_id, "profile": args.profile, "service": args.service,
              "capability": capability, "effect": args.effect, "contract": ap.CONTRACT_COMMIT}
    files[RECORD] = ap._json_text(record)
    return files


def _service_files(folder: Path) -> List[str]:
    """Copy the kit's sample and the closure of what it imports into `service/` (fabric_kit.py install)."""
    import importlib.util
    found = importlib.util.spec_from_file_location("fabric_kit", KIT / "fabric_kit.py")  # the kit's own installer
    fabric_kit = importlib.util.module_from_spec(found)
    found.loader.exec_module(fabric_kit)  # type: ignore[union-attr]
    target = folder / "service"
    result = fabric_kit.install(target, "python", list(SERVICE_MODULES))
    if result["refused"]:
        raise Refused("service/ holds kit modules this kit does not recognise: %s" % ", ".join(result["refused"]))
    shutil.copyfile(KIT / "sample_service.py", target / "service.py")
    return ["service/" + name for name in result["copied"] + result["kept"]] + ["service/service.py"]


def make(folder: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if not AGENT_ID.match(args.id) or len(args.id) > 64:
        raise Refused("--id %r is not an agent id (lower case words joined by -, at most 64 characters)" % args.id)
    files = plan(args)
    answer = {"folder": str(folder), "id": args.id, "profile": args.profile, "service": args.service}
    if folder.exists() and not folder.is_dir():
        raise Refused("%s is not a folder" % folder.name)
    present = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) if folder.is_dir() else []
    if present:
        record = folder / RECORD
        try:
            same = record.is_file() and json.loads(record.read_text(encoding="utf-8")) == json.loads(files[RECORD])
        except ValueError:
            same = False
        if same and all((folder / path).is_file() for path in files) and not args.force:
            return dict(answer, created=[], repeated=True)
        if not args.force:
            raise Refused("the folder is not empty and was not made by this command with these arguments: "
                          "name another folder, or pass --force to write the planned files over it")
    for path, text in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    created = sorted(files)
    if args.service:
        created = sorted(created + _service_files(folder))
    return dict(answer, created=created, repeated=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="new_agent.py", description="Create a Fabric agent project with the contract built in.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--id", required=True, help="the agent's id, kebab case (example-agent)")
    parser.add_argument("--profile", choices=("mcp", "a2a", "local-runner"), default="mcp")
    parser.add_argument("--service", action="store_true", help="also wire the service kit's sample (fabric-service/0.1)")
    parser.add_argument("--capability", help="its capability, `domain.action` (default <id>.run)")
    parser.add_argument("--effect", choices=ap.EFFECT_CLASSES, default="none",
                        help="the capability's effect class (default none: declare money, deletion or publication now)")
    parser.add_argument("--force", action="store_true", help="write the planned files into a folder that holds others")
    parser.add_argument("--json", action="store_true", help="print only the last line")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        answer = make(args.folder.expanduser().resolve(), args)
    except (Refused, ap.AdaptationError, OSError) as exc:
        print("new_agent.py: %s" % (exc if not isinstance(exc, OSError) else "the folder cannot be written (%s)"
                                    % type(exc).__name__), file=sys.stderr)
        return 1
    if not args.json:
        print("%s %s: %d file(s)%s" % ("already made" if answer["repeated"] else "made", args.id, len(answer["created"]),
                                       "" if answer["repeated"] else "; next: replace the sentinels `adapt_project.py check` "
                                       "names, then run fabric_source_check.py check on the folder"))
    print(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
