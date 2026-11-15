# Agent first: every function is an API and MCP capability

The operator's rule (2026-11-14): an agent is built for agents first. Every function it has, whatever a person can see
or change, is a capability on its agent surface from its first version: an MCP tool, served from the same API the
agent's own page or bot calls. A dashboard, a bot, a CLI or a report is a view over those capabilities, never the only
door to one. There is no function a person can reach and an agent cannot: not to view, not to edit.

## The rules

- **AS-1, the capability comes first.** Name each function as a capability (`domain.action`) with typed input and
  output before its page, command or report exists. The page calls the API the agent calls: one code path, one set of
  checks, one audit record.
- **AS-2, read parity.** Everything a person can see (a list, a record, a status, a number, a chart's series, a log, a
  history, a setting, an export, a preview with its diff and hash) has a read capability that answers the same data
  with the same filters and paging, as structured data. An agent is never told to open the page, and never scrapes it.
- **AS-3, write parity.** Every change a person can make (a button, a form, an inline edit, a setting, an upload, a
  bulk action) has a tool with the same effect, the same checks, the same audit record and an idempotency key: the
  contract's DEC-0121 AP-1, declared under `extensions/actions/0.1` with its gate (`none`, `relayed` or `human`;
  building-fabric-services, the interop reference's *Actions*).
- **AS-4, only a human step stays the person's, and the agent still sees it.** A sign-in, a consent, a payment, a typed
  secret, spend above a limit or a passkey (AP-4): the tool answers `human-step-required` with the direct link to that
  step, and the step's state stays readable by the agent.
- **AS-5, parity never widens access.** A read or a write answers under the caller's grant and context exactly as the
  page answers under the person's session: the same scopes, the same tenant boundary, the same redaction of secrets.
- **AS-6, checked before every release.** The repository keeps an inventory of every function a person reaches (each
  page route and view, button, form, export, bot command, CLI verb, scheduled report or mail) beside the capability
  that serves it, in `docs/agent-surface.md` or a section of the README, changed with the surface. A row with no
  capability is built before the release, never filed for later.

## Checking an existing agent

1. List the person's surfaces: the dashboard's routes and controls, the bot's commands, the CLI's verbs, the reports
   and mails it sends.
2. For each, find the capability that serves it: `tools/list`, the well-known `surfaces.mcp.capabilities`, the API
   route the page calls.
3. A view with no read capability gets a read tool over the query the page already runs. A control with no tool gets
   its tool and its action declaration with a gate.
4. Run the probe (`check_service.py`): `dashboard.agent-surface` fails a dashboard with no agent surface, one whose
   MCP surface serves no tool, or an empty declared `surfaces.mcp.capabilities`, and `interop.action-tools` fails a declared action whose tool is not served.

## What the contract says today

DEC-0121 AP-1 makes write parity normative for a service's actions. Read parity and the design order are the
operator's rule, carried by these skills, and since the contract's DEC-0169 (row CT-311, `main` `6adeecf3`) its
normative text too: RP-1 (an agent reads what a person sees, with the same data, filters and paging), RP-2 (a function
is built for the agent first) and RP-3 (`FAC-SEM-176`: a dashboard needs `surfaces.mcp` or `surfaces.a2a`, and a
present `surfaces.mcp.capabilities` is never empty), which the probe's `dashboard.agent-surface` reads as the contract
does (FAA-332, FAA-335). It binds a service at its next pin past that commit.
