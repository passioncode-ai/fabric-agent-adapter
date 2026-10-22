"""Windows, where the kit needs it (DEC-0032): named pipes that hold one copy, protecting a file to its owner, and
reading a file's ACL to refuse a token file others can read. On other systems the same names exist and do nothing
or answer "absent". Part of the service kit (FAA-65, layer L1)."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import (
    ServiceError,
    WINDOWS,
)


#: The trustees a token file may grant anything to besides the current user: LocalSystem and the
#: Administrators group — the same trust as root reading a 0600 file on POSIX.
WINDOWS_TRUSTED = ("S-1-5-18", "S-1-5-32-544")


def token_file_problem(path: Path, file: Dict[str, Any], user: str) -> Optional[str]:
    """windows_token_acl_problem as one sentence naming the file and the refusal, or None."""
    problem = windows_token_acl_problem(file, user)
    return None if problem is None else "Token file %s refused: %s." % (path, problem["message"])


SYSTEM_SID = "S-1-5-18"


ADMINISTRATORS_SID = "S-1-5-32-544"


#: A string SID: revision 1, an identifier authority and up to 15 sub-authorities of 32 bits each.
_SID_TEXT = re.compile(r"S-1-[0-9]{1,15}(?:-[0-9]{1,10}){0,15}", re.IGNORECASE | re.ASCII)


def _sid(value: Any) -> Optional[str]:
    """A readable SID in upper case (SIDs compare case-insensitively on their S), or None."""
    if not isinstance(value, str) or not _SID_TEXT.fullmatch(value):
        return None
    return value.upper() if all(int(part) <= 0xFFFFFFFF for part in value.split("-")[3:]) else None


def windows_token_acl_problem(file: Any, current_user_sid: Any) -> Optional[Dict[str, Any]]:
    """service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057, FAC-SEM-079) on what a reader has read:
    ``file`` is ``{isRegularFile, isReparsePoint, realPathInProfile, ownerSid, aces: [{type, sid, mask}]}``, the mask
    the ACE's unsigned 32-bit access mask. The first refusal ``{problem, at, sid?, message}``, or None when the file may
    be read: a regular file, not a reparse point, inside the profile; owned by the user, SYSTEM or Administrators; every
    allow ACE with a non-zero mask naming one of those three; deny ACEs ignored; any other ACE type refused; anything
    unreadable refused. The contract's ``windowsTokenAclProblem``; a refusal names the SID, never the contents."""
    def refuse(problem: str, at: str, message: str, sid: Optional[str] = None) -> Dict[str, Any]:
        out = {"problem": problem, "at": at, "message": message}
        if sid is not None:
            out["sid"] = sid
        return out
    user = _sid(current_user_sid)
    if user is None:
        return refuse("unreadable", "/currentUserSid", "the current user's SID is unreadable")
    if not isinstance(file, dict):
        return refuse("unreadable", "/file", "the token file's metadata is unreadable")
    for flag in ("isRegularFile", "isReparsePoint", "realPathInProfile"):
        if not isinstance(file.get(flag), bool):
            return refuse("unreadable", "/file/" + flag, flag + " is unreadable")
    if file["isReparsePoint"]:
        return refuse("reparse-point", "/file/isReparsePoint", "the token file is a reparse point (a symlink or a junction)")
    if not file["isRegularFile"]:
        return refuse("not-regular-file", "/file/isRegularFile", "the token file is not a regular file")
    if not file["realPathInProfile"]:
        return refuse("outside-profile", "/file/realPathInProfile", "the token file's real path lies outside the user's profile")
    trusted = {user, SYSTEM_SID, ADMINISTRATORS_SID}
    owner = _sid(file.get("ownerSid"))
    if owner is None:
        return refuse("unreadable", "/file/ownerSid", "the owner SID is unreadable")
    if owner not in trusted:
        return refuse("owner", "/file/ownerSid", "the token file is owned by %s, not by the current user, SYSTEM or Administrators" % owner, owner)
    aces = file.get("aces")
    if not isinstance(aces, list):
        return refuse("unreadable", "/file/aces", "the ACL is unreadable")
    for index, ace in enumerate(aces):
        at = "/file/aces/%d" % index
        if not isinstance(ace, dict):
            return refuse("unreadable", at, "ACE %d is unreadable" % index)
        if not isinstance(ace.get("type"), str):
            return refuse("unreadable", at + "/type", "ACE %d has an unreadable type" % index)
        trustee = _sid(ace.get("sid"))
        if trustee is None:
            return refuse("unreadable", at + "/sid", "ACE %d names an unreadable SID" % index)
        mask = ace.get("mask")
        if (not isinstance(mask, (int, float)) or isinstance(mask, bool) or (isinstance(mask, float) and not mask.is_integer())
                or not 0 <= mask <= 0xFFFFFFFF):
            return refuse("unreadable", at + "/mask", "ACE %d has an unreadable access mask" % index)
        if ace["type"] == "deny":
            continue
        if ace["type"] != "allow":
            return refuse("ace-type", at + "/type", "ACE %d for %s is of a type the rule does not read" % (index, trustee), trustee)
        if mask == 0:
            continue
        if trustee not in trusted:
            return refuse("ace-sid", at + "/sid", "the token file grants access to %s; only the current user, SYSTEM and Administrators may hold any" % trustee, trustee)
    return None


#: SDDL ACE types (MS-DTYP §2.5.1.1) as the rule's ACE type: allow and deny are read, every other type is refused.
_SDDL_ACE_TYPES = {"A": "allow", "D": "deny", "OA": "allow-object", "OD": "deny-object", "XA": "allow-callback",
                   "XD": "deny-callback", "ZA": "allow-object-callback"}


#: SDDL access-right aliases (MS-DTYP §2.5.1.1, "ace_rights") and their masks.
_SDDL_RIGHTS = {"GA": 0x10000000, "GR": 0x80000000, "GW": 0x40000000, "GX": 0x20000000, "RC": 0x20000, "SD": 0x10000,
                "WD": 0x40000, "WO": 0x80000, "RP": 0x10, "WP": 0x20, "CC": 0x1, "DC": 0x2, "LC": 0x4, "SW": 0x8,
                "LO": 0x80, "DT": 0x40, "CR": 0x100, "FA": 0x1F01FF, "FR": 0x120089, "FW": 0x120116, "FX": 0x1200A0,
                "KA": 0xF003F, "KR": 0x20019, "KX": 0x20019, "KW": 0x20006}


def _sddl_ace_strings(dacl: str) -> List[str]:
    """The top-level parenthesized ACE strings of an SDDL DACL; a callback ACE's conditional expression may nest."""
    aces, depth, start = [], 0, 0
    for index, char in enumerate(dacl):
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")" and depth:
            depth -= 1
            if depth == 0:
                aces.append(dacl[start:index])
    return aces


def _sddl_mask(rights: str) -> Optional[int]:
    """An SDDL rights field as the unsigned 32-bit mask, or None when it cannot be read."""
    if re.fullmatch(r"0[xX][0-9a-fA-F]{1,8}", rights):
        return int(rights, 16)
    if len(rights) % 2:
        return None
    mask = 0
    for i in range(0, len(rights), 2):
        if rights[i:i + 2] not in _SDDL_RIGHTS:
            return None
        mask |= _SDDL_RIGHTS[rights[i:i + 2]]
    return mask


def acl_from_sddl(sddl: str, canonical: Callable[[str], str] = lambda sid: sid) -> Tuple[str, List[Dict[str, Any]]]:
    """(owner SID, the ACEs that apply to the object itself as ``{type, sid, mask}``) from an SDDL owner-and-DACL
    string. ``canonical`` turns an SDDL alias (SY, BA, WD…) into its SID. A missing or NULL DACL grants everyone
    everything and is read as an allow ACE for Everyone (S-1-1-0); an inherit-only ACE (flag IO) applies to children
    only and is not read; an unreadable rights field gives mask None, which the rule refuses."""
    owner = sddl.split("O:", 1)[1].split("G:", 1)[0].split("D:", 1)[0] if "O:" in sddl else ""
    dacl = sddl.split("D:", 1)[1] if "D:" in sddl else ""
    owner_sid = canonical(owner) if owner else ""
    if not dacl or dacl.startswith("NO_ACCESS_CONTROL"):
        return owner_sid, [{"type": "allow", "sid": "S-1-1-0", "mask": 0x1F01FF}]
    aces = []
    for text in _sddl_ace_strings(dacl):
        fields = text.split(";", 6)
        if len(fields) < 6:  # unreadable: the rule refuses it
            aces.append({"type": None, "sid": None, "mask": None})
            continue
        kind, flags, rights, trustee = fields[0], fields[1], fields[2], fields[5]
        if "IO" in [flags[i:i + 2] for i in range(0, len(flags), 2)]:
            continue
        aces.append({"type": _SDDL_ACE_TYPES.get(kind, kind), "sid": canonical(trustee), "mask": _sddl_mask(rights)})
    return owner_sid, aces


if WINDOWS:  # pragma: no cover - exercised by the Windows CI job
    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PVOID = ctypes.c_void_p
    _SE_FILE_OBJECT, _OWNER_INFO, _DACL_INFO, _PROTECTED_DACL = 1, 0x1, 0x4, 0x80000000
    _REPARSE_POINT = 0x400
    _advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.POINTER(_PVOID)] * 5
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD] + [_PVOID] * 4
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        _PVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_PVOID), ctypes.POINTER(wintypes.ULONG)]
    _advapi32.GetSecurityDescriptorDacl.argtypes = [_PVOID, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(_PVOID),
                                                    ctypes.POINTER(wintypes.BOOL)]
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, _PVOID, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    _advapi32.ConvertSidToStringSidW.argtypes = [_PVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_PVOID)]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.LocalFree.argtypes = [_PVOID]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _CANONICAL: Dict[str, str] = {}

    def _win_error(what: str, code: Optional[int] = None) -> OSError:
        code = ctypes.get_last_error() if code is None else code
        return OSError(code, "%s: %s" % (what, ctypes.FormatError(code).strip()))

    def _sid_text(sid: Any) -> str:
        text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise _win_error("ConvertSidToStringSidW")
        try:
            return text.value
        finally:
            _kernel32.LocalFree(text)

    def _canonical_sid(trustee: str) -> str:
        """SDDL writes well-known accounts by alias (SY, BA, LA, OW); compare SIDs."""
        if trustee not in _CANONICAL:
            sid = _PVOID()
            if _advapi32.ConvertStringSidToSidW(trustee, ctypes.byref(sid)):
                try:
                    _CANONICAL[trustee] = _sid_text(sid)
                finally:
                    _kernel32.LocalFree(sid)
            else:
                _CANONICAL[trustee] = trustee
        return _CANONICAL[trustee]

    def windows_user_sid() -> str:
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token)):
            raise _win_error("OpenProcessToken")
        try:
            size = wintypes.DWORD()
            _advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not _advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                raise _win_error("GetTokenInformation")
            return _sid_text(ctypes.cast(buf, ctypes.POINTER(_PVOID))[0])
        finally:
            _kernel32.CloseHandle(token)

    def _sddl(path: Path) -> str:
        sd = _PVOID()
        refs = [_PVOID() for _ in range(4)]
        code = _advapi32.GetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _OWNER_INFO | _DACL_INFO,
                                               *[ctypes.byref(r) for r in refs], ctypes.byref(sd))
        if code:
            raise _win_error("GetNamedSecurityInfoW", code)
        try:
            text = wintypes.LPWSTR()
            if not _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    sd, 1, _OWNER_INFO | _DACL_INFO, ctypes.byref(text), None):
                raise _win_error("ConvertSecurityDescriptorToStringSecurityDescriptorW")
            try:
                return text.value or ""
            finally:
                _kernel32.LocalFree(text)
        finally:
            _kernel32.LocalFree(sd)

    def windows_acl(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
        """(owner SID, the ACEs on the object itself as ``{type, sid, mask}``), read from its SDDL (acl_from_sddl)."""
        return acl_from_sddl(_sddl(path), _canonical_sid)

    def _win_protect(path: Path, folder: bool) -> None:
        """A protected list (inheritance off): this user, SYSTEM, Administrators, full control;
        inherited by what a folder holds."""
        inherit = "OICI" if folder else ""
        sddl = "D:P" + "".join("(A;%s;FA;;;%s)" % (inherit, who) for who in (windows_user_sid(), "SY", "BA"))
        sd = _PVOID()
        if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
            raise _win_error("ConvertStringSecurityDescriptorToSecurityDescriptorW")
        try:
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), _PVOID()
            if not _advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
                raise _win_error("GetSecurityDescriptorDacl")
            code = _advapi32.SetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _DACL_INFO | _PROTECTED_DACL,
                                                   None, None, dacl, None)
            if code:
                raise _win_error("SetNamedSecurityInfoW", code)
        finally:
            _kernel32.LocalFree(sd)

    _kernel32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR] + [wintypes.DWORD] * 6 + [_PVOID]
    _kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    _INVALID_HANDLE = wintypes.HANDLE(-1).value

    def _create_first_pipe(name: str) -> Any:
        """The pipe's first instance, or None when another process holds it (ERROR_ACCESS_DENIED)."""
        # PIPE_ACCESS_INBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE; PIPE_REJECT_REMOTE_CLIENTS; unlimited instances,
        # as libuv creates them: then a second first-instance attempt, ours or the Node kit's, is refused with
        # ERROR_ACCESS_DENIED (Node: EADDRINUSE), never ERROR_PIPE_BUSY.
        handle = _kernel32.CreateNamedPipeW(name, 0x1 | 0x00080000, 0x8, 255, 0, 0, 0, None)
        if handle == _INVALID_HANDLE:
            code = ctypes.get_last_error()
            if code in (5, 231):  # ERROR_ACCESS_DENIED, ERROR_PIPE_BUSY: another process holds it
                return None
            raise _win_error("CreateNamedPipeW", code)
        return handle

    def _close_handle(handle: Any) -> None:
        _kernel32.CloseHandle(handle)

    _kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    def _pipe_exists(name: str) -> bool:
        """Some process holds the pipe: waiting for it does not fail with ERROR_FILE_NOT_FOUND. Nothing connects."""
        if _kernel32.WaitNamedPipeW(name, 1):
            return True
        return ctypes.get_last_error() != 2

    def _win_token_problem(path: Path, info: os.stat_result) -> Optional[str]:
        profile = os.path.normcase(os.path.realpath(os.environ.get("USERPROFILE") or str(Path.home())))
        real = os.path.normcase(os.path.realpath(str(path)))
        try:
            inside = os.path.commonpath([profile, real]) == profile
        except ValueError:  # another drive
            inside = False
        owner, aces = windows_acl(path)
        file = {"isRegularFile": stat.S_ISREG(info.st_mode), "isReparsePoint": bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT),
                "realPathInProfile": inside, "ownerSid": owner, "aces": aces}
        return token_file_problem(path, file, windows_user_sid())
else:
    def _create_first_pipe(name: str) -> Any:  # noqa: ARG001
        raise ServiceError("named pipes exist only on Windows")

    def _close_handle(handle: Any) -> None:  # noqa: ARG001
        raise ServiceError("handles exist only on Windows")

    def _pipe_exists(name: str) -> bool:  # noqa: ARG001
        raise ServiceError("named pipes exist only on Windows")

    def _win_protect(path: Path, folder: bool) -> None:  # noqa: ARG001 - POSIX uses modes
        raise ServiceError("Windows ACLs exist only on Windows")

    def _win_token_problem(path: Path, info: os.stat_result) -> Optional[str]:  # noqa: ARG001
        raise ServiceError("Windows token rules apply only on Windows")
