#!/usr/bin/env python3
"""Find instance data in an agent's source tree, without repeating it (FAA-188 part 1).

An agent's source is what can be handed over (code, skills, prompts, schemas, examples); its instance is what belongs
to one installation (records, logs, keys, the owner's names and paths, its configuration). This check reads the files
the source would carry and reports, by path, line and kind, each place where the instance shows through:

- `home-path`: an absolute path inside a person's home folder whose name is ASCII: `/Users/<name>/`, `/home/<name>/`,
  `/var/home/<name>/`, `C:\\Users\\<name>\\` (any case, either separator, a JSON-escaped backslash), the dashed form a
  tool makes of such a path (`-Users-<name>-`, `C--Users-<name>-`, DEC-0105, its name up to the next dash), Git Bash's
  `/c/Users/<name>`, WSL's `/mnt/c/Users/<name>` and the URL-encoded ones (`%2FUsers%2F<name>`, `%5CUsers%5C<name>`); a neutral name (`example`, `user`,
  `runner`, a container's or a cloud machine's user such as `node` or `ubuntu`), a one-letter name or a placeholder
  (`<name>`, `$USER`) is not a finding;
- `secret`: a value shaped like a credential by the contract's detector (fabric_secrets.py, DEC-0044), read line by
  line: a provider key starting a word, a JWT, a bearer token, or a long run mixing upper case, lower case and digits
  assigned to a name that can only carry a credential (a bare long run, such as an integrity hash, is not; a whole
  Ed25519 signature under a JSON `"sig"`, `"signature"` or `"signatures"` member, as `sign` writes it, is public); or a private key: a PEM, OpenSSH or PGP
  block, or a JWK's `d`; a URL that carries a password or a credential in its query; a file that is a credential by
  its name (pack's rule: `.env`, `*.pem`, `*.key`, `.npmrc` ...) or a kit credential file (`*.token`, `board.credential`). A value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) is
  not a finding;
- `instance-string`: a string from the owner's list of instance strings (names, accounts, hosts), kept outside the tree.

A file's path is read as a line is (line 0). It never prints a value it found, a line that holds one, an entry of the
owner's list or the folder it checks: a finding names its path (an entry of the list, a home folder's name or a
credential-shaped value in the path printed as `<line N>`, `<home>` or `<secret>`), line, kind and rule, and an
instance string by its line in the owner's list. It changes nothing. Exit 0: every file was read and none holds a
finding; 1: at least one finding; 2: the check could not run, or a file was not read: an unreadable file, a nested
repository, or a binary one the ignore file does not name as source. A file not read is listed by its path.

  fabric_source_check.py check [ROOT] [--instance-strings FILE] [--exclude GLOB ...] [--every-file] [--json]

The files read are those Git would commit (`git ls-files --cached --others --exclude-standard`), as they are in the
work tree (a staged copy that differs is not read). With `--every-file`, every file but `.git`, `__pycache__`,
`.DS_Store` and `*.pyc`, which `pack` refuses as litter (what `pack` reads). When ROOT is not in a Git checkout or Git lists nothing in it, every file outside `.git`,
`__pycache__`, `node_modules`, virtual environments and caches; the dependency folders it leaves are named. A committed symbolic link is checked by the path it names, never followed. A binary file (a NUL byte in
its first 8 KiB) is not read; it is listed. Globs in ROOT's `.fabric-source-ignore` (one per line, `#`
comments) and `--exclude` leave matching paths out. The owner's list is `--instance-strings`, else the file
`FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
(`$XDG_CONFIG_HOME` or `~/.config`; `%APPDATA%` on Windows) when it exists: one string per
line, `#` comments, strings shorter than three characters ignored, matched without regard to case. A list inside ROOT
is refused: it would travel with the source. The summary says whether Git chose the files or every file was read.
Standard library only.
"""

# #region source-check — docs: plugins/fabric-agent-adapter/skills/creating-fabric-agents/references/source-and-instance.md#the-check

from __future__ import annotations

import argparse
import bisect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import unquote
from typing import Dict, Iterable, List, NoReturn, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
_WROTE_BYTECODE, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # a copy inside the checked tree adds no .pyc
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file
sys.dont_write_bytecode = _WROTE_BYTECODE

IGNORE_FILE = ".fabric-source-ignore"
LIST_NAME = "instance-strings.txt"
#: The folders `pack` refuses to carry (fabric_package.JUNK); --every-file leaves them and the files below unread.
PACK_REFUSES = {".git", "__pycache__"}
WALK_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
#: Names that stand for nobody in a home path: placeholders, CI runners and the system's shared folders.
NEUTRAL_HOMES = {"example", "examples", "user", "username", "you", "me", "name", "someone", "runner", "shared", "public",
                 "default", "guest", "linuxbrew", "alice", "bob", "operator", "owner", "person", "your-name", "yourname",
                 # the users of container images, cloud machines and hosted CI
                 "node", "ubuntu", "ec2-user", "runneradmin", "admin", "vagrant", "debian", "centos", "app", "builder"}
_SEP = r"(?:\\|/)+"  # one way to read a run: two alternatives that both take a `\\` backtrack exponentially
HOME_PATHS = (
    re.compile(r"(?<![A-Za-z0-9_.-])(?:/var)?/home/([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII),
    # macOS writes `/Users` capitalised; `/users/...` in code is a web route
    re.compile(r"(?<![A-Za-z0-9_.-])/Users/([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII),
    # Git Bash's `/c/Users/<name>` and WSL's `/mnt/c/Users/<name>`
    re.compile(r"(?<![A-Za-z0-9_.-])(?:/mnt)?/[A-Za-z]/Users/([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII),
    re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:%sUsers%s([A-Za-z0-9][A-Za-z0-9._-]*)" % (_SEP, _SEP), re.ASCII | re.IGNORECASE),
    # DEC-0105's dashed form starts a name; after a dash it is a flag or a CSS variable (`--home-dir`)
    # (on Windows a drive comes first: `C--Users-<name>-proj`; Silverblue's, WSL's and Git Bash's homes dash to
    # `-var-home-<name>`, `-mnt-c-Users-<name>` and `-c-Users-<name>`)
    re.compile(r"(?:^|[^A-Za-z0-9-])(?:-Users|-home|-var-home|(?:-mnt)?-[A-Za-z]-Users)-([A-Za-z0-9][A-Za-z0-9._]*)",
               re.ASCII),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]--Users-([A-Za-z0-9][A-Za-z0-9._]*)", re.ASCII | re.IGNORECASE),
    re.compile(r"%2[Ff](?:Users|home)%2[Ff]([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII),  # `%2Fusers%2F` is a route
    re.compile(r"%5CUsers%5C([A-Za-z0-9][A-Za-z0-9._-]*)", re.ASCII | re.IGNORECASE),
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")  # PEM, OpenSSH, PGP
#: A private JWK's `d` (`sign --key` takes an Ed25519 one): 32 bytes or more in base64url.
JWK_PRIVATE = re.compile(r"\\?[\"']d\\?[\"'][ \t]*:[ \t]*\\?[\"']([A-Za-z0-9_-]{43,})")  # JSON, escaped, Python
#: Words a documented or synthetic credential carries (AWS's `...EXAMPLE`, `sk-test-not-a-key`); a random key does not.
SYNTHETIC = ("example", "not-a-key", "notakey", "fake", "dummy", "placeholder", "redacted")
# The detector's provider-key shapes without its first alternative, `^bearer\s.+`, which reads a whole header value: in
# a file it would take prose that starts with the word and hide a key later on the same line. A bearer token is looked
# for as `_BEARER_INSIDE` does: the word, then a run of 12 or more with a digit.
_BEARER_FIRST = "(^bearer["
if not _secrets.SECRET_VALUE.pattern.startswith(_BEARER_FIRST):  # not an assert: `python -O` would drop it
    raise ImportError("fabric_secrets.SECRET_VALUE changed its first branch; update fabric_source_check.py with it")
PROVIDER_KEY = re.compile("(" + _secrets.SECRET_VALUE.pattern.split("|", 1)[1], _secrets.SECRET_VALUE.flags)
#: Files that are credentials by their name: pack's own rule (fabric_package.SECRET_FILE and SECRET_FILE_OK, held
#: equal by test_source_check), and the kit's token files (`service.token`, fabric_auth; `board.credential`, fabric_hub).
_JS_DOT = "[^\n\r\u2028\u2029]"
SECRET_FILE = re.compile(r"\.env(\.%s+)?|%s*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc)"
                         % (_JS_DOT, _JS_DOT))
SECRET_FILE_OK = re.compile(r"\.env\.(example|sample|template)")
_PACK_JUNK_FILE = re.compile(r"\.DS_Store|%s*\.pyc" % _JS_DOT)  # held to fabric_package.JUNK by test_source_check
TOKEN_FILE = re.compile(r".+\.(token|credential)")  # the kit's service.token and board.credential
#: An absolute URL in a line, read whole by `_url_secret`: a password in it, a credential in its query.
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{0,63}://[^\s\"'<>`]+")  # a bounded scheme: linear, and `${X:-pg://..}`
#: `NAME = value`, `NAME: value` or `"name": "value"`: the long-run rule applies only where the name carries a credential.
#: The name is bounded and starts a word, so a long line is read in linear time.
ASSIGNED = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]{0,63})[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?"
                      r"((?:[A-Za-z0-9+/_-]|%[0-9A-Fa-f]{2}){40,}={0,2})")  # `=` only as padding; `%2B` read decoded


class CheckError(Exception):
    pass


def _home_names(text: str) -> List[Tuple[int, int]]:
    """The spans of the names of real people's home folders in a text (neutral and one-letter names left out)."""
    spans = []
    for pattern in HOME_PATHS:
        for match in pattern.finditer(text):
            name = match.group(1).lower()
            if len(name) > 1 and name not in NEUTRAL_HOMES:  # a one-letter home (`/Users/a`) is a test's placeholder
                spans.append(match.span(1))
    return spans


def _real(token: str) -> bool:
    lowered = token.lower()
    return not any(word in lowered for word in SYNTHETIC)


#: An Ed25519 signature is public: `sign` writes one into fabric.package.json (`"sig"`), and every signed record carries
#: one. Only a whole one (64 bytes, 86 base64url characters) is: a storage URL's `sig=` (an HMAC) grants access.
PUBLIC_NAMES = {"sig", "signature", "signatures"}
_ED25519_SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}")


def _credential(name: str, value: str, quoted: bool) -> bool:
    """A credential's name, but a whole Ed25519 signature as a JSON member (`"sig": "..."`, as `sign` writes it)."""
    if quoted and name.lower() in PUBLIC_NAMES and _ED25519_SIGNATURE.fullmatch(value):
        return False
    return _secrets.credential_name(name)


_COLON_AFTER = re.compile(r"[ \t]*:")


def _quoted(text: str, match: "re.Match[str]") -> bool:
    """`"name": value`: a JSON member, the name quoted on both sides and `:` after it (never `"sig=...`)."""
    start, end = match.start(1), match.end(1)
    # matched in place: a copy of the rest of the line for each member made a minified JSON line quadratic
    return start > 0 and text[start - 1] == '"' and text[end:end + 1] == '"' and _COLON_AFTER.match(text, end + 1) is not None


def _url_secret(url: str, depth: int = 0) -> bool:
    """A URL that carries a credential, as a source tree holds one. The contract's URL rule (LC-21) reads one value a
    launch names, where any `token=` is one; across a tree it would read every documented `?token=abc` and `user:pw@`.
    So: a password of 8 or more mixing letters and digits, or a query or fragment value that, percent-decoded, is shaped
    like a credential (a provider key, a JWT, a long random run under a credential's name)."""
    url = url.rstrip(".,;)]}")
    if not _secrets._SCHEME.match(url):
        return False
    password, query, fragment = _secrets._url_parts(url)
    # what says it is synthetic is the value, never the host or the path (`examples.blob.core.windows.net`)
    if len(password) >= 8 and re.search(r"[0-9]", password) and re.search(r"[A-Za-z]", password) and _real(unquote(password)):
        return True
    for part in (query, fragment):
        for name, raws in _secrets.raw_values(part).items():
            for raw in raws:
                value = unquote(raw)
                if depth < 2 and "://" in value and _url_secret(value, depth + 1):  # `?next=https%3A%2F%2F...sig%3D`
                    return True  # read before the synthetic filter: an inner URL is judged by its own values
                if any(True for _ in _provider_keys(value)):  # each key by its own word, as on a line
                    return True
                if not _real(value):
                    continue
                if (_secrets.credential_name(name) and _secrets._long_secret(value)) or \
                        _secrets.JWT_SHAPE.search(value) or _secrets.SECRET_VALUE.search(value):
                    return True
    return False


#: The JSON escapes tools write for `&`, `=` and `/` (Go's encoding/json writes `\u0026`, PHP's json_encode `\/`).
_JSON_ESCAPES = re.compile(r"\\(?:u0026|u003[dD]|/)")


_UNESCAPED = {"u0026": "&", "u003d": "=", "u003D": "=", "/": "/"}


def _json_unescaped(line: str) -> str:
    return _JSON_ESCAPES.sub(lambda m: _UNESCAPED[m.group(0)[1:]], line)


def _unescaped_with_origin(line: str) -> Tuple[str, List[Tuple[int, int]]]:
    """The line with JSON escapes undone, and for each of its characters the raw span it came from."""
    out: List[str] = []
    origin: List[Tuple[int, int]] = []
    last = 0
    for m in _JSON_ESCAPES.finditer(line):
        out.extend(line[last:m.start()])
        origin.extend((i, i + 1) for i in range(last, m.start()))
        out.append(_UNESCAPED[m.group(0)[1:]])
        origin.append(m.span())
        last = m.end()
    out.extend(line[last:])
    origin.extend((i, i + 1) for i in range(last, len(line)))
    return "".join(out), origin


def _secret_finding(line: str) -> Optional[str]:
    """`_secret_in`, on the line as written and, when it holds a JSON escape of `&`, `=` or `/`, as JSON reads it."""
    found = _secret_in(line)
    if found is None and "\\" in line:
        unescaped = _json_unescaped(line)
        if unescaped != line:
            found = _secret_in(unescaped)
    return found


#: A whole Ed25519 signature as `sign` writes it: public, so no rule reads it (not even a provider key's shape in it).
_PUBLIC_SIGNATURE = re.compile(r"\"(?:sig|signature|signatures)\"[ \t]*:[ \t]*\"[A-Za-z0-9_-]{86}\"", re.IGNORECASE)


def _secret_in(line: str) -> Optional[str]:
    if '"' in line:
        line = _PUBLIC_SIGNATURE.sub('"sig": ""', line)
    if PRIVATE_KEY.search(line):
        return "a private key block"
    if any(_real(m.group(1)) for m in JWK_PRIVATE.finditer(line)):
        return "a private key (a JWK's `d`)"
    if any(_real(m.group(0)) for m in _secrets.JWT_SHAPE.finditer(line)):
        return "a token shaped like a JWT"
    # The detector reads one configuration value; across a line, `sk-` needs a word start of its own, or every name
    # with a segment ending in `sk` (`task-management-service`) would read as a key.
    if any(True for _ in _provider_keys(line)):
        return "a value shaped like a provider key"
    if any(_real(m.group(0)) for m in _overlapping(_secrets._BEARER_INSIDE, line)):
        return "a bearer token"
    if "://" in line and any(_url_secret(m.group(0)) for m in URL.finditer(line)):
        return "a URL that carries a credential"
    for m in (_assigned(line) if ":" in line or "=" in line else ()):
        name, value = m.group(1), m.group(2)
        if _credential(name, value, _quoted(line, m)) and _secrets._long_secret(unquote(value)) and _real(unquote(value)):
            return "a long random value assigned to a credential's name"
    return None


def _assigned(line: str) -> Iterable["re.Match[str]"]:
    """ASSIGNED's matches, each search starting again inside the last value: `id=<run>/TOKEN=<value>` reads both."""
    pos = 0
    while True:
        m = ASSIGNED.search(line, pos)
        if m is None:
            return
        yield m
        pos = m.start(2) if m.start(2) > pos else m.end()


def read_list(path: Path) -> List[str]:
    """The owner's list, one item per line: an entry casefolded, or '' for a comment, a blank or too short a line."""
    entries = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        entries.append("" if not text or text.startswith("#") or len(text) < 3 else text.casefold())
    return entries


def _entry_spans(text: str, entries: List[str]) -> List[Tuple[int, int, int]]:
    folded = text.casefold()
    spans = []
    if len(folded) != len(text):  # casefolding changed the length (ß, ﬁ): match, but mask the whole text
        return [(0, len(text), n) for n, e in enumerate(entries, 1) if e and e in folded][:1]
    for number, entry in enumerate(entries, 1):
        if entry:
            start = folded.find(entry)
            while start != -1:
                spans.append((start, start + len(entry), number))
                start = folded.find(entry, start + 1)
    return spans


def _instance_finding(text: str, entries: List[str]) -> Optional[str]:
    spans = _entry_spans(text, entries)
    return "a string from the owner's list (line %d)" % spans[0][2] if spans else None


def _alternatives(pattern: "re.Pattern[str]") -> List[Tuple["re.Pattern[str]", ...]]:
    """Each provider-key alternative of the contract's pattern as (its starts, its prefix, a run of its class, least
    length, open-ended, the whole alternative), so a key is read where its own class ends, not where another's does."""
    found = []
    for alt in pattern.pattern[1:-1].split("|"):
        part = re.fullmatch(r"(.+?)(\[[^\]]+\])\{(\d+)(,?)\}", alt)
        if part is None:  # not an assert: `python -O` would drop it
            raise ImportError("fabric_secrets.SECRET_VALUE has a key shape this check cannot read: %s" % alt[:12])
        prefix, cls, least, open_ended = part.groups()
        found.append((re.compile("(?=%s)" % prefix, pattern.flags), re.compile(prefix, pattern.flags),
                      re.compile(cls + "+", pattern.flags), int(least), bool(open_ended), re.compile(alt, pattern.flags)))
    return found


_KEY_SHAPES = _alternatives(PROVIDER_KEY)
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _provider_keys(text: str) -> Iterable[Tuple[int, int]]:
    """The spans of provider keys that start a word and do not say they are synthetic, each read where it starts, so a
    key a dropped run swallowed is found too (`task-runner-sk-<key>`, `sk-<16>_ghp_<key>_fake`). Every start is read
    once, by its own class's run end and the next synthetic word in the line: O(n log n) on any line."""
    if not PROVIDER_KEY.search(text):
        return
    lowered = text.translate(_ASCII_LOWER)  # a key's characters are ASCII, and this keeps every offset
    synthetic = [(len(word), [m.start() for m in re.finditer("(?=%s)" % re.escape(word), lowered)]) for word in SYNTHETIC]
    for starts, prefix, run, least, open_ended, whole in _KEY_SHAPES:
        runs = None
        for m in starts.finditer(text):
            p = m.start()
            if p and text[p - 1].isalnum():
                continue
            if open_ended:
                if runs is None:
                    runs = [r.span() for r in run.finditer(text)]
                    run_starts = [a for a, _ in runs]
                q = p + len(prefix.match(text, p).group(0))
                i = bisect.bisect_right(run_starts, q) - 1
                if i < 0 or runs[i][1] - q < least:
                    continue
                end = runs[i][1]
            else:
                key = whole.match(text, p)
                if key is None:
                    continue
                end = key.end()
            if not any(k < len(at) and at[k] + n <= end
                       for n, at in synthetic for k in (bisect.bisect_left(at, p),)):
                yield p, end


def _overlapping(pattern: "re.Pattern[str]", text: str) -> Iterable["re.Match[str]"]:
    """Matches that may start inside the last one (a second `Bearer` inside the first token's run gets its own span)."""
    pos = 0
    while pos <= len(text):
        m = pattern.search(text, pos)
        if m is None:
            return
        yield m
        pos = m.start() + 1


def _secret_spans(text: str) -> List[Tuple[int, int]]:
    """The spans of credential-shaped values in a text, as `_secret_in` reads them (a public signature is no span)."""
    public = [m.span() for m in _PUBLIC_SIGNATURE.finditer(text)] if '"' in text else []
    return [(a, b) for a, b in _raw_secret_spans(text) if not any(p <= a and b <= q for p, q in public)]


def _raw_secret_spans(text: str) -> List[Tuple[int, int]]:
    spans = [m.span() for m in PRIVATE_KEY.finditer(text)]
    spans += [m.span() for m in _secrets.JWT_SHAPE.finditer(text) if _real(m.group(0))]
    spans += [m.span(1) for m in JWK_PRIVATE.finditer(text) if _real(m.group(1))]
    spans += list(_provider_keys(text))
    spans += [m.span() for m in _overlapping(_secrets._BEARER_INSIDE, text) if _real(m.group(0))]
    spans += [m.span() for m in URL.finditer(text) if _url_secret(m.group(0))]
    spans += [m.span(2) for m in _assigned(text)
              if _credential(m.group(1), m.group(2), _quoted(text, m)) and _secrets._long_secret(unquote(m.group(2)))
              and _real(unquote(m.group(2)))]
    return spans


def redact(path: str, entries: List[str], seen: Optional["_Seen"] = None) -> str:
    """A path as it may be printed: an owner's string as `<line N>` (its line in the owner's list), a real home
    folder's name as `<home>`, and each segment in which `_secret_finding` finds a credential as `<secret>`, whole
    (a span inside a segment can miss a second value the first one runs into). While the segments left still hold a
    credential together (`https:\\/\\/app:<pw>@db/x`), the segments that finding's spans touch are masked, else the
    last one left, so what is printed holds no finding and its first folders still name the place. With `seen`, what the
    check found elsewhere in the tree is masked too: a home name at every occurrence, and a segment holding a run of 8
    characters of a found value as `<secret>`."""
    spans, offset = [], 0
    for segment in path.split("/"):
        spans.append((offset, offset + len(segment)))
        offset += len(segment) + 1
    masked = [bool(_secret_finding(path[a:b])) for a, b in spans]
    # every segment a found value's span touches, on the path and with JSON escapes undone (mapped back), so a value
    # that runs across a `/` prints no part of itself
    touched = list(_secret_spans(path))
    if "\\" in path:
        unescaped, origin = _unescaped_with_origin(path)
        if unescaped != path:
            touched += [(origin[a][0], origin[b - 1][1]) for a, b in _secret_spans(unescaped) if b > a]
    for a, b in touched:
        for i, (s, e) in enumerate(spans):
            if s < b and a < e:
                masked[i] = True

    def rest() -> str:
        # a masked segment keeps its length, so the spans read in what is left are offsets in the path
        return "/".join(" " * (b - a) if m else path[a:b] for (a, b), m in zip(spans, masked))

    # the guard: while what is left still holds a credential, mask the segments its spans touch, else the last one left
    for _ in range(len(spans)):
        left = rest()
        if not _secret_finding(left):
            break
        in_left = _secret_spans(left)  # once a pass: read per segment, a long path cost the cube of its folders
        if "\\" in left:  # a finding only the unescaped reading sees has its spans there, mapped back
            unescaped, origin = _unescaped_with_origin(left)
            if unescaped != left:
                in_left += [(origin[a][0], origin[b - 1][1]) for a, b in _secret_spans(unescaped) if b > a]
        hit = [i for i, (s, e) in enumerate(spans) if not masked[i] and any(s < b and a < e for a, b in in_left)]
        if not hit:
            hit = [max(i for i, m in enumerate(masked) if not m)]
        for i in hit:
            masked[i] = True
    if seen is not None and seen.grams:  # a segment holding a run of a value found elsewhere in the tree
        for i, (a, b) in enumerate(spans):
            if not masked[i] and any(path[k:k + 8] in seen.grams for k in range(a, b - 7)):
                masked[i] = True
    secret_segments = [span for span, m in zip(spans, masked) if m]
    marks = [(s, e, "<line %d>" % n) for s, e, n in _entry_spans(path, entries)]
    found = _home_names(path)
    marks += [(s, e, "<home>") for s, e in found]
    names = {path[s:e] for s, e in found} | (seen.names if seen is not None else set())
    # every other occurrence of a found name, searched in the path itself: a lowered copy can change its length (U+0130),
    # and Unicode case matching also takes the letters that fold to ASCII ones (U+212A to `k`, U+017F to `s`)
    for name in names:
        marks += [(m.start(), m.end(), "<home>") for m in re.finditer(re.escape(name), path, re.IGNORECASE)]
    marks += [(s, e, "<secret>") for s, e in secret_segments]
    out, last = [], 0
    for start, end, label in sorted(marks):
        if start < last:  # overlapping marks: the first covers the union, so no part of either is printed
            last = max(last, end)
            continue
        out += [path[last:start], label]
        last = end
    return "".join(out) + path[last:]


def _git() -> Optional[str]:
    """`git` from PATH's absolute folders only. On Windows CreateProcess looks in the current folder first (and
    shutil.which there puts the current folder first too), so a tree checked from inside could run its own git.exe."""
    if os.name != "nt":
        return "git"
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder and os.path.isabs(folder):
            for name in ("git.exe", "git.cmd", "git.bat"):
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    return candidate
    return None


def _git_files(root: Path) -> Optional[List[str]]:
    git = _git()
    if git is None:
        return None
    try:
        # `core.fsmonitor` off: `--others` would run a command the checked tree's own configuration names. Empty, not
        # `false`: Git before 2.36 reads the value as a hook and would run a program named `false` from PATH
        result = subprocess.run([git, "-c", "core.fsmonitor=", "-C", str(root), "ls-files", "-z", "--cached",
                                 "--others", "--exclude-standard"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return sorted({p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p})


def _walk_files(root: Path, unreadable: List[str], skip: Iterable[str] = WALK_SKIP,
                left: Optional[List[str]] = None) -> List[str]:
    """Every file under root but the folders in skip; each folder skipped is named in left."""
    found = []
    skip = set(skip)

    def failed(error: OSError) -> None:
        unreadable.append(Path(str(error.filename or root)).relative_to(root).as_posix())

    for folder, dirs, files in os.walk(root, onerror=failed):
        if left is not None:
            left += [Path(folder, d).relative_to(root).as_posix() for d in dirs
                     if d in skip and d not in PACK_REFUSES]  # `.git` and `__pycache__`: --every-file leaves them too
        dirs[:] = [d for d in dirs if d not in skip]
        # os.walk lists a link to a folder with the folders and does not follow it: check it as Git would, by its target
        files = files + [d for d in dirs if os.path.islink(os.path.join(folder, d))]
        for name in files:
            if name in skip and name == ".git":  # a worktree's or a submodule's `.git` file: never carried, never source
                continue
            if skip == PACK_REFUSES and _PACK_JUNK_FILE.fullmatch(name):  # --every-file: litter pack refuses, never carried
                continue
            found.append(Path(folder, name).relative_to(root).as_posix())
    return sorted(found)


_GLOBS: Dict[str, "re.Pattern[str]"] = {}


def _glob(glob: str) -> "re.Pattern[str]":
    """A line of the ignore file read from the tree's root: `*`, `?` and `[...]` stay inside one folder, `**` crosses
    folders (`**/` also matches none). fnmatch's `*` would cross `/`, so `vectors/*.json` would leave out
    `vectors/private/live.json`. Raises re.error for a class Python cannot read (`[9-0]`)."""
    if glob not in _GLOBS:
        out, i = [], 0
        while i < len(glob):
            c = glob[i]
            if glob.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if glob.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            if c == "*":
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            elif c == "[":
                j = i + 1 + (glob[i + 1:i + 2] == "!")
                j += glob[j:j + 1] == "]"
                end = glob.find("]", j)
                if end < 0:
                    out.append(re.escape(c))
                else:
                    inner = glob[i + 1:end].replace("\\", "\\\\")
                    negated, body = inner.startswith("!"), inner[inner.startswith("!"):]
                    if body[:1] in ("^", "["):  # a literal there, as fnmatch reads it
                        body = "\\" + body
                    out.append("(?!/)[%s%s]" % ("^" if negated else "", body))
                    i = end
            else:
                out.append(re.escape(c))
            i += 1
        _GLOBS[glob] = re.compile("(?s:%s)\\Z" % "".join(out))
    return _GLOBS[glob]


def _readable_glob(glob: str) -> bool:
    """Whether every form `_ignored` tries can be read: a reversed range (`[9-0]`) is refused on every Python."""
    try:
        for form in (glob, glob.rstrip("/") + "/**", glob.rstrip("/")):
            _glob(form)
    except re.error:
        return False
    return True


def ignore_globs(root: Path, extra: Iterable[str]) -> List[str]:
    globs = list(extra)
    if not all(_readable_glob(g) for g in globs):
        raise CheckError("an --exclude glob cannot be read")
    ignore = root / IGNORE_FILE
    try:
        present = ignore.is_file()
    except OSError:
        raise CheckError("the folder cannot be read")
    if present:
        try:
            lines = ignore.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            raise CheckError("%s cannot be read as UTF-8" % IGNORE_FILE)
        for number, line in enumerate(lines, 1):
            glob = line.strip()
            if glob and not glob.startswith("#"):
                if not _readable_glob(glob):
                    raise CheckError("line %d of %s is not a glob it can read" % (number, IGNORE_FILE))
                globs.append(glob)
    return globs


def _ignored(path: str, globs: List[str], root: Optional[Path] = None) -> bool:
    if any(_glob(g).match(path) or _glob(g.rstrip("/") + "/**").match(path) for g in globs):
        return True
    # `vendor/sub/` names a folder, and Git lists a submodule there as `vendor/sub`, with no slash: only a path that
    # is a folder on disk (never a file a wildcard such as `src/*/` would also reach) is left out by it
    return root is not None and any(g.endswith("/") and _glob(g.rstrip("/")).match(path) for g in globs) \
        and os.path.isdir(str(root / path)) and not os.path.islink(str(root / path))


def _lines(data: bytes) -> Iterable[Tuple[int, str]]:
    """Lines as an editor numbers them: split at LF, a trailing CR dropped (str.splitlines also splits at FF, VT...)."""
    for number, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        yield number, line[:-1] if line.endswith("\r") else line


def _text_findings(text: str, entries: List[str], seen: Optional["_Seen"] = None) -> List[Tuple[str, str]]:
    found = []
    homes = _home_names(text)
    if homes:
        found.append(("home-path", "a path inside a person's home folder"))
        if seen is not None:
            seen.names.update(text[a:b] for a, b in homes)
    secret = _secret_finding(text)
    if secret:
        found.append(("secret", secret))
        if seen is not None:
            seen.add_values(text)
    rule = _instance_finding(text, entries)
    if rule:
        found.append(("instance-string", rule))
    return found


class _Seen:
    """What the check found anywhere in the tree, so that no printed path repeats it: a file named after its owner, or
    after the key it holds, prints with the name as `<home>` and the segment as `<secret>`."""

    def __init__(self) -> None:
        self.names: Set[str] = set()
        self.grams: Set[str] = set()  # every 8-character run of a found value

    def add_values(self, text: str) -> None:
        values = [text[a:b] for a, b in _secret_spans(text)]
        if "\\" in text:
            unescaped, _ = _unescaped_with_origin(text)
            if unescaped != text:
                values += [unescaped[a:b] for a, b in _secret_spans(unescaped)]
        for value in values:
            value = value[:4096]  # a path segment is at most 255 characters
            self.grams.update(value[i:i + 8] for i in range(max(0, len(value) - 7)))


def check(root: Path, entries: List[str], globs: List[str], every_file: bool = False) -> Dict[str, object]:
    """Read the tree and return {files, skipped, findings}; a finding is {path, line, kind, rule}, its path redacted."""
    unreadable: List[str] = []
    files = None if every_file else _git_files(root)
    mode = "git"
    dependencies: List[str] = []  # dependency folders the walk leaves unread: named, so a clean result says so
    if every_file:  # what `pack` reads: every file, ignored or not; `.git` and `__pycache__` it refuses to pack
        files, mode = _walk_files(root, unreadable, PACK_REFUSES), "walk"
    elif not files:  # not a checkout, Git refused it, or a folder Git ignores or holds nothing of: read what is there
        files, mode = _walk_files(root, unreadable, WALK_SKIP, dependencies), "walk"
    findings: List[Dict[str, object]] = []
    read = 0
    skipped = {"binary": 0, "unreadable": len(unreadable), "excluded": 0, "nested": 0, "dependencies": len(dependencies)}
    # paths are redacted once the whole tree is read, with what was found anywhere in it (`_Seen`)
    not_read: List[Dict[str, str]] = [{"path": p, "why": "unreadable"} for p in unreadable]
    seen = _Seen()

    def add(path: str, line: int, kind: str, rule: str) -> None:
        findings.append({"path": path, "line": line, "kind": kind, "rule": rule})

    for path in files:
        if _ignored(path, globs, root):
            skipped["excluded"] += 1
            continue
        for kind, rule in _text_findings(path, entries, seen):  # a name carries instance data as a line does
            add(path, 0, kind, rule + " in the file's path")
        name = path.rsplit("/", 1)[-1]
        if (SECRET_FILE.fullmatch(name) and not SECRET_FILE_OK.fullmatch(name)) or TOKEN_FILE.fullmatch(name):
            add(path, 0, "secret", "a file that is a credential by its name")
        full = root / path
        # os.path.islink, not Path.is_symlink: on Python 3.9 the latter raises on a folder it cannot search
        if any(os.path.islink(str(root / parent)) for parent in Path(path).parents if str(parent) != "."):
            # a tracked folder replaced by a link: the file Git lists is not here, and the link is never followed
            skipped["unreadable"] += 1
            not_read.append({"path": redact(path, entries), "why": "under a symbolic link"})
            continue
        try:
            if full.is_symlink():  # Git commits the path a link names: check it, never follow it
                read += 1
                for kind, rule in _text_findings(os.readlink(full), entries, seen):
                    add(path, 0, kind, rule + " in the link's target")
                continue
            kind = os.lstat(str(full)).st_mode
            if stat.S_ISDIR(kind):  # Git lists a submodule or a nested repository as one path: its files are not read
                skipped["nested"] += 1
                not_read.append({"path": redact(path, entries), "why": "a nested repository"})
                continue
            if not stat.S_ISREG(kind):  # a socket, a pipe: nothing a source carries
                continue
            with open(full, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:  # Git lists it and the work tree lacks it: deleted, or outside a sparse checkout
            skipped["unreadable"] += 1
            not_read.append({"path": redact(path, entries),
                             "why": "not in the work tree" if mode == "git" else "unreadable"})
            continue
        except OSError:
            skipped["unreadable"] += 1
            not_read.append({"path": redact(path, entries), "why": "unreadable"})
            continue
        if b"\0" in data[:8192]:
            skipped["binary"] += 1
            not_read.append({"path": redact(path, entries), "why": "binary"})
            continue
        read += 1
        for number, line in _lines(data):
            for kind, rule in _text_findings(line, entries, seen):
                add(path, number, kind, rule)
    printed: Dict[str, str] = {}  # one redaction per path, however many findings it has

    def shown(path: str) -> str:
        if path not in printed:
            printed[path] = redact(path, entries, seen)
        return printed[path]

    for entry in findings:
        entry["path"] = shown(str(entry["path"]))
    for entry in not_read:
        entry["path"] = shown(entry["path"])
    return {"mode": mode, "files": read, "skipped": skipped, "notRead": not_read, "findings": findings,
            "dependencies": [shown(d) for d in dependencies]}


def default_list(platform: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Path:
    """Where the owner's list is kept when none is named: the user's configuration folder, never a project's."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "win32":
        base = Path(env["APPDATA"]) if env.get("APPDATA") else Path.home() / "AppData" / "Roaming"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "passioncode-fabric" / LIST_NAME


def _list_path(given: Optional[str]) -> Tuple[Optional[Path], bool]:
    """The owner's list and whether it must be read (a named or an existing default list; else no list)."""
    named = given or os.environ.get("FABRIC_INSTANCE_STRINGS")
    if named:
        try:
            return Path(named).expanduser(), True
        except (RuntimeError, KeyError):  # `~user` with no such user (KeyError on 3.9): never "no finding"
            raise CheckError("the owner's list cannot be read")
    try:
        default = default_list()
    except (RuntimeError, KeyError):  # no HOME and no account entry (a container's arbitrary user)
        raise CheckError("there is no home folder to find the owner's list in: set XDG_CONFIG_HOME (APPDATA on "
                         "Windows) or name the list with --instance-strings")
    try:
        os.stat(str(default))
    except (FileNotFoundError, NotADirectoryError):
        # a link to a list, its folder or the configuration folder on a volume not mounted: there, but not reachable
        if any(os.path.lexists(str(p)) and not os.path.exists(str(p)) for p in (default, *default.parents)):
            raise CheckError("the owner's list in your configuration folder cannot be read")
        return None, False
    except OSError:  # a list that is there but cannot be reached is not "no list": that would fail open
        raise CheckError("the owner's list cannot be read")
    return default, True


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # argparse would repeat the arguments it could not read
        self.print_usage(sys.stderr)
        self.exit(2, "fabric_source_check.py: the arguments cannot be read; see the usage above\n")


def _print(text: str) -> None:
    """Print a line the console may not encode (a name in another script, a byte Git kept as a surrogate)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding, "replace"))


def run(argv: Optional[List[str]] = None) -> int:
    parser = _Parser(prog="fabric_source_check.py", description="Find instance data in an agent's source.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("check", help="read the source tree and report instance data without repeating it")
    cmd.add_argument("root", nargs="?", default=".")
    cmd.add_argument("--instance-strings", metavar="FILE")
    cmd.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    cmd.add_argument("--json", action="store_true")
    cmd.add_argument("--every-file", action="store_true", help="read every file, not only what Git would commit")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, or arguments argparse refused: the exit code, as the command line gives it
        return exc.code if isinstance(exc.code, int) else 2
    try:
        try:
            root = Path(args.root).expanduser().resolve()
            is_folder = root.is_dir()
        except (OSError, RuntimeError, KeyError):  # a parent it cannot search, a symlink loop, `~` with no home
            raise CheckError("the folder cannot be read")
        if not is_folder:
            raise CheckError("ROOT is not a folder")
        list_path, _ = _list_path(args.instance_strings)  # may raise CheckError
        entries: List[str] = []
        if list_path is not None:
            try:
                resolved = list_path.resolve()
            except (OSError, RuntimeError):  # RuntimeError: Python 3.9's symlink loop
                raise CheckError("the owner's list cannot be read")
            if resolved == root or root in resolved.parents:
                raise CheckError("the owner's list is inside the tree it checks, where it would travel with the source; "
                                 "keep it in your configuration folder (passioncode-fabric/%s)" % LIST_NAME)
            try:
                present = resolved.is_file()
            except OSError:
                raise CheckError("the owner's list cannot be read")
            if not present:
                raise CheckError("the owner's list named by --instance-strings or FABRIC_INSTANCE_STRINGS does not exist"
                                 if args.instance_strings or os.environ.get("FABRIC_INSTANCE_STRINGS")
                                 else "the owner's list in your configuration folder is not a file")
            try:
                entries = read_list(resolved)
            except UnicodeDecodeError:
                raise CheckError("the owner's list is not UTF-8")
            except OSError:
                raise CheckError("the owner's list cannot be read")
        result = check(root, entries, ignore_globs(root, args.exclude), args.every_file)
    except CheckError as exc:
        print("fabric_source_check.py: %s" % exc, file=sys.stderr)
        return 2
    findings = result["findings"]
    skipped = result["skipped"]
    listed = sum(1 for e in entries if e)
    # a binary file is not read either: it is complete only when every one is named as source in the ignore file
    complete = not (skipped["unreadable"] or skipped["binary"] or skipped["nested"])  # type: ignore[index]
    result.update({"instanceStrings": listed, "instanceList": list_path is not None, "blocking": bool(findings),
                   "complete": complete})
    if args.json:
        _print(json.dumps(result, indent=2))
    else:
        for f in findings:  # type: ignore[union-attr]
            _print("%s:%s: %s (%s)" % (f["path"], f["line"], f["kind"], f["rule"]))
        for n in result["notRead"]:  # type: ignore[union-attr]
            _print("%s: not read (%s)" % (n["path"], n["why"]))
        for folder in result["dependencies"]:  # type: ignore[union-attr]
            _print("%s: not read (a dependency folder; --every-file reads it)" % folder)
        if skipped["dependencies"]:  # type: ignore[index]
            _print("%d dependency folder(s) not read (node_modules, virtual environments, caches); --every-file reads "
                   "them" % skipped["dependencies"])  # type: ignore[index]
        _print("%d file(s) read (%s), %d finding(s); not read: %d binary, %d unreadable, %d nested repository; "
               "%d left out by name; %d instance string(s) listed%s"
               % (result["files"], "what Git would commit" if result["mode"] == "git" else
                  "every file, as pack reads them" if args.every_file else "every file but dependency folders, Git not used",
                  len(findings), skipped["binary"], skipped["unreadable"], skipped["nested"],  # type: ignore[index]
                  skipped["excluded"], listed,  # type: ignore[index]
                  "" if listed else (" (the owner's list holds no string of three or more characters)" if list_path
                                     else " (no owner's list)")))
    if findings:
        return 1
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(run())

# #endregion source-check
