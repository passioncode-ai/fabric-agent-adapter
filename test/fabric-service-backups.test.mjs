// Settings backups, the feed client's token header and every spending limit in the usage report — contract DEC-0025
// and DEC-0027 in the Node kit (FAA-13); the twin of test_fabric_service_backups.py. The last case holds the two kits
// to byte-identical backup files.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/dec-0025-0027', `${name}.json`), 'utf8'));
const temp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-backup-'));
const NOW = Date.UTC(2026, 9, 5, 2, 0, 0, 123);
const DAY = 86_400_000;
const TABLES = {
  projects: { columns: ['id', 'name', 'archived'], rows: [['p-001', 'Quarterly report', false], ['p-002', 'Board memo', true]] },
  secret_bindings: { columns: ['project_id', 'slot', 'secret_name'], rows: [['p-001', 'llm', 'EXAMPLE_LLM_KEY']] },
};
const backup = (tables = TABLES, now = NOW, reason = 'daily') => k.makeSettingsBackup({ id: 'example-agent', instance: 'default', version: '0.4.0', schema: 7, tables: structuredClone(tables), reason, now });
const has = (problems, needle) => problems.some((p) => p.includes(needle));

test('the canonical form matches the contract vectors and refuses what has none', () => {
  const vectors = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/canonical.json'), 'utf8')).settings.vectors;
  let ran = 0;
  for (const v of vectors.filter((x) => 'expected' in x)) {
    assert.equal(k.settingsCanonicalJson('inputJson' in v ? JSON.parse(v.inputJson) : v.input), v.expected, v.name);
    ran += 1;
  }
  assert.ok(ran > 2);
  for (const value of [0.5, 2 ** 53, -(2 ** 53), Number.NaN, { a: undefined }, new Date(0)]) assert.throws(() => k.settingsCanonicalJson(value), k.ServiceError);
  const refuses = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/canonical.json'), 'utf8')).settings.refuses;
  assert.ok(refuses.length >= 7);
  for (const v of refuses) assert.throws(() => k.settingsCanonicalJson('inputJson' in v ? JSON.parse(v.inputJson) : v.input), k.ServiceError, v.name);
  const positive = fixture('positive-settings-backup');
  assert.equal(k.settingsBackupDigest(positive.tables), positive.sha256);
});

test('the contract backup fixtures', () => {
  assert.deepEqual(k.settingsBackupProblems(fixture('positive-settings-backup')), []);
  for (const [name, needle] of [['negative-settings-backup-account-connections', 'account_connections'], ['negative-settings-backup-fraction', 'FAC-SEM-035'],
    ['negative-settings-backup-no-checksum', 'sha256'], ['negative-settings-backup-token-column', 'access_token'],
    ['negative-settings-backup-wrong-format', 'format'], ['semantic-settings-backup-bad-checksum', 'FAC-SEM-035 /sha256']]) {
    assert.ok(has(k.settingsBackupProblems(fixture(name)), needle), name);
  }
});

test('counts, widths and surrogates', () => {
  let doc = backup();
  doc.counts.projects = 3;
  assert.ok(has(k.settingsBackupProblems(doc), '/counts/projects'));
  doc = backup();
  doc.counts.ghost = 0;
  assert.ok(has(k.settingsBackupProblems(doc), 'ghost'));
  doc = backup();
  doc.tables.projects.rows[0].push('extra');
  assert.ok(has(k.settingsBackupProblems(doc), 'row has 4 values for 3 columns'));
  doc = backup();
  doc.tables.projects.rows[0][1] = 'lone \ud800';
  assert.ok(has(k.settingsBackupProblems(doc), 'surrogate'));
});

test('make writes counts, the checksum and the time; refuses what a backup never holds', () => {
  const doc = backup();
  assert.equal(doc.created_at, '2026-10-05T02:00:00.123000Z');
  assert.deepEqual(doc.counts, { projects: 2, secret_bindings: 1 });
  assert.equal(doc.sha256, k.settingsBackupDigest(doc.tables));
  assert.deepEqual(k.settingsBackupProblems(doc), []);
  for (const tables of [{ operator_sessions: { columns: ['id'], rows: [] } }, { bindings: { columns: ['id', 'client_secret'], rows: [] } },
    { prices: { columns: ['id', 'usd'], rows: [['a', 0.5]] } }]) {
    assert.throws(() => backup(tables), k.ServiceError, Object.keys(tables)[0]);
  }
  assert.throws(() => backup(TABLES, NOW, 'Daily!'), k.ServiceError);
});

test('the root per system', () => {
  const saved = { APPDATA: process.env.APPDATA, XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME };
  Object.assign(process.env, { APPDATA: '/fake/Roaming', XDG_CONFIG_HOME: '/fake/config' });
  try {
    assert.equal(k.settingsBackupRoot('darwin'), path.join(os.homedir(), 'Library/Application Support/PassionCode'));
    assert.equal(k.settingsBackupRoot('win32'), path.join('/fake/Roaming', 'PassionCode'));
    assert.equal(k.settingsBackupRoot('linux'), path.join('/fake/config', 'PassionCode'));
    assert.equal(k.settingsBackupDir('example-agent', 'default', '/r'), path.join('/r', 'settings-backups', 'example-agent', 'default'));
  } finally {
    for (const [key, value] of Object.entries(saved)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});

test('write is named by time, private, skips an unchanged snapshot, removes a left temp file and keeps fourteen', () => {
  const dir = path.join(temp(), 'settings-backups', 'example-agent', 'default');
  const first = k.writeSettingsBackup(backup(), dir);
  assert.equal(path.basename(first), 'settings-20261005T020000123000Z.json');
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(first).mode & 0o777, 0o600);
    assert.equal(fs.statSync(dir).mode & 0o777, 0o700);
  }
  assert.equal(k.writeSettingsBackup(backup(TABLES, NOW + DAY), dir), null, 'unchanged: not written');
  const left = path.join(dir, '.settings-x.json.tmp1');
  fs.writeFileSync(left, 'half');
  const twoHoursAgo = new Date(Date.now() - 7_200_000);
  fs.utimesSync(left, twoHoursAgo, twoHoursAgo);
  for (let day = 1; day <= 20; day += 1) {
    const tables = structuredClone(TABLES);
    tables.projects.rows.push([`p-${100 + day}`, `Day ${day}`, false]);
    k.writeSettingsBackup(backup(tables, NOW + day * DAY), dir);
  }
  const kept = k.settingsBackups(dir);
  assert.equal(kept.length, k.SETTINGS_BACKUP_KEEP);
  assert.equal(path.basename(kept[0]), 'settings-20261025T020000123000Z.json');
  assert.deepEqual(fs.readdirSync(dir).filter((n) => !n.startsWith('settings-')), []);
  assert.equal(k.readSettingsBackup(kept[0]).counts.projects, 3);
  const filling = path.join(dir, '.settings-y.json.tmp2');
  fs.writeFileSync(filling, 'half');
  k.writeSettingsBackup(backup(TABLES, NOW + 40 * DAY), dir);
  assert.ok(fs.existsSync(filling), 'a young temporary file belongs to a writer still at work');
});

test('a clock that stepped back never deletes the new snapshot; a damaged newest file suppresses nothing; an impossible name is due', () => {
  const dir = temp();
  for (let day = 0; day < 15; day += 1) {
    const tables = structuredClone(TABLES);
    tables.projects.rows.push([`p-${200 + day}`, `Day ${day}`, false]);
    k.writeSettingsBackup(backup(tables, NOW + day * DAY), dir);
  }
  const tables = structuredClone(TABLES);
  tables.projects.rows.push(['p-999', 'Written after the clock stepped back', false]);
  const written = k.writeSettingsBackup(backup(tables, NOW - 365 * DAY), dir);
  assert.ok(fs.existsSync(written));
  assert.equal(k.settingsBackups(dir).length, k.SETTINGS_BACKUP_KEEP);

  const other = temp();
  const doc = backup();
  fs.writeFileSync(path.join(other, 'settings-20991231T000000000000Z.json'), JSON.stringify({ sha256: doc.sha256 }));
  assert.notEqual(k.writeSettingsBackup(doc, other), null);
  fs.writeFileSync(path.join(other, 'settings-20991231T000000000001Z.json'), '[]');
  const more = structuredClone(TABLES);
  more.projects.rows.push(['p-777', 'x', false]);
  assert.notEqual(k.writeSettingsBackup(backup(more), other), null);

  const odd = temp();
  fs.writeFileSync(path.join(odd, 'settings-20261345T000000000000Z.json'), '{}');
  assert.equal(k.backupDue(odd, NOW), true);
});

test('what the schema refuses is refused, and a reader parses as the Python one does', () => {
  const cases = [];
  let doc = backup(); doc.reason = 'daily\n'; cases.push([doc, 'reason']);
  doc = backup(); doc.sha256 += '\n'; cases.push([doc, 'sha256']);
  doc = backup(); doc.created_at = '2026-02-30T00:00:00Z'; cases.push([doc, 'created_at']);
  doc = backup(); doc.extensions = { 'not a uri': 1 }; cases.push([doc, 'extensions']);
  doc = backup(); doc.tables.projects.rows[0][1] = 'x'.repeat(1048577); cases.push([doc, 'longer than']);
  doc = backup(); doc.tables['lone\ud800'] = { columns: ['id'], rows: [] }; doc.counts['lone\ud800'] = 0; cases.push([doc, 'lone']);
  for (const [d, needle] of cases) assert.ok(has(k.settingsBackupProblems(d), needle), needle);
  doc = backup(); doc.created_at = '2026-10-05T04:00:00.5+02:00';
  assert.deepEqual(k.settingsBackupProblems(doc), [], 'an RFC 3339 offset is a date-time too');
  const dir = temp();
  const file = path.join(dir, 'settings-20261005T020000000000Z.json');
  fs.writeFileSync(file, JSON.stringify(backup()).replace('"schema":7', '"schema":7.0'));
  assert.throws(() => k.readSettingsBackup(file), /not an integer/);
  const withExtension = { ...backup(), extensions: { 'https://example.com/ext': 'PLACEHOLDER' } };
  const [head, tail] = JSON.stringify(withExtension).split('PLACEHOLDER');
  fs.writeFileSync(file, Buffer.concat([Buffer.from(head), Buffer.from([0xff]), Buffer.from(tail)])); // where nothing else looks
  assert.throws(() => k.readSettingsBackup(file), k.ServiceError, 'invalid UTF-8 is refused, never replaced');
  fs.writeFileSync(file, JSON.stringify(backup()));
  assert.equal(k.readSettingsBackup(file).sha256, backup().sha256);
});

test('due after a day; a damaged file is refused and skipped; an empty one is not a source', () => {
  const dir = temp();
  assert.equal(k.backupDue(dir, NOW), true);
  const good = k.writeSettingsBackup(backup(), dir);
  assert.equal(k.backupDue(dir, NOW + 23 * 3_600_000), false);
  assert.equal(k.backupDue(dir, NOW + DAY + 1000), true);
  const tables = structuredClone(TABLES);
  tables.projects.rows.push(['p-009', 'Later', false]);
  const bad = k.writeSettingsBackup(backup(tables, NOW + DAY), dir);
  const doc = JSON.parse(fs.readFileSync(bad, 'utf8'));
  doc.tables.projects.rows[0][1] = 'tampered';
  fs.writeFileSync(bad, JSON.stringify(doc));
  assert.throws(() => k.readSettingsBackup(bad), /checksum/);
  const empty = Object.fromEntries(Object.entries(TABLES).map(([n, t]) => [n, { columns: t.columns, rows: [] }]));
  k.writeSettingsBackup(backup(empty, NOW + 2 * DAY), dir);
  const chosen = k.newestIntactBackup(dir);
  assert.equal(chosen.file, good);
  assert.deepEqual(chosen.skipped.map((s) => s.file), [bad]);
});

test('restore adds missing rows, never overwrites, and names what it drops, defaults and refuses', () => {
  const plan = k.restorePlan(backup(), {
    projects: { columns: ['id', 'name', 'owner'], key: ['id'], required: ['id', 'name'], existing: [['p-001']] },
    secret_bindings: { columns: ['project_id', 'slot', 'secret_name', 'scope'], key: ['project_id', 'slot'], required: ['project_id', 'slot', 'scope'], existing: [] },
  });
  assert.deepEqual(plan.tables.projects.insert, [{ id: 'p-002', name: 'Board memo' }]);
  assert.equal(plan.tables.projects.present, 1);
  assert.deepEqual(plan.tables.projects.droppedColumns, ['archived']);
  assert.deepEqual(plan.tables.projects.defaultedColumns, ['owner']);
  assert.deepEqual(plan.tables.secret_bindings.missingRequired, ['scope']);
  assert.deepEqual(plan.tables.secret_bindings.refused, [{ key: ['p-001', 'llm'], reason: 'required column scope is not in the snapshot' }]);
  assert.deepEqual(k.restorePlan(backup(), { projects: { columns: ['id', 'name', 'archived'], key: ['id'], required: [], existing: [] } }).unknownTables, ['secret_bindings']);
  const twice = structuredClone(TABLES);
  twice.projects.rows.push(['p-002', 'Board memo again', false]);
  const dup = k.restorePlan(backup(twice), { projects: { columns: ['id', 'name', 'archived'], key: ['id'], required: [], existing: [] } });
  assert.equal(dup.tables.projects.insert.length, 2);
  assert.deepEqual(dup.tables.projects.refused, [{ key: ['p-002'], reason: 'the snapshot holds this key twice' }]);
  const damaged = backup();
  damaged.sha256 = '0'.repeat(64);
  assert.throws(() => k.restorePlan(damaged, {}), k.ServiceError);
});

test('the feed client sends the header the descriptor declares', () => {
  const token = 't'.repeat(20);
  assert.deepEqual(k.tokenHeader({}, token), { name: 'Authorization', value: `Bearer ${token}` });
  assert.deepEqual(k.tokenHeader({ header: 'X-Example-Token', scheme: 'none' }, token), { name: 'X-Example-Token', value: token });
  for (const [name, ok] of [['semantic-service-feed-request-custom-header', true], ['semantic-service-feed-request-assumed-bearer', false]]) {
    const doc = fixture(name);
    const sent = k.tokenHeader(doc.descriptor.auth, doc.token);
    assert.equal(doc.request.headers[sent.name] === sent.value, ok, name);
  }
});

test('every spending limit: the contract fixtures and FAC-SEM-031', () => {
  assert.deepEqual(k.usageLimitProblems(fixture('positive-service-usage-budgets')), []);
  for (const [name, needle] of [['negative-service-usage-budgets-bad-scope', 'scope'], ['negative-service-usage-budgets-unknown-field', 'note'],
    ['negative-service-usage-budgets-zero-limit', 'limitUsd']]) {
    assert.ok(has(k.usageLimitProblems(fixture(name)), needle), name);
  }
  const daily = { id: 'machine.daily', scope: 'machine', kind: 'daily', period: 'day', limitUsd: 5, spentUsd: 1, enforced: true };
  const { period, ...dailyNoPeriod } = daily;
  for (const [limits, needle] of [
    [[daily, { ...daily }], 'appears twice'],
    [[{ ...daily, id: 'p', scope: 'project' }], 'names its project in subject'],
    [[{ ...daily, id: 'm', subject: 'x' }], 'has no subject'],
    [[{ ...daily, windowSeconds: 86400 }], 'one window'],
    [[{ id: 'j', scope: 'job', kind: 'per_job', limitUsd: 2, spentUsd: 0.5, enforced: true }], 'nothing is spent'],
    [[{ id: 'j', scope: 'job', kind: 'per_job', period: 'day', limitUsd: 2, spentUsd: null, enforced: true }], 'no window'],
    [[{ ...daily, period: 'month' }], 'a daily limit'],
    [[{ ...dailyNoPeriod, kind: 'monthly', windowSeconds: 86400 }], 'a monthly limit'],
    [[{ id: 'v', scope: 'machine', kind: 'velocity', limitUsd: null, spentUsd: 0, enforced: true }], 'velocity'],
    [[{ id: 'e', scope: 'machine', kind: 'emergency', limitUsd: 500, spentUsd: 0, enforced: true }], 'names the window'],
    [[{ ...daily, limitUsd: null }], 'only a relative limit'],
    [[{ ...daily, enforced: false, tripped: true }], 'not enforced cannot have stopped'],
  ]) assert.ok(has(k.usageLimitProblems({ budgets: limits }), needle), needle);
  assert.deepEqual(k.usageLimitProblems({ budgets: [daily, { id: 'custom', scope: 'machine', kind: 'night_cap', limitUsd: 1, spentUsd: 0, enforced: false }] }), [], 'an unknown kind is never refused');
  assert.deepEqual(k.usageLimitProblems({ budgets: [daily], budget: { period: 'day', limitUsd: 5, spentUsd: 1 } }), []);
  assert.ok(has(k.usageLimitProblems({ budgets: [daily], budget: { period: 'month', limitUsd: 5, spentUsd: 1 } }), 'budget repeats'));
});

test('the report counts a machine period limit and refuses an incoherent one', () => {
  const now = Date.UTC(2026, 9, 4, 16);
  const receipts = [k.makeUsageReceipt('anthropic', 'm', { inputTokens: 10, outputTokens: 5, costUsd: 0.25, costBasis: 'provider', at: '2026-10-04T10:00:00Z' }),
    k.makeUsageReceipt('anthropic', 'm', { inputTokens: 10, outputTokens: 5, costUsd: 0.5, costBasis: 'provider', at: '2026-10-01T10:00:00Z' })];
  const report = k.usageReport(receipts, { id: 'example-agent', now, budget: { period: 'month', limitUsd: 100 }, budgets: [
    { id: 'machine.monthly', scope: 'machine', kind: 'monthly', period: 'month', limitUsd: 100, enforced: true },
    { id: 'machine.daily', scope: 'machine', kind: 'daily', period: 'day', limitUsd: 5, enforced: false },
    { id: 'job.cap', scope: 'job', kind: 'per_job', limitUsd: 2, enforced: true }] });
  const byId = Object.fromEntries(report.budgets.map((l) => [l.id, l]));
  assert.equal(byId['machine.monthly'].spentUsd, 0.75);
  assert.equal(byId['machine.daily'].spentUsd, 0.25);
  assert.equal(byId['job.cap'].spentUsd, null);
  assert.deepEqual(report.budget, { period: 'month', limitUsd: 100, spentUsd: 0.75 });
  assert.deepEqual(k.usageLimitProblems(report), []);
  assert.throws(() => k.usageReport(receipts, { id: 'example-agent', now, budgets: [{ id: 'p', scope: 'project', kind: 'daily', period: 'day', limitUsd: 5, enforced: true }] }), k.ServiceError);
  assert.throws(() => k.usageReport(receipts, { id: 'example-agent', now, budgets: ['machine.daily'] }), /is an object/);
  const rolling = k.usageReport(receipts.values(), { id: 'example-agent', now, budgets: [{ id: 'machine.24h', scope: 'machine', kind: 'emergency', windowSeconds: 86400, limitUsd: 50, enforced: true }] });
  assert.equal(rolling.budgets[0].spentUsd, 0.25, 'a rolling machine window is counted from the receipts, even from an iterator');
});

test('the descriptor names its header and scheme the schema way', () => {
  const base = { protocol: k.PROTOCOL, id: 'example-agent', instance: 'default', name: 'Example', origin: 'http://127.0.0.1:47195',
    auth: { tokenFile: '~/t' }, lifecycle: { manager: 'none' }, paths: { data: '~/d', logs: [] }, installedAt: '2026-10-05T00:00:00Z', installedBy: 'test' };
  assert.deepEqual(k.validateDescriptor(base), []);
  assert.ok(has(k.validateDescriptor({ ...base, auth: { tokenFile: '~/t', header: 'X Token', scheme: 'none' } }), 'auth.header'));
  assert.ok(has(k.validateDescriptor({ ...base, auth: { tokenFile: '~/t', scheme: 'Basic' } }), 'auth.scheme'));
});

test('both kits write byte-identical backup files', { skip: spawnSync('python3', ['--version']).status !== 0 && 'needs python3' }, () => {
  const tables = { projects: { columns: ['id', 'name', 'note'], rows: [['p-001', 'Résumé “final”', 'line\nbreak\t\u0001 😀'], ['p-002', '', null]] },
    settings_overrides: { columns: ['key', 'value_int', 'on'], rows: [['limit', -9007199254740991, true]] } };
  const pyDir = temp(), jsDir = temp();
  const py = spawnSync('python3', ['-c', `
import datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(scripts)})
import fabric_service as fs
doc = fs.make_settings_backup(service_id="example-agent", instance="default", version="0.4.0", schema=7, tables=json.loads(sys.argv[1]),
                              reason="daily", now=dt.datetime(2026, 10, 5, 2, 0, 0, 123000, tzinfo=dt.timezone.utc))
print(fs.write_settings_backup(doc, Path(sys.argv[2])))`, JSON.stringify(tables), pyDir], { encoding: 'utf8' });
  assert.equal(py.status, 0, py.stderr);
  const js = k.writeSettingsBackup(backup(tables), jsDir);
  assert.equal(path.basename(py.stdout.trim()), path.basename(js));
  assert.equal(fs.readFileSync(js, 'utf8'), fs.readFileSync(py.stdout.trim(), 'utf8'));
});
