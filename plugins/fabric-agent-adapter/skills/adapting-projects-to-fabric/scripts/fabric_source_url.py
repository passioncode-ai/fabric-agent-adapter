#!/usr/bin/env python3
"""The URL constants of the contract's source tree check (`src/source-rules.ts`, DEC-0176) and how a URL's user and
host are split, for fabric_source_check.py and its port fabric_source_tree.py. Standard library only."""
from __future__ import annotations

import re
from typing import Tuple

#: The contract's DEC-0176 constants, each written as the vectors carry it but `$` read as `\Z` (and `.` as JavaScript's,
#: no line terminator), flag `i` with re.ASCII: test_source_tree holds them equal.
PASSWORD_NAME = re.compile(r"(?:^|[_.-])(?:password|passwd)\Z", re.IGNORECASE | re.ASCII)
URL_BEARER_VALUE = re.compile(r"^bearer[ \t]+(?=[A-Za-z0-9._~+/-]*\d)[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE | re.ASCII)
_PLACEHOLDER_UPPER = "[A-Z]+[0-9]*(?:_+(?:[A-Z]+[0-9]*|[0-9]+))*"
_PLACEHOLDER_LOWER = "[a-z]+[0-9]*(?:[_.-]+(?:[a-z]+[0-9]*|[0-9]+))*"
_PLACEHOLDER_CAMEL = "[a-z]+[0-9]*(?:[A-Z][a-z]*[0-9]*)+"
PLACEHOLDER_SOURCE = (r"^(?=.{2,72}$)(?:\$\{_?(?:%(u)s|%(l)s|%(c)s)\}?|\$_?%(u)s|\{\{(?:\.?_?(?:%(u)s|%(l)s|%(c)s)|"
                      r"(?:\.[A-Za-z][a-z]*[0-9]*)+)\}{0,2}|\{_?(?:%(u)s|%(l)s)\}?|%%\(_?(?:%(u)s|%(l)s)\)s)$"
                      % {"u": _PLACEHOLDER_UPPER, "l": _PLACEHOLDER_LOWER, "c": _PLACEHOLDER_CAMEL})
PLACEHOLDER = re.compile(PLACEHOLDER_SOURCE.replace(".{2,72}$", "[^\n\r\u2028\u2029]{2,72}\\Z").replace(")$", ")\\Z"))
DOCUMENTATION_HOST = re.compile(r"^(?:(?:[a-z0-9-]+\.)*example\.(?:com|net|org)|(?:[a-z0-9-]+\.)+(?:example|invalid))\Z")
#: A Latin letter or an ASCII digit: a key that follows one starts no word (DEC-0176; any script's letter did before).
LETTER_OR_DIGIT = re.compile("^[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\u1E00-\u1EFF]\\Z")
GENERATED_LENGTH = 24

def _url_user_host(url: str) -> Tuple[str, str]:
    """A URL's user (before the first `:` of its user information) and its host (lower case, no port), as the
    contract's urlParts splits the authority (url_parts' rule: a special scheme's authority after every slash or
    backslash, another's only after `//`, `file` none; the user information ends at the authority's last `@`)."""
    scheme, _, rest = url.partition(":")
    rest = rest.partition("#")[0].partition("?")[0]
    lowered = scheme.lower()
    if lowered in ("ftp", "http", "https", "ws", "wss"):  # the special schemes (the contract's SPECIAL_SCHEMES)
        authority = rest.replace("\\", "/").lstrip("/").partition("/")[0]
    elif lowered != "file" and rest.startswith("//"):
        authority = rest[2:].partition("/")[0]
    else:
        authority = ""
    userinfo, at, host = authority.rpartition("@")
    if not at:
        userinfo, host = "", authority
    return userinfo.partition(":")[0], re.sub(r":[0-9]*$", "", host).lower()
