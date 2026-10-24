# Packing, signing and verifying: `fabric-package/1`

Contract DEC-0050 (format and digest), DEC-0051 (signatures), DEC-0071 and DEC-0074 (a consumer agent), rules
`FAC-SEM-064`…`066` and `FAC-SEM-102`, all at this plugin's pin. The kit: `scripts/fabric_package.py` and
`scripts/fabric-package.mjs`, which write the same bytes, and `npx @passioncode-ai/fabric-agent-adapter pack|sign|verify`.

## Contents

- [What a package is](#what-a-package-is)
- [The author's file](#the-authors-file)
- [pack](#pack)
- [sign](#sign)
- [verify](#verify)
- [A consumer agent](#a-consumer-agent)
- [A partner's setup for a company](#a-partners-setup-for-a-company)
- [What this version does not do](#what-this-version-does-not-do)

## What a package is

One version of an agent or a skill set, as one folder: `fabric.package.json` at its root, every other file listed in it
with its SHA-256. The digest is SHA-256 over the RFC 8785 form of the document without `digest` and `signatures`, so it
covers every file through `files[]`, and a countersignature needs no repacking. A folder that is a Claude Code plugin
has `.claude-plugin/plugin.json` whose `name` and `version` are the package's `id` and `version`.

## The author's file

The person writes the descriptive part; `pack` fills in the rest.

| You write | `pack` writes |
|---|---|
| `schema` (`fabric-package/1`), `kind` (`agent` or `skill-set`), `id` (kebab-case, the plugin name), `version` (semver), `publisher` (a name, never a key), `licence` (SPDX) | `agentRef` = `urn:fabric:agent:<publisher>:<id>`, after `publisher` (an agent only; a hand-written one that differs is refused) |
| an agent: `resultSignal {name, says}`, `evals {suite, receipt {ranAt, suite, passed, failed, skipped?}}`, and as needed `provider`, `service`, `secrets[]` (slots: name and purpose, never a value), `requires`, `costPresets`, `state[]`, `dependencies[]` | `files[]`: every file but `fabric.package.json`, in UTF-16 order, each with `sha256:` and its hex digest |
| a skill set: `layer`, `skills` | `digest` |

The evals receipt's `suite` is the SHA-256 of the suite **as packed**. When the suite changes, run it again and write that
receipt; `pack` names the digest it expects. Never edit the receipt to match.

## pack

```bash
python3 scripts/fabric_package.py pack <folder>           # a dry run: the package, the digest, every problem
python3 scripts/fabric_package.py pack <folder> --apply   # writes fabric.package.json when nothing is wrong
```

It refuses to list what must not ship, and names each: a symlink, a special file, `.git`, `__pycache__`, `.DS_Store`,
`*.pyc`, and files that are credentials by name (`.env` and `.env.*` but `.env.example|sample|template`, `*.pem`, `*.key`,
`*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `id_rsa`-style keys, `.npmrc`, `.netrc`, `.pypirc`). Remove them or pack a clean
copy. A member named twice in `fabric.package.json` is refused too. A folder swapped for a link while it is read is refused as a
symlink. The Python kit reads each folder through an open handle, so a swap cannot redirect it. The Node kit has no
such call: it checks each folder before listing it, after each file it reads and after listing it (FAA-91), and does not
see a swap made and undone between two of those checks. Pack from a folder only you can write to.

Then every problem is listed, each with its `rule`: `schema` (the contract's schema), `FAC-SEM-064` (whole: its own
digest, each path once, every named file listed with the same SHA-256), `FAC-SEM-065` (no secret), `FAC-SEM-066`
(`agentRef` derived), `FAC-SEM-102` (one role, one server) and `folder` (`file-missing`, `file-digest`, `file-unlisted`,
`plugin-manifest`, `provider-manifest`) and `path` (a listed or folder path holding a control character, U+2028 or
U+2029, a `..` segment, a backslash, `//` or a colon, refused by the kit itself whatever the schema's pattern lets
through, FAA-78). A JSON document is read as strict UTF-8 and nested at most 256 levels; a folder entry the kit cannot
read is refused as `Cannot read <path>`, and a link, FIFO or other non-regular file is never followed. With a problem,
`--apply` writes nothing. Repacking drops old signatures and
says so: a changed package is signed again.

## sign

```bash
python3 scripts/fabric_package.py sign <folder> --key <key file> [--kid <kid>] [--role publisher|organization] --apply
```

- The key is a file the person names: an Ed25519 private JWK (`kty` OKP, `crv` Ed25519, `d`, its `kid`) or a PKCS#8 PEM
  from `openssl genpkey -algorithm ed25519` (then `--kid`). It must be mode 600. The kit never makes, keeps or prints a
  key; where the key lives is the person's decision (contract v4 D3).
- The signature covers `{"type": "fabric-package-signature/1", "role", "digest"}` in RFC 8785 form, so a publisher's
  signature never stands for a countersignature. `alg` is `EdDSA`, the one algorithm DEC-0051 admits.
- Only a package that is whole and matches its folder is signed. A publisher signature is always one (re-signing replaces
  it); an organization countersignature under the same `kid` is replaced, another is added.
- The answer carries `publicKey`, the public JWK the installing machine pins (the estate record's `publisherKeys`,
  DEC-0055). The package names a publisher, never a key.

## verify

```bash
python3 scripts/fabric_package.py verify <folder> --trust trust.json [--countersigned]
```

`trust.json` is `{"publisher": [jwk…], "organization": [jwk…]}`, the keys this machine pins. The verdict is the
contract's `verifyPackage`, in PK-1…PK-10's order: `malformed`, `digest-mismatch`, `unsigned`, `no-publisher-signature`,
then per signature `unknown-algorithm`, `unknown-key` / `duplicate-kid`, `key-algorithm-mismatch` / `unusable-key`,
`small-order-key` (checked before any verification, DEC-0045), `bad-signature`, and with `--countersigned`
`no-countersignature`. A countersignature under a key the machine does not pin is listed in `unverified` unless
`--countersigned` is asked; a bad one under a pinned key refuses the package. `verify` also runs the folder check and the
rules, so a file changed after signing is caught (`file-digest`, `file-unlisted`).

Exit codes for all three: 0 when it holds, 1 when it does not, 2 for a usage error. The answer is JSON on stdout.

## A consumer agent

An agent that serves nothing and only calls MCP servers is `kind: agent` without `provider` (DEC-0071). It lists its
`skills` and its plugin manifest, has no `service`, `state` or `layer`, and names the servers it calls in `requires.mcp[]`
by role and tools. A role names the secret slots that configure its server (`secrets`, DEC-0074), each declared in
`secrets[]`, one slot to one role. Before installing, `consumer_placement(pkg, configured)` / `consumerPlacement(pkg,
Map)` names each role the placement does not register and each tool its server lacks.

## A partner's setup for a company

A partner who builds agents for a company ships them without a new format (FAA-55, the partner channel's PA-07). Each
agent is its own `kind: agent` package. The setup is one `kind: skill-set` package at `layer: org`: the company's own
skills (house style, procedures), with `requires.packages` naming every agent it sets up by `publisher`, `id` and a
version `range`. The partner packs and signs every package with its own publisher key (`sign --key`); the company's
machine pins that key and `verify` refuses a package signed by any other. One signed package serves every company: what
differs per company (a display name, a brand, an address) is placement configuration, never a second package.

The company's estate record trusts the partner's key for that company only (DEC-0090): `publisherScopes[]` names the
key, the partner and the organization contexts, and `placement_trust` / `placementTrust` hand the key to a placement in
one of those contexts and to no other (FAC-SEM-122, [the estate record reference](estate-record.md)). The partner's own
agents call the company's agents with the partner innermost in the delegation chain ([delegation](delegation.md)).

Still to come, each waiting on its owner: a partner's own space in a catalog and publishing to it (FAA-44, Vesta
PA-03).

## What this version does not do

- **ES256.** It waits for Fabric's decision D2; until then a verifier refuses it as `unknown-algorithm` (FAA-29).
- **Hub signing for the person's own machines, and the passkey.** Stage 3 of target architecture v4.
- **The organization's countersignature as a passkey assertion.** It waits for `org-countersign/1` and
  `org-authority/1`; this version's countersignature is a detached Ed25519 signature.
- **Fabric recording packages by `agentRef`.** It waits for the ADR-0138 D2b amendment.
- **`publish --to org`** (FAA-28; an organization cloud's import API is FAA-63, under FAA-28's rule that publishing to
  an organization is the person's own act).
