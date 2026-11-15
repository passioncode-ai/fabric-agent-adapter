#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""FAA-273 items 8, 10, 15: the env rule of 0.76.0 against fabric_secrets.secret_env_value on random keys and on the
folders of the machine it runs on. Prints counts only, never a path. Run from the repository root:

    python3 -I docs/reports/2026-11-15-faa-273-env-rule/measure.py
"""
import base64
import importlib.util
import os
import random
import re
import sys

KIT = "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, KIT)  # the kit's modules import their neighbours by name
_spec = importlib.util.spec_from_file_location("fabric_secrets", KIT + "/fabric_secrets.py")
s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s)


def old_rule(value):
    """0.76.0 to 0.91.2: path-aware (`secret_argument`) only for an anchored value with two separators and a lower-case
    part of three or more characters; any other value `secret_value`."""
    pieces = re.split(r"[\\/]", value)
    path = bool(re.match(r"(?:[/~.]|[A-Za-z]:[\\/])", value)) and len(pieces) >= 3 and any(
        re.fullmatch(r"[a-z][a-z0-9_-]{2,}", x) for x in pieces)
    return s.secret_argument(value) if path else s.secret_value(value)


new_rule = s.secret_env_value
r = random.Random(2026)
keys = [base64.b64encode(bytes(r.getrandbits(8) for _ in range(n))).decode() for n in (32, 48, 64) for _ in range(20000)]
slash = [k for k in keys if k.startswith("/")]
tails = ["/opt/xyz/" + k[:m] for k in keys[:20000] for m in (24, 32, 38)]
urlsafe = [base64.urlsafe_b64encode(bytes(r.getrandbits(8) for _ in range(n))).decode() for n in (32, 48) for _ in range(5000)]
paths = []
for root in [os.path.expanduser("~/Library/Application Support"), "/Applications", os.path.expanduser("~/DATA"), "/usr/local",
             "/opt/homebrew/Cellar", os.path.expanduser("~/.local/share")]:
    for here, dirs, _ in os.walk(root):
        if here[len(root):].count("/") >= 4:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git")]
        paths.append(here)
joined = [":".join(r.sample(paths, 3)) for _ in range(3000)] if len(paths) >= 3 else []
releases = (["/Users/example/Library/Application Support/ExampleAgent/Releases/2026-11-%02d" % d for d in range(1, 29)]
            + ["/Applications/%s/Contents/Resources/Releases/2026-11-07" % a for a in ("ExampleAgent", "Fabric", "Writer2")])
for name, corpus, want in (("random keys", keys, True), ("keys starting with /", slash, True),
                           ("a key as a path's last part", tails, True), ("url-safe keys", urlsafe, True),
                           ("this machine's folders", paths, False), ("colon-joined folders", joined, False),
                           ("item 8 release folders", releases, False)):
    print("%-30s %6d  old %6d  new %6d  (%s)" % (name, len(corpus), sum(map(old_rule, corpus)), sum(map(new_rule, corpus)),
                                                   "caught" if want else "refused"))
