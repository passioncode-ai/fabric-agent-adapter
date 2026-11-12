"""How fabric_source_check.py restarts itself in Python's UTF-8 mode under a locale whose file-system encoding is not
UTF-8, and keeps the console's encoding and the interpreter's own options across the restart. Standard library only."""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional


def _utf8_restart(encoding: str, utf8_mode: int, executable: str, argv: List[str]) -> Optional[List[bytes]]:
    """The command that restarts the check in Python's UTF-8 mode, or None when it needs none. Under a locale whose
    file-system encoding is not UTF-8 (ISO-8859-1, KOI8-R, a C locale with UTF-8 mode off), a name, an argument and a
    file's text would each be read in its own encoding; in UTF-8 mode all three are, and a byte that is not UTF-8 stays
    that byte. Windows names are UTF-16 and need none. The arguments go back as the bytes they came in. An empty list:
    a restart is needed and no interpreter is known (the caller exits 2 rather than read in two encodings)."""
    if os.name == "nt" or utf8_mode or encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        return None
    if not executable:
        return []
    return [os.fsencode(executable), b"-X", b"utf8"] + [os.fsencode(a) for a in argv]


def _interpreter() -> str:
    """The running interpreter: Linux's `/proc/self/exe`, which no PATH or working folder can stand in for (Python 3.9
    may take a `./python3` of the working folder as sys.executable), else sys.executable, which may be empty."""
    try:
        return os.readlink("/proc/self/exe")
    except (OSError, AttributeError):
        return sys.executable or ""


def _interpreter_flags(flags: object, xoptions: Dict[str, object]) -> List[str]:
    """The interpreter's own options, rebuilt where sys.orig_argv is missing (Python 3.9), so a restart keeps `-I`."""
    out: List[str] = []
    if getattr(flags, "isolated", 0):
        out.append("-I")
    else:
        out += ["-E"] * bool(getattr(flags, "ignore_environment", 0)) + ["-s"] * bool(getattr(flags, "no_user_site", 0))
    out += ["-S"] * bool(getattr(flags, "no_site", 0)) + ["-B"] * bool(getattr(flags, "dont_write_bytecode", 0))
    if getattr(flags, "optimize", 0):
        out.append("-" + "O" * int(getattr(flags, "optimize")))
    for key, value in xoptions.items():
        if key not in ("utf8", "fabric_console"):
            out += ["-X", key if value is True else "%s=%s" % (key, value)]
    return out


def _keep_console(xoptions: Dict[str, object]) -> None:
    """After a restart, write the console's own encoding again (the parent named it in `-X fabric_console=`)."""
    console = xoptions.get("fabric_console")
    if isinstance(console, str):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding=console, errors="backslashreplace")  # type: ignore[union-attr]
            except (AttributeError, LookupError, ValueError):
                pass
