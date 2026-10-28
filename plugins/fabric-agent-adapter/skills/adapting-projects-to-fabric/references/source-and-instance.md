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
| `config/<name>.example.json` (or `.env.example`, `*.example.yaml`) | every instance value the agent reads, with a neutral default: the repository address of the owner's account, folders, the owner, account ids, hosts | yes, the example only |
| the instance folder, outside the repository | the real configuration, records (a database included), logs, journals, state documents | never in the source's repository (a separate private repository of the owner's data belongs to the instance) |
| the secret store | key values; the source names each key by name only (`EXAMPLE_API_KEY`) | never |

- **The instance folder is the agent's data folder.** An agent that is not a kit service reads it through one named
  variable (`<AGENT>_DATA_DIR`) that overrides its default. A service built with `building-fabric-services` takes the
  kit's folders unchanged (the Directories table in its `references/lifecycle.md`, `fabric_paths.service_dirs`): on macOS `~/Library/Application Support/<id>/`,
  on Linux `${XDG_DATA_HOME:-~/.local/share}/<id>/`, on Windows `%LOCALAPPDATA%\<id>\`. An agent's second context
  (an organization's) is a sibling instance, `<id>.<instance>`, never a folder inside the personal one
  (`references/estate-record.md` of that skill).
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
- **Two names stay in the source until the contract decides (CT-194).** A service's supervisor label is the agent's
  own name, reverse-DNS on the publisher's domain (`com.example.example-agent`), and `AGENTS.md` names it (LC-09):
  never the owner's account or name. A provider's `createdBy` names the publisher; until one is chosen it
  keeps the scaffold's sentinel, and a person's name or account is never written there. The adapter moves both when the
  contract decides how an instance renames them (FAA-188 part 2).

## The check

`fabric_source_check.py check` reads the files the source would carry (what Git would commit: tracked files and
untracked ones that are not ignored) and reports each place where the instance shows through, by path, line and kind:

| Kind | Finds |
|---|---|
| `home-path` | an absolute path inside a person's home folder: `/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>\`, and the dashed (`-Users-<name>-`) and URL-encoded forms a tool makes of one |
| `secret` | a value shaped like a credential by the contract's detector (DEC-0044), read line by line: a provider key starting a word, a JWT, a bearer token, a long random value assigned to a credential's name; or a private key block |
| `instance-string` | a string from the owner's list, in a file, in a file's path or in a link's target |

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/fabric_source_check.py check <project-root>
```

- It **never repeats** a value it found: no value, no line holding one, no entry of the owner's list and not the
  folder it checks reaches its output. A file's path is checked like its text (line `0` of a finding), and printed
  with an entry of the list as `<line N>`, a home folder's name as `<home>` and a credential-shaped value as
  `<secret>`; an instance string is named by its line in the owner's list. The report can go in a commit
  message, an issue or a chat.
- It **changes nothing.** Exit `0`: no finding and every file read; `1`: at least one finding (the step is not done);
  `2`: the check could not run, or a file could not be read (the summary counts them).
- **What it reads.** A text file of any size is read whole, and the summary counts every text file read; a binary file (a NUL byte in its first 8 KiB) or one that
  cannot be read is listed by its path as not read, and the summary counts it. A database or another binary of
  records in the tree is instance data the check cannot read: move it to the instance folder. A committed symbolic link is checked by the path it names, never followed. When the folder is
  not in a Git checkout, or Git lists nothing in it, every file is read, and the summary says Git was not used.
- **The owner's list** holds the strings only the owner knows are theirs (their name, company, accounts, hosts), one
  per line, `#` comments, at least three characters. It is `--instance-strings FILE`, else the file
  `FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
  (`$XDG_CONFIG_HOME` or `~/.config`; `%APPDATA%` on Windows). A list inside the tree is refused, because it would
  travel with the source. A person who already keeps private terms for org-index's `check_private.py`
  (`~/.config/passioncode/private-terms.txt`) passes that file with `--instance-strings`; this check matches a term
  anywhere in a word, and it does not look for e-mail addresses or account ids by their shape.
- **Leaving paths out.** `.fabric-source-ignore` at the root (globs, one per line, `#` comments) or `--exclude GLOB`
  leaves out files that hold synthetic values on purpose, such as test vectors. Name the files, or a folder that holds
  only synthetic vectors, never a whole source folder, and say why on the line above.
- A neutral home (`example`, `user`, `runner`, a container's or a cloud machine's user such as `node` or `ubuntu`, a
  one-letter name, a placeholder) and a value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) are
  not findings.

The check reads the tree, not Git history. A value that was committed once is still in the history after the tree is
clean: handing such a source over needs a fresh history, which is the owner's act, never the agent's (no history
rewrite, no force-push).
