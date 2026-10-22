// fabric-package/1, the schema reading: the package schema bundled from the contract at the pin, read by a JSON
// Schema 2020-12 subset with JavaScript's patterns, lengths in code points and the formats the contract uses.
// fabric-package.mjs checks, packs, signs and verifies on it and re-exports schemaProblems. Part of the Node service
// kit (FAA-92, split from fabric-package.mjs; layer L2); the twin of fabric_package_schema.py. Node 20+, no dependency.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isString, jsonEqual } from './fabric-jsvalue.mjs'; // the core's (FAA-65)

export const SCHEMA_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fabric-package.schema.json');

// --- the schema (bundled from the contract at the pin) ---------------------------------------------------------------

export let schemaCache;
export const schema = () => (schemaCache ??= JSON.parse(fs.readFileSync(SCHEMA_FILE, 'utf8')));


export const typeOf = (v) => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v === 'number' ? (Number.isInteger(v) ? 'integer' : 'number') : typeof v);
export const DATE_TIME = /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|[+-]([0-9]{2}):([0-9]{2}))$/;
export const MONTH_DAYS = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
export const leap = (year) => year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);

export function formatOk(format, value) {
  if (!isString(value)) return true;
  if (format === 'date-time') {
    const m = DATE_TIME.exec(value);
    if (!m) return false;
    const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
    // The proleptic calendar the contract's ajv-formats checks: year 0000 exists and is a leap year (0000-02-29 holds).
    // Counted here, not with Date.UTC, which reads years 0 to 99 as 1900 to 1999.
    if (mo < 1 || mo > 12 || d < 1 || d > (mo === 2 && leap(y) ? 29 : MONTH_DAYS[mo]) || h > 23 || mi > 59 || s > 59) return false;
    return m[8] === 'Z' || m[8] === 'z' || (Number(m[9]) < 24 && Number(m[10]) < 60);
  }
  if (format === 'uri') return /^[A-Za-z][A-Za-z0-9+.-]*:\S*$/.test(value);
  return true;
}

export const pointer = (token) => String(token).replace(/~/g, '~0').replace(/\//g, '~1');
export const codePoints = (s) => [...s].length; // JSON Schema counts code points, not UTF-16 units

export function validate(node, value, at, out) {
  if (node === true) return;
  if (node === false) { out.push({ instancePath: at, message: 'is not allowed here' }); return; }
  if (node.$ref) {
    const target = node.$ref.replace(/^#\//, '').split('/').reduce((n, t) => n[t.replace(/~1/g, '/').replace(/~0/g, '~')], schema());
    validate(target, value, at, out);
  }
  const kind = typeOf(value);
  if (node.type !== undefined) {
    const allowed = Array.isArray(node.type) ? node.type : [node.type];
    if (!(allowed.includes(kind) || (kind === 'integer' && allowed.includes('number')))) { out.push({ instancePath: at, message: `must be ${allowed.join(' or ')}` }); return; }
  }
  if ('const' in node && !jsonEqual(node.const, value)) out.push({ instancePath: at, message: `must be ${JSON.stringify(node.const)}` });
  if (node.enum && !node.enum.some((item) => jsonEqual(item, value))) out.push({ instancePath: at, message: `must be one of ${node.enum.map((i) => JSON.stringify(i)).join(', ')}` });
  if (kind === 'string') {
    const length = codePoints(value);
    if (length < (node.minLength ?? 0)) out.push({ instancePath: at, message: `is shorter than ${node.minLength}` });
    if (node.maxLength !== undefined && length > node.maxLength) out.push({ instancePath: at, message: `is longer than ${node.maxLength}` });
    if (node.pattern !== undefined && !new RegExp(node.pattern, 'u').test(value)) out.push({ instancePath: at, message: `does not match ${node.pattern}` });
    if (node.format !== undefined && !formatOk(node.format, value)) out.push({ instancePath: at, message: `is not a ${node.format}` });
  }
  if ((kind === 'integer' || kind === 'number') && node.minimum !== undefined && value < node.minimum) out.push({ instancePath: at, message: `is below ${node.minimum}` });
  if (kind === 'array') {
    if (value.length < (node.minItems ?? 0)) out.push({ instancePath: at, message: `has fewer than ${node.minItems} items` });
    if (node.maxItems !== undefined && value.length > node.maxItems) out.push({ instancePath: at, message: `has more than ${node.maxItems} items` });
    if (node.uniqueItems && value.some((item, i) => value.slice(0, i).some((other) => jsonEqual(item, other)))) out.push({ instancePath: at, message: 'has duplicate items' });
    if (node.items !== undefined) value.forEach((item, i) => validate(node.items, item, `${at}/${i}`, out));
    if (node.contains !== undefined) {
      const matches = value.filter((item) => problemsOf(node.contains, item).length === 0).length;
      if (matches < (node.minContains ?? 1)) out.push({ instancePath: at, message: `has fewer than ${node.minContains ?? 1} matching items` });
      if (node.maxContains !== undefined && matches > node.maxContains) out.push({ instancePath: at, message: `has more than ${node.maxContains} matching items` });
    }
  }
  if (kind === 'object') {
    for (const name of node.required ?? []) if (!Object.hasOwn(value, name)) out.push({ instancePath: at, message: `must have ${name}` });
    const properties = node.properties ?? {};
    for (const [name, member] of Object.entries(value)) {
      const where = `${at}/${pointer(name)}`;
      if (Object.hasOwn(properties, name)) validate(properties[name], member, where, out);
      else if (node.additionalProperties === false) out.push({ instancePath: where, message: 'is not a member of this object' });
      else if (node.additionalProperties !== undefined) validate(node.additionalProperties, member, where, out);
      if (node.propertyNames !== undefined) validate(node.propertyNames, name, where, out);
    }
  }
  for (const sub of node.allOf ?? []) validate(sub, value, at, out);
  if (node.not !== undefined && problemsOf(node.not, value).length === 0) out.push({ instancePath: at, message: 'must not match' });
  if (node.if !== undefined) {
    const branch = problemsOf(node.if, value).length === 0 ? node.then : node.else;
    if (branch !== undefined) validate(branch, value, at, out);
  }
}

export function problemsOf(node, value) {
  const out = [];
  validate(node, value, '', out);
  return out;
}

/** Where the package breaks fabric-package.schema.json (the contract's, bundled at the pin). */
export const schemaProblems = (pkg) => problemsOf(schema(), pkg);
