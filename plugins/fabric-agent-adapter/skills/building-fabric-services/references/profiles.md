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
- Declaring and showing what applies
- The doctor
- Usage by route

## Resolving the model profile

```python
import fabric_profiles as fp
resolution = fp.resolve_model_profile(catalogue=catalogue, profiles=estate_and_agent_profiles,
                                      choices={"request": asked, "agent": own_default, "binding": bound, "estate": estate_default},
                                      policy=project_spend_policy)
```

The first level that names a profile wins: **request, agent, binding or project, estate default**. The project's
`modelClasses` narrow the profile's models — a model stays only if every class the catalogue gives it is allowed — and
never choose one. An empty result is `{"refused": "model-classes-empty", "policy": {id, revision}}`: refuse the launch
and name the policy; never fall back to a model outside it. No level at all is `no-profile`; an id nobody offers is
`unknown-profile`.

## Checking the documents

`profile_problems(kind, doc)` / `profileProblems(kind, doc)` returns the contract's findings for a `model-catalogue`
(a model catalogued once; a provider never both ordered and ignored, a base slug covering its variants), a
`model-profiles` set (an id once), a `runner-profile` (a subscription only in its vendor's runner — Claude in Claude
Code, Kimi in Kimi Code, ChatGPT in Codex; a key route's allow-list is its own model profile; a key named by reference,
never by value) and a recorded `profile-resolution` (it equals the order's answer).

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
catalogue, policy)` names why a model cannot be used here: not catalogued, or a class the project does not allow.

## Usage by route

`make_usage_receipt(..., route="subscription"|"key")` records how the call was paid — the operator's own login in its
vendor's runner, or an issued key. The usage report keeps the rows of one model on two routes apart.
