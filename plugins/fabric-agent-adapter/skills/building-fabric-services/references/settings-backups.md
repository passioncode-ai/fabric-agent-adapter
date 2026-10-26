# Settings backups: what the operator decided survives the data directory (DEC-0025)

Fabric Agent Contract DEC-0025, `docs/specification/service.md` → *Settings backup*, schema
`schemas/settings-backup.schema.json`, rule `FAC-SEM-035`. A service whose store holds what the operator
decided (which projects it serves, how each is bound, which secret slot each binding uses, their overrides)
SHOULD keep settings backups, so a lost, purged or wrongly migrated data directory costs the operator nothing.

## Where

`<root>/settings-backups/<id>/<instance>/settings-<UTC %Y%m%dT%H%M%S%fZ>.json`, outside the data directory:

| System | `<root>` (`settings_backup_root` / `settingsBackupRoot`) |
|---|---|
| macOS | `~/Library/Application Support/PassionCode` |
| Windows | `%APPDATA%\PassionCode` |
| Linux | `$XDG_CONFIG_HOME/PassionCode`, default `~/.config/PassionCode` |

`settings_backup_dir(id, instance)` / `settingsBackupDir(id, instance)` names the folder. Directories are 0700
(on Windows a protected ACL), files 0600, writes atomic.

## Take a snapshot

```python
dirs = fs.settings_backup_dir(ID, INSTANCE)
if fs.backup_due(dirs):                                   # none yet, or the newest is older than 24 hours
    doc = fs.make_settings_backup(service_id=ID, instance=INSTANCE, version=VERSION, schema=SCHEMA_VERSION,
                                  tables=allow_listed_tables(db), reason="start")      # or daily, uninstall, manual
    fs.write_settings_backup(doc, dirs)                   # None when unchanged; keeps the 14 newest
```

```js
const dir = k.settingsBackupDir(ID, INSTANCE);
if (k.backupDue(dir)) k.writeSettingsBackup(k.makeSettingsBackup({ id: ID, instance: INSTANCE, version, schema, tables, reason: 'daily' }), dir);
```

- **Tables on an allow-list**, each `{"columns": [...], "rows": [[...], ...]}` of JSON scalars. A fraction is its
  decimal string (`"0.25"`), binary data is never stored, and an integer stays within ±(2^53 − 1).
- **Secrets by name only.** `make_settings_backup` refuses a table that can only hold connections, tokens,
  secrets, credentials, passwords, login codes or sessions, and a column whose name says it holds a credential
  value (`access_token`, `client_secret`); `secret_name` and `token_slot` pass. The names cannot see values, so
  back up what is on the allow-list, never everything except a deny-list.
- **When:** at start when `backup_due`, then daily; on uninstall a last one, read-only (open the store without
  migrating or writing). An unchanged snapshot is not rewritten; a temporary file an interrupted write left is
  removed first. A fresh, empty database writes none: it would hide the good snapshot before it is restored.
- Both kits write byte-identical files (`test/fabric-service-backups.test.mjs`, last case).

## Read and restore

`read_settings_backup` / `readSettingsBackup` refuses a file whose checksum, counts or row widths disagree with
its tables, that carries a value with no canonical form, or whose `format` it does not know, naming why
(`FAC-SEM-035`). The checksum is SHA-256 of the settings canonical form of `tables`
(`settings_canonical_json` / `settingsCanonicalJson`: Python's `json.dumps(sort_keys=True,
ensure_ascii=False)`).

Restore **adds and never overwrites**:

```python
path, doc, skipped = fs.newest_intact_backup(dirs)        # the newest intact snapshot with content; damaged ones named
plan = fs.restore_plan(doc, {"projects": {"columns": [...], "key": ["id"], "required": ["id", "name"],
                                          "existing": existing_keys("projects")}})
# plan["tables"]["projects"]: insert, present, droppedColumns, defaultedColumns, missingRequired, refused
```

- **Automatic restore** only on a *fresh* database (no domain records **and** the service has never started),
  so a restart never undoes a deletion. Insert `plan[...]["insert"]` and add every row the database refuses to
  `refused` with its key and reason.
- **Manual restore** shows the plan first; applying it is the operator's decision, taken on the page or relayed by
  their agent with `_meta.decision` (a restore is a `relayed` action, contract DEC-0121), never the agent's own act.
