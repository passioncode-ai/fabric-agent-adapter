"""The source manifest's rules (DEC-0149, `fabric-source/1`, FAC-SEM-156 to FAC-SEM-160), ported from the contract's
`src/source-rules.ts` at the pin and held to its vectors (`test/fixtures/contract/source-vectors.json`, FAA-261).

- `source_tree_problems(value)`: the tree check over `{manifest, files, instanceStrings?, listed?}`, each place the
  instance shows through as `{kind, file?, line?, column?, entry?, include?, exclude?}`, never the text it found;
- `patch_paths_allowed(manifest, paths)`: the paths of a patch that are not source (DEC-0149 item 13);
- `manifest_findings(manifest)`: FAC-SEM-156 (slots) and FAC-SEM-157 (paths), each `{code, instancePath, message}`;
- `package_findings(source, package)`: FAC-SEM-160, the package's `secrets[]` and `state[]` against the slots;
- `package_members(manifest)`: the `secrets[]` and `state[]` a packer writes from the manifest.

Columns count UTF-16 code units, as the contract's do; the credential and home-folder shapes are fabric_source_check's
(the contract ported them from it). Standard library only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_secrets as _secrets  # noqa: E402 - the contract's credential detector (DEC-0044), beside this file
import fabric_source_check as _check  # noqa: E402 - the credential and home-folder shapes this port shares

SOURCE_FILE = "fabric.source.json"
SOURCE_FORMAT = "fabric-source/1"
SLOT_KINDS = ("secret", "config", "store", "endpoint")
_GRAMMAR_HEAD = r"(?![/~])(?![\s\S]*\\)(?![\s\S]*//)(?!(?:[\s\S]*/)?\.{1,2}(?:/|\Z))"
SOURCE_FILE_PATH = re.compile(_GRAMMAR_HEAD + r"[^\u0000-\u001f:]{1,256}(?<!/)\Z")
SOURCE_PATH = re.compile(_GRAMMAR_HEAD + r"[^\u0000-\u001f:]{1,256}\Z")
_HFS_IGNORABLE = re.compile("[‌-‏‪-‮⁪-⁯﻿]")
_NUSKHURI = re.compile("[ⴀ-ⴥ]")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
BLOCKING_KINDS = ("home-path", "credential", "binary", "nested-repository", "instance-string", "missing",
                  "short-instance-string", "no-include")
WARNING_KINDS = ("email", "link-outside", "no-license", "unused-exclude", "excluded-by-fold")
_JS_DOT = "[^\n\r  ]"
CREDENTIAL_FILE = re.compile(r"(?:\.env(?:\.[^\n]+)?|[^\n]*\.(?:pem|key|p12|pfx|jks|keystore)|id_(?:rsa|dsa|ecdsa|ed25519)"
                             r"|\.(?:npmrc|netrc|pypirc))\Z")
CREDENTIAL_FILE_OK = re.compile(r"\.env\.(?:example|sample|template)\Z")
TOKEN_FILE = re.compile(r"[^\n]+\.(?:token|credential)\Z")
_SHORT_NAME = re.compile("~[0-9]")


def _u16(text: str) -> int:
    """A text's length in UTF-16 code units, as the contract counts it."""
    return len(text) + sum(1 for c in text if ord(c) > 0xFFFF)


def _strings(value: Any) -> List[Tuple[str, int]]:
    return [(item, index) for index, item in enumerate(value) if isinstance(item, str)] if isinstance(value, list) else []


def _objects(value: Any) -> List[Tuple[Dict[str, Any], int]]:
    return [(item, index) for index, item in enumerate(value) if isinstance(item, dict)] if isinstance(value, list) else []


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _ascii_fold(text: str) -> str:
    return text.translate(_ASCII_LOWER)


def is_dot_git_segment(segment: str) -> bool:
    """`.git` as Git's is_hfs_dotgit and is_ntfs_dotgit read a segment (or the short name `git~1`)."""
    name = _ascii_fold(_HFS_IGNORABLE.sub("", segment)).rstrip(" .")
    return name in (".git", "git~1")


def _in_git(path: str) -> bool:
    return any(is_dot_git_segment(s) for s in path.split("/"))


def fold_segment(segment: str) -> str:
    """One segment as a case-insensitive file system may resolve it: canonical caseless matching, Georgian Nuskhuri onto
    Mkhedruli, trailing dots and spaces dropped (`foldSegment`)."""
    text = unicodedata.normalize("NFD", _HFS_IGNORABLE.sub("", segment)).lower().upper().lower()
    text = _NUSKHURI.sub(lambda m: chr(ord(m.group(0)) - 0x2D00 + 0x10D0), _nfc(text))
    return text.rstrip(" .")


def fold_path(path: str) -> str:
    return "/".join(fold_segment(s) for s in path.split("/"))


def in_grammar(path: str, folder: bool = False) -> bool:
    """In the grammar as written, in NFC and in NFD, with no segment that folds to nothing (`inGrammar`)."""
    grammar = SOURCE_PATH if folder else SOURCE_FILE_PATH
    if not all(grammar.match(p) for p in (path, _nfc(path), unicodedata.normalize("NFD", path))):
        return False
    body = path[:-1] if path.endswith("/") else path
    return all(fold_segment(s) != "" for s in body.split("/"))


def _folder_prefixes(path: str) -> List[str]:
    return [path[:at + 1] for at, c in enumerate(path) if c == "/"]


class _PathList:
    def __init__(self, entries: List[str], reaches: bool = False, everything: bool = False) -> None:
        self.files = {e for e in entries if not e.endswith("/")}
        self.folders = {e for e in entries if e.endswith("/")}
        self.reaches = {p for e in entries for p in _folder_prefixes(e)} if reaches else set()
        self.all = everything


def _empty_segment(entry: str) -> Tuple[List[str], int, bool]:
    written = _nfc(entry)
    bare = not written.endswith("/")
    segments = (written if bare else written[:-1]).split("/")
    at = next((i for i, s in enumerate(segments) if fold_segment(s) == ""), -1)
    return segments, at, bare


def _widest_reading(entry: str) -> Tuple[bool, bool, List[str]]:
    """An exclude entry outside the grammar as a file system reads it removes its widest reading (`widestReading`)."""
    segments, at, bare = _empty_segment(entry)
    if at < 0:
        return False, bare, [fold_path(_nfc(entry))]
    depth = shallowest = at
    for segment in segments[at:]:
        if fold_segment(segment) != "":
            depth += 1
        elif segment.count(".") >= 2:
            depth -= 1
        shallowest = min(shallowest, depth)
    if shallowest <= 0:
        return True, bare, []
    folder = "/".join(fold_segment(s) for s in segments[:shallowest])
    return False, bare, ([folder + "/", folder] if bare else [folder + "/"])


def _folded_list(value: Any, widest: bool = False) -> _PathList:
    entries: List[str] = []
    everything = False
    for entry, _ in _strings(value):
        if in_grammar(entry, True):
            entries.append(fold_path(_nfc(entry)))
        elif widest and SOURCE_PATH.match(entry):
            whole, _bare, more = _widest_reading(entry)
            everything = everything or whole
            entries += more
    return _PathList(entries, everything=everything)


def _path_list(value: Any, reaches: bool = False) -> _PathList:
    return _PathList([_nfc(e) for e, _ in _strings(value) if in_grammar(e, True)], reaches)


def _excludes_folder(lst: _PathList, folded: str) -> bool:
    return lst.all or any(p in lst.folders or p[:-1] in lst.files for p in _folder_prefixes(folded))


def _covers_nfc(lst: _PathList, path: str) -> bool:
    return path in lst.files or any(f in lst.folders for f in _folder_prefixes(path))


def _list_covers(lst: _PathList, written: str) -> bool:
    return _u16(written) <= 512 and _covers_nfc(lst, _nfc(written))


def _exclude_covers_nfc(lst: _PathList, path: str) -> bool:
    return lst.all or path in lst.files or any(f in lst.folders or f[:-1] in lst.files for f in _folder_prefixes(path))


def _folded_covers(lst: _PathList, written: str) -> bool:
    return _u16(written) <= 512 and _exclude_covers_nfc(lst, fold_path(_nfc(written)))


def source_path_test(manifest: Any) -> Callable[[Any], bool]:
    """Whether a path is source: in the grammar, in no `.git`, the manifest itself or inside an include path and no
    exclude path (exclude read folded)."""
    source = manifest if isinstance(manifest, dict) else {}
    include = _path_list(source.get("include"))
    exclude = _folded_list(source.get("exclude"), True)

    def test(path: Any) -> bool:
        if not isinstance(path, str) or not in_grammar(path) or _in_git(path):
            return False
        if _nfc(path) == SOURCE_FILE:
            return True
        return _list_covers(include, path) and not _folded_covers(exclude, path)
    return test


def fold_only_exclude_test(manifest: Any) -> Callable[[Any], int]:
    """The first exclude entry that names a path only once both are folded, or -1 (`foldOnlyExcludeTest`)."""
    source = manifest if isinstance(manifest, dict) else {}
    include = _path_list(source.get("include"))
    literal = _path_list(source.get("exclude"))
    first: Dict[str, int] = {}
    for entry, at in _strings(source.get("exclude")):
        if in_grammar(entry, True):
            first.setdefault(fold_path(_nfc(entry)), at)

    def test(path: Any) -> int:
        if not isinstance(path, str) or not in_grammar(path) or _in_git(path) or _nfc(path) == SOURCE_FILE:
            return -1
        if not _list_covers(include, path) or (_u16(path) <= 512 and _exclude_covers_nfc(literal, _nfc(path))):
            return -1
        folded = fold_path(_nfc(path))
        keys = [folded] + [k for f in _folder_prefixes(folded) for k in (f, f[:-1])]
        found = [first[k] for k in keys if k in first]
        return min(found) if found else -1
    return test


def excluded_folder_test(manifest: Any) -> Callable[[str], bool]:
    """Whether a walk skips a folder (no trailing `/`): an exclude names it or a folder holding it, and no include
    path lies under it (`excludedFolderTest`)."""
    source = manifest if isinstance(manifest, dict) else {}
    exclude = _folded_list(source.get("exclude"), True)
    under = {p for e, _ in _strings(source.get("include")) if in_grammar(e, True) for p in _folder_prefixes(_nfc(e))}
    return lambda written: _excludes_folder(exclude, fold_path(_nfc(written)) + "/") and (_nfc(written) + "/") not in under


def _unchecked_paths(manifest: Any) -> List[Tuple[str, int]]:
    if not isinstance(manifest, dict):
        return []
    return [(e["path"], i) for e, i in _objects(manifest.get("unchecked")) if isinstance(e.get("path"), str)]


def unchecked_test(manifest: Any) -> Callable[[Any], bool]:
    is_source = source_path_test(manifest)
    unchecked = _path_list([p for p, _ in _unchecked_paths(manifest)])
    return lambda path: is_source(path) and _nfc(path) != SOURCE_FILE and _list_covers(unchecked, path)


def at_manifest_path(written: Any) -> bool:
    return isinstance(written, str) and _nfc(written[:-1] if written.endswith("/") else written) == SOURCE_FILE


def nested_test(manifest: Any) -> Callable[[Any], bool]:
    """Whether a nested repository at a path lies in the source (`nestedTest`)."""
    source = manifest if isinstance(manifest, dict) else {}
    include = _path_list(source.get("include"), True)
    exclude = _folded_list(source.get("exclude"), True)

    def test(written: Any) -> bool:
        stored = written[:-1] if isinstance(written, str) and written.endswith("/") else written
        if not isinstance(stored, str) or not in_grammar(stored) or _in_git(stored):
            return False
        if at_manifest_path(written):
            return True
        path = _nfc(stored)
        folder = path + "/"
        reached = path in include.files or folder in include.reaches or any(p in include.folders for p in _folder_prefixes(folder))
        folded = fold_path(path)
        return reached and folded not in exclude.files and not _excludes_folder(exclude, folded + "/")
    return test


def credential_file_name(name: str) -> str:
    return _ascii_fold(_HFS_IGNORABLE.sub("", name)).rstrip(" .")


def credential_file(path: str) -> bool:
    """A file that is a credential by its name, read as a case-insensitive or Windows file system resolves it."""
    written = path[path.rfind("/") + 1:]
    name = credential_file_name(written)
    return bool((CREDENTIAL_FILE.match(name) and not CREDENTIAL_FILE_OK.match(written)) or TOKEN_FILE.match(name))


def _credential_file_folded(path: str) -> bool:
    written = path[path.rfind("/") + 1:]
    name = fold_segment(written)
    return bool((CREDENTIAL_FILE.match(name) and not CREDENTIAL_FILE_OK.match(written)) or TOKEN_FILE.match(name))


def patch_paths_allowed(manifest: Any, paths: Any) -> List[str]:
    """DEC-0149 item 13: the paths of a patch that are not source, in the order given (empty: the patch applies)."""
    is_source = source_path_test(manifest)
    source = manifest if isinstance(manifest, dict) else {}
    any_exclude = bool(_strings(source.get("exclude")))

    def refused(path: Any) -> bool:
        if not is_source(path):
            return True
        folded = fold_path(_nfc(path))
        return (folded == SOURCE_FILE or credential_file(path) or _credential_file_folded(path)
                or (any_exclude and any(_SHORT_NAME.search(s) for s in folded.split("/"))))
    if not isinstance(paths, list):
        return ["paths"]
    return [(p if isinstance(p, str) else "paths[%d]" % i) for i, p in enumerate(paths) if refused(p)]


# #region credential and home shapes: the contract's credentialAt and homeAt, read with the source check's shapes
_PUBLIC_SIGNATURE = re.compile(r"(\"(?:sig|signature|signatures)\"[ \t]*:[ \t]*\")([A-Za-z0-9_-]{86})(\")", re.IGNORECASE)
_URL_IN_LINE = re.compile("[A-Za-z][A-Za-z0-9+.-]{0,63}://[^\t\n\x0b\x0c\r \x1c-\x1f\x85\xa0  - "
                          "    　\"'<>`]+")


def _secret_urls(line: str) -> List[Tuple[int, int]]:
    return [m.span() for m in _URL_IN_LINE.finditer(line) if _check._url_secret(m.group(0))] if "://" in line else []


def _unescaped(line: str) -> Optional[Tuple[str, List[int]]]:
    if "\\" not in line:
        return None
    text, origin = _check._unescaped_with_origin(line)
    return (text, [a for a, _ in origin]) if text != line else None


def _credential_in(written: str) -> int:
    line = _PUBLIC_SIGNATURE.sub(lambda m: m.group(1) + " " * len(m.group(2)) + m.group(3), written) if '"' in written else written
    found: List[int] = []
    block = _check.PRIVATE_KEY.search(line)
    if block:
        found.append(block.start())
    found += [m.start() for m in _check.JWK_PRIVATE.finditer(line) if _check._real(m.group(1))]
    found += [a for a, b in _jwt_spans(line) if _check._real(line[a:b])]
    found += [a for a, _ in _check._provider_keys(line)]
    found += [m.start() for m in _check._overlapping(_secrets._BEARER_INSIDE, line) if _check._real(m.group(0))]
    found += [a for a, _ in _secret_urls(line)][:1]
    for m in (_check._assigned(line) if ":" in line or "=" in line else ()):
        name, value = m.group(1), m.group(2)
        if _check._credential(name, value, _check._quoted(line, m)) and _secrets._long_secret(unquote(value)) \
                and _check._real(unquote(value)):
            found.append(m.start(2))
    return min(found) if found else -1


def _jwt_spans(text: str) -> List[Tuple[int, int]]:
    """`jwtSpans`: `JWT_SHAPE`'s leftmost, non-overlapping matches, read as the contract's one pass reads them."""
    return _secrets.jwt_spans(text)


def credential_at(line: str) -> int:
    """The index where a line first shows a credential, as written or with its JSON escapes undone, or -1."""
    written = _credential_in(line)
    if written >= 0:
        return written
    unescaped = _unescaped(line)
    if unescaped is None:
        return -1
    found = _credential_in(unescaped[0])
    return -1 if found < 0 else unescaped[1][found]


def _credential_url_spans(line: str) -> List[Tuple[int, int]]:
    written = _secret_urls(line)
    unescaped = _unescaped(line)
    if written or unescaped is None:
        return written
    text, origin = unescaped
    return [(origin[a], origin[b] if b < len(origin) else len(line)) for a, b in _secret_urls(text)]


def _own_secret_value(text: str) -> bool:
    return bool(_secrets.has_jwt(text) or _check.URL_SECRET_VALUE.search(text) or _secrets._long_secret(text))


def credential_shaped(text: str) -> bool:
    return credential_at(text) >= 0 or _own_secret_value(text)


def _prose_secret_value(text: str) -> bool:
    return bool(_secrets.has_jwt(text) or any(True for _ in _check._provider_keys(text))
                or _secrets._BEARER_INSIDE.search(text) or _secrets._long_secret(text))


def home_at(line: str) -> int:
    found = [m.start(1) for pattern in _check.HOME_PATHS for m in pattern.finditer(line)
             if len(m.group(1)) > 1 and m.group(1).lower() not in _check.NEUTRAL_HOMES]
    return min(found) if found else -1
# #endregion


def _forms(entry: str) -> List["re.Pattern[str]"]:
    """An instance string as written and in NFC, each also percent-encoded, form-encoded, JSON-escaped, with `\\/`, and
    with every character outside ASCII as `\\uXXXX`; matched without regard to case."""
    out: List[str] = []
    for written in (entry, _nfc(entry)):
        js = json.dumps(written, ensure_ascii=False)[1:-1]
        ascii_form = "".join(c if ord(c) < 0x80 else "".join("\\u%04x" % u for u in _units(c)) for c in js)
        percent = "".join(c if re.match(r"[A-Za-z0-9\-_.!~*'()]", c) else "".join("%%%02X" % b for b in c.encode("utf-8"))
                          for c in written)
        for form in (written, percent, percent.replace("%20", "+"), js, js.replace("/", "\\/"), ascii_form):
            if form not in out:
                out.append(form)
    return [re.compile(re.escape(f), re.IGNORECASE) for f in out]


def _units(c: str) -> List[int]:
    data = c.encode("utf-16-be", "surrogatepass")
    return [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]


def _first_of(patterns: List["re.Pattern[str]"], text: str) -> Tuple[int, str]:
    for form in (text, _nfc(text)):
        found = [m.start() for m in (p.search(form) for p in patterns) if m]
        if found:
            return min(found), form
    return -1, text


_LOCAL_CHAR = re.compile(r"[A-Za-z0-9._%+-]")
_DOMAIN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def _addresses(line: str) -> List[Tuple[int, str]]:
    found, floor = [], 0
    at = line.find("@")
    while at >= 0:
        start = at
        while start > floor and at - start < 64 and _LOCAL_CHAR.match(line[start - 1]):
            start -= 1
        if start != at:
            domain = _DOMAIN.match(line, at + 1)
            if domain:
                floor = domain.end()
                found.append((start, line[start:floor]))
        at = line.find("@", at + 1)
    return found


def _example_address(address: str) -> bool:
    domain = address[address.rfind("@") + 1:].lower()
    return (any(domain == n or domain.endswith("." + n) for n in ("example.com", "example.org", "example.net"))
            or domain.endswith((".invalid", ".test", ".example")))


def _image_name(text: str) -> bool:
    return text[text.rfind(".") + 1:].lower() in ("png", "jpg", "jpeg", "gif", "svg", "webp", "ico")


def _not_an_address(line: str, start: int, text: str) -> bool:
    return line[start + len(text):start + len(text) + 1] == ":" or _image_name(text)


_MARKDOWN = re.compile(r"\.(?:md|mdx|markdown)\Z", re.IGNORECASE | re.ASCII)
_JS_SPACE = "[" + _secrets.JS_SPACE + "]"
_LINK = re.compile(r"\]\(%s{0,64}<?([^)\]%s>]{1,2048})>?(?:%s{1,64}[^)\]]{0,2048})?\)"
                   % (_JS_SPACE, _secrets.JS_SPACE, _JS_SPACE))
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_LICENSE_FILE = re.compile(r"(?:LICENSE|LICENCE|COPYING)(?:\.%s+)?\Z" % _JS_DOT, re.IGNORECASE | re.ASCII)


def _decode_uri_component(raw: str) -> str:
    """`decodeURIComponent`, or the text as written when it would throw."""
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        return raw
    try:
        return unquote(raw, errors="strict")
    except UnicodeDecodeError:
        return raw


def _resolve(parts: List[str], raw: str) -> Optional[str]:
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(segment)
    return "/".join(parts)


def _resolve_link(file: str, target: str) -> Optional[str]:
    raw = _decode_uri_component(re.sub(r"[#?][\s\S]*\Z", "", target, count=1))
    return _resolve([] if raw.startswith("/") else file.split("/")[:-1], raw)


def source_tree_problems(value: Any) -> List[Dict[str, Any]]:
    """DEC-0149 item 8, the tree check (`sourceTreeProblems`)."""
    data = value if isinstance(value, dict) else {}
    manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
    problems: List[Dict[str, Any]] = []
    instance: List[Tuple[int, List["re.Pattern[str]"]]] = []
    if isinstance(data.get("instanceStrings"), list):
        for index, entry in enumerate(data["instanceStrings"]):
            if not isinstance(entry, str) or len(entry) < 3 or any(0xD800 <= ord(c) <= 0xDFFF for c in entry):
                problems.append({"kind": "short-instance-string", "entry": index})
            else:
                instance.append((index, _forms(entry)))
    if not _strings(manifest.get("include")):
        problems.append({"kind": "no-include"})
    allowed = {a.lower() for a, _ in _strings(manifest.get("publicAddresses"))}
    binaries = {_nfc(p) for p, _ in _strings(manifest.get("binaries"))}
    is_source, is_nested, is_unchecked = source_path_test(manifest), nested_test(manifest), unchecked_test(manifest)
    given = data.get("files") if isinstance(data.get("files"), list) else []
    files = [(f, i) for i, f in enumerate(given) if isinstance(f, dict)
             and (is_nested(f.get("path")) if f.get("nestedRepository") is True else is_source(f.get("path")))]
    source_paths = [f["path"] for f, _ in files if f.get("nestedRepository") is not True]
    fold_only = fold_only_exclude_test(manifest)
    folded_out = []
    for index, f in enumerate(given):
        if isinstance(f, dict) and f.get("nestedRepository") is not True:
            at = fold_only(f.get("path"))
            if at >= 0:
                folded_out.append({"kind": "excluded-by-fold", "file": index, "exclude": at})
    source_folders = {"/".join(parts[:k + 1]) for p in source_paths for parts in [_nfc(p).split("/")[:-1]] for k in range(len(parts))}

    def link_inside(target: str) -> bool:
        return target == "" or is_source(target) or _nfc(target) in source_folders

    for f, index in files:
        path = f["path"]
        binary = f.get("binary") is True and _nfc(path) != SOURCE_FILE
        if home_at(path) >= 0:
            problems.append({"kind": "home-path", "file": index})
        if credential_file(path) or credential_at(path) >= 0:
            problems.append({"kind": "credential", "file": index})
        for entry, patterns in instance:
            if _first_of(patterns, path)[0] >= 0:
                problems.append({"kind": "instance-string", "file": index, "entry": entry})
        if f.get("nestedRepository") is True:
            problems.append({"kind": "nested-repository", "file": index})
            continue
        if is_unchecked(path):
            continue
        if binary:
            if _nfc(path) not in binaries:
                problems.append({"kind": "binary", "file": index})
            continue
        text = f["text"] if isinstance(f.get("text"), str) else ""
        link_outside = False
        if f.get("link") is True:
            resolved = None if text.startswith("/") else _resolve(path.split("/")[:-1], text)
            link_outside = resolved is None or not link_inside(resolved)
        markdown = bool(_MARKDOWN.search(path))
        for at, raw in enumerate(text.split("\n")):
            line = raw[:-1] if raw.endswith("\r") else raw

            def place(kind: str, column: int, within: str = line, **extra: Any) -> None:
                problems.append(dict({"kind": kind, "file": index, "line": at + 1, "column": _u16(within[:column]) + 1}, **extra))
            home = home_at(line)
            if home >= 0:
                place("home-path", home)
            credential = credential_at(line)
            if credential >= 0:
                place("credential", credential)
            for entry, patterns in instance:
                found, form = _first_of(patterns, line)
                if found >= 0:
                    place("instance-string", found, form, entry=entry)
            urls = _credential_url_spans(line) if credential >= 0 else []
            address = next((s for s, t in _addresses(line) if t.lower() not in allowed and not _example_address(t)
                            and not _not_an_address(line, s, t) and not any(a <= s < b for a, b in urls)), None)
            if address is not None:
                place("email", address)
            if markdown:
                outside = None
                for m in _LINK.finditer(line):
                    target = m.group(1)
                    if target.startswith("#") or target.startswith("//") or _SCHEME.match(target):
                        continue
                    resolved = _resolve_link(path, target)
                    if resolved is None or not link_inside(resolved):
                        outside = m.start()
                        break
                if outside is not None:
                    place("link-outside", outside)
                    if at == 0:
                        link_outside = False
            if at == 0 and link_outside:
                place("link-outside", 0)
    problems += folded_out
    present = {_nfc(p) for p in source_paths}
    present_folders = {f for p in present for f in _folder_prefixes(p)}
    for written, at in _strings(manifest.get("include")):
        if not in_grammar(written, True):
            continue
        entry = _nfc(written)
        if not (entry in present_folders if entry.endswith("/") else entry in present):
            problems.append({"kind": "missing", "include": at})
    if isinstance(data.get("listed"), list):
        listed = [fold_path(_nfc(p)) for p, _ in _strings(data["listed"]) if _u16(p) <= 513]
        listed_files = set(listed)
        listed_folders = {f for p in listed for f in _folder_prefixes(p)}
        naming = {p["exclude"] for p in folded_out}
        for written, at in _strings(manifest.get("exclude")):
            if not in_grammar(written, True):
                continue
            entry = fold_path(_nfc(written))
            used = entry in listed_folders if entry.endswith("/") else (entry in listed_files or entry + "/" in listed_folders)
            if at not in naming and not used:
                problems.append({"kind": "unused-exclude", "exclude": at})
    linked = {f["path"] for f, _ in files if f.get("link") is True}
    if not any("/" not in p and _LICENSE_FILE.match(p) and p not in linked for p in source_paths):
        problems.append({"kind": "no-license"})
    return problems


# #region the manifest and the package (FAC-SEM-156, FAC-SEM-157, FAC-SEM-160)
def _slot_findings(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-156", "instancePath": at, "message": message})
    if isinstance(value.get("description"), str) and _prose_secret_value(value["description"]):
        flag("/description", "a manifest never holds a value: this looks like a credential")
    names: List[Any] = []
    stores: List[Any] = []
    for slot, index in _objects(value.get("slots")):
        if slot.get("name") in names:
            flag("/slots/%d/name" % index, "slots[%d] is declared twice" % index)
        names.append(slot.get("name"))
        for field in ("name", "purpose"):
            text = slot.get(field)
            if isinstance(text, str) and (_secrets.secret_value(text) or credential_shaped(text)
                                          or credential_shaped(json.dumps(text, ensure_ascii=False))):
                flag("/slots/%d/%s" % (index, field), "a slot is named, never filled: this looks like a credential")
        if slot.get("kind") == "store" and isinstance(slot.get("path"), str):
            if slot["path"] in stores:
                flag("/slots/%d/path" % index, "slots[%d].path is declared twice" % index)
            stores.append(slot["path"])
    return findings


def _grammar_finding(member: str, path: str, index: int, at: str = "") -> List[Dict[str, str]]:
    if not SOURCE_PATH.match(path) or in_grammar(path, True):
        return []
    effect = "names, reaches and removes nothing" if member != "exclude" else "still removes its widest reading"
    return [{"code": "FAC-SEM-157", "instancePath": "%s/%s/%d" % (at, member, index),
             "message": "%s[%d] is outside the path grammar as a file system reads it, so it %s" % (member, index, effect)}]


def _path_findings(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-157", "instancePath": at, "message": message})
    include = _strings(value.get("include"))
    for member in ("include", "exclude", "binaries"):
        seen: Set[str] = set()
        for path, index in _strings(value.get(member)):
            if path in seen:
                flag("/%s/%d" % (member, index), "%s[%d] is listed twice" % (member, index))
            seen.add(path)
            if _in_git(path):
                flag("/%s/%d" % (member, index), "%s[%d] lies in .git, which is never source" % (member, index))
            findings.extend(_grammar_finding(member, path, index))
    includes = _path_list(value.get("include"))
    folded_includes = _folded_list(value.get("include"))
    excludes = _folded_list(value.get("exclude"), True)
    is_source = source_path_test(value)

    def prefixes_of(written: str) -> List[str]:
        return _folder_prefixes(fold_path(_nfc(written))) if in_grammar(written, True) else []
    widened = _folded_list([e for e, _ in _strings(value.get("exclude")) if not in_grammar(e, True)], True)
    for written, index in include:
        path = fold_path(_nfc(written))
        dead = (excludes.all or any(f != path and (f in excludes.folders or f[:-1] in excludes.files) for f in prefixes_of(written))
                or path in widened.files or any(f in widened.folders or f[:-1] in widened.files for f in prefixes_of(written)))
        if dead:
            flag("/include/%d" % index, "include[%d] lies inside an exclude path, so it names nothing" % index)
    folded_include_paths = [fold_path(_nfc(p)) for p, _ in include if in_grammar(p, True)]
    for path, index in _strings(value.get("exclude")):
        if not in_grammar(path, True):
            continue
        folded = fold_path(_nfc(path))
        if folded in folded_includes.files or folded in folded_includes.folders or folded + "/" in folded_includes.folders:
            flag("/exclude/%d" % index, "exclude[%d] is an include path: it would remove it whole, so leave both out" % index)
        elif not any(f in folded_includes.folders for f in prefixes_of(path)) and not any(
                i.startswith(folded if folded.endswith("/") else folded + "/") for i in folded_include_paths):
            flag("/exclude/%d" % index, "exclude[%d] lies inside no include folder, so it removes nothing" % index)
    for path, index in _strings(value.get("binaries")):
        if not in_grammar(path, True):
            continue
        if fold_path(_nfc(path)) == SOURCE_FILE:
            flag("/binaries/%d" % index, "binaries[%d] names %s, which is always read as text" % (index, SOURCE_FILE))
            continue
        if not _in_git(path) and not is_source(path):
            flag("/binaries/%d" % index, "binaries[%d] is not a file of the source" % index)
    unchecked: Set[str] = set()
    for path, index in _unchecked_paths(value):
        if path in unchecked:
            flag("/unchecked/%d/path" % index, "unchecked[%d] is listed twice" % index)
        unchecked.add(path)
        if not path.endswith("/") and in_grammar(path) and fold_path(_nfc(path)) == SOURCE_FILE:
            flag("/unchecked/%d/path" % index, "unchecked[%d] names %s, which is always read" % (index, SOURCE_FILE))
            continue
        inside = (in_grammar(path, True) and not _in_git(_nfc(path)[:-1])
                  and any(p in includes.folders for p in _folder_prefixes(_nfc(path)))
                  and not _excludes_folder(excludes, fold_path(_nfc(path)))) if path.endswith("/") else is_source(path)
        if not inside:
            flag("/unchecked/%d/path" % index, "unchecked[%d] is not in the source" % index)
    return findings


def manifest_findings(manifest: Any) -> List[Dict[str, str]]:
    """FAC-SEM-156 and FAC-SEM-157 over a source manifest (the contract's `source-manifest` rules)."""
    return _slot_findings(manifest) + _path_findings(manifest) if isinstance(manifest, dict) else []


def package_findings(source: Any, package: Any) -> List[Dict[str, str]]:
    """FAC-SEM-160: the package's secrets[] are the source's secret slots, by name and optional; its state[] paths the
    store slots' paths, when state[] holds any entry."""
    if not isinstance(source, dict) or not isinstance(package, dict):
        return []
    findings: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-160", "instancePath": at, "message": message})
    slots = [s for s, _ in _objects(source.get("slots"))]
    secrets = {s["name"]: s.get("optional") is True for s in slots if s.get("kind") == "secret" and isinstance(s.get("name"), str)}
    stores = {s["path"] for s in slots if s.get("kind") == "store" and isinstance(s.get("path"), str)}
    packaged = _objects(package.get("secrets"))
    names = {e.get("name") for e, _ in packaged}
    for name in secrets:
        if name not in names:
            flag("/package/secrets", "the source's secret slot %s is not in the package's secrets[]" % name)
    for entry, index in packaged:
        name = entry.get("name")
        if not isinstance(name, str) or name not in secrets:
            flag("/package/secrets/%d/name" % index, "secrets[%d] is no secret slot of the source" % index)
        elif secrets[name] != (entry.get("optional") is True):
            flag("/package/secrets/%d/optional" % index, "secrets[%d] is %soptional in the source" % (index, "" if secrets[name] else "not "))
    state = package.get("state")
    if not isinstance(state, list) or not state:
        return findings
    paths = {e.get("path") for e, _ in _objects(state)}
    for path in sorted(stores):
        if path not in paths:
            flag("/package/state", "a store slot's path of the source is not in the package's state[]")
    for entry, index in _objects(state):
        if not isinstance(entry.get("path"), str) or entry["path"] not in stores:
            flag("/package/state/%d/path" % index, "state[%d] is no store slot of the source" % index)
    return findings


def package_members(manifest: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The `secrets[]` and `state[]` a packer writes from a source manifest: each secret slot by name, purpose and
    optional, each store slot's path with its purpose (DEC-0149, the package's FAC-SEM-160)."""
    secrets, state = [], []
    for slot, _ in _objects(manifest.get("slots")):
        if slot.get("kind") == "secret" and isinstance(slot.get("name"), str):
            entry = {"name": slot["name"], "purpose": slot.get("purpose")}
            if slot.get("optional") is True:
                entry["optional"] = True
            secrets.append(entry)
        elif slot.get("kind") == "store" and isinstance(slot.get("path"), str):
            state.append({"path": slot["path"], "purpose": slot.get("purpose")})
    return secrets, state
# #endregion


# #region the folder check: `fabric_source_check.py check` on a tree whose root holds fabric.source.json
MESSAGES = {
    "home-path": "a path in a person's home folder belongs to the instance, never to the source",
    "credential": "shaped like a credential: a key reaches the agent through its slot, never through the source",
    "binary": "a binary file the manifest does not list in binaries: it is source only when listed",
    "nested-repository": "a nested repository: name it in exclude and check it in its own tree",
    "instance-string": "a string of the owner's list: the installation's own strings never travel",
    "missing": "an include path names no file of the tree",
    "short-instance-string": "an instance string shorter than 3 characters is not looked for",
    "no-include": "the source manifest names no include path, so nothing is source",
    "email": "an e-mail address not listed in publicAddresses: a person's address belongs to the instance",
    "link-outside": "a link to a path outside the source: a source export does not carry its target",
    "no-license": "no licence file at the source's root (LICENSE, LICENCE or COPYING)",
    "unused-exclude": "an exclude path names nothing the tree holds, in any letter case: check its spelling",
    "excluded-by-fold": "an exclude path names this file only in another spelling: it is left out and never read",
}


def read_manifest(root: Path) -> Dict[str, Any]:
    """The source manifest at a tree's root, refused (CheckError, exit 2) when it is no `fabric-source/1` object."""
    path = root / SOURCE_FILE
    if path.is_dir():
        raise _check.CheckError("%s is a folder, not a file: the manifest cannot be read" % SOURCE_FILE)
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise _check.CheckError("%s cannot be read as UTF-8 JSON" % SOURCE_FILE)
    if not isinstance(value, dict) or value.get("format") != SOURCE_FORMAT:
        raise _check.CheckError("%s is not a %s manifest (its format member)" % (SOURCE_FILE, SOURCE_FORMAT))
    return value


def _nested_folders(root: Path, paths: List[str]) -> Set[str]:
    """In a walk, the folders below the root that hold their own `.git`: each a nested repository."""
    folders = {p.rsplit("/", 1)[0] for p in paths if "/" in p}
    found = set()
    for folder in sorted({f for p in folders for f in ["/".join(p.split("/")[:k + 1]) for k in range(p.count("/") + 1)]}):
        if not any(folder.startswith(n + "/") for n in found) and (root / folder / ".git").exists():
            found.add(folder)
    return found


def check_folder(root: Path, listing: List[str], mode: str, entries: List[str], unreadable: List[str],
                 dependencies: List[str]) -> Dict[str, Any]:
    """The tree check over the files a folder holds, under its fabric.source.json: findings with a column and a
    severity, every path printed as `redact` prints it, never a value found."""
    manifest = read_manifest(root)
    seen = _check._Seen()
    strings = [(n, e) for n, e in enumerate(entries, 1) if e and not e.startswith(_check.HOME_ENTRY)]
    owner_homes = _check._owner_homes(entries)
    nested = _nested_folders(root, listing) if mode == "walk" else set()
    files: List[Dict[str, Any]] = []
    not_read: List[Dict[str, str]] = [{"path": p, "why": "unreadable"} for p in unreadable]
    is_source, unchecked = source_path_test(manifest), unchecked_test(manifest)
    listed: List[str] = []
    for folder in sorted(nested):
        files.append({"path": folder, "nestedRepository": True})
        listed.append(folder)
    for path in listing:
        if any(path.startswith(n + "/") for n in nested):
            continue
        listed.append(path)
        full = root / path
        entry: Dict[str, Any] = {"path": path}
        try:
            if full.is_symlink():
                entry.update(link=True, text=os.readlink(str(full)))
            elif full.is_dir():
                entry["nestedRepository"] = True
                listed.append(path + "/")
            elif is_source(path):
                data = full.read_bytes()
                if b"\0" in data[:8192] and _nfc(path) != SOURCE_FILE:
                    entry["binary"] = True
                else:
                    entry["text"] = data.decode("utf-8", "replace")
        except OSError:
            if is_source(path):
                not_read.append({"path": path, "why": "unreadable"})
            continue
        files.append(entry)
    problems = source_tree_problems({"manifest": manifest, "files": files, "listed": listed,
                                     "instanceStrings": [e for _, e in strings]})
    findings: List[Dict[str, Any]] = []
    for f in manifest_findings(manifest):
        findings.append({"path": SOURCE_FILE, "line": 0, "column": 0, "kind": "manifest", "severity": "blocking",
                         "rule": "%s at %s: %s" % (f["code"], f["instancePath"], f["message"])})
    for p in problems:
        path = files[p["file"]]["path"] if "file" in p else SOURCE_FILE
        rule = MESSAGES[p["kind"]]
        if "entry" in p:
            rule += " (line %d of the owner's list)" % strings[p["entry"]][0]
        for member in ("include", "exclude"):
            if member in p:
                rule += " (%s[%d])" % (member, p[member])
        if "line" in p:
            text = files[p["file"]].get("text", "").split("\n")[p["line"] - 1]
            _check._text_findings(text.rstrip("\r"), entries, seen)
        elif "file" in p:
            _check._text_findings(path, entries, seen)
        findings.append({"path": path, "line": p.get("line", 0), "column": p.get("column", 0), "kind": p["kind"],
                         "severity": "blocking" if p["kind"] in BLOCKING_KINDS else "warning", "rule": rule})
    if owner_homes:  # a declared home (`home: <name>`) is the owner's in every form, neutral or one letter
        found = {(f["path"], f["line"]) for f in findings if f["kind"] == "home-path"}
        for entry in files:
            if "text" not in entry or not is_source(entry["path"]) or unchecked(entry["path"]):
                continue
            for number, line in enumerate(entry["text"].split("\n"), 1):
                line = line[:-1] if line.endswith("\r") else line
                spans = [a for a, b in _check._home_names(line, owner_homes) if line[a:b].lower() in owner_homes]
                if spans and (entry["path"], number) not in found:
                    _check._text_findings(line, entries, seen)
                    findings.append({"path": entry["path"], "line": number, "column": _u16(line[:min(spans)]) + 1,
                                     "kind": "home-path", "severity": "blocking", "rule": MESSAGES["home-path"]})
    shown: Dict[str, str] = {}  # one redaction per path, however many findings it has
    for item in findings + not_read:
        if item["path"] not in shown:
            shown[item["path"]] = _check.redact(item["path"], entries, seen)
        item["path"] = shown[item["path"]]
    read = sum(1 for e in files if "text" in e and is_source(e["path"]))
    source = sum(1 for e in files if e.get("nestedRepository") is not True and is_source(e["path"]))
    return {"mode": mode, "manifest": True, "files": read, "source": source,
            "skipped": {"binary": 0, "unreadable": len(not_read), "excluded": len(listing) - source, "nested": 0,
                        "dependencies": len(dependencies)},
            "notRead": not_read, "findings": findings, "dependencies": [_check.redact(d, entries, seen) for d in dependencies]}


def print_run(result: Dict[str, Any], entries: List[str], listed_any: bool, as_json: bool, _print: Callable[[str], None]) -> int:
    """The run under a source manifest: exit 1 on a blocking finding, 0 when only warnings remain and every source
    file was read, 2 when one was not."""
    findings = result["findings"]
    blocking = [f for f in findings if f["severity"] == "blocking"]  # type: ignore[union-attr,index]
    complete = not result["notRead"]
    result.update({"instanceStrings": sum(1 for e in entries if e and not e.startswith(_check.HOME_ENTRY)),
                   "ownerHomes": sum(1 for e in entries if e.startswith(_check.HOME_ENTRY)), "instanceList": listed_any,
                   "blocking": bool(blocking), "complete": complete})
    if as_json:
        _print(json.dumps(result, indent=2))
    else:
        for f in findings:  # type: ignore[union-attr]
            _print("%s:%s:%s: %s%s (%s)" % (f["path"], f["line"], f["column"], "" if f["severity"] == "blocking"
                                            else "warning: ", f["kind"], f["rule"]))
        for n in result["notRead"]:  # type: ignore[union-attr]
            _print("%s: not read (%s)" % (n["path"], n["why"]))
        _print("fabric.source.json decides the source: %d source file(s), %d read as text (%s), %d blocking finding(s), "
               "%d warning(s); %d path(s) not source; .fabric-source-ignore and --exclude are not read under a manifest"
               % (result["source"], result["files"], "what Git would commit" if result["mode"] == "git" else "a walk",
                  len(blocking), len(findings) - len(blocking), result["skipped"]["excluded"]))  # type: ignore
    if blocking:
        return 1
    return 0 if complete else 2
# #endregion
