"""Who may call a service: the descriptor token, the network guard,
the operator's one-time login and its session, remote placement (DEC-0019) and the feed client's token header.
Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import (
    PROTOCOL,
    ServiceError,
    WINDOWS,
    now_iso,
)
from fabric_platform import (
    _win_token_problem,
)
from fabric_paths import (
    atomic_write,
    ensure_private_dir,
    services_dir,
)
from fabric_descriptor import (
    validate_descriptor,
    write_descriptor,
)


LOGIN_CODE_TTL_SECONDS = 120


# DEC-0039 (service.md "The session's lifetime"): the longest a service may keep an operator session.
OPERATOR_SESSION_IDLE_SECONDS = 12 * 60 * 60


OPERATOR_SESSION_MAX_SECONDS = 7 * 24 * 60 * 60


_CODE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


def ensure_token(path: Path) -> str:
    """Create the service token once (0600, owner only); never rotate silently."""
    path = Path(path)
    if path.exists():
        return read_token(path)
    ensure_private_dir(path.parent)
    token = secrets.token_urlsafe(32)
    atomic_write(path, token.encode(), 0o600)
    return token


def read_token(path: Path) -> str:
    """Refuse a symlink, a file owned by someone else, or one others can read.

    On Windows the rule is service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057):
    windows_token_acl_problem over the file's flags, owner and ACEs; a refusal names the SID,
    never the contents."""
    path = Path(path)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise ServiceError("Token file %s is a symlink; refusing it." % path)
    if WINDOWS:
        problem = _win_token_problem(path, info)
        if problem:
            raise ServiceError(problem)
    else:
        if info.st_uid != os.getuid():
            raise ServiceError("Token file %s belongs to another user." % path)
        if info.st_mode & 0o077:
            raise ServiceError("Token file %s is readable by others; set mode 0600." % path)
    token = path.read_text().strip()
    if len(token) < 16:
        raise ServiceError("Token file %s holds no usable token." % path)
    return token


def token_matches(presented: Optional[str], token: str, scheme: str = "Bearer") -> bool:
    if not presented:
        return False
    value = presented
    if scheme == "Bearer":
        if not presented.startswith("Bearer "):
            return False
        value = presented[len("Bearer "):]
    return hmac.compare_digest(value.strip().encode(), token.encode())


def check_request(port: int, host: Optional[str], origin: Optional[str] = None,
                  sec_fetch_site: Optional[str] = None) -> Optional[str]:
    """Return why a request must be refused (403), or None when it may proceed."""
    allowed_hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port, "[::1]:%d" % port}
    if host not in allowed_hosts:
        return "Host %r is not this service." % host
    if origin is not None and origin not in {"http://" + h for h in allowed_hosts}:
        return "Origin %r is not this service." % origin
    if sec_fetch_site == "cross-site":
        return "Cross-site requests are refused."
    return None


def token_header(auth: Any, token: str) -> Tuple[str, str]:
    """The one header a client sends the service token in, as the descriptor's ``auth`` declares it: ``header``
    defaults to Authorization and ``scheme`` to Bearer; ``none`` carries the raw token. Never assume
    ``Authorization: Bearer`` (a feed client that did was refused on every poll and dropped every notify event)."""
    declared = auth if isinstance(auth, dict) else {}
    name = declared.get("header") if isinstance(declared.get("header"), str) else "Authorization"
    scheme = declared.get("scheme") if isinstance(declared.get("scheme"), str) else "Bearer"
    return name, token if scheme == "none" else "Bearer " + token


class LoginCodes:
    """Single-use login codes (<=120 s), recorded as used BEFORE they are honoured, and operator
    sessions with the DEC-0039 lifetime: a session ends 12 h after its last use, 7 days after the code
    was redeemed, on logout, and when the descriptor token rotates. The server enforces all four: the
    cookie carries a signed claim (session id, sign-in time, token revision) and the code store keeps a
    record per session (last use, logout). Rotating the key with revoke_all() ends every session."""

    def __init__(self, state_dir: Optional[Path], ttl: int = LOGIN_CODE_TTL_SECONDS, *,
                 store: Optional["MemoryCodeStore"] = None, key: Optional[bytes] = None,
                 token: "Optional[str | Callable[[], str]]" = None,
                 idle_seconds: int = OPERATOR_SESSION_IDLE_SECONDS,
                 max_seconds: int = OPERATOR_SESSION_MAX_SECONDS,
                 clock: Callable[[], float] = time.time):
        # A local service keeps codes, sessions and the key in files. An online one (DEC-0019) usually has
        # no durable disk: pass state_dir=None with store=MemoryCodeStore() and key= bytes from a platform
        # secret. A memory store forgets codes AND sessions on a restart, so a deploy signs the operator
        # out (the host signs in again on the page's 401); pass a durable store to keep sessions.
        # token= is the descriptor token, or a callable returning the current one: a session begun under
        # one token is refused once it rotates. A service MAY shorten either bound, never lengthen one.
        self.ttl = min(ttl, LOGIN_CODE_TTL_SECONDS)
        self.idle_seconds = _session_bound(idle_seconds, OPERATOR_SESSION_IDLE_SECONDS)
        self.max_seconds = _session_bound(max_seconds, OPERATOR_SESSION_MAX_SECONDS)
        # One lock around every load-modify-save, so a concurrent refresh never saves over a logout or a
        # burned code (a threading server checks sessions on several threads; the instance lock keeps
        # other processes out of the state directory).
        self._lock = threading.RLock()
        self._store = store
        self._fixed_key = key
        self._token = token
        self._clock = clock
        if state_dir is not None:
            self.dir = ensure_private_dir(Path(state_dir))
            self._key_path = self.dir / "session.key"
            self._codes_path = self.dir / "login-codes.json"
        elif store is None or key is None:
            raise ServiceError("LoginCodes without a state directory needs store= and key=.")
        if key is not None and len(key) < 32:
            raise ServiceError("the session key must be at least 32 bytes.")

    def _key(self) -> bytes:
        if self._fixed_key is not None:
            return bytes(self._fixed_key)
        if not self._key_path.exists():
            atomic_write(self._key_path, secrets.token_bytes(32), 0o600)
        return self._key_path.read_bytes()

    def _load(self) -> Dict[str, Any]:
        if self._store is not None:
            return self._store.load()
        try:
            return json.loads(self._codes_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, codes: Dict[str, Any]) -> None:
        horizon = self._clock() - 3600
        codes = {k: v for k, v in codes.items() if v.get("expires", 0) > horizon}
        if self._store is not None:
            self._store.save(codes)
            return
        atomic_write(self._codes_path, json.dumps(codes).encode(), 0o600)

    def issue(self) -> Dict[str, str]:
        with self._lock:
            code = secrets.token_urlsafe(24)
            expires = self._clock() + self.ttl
            codes = self._load()
            codes[hashlib.sha256(code.encode()).hexdigest()] = {"expires": expires, "used": False}
            self._save(codes)
            at = _dt.datetime.fromtimestamp(expires, _dt.timezone.utc).replace(microsecond=0)
            return {"url": "/fabric/v1/login?code=" + code, "expiresAt": at.isoformat().replace("+00:00", "Z")}

    def redeem(self, code: Optional[str]) -> Optional[str]:
        """Return a session cookie value, or None. The code is burned even when it has expired."""
        with self._lock:
            if not code or not _CODE.match(code):
                return None
            digest = hashlib.sha256(code.encode()).hexdigest()
            codes = self._load()
            entry = codes.get(digest)
            if not entry or entry.get("used"):
                return None
            entry["used"] = True
            self._save(codes)
            now = self._clock()
            if entry.get("expires", 0) < now:
                return None
            session_id = secrets.token_urlsafe(18)
            signed_in = int(now)
            codes[self._record_key(session_id)] = {"expires": signed_in + self.max_seconds,
                                                   "signedInAt": signed_in, "lastUsedAt": now}
            self._save(codes)
            claim = "v2.%s.%d.%s" % (session_id, signed_in, self._token_revision())
            return claim + "." + self._mac(claim)

    def session_valid(self, cookie_value: Optional[str]) -> bool:
        """True while the session is live; a use within the bounds refreshes the idle bound."""
        with self._lock:
            parsed = self._parse(cookie_value)
            if parsed is None:
                return False
            session_id, signed_in = parsed
            now = self._clock()
            if now >= signed_in + self.max_seconds:
                return False
            codes = self._load()
            record = codes.get(self._record_key(session_id))
            if not record or record.get("signedInAt") != signed_in or record.get("loggedOutAt") is not None:
                return False
            last = float(record.get("lastUsedAt", 0))
            if now >= last + self.idle_seconds:
                return False
            if now - last >= min(60, max(1, self.idle_seconds // 10)):
                record["lastUsedAt"] = now
                self._save(codes)
            return True

    def logout(self, cookie_value: Optional[str]) -> bool:
        """End this session on the server: every copy of the cookie is refused from now on. Clear the
        browser's copy with expired_session_cookie_header(). False when there was no live record."""
        with self._lock:
            parsed = self._parse(cookie_value)
            if parsed is None:
                return False
            codes = self._load()
            record = codes.get(self._record_key(parsed[0]))
            if not record or record.get("signedInAt") != parsed[1] or record.get("loggedOutAt") is not None:
                return False
            record["loggedOutAt"] = self._clock()
            self._save(codes)
            return True

    def _parse(self, cookie_value: Optional[str]) -> Optional[Tuple[str, int]]:
        """The signed claim of a cookie under the current key and token, or None."""
        if not isinstance(cookie_value, str) or not cookie_value.isascii():
            return None
        parts = cookie_value.split(".")
        if len(parts) != 5 or parts[0] != "v2" or not parts[1] or not parts[2].isdigit():
            return None
        claim, mac = ".".join(parts[:4]), parts[4]
        if not hmac.compare_digest(mac, self._mac(claim)):
            return None
        if not hmac.compare_digest(parts[3], self._token_revision()):
            return None
        return parts[1], int(parts[2])

    def _mac(self, claim: str) -> str:
        return hmac.new(self._key(), claim.encode(), hashlib.sha256).hexdigest()

    def _token_revision(self) -> str:
        token = self._token() if callable(self._token) else self._token
        if not token:
            return "-"
        return hmac.new(self._key(), b"token-revision\0" + token.encode(), hashlib.sha256).hexdigest()[:16]

    @staticmethod
    def _record_key(session_id: str) -> str:
        return "s:" + hashlib.sha256(session_id.encode()).hexdigest()

    def revoke_all(self) -> None:
        if self._fixed_key is not None:
            raise ServiceError("a platform-held session key is rotated on the platform, not here.")
        atomic_write(self._key_path, secrets.token_bytes(32), 0o600)


def _session_bound(value: Any, longest: int) -> int:
    """A session bound in seconds: a finite number, never longer than the contract's (DEC-0039)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise ServiceError("a session bound must be a finite number of seconds.")
    return min(int(value), longest)


class MemoryCodeStore:
    """DEC-0019: a login-code store held in memory — for an online service with no durable disk."""

    def __init__(self) -> None:
        self._codes: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._codes))

    def save(self, codes: Dict[str, Any]) -> None:
        self._codes = json.loads(json.dumps(codes))


SESSION_COOKIE = "fabric_session"


REMOTE_SESSION_COOKIE = "__Host-fabric_session"


def session_cookie_header(value: str, max_age: int = OPERATOR_SESSION_MAX_SECONDS) -> str:
    """The cookie lives no longer than the absolute bound (DEC-0039); the server ends it sooner."""
    return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (SESSION_COOKIE, value, max_age)


def remote_session_cookie_header(value: str, max_age: int = OPERATOR_SESSION_MAX_SECONDS) -> str:
    """DEC-0019: the remote cookie — __Host- name, Secure, no Domain, Path=/."""
    return "%s=%s; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=%d" % (REMOTE_SESSION_COOKIE, value, max_age)


def expired_session_cookie_header(remote: bool = False) -> str:
    """The header that clears the browser's session cookie, sent with a logout."""
    return (remote_session_cookie_header if remote else session_cookie_header)("", 0)


def check_remote_request(origin: str, host: Optional[str], request_origin: Optional[str] = None,
                         sec_fetch_site: Optional[str] = None, forwarded_proto: Optional[str] = None) -> Optional[str]:
    """DEC-0019: the request guard of an online service; returns the refusal sentence or None.
    ``forwarded_proto`` is the platform-set scheme where TLS ends before the process; pass None
    when the process terminates TLS itself."""
    own = urllib.parse.urlsplit(origin)
    own_host = own.netloc.lower()
    if str(host or "").lower() != own_host:
        return "Host %s is not this service." % host
    if forwarded_proto is not None and str(forwarded_proto).split(",")[0].strip() != "https":
        return "This service answers over https only."
    if request_origin is not None and request_origin != "%s://%s" % (own.scheme, own_host):
        return "Origin %s is not this service." % request_origin
    if sec_fetch_site == "cross-site":
        return "Cross-site requests are refused."
    return None


def well_known_allowed(placement: str, authorization: Optional[str], token: str, scheme: str = "Bearer") -> bool:
    """DEC-0019: a local service answers anyone (the loopback guard already ran); a remote one only
    the bearer of the service token. False is a 401 with an EMPTY body."""
    return placement != "remote" or token_matches(authorization, token, scheme)


def remote_token_file(service_id: str, instance: str = "default", directory: Optional[Path] = None) -> Path:
    return (directory or services_dir()).parent / "tokens" / ("%s.%s.token" % (service_id, instance))


def register_remote(*, service_id: str, name: str, origin: str, token: str, instance: str = "default",
                    summary: Optional[str] = None, doctor: Optional[List[str]] = None,
                    directory: Optional[Path] = None, installed_by: Any = None,
                    runner: Optional[Dict[str, str]] = None, peer: Optional[Dict[str, Any]] = None) -> Path:
    """DEC-0019, installer side: register an online service on THIS computer — the token file
    (0600, never printed) and the descriptor. The same token is set on the platform as a secret.

    DEC-0061: ``installed_by`` defaults to ``{"by": "person", "role": "operator", "tool": "fabric-service
    register-remote"}`` (a person runs this); pass ``role: "administrator"`` for an organization's administrator, or a
    string as before. ``runner`` (``{kind?, credentialKind}``) says how its model calls sign in, as a kind and never a
    credential; ``peer`` (``{endpoint, custody, residency, maxDataClass}``) offers it to others and needs ``runner``."""
    if not token or len(token.strip()) < 16:
        raise ServiceError("the service token must be at least 16 characters.")
    root = directory or services_dir()
    token_file = remote_token_file(service_id, instance, root)
    descriptor: Dict[str, Any] = {"protocol": PROTOCOL, "id": service_id, "instance": instance, "name": name,
                                  "placement": "remote", "origin": origin, "auth": {"tokenFile": str(token_file)},
                                  "lifecycle": {"manager": "none"}, "installedAt": now_iso(),
                                  "installedBy": installed_by if installed_by is not None else
                                  {"by": "person", "role": "operator", "tool": "fabric-service register-remote"}}
    if summary:
        descriptor["summary"] = summary
    if runner is not None:
        descriptor["runner"] = dict(runner)
    if peer is not None:
        descriptor["peer"] = dict(peer)
    if doctor:
        descriptor["commands"] = {"doctor": list(doctor)}
    problems = validate_descriptor(descriptor)
    if problems:
        raise ServiceError("Descriptor is invalid: %s." % "; ".join(problems))
    ensure_private_dir(token_file.parent)
    atomic_write(token_file, token.strip().encode(), 0o600)
    return write_descriptor(descriptor, root)


def cookie_value(cookie_header: Optional[str], name: str = SESSION_COOKIE) -> Optional[str]:
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None
