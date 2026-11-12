// The code checks of the support-agent recipe for a Node agent (FAA-264 item 10): checkReply, the gate the
// communication template runs on every final text, and what it reads (unsupported, scriptOf). The twin of
// support_agent.py's check_reply; both answer the cases in test/fixtures/support-check-reply-cases.json the same way.
// Python's Unicode classes are written out (\w as [\p{L}\p{N}_], \d as \p{Nd}, \b as lookarounds), since a JavaScript
// \w, \d and \b are ASCII. Node 20+, no dependency.
const W = '\\p{L}\\p{N}_';
const LETTER = '\\p{L}\\p{Nl}\\p{No}'; // Python's [^\W\d_]: a word character that is no decimal digit and no underscore
const DASHES = new RegExp(`[\\u2012\\u2014\\u2015\\u2e3a\\u2e3b\\ufe58]|--|(?<=[${LETTER}])[ \\u00a0][-\\u2013]\\s(?=[${LETTER}])`, 'u');
const CITATION = /\[KB:([A-Za-z0-9][A-Za-z0-9._-]{0,63})\]/g;
const URL_RUN = /https?:\/\/\S+/gu;
const CCTLD = ('ac ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bm bn bo br bs bt bw by bz ca '
  + 'cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg er es et eu fi fj fk fm fo '
  + 'fr ga gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je '
  + 'jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mg mh mk ml mm mn mo '
  + 'mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt '
  + 'pw py qa re ro rs ru rw sa sb sc sd se sg sh si sk sl sm sn so sr ss st su sv sx sy sz tc td tf tg th tj tk '
  + 'tl tm tn to tr tt tv tw tz ua ug uk us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw');
const GTLD = ('com net org info biz edu gov mil int app dev xyz online site shop store tech cloud email link live news blog '
  + 'page help support pro club top vip one world today space website mobi name travel agency company services '
  + 'solutions digital network media studio design money finance bank pay refund claim click download win '
  + 'рф рус укр бел срб');
const TLDS = [...new Set(`${CCTLD} ${GTLD}`.split(' '))].sort((a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0)).join('|');
const STOP = '[^\\s<>()"\'\\[\\]]';
const LINK = new RegExp(`(?:(?<![${W}])https?://|(?<![${W}@.-])www\\.)${STOP}+`
  + `|(?<![${W}@.\\-/])(?:[\\p{L}\\p{N}](?:[${W}-]{0,61}[\\p{L}\\p{N}])?\\.)+(?:${TLDS})(?![${W}-])(?::\\p{Nd}{1,5})?(?:[/?#]${STOP}*)?`, 'giu');
const EMAIL = new RegExp(`[${W}.+-]+@[${W}-]+(?:\\.[${W}-]+)+`, 'gu');
const PHONE = new RegExp(`(?<![${W}+])\\+?\\p{Nd}(?:[ ().-]{0,2}\\p{Nd}){6,}`, 'gu');
const CURRENCY = { $: 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₽': 'rub', '₹': 'inr', dollar: 'usd', dollars: 'usd', euro: 'eur', euros: 'eur', pound: 'gbp', pounds: 'gbp' };
const CODES = 'usd|eur|gbp|jpy|rub|inr|chf|cad|aud|cny|uah|pln|try';
const UNIT = `[$\\u20ac\\u00a3\\u00a5\\u20bd\\u20b9]|(?<![${W}])(?:${CODES}|dollars?|euros?|pounds?)(?![${W}])|руб[${W}]*`;
const NUM = '\\p{Nd}+(?:[.,]\\p{Nd}+)*';
const AMOUNT = new RegExp(`(${UNIT})\\s?(${NUM})|(${NUM})\\s?(${UNIT})`, 'giu');
const NUMBER = new RegExp(NUM, 'gu');
const TRAILING = ".,;:!?'\")]";
export const SCRIPTS = Object.freeze([
  ['latin', [[0x41, 0x5A], [0x61, 0x7A], [0xC0, 0x24F], [0x1E00, 0x1EFF]]],
  ['cyrillic', [[0x400, 0x52F]]],
  ['greek', [[0x370, 0x3FF]]],
  ['hebrew', [[0x590, 0x5FF]]],
  ['arabic', [[0x600, 0x6FF], [0x750, 0x77F]]],
  ['devanagari', [[0x900, 0x97F]]],
  ['thai', [[0xE00, 0xE7F]]],
  ['cjk', [[0x3040, 0x30FF], [0x3400, 0x4DBF], [0x4E00, 0x9FFF], [0xAC00, 0xD7AF]]],
]);

/** The script most of a text's letters are written in (citations and URLs left out), or null without letters. */
export function scriptOf(text) {
  const counts = new Map();
  for (const ch of text.replace(CITATION, ' ').replace(URL_RUN, ' ')) {
    const code = ch.codePointAt(0);
    const hit = SCRIPTS.find(([, ranges]) => ranges.some(([lo, hi]) => lo <= code && code <= hi));
    if (hit) counts.set(hit[0], (counts.get(hit[0]) ?? 0) + 1);
  }
  let best = null;
  for (const [name, n] of counts) if (best === null || n > counts.get(best) || (n === counts.get(best) && name > best)) best = name;
  return best;
}

const currency = (unit) => {
  const lowered = unit.toLowerCase();
  return lowered.startsWith('руб') ? 'rub' : (CURRENCY[lowered] ?? lowered);
};

function linkKey(link) {
  let key = link.replace(/^https?:\/\//i, '');
  while (key && (TRAILING + '/').includes(key[key.length - 1])) key = key.slice(0, -1);
  const cut = key.search(/[/?#]/);
  return cut < 0 ? key.toLowerCase() : key.slice(0, cut).toLowerCase() + key.slice(cut);
}

const rstrip = (text, chars) => { let end = text.length; while (end && chars.includes(text[end - 1])) end -= 1; return text.slice(0, end); };

function claims(text) {
  const amounts = new Set();
  for (const m of text.matchAll(AMOUNT)) amounts.add(JSON.stringify([currency(m[1] ?? m[4]), m[2] ?? m[3]]));
  return {
    url: new Set([...text.matchAll(LINK)].map((m) => linkKey(m[0]))),
    email: new Set([...text.matchAll(EMAIL)].map((m) => rstrip(m[0], TRAILING).toLowerCase())),
    phone: new Set([...text.matchAll(PHONE)].map((m) => m[0].replace(/\P{Nd}/gu, ''))),
    amount: amounts,
    number: new Set([...text.matchAll(NUMBER)].map((m) => m[0])),
  };
}

/** unsupported:<kind> for each kind of claim in the reply that the source text does not carry. */
export function unsupported(reply, source) {
  const said = claims(reply);
  const known = claims(source);
  const problems = [];
  for (const kind of ['url', 'email', 'phone', 'amount', 'number']) {
    const missing = kind === 'phone'
      ? [...said[kind]].filter((c) => ![...known[kind]].some((k) => k.endsWith(c)))
      : [...said[kind]].filter((c) => !known[kind].has(c));
    if (missing.length) problems.push(`unsupported:${kind}`);
  }
  return problems;
}

/** What code can prove about a draft: {ok, problems, citations, reply}; the twin of support_agent.check_reply. */
export function checkReply(draft, question, given, { maxChars, sources = {} } = {}) {
  const problems = [];
  const cited = [...new Set([...draft.matchAll(CITATION)].map((m) => m[1]))];
  if (!cited.length) problems.push('no-citation');
  const unknown = cited.filter((c) => !given.includes(c));
  if (unknown.length) problems.push(`unknown-citation:${unknown.join(',')}`);
  if (DASHES.test(draft)) problems.push('dash');
  const reply = draft.replace(CITATION, '').replace(/[ \t]+/g, ' ').replaceAll(' .', '.').replaceAll(' ,', ',').trim();
  if (!reply) problems.push('empty');
  else if ([...reply].length > maxChars) problems.push('too-long');
  problems.push(...unsupported(reply, cited.filter((c) => given.includes(c)).map((c) => (Object.hasOwn(sources, c) ? sources[c] : '')).join('\n')));
  const wanted = scriptOf(question);
  const written = scriptOf(reply);
  if (wanted && written && wanted !== written) problems.push(`script:${written}-not-${wanted}`);
  return { ok: problems.length === 0, problems, citations: cited, reply };
}
