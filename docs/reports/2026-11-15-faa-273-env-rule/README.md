---
report: 2026-11-15-faa-273-env-rule
project: fabric-agent-adapter
date: 2026-11-15
topic: the environment value rule, FAA-273 items 8, 10 and 15
---

# The environment value rule, measured (FAA-273 items 8, 10, 15)

A supervisor file (launchd, systemd, Task Scheduler) and a plugin MCP server's `env` never carry a credential. Since
0.76.0 (FAA-266) a value that reads as a path was read by the path-aware detector, any other value by the strict one.
FAA-273 named three ways that rule was wrong: it refused a release folder with no lower-case part whose words ran to 40
characters across a space (item 8), it let a base64 key through when the key started with `/` and held two more
(item 10), and it let a key through as a real path's last part (item 15), since the path-aware detector looks for a
40-character run between separators.

## The rule from 0.91.4

`fabric_secrets.secret_env_value` (and `secretEnvValue` in `fabric-secrets.mjs`); the supervisor writers and
`adapt_project.py` call it:

- a JWT, a provider key or `Bearer` anywhere is a credential;
- a value that starts as a path (`/`, `~`, `.`, a drive) and has two or more separators is one only when a part between
  `/`, `\`, `:` or a space is 20 characters or more (`ENV_KEY_PART`), mixes upper case, lower case and digits, and holds
  no lower-case word (three or more characters, letter first) between `-`, `_` or `.`; or when it has no such word as a
  part, is written in base64's alphabet alone, and the strict detector finds it;
- any other value is judged by the strict detector, as before.

## Measured

`python3 -I docs/reports/2026-11-15-faa-273-env-rule/measure.py` on 2026-11-15, macOS 26.6.2, Python 3.14.7, on this
machine's folders (up to four levels under Application Support, Applications, the projects folder, `/usr/local`, the
Homebrew cellar and `~/.local/share`; counts only):

| Corpus | Size | 0.76.0 to 0.91.2 | 0.91.4 | Wanted |
|---|---|---|---|---|
| random base64 keys (32, 48, 64 bytes, seed 2026) | 60,000 | 59,980 | 59,986 | caught |
| of them, keys starting with `/` | 953 | 946 | 952 | caught |
| a key cut to 24, 32 or 38 characters after `/opt/xyz/` | 60,000 | 0 | 51,061 | caught |
| url-safe keys | 10,000 | 9,999 | 9,999 | caught |
| this machine's folders | 16,732 | 75 | 18 | refused |
| three folders joined by `:` | 3,000 | 21 | 8 | refused |
| item 8's release folders | 31 | 31 | 0 | refused |

The strict detector alone catches 59,987 of the random keys. The new rule is better than the old one on every corpus.
What it still refuses among real folders are parts that read as keys: a CamelCase name with a digit and no separator
(a shader cache's file names) and random-looking identifiers some applications name folders with; such a value goes
into a supervisor file only through the service's own token file or a secret reference.

Cases for items 8, 10 and 15 are in `test/fixtures/kit-env-rule-cases.json`, read by all three copies of the rule
(`test_fabric_service_supervisors.EnvRuleCorpus` and its Node twin); each failed on the 0.91.3 tree.
