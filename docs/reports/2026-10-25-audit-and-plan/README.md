---
report:
  id: fabric-agent-adapter/2026-10-25-audit-and-plan
  title: "Adapter state at 0.49.2: cleanup, every open item in one list, and the plan for the first organization"
  kind: audit
  project: fabric-agent-adapter
  domains: [backlog, board, branches, contract-pin, release, rollout]
  as_of: 2026-10-25
  status: active
  valid_until: 2026-11-25
  summary: >-
    The operator asked to check what other sessions did, the board, the debts, worktrees and
    branches, delete what is finished, gather what is open in one place and split it into hotfixes,
    the product plan for the first organization, later plans and backlog. main is 0.49.2, equal to
    the tag and npm, nightly validate green; nothing was unmerged. Cleaned: 34 merged remote
    branches, one abandoned clone, one expired lease. Open: two board requests addressed to the
    adapter (DEC-0121 actions, the Dashboards-only rule), three findings on the dashboard kit and
    the remote registration, a contract 71 commits past the pin, seventeen contract rows whose
    adapter part is done but not reported. Rows FAA-117 to FAA-124.
---

# Adapter state at 0.49.2: audit and plan

**Question.** What did the sessions before this one leave, what is finished and can go, what is open, and in what
order the open work should be done so the adapter is ready for the first organization.

## 1. What was read

| Source | How | What it said |
|---|---|---|
| Repository | `git fetch --prune`, `git worktree list`, `git for-each-ref`, `gh pr list --state open`, `gh issue list --state open` | `main` at `4902d2f`; one worktree; 34 remote branches, every one an ancestor of `origin/main`; 0 open PRs; 0 open issues |
| Other checkouts | every `~/DATA/*` and `~/DATA/_worktrees/*` whose origin is this repository | `~/DATA/fabric-agent-adapter-review-access`: branch `codex/contract-adoption-review-20261004` at `2d117ea`, 134 staged deletions (the whole tree), no stash, no unpushed commit |
| Release | `gh release list`, `npm view @passioncode-ai/fabric-agent-adapter version`, `package.json` | `v0.49.2` latest, npm `0.49.2`, `package.json` `0.49.2` |
| CI | `gh run list --workflow validate.yml` | nightly run [40144441972](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/40144441972) on `4902d2f`: success |
| Backlog | [backlog.md](../../backlog.md), 119 rows before this cut | 15 rows not done (section 3) |
| Board | `com.status`, `com.list {unread: true}` | 31 unread, read in full and marked; 2 requests addressed here, `queued` |
| Fabric tasks | `fabric_work_list`, `fabric_tasks_list` | 9 tasks in `review` (finished, the operator closes them); 1 claim of an ended session, lapsed |
| Contract | `git log 2f020a6..origin/main` in fabric-agent-contract, its tags and `docs/backlog.md` | 71 commits and 3 releases past the pin (`v0.1.0+2026-10-24`, `+2026-10-24.2`, `+2026-10-25`), DEC-0112 to DEC-0121; 18 open CT rows name the adapter |
| Roadmap | fabric-workspace `knowledge/roadmap.md` at `e5eae7f5` | the first organization is the RM-28 pilot (two organizations in Vesta at `org.passioncode.ai`); the adapter's part there is packing and sharing (FAA-27, done in 0.31.0) and later publishing (FAA-28) |
| Leases | `agent_sync.py residue`, `git ls-remote origin 'refs/agent-sync/*'` | one foreign lease `AUTO-PROJECT-REGISTRATION`, expired 7 days 18 hours |

**Not read.** The board history before today's unread messages was not paged through (about 5 pages of 100 per call);
the session of 2026-10-24 read and answered 225 messages ([handoff](../../handoffs/2026-10-24-session-cookie-0.49.2.md)),
so only what arrived after it is covered here. No test was run: this cut changes no code.

## 2. Cleaned in this run

| What | Proof it was finished | Done |
|---|---|---|
| 34 remote branches (`agent/faa-*`, `backlog/faa-*`) | each head an ancestor of `origin/main` (`git merge-base --is-ancestor`) | deleted; `git ls-remote origin 'refs/heads/*'` lists only `main` |
| Clone `~/DATA/fabric-agent-adapter-review-access` | its HEAD `2d117ea` is an ancestor of `5f88fb4`, and every file `5f88fb4` touched equals `origin/main` (`git diff --quiet`); the tree held only staged deletions and a 215-byte local settings file | removed |
| Lease `refs/agent-sync/leases/AUTO-PROJECT-REGISTRATION` | expired 2026-10-17 (TTL 2700 s), no holder | deleted on `origin` |
| 31 unread board messages | read in full | marked read (`com.read_ack`, 31 marked) |

**Left for the operator** (a human gate: an agent cannot move a task to `done` in Fabric): the 9 tasks in `review`
(0.36.0, the audit of 2026-10-22, 0.41.0, 0.47.0, 0.47.1, 0.48.0, 0.48.1, 0.48.2, the sweep of 2026-10-24). Each one's
release is tagged and on npm; they can be closed.

## 3. Open work, in one list

### P0: hotfixes (small, unblocked, a patch release)

| Row | What | Why now |
|---|---|---|
| FAA-119 | the dashboard kit's `fabric-button.js`: U+2014 at line 288, English-only labels at 163, 167, 204, 215 | two services cannot take the kit (prowl-research B-088, telegram-gateway-agent TG-11); vendored copies cannot be patched |
| FAA-120 | `registerRemote` / `register_remote` take `source` | remote services register with `repository: null`; Prowl Agent carries a workaround |

### P1: the first organization (RM-28 pilot and what services need to pin)

| Row | What | Blocks |
|---|---|---|
| FAA-117 | repin to `v0.1.0+2026-10-25` and adopt DEC-0121 (actions and relayed operator decisions) | every service with a dashboard (CT-127), Fabric's hub (CT-125); deadline 2026-11-07 |
| FAA-118 | the Dashboards-only rule in the three skills, the templates and the probe | the operator's rule of 2026-10-24; deadline 2026-10-31 |
| FAA-121 | tell the contract owner which seventeen CT rows have the adapter's part done (sent, thread `c06f2991`) | the contract board shows the adapter as late where it is not |
| FAA-87 | npm trusted publishing, the publish token removed | a human gate: the operator's `npm login` on npmjs.com |

### P2: next, on demand

| Row | What | Waits on |
|---|---|---|
| FAA-116 | guidance for agents that answer people (tiers, tier-5 diagnosis, learning cycle) | agent-stack's `agent-evals` reference; the shape is now agreed on the board (`cause`, flat `cited` and `coverage`) |
| FAA-122 | feed events nest two levels at most; say so and name the path in the refusal | nothing |
| FAA-103, FAA-106 | the call queue (DEC-0104), relay calls (DEC-0106) | an agent that asks for them |
| FAA-98 | non-ASCII hosts in the Python connections reader | by decision D5 of 0.44.0, non-blocking |

### Later: the organization's distribution path

| Row | What | Waits on |
|---|---|---|
| FAA-28 | `publish --to me|person|org` | `estate-record/1`, `org-authority/1`, share grants, the first organization server |
| FAA-63 | upload a signed package to an organization cloud's import API | the import API's schema from its owner |
| FAA-44 | a private catalog of commercial agents (RM-30) | the catalog's shape |
| FAA-26 | `new "<sentence>"` and `test` (target architecture v4, stage 1) | the remaining stage-1 decisions in the row |
| FAA-29 | DEC-0039 and DEC-0030 amendments (ES256, `run`, DPoP) | the contract amendments |
| FAA-27 | the rest of `pack` beyond 0.31.0 | see the row |

### Backlog: features

| Row | What |
|---|---|
| FAA-10 | A2A v1.0 in the kits (RM-17), waits on `surfaces.a2a` in the contract |
| FAA-66 | a data or analytics agent recipe |
| FAA-67 | a Telegram connector, after `telegram-dev` decides whether it belongs here |
| FAA-64 | review of 0.39.0: fixes done in 0.39.1; the row's remaining text to re-read and close |

## 4. Plan for the first organization

1. **0.49.3, hotfixes:** FAA-119 and FAA-120 together, kit release with them; reply on threads `288afbce`, `a0929fba`,
   `44ff5ea0`.
2. **FAA-121** the same day: one board message to fabric-agent-contract with a receipt per CT row.
3. **0.50.0, the contract release:** FAA-117 (repin and DEC-0121) with FAA-118 (Dashboards-only rule); this unblocks
   CT-125 and CT-127, so every service with a dashboard can pin `v0.1.0+2026-10-25`. Reply on `92c6f277` and `38b5b8a8`.
4. **Pilot check:** with 0.50.0 installed, one personal agent packed, signed, shared into both Vesta organizations
   (`org:<id>` placement, DEC-0082) and its dashboard opened from Fabric Dashboards; what fails becomes a row.
5. **Then** FAA-116 when its reference lands, FAA-28 and FAA-63 when their owners publish.

## 5. Questions for the operator, and the answers (2026-10-25)

Asked and answered in the session; the answer follows each question.

1. Which organization is "the first"? **The RM-28 pilot pair** (PassionCode.ai and Appvillis in Vesta).
2. "One new finished project that we integrate"? **An estate release:** the adapter, the contract, Fabric's hub
   (CT-125) and the services with a dashboard ship in order, coordinated by the adapter (FAA-124; proposed on the board,
   thread `0144d916`).
3. The dashboard kit's labels? **Data attributes and built-in Russian** chosen by the page's `lang`, English by default
   (FAA-119); the strings go through Copylot.
4. FAA-87 needs `npm login` on npmjs.com: not answered; it stays a human gate.
5. A2A? **The adapter drafts `surfaces.a2a` and proposes it to the contract** (FAA-123).

The plan in section 4 stands, with FAA-124 as its frame and FAA-123 after 0.50.0. FAA-121's message went to the
contract's owner (thread `c06f2991`): it covers 17 rows, not 14 (CT-03, CT-81 and CT-82 were found done too).
