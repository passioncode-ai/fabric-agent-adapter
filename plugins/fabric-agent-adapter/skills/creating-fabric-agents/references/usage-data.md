# Anonymous usage and error data (DEC-0157)

The contract's [usage data page](https://github.com/passioncode-ai/fabric-agent-contract/blob/560d60369b553fc123ba29c3e1e637de68901678/docs/specification/usage-data.md)
(DEC-0157, rules UD-1 to UD-6) binds every product the estate ships to people that collects anonymous data about how it
is used and about its errors: an app, an agent, a command line tool, a service installed on the person's machine or a
component run on their own server. A product may collect none. A hosted service that installs nothing for the person is
outside the page (pending the operator's answer, the contract's OQ-0013). The kit offers no usage data switch of its
own: an agent or service that sends such data builds what follows, and nothing on the wire declares it.

## Contents

- [Before the first send: the notice (UD-1)](#before-the-first-send-the-notice-ud-1)
- [The agent's own switch (UD-2)](#the-agents-own-switch-ud-2)
- [Anonymous ids (UD-3)](#anonymous-ids-ud-3)
- [The agent's door to the switch (UD-4)](#the-agents-door-to-the-switch-ud-4)
- [The usage data page (UD-5)](#the-usage-data-page-ud-5)
- [What is not usage data (UD-6)](#what-is-not-usage-data-ud-6)
- [Checklist](#checklist)

## Before the first send: the notice (UD-1)

On by default, for a new install and for an existing one that never answered and never declined. Send nothing before the
notice was shown once where the person reads it: the first start that opens the window, or, for an agent, a command line
tool or a service with no window (or one started at login, in the background or by a silent update), its first output to
the person: the agent's first answer in the person's chat, the first run in a terminal the person reads, the installer's
output, the service's page on its first open. A line only an agent's tool reads is not that place. What was collected
before then is sent only after the notice, or dropped.

The notice is a notice, never a question: the first send waits for it to be shown, never for an answer; no answer means
on, and an OK may be offered with nothing waiting on it. Where a platform's own consent or a market's privacy review asks
first, ask there, send nothing until it is answered and treat no answer as off in that place.

The notice names what is collected and its purpose (to improve the product; counting one installation once across the
products that share an installation id, when it sends a shared one); the installation id it sends, whether it is shared
and with which products (with a link to the maintained list of them), that it ties this install's events together though
no person is named, and that turning the switch back on resumes a shared id; a session id when it sends one, and that it
ties one session's events together; where the data goes (the receiving organization, or a link to the usage data page);
and where the switch is. Show it again, once, before sending under a change of what it states (a new purpose, a new
sharing product).

## The agent's own switch (UD-2)

The switch lives in the product's own settings and governs that product alone. Read it before the first send, and on
every start. Off stops usage and error data both, drops what waits to be sent, and removes nothing already sent. An
installation id the product owns is deleted at off and made anew at on; a shared id is never deleted or rotated by one
product, only no longer sent.

An earlier decline stays off. A shared off (the `analytics` field of the shared `PassionCode/installation.json`) present
before the product's first send, on an install whose own switch the person never set on, is that earlier no: show the
product's switch as off and say where to turn it on. After the first send the product's own switch alone governs it. A
product's switch never writes the shared file. A shared file that exists but cannot be read before the first send is no
answer: send nothing in that run, say beside the switch that nothing is sent until the file can be read, and read it
again at the next start. A device policy may lock the switch off, never on.

## Anonymous ids (UD-3)

Anonymous means no person named, not unlinkable. Leave out every person (a name, an email, a phone, an account, a billing
or store id, an IP address kept with the data, a hardware or advertising id), every credential, every path or file name
from the person's machine or data, and any content a person wrote or received. An installation id the product creates is
a random UUID for analytics only, never derived from another id. A session id, if sent, is random, kept only in memory,
renewed no later than after an idle hour, and authorizes nothing. No one (the product, the receiving service, any agent
or service that reads the data there) joins either id with an account, purchase, billing or advertising record; data so
joined is personal, needs its own consent and is never called anonymous. Error data names a place in the product's own
code and is cleared of content, paths and credentials before it leaves.

## The agent's door to the switch (UD-4)

A product that offers its switch in its app or page offers it on its agent surface too (AP-1): a tool whose manifest
capability declares the effect `change-policy`, and an action under `extensions/actions/0.1` with `gate: relayed`; a gate
of `none` is nonconformant. Where the ask-first branch of UD-1 applies, the action that turns it on is
`gate: human` with `humanStep: consent`, and a separate action turns it off with `gate: relayed`.

An agent turns a switch a person turned off back on only on that person's own word for that switch, and only when the
person is its operator: a decision the operator gave naming the switch, or an `approval/1` the operator gave for it.
Never a mandate, another approver's approval or a standing rule. In an organization's context at a service given
`levels`, only a level decision decides it, and it is the person's word only when the level holder is that person.
Anyone else is told the switch is in the product's settings. An agent never declines a person who asks to turn their
switch off, never sends around a switch that is off, and never deletes or rewrites a shared file it cannot read. A command
line the person runs in their own shell (such as an `analytics on|off` command) is their own surface and owes no action.

## The usage data page (UD-5)

Each product documents, in its privacy text and a usage data page: what it sends, the installation id when it sends one
and whether it is shared, where it goes (the receiving organization and host, and every service or agent that reads it
there with its purpose), the switch, how long it is kept, the version that turned it on, and whether and how sent data
can be erased. Where erasure needs an id, show it beside the switch before off deletes it, or say there that turning off
ends erasure.

## What is not usage data (UD-6)

Activity telemetry (DEC-0030), an organization's record of its people's sessions sent by an enrolled device's collector,
is under its own notice and consent; neither kind travels in the other's channel. An operations digest (DEC-0153) kept on
its machine, or read only by the person, is not usage data; a digest sent to anyone else is, and is sent only for a
product whose switch is on and whose notice was shown. OpenRouter attribution (DEC-0065) and a service's usage report
(`GET /fabric/v1/usage`, read by its host) are not usage data either.

## Checklist

- [ ] The first send waits for the notice, shown where the person reads it; nothing waits for an answer (UD-1).
- [ ] The notice names what, why, the id and its sharing, any session id, where it goes and where the switch is (UD-1).
- [ ] The product's own switch is read before the first send; an earlier decline stays off; off drops what waits (UD-2).
- [ ] Only a random UUID installation id and an in-memory session id leave; no person, path, credential or content (UD-3).
- [ ] The switch's agent tool declares `change-policy` with `gate: relayed`, on only on the operator's word (UD-4).
- [ ] The usage data page is written and linked from the notice (UD-5).
