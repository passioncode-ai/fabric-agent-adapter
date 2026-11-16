#!/usr/bin/env python3
"""How fabric_source_check.py reads the owner's list and finds its strings in a text (FAA-188 part 1; split from the
check in FAA-190): one entry a line, casefolded and composed, a declared home (`home: <name>`) kept apart, and a text
folded the same way with each match mapped back to the characters it came from. Beside fabric_source_check.py, which
imports it. Standard library only.
"""

from __future__ import annotations

from array import array
import bisect
import io
from pathlib import Path
import re
import unicodedata
from typing import List, Tuple

from fabric_source_ignore import CheckError
from fabric_source_homes import HOME_ENTRY

#: Characters that stand inside a word and show nothing: a soft hyphen (HTML's `&shy;`), a zero-width space, a word
#: joiner, a byte-order mark, the invisible operators and every direction mark, embedding and isolate. A text is
#: compared without them (FAA-190 (93)), so a listed string holding one inside could never match: it is refused
#: (FAA-190 (90)). The joiners (U+200C, U+200D) are not here: an emoji or a Persian word needs one, and both sides keep it.
INVISIBLE = re.compile("[­؜᠎​‎‏‪-‮⁠-⁤⁦-⁩﻿]")


def _ignorable_edge(c: str) -> bool:
    """White space, a format character, or a default-ignorable code point that is not one (a variation selector, the
    combining grapheme joiner, a Hangul filler, a Mongolian free variation selector): nothing an entry's end holds
    (FAA-190 (94))."""
    if c.isspace() or unicodedata.category(c) == "Cf":
        return True
    cp = ord(c)
    return (cp in (0x34F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180F, 0x3164, 0xFFA0) or 0x180B <= cp <= 0x180D
            or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF)


class Folded:
    """A text as an entry is compared with it (`text`), and where each of its characters came from: pieces, each an
    output start, a source start and end, and whether it maps one character for one (a run of ASCII or of letters
    whose fold is one letter). Kept in arrays, never a list per character, so a line of a few MB costs a few times its
    size (FAA-190 (79))."""

    __slots__ = ("text", "_out", "_src", "_end", "_linear")

    def __init__(self, text: str, out: array, src: array, end: array, linear: bytearray) -> None:
        self.text, self._out, self._src, self._end, self._linear = text, out, src, end, linear

    def span(self, a: int, b: int) -> Tuple[int, int]:
        """The source characters a match of `text[a:b]` (b > a) came from, whole pieces at both ends."""
        i = bisect.bisect_right(self._out, a) - 1
        j = bisect.bisect_right(self._out, b - 1) - 1
        start = self._src[i] + (a - self._out[i]) if self._linear[i] else self._src[i]
        end = self._src[j] + (b - self._out[j]) if self._linear[j] else self._end[j]
        return start, end


_ASCII_RUN = re.compile(r"[\x00-\x7f]+")


def fold_map(text: str) -> Folded:
    """Text as an entry is compared: each letter with the marks after it casefolded, then composed (NFC), so `é` typed
    in the list finds a name a file system stored decomposed and `ß` finds `ss`, and every INVISIBLE character left
    out. Folding changes lengths both ways, so a match is mapped back through the pieces (`Folded.span`), never by its
    offsets. A run of ASCII is folded at once (lowered), so a mostly ASCII line costs about what an ASCII one does."""
    out_text = io.StringIO()  # never a list of one-character strings: about 50 bytes each
    out, src, end, linear = array("q"), array("q"), array("q"), bytearray()
    size = 0

    def piece(folded: str, a: int, b: int) -> None:
        nonlocal size
        one_for_one = len(folded) == b - a
        if one_for_one and linear and linear[-1] and end[-1] == a and out[-1] + (end[-1] - src[-1]) == size:
            end[-1] = b  # one more character mapped one for one: the run grows
        else:
            out.append(size)
            src.append(a)
            end.append(b)
            linear.append(1 if one_for_one else 0)
        out_text.write(folded)
        size += len(folded)

    def slow(lo: int, hi: int) -> None:
        """The pieces of text[lo:hi]: a letter with the marks it composes with, as the reader of a name joins them."""
        if lo >= hi:
            return
        run, last = lo, text[lo]
        for k in range(lo + 1, hi + 1):
            if k < hi:
                joined = unicodedata.normalize("NFC", last + text[k])
                if unicodedata.combining(text[k]) or len(joined) < len(last) + 1:  # a mark, or a jamo or vowel sign
                    last = joined[-1:]
                    continue
                last = text[k]
            chunk = text[run:k]
            piece("" if INVISIBLE.fullmatch(chunk) else unicodedata.normalize("NFC", chunk.casefold()), run, k)
            run = k

    pos = 0
    for m in _ASCII_RUN.finditer(text):
        a, b = m.span()
        if b < len(text):
            b -= 1  # the last ASCII character may take the mark after it: read with what follows
        slow(pos, a)
        if b > a:
            piece(text[a:b].lower(), a, b)
        pos = max(a, b)
    slow(pos, len(text))
    return Folded(out_text.getvalue(), out, src, end, linear)


def fold(text: str) -> str:
    return fold_map(text).text


#: `home: <name>`: one ASCII name (a letter or digit first; letters, digits, `.`, `_`, `-`, `'` and spaces inside, as
#: a Windows profile may hold), a horizontal space (a space, a tab, a Unicode space) around the colon; any other white
#: space there is refused. The name is checked as ASCII apart: IGNORECASE alone would
#: let `[A-Za-z]` take U+017F and U+212A.
_GAP = "[ \t   -   　]*"  # a horizontal space only: never a control or a separator
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
        text = raw.strip().lstrip("﻿​⁠").strip()  # no meaning at a start
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
        # a string keeps a joiner between its letters (an emoji needs one); one at either end belongs to no string, nor
        # does a variation selector or another default-ignorable character there (FAA-190 (94))
        edge = [i for i, c in enumerate(text) if not _ignorable_edge(c)]
        text = text[edge[0]:edge[-1] + 1] if edge else ""  # ends taken in one slice, spaces between marks too
        if bare and not bare.startswith("#") and INVISIBLE.search(text):
            # a text is compared without these, so the entry would never match (FAA-190 (90))
            raise CheckError("line %d of the owner's list holds an invisible character inside a string (a soft hyphen, a "
                             "zero-width space or a direction mark, which an editor may not show): delete it and write "
                             "the string again" % (len(entries) + 1))
        entries.append("" if not bare or bare.startswith("#") or len(text) < 3 else fold(text))
    return entries


def entry_spans(text: str, entries: List[str]) -> List[Tuple[int, int, int]]:
    """Where each string of the owner's list stands in a text, as (start, end, its line in the list)."""
    strings = [(n, e) for n, e in enumerate(entries, 1) if e and not e.startswith(HOME_ENTRY)]
    if not strings:
        return []
    folded = None if text.isascii() else fold_map(text)  # casefolding ASCII is lowering it: no map to build
    haystack = text.lower() if folded is None else folded.text
    spans = []
    for number, entry in strings:
        start = haystack.find(entry)
        while start != -1:  # back to the original characters: every one a matched character came from
            end = start + len(entry)
            spans.append((start, end, number) if folded is None else folded.span(start, end) + (number,))
            start = haystack.find(entry, start + 1)
    return spans
