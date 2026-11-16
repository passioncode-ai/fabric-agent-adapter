"""The usage data files `new_agent.py` lays down in a new agent project (FAA-202, the contract's DEC-0157, UD-1 to UD-6).

Not a command: `new_agent.py` reads the three texts below and writes them as `src/usage_data.py`,
`tests/test_usage_data.py` and `docs/usage-data.md`, with `{agent_id}` replaced by the agent's id. The generated module
is on by default, sends nothing before its notice was shown, nothing without the receiving host's app key (so a source
checkout, a fork and a test send nothing), and only counts and codes. Standard library only.
"""

from __future__ import annotations

#: The slot a release fills with the receiving host's app key; without it the agent sends nothing.
APP_KEY_SLOT = {"name": "USAGE_DATA_APP_KEY", "kind": "config", "optional": True,
                "purpose": "the receiving analytics host's app key, set by the release; without it nothing is sent (DEC-0157)"}

USAGE_DATA_PY = '''"""Anonymous usage and error data, on by default (the Fabric Agent Contract's DEC-0157, rules UD-1 to UD-6).

    usage = UsageData("{agent_id}", "0.1.0", data_dir)
    text = usage.notice_due()   # show it once in the first output a person reads, then usage.notice_shown()
    usage.track("run_finished", {"outcome": "ok", "items": 3})
    usage.error("timeout", "src/agent.py:run")
    usage.flush()               # at the end of a run, or on a timer

    python3 src/usage_data.py --data-dir <dir> status | on | off

UD-1: nothing leaves before the notice was shown where the person reads it; no answer is needed, no answer means on.
UD-2: this agent's own switch (absent means on) governs this agent alone; an earlier no in the shared
`PassionCode/installation.json`, before this agent's first send and with its own switch never set, stays off; a shared
file that cannot be read sends nothing in that run. Off drops what waits. UD-3: the installation id is this agent's
own random UUID, deleted at off and made anew at on; the session id lives in memory and is renewed after an idle hour;
an event carries counts, booleans and short codes only, so no text, path, address, account or credential can leave
(a property of any other shape is refused with ValueError). Nothing is sent without the receiving host's app key
(`USAGE_DATA_APP_KEY`, set by the release): a source checkout, a fork and a test send nothing.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import random
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request
import uuid

HOST = os.environ.get("USAGE_DATA_HOST") or "https://analytics.passioncode.ai"
RECEIVER = "PassionCode.ai"
STATE_FILE = "usage-data.json"
SDK = "fabric-agent-template-usage@1"
NAME = re.compile(r"[a-z][a-z0-9_]{0,59}\\Z")
CODE = re.compile(r"[a-z0-9][a-z0-9_.:/-]{0,63}\\Z")
#: A code that is a path, an address or a long hex or base64 run is not a code.
NOT_A_CODE = re.compile(r"(?:^/|^~|@|//|\\\\|\\.\\.|[0-9a-f]{16,}|[A-Za-z0-9+_-]{32,})")
BATCH = 25
MAX_QUEUE = 200
MAX_AGE = 23 * 3600
IDLE = 3600
#: post(url, headers, body) -> HTTP status; raises OSError when the host cannot be reached.
Post = Callable[[str, Dict[str, str], bytes], int]


def shared_file() -> Path:
    """The PassionCode family's shared `installation.json`, where the other products of the family keep it."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or ""
        base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".config"
    return base / "PassionCode" / "installation.json"


def _post(url: str, headers: Dict[str, str], body: bytes) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _code(value: Any, what: str) -> str:
    if not isinstance(value, str) or not CODE.match(value) or NOT_A_CODE.search(value):
        raise ValueError("%s is not a short code (lower case letters, digits and _ . : / -, no path or address)" % what)
    return value


class UsageData:
    def __init__(self, product: str, version: str, data_dir: Path, app_key: Optional[str] = None,
                 shared: Optional[Path] = None, post: Optional[Post] = None, clock: Callable[[], float] = time.time):
        self.product, self.version = product, version
        self.path = Path(data_dir) / STATE_FILE
        self.app_key = os.environ.get("USAGE_DATA_APP_KEY") if app_key is None else app_key
        self.shared = shared_file() if shared is None else shared
        self.post, self.clock = post or _post, clock
        self.queue: List[Dict[str, Any]] = []
        self.session = ("", 0.0)
        self.environment = "sandbox" if "-" in version else "production"

    # the agent's own state file
    def _load(self) -> Dict[str, Any]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _save(self, doc: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(".%s.%s" % (STATE_FILE, uuid.uuid4().hex))
        temporary.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def _shared_answer(self) -> str:
        """absent | on | off | unreadable: the shared file's `analytics` field, read only for an earlier no."""
        try:
            doc = json.loads(self.shared.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "absent"
        except (OSError, ValueError):
            return "unreadable"
        if not isinstance(doc, dict):
            return "unreadable"
        return "off" if doc.get("analytics") is False else "on"

    def status(self) -> Dict[str, Any]:
        """{state: on | off | waiting, reason, noticeShown, sends}: what the switch reads now, and why."""
        doc = self._load()
        shown = bool(doc.get("noticeShownAt"))
        if doc.get("enabled") is False:
            state, reason = "off", "turned off in this agent"
        elif doc.get("enabled") is None and not doc.get("firstSentAt") and self._shared_answer() == "off":
            state, reason = "off", "an earlier no in the shared PassionCode installation file; turn it on here"
        elif doc.get("enabled") is None and not doc.get("firstSentAt") and self._shared_answer() == "unreadable":
            state, reason = "waiting", "nothing is sent until the shared PassionCode installation file can be read"
        else:
            state, reason = "on", "on by default" if doc.get("enabled") is None else "turned on in this agent"
        return {"state": state, "reason": reason, "noticeShown": shown,
                "sends": state == "on" and shown and bool(self.app_key)}

    # UD-1: the notice
    def notice_due(self) -> Optional[str]:
        """The notice, when it has not been shown and this agent would send; else None."""
        if not self.app_key or self._load().get("noticeShownAt") or self.status()["state"] == "off":
            return None
        return ("%s sends %s anonymous usage and error data (counts of what it did and error codes, never your text, "
                "files, paths or accounts) to %s, to improve it. It sends a random installation id of this install alone, "
                "which ties its events together though no person is named, and a session id that ties one session's "
                "events together. Turn it off with `python3 src/usage_data.py --data-dir <data dir> off`; what is sent "
                "and kept is in docs/usage-data.md." % (self.product, RECEIVER, HOST.split("//")[-1]))

    def notice_shown(self) -> None:
        doc = self._load()
        if not doc.get("noticeShownAt"):
            doc["noticeShownAt"] = int(self.clock())
            self._save(doc)

    # UD-2: the switch
    def set(self, on: bool) -> Dict[str, Any]:
        doc = self._load()
        doc["enabled"] = bool(on)
        doc.pop("installationId", None)  # off deletes this agent's id; on makes a new one at the next send
        if on:
            doc["installationId"] = str(uuid.uuid4())
        else:
            self.queue.clear()
        self._save(doc)
        return self.status()

    # UD-3: events
    def _session(self, at: float) -> str:
        if not self.session[0] or at - self.session[1] > IDLE:
            self.session = ("%d" % (int(at) * 100000000 + random.randrange(100000000)), at)
        self.session = (self.session[0], at)
        return self.session[0]

    def track(self, name: str, props: Optional[Dict[str, Any]] = None) -> bool:
        """Queue one event; False when the switch is off. A property must be a number, a boolean or a short code."""
        if not isinstance(name, str) or not NAME.match(name):
            raise ValueError("an event name is lower case letters, digits and _, at most 60")
        clean: Dict[str, Any] = {}
        for key, value in (props or {}).items():
            if not isinstance(key, str) or not NAME.match(key) or key in ("iid", "environment"):
                raise ValueError("a property name is lower case letters, digits and _")
            if isinstance(value, bool) or (isinstance(value, (int, float)) and abs(value) < 1e15):
                clean[key] = value
            else:
                clean[key] = _code(value, "property %s" % key)
        if self.status()["state"] == "off":
            return False
        at = self.clock()
        self.queue.append({"at": at, "eventName": name, "props": clean, "sessionId": self._session(at)})
        del self.queue[:-MAX_QUEUE]
        return True

    def error(self, code: str, place: str) -> bool:
        """An error by its code and the place in this agent's own code (`src/agent.py:run`), nothing of its text."""
        return self.track("error", {"code": _code(code, "the error code"), "place": _code(place, "the place")})

    def flush(self) -> int:
        """Send what waits, 25 at a time; the number sent. Off drops it; no notice, no key or no shared answer keeps it."""
        state = self.status()
        if state["state"] == "off":
            self.queue.clear()
            return 0
        if not state["sends"]:
            return 0
        doc = self._load()
        if not doc.get("installationId"):
            doc["installationId"] = str(uuid.uuid4())
            self._save(doc)
        cutoff, sent = self.clock() - MAX_AGE, 0
        self.queue = [e for e in self.queue if e["at"] >= cutoff]
        while self.queue:
            batch = self.queue[:BATCH]
            body = json.dumps([{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["at"])), "sessionId": e["sessionId"],
                "eventName": e["eventName"],
                "systemProps": {"isDebug": self.environment != "production", "osName": platform.system() or "unknown",
                                "appVersion": self.version, "sdkVersion": SDK},
                "props": dict(e["props"], iid=doc["installationId"], environment=self.environment)} for e in batch]).encode()
            try:
                answer = self.post(HOST.rstrip("/") + "/api/v0/events",
                                   {"App-Key": str(self.app_key), "Content-Type": "application/json"}, body)
            except OSError:
                break  # the host cannot be reached: keep it for a later flush
            if 200 <= answer < 300 or answer in (400, 404):
                del self.queue[:len(batch)]  # sent, or refused for good
                sent += len(batch) if answer < 300 else 0
            else:
                break
        if sent and not doc.get("firstSentAt"):
            doc["firstSentAt"] = int(self.clock())
            self._save(doc)
        return sent


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="usage_data.py", description="This agent's anonymous usage data switch.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("command", choices=("status", "on", "off"))
    args = parser.parse_args(argv)
    usage = UsageData("{agent_id}", "0.0.0", args.data_dir)
    answer = usage.status() if args.command == "status" else usage.set(args.command == "on")
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

USAGE_DATA_TEST = '''"""The usage data module: nothing before the notice, the switch, an earlier no, and nothing but counts and codes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import usage_data  # noqa: E402


class Host:
    def __init__(self, status=200):
        self.status, self.bodies = status, []

    def __call__(self, url, headers, body):
        self.bodies.append((url, headers, json.loads(body.decode("utf-8"))))
        if self.status is None:
            raise OSError("unreachable")
        return self.status


class UsageDataTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.shared = self.root / "PassionCode" / "installation.json"
        self.host = Host()
        self.now = [1800000000.0]

    def usage(self, app_key="example-app-key", version="1.2.3"):
        return usage_data.UsageData("{agent_id}", version, self.root / "data", app_key=app_key, shared=self.shared,
                                    post=self.host, clock=lambda: self.now[0])

    def test_nothing_leaves_before_the_notice_then_counts_with_the_installation_id(self):
        usage = self.usage()
        self.assertTrue(usage.track("run_finished", {"outcome": "ok", "items": 3, "dry": False}))
        self.assertEqual(usage.flush(), 0)
        self.assertEqual(self.host.bodies, [])
        self.assertIn("anonymous usage and error data", usage.notice_due())
        usage.notice_shown()
        self.assertIsNone(usage.notice_due())
        self.assertEqual(usage.flush(), 1)
        url, headers, events = self.host.bodies[0]
        self.assertTrue(url.endswith("/api/v0/events"))
        self.assertEqual(headers["App-Key"], "example-app-key")
        props = events[0]["props"]
        self.assertEqual((props["outcome"], props["items"], props["environment"]), ("ok", 3, "production"))
        self.assertRegex(props["iid"], r"^[0-9a-f-]{36}$")

    def test_no_app_key_sends_nothing_and_shows_no_notice(self):
        usage = self.usage(app_key="")
        usage.track("run_finished")
        usage.notice_shown()
        self.assertIsNone(self.usage(app_key="").notice_due())
        self.assertEqual(usage.flush(), 0)
        self.assertEqual(self.host.bodies, [])

    def test_off_drops_what_waits_and_on_makes_a_new_id(self):
        usage = self.usage()
        usage.notice_shown()
        usage.track("run_finished")
        usage.flush()
        first = self.host.bodies[0][2][0]["props"]["iid"]
        usage.track("run_finished")
        self.assertEqual(usage.set(False)["state"], "off")
        self.assertFalse(usage.track("run_finished"))
        self.assertEqual(usage.flush(), 0)
        self.assertNotIn("installationId", json.loads((self.root / "data" / "usage-data.json").read_text()))
        usage.set(True)
        usage.track("run_finished")
        usage.flush()
        self.assertNotEqual(self.host.bodies[-1][2][0]["props"]["iid"], first)

    def test_an_earlier_no_in_the_shared_file_stays_off_until_the_first_send(self):
        self.shared.parent.mkdir(parents=True)
        self.shared.write_text(json.dumps({"version": 1, "id": "shared", "analytics": False}))
        self.assertEqual(self.usage().status()["state"], "off")
        self.assertIsNone(self.usage().notice_due())
        usage = self.usage()
        usage.set(True)
        self.assertEqual(usage.status()["state"], "on")

    def test_an_unreadable_shared_file_sends_nothing_in_that_run(self):
        self.shared.parent.mkdir(parents=True)
        self.shared.write_text("{not json")
        usage = self.usage()
        usage.notice_shown()
        usage.track("run_finished")
        self.assertEqual(usage.status()["state"], "waiting")
        self.assertEqual(usage.flush(), 0)
        self.shared.write_text(json.dumps({"version": 1, "id": "shared", "analytics": True}))
        self.assertEqual(usage.flush(), 1)

    def test_a_planted_identifier_never_leaves(self):
        usage = self.usage()
        for value in ("/".join(("", "Users", "example", "notes.txt")), "C:\\\\\\\\Users\\\\\\\\example", "person@example.com", "https://example.com/a",
                      "a sentence a person wrote", "0123456789abcdef0123", "x" * 70, None, {"nested": 1}, ["a"]):
            with self.assertRaises(ValueError, msg=repr(value)):
                usage.track("run_finished", {"detail": value})
        with self.assertRaises(ValueError):
            usage.track("Run Finished")
        with self.assertRaises(ValueError):
            usage.error("timeout", "~/secret/place")
        self.assertEqual(usage.queue, [])

    def test_the_host_refusing_drops_and_the_host_down_keeps(self):
        usage = self.usage()
        usage.notice_shown()
        usage.track("run_finished")
        self.host.status = None
        self.assertEqual(usage.flush(), 0)
        self.assertEqual(len(usage.queue), 1)
        self.host.status = 400
        self.assertEqual(usage.flush(), 0)
        self.assertEqual(usage.queue, [])

    def test_an_event_older_than_a_day_is_dropped_and_a_pre_release_is_sandbox(self):
        usage = self.usage(version="1.3.0-rc.1")
        usage.notice_shown()
        usage.track("run_finished")
        self.now[0] += 24 * 3600
        self.assertEqual(usage.flush(), 0)
        usage.track("run_finished")
        usage.flush()
        self.assertEqual(self.host.bodies[-1][2][0]["props"]["environment"], "sandbox")
        self.assertTrue(self.host.bodies[-1][2][0]["systemProps"]["isDebug"])


if __name__ == "__main__":
    unittest.main()
'''

USAGE_PAGE = """# Usage data

{agent_id} sends anonymous usage and error data, on by default (the Fabric Agent Contract's DEC-0157, UD-1 to UD-6).
The owner checks every line below before the first release that carries an app key, and keeps it true.

- **What is sent:** counts of what the agent did and error codes with the place in its own code (`src/usage_data.py`
  refuses anything else), the agent's version, the operating system's name, and whether the build is a pre-release.
  Never a person's text, a file, a path, an account, an address or a credential.
- **Installation id:** a random UUID of this install alone, not shared with another product; it ties this install's
  events together though no person is named. Turning the switch off deletes it; turning it on makes a new one. A
  session id lives in memory only and is renewed after an idle hour.
- **Where it goes:** PassionCode.ai, to its analytics host `analytics.passioncode.ai`. Readers there: (the owner names
  every service or agent that reads the raw events, with its purpose).
- **The switch:** `python3 src/usage_data.py --data-dir <data dir> off` (and `on`, `status`). An earlier no in the
  shared PassionCode installation file stays off. Nothing is sent before the notice was shown once, and nothing without
  the release's app key (`USAGE_DATA_APP_KEY`).
- **How long it is kept:** the host deletes events after 730 days and removes installation ids from them after 400
  days; its backups keep them beyond that (nightly copies 14 days, a weekly backup off the host).
- **Erasure:** the host offers no erasure by installation id, so data already sent cannot be erased.
- **Since version:** (the owner names the first version that sends).
"""
