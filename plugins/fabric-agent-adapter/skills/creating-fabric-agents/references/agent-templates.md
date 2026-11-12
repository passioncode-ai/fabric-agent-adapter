# Agent templates: the folder, its schema and its check

An organization's agents are built from **templates**: one folder per kind of agent, which a developer agent fills for
one organization (fabric-workspace `knowledge/system/templates.md`, decision W0-Q8; FAA-265). The adapter holds the
format, versioned with it: the JSON Schemas in [`schemas/template/`](../schemas/template/) and the check
[`scripts/template_check.py`](../scripts/template_check.py). The templates themselves live in the agents database
(format v2, see [agents-database.md](agents-database.md)); the adapter keeps one neutral example for its tests,
`test/fixtures/templates/example-agent/`, and one public template, the communication agent
([`templates/communication-agent/`](../templates/communication-agent/), released as one file in 0.75.0 and moved into
its folder by FAA-265). Whether the agents database takes that folder as its template of the kind or merges it into a
close one is its owner's decision, open; `test/validate.py` runs the check on every folder a skill ships.

## The folder

| Part | Holds | Checked |
|---|---|---|
| `TEMPLATE.md` | a front matter block with one `template:` mapping (`id`, `name`, `version`, `family`, `checked`, `readiness`, `variants`, optional `sources`), then the prompt: role, duties, never, escalation | the header against `template-header.schema.json`; `id` equals the folder's name; the text names the operating rules A1 to A12 it inherits |
| `manifest.json` | `template`, `version`, `contract` (one protocol `{name, home, checked_against}` or a map of them), `placement`, `doors`, `models`, `dashboard`, `budget` | `manifest.schema.json`; `template` and `version` equal the header's; the last five sit at the top or in every entry of `variants` |
| `connections.json` | a list of `{source_class, connector, grant, required, direction}` with optional `when`, `scope`, `spends`, `variants`, `notes` | `connections.schema.json`; `direction` is `read`, `write`, `read-write` or `call`, the detail in `scope` |
| `access.json` | `levels` with `owner`, `administrator`, `project_architect` and `member`, each `{without_asking, with_approval, escalates}`, and `never` | `access.schema.json`; the owner escalates to nobody |
| `data-rooms.json` | a list of `{room, blocks, access}` with optional `scope`, `classes`, `level`, `required`, `variants`, `use`, `notes`; `[]` when none | `data-rooms.schema.json` |
| `checks/` | the acceptance tests the assembled agent passes before it serves anyone | at least one file |
| `assembly.md` | how a developer agent fills it for one organization | present, not empty |
| `CHANGELOG.md` | the template's versions | names the header's version |

Every variant a file names is one the header declares. A key a template needs beyond the schema goes in as `x-<name>`
in `manifest.json` or `access.json` (an entry of the manifest's `variants` may carry keys of its own); anywhere else
an unknown key is an error, so a typo never passes as a new field. A grant is named, never its value. Schema 1 checks
only the presence and type of `placement`, `doors`, `models`, `dashboard` and `budget`, not their inner shape.

## Running the check

```
python3 <skill>/scripts/template_check.py [--legacy] [--json] <template-folder> [...]
```

Run it from the skill's own directory, not a copy. It reads only and exits 0 when no folder has an error, 1 when one
has, 2 on a usage error; `--json` prints `{ok, folders: {<folder>: [{level, file, path, message}]}}`.

`--legacy` reads the older spellings the first templates used (`class` for `source_class`, `mode` or a sentence for
`direction`, `required` as a sentence, levels outside `levels`, `project architect` or `architect`, `withApproval`,
`never_*` keys, `block`, `spend`, `checkedAgainst`) and names each as a warning with its canonical form; a missing
`direction` or manifest `version` is a warning there and an error otherwise. Use it to migrate a folder, then fix the
warnings: a template is done when the check passes without it.
