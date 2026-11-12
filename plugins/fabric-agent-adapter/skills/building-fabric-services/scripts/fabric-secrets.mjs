// The contract's one credential detector (Fabric Agent Contract DEC-0044, `src/secret-shape.ts` at the pin): a name
// that can only carry a credential, a value shaped like one, a launch argument that carries one, and a URL that does
// (LC-21). A port held to the contract's own answers by test/fixtures/contract/profile-vectors.json. No dependencies.

/** A name's words: split at `.`, `_`, `-` and camelCase humps, lowercased (`APIKey` is `api key`). */
export function nameWords(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .split(/[\s._-]+/)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
}

export const CREDENTIAL_WORDS = Object.freeze([
  'token', 'secret', 'password', 'passwd', 'pass', 'passphrase', 'credential', 'credentials', 'cookie', 'authorization',
  'bearer', 'jwt', 'otp', 'apikey', 'signature', 'sig',
  'accesstoken', 'idtoken', 'authtoken', 'refreshtoken', 'sessionid', 'sessiontoken', 'logincode', 'authcode', 'privatekey',
  'clientsecret', 'secretkey', 'accesskey',
]);
export const CREDENTIAL_PAIRS = Object.freeze({
  key: ['private', 'api', 'access', 'secret', 'session', 'auth', 'signing', 'encryption', 'master', 'client', 'login', 'refresh'],
  auth: ['token', 'code', 'header'],
  session: ['token', 'id'],
  code: ['login', 'auth', 'access', 'session'],
});

const withSingulars = (words) => [...words, ...words.filter((word) => word.length > 2 && word.endsWith('s')).map((word) => word.slice(0, -1))];

/** Whether a name — a parameter, a header, an environment variable, a config key — can only carry a credential. */
export function credentialName(name) {
  const split = nameWords(name);
  const words = withSingulars(split);
  if (words.some((word) => CREDENTIAL_WORDS.includes(word))) return true;
  if (split.length === 1 && words.some((word) => Object.hasOwn(CREDENTIAL_PAIRS, word))) return true;
  return Object.entries(CREDENTIAL_PAIRS).some(([word, partners]) => words.includes(word) && partners.some((partner) => words.includes(partner)));
}

/** A JWT or JWS anywhere in a value. */
export const JWT_SHAPE = /eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*/;
const isUrlBase64 = (code) => (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a) || (code >= 0x30 && code <= 0x39)
  || code === 0x2d || code === 0x5f;
const runEnd = (text, from) => { let end = from; while (end < text.length && isUrlBase64(text.charCodeAt(end))) end += 1; return end; };
/** The spans JWT_SHAPE matches in a text, leftmost and not overlapping, read in one pass (the contract's jwtSpans,
 * FAA-313): the regular expression backtracks from every `eyJ` of a long run, quadratic in it, while every `eyJ` of one
 * run shares that run's end, so only its first is tried, and a match ends where its third segment's run ends. `first`
 * stops at the first match. */
export function jwtSpans(text, first = false) {
  const spans = [];
  let from = 0;
  for (let at = text.indexOf('eyJ', from); at >= 0; at = text.indexOf('eyJ', from)) {
    const one = runEnd(text, at + 3);
    from = one;
    if (one - at - 3 < 2 || text[one] !== '.') continue;
    const two = runEnd(text, one + 1);
    if (two - one - 1 < 2 || text[two] !== '.') continue;
    const three = runEnd(text, two + 1);
    spans.push([at, three]);
    if (first) break;
    from = three;
  }
  return spans;
}
/** Whether JWT_SHAPE matches anywhere in a text, read in one pass (the contract's hasJwt, FAA-313). */
export const hasJwt = (text) => jwtSpans(text, true).length > 0;
/** A value that says it is a credential (`Bearer ` at its start, in any case), or a provider key's shape with its prefix
 * in its canonical case only, at the start of a value, after a character that is no ASCII letter or digit, or after an
 * escape; an `sk-` key holds a digit and an upper-case letter with 16 or more characters, or a digit with 32 or more,
 * within 256 characters (the contract's SECRET_VALUE at the pin, DEC-0151). A match includes its boundary character:
 * callers test, never read the matched text or its index. */
export const SECRET_VALUE = /(^[Bb][Ee][Aa][Rr][Ee][Rr]\s.+|(?:^|[^A-Za-z0-9]|%[0-9A-Fa-f]{2}|\\[nrt"']|\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}|\\[bfv0ae]|\\[0-7]{1,3}|%25[0-9A-Fa-f]{2}|\x1b\[[0-9;:]*m|(?:\\u001[bB]|\\x1[bB]|\\e|\\033|\\33)\[[0-9;:]*m)(?:sk-(?=[A-Za-z0-9_-]{0,255}?\d)(?:(?=[A-Za-z0-9_-]{0,255}?[A-Z])[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{32,})|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}))/;
const LONG_RUN = /[A-Za-z0-9+/=_-]{40,}/g;
export const longSecret = (value) => (value.match(LONG_RUN) ?? []).some((run) => /[a-z]/.test(run) && /[A-Z]/.test(run) && /[0-9]/.test(run));

/** Whether a value could be a credential: a JWT anywhere, a provider key or `Bearer …`, or a long secret-shaped run. */
export const secretValue = (value) => hasJwt(value) || SECRET_VALUE.test(value) || longSecret(value);

export const BEARER_INSIDE = /\bbearer\s+(?=[A-Za-z0-9._~+/-]*\d)[A-Za-z0-9._~+/-]{12,}=*/i;
const PATH_LIKE = /^(?:[/~.]|[A-Za-z]:[\\/]|[a-z][a-z0-9+.-]*:\/\/)/i;
const pathLike = (piece) =>
  PATH_LIKE.test(piece) ||
  (/[\\/]/.test(piece) && (/\.[A-Za-z0-9]{1,8}$/.test(piece) || piece.split(/[\\/]/).some((segment) => /^[a-z][a-z0-9_-]{2,}$/.test(segment))));

/** The same for a launch argument or a server's command and URL: a long run is looked for between path separators. */
export const secretArgument = (value) =>
  hasJwt(value) || SECRET_VALUE.test(value) || BEARER_INSIDE.test(value) ||
  value.split(/[\s=]/).some((piece) => (pathLike(piece) ? piece.split(/[\\/]/).some((part) => longSecret(part)) : longSecret(piece)));

const decodeKeepingPlus = (raw) => { try { return decodeURIComponent(raw); } catch { return raw; } };

/** Each query or fragment piece's raw value by its decoded name, with `+` kept. */
export function rawValues(query) {
  const values = new Map();
  for (const piece of query.split('&')) {
    if (piece === '') continue;
    const at = piece.indexOf('=');
    const name = [...new URLSearchParams(at < 0 ? piece : piece.slice(0, at)).keys()][0] ?? '';
    const value = at < 0 ? '' : decodeKeepingPlus(piece.slice(at + 1));
    const list = values.get(name);
    if (list) list.push(value); // appended in place: copying the list per piece made a long query quadratic (FAA-245)
    else values.set(name, [value]);
  }
  return values;
}

/** Whether a URL an MCP entry or a launch names carries a credential (LC-21). */
export function secretUrl(value) {
  if (secretArgument(value)) return true;
  let url;
  try { url = new URL(value); } catch { return false; }
  if (url.password !== '') return true;
  for (const part of [url.search, url.hash]) {
    for (const [name, values] of rawValues(part.slice(1))) {
      if (values.some((raw) => (raw !== '' && credentialName(name)) || secretValue(raw))) return true;
    }
  }
  return false;
}

const REPOSITORY_URI = /^([A-Za-z][A-Za-z0-9+.-]*:(?:\/\/[^/?#]*)?)([^?#]*)([\s\S]*)$/;
const REPOSITORY_NAME = /^(?:[a-z0-9._-]+|[A-Za-z._-]+)$/; // lower case, or letters with no digit (readings 8)
const REPOSITORY_AUTHORITY = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;
// A repository name's own key shapes, boundary-free and case-sensitive (DEC-0151): SECRET_VALUE takes a consuming
// boundary, so composed after a separator look-behind it would miss a key after `-`, `.` or `_`.
const REPOSITORY_KEYS = 'sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}';
const KEY_AT_A_WORD = new RegExp(`(?:^|(?<=[._-]))(?:${REPOSITORY_KEYS})`);
const JWT_AT_A_WORD = new RegExp(`(?:^|(?<=[._-]))${JWT_SHAPE.source}`);
const SPECIAL_QUERY = /^(?:https?|wss?|ftp|file):/i; // whose query also encodes `'`, as the URL standard does

/** Whether a path segment reads as a repository's name: lower case, or letters with no digit, with no provider key's
 * or JWT's shape at its start or after a `.`, `_` or `-` (0.62.0 readings 9 and 10), so a letters-only key is a key. */
export const repositoryName = (piece) => REPOSITORY_NAME.test(piece) && !KEY_AT_A_WORD.test(piece) && !JWT_AT_A_WORD.test(piece);

/** Every `%XX` escape of an ASCII character decoded, the rest as written (fabric_secrets.ascii_decoded, readings 11). */
export const asciiDecoded = (text) => text.replace(/%([0-7][0-9A-Fa-f])/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));

/** Whether a repository URI's user information holds a password: every slash and backslash after the colon skipped,
 * then up to the next `/`, `?` or `#` (fabric_secrets.repository_password, 0.62.0 readings 10 to 14). */
export function repositoryPassword(value) {
  const text = value.replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '').replace(/[\t\n\r]/g, '');
  const colon = text.indexOf(':');
  const rest = colon < 0 ? '' : text.slice(colon + 1); // as Python's partition leaves it (unit reading 12)
  const authorities = colon < 0 ? [] : [/^[^/?#]*/.exec(rest.replace(/^[/\\]+/, ''))[0]];
  const users = authorities.map((authority) => authority.slice(0, Math.max(authority.lastIndexOf('@'), 0)));
  return [...users, ...users.map(asciiDecoded)].some((user) => user.includes(':') && user.slice(user.indexOf(':') + 1) !== '');
}

// A repository's parameters, read as fabric_secrets.secret_url reads them, by hand: `new URL`
// refuses a host it cannot parse and a special scheme written without `//` (`https:host/r?access_token=...`), where
// the Python twin's repository_credential reads them too (0.62.0 readings 8 and 9, FAA-200 (17)); its secret_url, like
// secretUrl, refuses such a URL since FAA-309.
function repositoryParts(head, tail) {
  const text = tail.replace(/[\x00-\x20]+$/, '').replace(/[\t\n\r]/g, '');
  const hash = text.indexOf('#');
  const before = hash < 0 ? text : text.slice(0, hash);
  const query = before.startsWith('?') ? before.slice(1) : '';
  const fragment = hash < 0 ? '' : text.slice(hash + 1);
  try { // percent-encode them as `new URL` does, on a host it always reads
    const url = new URL(`${SPECIAL_QUERY.test(head) ? 'https://h.invalid/' : 'x-repository://h/'}?${query}#${fragment}`);
    return [url.search.slice(1), url.hash.slice(1)];
  } catch { return [query, fragment]; }
}

// FAA-198 (0.62.0 readings 6 and 7): whether a repository URI carries a credential: in its scheme and authority (a
// user), in its query or fragment as secretUrl reads them, or as a path segment shaped like a key. A path segment in
// lower case, or of letters with no digit (task-pipeline-dashboard, Task-Pipeline-Dashboard), is the repository's
// name, never a key, though it reads as an `sk-` shape, unless a key's shape starts it or follows a `.`, `_` or `-` in
// it (repositoryName); a segment is read as written and asciiDecoded. A
// user outside a URL's authority (an scp form, `https:user@host/path`) counts as one: a user is an authority's.
export function repositoryCredential(value) {
  if (value.includes('@') && !REPOSITORY_AUTHORITY.test(value)) return true;
  const match = REPOSITORY_URI.exec(value);
  if (!match) return secretArgument(value);
  const [, head, path, tail] = match;
  const odd = [path, asciiDecoded(path)].flatMap((written) => written.split(/[/\\:]/)).filter((piece) => piece && !repositoryName(piece));
  if (repositoryPassword(value) || secretArgument(head + tail) || secretArgument(asciiDecoded(head)) || odd.some((piece) => secretArgument(piece))) return true; // the authority decoded too (unit reading 12)
  return repositoryParts(head, tail).some((part) => [...rawValues(part)].some(([name, values]) =>
    values.some((raw) => (raw !== '' && credentialName(name)) || secretValue(raw))));
}
