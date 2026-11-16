#!/usr/bin/env python3
"""Find instance data in an agent's source tree, without repeating it (FAA-188 part 1).

An agent's source is what can be handed over (code, skills, prompts, schemas, examples); its instance is what belongs
to one installation (records, logs, keys, the owner's names and paths, its configuration). This check reads the files
the source would carry and reports, by path, line and kind, each place where the instance shows through:

- `home-path`: an absolute path inside a person's home folder whose name is ASCII: `/Users/<name>/`, `/home/<name>/`,
  `/var/home/<name>/`, `C:\\Users\\<name>\\` (any case, either separator, a JSON-escaped backslash), the dashed form a
  tool makes of such a path (`-Users-<name>-`, `C--Users-<name>-`, DEC-0105, its name up to the next dash), Git Bash's
  `/c/Users/<name>`, WSL's `/mnt/c/Users/<name>` and the URL-encoded ones (`%2FUsers%2F<name>`, `%5CUsers%5C<name>`), and
  the plain check's own beside them (a `file` URL's host, `vscode://file/`, an encoded drive colon, JSON-escaped
  slashes: fabric_source_homes.MORE_HOME_PATHS, FAA-190); a neutral name (`example`, `user`,
  `runner`, a container's or a cloud machine's user such as `node` or `ubuntu`), a one-letter name or a placeholder
  (`<name>`, `$USER`) is not a finding;
- `secret`: a value shaped like a credential by the contract's detector (fabric_secrets.py, DEC-0044), read line by
  line: a provider key starting a word, a JWT, a bearer token, or a long run mixing upper case, lower case and digits
  assigned to a name that can only carry a credential (a bare long run, such as an integrity hash, is not; a whole
  Ed25519 signature under a JSON `"sig"`, `"signature"` or `"signatures"` member, as `sign` writes it, is public); or a private key: a PEM, OpenSSH or PGP
  block, or a JWK's `d`; a URL that carries a password or a credential in its query; a file that is a credential by
  its name (pack's rule: `.env`, `*.pem`, `*.key`, `.npmrc` ...) or a kit credential file (`*.token`, `board.credential`),
  or a folder so named anywhere in its path (FAA-190 (74)). A value that says it is synthetic (`EXAMPLE`, `not-a-key`, `fake`, `dummy`) is
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
work tree, and the staged copy of a file whose index differs from the last commit too, when it differs from the work
tree (what a plain `git commit` takes; its findings say `in its staged copy`). With `--every-file`, every file but `.git`, `__pycache__`,
`.DS_Store` and `*.pyc`, which `pack` refuses as litter (what `pack` reads). When ROOT is not in a Git checkout or Git lists nothing in it, every file outside `.git`,
`__pycache__`, `node_modules`, virtual environments and caches; the dependency folders it leaves are named (so too
when no `git` is found in PATH's absolute folders outside ROOT, or with PATH unset in `/bin` and `/usr/bin`; on
Windows with PATH unset the walk is used). Git runs through fabric_git.py: no fsmonitor, no caller's Git location or
trace (FAA-190). A committed symbolic link is checked by the path it names, never followed. A binary file (a NUL byte in
its first 8 KiB) is not read; it is listed. Globs in ROOT's `.fabric-source-ignore` (one per line, `#`
comments) and `--exclude` leave matching paths out. The owner's list is `--instance-strings`, else the file
`FABRIC_INSTANCE_STRINGS` names, else `passioncode-fabric/instance-strings.txt` in the user's configuration folder
(`$XDG_CONFIG_HOME` when it is absolute, else `~/.config`; `%APPDATA%` when absolute on Windows) when it exists: one string per
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
from typing import Callable, Dict, Iterable, List, NoReturn, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _refuse_sibling(step: str, missing: BaseException) -> NoReturn:
    """A sibling module that did not load: name it and exit 2, never a traceback and never exit 1 (a finding)."""
    # the exception's own text is never printed: an OSError's carries a path, which may be under the owner's home
    why = "a module beside this file refused to load"
    try:
        here, sibling = Path(__file__).resolve().parent, step + ".py"
        file = getattr(missing, "filename", None) if isinstance(missing, OSError) else None
        why = ("%s must sit beside this file" % sibling if not (here / sibling).is_file()
               else "%s beside this file cannot be read" % sibling
               if isinstance(file, (str, bytes)) and Path(os.fsdecode(file)).resolve() == here / sibling
               # the file is there and Python found no module of its name: the folder can be searched, not listed
               # (mode 311), and an import lists it (FAA-190 (92))
               else "the scripts folder holding %s cannot be listed: give it read permission" % sibling
               if isinstance(missing, ModuleNotFoundError) and getattr(missing, "name", None) == step
               else "%s beside this file is from another version: copy it with this one" % sibling
               if isinstance(missing, (ImportError, SyntaxError))
               else "%s beside this file refused to load (%s): copy the scripts folder whole, from one version"
               % (sibling, type(missing).__name__))
    except Exception:  # naming the cause must never be what fails
        pass
    sys.stderr.write("fabric_source_check.py: %s\n" % why)
    sys.exit(2)


_WROTE_BYTECODE, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # a copy inside the checked tree adds no .pyc
_STEP = "fabric_secrets"  # the sibling being loaded, so a refusal names it whatever the exception says
#: The public names of fabric_secrets the check and its command line read (FAA-190 (2), (12)), checked when it loads.
SECRETS_NAMES = ("BEARER_INSIDE", "JS_SPACE", "NOT_LINE_END", "SCHEME", "credential_name", "has_jwt", "jwt_spans",
                 "long_secret", "raw_values", "secret_value", "url_parts")
try:
    import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file
    _STEP = "fabric_source_ignore"
    from fabric_source_ignore import (  # noqa: E402,F401 - how the ignore lines are read, beside this file
        IGNORE_FILE, CheckError, _as_bytes, _glob, _ignored, _line, _readable_glob, ignore_globs)
    _STEP = "fabric_source_restart"
    from fabric_source_restart import _interpreter, _interpreter_flags, _keep_console, _utf8_restart  # noqa: E402,F401
    _STEP = "fabric_source_homes"
    from fabric_source_homes import (  # noqa: E402,F401 - how a declared home is read, beside this file
        HOME_ENTRY, HOME_ESCAPES, MORE_HOME_PATHS, _NAME_JOIN, _NAME_START, _SEP, _dashed_home, _name_parts, _owner_homes,
        _spellings)
    _STEP = "fabric_source_list"
    from fabric_source_list import (  # noqa: E402,F401 - the owner's list and how its strings are found, beside this file
        INVISIBLE, entry_spans as _entry_spans, fold as _fold, fold_map as _fold_map, read_list)
    _STEP = "fabric_source_redact"
    import fabric_source_redact as _redact  # noqa: E402 - how a path is printed without what was found, beside this file
    _STEP = "fabric_git"
    import fabric_git as _gitrun  # noqa: E402 - how Git runs on the tree (FAA-190 (66)), beside this file
    _STEP = "fabric_source_check_cli"
    from fabric_source_check_cli import (  # noqa: E402,F401 - the command line, beside this file (FAA-190 (104))
        LIST_NAME, _Parser, _absolute, _list_path, _print, default_list, run_check)
    _STEP = "fabric_secrets"
    for _name in SECRETS_NAMES:  # a detector from another version fails here, never at the first file read (FAA-190 (89))
        if not hasattr(_secrets, _name):
            raise ImportError(_name)
except Exception as _missing:  # a copy without its siblings, or mixed from two versions: a refusal, never exit 1
    _refuse_sibling(_STEP, _missing)
finally:
    sys.dont_write_bytecode = _WROTE_BYTECODE

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
# word: a bearer token is looked for as `BEARER_INSIDE` does, the word, then a run of 12 or more with a digit.
KEY_SHAPE_SOURCES = ("sk-[A-Za-z0-9_-]{16,}", "gh[pousr]_[A-Za-z0-9]{20,}", "xox[abposr]-[A-Za-z0-9-]{10,}", "AKIA[0-9A-Z]{16}", "glpat-[A-Za-z0-9_-]{20,}")
PROVIDER_KEY = re.compile("(" + "|".join(KEY_SHAPE_SOURCES) + ")", re.IGNORECASE | re.ASCII)
#: A URL parameter's value read as the contract's tree check reads it (`URL_SECRET_VALUE` in `src/source-rules.ts`): the
#: detector's whole-value `^bearer` branch and this check's own unbounded shapes, never the shared DEC-0151 detector.
URL_SECRET_VALUE = re.compile("(^bearer[" + _secrets.JS_SPACE + "]" + _secrets.NOT_LINE_END + "+|" + "|".join(KEY_SHAPE_SOURCES) + ")",
                              re.IGNORECASE | re.ASCII)
#: Files that are credentials by their name: pack's own rule (fabric_package.SECRET_FILE and SECRET_FILE_OK, held
#: equal by test_source_check), the kit's token files among them (`service.token`, fabric_auth; `board.credential`,
#: fabric_hub): pack refuses them too since FAA-190 (15), so the check's own TOKEN_FILE is folded in.
_JS_DOT = "[^\n\r\u2028\u2029]"
SECRET_FILE = re.compile(r"\.env(\.%s+)?|%s*\.(pem|key|p12|pfx|jks|keystore|token|credential)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc)"
                         % (_JS_DOT, _JS_DOT))
SECRET_FILE_OK = re.compile(r"\.env\.(example|sample|template)")
_PACK_JUNK_FILE = re.compile(r"\.DS_Store|%s*\.pyc" % _JS_DOT)  # held to fabric_package.JUNK by test_source_check
#: An absolute URL in a line, read whole by `_url_secret`: a password in it, a credential in its query.
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{0,63}://[^\s\"'<>`]+")  # a bounded scheme: linear, and `${X:-pg://..}`
#: `NAME = value`, `NAME: value` or `"name": "value"`: the long-run rule applies only where the name carries a credential.
#: The name is bounded and starts a word, so a long line is read in linear time.
ASSIGNED = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]{0,63})[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?"
                      r"((?:[A-Za-z0-9+/_-]|%[0-9A-Fa-f]{2}){40,}={0,2})")  # `=` only as padding; `%2B` read decoded


def _homes_once(text: str, owner: Set[str]) -> List[Tuple[int, int]]:
    spans = []
    for pattern in HOME_PATHS + MORE_HOME_PATHS:
        pos = 0
        while True:
            match = pattern.search(text, pos)
            if match is None:
                break
            name = match.group(1).lower()
            if name in owner or (len(name) > 1 and name not in NEUTRAL_HOMES):  # one letter (`/Users/a`): a placeholder
                spans.append(match.span(1))
                pos = match.end()
            else:  # a name dropped may hide a home that starts inside it (`C:\\Users\\C:\\Users\\<name>`, FAA-190 (85))
                pos = match.start() + 1
    if owner:
        lowered = text.translate(_ASCII_LOWER)
        for name in sorted(owner):  # declared: found whatever it reads as, on a line holding each of its parts (FAA-190 (84))
            if all(part in lowered for part in _name_parts(name)):
                spans += [match.span(1) for pattern in _dashed_home(name) for match in pattern.finditer(text)]
    return spans


def _home_names(text: str, owner: Iterable[str] = ()) -> List[Tuple[int, int]]:
    """The spans of the names of real people's home folders in a text (neutral and one-letter names left out, unless
    the owner's list declares the name as the owner's home): the contract's forms and the plain check's own
    (MORE_HOME_PATHS), as written and with a JSON-escaped slash undone (`\\/`, `\\u002f`, FAA-190 (16)), mapped back."""
    owner = set(owner)
    spans = _homes_once(text, owner)
    if "\\" in text:
        plain, origin = _substituted(text, HOME_ESCAPES, lambda m: "/")
        if plain != text:
            spans += [(origin[a][0], origin[b - 1][1]) for a, b in _homes_once(plain, owner) if b > a]
    return sorted(set(spans))


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
    if not _secrets.SCHEME.match(url):
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
                if (_secrets.credential_name(name) and _secrets.long_secret(value)) or \
                        _secrets.has_jwt(value) or URL_SECRET_VALUE.search(value):
                    return True
    return False


#: How deep the plain check follows a URL inside another (its path, or a parameter's value); the contract's rule
#: (`_url_secret`) follows two levels of parameter values (FAA-190 (17)).
_URL_DEPTH = 4
#: A special scheme's URL written without its `//` (`<https>:app:<password>@db`), as a URL can sit in a path; WHATWG
#: reads the same user information there (FAA-190 (48)).
_SLASHLESS_URL = re.compile(r"(?<![A-Za-z0-9+.-])(?:https?|ftps?|wss?):(?!//)[^\s\"'<>`]+", re.IGNORECASE)
#: A whole URL percent-encoded (`<https>%3A%2F%2F...`), read decoded (FAA-190 (52)).
_ENCODED_URL = re.compile(r"%3[Aa]%2[Ff]%2[Ff]")
_PERCENT_ASCII = re.compile(r"%([0-7][0-9A-Fa-f])")


def _url_finding(url: str, depth: int = 0) -> bool:
    """The plain check's reading of one URL: the contract's (`_url_secret`), then a URL inside its path (`<https>://proxy/
    <https>://app:<password>@db/`, FAA-190 (18)) and one nested in a parameter's value deeper than the contract reads
    (FAA-190 (17)), each judged as a URL of its own."""
    if _url_secret(url):
        return True
    if depth >= _URL_DEPTH:
        return False
    at = url.find("://")
    inner = [m.group(0) for m in URL.finditer(url, at + 3)] if at >= 0 else []
    trimmed = url.rstrip(".,;)]}")
    if _secrets.SCHEME.match(trimmed):
        _, query, fragment = _secrets.url_parts(trimmed)
        for part in (query, fragment):
            for raws in _secrets.raw_values(part).values():
                inner += [m.group(0) for raw in raws if "://" in unquote(raw) for m in URL.finditer(unquote(raw))]
    return any(_url_finding(u, depth + 1) for u in inner)


def _url_spans(line: str) -> Iterable[Tuple[int, int]]:
    """The spans of the URLs in a line that carry a credential, as the plain check reads them: written whole, written
    without `//` (FAA-190 (48)), or percent-encoded whole (FAA-190 (52), mapped back)."""
    if "://" in line:
        yield from (m.span() for m in URL.finditer(line) if _url_finding(m.group(0)))
    if ":" in line:
        yield from (m.span() for m in _SLASHLESS_URL.finditer(line) if _url_finding(m.group(0)))
    if "%" in line and _ENCODED_URL.search(line):
        decoded, origin = _substituted(line, _PERCENT_ASCII, lambda m: chr(int(m.group(1), 16)))
        yield from ((origin[m.start()][0], origin[m.end() - 1][1]) for m in URL.finditer(decoded)
                    if _url_finding(m.group(0)))


def _url_credentials(text: str) -> List[str]:
    """The parts of each credential URL in a text that carry the credential: its password and each query or fragment
    value read as one, as written and decoded; a URL whose credential sits deeper gives itself whole. What a printed
    path is masked by, so a host or a path shared with an unrelated file masks nothing (FAA-190 (45), (54))."""
    out: List[str] = []
    sources = [text]
    if "\\" in text and _json_unescaped(text) != text:
        sources.append(_json_unescaped(text))
    for source in sources:
        for a, b in _url_spans(source):
            url = source[a:b].rstrip(".,;)]}")
            parts: List[str] = []
            if "://" in url[:72] and _secrets.SCHEME.match(url):
                password, query, fragment = _secrets.url_parts(url)
                if password and _url_secret("https://" + "u:%s@h.invalid/" % password):
                    parts += [password, unquote(password)]
                for part in (query, fragment):
                    for piece in part.split("&"):
                        if "=" in piece and _url_finding("https://h.invalid/?" + piece):
                            value = piece.partition("=")[2]
                            parts += [value, unquote(value)]
            out += parts or [url]
    return out


#: Plain check only (FAA-190 (8)): on a line that names `kty`, a private JWK's `d` or a symmetric one's `k` under a
#: key quoted or not (a JS object, YAML flow), beside the contract's JSON, escaped JSON and Python `d` (JWK_PRIVATE).
_JWK_MORE = re.compile(r"(?<![A-Za-z0-9_$\\])\\?[\"']?[dk]\\?[\"']?[ \t]*:[ \t]*\\?[\"']?([A-Za-z0-9_-]{43,})")
#: Plain check only (FAA-190 (11)): a value under a credential's name holding an `=` inside it (`<24>=<30>`), read
#: whole; the contract's ASSIGNED takes `=` only as padding.
_ASSIGNED_EQ = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]{0,63})[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?"
                          r"((?:[A-Za-z0-9+/_=-]|%[0-9A-Fa-f]{2}){40,})")


def _jwk_more(line: str) -> Iterable[Tuple[int, int]]:
    return (m.span(1) for m in _JWK_MORE.finditer(line) if _real(m.group(1))) if "kty" in line else iter(())


def _assigned_values(line: str) -> Iterable[Tuple[int, int]]:
    """The spans of long random values assigned to a credential's name: ASSIGNED's, then the plain check's own with an
    `=` inside the value."""
    if ":" not in line and "=" not in line:
        return
    for pattern in (ASSIGNED, _ASSIGNED_EQ):
        for m in _assigned(line, pattern):
            value = unquote(m.group(2))
            if (pattern is ASSIGNED or "=" in m.group(2).rstrip("=")) and _credential(m.group(1), m.group(2), _quoted(line, m)) \
                    and _secrets.long_secret(value) and _real(value):
                yield m.span(2)


#: The JSON escapes tools write for `&`, `=` and `/` (Go's encoding/json writes `\u0026`, PHP's json_encode `\/`).
_JSON_ESCAPES = re.compile(r"\\(?:u0026|u003[dD]|/)")


_UNESCAPED = {"u0026": "&", "u003d": "=", "u003D": "=", "/": "/"}


def _json_unescaped(line: str) -> str:
    return _JSON_ESCAPES.sub(lambda m: _UNESCAPED[m.group(0)[1:]], line)


def _substituted(line: str, pattern: "re.Pattern[str]", repl: Callable[["re.Match[str]"], str]
                 ) -> Tuple[str, List[Tuple[int, int]]]:
    """The line with each match of `pattern` replaced by one character, and for each of its characters the raw span it
    came from."""
    out: List[str] = []
    origin: List[Tuple[int, int]] = []
    last = 0
    for m in pattern.finditer(line):
        out.extend(line[last:m.start()])
        origin.extend((i, i + 1) for i in range(last, m.start()))
        out.append(repl(m))
        origin.append(m.span())
        last = m.end()
    out.extend(line[last:])
    origin.extend((i, i + 1) for i in range(last, len(line)))
    return "".join(out), origin


def _unescaped_with_origin(line: str) -> Tuple[str, List[Tuple[int, int]]]:
    """The line with JSON escapes undone, and for each of its characters the raw span it came from."""
    return _substituted(line, _JSON_ESCAPES, lambda m: _UNESCAPED[m.group(0)[1:]])


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
    if any(_real(m.group(1)) for m in JWK_PRIVATE.finditer(line)) or any(True for _ in _jwk_more(line)):
        return "a private key (a JWK's `d` or `k`)"
    if any(_real(line[a:b]) for a, b in _secrets.jwt_spans(line)):  # one pass (FAA-313)
        return "a token shaped like a JWT"
    # The detector reads one configuration value; across a line, `sk-` needs a word start of its own, or every name
    # with a segment ending in `sk` (`task-management-service`) would read as a key.
    if any(True for _ in _provider_keys(line)):
        return "a value shaped like a provider key"
    if any(_real(m.group(0)) for m in _overlapping(_secrets.BEARER_INSIDE, line)):
        return "a bearer token"
    if any(True for _ in _url_spans(line)):
        return "a URL that carries a credential"
    if any(True for _ in _assigned_values(line)):
        return "a long random value assigned to a credential's name"
    return None


def _assigned(line: str, pattern: "re.Pattern[str]" = ASSIGNED) -> Iterable["re.Match[str]"]:
    """ASSIGNED's matches, each search starting again inside the last value: `id=<run>/TOKEN=<value>` reads both."""
    pos = 0
    while True:
        m = pattern.search(line, pos)
        if m is None:
            return
        yield m
        pos = m.start(2) if m.start(2) > pos else m.end()


def _instance_finding(text: str, entries: List[str]) -> Optional[str]:
    spans = _entry_spans(text, entries)
    return "a string from the owner's list (line %d)" % spans[0][2] if spans else None


def _alternatives(pattern: "re.Pattern[str]") -> List[Tuple["re.Pattern[str]", ...]]:
    """Each provider-key alternative of this check's pattern as (its starts, its prefix, a run of its class, least
    length, open-ended, the whole alternative), so a key is read where its own class ends, not where another's does."""
    found = []
    for alt in pattern.pattern[1:-1].split("|"):
        part = re.fullmatch(r"(.+?)(\[[^\]]+\])\{(\d+)(,?)\}", alt)
        # a prefix of variable length (`sk-(?:proj-)?`) would be read as one of fixed length: refused (FAA-190 (33))
        if part is None or any(c in part.group(1) for c in "()?*+{|\\"):  # not an assert: `python -O` would drop it
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


def _secret_spans(text: str, urls: bool = True) -> List[Tuple[int, int]]:
    """The spans of credential-shaped values in a text, as `_secret_in` reads them (a public signature is no span);
    without `urls`, a URL's span is left out (`_url_credentials` gives its parts)."""
    public = [m.span() for m in _PUBLIC_SIGNATURE.finditer(text)] if '"' in text else []
    return [(a, b) for a, b in _raw_secret_spans(text, urls) if not any(p <= a and b <= q for p, q in public)]


def _raw_secret_spans(text: str, urls: bool = True) -> List[Tuple[int, int]]:
    spans = [m.span() for m in PRIVATE_KEY.finditer(text)]
    spans += [(a, b) for a, b in _secrets.jwt_spans(text) if _real(text[a:b])]  # one pass (FAA-313)
    spans += [m.span(1) for m in JWK_PRIVATE.finditer(text) if _real(m.group(1))]
    spans += list(_jwk_more(text))
    spans += list(_provider_keys(text))
    spans += [m.span() for m in _overlapping(_secrets.BEARER_INSIDE, text) if _real(m.group(0))]
    spans += list(_url_spans(text)) if urls else []
    spans += list(_assigned_values(text))
    return spans


def _git(root: Optional[Path] = None) -> Optional[str]:
    """`git` from PATH's absolute folders only, never one inside the checked tree (fabric_git.executable): on Windows
    CreateProcess looks in the current folder first, on POSIX an empty or relative PATH element is the current folder,
    and `npm run` puts `<root>/node_modules/.bin` on PATH (FAA-190 (67)): a tree checked from inside could run its own
    `git`."""
    return _gitrun.executable([root] if root is not None else [])


_GIT_LOCATION = _gitrun.LOCATION
#: Git's discovery limits the caller may export: never passed either, so a ceiling at or above the repository's top
#: does not turn ROOT into a folder outside Git (the walk) (FAA-190 (98)).
_GIT_DISCOVERY = ("GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM")


def _git_env() -> Dict[str, str]:
    env = _gitrun.environment()
    for name in [k for k in env if k.upper() in _GIT_DISCOVERY]:
        del env[name]
    return env


def _git_run(root: Path, args: List[str]) -> Optional[bytes]:
    """Git's output in ROOT through fabric_git (both fsmonitors off, the caller's Git location, discovery limits and
    traces not passed, nothing written), or None when no git ran or it refused."""
    git = _git(root)
    if git is None:
        return None
    try:
        result = subprocess.run([git, *_gitrun.NO_COMMANDS, "-C", str(root), *args], capture_output=True, timeout=60,
                                env=_git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _git_name(raw: bytes, nt: bool) -> Tuple[str, bool]:
    """A name Git lists, as os.walk would give it, and whether it is one (False: on Windows a name that is not UTF-8,
    committed elsewhere, which no Windows work tree can hold). Git for Windows writes a lone surrogate as WTF-8, read
    back as that character; elsewhere a name is bytes, decoded with the file system's own encoding, so the name is
    the one os.walk and open() use in any locale."""
    try:
        return (raw.decode("utf-8", "surrogatepass") if nt else os.fsdecode(raw)), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", "surrogateescape"), not nt


class _Listing(list):
    """The names Git lists; `undecodable` the Windows ones that are not UTF-8 (FAA-190 (71))."""

    undecodable: Set[str]


def _git_files(root: Path) -> Optional[List[str]]:
    # `--others` would run a command the checked tree's configuration names (fsmonitor), and a hook in a linked worktree
    # has GIT_DIR and GIT_INDEX_FILE, which would list another repository's files: `_git_run` passes neither
    out = _git_run(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    if out is None:
        return None
    names, undecodable = set(), set()
    for raw in out.split(b"\0"):  # each name on its own: one name that is not UTF-8 changes no other
        if raw:
            name, ok = _git_name(raw, os.name == "nt")
            names.add(name)
            if not ok:
                undecodable.add(name)
    listing = _Listing(sorted(names))
    listing.undecodable = undecodable
    return listing


def _gitlinks(root: Path) -> Set[str]:
    """The submodules Git's index lists (mode 160000): `ls-files -s` prefixes each name, so none is read as another."""
    found = set()
    for entry in (_git_run(root, ["ls-files", "-z", "-s"]) or b"").split(b"\0"):
        head, tab, raw = entry.partition(b"\t")
        if tab and head.startswith(b"160000 "):
            found.add(_git_name(raw, os.name == "nt")[0])
    return found


def _staged_copies(root: Path) -> Dict[str, bytes]:
    """The staged copy of each file whose index differs from the last commit: a plain `git commit` commits it, and it
    may hold what the work tree no longer does (FAA-190 (68)). Read with no work tree file opened by Git, so no clean
    filter the tree's configuration names runs: `diff --cached` compares the index with the commit, `ls-files -s`
    names each blob, `cat-file --batch` reads it as stored."""
    out = _git_run(root, ["diff", "--cached", "--name-only", "-z", "--relative", "--no-ext-diff", "--no-textconv",
                          "--no-renames"])
    listed = _git_run(root, ["ls-files", "-z", "-s"]) if out else None
    if not out or not listed:
        return {}
    staged = {_git_name(raw, os.name == "nt")[0] for raw in out.split(b"\0") if raw}
    blobs: Dict[str, str] = {}
    for entry in listed.split(b"\0"):
        head, tab, raw = entry.partition(b"\t")
        parts = head.split(b" ")
        name = _git_name(raw, os.name == "nt")[0] if tab else ""
        if name in staged and len(parts) == 3 and parts[0] != b"160000" and parts[2] == b"0":
            blobs[name] = parts[1].decode("ascii", "replace")
    git = _git(root)
    if not blobs or git is None:
        return {}
    try:
        result = subprocess.run([git, *_gitrun.NO_COMMANDS, "-C", str(root), "cat-file", "--batch"], capture_output=True,
                                timeout=60, env=_git_env(), input="".join(sha + "\n" for sha in blobs.values()).encode())
    except (OSError, subprocess.SubprocessError):
        return {}
    data, pos, copies = result.stdout, 0, {}
    for name, sha in blobs.items():
        end = data.find(b"\n", pos)
        header = data[pos:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            break  # a missing object, or an answer that cannot be read: what was read stays
        size = int(header[2])
        copies[name] = data[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return copies


def _credential_name(name: str) -> bool:
    """A name `pack` refuses as a credential file (kit credential files `*.token` and `*.credential` included)."""
    return bool(SECRET_FILE.fullmatch(name) and not SECRET_FILE_OK.fullmatch(name))


def _walk_files(root: Path, unreadable: List[str], skip: Iterable[str] = WALK_SKIP,
                left: Optional[List[str]] = None) -> List[str]:
    """Every file under root but the folders in skip; each folder skipped is named in left. Without Git (skip is
    WALK_SKIP) a folder holding `pyvenv.cfg` is a virtual environment whatever its name (FAA-190 (40)). The litter
    `pack` refuses (`.DS_Store`, `*.pyc`) is left out with --every-file only: without Git the walk stands in for what Git
    would commit, which carries it."""
    found = []
    skip = set(skip)
    walk = skip != PACK_REFUSES

    def failed(error: OSError) -> None:
        unreadable.append(Path(str(error.filename or root)).relative_to(root).as_posix())

    def dependency(folder: str, name: str) -> bool:
        if name in skip:
            return True
        full = os.path.join(folder, name)
        return walk and not os.path.islink(full) and os.path.isfile(os.path.join(full, "pyvenv.cfg"))

    for folder, dirs, files in os.walk(root, onerror=failed):
        skipped = [d for d in dirs if dependency(folder, d)]
        if left is not None:
            left += [Path(folder, d).relative_to(root).as_posix() for d in skipped
                     if d not in PACK_REFUSES]  # `.git` and `__pycache__`: --every-file leaves them too
        dirs[:] = [d for d in dirs if d not in skipped]
        # os.walk lists a link to a folder with the folders and does not follow it: check it as Git would, by its target
        files = files + [d for d in dirs if os.path.islink(os.path.join(folder, d))]
        for name in files:
            if name in skip and name == ".git":  # a worktree's or a submodule's `.git` file: never carried, never source
                continue
            if not walk and _PACK_JUNK_FILE.fullmatch(name):  # --every-file: litter pack refuses, never carried
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
            seen.names.update(_redact.home_spellings({text[a:b] for a, b in homes}, _owner_homes(entries), NEUTRAL_HOMES))
    secret = _secret_finding(text)
    if secret:
        found.append(("secret", secret))
        if seen is not None:
            seen.add_values(text)
    spans = _entry_spans(text, entries)
    if spans:
        found.append(("instance-string", "a string from the owner's list (line %d)" % spans[0][2]))
        if seen is not None:
            seen.add_entries({n for _, _, n in spans}, entries)
    return found


#: The check's readers, handed to fabric_source_redact so a path is judged by the rules a line is.
_READ = _redact.Readers(_secret_finding, _secret_spans, _url_credentials, _unescaped_with_origin, _json_unescaped,
                        _entry_spans, _home_names, _fold_map, NEUTRAL_HOMES)


class _Seen(_redact.Seen):
    """What the check found anywhere in the tree (fabric_source_redact.Seen), read with this check's readers."""

    def __init__(self) -> None:
        super().__init__(_READ)


def redact(path: str, entries: List[str], seen: Optional[_Seen] = None) -> str:
    """A path as it may be printed (fabric_source_redact.redact), read with this check's readers."""
    return _redact.redact(path, entries, seen, _READ)


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
        except Exception as missing:  # the same named-sibling refusal as the imports at the top (exit 2)
            _refuse_sibling("fabric_source_tree", missing)
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

    links: List[Set[str]] = []  # the submodules Git lists, read once and only when a listed path is absent

    def absent_submodule(path: str) -> bool:
        """A submodule not checked out has no folder: asked with the `/` Git's listing lacks, it is a folder still, so
        `vendor/sub/` takes it and `vendor/*` does not, as when it is checked out (FAA-190 (46))."""
        if mode != "git" or os.path.lexists(str(root / path)):
            return False
        if not links:
            links.append(_gitlinks(root))
        return path in links[0]

    unmatched = dict(enumerate(globs))  # the lines no path matched yet, by their place (FAA-190 (50))
    undecodable = getattr(files, "undecodable", set())
    staged = _staged_copies(root) if mode == "git" else {}
    for path in files:
        if path in undecodable:  # read three bytes wide by a line, a Windows name that is not UTF-8 is never left out
            skipped["unreadable"] += 1
            not_read.append({"path": path, "why": "a name that is not UTF-8, which Windows cannot hold"})
            continue
        asked = path + "/" if absent_submodule(path) else path
        if _ignored(asked, globs, root):
            skipped["excluded"] += 1
            for index in [i for i, line in unmatched.items() if _ignored(asked, [line], root)]:
                del unmatched[index]
            continue
        for kind, rule in _text_findings(path, entries, seen):  # a name carries instance data as a line does
            add(path, 0, kind, rule + " in the file's path")
        *folders, name = path.split("/")  # a nested repository is listed as `vendor/sub/`: its name is a folder's
        if _credential_name(name):
            add(path, 0, "secret", "a file that is a credential by its name")
        if any(_credential_name(folder) for folder in folders):  # `pack` refuses it as well (FAA-190 (74))
            add(path, 0, "secret", "a folder in the path that is a credential by its name, which pack refuses")
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
        copy = staged.get(path)
        if copy is not None and copy != data and copy != data.replace(b"\r\n", b"\n") and b"\0" not in copy[:8192]:
            for number, line in _lines(copy):  # what a plain `git commit` takes, when the work tree holds another
                for kind, rule in _text_findings(line, entries, seen):
                    add(path, number, kind, rule + " in its staged copy")
    printed: Dict[str, str] = {}  # one redaction per path, however many findings it has

    def shown(path: str) -> str:
        if path not in printed:
            printed[path] = redact(path, entries, seen)
        return printed[path]

    for entry in findings:
        entry["path"] = shown(str(entry["path"]))
    for entry in not_read:
        entry["path"] = shown(entry["path"])
    where = getattr(globs, "where", None)
    return {"mode": mode, "files": read, "skipped": skipped, "notRead": not_read, "findings": findings,
            "dependencies": [shown(d) for d in dependencies],
            "unmatched": [where[i] if where else "glob %d" % (i + 1) for i in sorted(unmatched)]}


def run(argv: Optional[List[str]] = None) -> int:
    """The command line (fabric_source_check_cli.run_check), run with this module's check."""
    return run_check(argv, check, read_list, ignore_globs, HOME_ENTRY)


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
