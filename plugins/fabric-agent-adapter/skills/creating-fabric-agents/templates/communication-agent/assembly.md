# Assembly

How a developer agent fills this template for one organization.

1. Answer the brief (section 0 of the prompt in `TEMPLATE.md`) from the organization's systems: its product and
   audience, each channel with its transport and volume, the business pattern per channel, what the agent may do and
   what only a person may do with that person's queue, the knowledge sources with their owners and maximum ages, the
   tools for account data, the voice pack, the owner and the access levels. A field the systems do not answer is a
   question for the agent's owner before the build, never a guess.
2. Defaults: a model key of USD 100 a month with the code's stop just under it; the open-vendor lanes of section 7;
   one variant, `local` or `cloud`, by where the organization runs its agents.
3. What needs a person: the owner's switch of each channel to live (S2's A8 gate for that channel's replies), a key
   limit above the default, a grant for a transport or a CRM, and the weekly labelling of judged pairs.
4. Give the whole prompt to the coding agent in the agent's own repository; it builds the agent end to end and passes
   `checks/acceptance.md`.
