# Where an agent runs: this machine, a personal cloud, an organization

An agent built with this skill can run on the person's own machine, in their personal cloud, or in an organization's
cloud, and the same agent can serve the person and several organizations at once. Decide where it runs at the intake
grill (*Where does it run?*), because it decides where its secrets live, who pays for its calls, whose journal records
it, and what happens when the person's laptop is closed.

The normative rules are the Fabric Agent Contract's, at the commit this plugin pins: `docs/specification/contexts.md`
(contexts), `estate-record.md` (machines and placements), `share-registration.md` (sharing into an organization),
`entitlement.md` (what an order entitles), `ceremonies.md` (adding a machine). This page says how to design for them.

## Contents

- [The places](#the-places)
- [Contexts: one agent, the person and each organization](#contexts-one-agent-the-person-and-each-organization)
- [Connecting a machine or a cloud to the estate](#connecting-a-machine-or-a-cloud-to-the-estate)
- [Sharing an agent into an organization](#sharing-an-agent-into-an-organization)
- [Running while the laptop is closed](#running-while-the-laptop-is-closed)
- [Selling an agent](#selling-an-agent)
- [The checklist](#the-checklist)

## The places

| Where | What it is | Typical agent |
|---|---|---|
| **This machine** | the person's computer, Fabric and its services local; free and open source | a coding helper, a personal assistant that may stop when the laptop sleeps |
| **Personal cloud** | the person's own always-on machine in PassionCode's cloud (or the same stack self-hosted), one more machine of their estate | an agent that answers mail at night, a scheduled digest, a bot |
| **Organization** | the organization's cloud, its members' machines enrolled into it, its own server holding members, grants and usage | a support agent, an internal analyst, an agent the organization bought |
| **Enterprise** | an organization's dedicated cloud with personal onboarding | the same agents under the enterprise's own boundary |

Every step up is paid as cloud only: the person or the organization pays for the cloud its agents run in, and the
order says which hosting it holds (`personal-cloud`, `org-cloud`, `enterprise-cloud` in `entitlement/1`). An agent never
checks a price; it may read whether its context's entitlement is current and degrade honestly when it is not.

## Contexts: one agent, the person and each organization

A context is `personal` or `org:<orgId>`, compared exactly as written. Design every agent as if it will run in more
than one:

- **One instance per context.** On a machine an agent runs once per (agent, context). The personal instance and an
  organization's instance are two instances with two state folders, two journals and two sets of secrets; never one
  process that switches. In the estate record a placement names its `context`, and an organization's placement names
  the share grant it runs under (FAC-SEM-074, FAC-SEM-111).
- **Secrets stay in their context.** An organization's instance fills its secret slots from the organization's own
  machine and vault; a personal secret never reaches it, and the person's personal keys never pay for organization
  work.
- **Spend and usage stay in their context.** Every call is metered under the grant it runs under; the organization
  sees its instance's usage (`grant.usage`) and nothing of the person's personal work.
- **Contexts are never linked.** Nothing the agent sends to one organization names the person's personal context or
  another organization: no shared ids, no shared logs, no "also used by" field.
- **Access is the grant, not a label.** What an organization's instance may do is its grant's capabilities, effect
  ceiling, data classes, spend windows and expiry. A named level ("read only") is a preset that fills those fields.

## Connecting a machine or a cloud to the estate

A person's machines form their estate; an estate record signed with the person's passkey lists every machine, its
keys, and what runs where. A new machine joins only when a passkey-signed revision lists it:

- **Nearby** (a laptop, a phone): the two machines show the same six-digit comparison code; the person confirms it.
- **Headless** (a cloud machine, a server): Fabric issues an `enroll-token/1`, valid for at most 15 minutes and one use.
  The machine reads it from stdin or a file only its user can read, never from a command-line argument, a URL or a
  log, proves its key with it, and waits until the revision that lists it is signed. The token gives no trust by
  itself. The kit's `fabric_ceremonies.py` checks a token (building-fabric-services, *The estate ceremonies*).
- **An organization's machine** enrolls into the organization's server: a device certificate names the organization
  (`org.id`), and the machine's collector routes each context's events only to the server of that context.

Removing a machine or replacing its key is a revision that revokes what it drops in the same revision (FAC-SEM-114).
An agent service that applies the estate record verifies each revision with its parent before trusting it.

## Sharing an agent into an organization

The person's own agent can work for an organization without being copied into it:

1. Fabric writes a **share grant** into the organization: `context: org:<orgId>`, id `urn:fabric:share:` and 32 random
   hex digits, one agent (`agentRef`) for its whole life, a window, the capabilities and spend the organization may
   use. Moving the share to another agent revokes the grant and mints a new id.
2. The person's node sends the organization a **share registration**, so its server knows which agent the grant runs.
3. The instance placed in that context runs under the grant; its daily `grant.usage` goes to the organization's
   server, carrying the grant's own context.

The kit checks the grant and the usage event (`fabric_share.py`). Revoking the grant stops calls at once where they are
checked, and removes the instance from the next revision.

## Running while the laptop is closed

A cloud agent keeps working with the laptop closed only if everything it needs is in the cloud: its worker, its
secrets, its data, and a hub that can admit calls. The local Fabric hub is not a cloud hub. Design for it:

- Declare what each capability needs and where it is; a capability that needs the person's machine reports
  `pending` or `unavailable` instead of pretending, and queues within a deadline or declines.
- Never charge for work it cannot deliver on the promised terms.
- A test that passed on fixtures says nothing about uptime; measure the installed agent in its cloud.

## Selling an agent

- **A paid agent** runs in PassionCode's cloud inside its developer's organization (`org:<developer>`); each customer
  organization reaches it through its own credential, which is the credential of an external grant, metered per
  customer. The developer sets the price; the platform earns the cloud.
- **A partner** builds agents for a company and delivers them as a setup: each agent its own signed package, and one
  organization skill set that requires them, all signed with the partner's key (building-fabric-services, *package*,
  *A partner's setup for a company*). The company pays for the cloud; the partner's own work is between them.
- Whatever is sold: one signed `fabric-package/1` per version, no secret in it, every effect declared, and the agent's
  spend under the customer's grant, never under the developer's personal key.

## The checklist

- Where does each instance run, and in which context? Write it in the knowledge pack.
- Does any state, secret, log line or cache key cross contexts? It must not.
- Which capabilities need the person's machine, and what do they answer when it is off?
- Who pays for each call (which grant, which key)? The person's personal key never pays for an organization.
- If it joins machines or applies the estate record: tokens from stdin or a 0600 file only, revisions verified with
  their parent.
