#!/usr/bin/env python3
"""Install a dashboard-only fabric-service/0.1 service (FAA-268): a descriptor with a dashboard and nothing else.

  python3 install.py --id <id> --folder <folder> [--instance default] [--name NAME] [--repository URI]
                     [--port N] [--label LABEL --plist PLIST] [--services-dir DIR] [--json]

The service has no capabilities, no provider keys and no token of anybody else: its page shows what the person's agent
reads through the Fabric Dashboards MCP (`list_services`, `spend`, `connections`) and Project Observatory and writes
into `<folder>/snapshot.json`. The installer picks a loopback port no other descriptor claims and that is free now,
writes the token file (0600) and the descriptor through the kit's `write_descriptor`, whose port claim check refuses a
port another descriptor declares. The last stdout line is `{"descriptor": <path>, "key": "<id>.<instance>", "port": <n>}`
(`--json` prints only it). A repeat with the same `--id` changes nothing and answers the same line. The HA-1 port claim
file per OS account is not written: its schema waits on the contract's CT-228.

Exit codes: 0 installed or already installed, 1 refused (the reason on stderr), 2 usage.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if str(Path(__file__).resolve().parent) not in sys.path:  # the kit installed beside it, under `python3 -I` too
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import fabric_service as fs
except ImportError:  # in the adapter's repository: the kit is two folders up
    sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))
    import fabric_service as fs

VERSION = "0.1.0"
TOOL = "dashboard-only install %s" % VERSION
PORT_FIRST, PORT_LAST = 47300, 47999  # the recipe's range; a port another descriptor claims is skipped
ATTEMPTS = 8  # a port taken between the check and the write is retried on the next one


def claimed_ports(services: Optional[Path], me: str) -> set:
    ports = set()
    for _path, other in fs.read_descriptors(services):
        if "%s.%s" % (other.get("id"), other.get("instance", "default")) == me or other.get("placement") == "remote":
            continue
        try:
            ports.add(fs.port_of(str(other.get("origin", ""))))
        except fs.ServiceError:
            continue
    return ports


def free_now(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def candidates(services: Optional[Path], me: str, wanted: Optional[int]) -> List[int]:
    if wanted is not None:
        return [wanted]
    taken = claimed_ports(services, me)
    return [p for p in range(PORT_FIRST, PORT_LAST + 1) if p not in taken and free_now(p)][:ATTEMPTS]


def git_origin(folder: Path) -> Optional[str]:
    """The folder's own `origin`, when it is an https URL the kit accepts as source.repository."""
    try:
        out = subprocess.run(["git", "-C", str(folder), "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    url = out.stdout.strip()
    if out.returncode != 0 or not url.startswith("https://"):
        return None
    return url[:-4] if url.endswith(".git") else url


def answer(descriptor_file: Path, descriptor: Dict[str, Any]) -> Dict[str, Any]:
    return {"descriptor": str(descriptor_file), "key": "%s.%s" % (descriptor["id"], descriptor["instance"]),
            "port": fs.port_of(descriptor["origin"])}


def build(args: argparse.Namespace, folder: Path, port: int, repository: Optional[str]) -> Dict[str, Any]:
    descriptor: Dict[str, Any] = {
        "protocol": fs.PROTOCOL, "id": args.id, "instance": args.instance, "name": args.name or args.id,
        "summary": "A dashboard-only service: no capabilities, no provider keys.",
        "origin": "http://127.0.0.1:%d" % port,
        "auth": {"tokenFile": str(folder / "service.token")},
        "lifecycle": {"manager": "launchd", "label": args.label, "plist": args.plist} if args.label else {"manager": "none"},
        "paths": {"data": str(folder), "logs": []},
        "installedAt": fs.now_iso(),
        "installedBy": {"by": "person", "role": "operator", "tool": TOOL},
    }
    if repository:
        descriptor["source"] = {"repository": repository}
    return descriptor


def install(args: argparse.Namespace) -> Dict[str, Any]:
    services = Path(args.services_dir).expanduser() if args.services_dir else None
    folder = Path(args.folder).expanduser().resolve()
    me = "%s.%s" % (args.id, args.instance)
    installed = fs.descriptor_path(args.id, args.instance, services)
    if installed.is_file():
        try:
            current = json.loads(installed.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise fs.ServiceError("The installed descriptor %s cannot be read (%s); nothing was written." % (installed, exc))
        by = current.get("installedBy") if isinstance(current, dict) else None
        if not (isinstance(by, dict) and str(by.get("tool", "")).startswith("dashboard-only install")):
            raise fs.ServiceError("%s is installed by another installer (%s); nothing was written." % (me, installed))
        if Path(str((current.get("paths") or {}).get("data", ""))) != folder:
            raise fs.ServiceError("%s is installed with the folder %s, not %s; nothing was written."
                                  % (me, (current.get("paths") or {}).get("data"), folder))
        return answer(installed, current)
    if args.label and not args.plist:
        raise fs.ServiceError("--label needs --plist, the launchd job's plist path.")
    repository = args.repository or git_origin(folder)
    ports = candidates(services, me, args.port)
    if not ports:
        raise fs.ServiceError("No free port in %d-%d that no other descriptor claims." % (PORT_FIRST, PORT_LAST))
    last: Optional[Exception] = None
    for port in ports:
        descriptor = build(args, folder, port, repository)
        problems = fs.validate_descriptor(descriptor)
        refusal = ("Descriptor is invalid: %s." % "; ".join(problems) if problems else fs.source_refusal(descriptor, services))
        if refusal:  # before any side effect: a refused install leaves nothing behind
            raise fs.ServiceError(refusal)
        try:  # the descriptor first: a port claim the kit refuses leaves no folder and no token behind
            path = fs.write_descriptor(descriptor, services)
        except fs.ServiceError as exc:  # the kit's port claim: another descriptor declared it in between
            if "already claimed" not in str(exc) or args.port is not None:
                raise
            last = exc
            continue
        try:
            fs.ensure_private_dir(folder)
            fs.ensure_token(folder / "service.token")  # 0600, never printed
        except (OSError, fs.ServiceError):
            fs.remove_descriptor(args.id, args.instance, services)  # no descriptor names a token that is not there
            raise
        return answer(path, descriptor)
    raise fs.ServiceError(str(last))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", required=True)
    parser.add_argument("--folder", required=True, help="the service's own folder: token, data, snapshot")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--name")
    parser.add_argument("--repository", help="the repository its code is built from (default: the folder's https origin)")
    parser.add_argument("--port", type=int, help="this port and no other")
    parser.add_argument("--label", help="a launchd job's label, with --plist")
    parser.add_argument("--plist")
    parser.add_argument("--services-dir", help="the descriptor directory (default: FABRIC_SERVICES_DIR, else the OS's)")
    parser.add_argument("--json", action="store_true", help="print only the JSON line")
    args = parser.parse_args(argv)
    try:
        installed_before = fs.descriptor_path(args.id, args.instance,
                                              Path(args.services_dir).expanduser() if args.services_dir else None).is_file()
        result = install(args)
    except (fs.ServiceError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.json:
        print("%s %s on port %d: %s" % ("Already installed:" if installed_before else "Installed", result["key"],
                                       result["port"], result["descriptor"]))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
