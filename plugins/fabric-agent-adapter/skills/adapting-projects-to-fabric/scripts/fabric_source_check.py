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
`__pycache__`, `node_modules`, virtual environments and caches; the dependency folders it leaves are named (so too
when no `git` is found in PATH's absolute folders, or with PATH unset in `/bin` and `/usr/bin`; on Windows with PATH
unset the walk is used). A committed symbolic link is checked by the path it names, never followed. A binary file (a NUL byte in
its first 8 KiB) is not read; it is listed. Globs in ROOT's `.fabric-source-ignore` (one per line, `#`
comments) and `--exclude` leave matching paths out. The owner's list is `--instance-strings`, else the file
`FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
(`$XDG_CONFIG_HOME` when it is absolute, else `~/.config`; `%APPDATA%` on Windows) when it exists: one string per
line, a line starting with `#` a comment, `home: <name>` declaring the owner's home name (never neutral), strings
shorter than three characters ignored, matched without regard to case. A list inside ROOT
is refused: it would travel with the source. The summary says whether Git chose the files or every file was read.
Under a locale whose file-system encoding is not UTF-8 the check restarts itself in Python's UTF-8 mode, so a name,
an argument and a file are read in one encoding. Standard library only.

Under a source manifest (DEC-0149, FAA-261): when ROOT holds `fabric.source.json`, the manifest decides what is source
and the contract's tree check reads it (fabric_source_tree.py, held to the contract's vectors): blocking findings exit
1, warnings alone (`email`, `link-outside`, `no-license`, `unused-exclude`, `excluded-by-fold`) exit 0, a source file
not read exits 2; each finding names its path, line and column, never the text found. `.fabric-source-ignore` and
`--exclude` are not read there.
"""
# Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).

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
import unicodedata
from urllib.parse import unquote
from typing import Dict, Iterable, List, NoReturn, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
_WROTE_BYTECODE, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # a copy inside the checked tree adds no .pyc
_STEP = "fabric_secrets"  # the sibling being loaded, so a refusal names it whatever the exception says
try:
    import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file
    _STEP = "fabric_source_ignore"
    from fabric_source_ignore import (  # noqa: E402,F401 - how the ignore lines are read, beside this file
        IGNORE_FILE, CheckError, _as_bytes, _glob, _ignored, _line, _readable_glob, ignore_globs)
    _STEP = "fabric_source_restart"
    from fabric_source_restart import _interpreter, _interpreter_flags, _keep_console, _utf8_restart  # noqa: E402,F401
    _STEP = "fabric_source_homes"
    from fabric_source_homes import (  # noqa: E402,F401 - how a declared home is read, beside this file
        HOME_ENTRY, _NAME_JOIN, _NAME_START, _SEP, _dashed_home, _name_parts, _owner_homes, _spellings)
except Exception as _missing:  # a copy without its siblings, or mixed from two versions: a refusal, never exit 1
    # the exception's own text is never printed: an OSError's carries a path, which may be under the owner's home
    _why = "a module beside this file refused to load"
    try:
        _HERE, _sibling = Path(__file__).resolve().parent, _STEP + ".py"
        _file = getattr(_missing, "filename", None) if isinstance(_missing, OSError) else None
        _why = ("%s must sit beside this file" % _sibling if not (_HERE / _sibling).is_file()
                else "%s beside this file cannot be read" % _sibling
                if isinstance(_file, (str, bytes)) and Path(os.fsdecode(_file)).resolve() == _HERE / _sibling
                else "%s beside this file is from another version: copy it with this one" % _sibling
                if isinstance(_missing, (ImportError, SyntaxError))
                else "%s beside this file refused to load (%s): copy the scripts folder whole, from one version"
                % (_sibling, type(_missing).__name__))
    except Exception:  # naming the cause must never be what fails
        pass
    sys.stderr.write("fabric_source_check.py: %s\n" % _why)
    sys.exit(2)
finally:
    sys.dont_write_bytecode = _WROTE_BYTECODE

LIST_NAME = "instance-strings.txt"
#: The folders `pack` refuses to carry (fabric_package.JUNK); --every-file leaves them and the files below unread.
PACK_REFUSES = {".git", "__pycache__"}
WALK_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}
#: Names that stand for nobody in a home path: placeholders, CI runners and the system's shared folders.
NEUTRAL_HOMES = {"example", "examples", "user", "username", "you", "me", "name", "someone", "runner", "shared", "public",
                 "default", "guest", "linuxbrew", "alice", "bob", "operator", "owner", "person", "your-name", "yourname",
                 # the users of container images, cloud machines and hosted CI
                 "node", "ubuntu", "ec2-user", "runneradmin", "admin", "vagrant", "debian", "centos", "app", "builder",
                 # dev containers and hosted workspaces, and the reference's own fixture id
                 "vscode", "codespace", "circleci", "gitpod", "jovyan", "coder", "example-agent"}
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
# This check's own key shapes, the detector's before DEC-0151 (unbounded, ASCII case-insensitive), apart from the shared
# SECRET_VALUE for parity with the contract's tree check (KEY_SHAPE_SOURCES, `src/source-rules.ts` at the pin; CT-207,
# FAA-258). Not the detector's `^bearer\s.+`, which reads a whole header value and would take prose that starts with the
# word: a bearer token is looked for as `_BEARER_INSIDE` does, the word, then a run of 12 or more with a digit.
KEY_SHAPE_SOURCES = ("sk-[A-Za-z0-9_-]{16,}", "gh[pousr]_[A-Za-z0-9]{20,}", "xox[abposr]-[A-Za-z0-9-]{10,}", "AKIA[0-9A-Z]{16}", "glpat-[A-Za-z0-9_-]{20,}")
PROVIDER_KEY = re.compile("(" + "|".join(KEY_SHAPE_SOURCES) + ")", re.IGNORECASE | re.ASCII)
#: A URL parameter's value read as the contract's tree check reads it (`URL_SECRET_VALUE` in `src/source-rules.ts`): the
#: detector's whole-value `^bearer` branch and this check's own unbounded shapes, never the shared DEC-0151 detector.
URL_SECRET_VALUE = re.compile("(^bearer[" + _secrets.JS_SPACE + "]" + _secrets._NOT_LINE_END + "+|" + "|".join(KEY_SHAPE_SOURCES) + ")",
                              re.IGNORECASE | re.ASCII)
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


def _home_names(text: str, owner: Iterable[str] = ()) -> List[Tuple[int, int]]:
    """The spans of the names of real people's home folders in a text (neutral and one-letter names left out, unless
    the owner's list declares the name as the owner's home)."""
    owner = set(owner)
    spans = []
    for pattern in HOME_PATHS:
        for match in pattern.finditer(text):
            name = match.group(1).lower()
            if name in owner or (len(name) > 1 and name not in NEUTRAL_HOMES):  # one letter (`/Users/a`): a placeholder
                spans.append(match.span(1))
    for pattern in (p for name in sorted(owner) for p in _dashed_home(name)):  # declared: found whatever it reads as
        spans += [match.span(1) for match in pattern.finditer(text)]
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
    password, query, fragment = _secrets.url_parts(url)
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
                        _secrets.JWT_SHAPE.search(value) or URL_SECRET_VALUE.search(value):
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


def _fold_map(text: str) -> Tuple[str, List[int], List[int]]:
    """Text as an entry is compared, with where each of its characters came from: each letter with the marks after it
    is casefolded, then composed (NFC), so `é` typed in the list finds a name a file system stored decomposed (macOS
    names made through its file-system representation are) and `ß` finds `ss`. Folding changes lengths both ways, so a
    match is mapped back to the original characters through the starts and ends, never by its offsets."""
    out: List[str] = []
    starts: List[int] = []
    ends: List[int] = []
    run = 0
    last = text[:1]  # the last character of the piece composed so far: what the next one may compose with
    for k in range(1, len(text) + 1):
        if k < len(text):
            joined = unicodedata.normalize("NFC", last + text[k])
            if unicodedata.combining(text[k]) or len(joined) < len(last) + 1:  # a mark, or a jamo or vowel sign
                last = joined[-1:]
                continue
            last = text[k]
        piece = unicodedata.normalize("NFC", text[run:k].casefold())
        out.append(piece)
        starts += [run] * len(piece)
        ends += [k] * len(piece)
        run = k
    return "".join(out), starts, ends


def _fold(text: str) -> str:
    return _fold_map(text)[0]


#: `home: <name>`: one ASCII name (a letter or digit first; letters, digits, `.`, `_`, `-`, `'` and spaces inside, as
#: a Windows profile may hold), a horizontal space (a space, a tab, a Unicode space) around the colon; any other white
#: space there is refused. The name is checked as ASCII apart: IGNORECASE alone would
#: let `[A-Za-z]` take U+017F and U+212A.
_GAP = "[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]*"  # a horizontal space only: never a control or a separator
_HOME_LINE = re.compile(r"home%s:%s([A-Za-z0-9](?:[A-Za-z0-9._' -]*[A-Za-z0-9._'-])?)" % (_GAP, _GAP), re.IGNORECASE)
_HOME_KEY = re.compile(r"home\s*:", re.IGNORECASE)  # any white space, so a control or a separator is refused


def read_list(path: Path) -> List[str]:
    """The owner's list, one item per line: an entry casefolded, a declared home (`home: <name>`) as HOME_ENTRY and the
    name lowered, or '' for a comment, a blank or too short a line."""
    entries = []
    # at CRLF, CR or LF: a list saved with CR alone keeps its lines, and a FF or U+2028 starts none
    for raw in re.split(r"\r\n|\r|\n", path.read_bytes().decode("utf-8-sig")):
        # a byte-order mark or a zero-width character at a line's start (two lists joined) is no part of the line
        if HOME_ENTRY in raw:  # never read as another name: a NUL is no character an owner types
            raise CheckError("line %d of the owner's list holds a NUL character: save it as plain text" % (len(entries) + 1))
        text = raw.strip().lstrip("\ufeff\u200b\u2060").strip()  # no meaning at a start
        # a joiner (U+200C, U+200D) may belong to a string, never to `home:`: a home line is read or refused with every
        # format character (Unicode Cf: a joiner, a direction mark, a soft hyphen) taken out, wherever it stands
        bare = "".join(c for c in text if unicodedata.category(c) != "Cf").strip()
        home = _HOME_LINE.fullmatch(bare)
        # the name as written: a format character inside it changes the name, so that line is refused, not read as another
        # (looked for after the key's colon, so the letters of `home` cannot stand in for a name such as `me`)
        if home and home.group(1).isascii() and home.group(1) in text.split(":", 1)[1]:
            entries.append(HOME_ENTRY + home.group(1).lower())
            continue
        if home and home.group(1).isascii():  # visible as a home name, but an invisible character sits inside it
            raise CheckError("line %d of the owner's list names a home that holds an invisible format character (a soft "
                             "hyphen, a zero-width space or a direction mark, which an editor may not show): delete it "
                             "and write the name again" % (len(entries) + 1))
        if _HOME_KEY.match(bare):  # meant as a home and not one: never kept as a string that cannot match
            raise CheckError("line %d of the owner's list starts with `home` and a colon but is not one ASCII home name "
                             "and nothing after it (a letter or digit first, then letters, digits, spaces, `.`, `_`, `-`, "
                             "`'`): a note goes on a line of its own, a path is written as its home name only, and a name "
                             "outside ASCII, or holding another character, is listed as a plain string (a typographic "
                             "apostrophe the folder's name does not hold is written as '; a folder whose name holds one is "
                             "listed as a plain string with it kept and declared too with `home:` written with ')"
                             % (len(entries) + 1))
        # a comment or a blank is judged without its invisible characters too, as a home line is (one rule per line)
        # a string keeps a joiner between its letters (an emoji needs one); one at either end belongs to no string
        edge = [i for i, c in enumerate(text) if not (c.isspace() or unicodedata.category(c) == "Cf")]
        text = text[edge[0]:edge[-1] + 1] if edge else ""  # ends taken in one slice, spaces between marks too
        entries.append("" if not bare or bare.startswith("#") or len(text) < 3 else _fold(text))
    return entries


def _entry_spans(text: str, entries: List[str]) -> List[Tuple[int, int, int]]:
    strings = [(n, e) for n, e in enumerate(entries, 1) if e and not e.startswith(HOME_ENTRY)]
    if not strings:
        return []
    if text.isascii():  # casefolding ASCII is lowering it, one character for one: no map to build
        folded, starts, ends = text.lower(), None, None
    else:
        folded, starts, ends = _fold_map(text)
    spans = []
    for number, entry in strings:
        start = folded.find(entry)
        while start != -1:  # back to the original characters: every one a matched character came from
            end = start + len(entry)
            spans.append((start, end, number) if starts is None or ends is None
                         else (starts[start], ends[end - 1], number))
            start = folded.find(entry, start + 1)
    return spans


def _instance_finding(text: str, entries: List[str]) -> Optional[str]:
    spans = _entry_spans(text, entries)
    return "a string from the owner's list (line %d)" % spans[0][2] if spans else None


def _alternatives(pattern: "re.Pattern[str]") -> List[Tuple["re.Pattern[str]", ...]]:
    """Each provider-key alternative of this check's pattern as (its starts, its prefix, a run of its class, least
    length, open-ended, the whole alternative), so a key is read where its own class ends, not where another's does."""
    found = []
    for alt in pattern.pattern[1:-1].split("|"):
        part = re.fullmatch(r"(.+?)(\[[^\]]+\])\{(\d+)(,?)\}", alt)
        if part is None:  # not an assert: `python -O` would drop it
            raise ImportError("KEY_SHAPE_SOURCES has a key shape this check cannot read: %s" % alt[:12])
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
    credential together (`<https>:\\/\\/app:<pw>@db/x`), the segments that finding's spans touch are masked, else the
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
    if seen is not None and seen.grams:  # a run of a value found elsewhere in the tree, across a `/` too
        for k in range(len(path) - 7):
            if path[k:k + 8] in seen.grams:
                for i, (a, b) in enumerate(spans):
                    if a < k + 8 and k < b:
                        masked[i] = True
    secret_segments = [span for span, m in zip(spans, masked) if m]
    marks = [(s, e, "<line %d>" % n) for s, e, n in _entry_spans(path, entries)]
    found = _home_names(path, _owner_homes(entries))
    marks += [(s, e, "<home>") for s, e in found]
    # every other occurrence of a found name, searched in the path itself: a lowered copy can change its length (U+0130),
    # and Unicode case matching also takes the letters that fold to ASCII ones (U+212A to `k`, U+017F to `s`); the names
    # found elsewhere in the tree are one compiled pattern, so the cost does not grow with names times paths
    # a declared home of three or more letters and digits is the owner's own name: masked wherever a printed path holds
    # it, its parts joined by none or any run of the separators a tool writes (a space, `.`, `_`, `-`, `+`, and their
    # percent-encodings), found or not
    known = {path[s:e] for s, e in found} | (seen.names if seen is not None else set())
    for declared in _owner_homes(entries):
        parts = _name_parts(declared)
        if sum(len(part) for part in parts) < 3 and len(parts) > 1:  # a short name found: each spelling with a separator
            spaced = (_NAME_JOIN + "+").join(re.escape(part) for part in parts)
            if any(re.fullmatch(spaced, name, re.IGNORECASE) for name in known):
                marks += [(m.start(), m.end(), "<home>") for m in re.finditer(spaced, path, re.IGNORECASE)]
        if sum(len(part) for part in parts) >= 3:
            body = (_NAME_JOIN + "*").join(re.escape(part) for part in parts)
            # found in the tree: masked wherever it stands; unfound: a whole word only, so `home: app` leaves `mapping`
            # readable (a percent-encoded or escaped separator before it starts a word too)
            if not any(re.fullmatch(body, name, re.IGNORECASE) for name in known):
                body = _NAME_START + body + "(?![A-Za-z0-9])"
            marks += [(m.start(), m.end(), "<home>") for m in re.finditer(body, path, re.IGNORECASE)]
    for name in _spellings({path[s:e] for s, e in found}, _owner_homes(entries)):
        marks += [(m.start(), m.end(), "<home>") for m in re.finditer(re.escape(name), path, re.IGNORECASE)]
    if seen is not None and seen.names:
        marks += [(m.start(1), m.end(1), "<home>") for m in seen.names_pattern().finditer(path)]
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
    shutil.which there puts the current folder first too), and on POSIX an empty or relative PATH element (a trailing
    `:`) is the current folder: a tree checked from inside could run its own `git`."""
    name = "git.exe" if os.name == "nt" else "git"  # never a .cmd or .bat: cmd.exe would read the arguments
    # with PATH unset, POSIX's default folders (`/bin`, `/usr/bin`); Windows' default (`.;C:\\bin`) is a folder any
    # user may create, so there no PATH means no git and the walk
    folders = os.get_exec_path() if os.name != "nt" else os.environ.get("PATH", "").split(os.pathsep)
    for folder in folders:
        if folder and os.path.isabs(folder):
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate
    return None


_GIT_LOCATION = frozenset(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX"))


def _git_files(root: Path) -> Optional[List[str]]:
    git = _git()
    if git is None:
        return None
    try:
        # `core.fsmonitor` off: `--others` would run a command the checked tree's own configuration names. Empty, not
        # `false`: Git before 2.36 reads the value as a hook and would run a program named `false` from PATH
        # the repository is found from ROOT: a Git location the caller exports (every hook in a linked worktree gets
        # GIT_DIR and GIT_INDEX_FILE) would list another repository's files and leave ROOT's own unread
        env = {k: v for k, v in os.environ.items() if k.upper() not in _GIT_LOCATION}
        result = subprocess.run([git, "-c", "core.fsmonitor=", "-C", str(root), "ls-files", "-z", "--cached",
                                 "--others", "--exclude-standard"], capture_output=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # Git for Windows writes a lone surrogate in a name as WTF-8: read back as that character, it is the name os.walk
    # gives; elsewhere a name is bytes, decoded as os.walk decodes it. `_name_bytes` turns either back into Git's bytes
    names = set()
    for raw in result.stdout.split(b"\0"):  # each name on its own: one name that is not UTF-8 changes no other
        if not raw:
            continue
        try:
            # POSIX: the file system's own encoding, so the name is the one os.walk and open() use in any locale
            names.add(raw.decode("utf-8", "surrogatepass") if os.name == "nt" else os.fsdecode(raw))
        except UnicodeDecodeError:
            names.add(raw.decode("utf-8", "surrogateescape"))
    return sorted(names)


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


def _lines(data: bytes) -> Iterable[Tuple[int, str]]:
    """Lines as an editor numbers them: split at LF, a trailing CR dropped (str.splitlines also splits at FF, VT...)."""
    for number, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        yield number, line[:-1] if line.endswith("\r") else line


def _text_findings(text: str, entries: List[str], seen: Optional["_Seen"] = None) -> List[Tuple[str, str]]:
    found = []
    homes = _home_names(text, _owner_homes(entries))
    if homes:
        found.append(("home-path", "a path inside a person's home folder"))
        if seen is not None:
            seen.names.update(_spellings({text[a:b] for a, b in homes}, _owner_homes(entries)))
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
        self.grams: Set[str] = set()  # every 8-character run of a found value, the whole of it
        self._names_pattern: Optional["re.Pattern[str]"] = None

    def add_values(self, text: str) -> None:
        sources = [(text, _secret_spans(text))]
        if "\\" in text:
            unescaped = _json_unescaped(text)
            if unescaped != text:
                sources.append((unescaped, _secret_spans(unescaped)))
        for source, spans in sources:
            # overlapping spans (each start of `sk-sk-sk-...` runs to the end) merged first: their runs are the same,
            # and reading each span apart cost the square of the line
            merged: List[List[int]] = []
            for a, b in sorted(spans):
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            for a, b in merged:
                value = source[a:b]
                self.grams.update(value[i:i + 8] for i in range(max(0, len(value) - 7)))

    def names_pattern(self) -> "re.Pattern[str]":
        """Every name found, longest first, as one pattern: read once the tree is read, when no name is added."""
        if self._names_pattern is None:
            alternatives = sorted(self.names, key=len, reverse=True)
            # a lookahead reads every start, so two names that overlap in a path are both marked
            self._names_pattern = re.compile("(?=(%s))" % "|".join(re.escape(n) for n in alternatives), re.IGNORECASE)
        return self._names_pattern


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
    if os.path.lexists(str(root / "fabric.source.json")):  # DEC-0149: the manifest decides (fabric_source_tree.py)
        wrote, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # a copy inside the tree adds no .pyc
        try:
            import fabric_source_tree  # noqa: E402 - beside this file; imported here, since it imports this one
        finally:
            sys.dont_write_bytecode = wrote
        return fabric_source_tree.check_folder(root, files, mode, entries, unreadable, dependencies)
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
            not_read.append({"path": path, "why": "under a symbolic link"})
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
                not_read.append({"path": path, "why": "a nested repository"})
                continue
            if not stat.S_ISREG(kind):  # a socket, a pipe: nothing a source carries
                continue
            with open(full, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:  # Git lists it and the work tree lacks it: deleted, or outside a sparse checkout
            skipped["unreadable"] += 1
            not_read.append({"path": path,
                             "why": "not in the work tree" if mode == "git" else "unreadable"})
            continue
        except OSError:
            skipped["unreadable"] += 1
            not_read.append({"path": path, "why": "unreadable"})
            continue
        if b"\0" in data[:8192]:
            skipped["binary"] += 1
            not_read.append({"path": path, "why": "binary"})
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


def _absolute(path: str, platform: str) -> bool:
    return bool(re.match(r"[A-Za-z]:[\\/]|[\\/]{2}", path)) if platform == "win32" else path.startswith("/")


def default_list(platform: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Path:
    """Where the owner's list is kept when none is named: the user's configuration folder, never a project's."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    # a relative value is ignored, as the XDG spec says (a quoted `~/.config` is relative too): never "no list"
    if platform == "win32":
        appdata = env.get("APPDATA", "")
        base = Path(appdata) if appdata and _absolute(appdata, platform) else Path.home() / "AppData" / "Roaming"
    else:
        xdg = env.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg.startswith("/") else Path.home() / ".config"
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
        raise CheckError("there is no home folder to find the owner's list in: set an absolute XDG_CONFIG_HOME (APPDATA on "
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
                raise CheckError("the owner's list named by --instance-strings or FABRIC_INSTANCE_STRINGS does not exist or is "
                                 "not a regular file"
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
    if result.get("manifest"):  # under fabric.source.json: its own report (fabric_source_tree.print_run)
        return sys.modules["fabric_source_tree"].print_run(result, entries, list_path is not None, args.json, _print)
    findings = result["findings"]
    skipped = result["skipped"]
    listed = sum(1 for e in entries if e and not e.startswith(HOME_ENTRY))
    homes = sum(1 for e in entries if e.startswith(HOME_ENTRY))
    # a binary file is not read either: it is complete only when every one is named as source in the ignore file
    complete = not (skipped["unreadable"] or skipped["binary"] or skipped["nested"])  # type: ignore[index]
    result.update({"instanceStrings": listed, "ownerHomes": homes, "instanceList": list_path is not None, "blocking": bool(findings),
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
               "%d left out by name; %d instance string(s) listed%s%s"
               % (result["files"], "what Git would commit" if result["mode"] == "git" else
                  "every file, as pack reads them" if args.every_file else "every file but dependency folders, Git not used",
                  len(findings), skipped["binary"], skipped["unreadable"], skipped["nested"],  # type: ignore[index]
                  skipped["excluded"], listed,  # type: ignore[index]
                  "" if listed or homes else (" (the owner's list holds no string of three or more characters)"
                                              if list_path else " (no owner's list)"),
                  "; %d home name(s) declared" % homes if homes else ""))
    if findings:
        return 1
    return 0 if complete else 2


if __name__ == "__main__":
    _keep_console(getattr(sys, "_xoptions", {}))
    _argv = (list(sys.orig_argv[1:]) if hasattr(sys, "orig_argv")
             else _interpreter_flags(sys.flags, getattr(sys, "_xoptions", {})) + sys.argv)
    _restart = _utf8_restart(sys.getfilesystemencoding(), sys.flags.utf8_mode, _interpreter(), _argv)
    if _restart is not None:
        try:
            if not _restart:
                raise OSError("no interpreter")
            # the output keeps the console's encoding, as before the restart: an -X option survives -I and -E
            _console = getattr(sys.stdout, "encoding", None) or "ascii"
            os.execv(_restart[0], _restart[:3] + [b"-X", os.fsencode("fabric_console=" + _console)] + _restart[3:])
        except OSError:
            sys.stderr.write("fabric_source_check.py: could not restart in Python's UTF-8 mode under this locale; run it "
                             "as `python3 -X utf8 fabric_source_check.py ...`\n")
            sys.exit(2)
    sys.exit(run())

# #endregion source-check
