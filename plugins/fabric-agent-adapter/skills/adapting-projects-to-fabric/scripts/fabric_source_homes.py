#!/usr/bin/env python3
"""How fabric_source_check.py reads a home the owner's list declares (`home: <name>`, FAA-188 part 1): the name in
every form the table names, its parts joined by any separator a tool or a language writes, and its spellings for the
masks of printed paths. Beside fabric_source_check.py, which imports it. Standard library only.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple

_SEP = r"(?:\\|/)+"  # one way to read a run: two alternatives that both take a `\\` backtrack exponentially

#: How a `home: <name>` line of the owner's list is kept among the entries: a character no line can hold.
HOME_ENTRY = "\0"


def _owner_homes(entries: List[str]) -> Set[str]:
    """The home names the owner's list declares (`home: <name>`), which are never neutral."""
    return {e[1:] for e in entries if e.startswith(HOME_ENTRY)}


_DASHED: Dict[str, Tuple["re.Pattern[str]", ...]] = {}


#: Where a declared home name stands in each form the table names: the slashed, drive, URL-encoded and dashed homes.
_DECLARED_SLASHED = (r"(?<![A-Za-z0-9_.-])(?:/var)?/home/", r"(?<![A-Za-z0-9_.-])/Users/",
                     r"(?<![A-Za-z0-9_.-])(?:/mnt)?/[A-Za-z]/Users/",
                     r"(?<![A-Za-z0-9_.-])(?i:[A-Za-z]:%sUsers%s)" % (_SEP, _SEP),
                     r"%2[Ff](?:Users|home)%2[Ff]", r"(?i:%5CUsers%5C)")
_DECLARED_DASHED = (r"(?:^|[^A-Za-z0-9-])(?:-Users|-home|-var-home|(?:-mnt)?-[A-Za-z]-Users)-",
                    r"(?<![A-Za-z0-9])(?i:[A-Za-z]--Users-)")


#: One separator between the parts of a declared home name, in any spelling a tool or a language writes: a space, `.`,
#: `_`, `-`, `+`, `'`, an escaped `\'` or `\u0027`, an HTML `&#39;` or `&#x27;`, or a percent-encoding of one of them.
_NAME_JOIN = r"(?:[ ._+'-]|\\'|\\x27|\\u0027|&#0?39;|&#[xX]27;|&apos;|%2[07BbDdEe]|%5[Ff])"


def _name_parts(name: str) -> List[str]:
    return [part for part in re.split(r"[ ._'-]+", name) if part]


def _spellings(found: Iterable[str], owner: Iterable[str]) -> Set[str]:
    """The names found, and every spelling of a declared home one of them spells (its parts joined by each separator
    a tool writes), so a printed path masks the other spellings of that home too."""
    names = set(found)
    for name in owner:
        parts = _name_parts(name)
        body = re.compile(r"(?i:%s)" % (_NAME_JOIN + "+").join(re.escape(part) for part in parts), re.ASCII)
        if parts and any(body.fullmatch(n) for n in names):
            names |= {name} | {sep.join(parts) for sep in (" ", ".", "_", "-", "+", "'", "%20", "%27")}
    return names


def _dashed_home(name: str) -> Tuple["re.Pattern[str]", ...]:
    """A declared home name in every form, read whole, its parts joined by any run of the separators a tool or a
    language writes (`_NAME_JOIN`: a space, `.`, `_`, `-`, `+`, `'` and their escapes and percent-encodings), since
    the generic forms end a name at a dash or a space, so `-Users-j-doe-proj` would read `j`. It ends only where a
    letter or digit would continue it: a `.` or `_` after it (an extension, a sentence's end) is read as the declared
    home, failing closed."""
    if name not in _DASHED:
        body = (_NAME_JOIN + "+").join(re.escape(part) for part in _name_parts(name)) or re.escape(name)
        whole = r"((?i:%s))(?![A-Za-z0-9])" % body
        _DASHED[name] = tuple(re.compile(prefix + whole, re.ASCII) for prefix in _DECLARED_SLASHED + _DECLARED_DASHED)
    return _DASHED[name]
