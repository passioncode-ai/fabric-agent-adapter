# Acceptance

The assembled agent is done when every item of the prompt's section 9 (`TEMPLATE.md`) passes on the build the channel
runs, not on a fixture:

1. Tests for every rule of sections 1 to 8 that has a check, as the creating-fabric-agents references
   agents-that-answer-people.md and practices.md list them.
2. The offline set of at least 50 real questions (restated, no personal data), judged blind by two judges of different
   vendors, scores at least as high as one call of the planning model.
3. Every adversarial batch of section 9 passes with its expected behaviour.
4. Clarifying questions and referrals are counted as shares of answered turns from the first day.
5. The first week's support.quality_daily is reported per channel against section 9's targets; a metric not measured is
   null and named in notMeasured.

Isolation and access: a member cannot read another person's conversation; channel text never acts as an instruction;
a closed-vendor route on a lane that reads people is refused by the agent's own config loader. Contract conformance:
the service passes the adapter's `check_service.py` and its channel-agent declaration validates.
