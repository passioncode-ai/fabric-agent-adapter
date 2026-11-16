# The source and the instance

An agent is two things. Its **source** is what can be handed to someone else: code, skills, prompts, schemas,
examples, the source documentation. Its **instance** is what belongs to one installation: records, logs, journals,
keys, the owner's names and paths, accounts, hosts and its configuration. A new agent keeps the two apart from its
first commit, so that its owner can hand the source over later without rewriting its history. Nothing is handed over
by itself: handing over, a new remote, a push or a change of visibility stays the owner's act, each time (a personal
agent stays private until its owner says so about that act).

The format of a source manifest, export and import is the contract's: DEC-0149 (`fabric-source/1`, its `source.md`) at
the pin. The kit lays down `fabric.source.json` ([the source manifest](#the-source-manifest)), and the check reads the
source under it.

## Contents

- [The layout](#the-layout)
- [The data home and its kind](#the-data-home-and-its-kind)
- [The source manifest](#the-source-manifest)
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
  `!config/*.example.json`), an instance folder an existing project still keeps inside the checkout, and what running
  the agent leaves (`__pycache__/`, `*.pyc`), which the check would otherwise report as binary in Git mode.
- **State documents are instance data.** A handoff, a decision log or a backlog about this codebase is source
  documentation; a record of what this installation did (runs, conversations, the owner's notes, a journal) lives in
  the instance folder.
- **Keys by name.** The README's Configure section lists key names, the agent reads each from its environment or the
  secret store, and no value is ever written to a file, a fixture, an argument or a commit.
- **Fixtures on neutral ids.** A test that needs a home folder, an owner or an account uses `example`, `example-agent`,
  `owner@example.com` or a one-letter home, and a credential-shaped test value says it is synthetic
  (`sk-test-not-a-key`) or is assembled at run time.
- **Two names are slots, never values (DEC-0149, FAA-188 part 2).** A service's supervisor label is the agent's own
  name, reverse-DNS on the publisher's domain (`com.example.example-agent`), and `AGENTS.md` names it (LC-09): never the
  owner's account or name; the label an installation runs under is its `SUPERVISOR_LABEL` slot, with its port in
  `SERVICE_PORT`. A provider's `createdBy` names the publisher; the source keeps the scaffold's sentinel, and the
  publisher's URI is the installation's `PUBLISHER_URI` slot, so a person's name or account is never written there.

## The data home and its kind

- **The data has a home of its own from the first commit: `<agent>-data`.** For an agent that is not a kit service it
  is a folder beside the checkout, never inside it, and `<AGENT>_DATA_DIR` names it (its default is
  `../<agent>-data`, resolved against the checkout's root, the folder that holds the agent's source, never the working
  directory). Two sibling checkouts, and a second context's instance from the same checkout (an organization's beside
  the personal one), would share that default: each sets its own `<AGENT>_DATA_DIR` (`../<agent>-data.<instance>`), so
  no copy reads another's data. A kit service keeps the kit's folders above, and on a host whose disk does not persist
  `FABRIC_DATA_HOME` moves its data folder onto a durable volume (building-fabric-services, the remote placement). When the owner keeps the data in Git, it goes to a
  separate private repository named `<agent>-data`, never to the source's repository. On a cloud host that does not
  keep its disk across a restart (Heroku and the like, an uptime A agent's default), the data home is a durable store
  the same variable names (a database, an object store, that private repository); the folder and the kit's folders
  serve a machine whose disk persists. A copy of the agent starts with an empty home of its own and never connects
  to the original's.
- **The README names the kind of the data.** **U**: the agent keeps data of people outside the owner's team
  (messages, support requests, reviews, customers' answers); it never enters the source, a copy or its tests, and the
  source holds only the schema and synthetic fixtures (its real-trace corpus and replay samples live in the data
  home). **O**: it keeps none (a tool or service for other agents, the
  owner's reports, runs and media); its working data still goes to the data home. When in doubt, the kind is U.
- **Every release runs the transfer audit.** `fabric_source_check.py check <project-root>` in Git mode, and
  `check <clean-copy> --every-file` on a clean copy of what Git would commit (`git ls-files --cached --others
  --exclude-standard`, as building-fabric-services' `references/package.md` makes it; never the checkout itself, whose ignored
  configuration and dependency folders `--every-file` reads too), each exit 0, with the owner's list or its absence recorded, until the contract's export (CT-194)
  replaces it.

## The source manifest

`fabric.source.json` at the source's root says what is source and which slots an installation fills, never a value
(DEC-0149, `fabric-source/1`):

| Member | What |
|---|---|
| `include` | the source, default deny: a file outside every entry is not source; an entry ending in `/` is a folder, no globs |
| `exclude` | holes in `include`, read in any letter case and Unicode form (a file an entry names only in another spelling is left out, and the check says `excluded-by-fold`) |
| `binaries` | the binary files that are source (an icon, a font); another binary blocks |
| `unchecked` | source paths that travel unread, each with its reason (synthetic test vectors, a licence naming a holder on the owner's list) |
| `publicAddresses` | the e-mail addresses the source may carry (a support address); another one warns |
| `slots` | what an installation fills, by name: `secret` (a key), `config` (a setting: a repository URL, a folder, the supervisor label, the publisher's identity), `store` (a data store, with its path in the data folder), `endpoint` (the operator's infrastructure by role) |

- **Laying it down.** A new agent gets it from `new_agent.py` (creating-fabric-agents' `references/new-agent.md`); an
  existing project from `adapt_project.py source <project-root>` (adapting-projects-to-fabric's scripts), which proposes `include` from the
  project's top-level entries (what Git would commit, instance data by its name left out) and names the kit's slots
  (`PUBLISHER_URI` where a provider manifest is there, `PLACEMENT_RECORD`, and with `--service` `SUPERVISOR_LABEL` and
  `SERVICE_PORT`); `--secret NAME:PURPOSE` and `--store NAME:PATH:PURPOSE` add the agent's own. `--dry-run` prints the
  proposal and writes nothing; an existing manifest is the owner's and is replaced only with `--force`. The author then
  narrows `include` to what is source.
- **The check under it.** When the folder it checks holds `fabric.source.json`, `fabric_source_check.py check` reads
  the source the manifest names and reports the contract's kinds (`fabric_source_tree.py`, held to the contract's
  vectors): blocking `home-path`, `credential`, `binary`, `nested-repository`, `instance-string`, `missing`,
  `no-include` and the manifest's own findings (FAC-SEM-156, FAC-SEM-157); warnings `email`, `link-outside`,
  `no-license`, `unused-exclude`, `excluded-by-fold`, each by path, line and column (UTF-16 units), never by the text
  found. Exit 1 on a blocking finding, 0 when only warnings remain and every source file was read, 2 when one was not.
  `.fabric-source-ignore` and `--exclude` are not read there: `exclude` and `unchecked` say it. A declared home
  (`home: <name>`) is still found in every source file.
- **Packing it.** `pack` (building-fabric-services' `references/package.md`) writes the package's `secrets[]` from the secret slots and `state[]` from the store slots' paths, and refuses a
  package whose members differ (FAC-SEM-160); an empty `state[]` is a copy packed without state, and stays so. A
  hand-written `secrets[]` naming a secret the manifest has no slot for is refused by name, never dropped.
- **Handing it over** stays the owner's act, each time, on their word for that act (the contract's `source.md`,
  Handing over).

## The check

`fabric_source_check.py check` reads the files the source would carry (what Git would commit: tracked files and
untracked ones that are not ignored, as they are in the work tree, and a staged copy that differs from it) and reports each place where the instance shows through, by path, line and kind:

| Kind | Finds |
|---|---|
| `home-path` | an absolute path inside a person's home folder (a root-relative web route under `/home/` is reported too, one after a host is not; a route under `/users/` is not): `/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>\`, Git Bash's `/c/Users/<name>/`, WSL's `/mnt/c/Users/<name>/`, and the dashed (`-Users-<name>-`, `C--Users-<name>-`) and URL-encoded forms a tool makes of one; and, read by this check beside the contract's forms, one after a `file` URL's host (`file://localhost/Users/<name>/`), in VS Code's `vscode://file/Users/<name>/`, after a drive whose colon is percent-encoded (`file:///c%3A/Users/<name>/`), with its slashes JSON-escaped (`\/`, `\\/`, `\u002f`), and after a doubled prefix (`C:\Users\C:\Users\<name>\`) (FAA-190, `test_a_home_after_a_file_url_host_is_found`, `test_a_json_escaped_home_path_is_found`). The name is ASCII, and in the dashed form it ends at the next dash: an owner whose home name holds a space, a dash, a dot, an underscore or an apostrophe (each a dash in the dashed form; a slashed name also ends at a space) declares it with `home: <name>` in the owner's list, which reads it whole in every form, and one whose home name is not ASCII, or holds another character, lists it as a plain string (a typographic apostrophe a keyboard typed, which the folder's name does not hold, is written as `'` in `home:`; a folder whose name holds `’` is listed as a plain string with `’` kept and declared too with `home: <name>` written with `'`, which reads the dashed forms; its URL-encoded `’` is not read; a name outside ASCII of one or two characters cannot be checked) |
| `secret` | a value shaped like a credential by the contract's detector (DEC-0044), read line by line: a provider key starting a word, a JWT, a bearer token, a long random value assigned to a credential's name (a run of 40 or more characters mixing upper case, lower case and digits, so a shorter key under `X_API_KEY=` is not read; but a whole Ed25519 signature under a JSON `"sig"`, `"signature"` or `"signatures"` member, as `sign` writes it, which is public); or a private key: a PEM, OpenSSH or PGP block, or a JWK's `d` as a JSON member, escaped JSON or a Python dict, and on a line that names `kty` a `d` or a symmetric JWK's `k` under a key quoted or not (a JS object, YAML flow; a YAML JWK across lines is not read); a URL with a password of 8 or more characters mixing letters and digits (a password without a digit or without a letter is not read) or a credential in its query, percent-encoded or not, JSON-escaped (`\u0026`, `\/`), nested in another URL's parameter (four levels deep) or in its path (`<https>://proxy/<https>://app:<password>@db/`), written without its `//` (`<https>:app:<password>@db`) or percent-encoded whole (`<https>%3A%2F%2F...`); a long random value under a credential's name that holds an `=` inside it (`<24>=<30>`); a file that is a credential by its name, as `pack` refuses it (`.env`, `*.pem`, `*.key`, `.npmrc` and the rest), or a kit credential file (`*.token`, `board.credential`); and a folder named so anywhere in a file's path (`k.pem/a.txt`), which `pack` refuses too (FAA-190, `test_a_folder_named_like_a_credential_file_is_a_finding`) |
| `instance-string` | a string from the owner's list, in a file, in a file's path or in a link's target |

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/fabric_source_check.py check <project-root>
```

Run it by path, with its scripts folder whole: it loads its siblings (`fabric_source_ignore.py`,
`fabric_source_homes.py`, `fabric_source_restart.py`, `fabric_source_list.py`, `fabric_source_redact.py`,
`fabric_source_check_cli.py`, `fabric_source_tree.py`, the
way it runs Git `fabric_git.py` and the contract's detector `fabric_secrets.py`) and refuses with exit `2` when one is missing or from another version, a
detector without one of the public names it reads included, or when its folder can be searched but not listed (mode
`311`, an import lists it; FAA-190, `test_an_unlistable_scripts_folder_is_named`). `python3 -m fabric_source_check` writes its own
`.pyc` before the check turns bytecode off; run by path, it writes nothing. `ROOT` defaults to the current folder.
`--json` prints one object: `mode` (`git` or a walk), `files`, `findings` (`path`, `line`, `kind`, `rule`),
`notRead`, `skipped`, `dependencies`, `unmatched` (the ignore lines that match no file, by their place),
`instanceStrings`, `ownerHomes`, `instanceList`, `blocking` (a finding) and `complete` (every file read); `--help`
names each option.

- It **never repeats** a value it found: no value, no line holding one, no entry of the owner's list and not the
  folder it checks reaches its output. A file's path is checked like its text (line `0` of a finding), and printed
  with an entry of the list as `<line N>`, a home folder's name as `<home>` and each segment holding a
  credential-shaped value as `<secret>` (two files can then print the same; the segments a found value runs across, an
  assigned value, a bearer run or a URL, are masked too, and a key, a JWT or a JWK `d` cut by a `/` masks the next folder,
  its rest, and the ones after it while they hold only a key's characters: find the file by the folder the finding
  names, `test_a_key_cut_by_a_slash_prints_no_part`); a path as printed, with its marks, is read once more, so a mark
  that takes away a synthetic word beside a value never leaves that value printed
  (`test_the_printed_path_holds_no_finding_after_marks`). An instance string is named by its line in the owner's list,
  and once found in a file, any 8 characters of it in another printed path print as that line's mark. The report can
  go in a commit message, an issue or a chat. A home name found in the tree is masked wherever a printed path holds
  it, its dotted, underscored or dashed parts of three or more characters too (`<name>.CORPORATE` masks `CORPORATE`)
  and without a trailing `.` or `_`; a name of three characters or fewer, found or declared, only as a word, with no
  ASCII letter or digit beside it (`bo` masks `src/bo/` and leaves `robot` readable, `home: qz` leaves `qzone`;
  `test_a_short_found_home_is_masked_only_as_a_word`); a declared home of one or two letters found nowhere is not
  masked. A URL found leaves only its credential (its password, a query value) to mask other paths with, so a path
  sharing its host prints whole.
- It **changes nothing.** Exit `0`: no finding and every file read; `1`: at least one finding (the step is not done);
  `2`: the check could not run, or a file was not read: an unreadable file, a nested repository, or a binary file the
  ignore file does not name as source (the summary counts each, and how many files were left out by name); or it
  found no file at all, read or left out by name, as in a submodule not checked out, which is an empty folder (the
  summary says `no file read`; `test_a_tree_with_no_file_read_is_incomplete`). A finding
  sets `1` even when a file was not read too; the files not read are still listed, so fixing the findings can leave `2`.
- **What it reads.** A text file of any size is read whole, and the summary counts every text file read; a binary file (a NUL byte in its first 8 KiB) or one that
  cannot be read is listed by its path as not read, and the summary counts it. A database or another binary of
  records in the tree is instance data the check cannot read: move it to the instance folder. A binary that is source
  (an icon, a font) is named in the ignore file. `--every-file` reads every file, those Git ignores included, but `.git`, `__pycache__`, `.DS_Store` and `*.pyc`
  (litter `pack` refuses): run it
  on a folder before `pack`, which carries them. A committed symbolic link is checked by the path it names, never followed. When the folder is
  not in a Git checkout, Git lists nothing in it, or no `git` is found in PATH's absolute folders (with PATH unset, in `/bin` and `/usr/bin`; on Windows, nowhere), every file is read but `.git` and `__pycache__` (uncounted) and the dependency
  folders (`node_modules`, virtual environments, caches; a folder holding `pyvenv.cfg` is a virtual environment
  whatever its name, `test_a_folder_with_pyvenv_cfg_is_a_dependency_folder`), and the summary says Git was not used and
  how many dependency folders were not read; that walk stands in for what Git would commit, so it reads `.DS_Store` and
  `*.pyc` (as binary files not read, exit `2`) where `--every-file` leaves them out. In Git mode the staged copy of a
  file whose index differs from the last commit is read too when it differs from the work tree, since a plain `git
  commit` takes it: its findings say `in its staged copy` (`test_a_value_only_in_the_staged_copy_is_found`). It is
  read as Git stores it (`diff --cached`, `cat-file`), so no clean filter the tree's configuration names runs.
  Under a locale whose file-system encoding is not UTF-8 (ISO-8859-1, KOI8-R) the check restarts itself in Python's UTF-8
  mode, so a file name, an argument and a file's text are read in one encoding; a name that is not UTF-8 is matched as its bytes.
  A file's text is read as UTF-8, so an entry of the owner's list with a letter outside ASCII is found in a UTF-8 file
  (composed or decomposed, as macOS may store a name), not in one saved as Latin-1 or CP1252. An entry without an accent
  does not find a name written with one (`jose` does not find `josé`, composed or decomposed): list both spellings.
  On Windows a tracked name that is not UTF-8 (committed elsewhere) is listed as not read, since no Windows work tree can
  hold it. After the UTF-8 restart a name that is not UTF-8 prints as its own bytes, as the console's locale shows them.
  In Git mode a nested repository (a submodule, a vendored checkout) is not read: check a nested repository in its own tree with
  the same check (a submodule checked out first, `git submodule update --init`), then name its path in the ignore file,
  with that reason on the line above. That line serves the check of the outer tree only: before `pack`, check the
  nested repository's files as the clean copy carries them too, `check <clean>/<nested> --every-file` on the clean copy
  ([the package reference](../../building-fabric-services/references/package.md)), because `pack` carries its files;
  `--every-file` in the nested repository's own tree would also read what the clean copy never carries (its
  dependency folders and ignored files).
- **The owner's list** holds the strings only the owner knows are theirs (their name, company, accounts, hosts), one
  per line, at least three characters; a line starting with `#` is a comment, so list a channel or a hashtag without its `#`, and a `#` after a string is
  part of that string. An entry matches in any case and inside any word; an invisible format character (a direction mark, a
  soft hyphen, a joiner) or another default-ignorable character (a variation selector, U+034F) at either end of a
  string is dropped, spaces between such characters too, and does not count toward the three; a joiner inside it
  (U+200C, U+200D: an emoji or a Persian word needs one) is kept and counts, and a soft hyphen, a zero-width space, a
  word joiner or a direction mark inside it refuses the line, exit 2, since a file's text is compared without those
  (a listed `zqcorpx` finds `zq&shy;corpx` once a page turns it into U+00AD;
  `test_a_soft_hyphen_inside_a_listed_string_in_a_file_is_found`). A line `home: <name>` declares the owner's home
  name instead (ASCII letters, digits, `.`, `_`, `-`, `'` and spaces, starting with a letter or a digit; a name holding a
  space, as a Windows profile may, is written whole, `home: Jane Doe`, and everything after the colon is the name, so
  a note goes on a line of its own (`# laptop`); spaces and tabs may stand around the colon; a line
  that starts with `home` and a colon and holds anything else is refused, exit 2 (an invisible format character before
  the name, after it or inside `home` is dropped, one inside the name refuses the line; a NUL anywhere in the list
  refuses it too); such a line is never a string
  entry, so list a string like `home: page` by a part of it, `ome: page`): the check then finds that home in every form the table names (it is never neutral, even with one or two
  letters), and the bare name is not looked for anywhere else, though a declared name of three or more letters and digits is
  masked wherever a printed path holds it as a word (so `home: admin` prints `admin-panel/.env` as `<home>-panel/.env`
  even when no home of that name is found: the declared name is the owner's own), its parts joined by none or any run of a space, `.`, `_`, `-`, `+`, `'`, their
  percent-encodings or an escaped apostrophe (`\'`, `\x27`, `\u0027`, `&#39;`, `&#x27;`, `&apos;`), the same separators it is found with in every form; a home that is also your name goes in the list
  as a plain string too, to be found in text. It is `--instance-strings FILE`, else the file
  `FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
  (`$XDG_CONFIG_HOME` when it is absolute, else `~/.config`; on Windows `%APPDATA%` when it is absolute, else `~\AppData\Roaming`). A list inside the tree is refused, because it would
  travel with the source. A person who already keeps private terms for org-index's `check_private.py`
  (`~/.config/passioncode/private-terms.txt`) passes that file with `--instance-strings`; this check matches a term
  anywhere in a word, and it does not look for e-mail addresses or account ids by their shape. Two more differences, as
  org-index's `scripts/check_private.py` reads its terms at `2c8dda9`: it splits its file with `splitlines` (a form
  feed or U+2028 also ends a term there, never here) and matches with `re.IGNORECASE`, so its `istanbul` finds
  `İSTANBUL`, which a casefolded comparison here does not (U+0130 folds to `i` and a combining dot). Keep `home:` lines
  in this check's own list, never in a terms file the two share: `check_private.py` reads such a line as a literal
  term.
- **Leaving paths out.** `.fabric-source-ignore` at the root (globs, one per line, `#` comments) or `--exclude GLOB`
  leaves out files that hold synthetic values on purpose, such as test vectors. A line is a path from the root, not a
  `.gitignore` line (a leading `/` changes nothing, a line with no `/` matches at the root only, and a line holding `\`, `//`, an unclosed `[` or a class such as `[[:digit:]]` is refused, as Git reads each
  otherwise): `*`, `?` and `[...]` stay inside one folder (`?` and `[...]` match one byte, as Git's do, so a letter
  outside ASCII takes two or more) and `**` as a whole segment crosses
  folders, so `vectors/*` takes the files in `vectors` and none in its subfolders. A line ending in `/`, or a path
  with no wildcard, takes that folder and all it holds; only such a line leaves out a nested repository or a
  submodule (`vendor/sub/`), never a wildcard line without the `/` (`vendor/*`). A wildcard folder line (`vendor/*/`)
  takes every nested repository it reaches, checked or not, so name each one by its path. A submodule that is not
  checked out (no folder) is still a folder to these lines: `vendor/sub/` and `vendor/sub` take it, `vendor/*` does
  not (`test_an_absent_submodule_named_with_a_slash_is_left_out`). In Git mode a nested
  repository is not read; `--every-file` and a folder outside Git read its files, its `.git` left out. An exception line (`!`) is refused, since what it would
  bring back would go unread. A line that matches no file is named in the summary by its place (`line 3 of
  .fabric-source-ignore matches no file`), never by what it holds, and is no failure: a reason written after a glob on
  the same line makes the line match nothing, so the reason goes on the line above. A line costs time in proportion to
  the path it is matched against, however many `*` and `**` it holds, as Git's own matching does
  (`test_many_stars_in_a_segment_stay_fast`, `test_many_double_stars_on_a_deep_path_stay_fast`). On macOS a name and a
  line are matched in their composed form (NFC), so a folder stored decomposed is taken by the same line in Git mode
  and with `--every-file` (`test_an_nfd_folder_matches_the_same_ignore_line_in_both_modes`). Name the files, or a folder that holds
  only synthetic vectors, never a whole source folder (a nested repository checked in its own tree is the one
  exception), and say why on the line above. The one owner's file named this way is the `LICENSE` (a file, never a
  folder exception): its copyright line names the holder, which is
  authorship and travels with the source, so when the holder is on the owner's list the licence file is named in the ignore
  file by its own path (`LICENSE`, `LICENSE.md`) with that reason (`# the copyright holder is authorship and travels with the source`); no other file of the
  owner's is. A file `pack` refuses by its name cannot ship in a package: a public
  certificate is renamed `*.crt`; a project `.npmrc` that holds no credential may be named in the ignore file, with
  that reason, for the source check (the line then hides whatever is added to it later, so keep it credential-free),
  and `pack` still refuses it, so a package is made from a copy without it (its
  settings then apply only where the owner sets them: `~/.npmrc` reaches every project of the owner, and
  `package.json`'s `publishConfig` carries publish-time settings such as `registry`, `tag` and `access`). A file
  holding a credential moves to the instance, never into the ignore file.
- A neutral home (`example`, `user`, `runner`, a container's, a cloud machine's or a dev container's user such as `node`, `ubuntu` or `vscode`, the fixture id
  `example-agent`, a
  one-letter name, a placeholder; the whole set is `NEUTRAL_HOMES` in the script. An owner whose home name is in it, a
  first name such as `alice` or an `admin` account, or has one or two letters, writes `home: <name>` in the owner's
  list; a container's, a cloud image's or a CI runner's user that only the image uses, such as `node` or `vscode`, is never declared, since
  its paths are the image's and stay in the source; the home of the owner's own machine is declared even when its
  name is an image's user, as `admin` or `ubuntu` on a cloud machine the owner works on; when that name is also the
  user of an image in the tree, the image's paths are reported, and they are written through a build argument that
  names the user, `ARG APP_USER=ubuntu`, `USER ${APP_USER}`, `WORKDIR /home/${APP_USER}/app`, so no home path stands
  in the source; `$HOME` serves only where a shell in the image expands it, a `RUN` line or a script, since a
  Dockerfile's `WORKDIR` and `COPY` see only `ENV` and `ARG` values) and a value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) are
  not findings.

The check finds the forms the table names, and only those: a credential in another shape (a bare token with no name
before it, a provider's key the contract's names do not cover, a key glued to a letter outside ASCII, which the
contract's word start counts as a letter) passes it. A home name outside ASCII is the owner's list's to find, as a
plain string. Some text that is not a credential or a home reads as one, and fails closed: the shapes are the
contract's (`src/source-rules.ts` at the pin, which a tree under a manifest is checked with), so they change there
first (FAA-190): a route whose first segment is one letter before a `Users` segment (`app.get("/v/Users/<route>")`), a
one-letter flag or block before `-Users-` (`ls -a-Users-<name>`, `class="a--Users-<block>"`, `#a--users-<anchor>`), a
WebAuthn assertion's `sig` or a passkey's `credentialId` under its name (instance data in any case: a recorded
assertion belongs to one installation), a placeholder password with a digit in a URL (`password1`, `changeme123`),
dotenv's vault URL (`<dotenv>://:key_...@dotenv.org/vault/...`), and a search URL whose query holds a key's prefix or
starts with `bearer` (`?q=desk-lamp-with-long-arm-shade`, `?q=bearer%20bonds`). Name such a file in the ignore file
with its reason. It is a floor under the owner's review and a
secret scanner, never a replacement for either.

The check finds the repository from the folder it checks: a Git location the caller exports (`GIT_DIR`,
`GIT_WORK_TREE`, `GIT_INDEX_FILE` and the rest, as a hook in a linked worktree has two) is not passed to Git, nor are
its discovery limits (`GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM`), so a ceiling at or above the
repository's top does not turn the folder into one outside Git (`test_a_git_ceiling_does_not_switch_to_the_walk`). So a work
tree Git finds only through those variables (a bare repository with a separate work tree) is read with the walk, every
file but the dependency folders; give that folder a `.git` file (`gitdir: <the repository>`) for Git mode. In a
pre-commit hook the check reads the repository's own index, not the one the commit is building: a file deleted with
`rm` and committed with `git commit -a` is still listed there and reads as not in the work tree (exit `2`), so stage a
deletion with `git rm` first. Git runs through `fabric_git.py`, as every script of the adapter runs it: from PATH's
absolute folders but never one inside the checked tree (`npm run` puts `<root>/node_modules/.bin` there,
`test_a_git_inside_the_checked_tree_is_not_run`), with `core.fsmonitor` empty and Git for Windows'
`core.useBuiltinFSMonitor` false, so no command the tree's configuration names runs and Git's own daemon is not started
(`test_git_runs_no_command_the_checked_tree_configures`, `test_the_builtin_fsmonitor_daemon_is_not_started`), and
with `GIT_TRACE*` not passed and the trace2 targets off, so it writes no trace (`test_git_trace_is_not_passed`). An
empty `core.fsmonitor` is boolean false from Git 2.36 and no hook before it (Git's `config.c`); the suite runs on the
Git the machine has, and no hosted job pins one older than 2.36. The caller's own Git configuration still applies: its
global excludes file decides what is ignored, as it does for what that caller would commit. The check reads the tree, not Git history. A value that was committed once is still in the history after the tree is
clean: handing such a source over needs a fresh history, which is the owner's act, never the agent's (no history
rewrite, no force-push).
