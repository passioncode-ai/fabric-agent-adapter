# The source and the instance

An agent is two things. Its **source** is what can be handed to someone else: code, skills, prompts, schemas,
examples, the source documentation. Its **instance** is what belongs to one installation: records, logs, journals,
keys, the owner's names and paths, accounts, hosts and its configuration. A new agent keeps the two apart from its
first commit, so that its owner can hand the source over later without rewriting its history. Nothing is handed over
by itself: handing over, a new remote, a push or a change of visibility stays the owner's act, each time (a personal
agent stays private until its owner says so about that act).

The format of a source manifest, export and import is the contract's to decide (CT-194). What follows does not depend
on it.

## The layout

| Where | What | In Git |
|---|---|---|
| the repository | code, skills, prompts, schemas, the source documentation, fixtures on neutral ids (`example-agent`, `/Users/example`) | yes |
| `config/<name>.example.json` (or `.env.example`, `*.example.yaml`) | every instance value the agent reads, with a neutral default: the service label, the repository address, folders, the owner, account ids, hosts | yes, the example only |
| the instance folder, outside the repository | the real configuration, records, logs, journals, state documents | never |
| the secret store | key values; the source names each key by name only (`EXAMPLE_API_KEY`) | never |

- **Read the instance folder through one named variable** with a default outside the tree:
  `<AGENT>_DATA_DIR`, else the platform's data folder (`~/.local/share/<agent-id>/` on Linux and macOS,
  `%LOCALAPPDATA%\<agent-id>\` on Windows). Under it, one folder per context (`personal`, `org-<id>`): an instance
  never reads another context's data.
- **Ignore the instance in the source**: `.gitignore` names the real configuration (`config/*.json` with
  `!config/*.example.json`), and an instance folder that sits inside the checkout during development.
- **State documents are instance data.** A handoff, a decision log or a backlog about this codebase is source
  documentation; a record of what this installation did (runs, conversations, the owner's notes, a journal) lives in
  the instance folder.
- **Keys by name.** The README's Configure section lists key names, the agent reads each from its environment or the
  secret store, and no value is ever written to a file, a fixture, an argument or a commit.
- **Fixtures on neutral ids.** A test that needs a home folder, an owner or an account uses `example`, `example-agent`,
  `owner@example.com` or a one-letter home, and a credential-shaped test value says it is synthetic
  (`sk-test-not-a-key`) or is assembled at run time.

## The check

`fabric_source_check.py check` reads the files the source would carry (what Git would commit: tracked files and
untracked ones that are not ignored) and reports each place where the instance shows through, by path, line and kind:

| Kind | Finds |
|---|---|
| `home-path` | an absolute path inside a person's home folder: `/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>\` |
| `secret` | a value shaped like a credential, by the contract's detector (DEC-0044), or a private key block |
| `instance-string` | a string from the owner's list, in a file or in a file's path |

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/fabric_source_check.py check <project-root>
```

- It **never repeats** a value it found: no value, no line holding one and no entry of the owner's list reaches its
  output, so the report can go in a commit message, an issue or a chat. An instance string is named by its entry
  number.
- It **changes nothing.** Exit `0`: no finding; `1`: at least one (the step is not done); `2`: the check could not
  run.
- **The owner's list** holds the strings only the owner knows are theirs (their name, company, accounts, hosts), one
  per line, `#` comments, at least three characters. It is `--instance-strings FILE`, else the file
  `FABRIC_INSTANCE_STRINGS` names, else `~/.config/passioncode-fabric/instance-strings.txt`. A list inside the tree is
  refused, because it would travel with the source.
- **Leaving paths out.** `.fabric-source-ignore` at the root (globs, one per line, `#` comments) or `--exclude GLOB`
  leaves out files that hold synthetic values on purpose, such as a folder of test vectors. Say why on the line above.
- A neutral home (`example`, `user`, `runner`, a one-letter name, a placeholder) and a value that says it is synthetic
  (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) are not findings.

The check reads the tree, not Git history. A value that was committed once is still in the history after the tree is
clean: handing such a source over needs a fresh history, which is the owner's act, never the agent's (no history
rewrite, no force-push).
