#!/usr/bin/env node
// Writes test/fixtures/idna/idna-tables.json: the two code point tables fabric_connections.py reads a non-ASCII host
// with (FAA-98), measured on every Node named, never written by hand. The reference reads URLs with the runtime's own
// `new URL`, whose UTS46 tables follow its ICU, so a table keeps only what every Node named answers alike:
//
// - disallowed: code points assigned in every Node's Unicode that `new URL` refuses as a whole host, between ASCII
//   letters (`a<c>b`) and as a second label (`a.<c>`), and beside a virama, an Arabic, a Hebrew and a Han letter; the
//   two joiners (U+200C, U+200D) are left out, as their verdict depends on their neighbours (CheckJoiners).
// - ignored: code points assigned everywhere that `new URL('https://a<c>b/').host` reads as `ab`.
//
//   node test/fixtures/idna/make_idna_tables.mjs --node <node 20> --node <node 22> --node <node 24> --node <node 26>
//     [--out test/fixtures/idna/idna-tables.json]
//
// Each --node runs this file in probe mode and prints its verdicts; the tables are what they all share.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const self = fileURLToPath(import.meta.url);
const CONTEXTS = ['{}', 'a{}b', 'a.{}', 'क्{}क', 'ب{}ب', 'א{}א', '日{}本'];
const parses = (host) => { try { new URL(`https://${host}/`); return true; } catch { return false; } };

if (process.argv[2] === '--probe') {
  let out = '';
  for (let cp = 0x80; cp < 0x110000; cp += 1) {
    if (cp >= 0xd800 && cp <= 0xdfff) continue;
    const c = String.fromCodePoint(cp);
    if (/\p{Cn}/u.test(c)) { out += 'n'; continue; }
    if (CONTEXTS.every((t) => !parses(t.replace('{}', c)))) { out += 'd'; continue; }
    let host = null;
    try { host = new URL(`https://a${c}b/`).host; } catch { /* refused between letters only */ }
    out += host === 'ab' ? 'i' : '.';
  }
  process.stdout.write(`${process.version} ${out}`); // no process.exit: a pipe would be cut short
} else {

const nodes = process.argv.slice(2).reduce((acc, a, i, all) => (a === '--node' ? [...acc, all[i + 1]] : acc), []);
const outAt = process.argv.indexOf('--out');
const out = outAt > 0 ? process.argv[outAt + 1] : path.join(path.dirname(self), 'idna-tables.json');
if (nodes.length === 0) throw new Error('name at least one --node');
const runs = nodes.map((node) => execFileSync(node, [self, '--probe'], { maxBuffer: 1 << 24 }).toString().split(' '));
const cps = [];
for (let cp = 0x80; cp < 0x110000; cp += 1) if (cp < 0xd800 || cp > 0xdfff) cps.push(cp);
const ranges = (mark) => {
  const list = [];
  cps.forEach((cp, i) => {
    if (cp === 0x200c || cp === 0x200d || !runs.every(([, v]) => v[i] === mark)) return;
    const last = list[list.length - 1];
    if (last && (last[1] === cp - 1 || (last[1] === 0xd7ff && cp === 0xe000))) last[1] = cp; else list.push([cp, cp]);
  });
  return list;
};
fs.writeFileSync(out, `${JSON.stringify({
  about: "Code points fabric_connections.py reads a non-ASCII host with (FAA-98), as [first, last] ranges, measured by make_idna_tables.mjs on every Node below; never written by hand. A code point outside both is left to the reading's other rules.",
  nodes: runs.map(([version]) => version),
  disallowed: ranges('d'),
  ignored: ranges('i'),
})}\n`);
}
