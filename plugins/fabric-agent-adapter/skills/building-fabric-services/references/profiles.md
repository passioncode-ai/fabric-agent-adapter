# Runner and model profiles (DEC-0046)

Which coding agent runs a job (the **runner**) and which models it may use (the **model profile**) are chosen in
Fabric, not in the service. The service resolves them in the contract's order, keeps to the project's model classes,
says what applies in its well-known document, and checks in its doctor that the runner and the model are usable.
Contract: `docs/specification/runners.md` §"Runner and model profiles" and `src/profile-rules.ts` at the pin.
Python: [`scripts/fabric_profiles.py`](../scripts/fabric_profiles.py); Node:
[`scripts/fabric-profiles.mjs`](../scripts/fabric-profiles.mjs). Both answer the contract's own vectors.

## Contents

- Resolving the model profile
- Checking the documents
- A lane that reads user content
- Declaring and showing what applies
- The doctor
- Runner routes
- Usage by route

## Resolving the model profile

```python
import fabric_profiles as fp
resolution = fp.resolve_model_profile(catalogue=catalogue, profiles=estate_and_agent_profiles,
                                      choices={"request": asked, "agent": own_default, "binding": bound, "estate": estate_default},
                                      policy=project_spend_policy)
```

The first level that names a profile wins: **request, agent, binding or project, estate default**. The project's
`modelClasses` narrow the profile's models (a model stays only if every class the catalogue gives it is allowed) and
never choose one. `open-vendor` is descriptive (DEC-0083): it is never checked against the policy, and a model whose
only class is `open-vendor` does not stay. An empty result is `{"refused": "model-classes-empty", "policy": {id, revision}}`: refuse the launch
and name the policy; never fall back to a model outside it. No level at all is `no-profile`; an id nobody offers is
`unknown-profile`.

## Checking the documents

`profile_problems(kind, doc)` / `profileProblems(kind, doc)` returns the contract's findings for a `model-catalogue`
(a model catalogued once; a provider never both ordered and ignored, a base slug covering its variants), a
`model-profiles` set (an id once), a `runner-profile` (a subscription only in its vendor's runner: Claude in Claude
Code, Kimi in Kimi Code, ChatGPT in Codex; a key route's allow-list is its own model profile; a key named by reference,
never by value) and a recorded `profile-resolution` (it equals the order's answer). Every rule compares as the contract
does: `===` (`1` and `true` differ, `null` is not absent) and its `jsonEqual` for a recorded resolution, where NaN
equals nothing. It never raises on hostile JSON: a value whose own `toString` member is data is shown as its JSON.

## A lane that reads user content

A model profile names what the lane it serves reads (DEC-0083, `reads`): `user-content`: what a member, a client or
the public sends (messages, questions, images, reviews, screenshots, voice); `operator`: only what the estate's own
operator or its agents write; `web`: pages fetched from the open web. Absent is "not declared", which stays valid.

A profile that reads `user-content` has an **open-vendor route** (FAC-SEM-112): with `fallback: none` (or any value the
contract does not name) its first model is `open-vendor` in the catalogue; with `between-turns` at least one of its
models is. Closed vendors refuse the content such a lane exists to handle, so a closed route alone skips the worst of
it. Which models are `open-vendor` is the catalogue writer's fact; the service never keeps a vendor list of its own,
and a model the catalogue does not hold counts as closed.

- `profile_problems("profile-resolution", doc)` / `profileProblems(...)` answer FAC-SEM-112 beside FAC-SEM-060, on each
  profile (`/profiles/<i>/models`) and on the resolution's outcome: when the resolved profile's own route is open but the
  models the project's policy leaves are all closed, the finding is at `/resolved/models` and names the policy.
- `closed_user_content_route(profile, catalogue)` / `closedUserContentRoute(profile, catalogue)` name the models that
  would run on such a lane when none is open-vendor, or `None`/`undefined` when the route holds.
- On such a lane a content refusal, or an empty answer to a non-empty request, is a **failed turn**: under
  `between-turns` the runner moves to the next model; it never counts that answer as done.
- `operator` and `web` carry no model rule in this revision; they let a lane say that it reads no user content.

## Declaring and showing what applies

```python
conf = fp.configuration(["runner", "model"], resolution, runner_profile)
well_known = fs.build_well_known(..., configuration=conf, summary=fp.configuration_summary(conf) + other_tiles)
```

`configuration` is read-only: a change is made in Fabric and reaches the service through its binding, never through
the well-known document. `configuration_summary` gives the **Runner** and **Model** tiles ("claude-code ·
subscription", "default · deepseek/deepseek-v4-pro") that the dashboard shows beside the others. The probe checks the
declaration (`configuration.declared`).

## The doctor

`runner_check(entry)` / `runnerCheck(entry)` takes one entry of Fabric's runner catalogue (`registry/runners.json`)
and answers whether the runner is installed, which version answers and whether it is signed in. It runs only a bare
catalogued binary found on `PATH`, only with the catalogued version argv (and `auth` argv), without a shell, within
the entry's timeout (at most 5 s); an entry outside these rules is refused and nothing runs. `model_usable(model,
catalogue, policy)` names why a model cannot be used here: not catalogued, a class the project does not allow, or
only `open-vendor`, which admits nothing: the same admission the resolution applies.

`probe` is the contract's closed probe result for that runner, the one Fabric's walk records (DEC-0026):
`not-installed` (no catalogued binary on `PATH`), `not-responding` (the version probe did not answer in its bound,
failed or did not match the catalogue's pattern, or the `auth` probe did not answer), `not-connected` (it answers but
the `auth` probe says signed out), or `None`/`null` when the runner can serve. The order is the walk's: installed,
then responding, then connected. `problems` still names every problem the doctor found.

## Runner routes

A project may pin a **runner route** (DEC-0026, DEC-0029, `runners.md` §"Runner routes"): the ordered terminal agents
that serve one capability, each with a session policy (`attach`, `spawn`), what happens when all are unavailable
(`exhausted`) and whether a conversation returns to a preferred runner (`recovery`). Fabric walks it; a service that
pins, records or shows routes checks them with `route_problems(kind, value)` / `routeProblems(kind, value)`, the
contract's `routeRules` finding for finding:

| `kind` | value | rules |
|---|---|---|
| `runner-route` | the route | one candidate per runner kind (FAC-SEM-028); a candidate can attach or spawn (029) |
| `route-bundle` | `{route, admissions, binding?, catalogue?}` | every candidate's provider revision admitted for the capability by id, revision and hash (030); the binding agrees (project, capability, local-runner, a candidate as provider, this route as `runnerRoute`) (032); every kind and named drive is in the runner catalogue (033) |
| `route-event` | `{route, event}` | the event names this route, project and capability; candidates by position; the probes cover every candidate above the selection in order (all for an exhausted walk, none for a sticky relaunch); attach, spawn, `no-held-session` and `spawn-failed` obey the session policy; `held` only under `exhausted: hold`; `preferred-available` only under `recovery: reprobe`, moving up (034) |

A probe result in an event is one of `PROBE_RESULTS`; a host never appends a runner the route does not name.

## Usage by route

`make_usage_receipt(..., route="subscription"|"key")` records how the call was paid: the operator's own login in its
vendor's runner, or an issued key. The usage report keeps the rows of one model on two routes apart.
