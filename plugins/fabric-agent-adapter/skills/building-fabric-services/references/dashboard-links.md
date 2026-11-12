# Dashboard links: producer and consumer rule

Read when an agent creates a dashboard, implements `<tool> dashboard`, or hands
an existing Fabric service dashboard to a person. This also applies to generated
agent instructions and completion messages. Headless agents need no dashboard;
API origins, external docs and OAuth links are not dashboard actions.

The rule (the operator's, 2026-10-24): every page of an agent or a local Fabric
service opens only in Fabric Dashboards, never in Safari, Dia, Chrome or any
other browser, unless Fabric Dashboards is confirmed not installed.

## Contents

- Resolve, then hand over
- The block a generated AGENTS.md carries
- An agent with a page and no service descriptor
- Device and channel
- Portable output gate
- Degradation

## Resolve, then hand over

1. Discover the target computer and exact registered `service.id.instance`.
   Never guess a key from a project name or port. `default` and `preview` differ.
2. Discover Fabric Dashboards tools by their descriptions; provider tool prefixes
   differ. Use `link` with service + path (including the page's query/fragment),
   or pass a known local service URL to it. For a root, `list_services.open_link`
   is also authoritative. Hand back **the returned `open_link` as the primary
   dashboard action**. Do not rebuild its URI or double-encode `path`.
3. Use `host_status`, where offered, to distinguish available, not_installed,
   unknown, incompatible, handler_mismatch and unsupported. It is a read, not a GUI launch.
   With an older server lacking that tool, host readiness is unverified: use a
   compatible host resolver or report the limitation, not presumed absence.
4. A request for a link opens nothing. A request to open uses the host `open`
   tool/approved opener, which starts or focuses the existing Fabric Dashboards
   and reuses the service view, with `fallback=never`: it forbids a browser.
   `if_absent` permits one only for confirmed absence. Discover schema support
   first: older `open` implementations may silently fall back on failure and are
   not strict. Never
   `open <url>`, `open -a Safari`, `xdg-open`, `start <url>`, `webbrowser.open`
   or `shell.openExternal` aimed at the service's pages.
5. An installed host that failed to open is **not absent**. Report the failure;
   do not silently launch HTTP in a browser, a second server, `npm run dev`, or
   another standalone dashboard. A stopped backend stays on its host status/Start
   surface; automatic wake-up follows the host's lifecycle grant and held-off state.
6. Preserve an unavailable/error result. `accepted_by_os` proves dispatch only,
   not page readiness, a successful login, or a completed job. Links carry no
   bearer tokens or login codes. The host handles dashboard authentication.

## The block a generated AGENTS.md carries

An agent with a page carries this block in its `AGENTS.md` (its `CLAUDE.md` reads
it through `@AGENTS.md`), beside its browser rule, and its completion and
notification renderers follow it:

```markdown
## Pages open only in Fabric Dashboards

Every page of this agent (its dashboard, a job, an approval, a report) opens in
Fabric Dashboards, never in a browser. Resolve the registered service key with
the fabric-dashboards MCP (`list_services`, never guessed) and hand over the
`open_link` its `link` tool returns for the page's path; to open it, call the
host's `open` with `fallback=never`. Never `open <url>`, `open -a Safari`,
`xdg-open`, `start <url>`, `webbrowser.open` or `shell.openExternal` on this
agent's pages. A browser only when `host_status` confirms `not_installed`, and
a raw `http://127.0.0.1:<port>` address only after the listener on that port is
this OS account's (DEC-0154 PL-3 and HA-2; the adapter's `building-fabric-services/scripts/fabric_peer_owner.py`: `server_end` of a connection it opens and sends nothing on; `check_service.py <id>.<instance>` prints it as `listener.owner`): a
`foreign-user` listener is reported, never opened (the link gate below takes
that owner as `listener_owner`). An installed host that failed
to open is reported, not replaced by HTTP. Links
carry no token or login code. Every completion and notification action passes
the Fabric Agent Adapter's link gate before delivery: `check_dashboard_link.py`
in its `building-fabric-services/scripts`, run from that skill's directory;
where it cannot run, the action is compared by hand and the check is NOT_RUN.
```

The project's checks run the gate below on each renderer's action, and a test
holds a raw-HTTP primary action beside an available host refused.

## An agent with a page and no service descriptor

Fabric Dashboards opens only a page a service descriptor names. An agent that
serves a local page without one cannot be opened there, and a browser is not the
workaround. Make it a `fabric-service/0.1` service (`building-fabric-services`:
the descriptor, the well-known document, the login-code routes and a declared
dashboard); until that lands, file a board row for it and say the page waits on it.

## Device and channel

A custom scheme opens on the device receiving it. A phone's localhost is not the
computer. For a remote chat use a supported, authorized action addressed to the
computer (device + service + page) and wait for its receipt. If no such transport
exists, say so; a skill is not a relay. If a client strips custom schemes, provide
a copyable URI with its target computer or the supported remote action; do not
silently replace it with HTTP or promise that Markdown is clickable.

## Portable output gate

Before emitting an executable dashboard action in a managed renderer, run
`scripts/check_dashboard_link.py` **from this skill's own directory** with one
JSON object on stdin. It exits 0 for an allowed action, 1 for a refused/malformed
one; it opens nothing and performs no network, discovery or authentication.
Its trusted context is supplied by the host, not by untrusted model output:

```json
{
  "resolved": {
    "service": "example-agent.default",
    "open_link": "fabric-dashboards://service/example-agent.default?path=%2Fdashboard",
    "http_url": "http://127.0.0.1:47195/dashboard"
  },
  "host": {"state": "available"},
  "target_device": "workstation",
  "viewer_device": "workstation",
  "fallback": "never",
  "action": {"kind": "native_link", "url": "fabric-dashboards://service/example-agent.default?path=%2Fdashboard"}
}
```

`native_link` must equal the resolved open_link, with an available host on the
viewer's device. `browser_link` must equal http_url, with confirmed not_installed,
if_absent policy, the same device and `"listener_owner": "this-account"`: the kind
the host read for the listener on http_url's port (`fabric_peer_owner`'s
`this-account`, `another-account`, `system`, `unknown`, `none`, or
`check_service.py`'s `foreign-user`); any other, or none given, refuses the
browser (DEC-0154 PL-3, FAA-251). The host reads that kind right before it opens
the page with the adapter's
`python3 building-fabric-services/scripts/fabric_peer_owner.py listener <port>`
(or `node building-fabric-services/scripts/fabric-peer-owner.mjs listener <port>`),
which prints it on one line (`--json` prints the whole owner) and sends nothing
to the port (FAA-315). Where the socket table is restricted (macOS 27.2 for an
ad-hoc-signed Python or Node, DEC-0155 RT-4) only this account's listener on
exactly `127.0.0.1` reads `this-account`; a wildcard or `::1` bind reads
`unknown` (`table-restricted`), and the browser is refused. The native link does not take it: Fabric
Dashboards checks its own listener. Contract DEC-0123 PL-3 also allows a browser
on `unsupported` (a system the host does not ship for); the gate treats
`unsupported` as no fallback, by the operator's rule that a browser opens only on a
confirmed `not_installed`, and macOS never reports it (FAA-137). `remote_open` instead contains `device_id`,
`service` and optional `path`, exactly matching the target and resolved page;
its acceptance does not authorize or deliver it. Enforce grants/dedup/expiry in
the transport. Unknown or failed host status produces no executable local action.
A separately labelled copyable link for diagnosis is not an open action.

The gate is **agent-side**: the agent runs it from this skill's directory before it
delivers an action. It is never copied into the generated project and never run by
that project's CI: the adapter's versioned plugin folder has no stable path there, so
its result in a project's pipeline would always be NOT_RUN. A raw-HTTP primary action
with an available host is the gate's negative fixture; a valid native action is the
positive one. Keep diagnostics separate. This gate checks structured actions, not
arbitrary prose: a CLI invocation or instructions alone do not prove all final answers
from every agent are filtered.

The generated project pins the same negative fixture in its own test suite, without
calling the gate: a test that renders its completion and notification output with an
available host and fails when a raw loopback `http_url` or a legacy `open?service=`
link appears in it. The snippet is self-contained; `render` stands for the project's
own renderer:

```python
import re
import unittest

RAW_LOOPBACK = re.compile(r"https?://(?:127\.0\.0\.1|localhost|\[::1\])")
LEGACY = "fabric-dashboards://open?service="
RESOLVED = {"service": "example-agent.default",
            "open_link": "fabric-dashboards://service/example-agent.default?path=%2Fdashboard",
            "http_url": "http://127.0.0.1:47195/dashboard"}


def render(resolved, host_state):  # replace with the project's completion/notification renderer
    raise NotImplementedError


class RenderedDashboardLinks(unittest.TestCase):
    def test_rendered_output_has_no_raw_loopback_or_legacy_link(self):
        out = render(RESOLVED, host_state="available")
        self.assertIn(RESOLVED["open_link"], out)
        self.assertIsNone(RAW_LOOPBACK.search(out), out)
        self.assertNotIn(LEGACY, out)
```

## Degradation

- Claude Code, Codex and other hosts use this same procedure; no hook or plugin-only
  path is required. Skills must be activated/loaded; install does not intercept every answer.
- MCP absent: report unresolved host capability once, use the project's approved
  resolver/CLI if available. Do not write machine or agent MCP config automatically.
- Python absent: perform the comparisons above manually, including the gate's own rules (a
  path with a `.` or `..` segment, an encoded or backslash separator, or a query or fragment
  name or value that reads as a credential, such as `code`, `key`, `auth` or `api_key`, is
  refused); mark the executable gate NOT_RUN. Do not label the output mechanically validated.

Syntax is owned by Fabric Dashboards and `@passioncode-ai/fabric-service-host`:
[ADR-0005](https://github.com/passioncode-ai/fabric-dashboards/blob/51a7a80acf42781d7bec304cc87c655d48cc309b/docs/adr/0005-service-links.md).
The gate accepts only the service form, `fabric-dashboards://service/SERVICE_ID.INSTANCE`
with at most one `path`; since 0.51.0 it refuses the legacy `open?service=` form, as contract
DEC-0123 (PL-1, checker rule `FAC-SEM-143`) and its vectors do. A host that still returns the
legacy form fails the gate: report it as an installed host that did not open the page. The gate
does not generate links or redefine the Fabric wire contract.
