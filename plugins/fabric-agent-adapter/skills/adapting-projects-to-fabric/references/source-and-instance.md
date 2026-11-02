# The source and the instance

An agent is two things. Its **source** is what can be handed to someone else: code, skills, prompts, schemas,
examples, the source documentation. Its **instance** is what belongs to one installation: records, logs, journals,
keys, the owner's names and paths, accounts, hosts and its configuration. A new agent keeps the two apart from its
first commit, so that its owner can hand the source over later without rewriting its history. Nothing is handed over
by itself: handing over, a new remote, a push or a change of visibility stays the owner's act, each time (a personal
agent stays private until its owner says so about that act).

The format of a source manifest, export and import is the contract's to decide (CT-194). What follows does not depend
on it.

## Contents

- [The layout](#the-layout)
- [The check](#the-check)

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
  `!config/*.example.json`), an instance folder that sits inside the checkout during development, and what running
  the agent leaves (`__pycache__/`, `*.pyc`), which the check would otherwise report as binary in Git mode.
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
untracked ones that are not ignored, as they are in the work tree; a staged copy that differs is not read) and reports each place where the instance shows through, by path, line and kind:

| Kind | Finds |
|---|---|
| `home-path` | an absolute path inside a person's home folder (a web route under `/home/` is reported too; a route under `/users/` is not): `/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>\`, Git Bash's `/c/Users/<name>/`, WSL's `/mnt/c/Users/<name>/`, and the dashed (`-Users-<name>-`, `C--Users-<name>-`) and URL-encoded forms a tool makes of one. The name is ASCII, and in the dashed form it ends at the next dash: an owner whose home name is not ASCII or holds a dash puts it in the owner's list |
| `secret` | a value shaped like a credential by the contract's detector (DEC-0044), read line by line: a provider key starting a word, a JWT, a bearer token, a long random value assigned to a credential's name (but a whole Ed25519 signature under a JSON `"sig"`, `"signature"` or `"signatures"` member, as `sign` writes it, which is public); or a private key: a PEM, OpenSSH or PGP block, or a JWK's `d` as a JSON member, escaped JSON or a Python dict; a URL with a password of 8 or more characters mixing letters and digits (a password without a digit or without a letter is not read) or a credential in its query, percent-encoded or not, JSON-escaped (`\u0026`, `\/`) or nested in another URL's parameter (two levels deep); a file that is a credential by its name, as `pack` refuses it (`.env`, `*.pem`, `*.key`, `.npmrc` and the rest), or a kit credential file (`*.token`, `board.credential`) |
| `instance-string` | a string from the owner's list, in a file, in a file's path or in a link's target |

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/fabric_source_check.py check <project-root>
```

- It **never repeats** a value it found: no value, no line holding one, no entry of the owner's list and not the
  folder it checks reaches its output. A file's path is checked like its text (line `0` of a finding), and printed
  with an entry of the list as `<line N>`, a home folder's name as `<home>` and each segment holding a
  credential-shaped value as `<secret>` (two files can then print the same; the segments a found value runs across, an
  assigned value, a bearer run or a URL, are masked too, while a key, a JWT or a JWK `d` is read up to the `/` that
  cuts it, so the rest of a cut one can print in the next folder: find the file by the folder the finding names); an instance string is named by its line in the owner's list. The report can go in a commit
  message, an issue or a chat.
- It **changes nothing.** Exit `0`: no finding and every file read; `1`: at least one finding (the step is not done);
  `2`: the check could not run, or a file was not read: an unreadable file, a nested repository, or a binary file the
  ignore file does not name as source (the summary counts each, and how many files were left out by name).
- **What it reads.** A text file of any size is read whole, and the summary counts every text file read; a binary file (a NUL byte in its first 8 KiB) or one that
  cannot be read is listed by its path as not read, and the summary counts it. A database or another binary of
  records in the tree is instance data the check cannot read: move it to the instance folder. A binary that is source
  (an icon, a font) is named in the ignore file. `--every-file` reads every file, those Git ignores included, but `.git`, `__pycache__`, `.DS_Store` and `*.pyc`
  (litter `pack` refuses): run it
  on a folder before `pack`, which carries them. A committed symbolic link is checked by the path it names, never followed. When the folder is
  not in a Git checkout, Git lists nothing in it, or no `git` is found in PATH's absolute folders (with PATH unset, in `/bin` and `/usr/bin`; on Windows, nowhere), every file is read but `.git` and `__pycache__` (uncounted) and the dependency
  folders (`node_modules`, virtual environments, caches), and the summary says Git was not used and how many dependency folders were not read.
  Under a locale whose file-system encoding is not UTF-8 (ISO-8859-1, KOI8-R) the check restarts itself in Python's UTF-8
  mode, so a file name, an argument and a file's text are read in one encoding; a name that is not UTF-8 is matched as its bytes.
  A file's text is read as UTF-8, so an entry of the owner's list with a letter outside ASCII is found in a UTF-8 file
  (composed or decomposed, as macOS may store a name), not in one saved as Latin-1 or CP1252.
  In Git mode a nested repository (a submodule, a vendored checkout) is not read: check a nested repository in its own tree with
  the same check (a submodule checked out first, `git submodule update --init`), then name its path in the ignore file,
  with that reason on the line above. That line serves the check of the outer tree only: before `pack`, check the
  nested repository with `--every-file` in its own tree too, because `pack` carries its files, ignored ones included.
- **The owner's list** holds the strings only the owner knows are theirs (their name, company, accounts, hosts), one
  per line, at least three characters; a line starting with `#` is a comment, so list a channel or a hashtag without its `#`, and a `#` after a string is
  part of that string. It is `--instance-strings FILE`, else the file
  `FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
  (`$XDG_CONFIG_HOME` when it is absolute, else `~/.config`; `%APPDATA%` on Windows). A list inside the tree is refused, because it would
  travel with the source. A person who already keeps private terms for org-index's `check_private.py`
  (`~/.config/passioncode/private-terms.txt`) passes that file with `--instance-strings`; this check matches a term
  anywhere in a word, and it does not look for e-mail addresses or account ids by their shape.
- **Leaving paths out.** `.fabric-source-ignore` at the root (globs, one per line, `#` comments) or `--exclude GLOB`
  leaves out files that hold synthetic values on purpose, such as test vectors. A line is a path from the root, not a
  `.gitignore` line (a leading `/` changes nothing, a line with no `/` matches at the root only, and a line holding `\`, `//`, an unclosed `[` or a class such as `[[:digit:]]` is refused, as Git reads each
  otherwise): `*`, `?` and `[...]` stay inside one folder (`?` and `[...]` match one byte, as Git's do, so a letter
  outside ASCII takes two or more) and `**` as a whole segment crosses
  folders, so `vectors/*` takes the files in `vectors` and none in its subfolders. A line ending in `/`, or a path
  with no wildcard, takes that folder and all it holds; only such a line leaves out a nested repository or a
  submodule (`vendor/sub/`), never a wildcard line without the `/` (`vendor/*`). A wildcard folder line (`vendor/*/`)
  takes every nested repository it reaches, checked or not, so name each one by its path. In Git mode a nested
  repository is not read; `--every-file` and a folder outside Git read its files, its `.git` left out. An exception line (`!`) is refused, since what it would
  bring back would go unread. Name the files, or a folder that holds
  only synthetic vectors, never a whole source folder (a nested repository checked in its own tree is the one
  exception), and say why on the line above. A file `pack` refuses by its name cannot ship in a package: a public
  certificate is renamed `*.crt`; a project `.npmrc` that holds no credential may be named in the ignore file, with
  that reason, for the source check (the line then hides whatever is added to it later, so keep it credential-free),
  and `pack` still refuses it, so a package is made from a copy without it (its
  settings then apply only where the owner sets them: `~/.npmrc` reaches every project of the owner, and
  `package.json`'s `publishConfig` carries publish-time settings such as `registry`, `tag` and `access`). A file
  holding a credential moves to the instance, never into the ignore file.
- A neutral home (`example`, `user`, `runner`, a container's, a cloud machine's or a dev container's user such as `node`, `ubuntu` or `vscode`, the fixture id
  `example-agent`, a
  one-letter name, a placeholder; the whole set is `NEUTRAL_HOMES` in the script. An owner whose home name is in it, a first name
  such as `alice` or an `admin` account, lists the home path in each form the tree may hold (`/Users/admin/`,
  `/home/admin/`, `-Users-admin-`, `C:\\Users\\admin\\`), never the bare name when it is a common word, since a
  listed string matches inside any word; a home name of one or two characters cannot be listed) and a value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) are
  not findings.

The check finds the forms the table names, and only those: a credential in another shape (a bare token with no name
before it, a provider's key the contract's names do not cover) passes it. It is a floor under the owner's review and a
secret scanner, never a replacement for either.

The check reads the tree, not Git history. A value that was committed once is still in the history after the tree is
clean: handing such a source over needs a fresh history, which is the owner's act, never the agent's (no history
rewrite, no force-push).
