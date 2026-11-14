# Authority levels: a level holder's word in an organization

Contract DEC-0162 (`v0.1.0+2026-11-14.2`, `docs/specification/membership.md#levels`, LV-1 to LV-11). In an
organization's context the organization's owner, an administrator, or an architect in their own projects decides for
the organization's agents as the operator does in his own context. The operator decided the four levels on 2026-11-06;
the contract made them a signed fact.

## What a level decides

- **LV-2: a role is a level, for decisions only.** `owner` covers `admin`, `admin` covers every `architect`, an
  `architect` covers only the projects its attestation names, and `member` decides nothing by its level. A level never
  makes anyone a signer.
- **LV-3: the level decision.** When a level holder tells you to take a relayed action, relay their words as a level
  decision: `by: level`, `via: level-command`, the `level`, the organization `org`, the `project` (required for an
  architect), the `action`, the `target` when they named one, their words verbatim in `instruction`, `at`, and their
  `org-membership/2` attestation in `membership`. Relay it never in the operator's form (`by: operator`), which a
  service in an organization's context does not take for an act only a level decides.
- **LV-5: the binding.** The hub writes the digest of the holder's attestation into your delegation token as `mem`; a
  service takes a level decision only from a call whose token carries it. You do not set `mem` yourself.
- **LV-6: the level mandate.** For a task the holder gives, state a level mandate (`mandate/1` with `by: level`, the
  level, the organization and the attestation; an architect's scope lists its projects). It travels in `_meta.mandate`
  to the service the attestation is for, never over the project board.
- **LV-7: the bounds.** A service may declare an action `owner` (a billing act: the plan, the payment method, the
  invoices), `admin` (an access grant, a spend limit, a client key's revocation, a source hand-over) or `operator` (an
  act no level decides, such as a rule proposal's approval). A call below that level is answered
  `operator-decision-required` with `level-insufficient: owner` or `level-insufficient: admin`: send one request to a
  holder of that level, whose own agent acts under its own level decision. An action whose effect is `change-policy` is
  an administrator's at least. No level covers a human step, spend above a limit, a personal context or another
  organization.

## What stays the same

- In the operator's own (personal) context nothing changes: his word, relayed as the operator's decision or mandate.
- A member's request carries no level: it goes through the approvals the product provides.
- A refusal `decision-invalid` with `level-membership: <problem>`, `level-unbound`, `level-audience`, `level-expired` or
  `level-role` means the attestation or its binding does not stand: get a fresh attestation through the hub, never a
  copy from another call.

The kit's reference is `fabric_levels` / `fabric-levels.mjs` and `action_decision` / `actionDecision`
(building-fabric-services, the interop reference's *Actions*).
