# Dashboard links — producer and consumer rule

Read when an agent creates a dashboard, implements `<tool> dashboard`, or hands
an existing Fabric service dashboard to a person. This also applies to generated
agent instructions and completion messages. Headless agents need no dashboard;
API origins, external docs and OAuth links are not dashboard actions.

## Resolve, then hand over

1. Discover the target computer and exact registered `service.id.instance`.
   Never guess a key from a project name or port. `default` and `preview` differ.
2. Discover Fabric Dashboards tools by their descriptions; provider tool prefixes
   differ. Use `link` with service + path (including the page's query/fragment),
   or pass a known local service URL to it. For a root, `list_services.open_link`
   is also authoritative. Hand back **the returned `open_link` as the primary
   dashboard action**. Do not rebuild its URI or double-encode `path`.
3. Use `host_status`, where offered, to distinguish available, not_installed,
   unknown, incompatible and handler_mismatch. It is a read, not a GUI launch.
   With an older server lacking that tool, host readiness is unverified: use a
   compatible host resolver or report the limitation, not presumed absence.
4. A request for a link opens nothing. A request to open uses the host `open`
   tool/approved opener, which starts or focuses the existing Fabric Dashboards
   and reuses the service view. `fallback=never` forbids a browser; `if_absent`
   permits one only for confirmed absence. Discover schema support first: older
   `open` implementations may silently fall back on failure and are not strict.
5. An installed host that failed to open is **not absent**. Report the failure;
   do not silently launch HTTP in a browser, a second server, `npm run dev`, or
   another standalone dashboard. A stopped backend stays on its host status/Start
   surface; automatic wake-up follows the host's lifecycle grant and held-off state.
6. Preserve an unavailable/error result. `accepted_by_os` proves dispatch only,
   not page readiness, a successful login, or a completed job. Links carry no
   bearer tokens or login codes. The host handles dashboard authentication.

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
if_absent policy and the same device. `remote_open` instead contains `device_id`,
`service` and optional `path`, exactly matching the target and resolved page;
its acceptance does not authorize or deliver it. Enforce grants/dedup/expiry in
the transport. Unknown or failed host status produces no executable local action.
A separately labelled copyable link for diagnosis is not an open action.

Add this check to the generated project's dashboard completion/notification
renderer before delivery. A raw-HTTP primary action with an available host is the
negative fixture; a valid native action is the positive one. Keep diagnostics
separate. This gate checks structured actions, not arbitrary prose: a CLI invocation
or instructions alone do not prove all final answers from every agent are filtered.

## Degradation

- Claude Code, Codex and other hosts use this same procedure; no hook or plugin-only
  path is required. Skills must be activated/loaded; install does not intercept every answer.
- MCP absent: report unresolved host capability once, use the project's approved
  resolver/CLI if available. Do not write machine or agent MCP config automatically.
- Python absent: perform the comparisons above manually; mark the executable gate
  NOT_RUN. Do not label the output mechanically validated.

Syntax is owned by Fabric Dashboards and `@passioncode-ai/fabric-service-host`:
[ADR-0005](https://github.com/passioncode-ai/fabric-dashboards/blob/51a7a80acf42781d7bec304cc87c655d48cc309b/docs/adr/0005-service-links.md).
The gate accepts canonical links and the legacy `open?service=` form returned by
older hosts; it does not generate either dialect or redefine the Fabric wire contract.
