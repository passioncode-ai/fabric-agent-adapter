#!/usr/bin/env python3
"""How fabric_source_check.py prints a path without repeating what it found (FAA-188 part 1; split from the check in
FAA-190): `redact` and `Seen`, what the check found anywhere in the tree. Beside fabric_source_check.py, which imports
it and hands it its readers (`Readers`), so this module reads no rule of its own. Standard library only.
"""

from __future__ import annotations

import bisect
import re
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from fabric_source_homes import _NAME_JOIN, _NAME_START, _name_parts, _owner_homes, _spellings


class Readers:
    """The check's own readers, so a path is judged by the rules a line is."""

    __slots__ = ("secret_finding", "secret_spans", "url_credentials", "unescaped_with_origin", "json_unescaped",
                 "entry_spans", "home_names", "fold_map", "neutral")

    def __init__(self, secret_finding: Callable[[str], Optional[str]],
                 secret_spans: Callable[..., List[Tuple[int, int]]],  # (text, urls=True)
                 url_credentials: Callable[[str], List[str]],  # the credential parts of the URLs a text holds
                 unescaped_with_origin: Callable[[str], Tuple[str, List[Tuple[int, int]]]],
                 json_unescaped: Callable[[str], str],
                 entry_spans: Callable[[str, List[str]], List[Tuple[int, int, int]]],
                 home_names: Callable[..., List[Tuple[int, int]]],
                 fold_map: Callable[[str], object],
                 neutral: Set[str]) -> None:
        self.secret_finding, self.secret_spans, self.url_credentials = secret_finding, secret_spans, url_credentials
        self.unescaped_with_origin, self.json_unescaped = unescaped_with_origin, json_unescaped
        self.entry_spans, self.home_names, self.fold_map, self.neutral = entry_spans, home_names, fold_map, neutral


#: A name shorter than this is masked only as a word (no ASCII letter or digit beside it): `bo` found as a home is not
#: the `bo` of `robot` (FAA-190 (53), (76)). From four characters a run is the name wherever it stands (`jdoe2024`).
WORD_ONLY_BELOW = 4
_WORD = "[A-Za-z0-9]"
#: The characters a key, a JWT or a JWK's `d` is made of: what a cut one's rest holds (FAA-190 (28)).
_KEY_REST = re.compile(r"[A-Za-z0-9_-]+")


def home_spellings(found: Iterable[str], owner: Iterable[str], neutral: Set[str]) -> Set[str]:
    """The home names found, as `seen` keeps them: without a trailing `.` or `_` (`/Users/<name>./` is `<name>`, FAA-190 (39)),
    each dotted, underscored or dashed part of three or more characters that is no neutral name (`<name>.CORPORATE` is
    both, FAA-190 (55)), and every spelling of a declared home one of them spells."""
    names: Set[str] = set()
    for name in found:
        name = name.rstrip("._")
        if len(name) < 2:
            continue
        names.add(name)
        names |= {p for p in re.split(r"[._-]+", name) if len(p) >= 3 and p.lower() not in neutral and p != name}
    return _spellings(names, owner)


def _merged(spans: Iterable[Tuple[int, int]]) -> List[List[int]]:
    merged: List[List[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


class Seen:
    """What the check found anywhere in the tree, so that no printed path repeats it: a file named after its owner, or
    after the key it holds, prints with the name as `<home>` and the segment as `<secret>`, and an 8-character part of
    an owner's string found in a file as `<line N>` (FAA-190 (59))."""

    def __init__(self, read: Readers) -> None:
        self.read = read
        self.names: Set[str] = set()
        self.grams: Set[str] = set()  # every 8-character run of a found value: a URL's credential parts only
        self.entry_grams: Dict[str, int] = {}  # every 8-character run of a found owner's string, by its line
        self._names_pattern: Optional["re.Pattern[str]"] = None
        self._declared: Dict[str, bool] = {}

    def add_values(self, text: str) -> None:
        sources = [(text, self.read.secret_spans(text, False))]
        if "\\" in text:
            unescaped = self.read.json_unescaped(text)
            if unescaped != text:
                sources.append((unescaped, self.read.secret_spans(unescaped, False)))
        values: List[str] = []
        for source, spans in sources:
            # overlapping spans (each start of `sk-sk-sk-...` runs to the end) merged first: their runs are the same,
            # and reading each span apart cost the square of the line
            values += [source[a:b] for a, b in _merged(spans)]
        # a URL's host and path name no one: only its credential parts (a password, a query value) are kept, so an
        # unrelated path sharing the host is not masked, and the set costs what the credentials do (FAA-190 (45), (54))
        values += self.read.url_credentials(text)
        for value in values:
            self.grams.update(value[i:i + 8] for i in range(max(0, len(value) - 7)))

    def add_entries(self, numbers: Iterable[int], entries: List[str]) -> None:
        """The owner's strings found in a text: every 8-character run of a longer one is masked in a printed path."""
        for number in numbers:
            entry = entries[number - 1]
            for i in range(len(entry) - 7 if len(entry) > 8 else 0):
                self.entry_grams.setdefault(entry[i:i + 8], number)

    def names_pattern(self) -> "re.Pattern[str]":
        """Every name found, longest first, as one pattern (a short one only as a word): read once the tree is read."""
        if self._names_pattern is None:
            ordered = sorted(self.names, key=len, reverse=True)
            long_ = "|".join(re.escape(n) for n in ordered if len(n) >= WORD_ONLY_BELOW)
            short = "|".join(re.escape(n) for n in ordered if len(n) < WORD_ONLY_BELOW)
            parts = ([long_] if long_ else []) + (["%s(?:%s)(?!%s)" % (_NAME_START, short, _WORD)] if short else [])
            # a lookahead reads every start, so two names that overlap in a path are both marked
            self._names_pattern = re.compile("(?=(%s))" % "|".join(parts), re.IGNORECASE)
        return self._names_pattern

    def declared_found(self, body: str) -> bool:
        """Whether a declared home's pattern spells a name found in the tree, decided once (FAA-190 (87))."""
        if body not in self._declared:
            pattern = re.compile(body, re.IGNORECASE)
            self._declared[body] = any(pattern.fullmatch(name) for name in self.names)
        return self._declared[body]


def _segments(path: str) -> List[Tuple[int, int]]:
    spans, offset = [], 0
    for segment in path.split("/"):
        spans.append((offset, offset + len(segment)))
        offset += len(segment) + 1
    return spans


def _found_spans(text: str, read: Readers) -> List[Tuple[int, int]]:
    """The spans of credential-shaped values in a text, as written and with its JSON escapes undone (mapped back)."""
    spans = list(read.secret_spans(text))
    if "\\" in text:
        unescaped, origin = read.unescaped_with_origin(text)
        if unescaped != text:
            spans += [(origin[a][0], origin[b - 1][1]) for a, b in read.secret_spans(unescaped) if b > a]
    return spans


def _guard(path: str, spans: List[Tuple[int, int]], masked: List[bool], read: Readers) -> None:
    """While what is left still holds a credential, mask the segments its spans touch, else the last one left."""
    for _ in range(len(spans)):
        # a masked segment keeps its length, so the spans read in what is left are offsets in the path
        left = "/".join(" " * (b - a) if m else path[a:b] for (a, b), m in zip(spans, masked))
        if not read.secret_finding(left):
            return
        in_left = _found_spans(left, read)  # once a pass: read per segment, a long path cost the cube of its folders
        hit = [i for i, (s, e) in enumerate(spans) if not masked[i] and any(s < b and a < e for a, b in in_left)]
        if not hit:
            unmasked = [i for i, m in enumerate(masked) if not m]
            if not unmasked:
                return
            hit = [unmasked[-1]]
        for i in hit:
            masked[i] = True


def _folded_finds(text: str, find: Callable[[str], Iterable[Tuple[int, int]]], read: Readers) -> List[Tuple[int, int]]:
    """`find` on a text that is not ASCII read casefolded as well, mapped back: a ligature (U+FB01 for `fi`) or a sharp
    s spells a name only after casefolding, which a case-insensitive pattern does not do (FAA-190 (25))."""
    if text.isascii():
        return []
    folded = read.fold_map(text)
    return [folded.span(a, b) for a, b in find(folded.text) if b > a]  # type: ignore[attr-defined]


def redact(path: str, entries: List[str], seen: Optional[Seen], read: Readers) -> str:
    """A path as it may be printed: an owner's string as `<line N>` (its line in the owner's list), a real home
    folder's name as `<home>`, and each segment in which a credential is found as `<secret>`, whole (a span inside a
    segment can miss a second value the first one runs into). The segments a found value's span touches are masked, and
    the next one after a key, a JWT or a JWK's `d` a `/` cuts (its rest, FAA-190 (28)). While what is left still holds
    a credential together, the segments that finding's spans touch are masked, else the last one left, and so again on
    the path as printed, with its marks (FAA-190 (19)), so what is printed holds no finding and its first folders still
    name the place. With `seen`, what the check found elsewhere in the tree is masked too: a home name at every
    occurrence (a short one as a word), a segment holding a run of 8 characters of a found value as `<secret>`, and a
    run of 8 characters of a found owner's string as `<line N>`."""
    spans = _segments(path)
    starts = [a for a, _ in spans]
    masked = [bool(read.secret_finding(path[a:b])) for a, b in spans]
    for a, b in _found_spans(path, read):
        for i, (s, e) in enumerate(spans):
            if s < b and a < e:
                masked[i] = True
            # a value that ends where its segment does, before a `/`: a key cut by the path, whose rest is the next
            # segment, and the ones after it while they hold only a key's characters
            if e == b and i + 1 < len(spans) and b > a:
                masked[i + 1] = True
                for k in range(i + 2, len(spans)):
                    if not _KEY_REST.fullmatch(path[spans[k - 1][0]:spans[k - 1][1]]) or \
                            not _KEY_REST.fullmatch(path[spans[k][0]:spans[k][1]]):
                        break
                    masked[k] = True
    _guard(path, spans, masked, read)
    if seen is not None and seen.grams:  # a run of a value found elsewhere in the tree, across a `/` too
        for k in range(len(path) - 7):
            if path[k:k + 8] in seen.grams:  # its segments by their starts: never every segment a hit (FAA-190 (58))
                for i in range(max(0, bisect.bisect_right(starts, k) - 1), bisect.bisect_left(starts, k + 8)):
                    masked[i] = True
    marks = [(s, e, "<line %d>" % n) for s, e, n in read.entry_spans(path, entries)]
    owner = _owner_homes(entries)
    found = read.home_names(path, owner)
    marks += [(s, e, "<home>") for s, e in found]
    if seen is not None and seen.entry_grams:  # an 8-character part of an owner's string found in the tree
        folded = None if path.isascii() else read.fold_map(path)
        text = path.lower() if folded is None else folded.text  # type: ignore[attr-defined]
        for k in range(len(text) - 7):
            number = seen.entry_grams.get(text[k:k + 8])
            if number is not None:
                s, e = (k, k + 8) if folded is None else folded.span(k, k + 8)  # type: ignore[attr-defined]
                marks.append((s, e, "<line %d>" % number))
    marks += [(s, e, "<secret>") for (s, e), m in zip(spans, masked) if m]
    # the path with what is marked so far blanked: a mark's edge is a word's edge, so a name glued to an owner's string
    # or a found name is read as a word (FAA-190 (88)); every offset stays the path's
    blanked = list(path)
    for s, e, _ in marks:
        blanked[s:e] = " " * (e - s)
    bounded = "".join(blanked)
    path_names = home_spellings({path[s:e] for s, e in found}, owner, read.neutral)

    def word(body: str, as_word: bool) -> str:
        """The name's pattern, read only where a word starts and ends when `as_word` (a separator's escape before it
        starts a word too, `_NAME_START`)."""
        return "%s(?:%s)(?!%s)" % (_NAME_START, body, _WORD) if as_word else body

    def mark(pattern: str) -> None:
        compiled = re.compile(pattern, re.IGNORECASE)
        finds = [m.span() for m in compiled.finditer(bounded)]
        finds += _folded_finds(bounded, lambda t: (m.span() for m in compiled.finditer(t)), read)
        marks.extend((s, e, "<home>") for s, e in finds if e > s)

    # a declared home is the owner's own name: its parts joined by none or any run of the separators a tool writes
    # (a space, `.`, `_`, `-`, `+`, and their percent-encodings and escapes); found in the tree it is masked wherever it
    # stands, and a short one, or one found nowhere, only as a word, so `home: app` leaves `mapping` readable
    for declared in owner:
        parts = _name_parts(declared)
        letters = sum(len(part) for part in parts)
        body = (_NAME_JOIN + ("*" if letters >= 3 else "+")).join(re.escape(part) for part in parts)
        if letters < 3 and len(parts) < 2:
            continue
        here = any(re.fullmatch(body, name, re.IGNORECASE) for name in path_names)
        known = here or (seen is not None and seen.declared_found(body))
        if letters < 3 and not known:
            continue
        mark(word(body, not known or letters < WORD_ONLY_BELOW))
    for name in path_names:
        mark(word(re.escape(name), len(name) < WORD_ONLY_BELOW))
    if seen is not None and seen.names:
        pattern = seen.names_pattern()
        marks += [(m.start(1), m.end(1), "<home>") for m in pattern.finditer(bounded) if m.end(1) > m.start(1)]
        marks += [(s, e, "<home>") for s, e in
                  _folded_finds(bounded, lambda t: (m.span(1) for m in pattern.finditer(t)), read)]
    return _printed(path, marks, read)


def _render(path: str, marks: List[Tuple[int, int, str]]) -> str:
    out, last = [], 0
    for start, end, label in sorted(marks):
        if start < last:  # overlapping marks: the first covers the union, so no part of either is printed
            last = max(last, end)
            continue
        out += [path[last:start], label]
        last = end
    return "".join(out) + path[last:]


def _printed(path: str, marks: List[Tuple[int, int, str]], read: Readers) -> str:
    """The path with its marks, guarded once more as it is printed: a mark can join what stood apart, or take away the
    synthetic word that kept a value beside it from being one (FAA-190 (19)); such a segment prints as `<secret>`."""
    shown = _render(path, marks)
    if not read.secret_finding(shown):
        return shown
    parts = shown.split("/")
    spans = _segments(shown)
    masked = [part == "<secret>" for part in parts]
    for a, b in _found_spans(shown, read):
        for i, (s, e) in enumerate(spans):
            if s < b and a < e:
                masked[i] = True
    _guard(shown, spans, masked, read)
    return "/".join("<secret>" if m else part for part, m in zip(parts, masked))
