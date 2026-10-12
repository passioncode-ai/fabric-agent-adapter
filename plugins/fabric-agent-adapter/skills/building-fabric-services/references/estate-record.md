# The estate record — what the operator's machines are, signed by their passkey (DEC-0055)

Fabric Agent Contract DEC-0055, `docs/specification/estate-record.md`, schema `schemas/estate-record.schema.json`,
rules `FAC-SEM-072…076`. One revision of one person's estate lists:
- the passkeys that sign it;
- the machines, with their device keys and a certificate of each machine's hub key;
- the packages placed on each machine;
- where each secret slot is filled from (by reference only);
- share grants and revocations.

A revision names its parent's digest and is signed by a passkey assertion (WebAuthn Level 3) over a challenge
derived from its own digest. Python: [`scripts/fabric_estate.py`](../scripts/fabric_estate.py). Node:
[`scripts/fabric-estate.mjs`](../scripts/fabric-estate.mjs). Both answer the contract's own vectors.

## Contents

- Applying a revision
- Trusting a delegation key
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
6. **The assertion.**
   - Client data: type, challenge, origin, no cross-origin use.
   - The RP ID hash, and the user-presence and user-verification flags.
   - The signature: ES256 or EdDSA, under a key validated first (a valid P-256 point; an Ed25519 key of full order).
7. **The window.** At most 30 days.
8. **The record's own rules.** A violation is `rule-violation` with its `codes`.

Dates are strict RFC 3339: a `T`, an offset, and a day that exists. `:60` and a space are refused. Passkey JWK `x`
and `y` must be canonical base64url. The Python kit verifies ES256 in pure Python (P-256, strict DER), and the Node
kit through `node:crypto`.

## Trusting a delegation key

A delegation verifier that reads the estate record trusts a token's `kid` only while a current revision certifies it
for a machine and does not revoke it (DL-14, contract CT-20). Give the gate the current verified revision, or a
function that returns it:

```python
gate = fd.delegation_gate(audience=..., jwks=keys, issuer=..., effects=..., estate=lambda: current)
```

- A `kid` the record does not certify is refused like an unknown key: `unauthenticated` (for an approval,
  `approval-invalid`) with detail `kid-not-certified`. The same holds when the record names another key under that
  kid, revokes it, or is outside its window.
- A record that cannot be read certifies nothing: `issuer-unavailable` with detail `estate-unreadable`.
- **What you pass in.** Pass only a revision that `verify_estate_record` accepted, and the highest revision the
  machine has applied. The rule trusts the record it is given. A record nobody verified, or an older revision still
  inside its window, would certify a key the current revision revoked (a rollback).
- `hub_key_certified(record, kid, x, at)` / `hubKeyCertified(...)` answers the question on its own.

## Checking a record you produce

`estate_record_rules(kind, value)` / `estateRecordRules(kind, value)` are the contract's rules, finding for finding:
- `estate-record` (FAC-SEM-072…076);
- `estate-record-revision` `{parent, next}` (072);
- `estate-placement` `{record, machine, package}` (074, 075).

`placement_trust(record, machine, agentRef)` names the publisher keys a package verifier trusts for a placed package.

## What the kit does not do

- It does not sign: it holds no passkey and no private key.
- It does not check the schema or verify packages.
- It does not attest the authenticator (an assertion carries no attestation).
- It does not track the signature counter: passkeys sync between devices.
