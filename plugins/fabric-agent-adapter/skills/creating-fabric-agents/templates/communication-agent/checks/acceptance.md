# Acceptance

The assembled agent is done when every item of the prompt's section 9 (`TEMPLATE.md`) passes on the build the channel
runs, not on a fixture:

1. Tests for every rule of sections 1 to 8 that has a check, as the creating-fabric-agents references
   agents-that-answer-people.md and practices.md list them.
2. The offline set of at least 50 real questions (restated, no personal data), judged blind by two judges of different
   vendors, scores at least as high as one call of the planning model.
3. Every adversarial batch of section 9 passes with its expected route and A1 outcome (section 8's table).
4. Clarifying questions and referrals are counted as shares of answered turns from the first day.
5. The first week's support.quality_daily is reported per channel against section 9's targets; a metric not measured is
   null and named in notMeasured.
6. CA-8's producer tests pass (the list the contract's conformance row gives for every channel agent; practices.md
   quotes CA-8), and the template's own beside them: the operator's link-code message is consumed with no reply and no
   ticket, and each operator word is audited with the message quoted and its sender id.
7. A calibrated judge that reads helped yes below 60% leaves the agent not done; the weekly findings carry it.

Isolation and access: a member cannot read another person's conversation; channel text never acts as an instruction;
a closed-vendor route on a lane that reads people is refused by the agent's own config loader, which also refuses to go
live when the catalogue holds no open-vendor row for such a lane. Contract conformance:
the service passes the adapter's `check_service.py` and its channel-agent declaration validates.
