# The estate record: what the operator's machines are, signed by their passkey (DEC-0055)

Fabric Agent Contract DEC-0055, `docs/specification/estate-record.md`, schema `schemas/estate-record.schema.json`,
rules `FAC-SEM-072…076`, with contexts (DEC-0082, `docs/specification/contexts.md`, `FAC-SEM-110`, `FAC-SEM-111`) and a
partner's scoped publisher key (DEC-0090, `docs/specification/partner-channel.md`, `FAC-SEM-122`) and each machine's
profile (DEC-0106, `docs/specification/machine-calls.md`, `FAC-SEM-134`), and the revocation delta's head a
revision vouches for (DEC-0107, `deltaAnchor`, `FAC-SEM-137`).
One revision of one person's estate lists:
- the passkeys that sign it;
- the machines, with their device keys, a certificate of each machine's hub key and, optionally, a profile;
- the packages placed on each machine, each in a context: the person's own, or an organization's;
- where each secret slot is filled from (by reference only);
- share grants and revocations.

A revision names its parent's digest and is signed by a passkey assertion (WebAuthn Level 3) over a challenge
derived from its own digest. Python: [`scripts/fabric_estate.py`](../scripts/fabric_estate.py). Node:
[`scripts/fabric-estate.mjs`](../scripts/fabric-estate.mjs). Both answer the contract's own vectors. Since 0.52.0 the
record's rules live in [`fabric_estate_rules.py`](../scripts/fabric_estate_rules.py) and
[`fabric-estate-rules.mjs`](../scripts/fabric-estate-rules.mjs); the estate modules re-export them, and
`fabric_kit.py install` copies both.

## Contents

- Applying a revision
- Trusting a delegation key
- Contexts: one agent for you and for an organization
- One instance per context: the helper
- Machine profiles: full, member, view
- The delta anchor
- The estate ceremonies
- Share grants into an organization
- Checking a record you produce
- What the kit does not do

## Applying a revision

A machine applies a revision only when it is valid against `estate-record.schema.json` **and** the verifier accepts
it. The verifier does not check the schema.

```python
verdict = fe.verify_estate_record(record, at=datetime.now(timezone.utc), parent=current)   # revision 2 and later
verdict = fe.verify_estate_record(record, at=now, authorities=pinned_passkeys)             # revision 1
if verdict["ok"]:
    current = record          # verdict: digest, revision, signedBy, signCount
```

```js
const verdict = verifyEstateRecord(record, { at: new Date(), parent: current });
```

It checks, in the order of the ER table:
1. **The clock.** An unreadable one is `no-clock`, and it comes first.
2. **The shape.**
3. **The digest.** SHA-256 over the RFC 8785 form, without `digest` and `signature`.
4. **The chain to the parent.** Same estate, the next revision number, the parent's digest, never issued before the
   parent, and no revocation dropped.
5. **The signer.** The signing passkey must be among the trusted ones and not revoked by the parent. A revision may
   revoke its own signer: that is rotation.
6. **The assertion.** The passkey is a signing credential (DEC-0063): an RP ID that is not a dedicated signing RP,
   `sign.<domain>` in lower case, is `wrong-rp` before the assertion is read, and an origin outside the RP ID is not
   pinned, so a ceremony that ran there is `wrong-origin`.
   - Client data: type, challenge, origin, no cross-origin use.
   - The RP ID hash, and the user-presence and user-verification flags.
   - The signature: ES256 or EdDSA, under a key validated first (a valid P-256 point; an Ed25519 key of full order).
7. **The window.** At most 30 days. A revision may be issued up to 60 s ahead of the verifier's clock (DEC-0066,
   `CLOCK_SKEW_SECONDS`); earlier than that it is `not-yet-valid`.
8. **The record's own rules.** A violation is `rule-violation` with its `codes`, `FAC-SEM-072…076`, `FAC-SEM-110`,
   `FAC-SEM-111`, `FAC-SEM-122`, `FAC-SEM-134` and `FAC-SEM-092`, and against the parent `FAC-SEM-114` and
   `FAC-SEM-137`
   (each passkey the record lists is a signing credential, its origins within its RP ID).

Dates are strict RFC 3339: a `T`, an offset, and a day that exists. `:60` and a space are refused. Passkey JWK `x`
and `y` must be canonical base64url. The Python kit verifies ES256 in pure Python (P-256, strict DER), and the Node
kit through `node:crypto`.

## Trusting a delegation key

A delegation verifier that reads the estate record trusts a token's `kid` only while the revision it reads certifies
it (DL-14, contract DEC-0060): exactly one machine's `hubKey` has that `kid` and the published key's `x`, the clock is
inside the revision's window (from 60 s before `issuedAt`, DEC-0066, to `validUntil`), and neither the revision nor the
revocation delta's entries applied since it revoke `hub-key <kid>` or `machine <id>`. It is checked right after the
signature (DL-13 row 4a). Give the gate the current verified revision, or a function that returns it, the highest
revision the machine applied, and the delta's revocations:

```python
gate = fd.delegation_gate(audience=..., jwks=keys, issuer=..., effects=..., estate=lambda: current,
                          estate_applied={"revision": applied_number, "digest": applied_digest},
                          estate_revocations=lambda: delta_entries)
```

**Which key: the instance's context** (DL-14a, contract DEC-0128). The personal context's tokens are signed by a
machine's `hubKey`; an organization's by that context's own key in the same machine's `contextHubKeys`
(`{context: "org:<orgId>", key}`), under the context issuer its pin in `organizations` names (`iss`,
`urn:fabric:context:<opaque>`). An instance that serves an organization passes its context and that issuer:

```python
gate = fd.delegation_gate(audience=..., jwks=keys, issuer=pin["iss"], effects=..., estate=lambda: current,
                          estate_context="org:acme-rehearsal")     # the context fabric_context started it for
```

The `kid` is then certified only when exactly one machine lists it for that context with the published key and the
revision pins the organization; omitted or `personal`, the personal `hubKey` is read. A context key never verifies a
personal token, the personal key never an organization's, and a context that is neither (`Org:x`, a trailing space, a
number, `null`) certifies nothing: a misconfigured callee fails closed with `kid-not-certified`.

- **The token's fault** (no such certification, another key under that `kid`, a `kid` on two machines, a revoked hub
  key or machine) is `unauthenticated` (for an approval, `approval-invalid`) with detail `kid-not-certified`.
- **The trust source's fault** is `issuer-unavailable`: `estate-unreadable` (a source that throws or answers nothing
  readable, a revision without a number or digest, a window of zero or over 30 days, dates read strictly, `machines` or
  `revocations` not arrays), `estate-outside-window`, `estate-rolled-back` (lower than the applied revision) and
  `estate-forked` (the applied number with another digest). A caller cannot cure these by minting again.
- An unreadable clock (not a finite number of seconds a `Date` can hold) is refused `unknown-state` `no-clock`
  before row 1, in every verifier.
- Only an absent `estate` skips the check: an option left out. An explicit `null` (Python `None`) is an unreadable
  source in both kits, and so is `applied: null`; an omitted `applied` means no revision applied yet (FAA-78).
- **What you pass in.** Pass only a revision that `verify_estate_record` accepted and whose number is not lower than
  the highest the machine applied; a higher one only when you verified its chain from the applied revision.
- `hub_key_certified(record, kid, x, at, applied, extra_revocations, context)` /
  `hubKeyCertified(record, kid, x, at, applied, {extraRevocations, context})` answers the question on its own:
  `{certified: true, machine, revision}` or `{certified: false, fault, detail}`. Both kits are held to the contract's
  `fixtures/vectors/hub-key.json` (`test/fixtures/contract/hub-key-vectors.json`), and to its `contextCases` and
  `contextVerifier`, generated with the contract's `hubKeyCertified` and `verifyDelegation` over its
  `estate-record-organizations.json`.

## Contexts: one agent for you and for an organization

A placement and a secret placement carry a `context` (DEC-0082): `personal`, or `org:<orgId>` with an organization id
of `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`. Absent is `personal`; `null` is not absent. A context is compared as written:
`Personal`, `ORG:x` or a trailing newline names no context. `parse_context(value)` / `parseContext(value)` answer
`{kind: "personal"}`, `{kind: "org", org}` or nothing.

- **One agent, once per context.** A machine may place the same `agentRef` for the person and for each organization;
  placements are keyed by agent and context (FAC-SEM-074), and a secret slot by agent, slot and context (FAC-SEM-075).
  A secret fills a slot of an agent placed on that machine in the secret's own context.
- **An organization's instance runs under a share grant** (FAC-SEM-111). Its placement names, in `grant`, a share grant
  of the record whose `context` is the placement's, as written, and that the record does not revoke. A personal
  placement names no grant. A context that is not `org:<orgId>` matches no grant, so it fails closed.
- **An organization's slot is filled from its own machine.** An envelope names no context, so a secret placed in an
  organization's context has `from` equal to the machine it sits on (FAC-SEM-075).
- **A share grant is never personal** (FAC-SEM-110). A grant to a principal outside the estate (`principalKind:
  external`) is used in that principal's organization; `context: "personal"` on it is a finding, and an absent one
  means not stated. `grant_context_findings(grant, at)` / `grantContextFindings(grant, at)` check one grant on its own.
- **A partner's publisher key is trusted only where its scope says** (DEC-0090, FAC-SEM-122). `publisherScopes[]`
  names the keys that are a partner's (`kid`, `partner: org:<id>`, `contexts`); a placement under such a key is in one
  of the organization contexts listed, never `personal` or another organization. A key is scoped once, and only a key
  `publisherKeys` pins. A key no scope names keeps DEC-0051's meaning, trusted in any context.
- **Update a copied kit before a revision carries `publisherScopes`.** A service runs the copy of the kit it was built
  with; a copy older than 0.39.0 does not read `publisherScopes`, so it trusts a partner's key in every context and
  finds no rule broken. A service that applies the estate record updates its copy first:
  `fabric_kit.py install <dir> --module fabric_estate` (or `--lang node --module fabric-estate`). Since 0.40.0 the
  estate reader imports the kit's core modules, so the one file alone no longer loads ([kit modules](kit-modules.md)).
- **The organizations the person admitted** (DEC-0127, DEC-0128). `organizations[]` pins each organization once by
  its context (`org`), with its server (`issuer`), its context issuer (`iss`) and the root that signs its key sets
  (`root`). FAC-SEM-147: an organization pinned twice, one `iss` used by two pins, an `iss` whose opaque part contains
  the estate id (eight characters or more, any case), and a root of small order are findings.
- **A hub key per organization context** (DEC-0128). `machines[].contextHubKeys[]` (`{context, key}`) certifies the
  key that signs that context's tokens. FAC-SEM-073: each context once on a machine, a context the record pins, every
  `kid` and public key unique across all the record's hub keys (personal and per context), no key of small order, and
  only on the machine that holds the personal `hubKey`; FAC-SEM-134: only a `full` machine; FAC-SEM-076: revoking
  `hub-key <kid>` while listing it; FAC-SEM-114: a context key dropped, replaced, moved to another context or left on a
  removed machine is revoked in the same revision.
- **An organization instance whose context the record does not pin** (decision D5 of 0.52.0). `fabric_context` starts
  it as before: it checks the placement and its share grant, not the pin. Every token presented to it in that context
  is then refused `kid-not-certified`, since `hub_key_certified` reads a context's keys only while the record pins it.
  The start is not refused because the contract lets Fabric write `organizations` only once every reader of the record
  is pinned at or after DEC-0127, so today's records pin none; a refusal now would stop every organization instance.
- **A tokenless call runs in the instance's context** (DEC-0137). A T0 or T1 caller presents no token (DL-26), so the
  call is in the context of the instance it reached: the personal instance for the person, an organization's instance
  for that organization ([delegation](delegation.md), the family).

Every rule is total on hostile JSON, as the contract's are: an `instancePath` names an item by its index as written (a
non-object before it does not shift it), and a value whose own `toString` member is data is shown as its JSON. Both kits
answer the contract's contexts fixtures and variants of them (`test/fixtures/contract/estate-vectors.json`).

## One instance per context: the helper

A service that runs for the person and for an organization runs once per context on a machine (contract
`contexts.md`, *One instance per context on a machine*; FAA-125). `fabric_context` / `fabric-context.mjs` turns the
context it is started for into that context's one instance. It is not in the facade: install it with
`fabric_kit.py install <dir> --module fabric_context` (Node: `--lang node --module fabric-context`), so a service that
does not run per context keeps the estate reader out of its closure.

```python
import fabric_context as fc
info, lock = fc.hold_context_instance("example-agent", "org:acme-rehearsal", record=applied_revision,
                                      machine_id="machine-a", agent_ref="urn:agent:example-agent")
serve(data=info["dirs"]["data"], instance=info["instance"])        # org-acme-rehearsal; lock held until exit
```

```js
import { holdContextInstance } from './fabric-context.mjs';
const { dirs, instance, lock } = await holdContextInstance('example-agent', 'org:acme-rehearsal', { record, machineId, agentRef });
```

- **The instance name.** `personal` is `default` (`personal_instance` / `personalInstance`), so an existing install
  keeps its descriptor `<id>.default.json`, its folders and its lock. `org:<orgId>` is `org-<orgId>` when the id is
  lower-case words joined by single hyphens, at most 28 characters, and does not end in a hyphen and 10 hex digits
  (`org:acme-rehearsal` is `org-acme-rehearsal`); any other id is `org-<slug>-<first 10 hex digits of sha256(orgId)>`
  (`org:Acme` is `org-acme-37036cd8f9`). `context_instance_name` / `contextInstanceName` answer it alone.
- **Its folders.** `instance_dirs(id, instance)` / `instanceDirs(id, instance, platform)`: `default` is
  `service_dirs`; any other is a sibling named as its descriptor, `<id>.<instance>` (on macOS
  `~/Library/Application Support/<id>.<instance>`, `~/Library/Logs/<id>.<instance>`, `~/Library/Caches/<id>.<instance>`),
  never inside the personal tree. `launchd_uninstall(..., purge=True, service_id=..., instance=...)` /
  `launchdUninstall(..., {purge, serviceId, instance})` purge only that instance's folders.
- **What it checks, before anything is created.** `context_instance` / `contextInstance` is pure and answers
  `{context, kind, org?, instance, key, dirs, descriptorPath, grant?}`, never the record. An organization's instance
  needs the estate record revision this machine applied (verified with `verify_estate_record`; the helper verifies no
  signature), the machine id and the agentRef, all passed by whoever installed the instance. It finds this machine's
  placement of that agent in that context, as written (FAC-SEM-074), runs FAC-SEM-111 on it
  (`placement_grant_findings` / `placementGrantFindings`), and refuses outside the grant's window (`startsAt` <= now <
  `expiresAt`); `instance_share_grant` / `instanceShareGrant` answers the three alone. A personal instance needs no
  record; given one, a personal placement that names a grant is refused.
- **What it holds.** `hold_context_instance` / `holdContextInstance` then takes the instance lock on the instance's
  data folder (`hold_single_instance`: a second copy for the same context exits 75, a supervised one waits first),
  then the marker `<data>/fabric-context.json` (`{service, instance, context}`, 0600): absent, it is written; equal,
  kept; another context or instance, or unreadable, releases the lock and refuses. The folder never changes context.

A refusal is one sentence on stderr naming the code and the context, never a record or grant value, and exit 78
(`EXIT_CONTEXT_REFUSED`, EX_CONFIG; 75 stays "already running"). `ContextRefused` carries the code:

| Code | When |
|---|---|
| `context-invalid` | the context is neither `personal` nor `org:<orgId>` as written (`Personal`, `ORG:x`) |
| `record-required` | an organization's context with no record, machine id or agentRef (fail closed) |
| `placement-missing` | the record places no such agent on this machine in that context |
| `grant-refused` | the placement names no share grant of the record for that context, or a revoked one (FAC-SEM-111); a personal placement names one |
| `grant-window` | now is before the grant's `startsAt`, at or after its `expiresAt`, or an instant cannot be read |
| `context-mismatch` | the data folder's `fabric-context.json` names another context or instance, or cannot be read |

Under launchd's `KeepAlive` a refused instance is started again every 10 s until the node's next revision removes it;
a revoked grant stops calls at once at the hub and the meter (DL-24), not here: the helper reads revisions only.
Tests: `test/test_fabric_context.py`, `test/fabric-context.test.mjs` over `test/fixtures/kit-context-cases.json`.

## Machine profiles: full, member, view

DEC-0106 gives a machine an optional `profile`. It says what the machine may be when other machines of the estate call
it over the relay.

- **`full`**, the default. A record omits it: a machine with no `profile` is `full`. Only a `full` machine carries a
  `hubKey`.
- **`member`** takes calls from the estate's machines and holds only the secret slots the record places on it. It has
  no `hubKey`.
- **`view`** only reads. It has no `hubKey`, no placement and no secret placement, and no secret placement names it as
  `from`.

`FAC-SEM-134` checks all of it: an unknown value, a hub key on a `member` or `view` machine, and a `view` machine that
places, holds or fills a secret. A revision that breaks it is `rule-violation`. A profile changes only by a revision
the passkey signs.

`machine_profile(record, machine_id)` / `machineProfile(record, machineId)` answers a machine's profile: `full` for a
machine listed once with no `profile`, its value when it is one of the three, and `None` / `undefined` otherwise (not
listed, listed twice, an unreadable record or id, an unknown value). It never raises. Both kits answer the contract's
own profile vectors (`fixtures/vectors/machine-call.json`) and hostile inputs (`test/fixtures/contract/estate-vectors.json`).

- **Update a copied kit before a record carries `profile`.** A copy older than 0.47.0 refuses a record with `profile`
  only when it checks the schema; its rules find nothing broken on a `view` machine that places agents. Fabric writes
  `profile` only once every reader of its records is pinned at or after DEC-0106, the kits included:
  `fabric_kit.py install <dir> --module fabric_estate` (or `--lang node --module fabric-estate`).
- **The kit does not take calls between machines.** Placing a relay caller (`relayCallerTier`), judging a call by
  profile (`machineCallVerdict`) and sealing it (`fabric-agent-call/1`, HPKE) are a relay node's duties; no kit-built
  service is one yet (FAA-106). A delegation verifier still names the refusal: `profile-forbids` is a DL-19 code
  ([delegation](delegation.md)).

## The delta anchor

DEC-0107 lets a revision name the revocation delta's head it vouches for: `deltaAnchor {sequence, sha256}`. Every
revocation of the delta's entries up to it is in the record. `FAC-SEM-137` keeps it from moving back: once a parent
anchors the delta, its next revision anchors it too, at the parent's sequence or later, with the parent's hash at the
same sequence. `delta_anchor_of(record)` / `deltaAnchorOf(record)` answers the anchor, or `None` / `undefined` when the
record names none or one of another shape. Applying the delta against the anchor (`anchorDelta`) is a machine's duty
when it applies revisions; the kit verifies the revision and does not hold a delta. Fabric writes `deltaAnchor` only
once every reader is pinned at or after DEC-0107: update a copied kit first, as for `profile`.

## The estate ceremonies

Contract DEC-0084: create a network, add a machine nearby (a six-digit comparison code) or headless (an enroll token),
remove a machine, replace a machine's key. Fabric runs the ceremonies and signs every revision with the person's
passkey; what a service applying the record checks is in the record itself:

- **What a revision drops, it revokes in the same revision (FAC-SEM-114).** A removed machine is listed as
  `machine <id>` in `revocations`, and its hub key as `hub-key <kid>`; a replaced device key is revoked by its key
  reference, `<kid>@sha256:<hex of its octets>` (`device_key_ref` / `deviceKeyRef`), so the new key under the same kid
  stays usable; a hub key certified anew takes a new kid. `verify_estate_record(record, at=..., parent=previous)` runs it
  when you pass the parent; `estate_record_rules("estate-record-revision", {"parent", "next"})` alone.
- **A device key's octets are canonical padded base64 (FAC-SEM-073),** the one form a key reference can name
  (`device_key_fingerprint`), and a `device-key` revocation that holds `@` is a well-formed key reference (FAC-SEM-076).
- **A headless machine joins with an `enroll-token/1`** (`fabric_ceremonies.py`, `fabric-ceremonies.mjs`). Read the token
  from stdin or a file only your user can read, never from argv, a URL or a log. `verify_enroll_token(token, record=,
  genesis=, at=)` checks it against the revision you applied and revision 1's digest; sign `enroll_join_input(token)`
  with the machine's `#sig` key and present that proof with the token. The token gives the machine no trust: only the
  passkey-signed revision that lists it does. `enroll_token_rules("enroll-token", token)` is FAC-SEM-113.

- **A machine nearby pairs by a comparison code.** Each side commits (`pairing_commit`), then reveals; each checks the
  other's reveal against its commitment, and both screens show the same six digits only when nothing sat in the middle
  (`checked_comparison_code`, never `comparison_code` on unchecked reveals). The one-time rendezvous burns on the first
  repeat, out-of-order message, mismatch, abort or after 600 s (`rendezvous_verdict`). Before it pins the estate, the new
  machine checks that the revision lists it with the keys it revealed and the trusted machine with its `#sig` key
  (`join_listed`), and shows `estate_fingerprint` of revision 1 for the person to compare. On each later revision it
  runs `own_keys_decision`: apply and retire the keys the record dropped, or stop when it was removed or another holder
  carries its key.
- **The hub binds a token once** (`redeem_enroll_token`): the joining machine's proof is its `#sig` key's signature over
  `enroll_join_input(token)` (ES256 as 64 bytes r and s, low S; Ed25519), and a second use, by any key, is refused and
  logged.

The relay's admission and session checks belong to the relay; the kits do not run a relay.

## Share grants into an organization

Contract DEC-0086. A grant whose `context` is an organization's (`org:<orgId>`) is a share grant, and the organization
server joins every `grant.usage` to the agent it runs through a share registration the sharer's node sends. Before you
sign a revision that places one, run `fabric_share.py` (`fabric-share.mjs`):

- `share_rules("org-share-grants", {"record": next, "parent": previous})`: FAC-SEM-117. The grant's `meta.id` is
  `urn:fabric:share:` and 32 lower-case hex digits from a CSPRNG (`secrets.token_hex(16)`), never a name, an address or an
  estate id; its window carries at most three fraction digits; the placements naming it run one `agentRef`; and against
  `parent`, the latest earlier revision that placed it, that `agentRef` never changes. To move a share to another agent,
  revoke the grant and mint a new id.
- `share_rules("grant", grant)`: FAC-SEM-110 and 117 on one grant.
- `share_rules("share-registration", doc)`: FAC-SEM-118 on a `share-registration/1` document you read or log.
- `share_rules("device-attribution", {binding, batch})`: FAC-SEM-045's DEC-0086 clause, for a collector that sends
  `grant.usage`: each carries its grant's own context, `org:` and the certificate's `org.id` as written.

`share-registration.schema.json` beside the kit is the contract's schema with `shareGrantId`, `orgContextId`,
`sha256` and `agentRef` brought in, so it validates offline. Deriving, sending, deciding and joining registrations are the
sharer's node's and the organization server's, not this kit's.

## Checking a record you produce

`estate_record_rules(kind, value)` / `estateRecordRules(kind, value)` are the contract's rules, finding for finding:
- `estate-record` (FAC-SEM-072…076, 092, 110, 111, 122, 134, 147);
- `estate-record-revision` `{parent, next}` (072, 114, 137);
- `estate-placement` `{record, machine, package, context?}` (074, 075, 111, 122): the package placed on that machine in that
  context, `personal` when `context` is absent.

`placement_trust(record, machine, agentRef, context="personal")` / `placementTrust(record, machine, agentRef, context)`
names the publisher keys a package verifier trusts for the package placed in that context. A caller that passes no
context gets the personal placement, as before contexts. A partner's key placed outside the contexts its scope names
answers `{publisher: []}`: the placement exists, and no key may verify it (DEC-0090).

## What the kit does not do

- It does not sign: it holds no passkey and no private key.
- It does not check the schema or verify packages.
- It does not attest the authenticator (an assertion carries no attestation).
- It does not track the signature counter: passkeys sync between devices.
