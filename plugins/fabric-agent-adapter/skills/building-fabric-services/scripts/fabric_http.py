"""An outbound HTTP client for a service: one deadline across every attempt, bounded retries with jittered backoff,
`Retry-After` honoured up to a cap, a response size cap, and no secret in an error.

    response = fabric_http.request("GET", "https://api.example/v1/items", headers={"Authorization": ...},
                                   deadline_s=20, retries=2)
    response.status, response.headers["content-type"], response.json()

Rules (FAA-65 REQ-06):

- **What is retried.** A status in `RETRY_STATUSES` (408, 425, 429, 500, 502, 503, 504) or a connection error,
  at most `retries` times. A request is retried only when repeating it is safe: an idempotent method (`GET`, `HEAD`,
  `OPTIONS`, `PUT`, `DELETE`) or a request that carries an `Idempotency-Key` header. Any other request is retried only
  on 429, which says the server refused it before doing anything. Every other status is answered as it came.
- **When.** The wait before attempt *n* (from 0) is `min(max_backoff_s, backoff_s * 2**n) * (0.5 + random())`; a
  `Retry-After` the server sent (seconds or an HTTP date) replaces it, up to `max_retry_after_s`. A wait that would
  pass the deadline is not taken: the last answer or error stands.
- **The deadline** covers every attempt and every wait: each attempt gets what is left of it.
- **The size cap.** A body longer than `max_bytes` is an error, read no further than one byte past the cap.
- **Secrets.** A plain `http://` URL is refused unless the host is loopback or `insecure=True`: a bearer token never
  crosses a network in clear. An error names the method and the URL without its userinfo, query and fragment
  (`redact_url`); it never carries a request header or a request body.

The transport is injected in tests: `transport(method, url, headers, body, timeout_s, max_bytes)` returns
`(status, headers, body_bytes)` or raises `OSError` (a connection error, `TimeoutError` included) or `HttpError`.
Standard library only. Part of the service kit (FAA-65, layer L4).
"""
from __future__ import annotations

import datetime as _dt
import http.client
import ipaddress
import json
import re
import socket
import random as _random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_jsvalue import json_stringify  # noqa: E402 - beside this file

RETRY_STATUSES = (408, 425, 429, 500, 502, 503, 504)
IDEMPOTENT_METHODS = ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
_TOKEN = frozenset("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")

Transport = Callable[[str, str, Dict[str, str], Optional[bytes], float, int], Tuple[int, Dict[str, str], bytes]]


class HttpError(Exception):
    """A request that did not get an answer it could use. `status` is None for a connection error, a timeout, a
    refused URL or a body over the cap; `url` is redacted; `body` holds at most 2048 bytes of an answer's body."""

    def __init__(self, message: str, *, status: Optional[int] = None, url: str = "", attempts: int = 0,
                 retry_after_s: Optional[float] = None, body: bytes = b"", kind: str = "http"):
        super().__init__(message)
        self.status = status
        self.url = url
        self.attempts = attempts
        self.retry_after_s = retry_after_s
        self.body = bytes(body[:2048])
        self.kind = kind  # http (an answer), connection, timeout, too-large, refused


class Response:
    """An answer: `status`, `headers` (names lower-cased), `body` (bytes), `attempts`, `url` (redacted)."""

    def __init__(self, status: int, headers: Mapping[str, str], body: bytes, *, attempts: int = 1, url: str = ""):
        self.status = status
        self.headers = {str(k).lower(): str(v) for k, v in headers.items()}
        self.body = body
        self.attempts = attempts
        self.url = url

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        """The body as JSON, read as `JSON.parse` reads it: a UTF-8 byte order mark skipped, `NaN` and `Infinity`
        refused; anything unreadable (nesting too deep included) is a ValueError."""
        def refuse(token: str) -> Any:
            raise ValueError("%s is not JSON" % token)
        try:
            return json.loads(self.body.decode("utf-8-sig"), parse_constant=refuse)
        except RecursionError:
            raise ValueError("the JSON is nested too deep")


_SURROGATE = re.compile("[\ud800-\udfff]")


def utf8(text: str) -> bytes:
    """Text as UTF-8 the way `TextEncoder` writes it: a lone surrogate becomes U+FFFD instead of an error."""
    return _SURROGATE.sub("\ufffd", text).encode("utf-8")


def json_bytes(value: Any) -> bytes:
    """Compact JSON byte for byte as `JSON.stringify` writes it (numbers, key order, a lone surrogate escaped as
    `\\uXXXX`), in UTF-8; NaN or Infinity refused (`ValueError`) rather than written as null, and a value JSON has no
    form for refused (`TypeError`)."""
    json.dumps(value, allow_nan=False)  # raises on NaN, Infinity and types JSON cannot hold
    return json_stringify(value).encode("utf-8")


def redact_url(url: str) -> str:
    """The URL as it may appear in an error or a log line: scheme, host, port and path; no userinfo, query or
    fragment, which is where keys and tokens ride."""
    url = str(url)
    scheme, colon, rest = url.partition(":")
    if colon and scheme.lower() in ("http", "https", "ws", "wss", "ftp"):
        # A special scheme as WHATWG reads it: the authority starts after every slash or backslash that follows the
        # colon, and a backslash before the query reads as a slash, so `https:u:pw@h` loses its password too (0.56.0
        # seam r9; the Node twin reads it through `new URL`).
        cut = min([at for at in (rest.find("?"), rest.find("#")) if at >= 0] or [len(rest)])
        url = scheme + "://" + (rest[:cut].replace("\\", "/") + rest[cut:]).lstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    if parts.scheme and parts.scheme.lower() not in ("http", "https"):
        # Only http and https are sent; any other scheme (a misspelled `htps:` included) keeps no more than its name,
        # since its user information may sit anywhere in the rest (0.56.0 product r10).
        return parts.scheme.lower() + ":<redacted>"
    host = parts.hostname or ""
    if ":" in host:
        host = "[%s]" % host
    try:
        port = parts.port
    except ValueError:
        port = None
    if port == {"http": 80, "https": 443}.get(parts.scheme.lower()):
        port = None  # as a WHATWG URL writes it, so both kits print one URL the same way
    netloc = host.lower() + (":%d" % port if port is not None else "")
    path = parts.path or ("/" if parts.scheme.lower() in ("http", "https") else "")
    return urllib.parse.urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def _is_loopback(host: str) -> bool:
    """Loopback as a WHATWG URL parser leaves the host: one trailing dot dropped from an IPv4 address, no whitespace,
    and an IPv4-mapped IPv6 address not counted (Node writes it in hex and the Node twin refuses it)."""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if not host or any(c.isspace() for c in host):
        return False
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback and not getattr(address, "ipv4_mapped", None)
    except ValueError:
        pass
    host = host[:-1] if host.endswith(".") else host
    try:  # the short IPv4 forms a WHATWG URL also reads (127.1, 2130706433, 0x7f.1)
        return socket.inet_aton(host)[0] == 127
    except (OSError, ValueError):
        return False


def check_url(url: str, *, insecure: bool = False) -> None:
    """Refuse what this client never sends: a scheme other than http or https, no host, credentials in the URL, or
    plain http to a host that is not loopback (unless `insecure`)."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises on a bad port
    except (ValueError, TypeError):
        raise HttpError("the URL does not parse", url=redact_url(url), kind="refused")
    if parts.scheme not in ("http", "https") or not host:
        raise HttpError("only http and https URLs with a host are sent", url=redact_url(url), kind="refused")
    if parts.username is not None or parts.password is not None:
        raise HttpError("credentials in a URL are refused: send them in a header", url=redact_url(url), kind="refused")
    if parts.scheme == "http" and not insecure and not _is_loopback(host):
        raise HttpError("plain http to a host that is not loopback is refused (insecure=True to allow)",
                        url=redact_url(url), kind="refused")


_IMF_FIXDATE = re.compile(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d\d) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
                          r"(\d{4}) (\d\d):(\d\d):(\d\d) GMT", re.ASCII)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def retry_after_s(value: Optional[str], *, now: Optional[float] = None) -> Optional[float]:
    """Seconds a `Retry-After` header asks for (RFC 9110 10.2.3): a non-negative integer, or an IMF-fixdate
    (`Sun, 06 Nov 1994 08:49:37 GMT`) read as the time from `now` (epoch seconds), never below 0. None when absent or
    in any other form; the obsolete date forms are not read."""
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"[0-9]{1,10}", text):
        return float(int(text))
    m = _IMF_FIXDATE.fullmatch(text)
    if not m:
        return None
    day, month, year, hh, mm, ss = int(m[2]), _MONTHS.index(m[3]) + 1, int(m[4]), int(m[5]), int(m[6]), int(m[7])
    if hh > 23 or mm > 59 or ss > 60 or year < 1000:  # a year before 1000 is no HTTP date (and Date.UTC maps 0-99)
        return None
    try:
        when = _dt.datetime(year, month, day, hh, mm, min(ss, 59), tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:  # a day the month does not have
        return None
    return float(max(0.0, when - (time.time() if now is None else now)))


def backoff_s(attempt: int, *, base_s: float, max_s: float, rand: float) -> float:
    """The jittered wait before retry `attempt` (from 0): `min(max_s, base_s * 2**attempt) * (0.5 + rand)`."""
    return min(max_s, base_s * (2 ** attempt)) * (0.5 + rand)


def may_retry(method: str, headers: Mapping[str, str], status: Optional[int]) -> bool:
    """Whether an answer with `status` (None: a connection error or a timeout) may be retried for this request."""
    if status is not None and status not in RETRY_STATUSES:
        return False
    safe = method.upper() in IDEMPOTENT_METHODS or any(str(k).lower() == "idempotency-key" for k in headers)
    return safe or status == 429


def _check_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    out = {}
    for name, value in headers.items():
        name, value = str(name), str(value)
        if not name or any(c not in _TOKEN for c in name):
            raise HttpError("a header name is not an HTTP token", kind="refused")
        if any(c in value for c in "\r\n\0"):
            raise HttpError("a header value carries a line break or NUL", kind="refused")
        out[name] = value
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect is answered as it came, never followed
        return None


class _Watchdog:
    """Shuts a request's socket down when its deadline passes, so a server that trickles its headers or a chunk-size
    line cannot hold the caller past it (a socket timeout bounds one read, not a whole response)."""

    def __init__(self, end: float):
        self.end = end
        self.fired = False
        self._timer: Optional[threading.Timer] = None

    def arm(self, sock: Any) -> None:
        def fire() -> None:
            self.fired = True
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._timer = threading.Timer(max(0.0, self.end - time.monotonic()), fire)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


def _watched(base: type, watchdog: _Watchdog) -> type:
    class Watched(base):  # type: ignore[misc, valid-type]
        def connect(self) -> None:
            super().connect()
            watchdog.arm(self.sock)
    return Watched


def _opener(watchdog: _Watchdog) -> urllib.request.OpenerDirector:
    class Http(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(_watched(http.client.HTTPConnection, watchdog), req)

    class Https(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_watched(http.client.HTTPSConnection, watchdog), req, context=self._context)
    return urllib.request.build_opener(_NoRedirect, Http, Https)


def urllib_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout_s: float,
                     max_bytes: int) -> Tuple[int, Dict[str, str], bytes]:
    """The default transport: urllib, no redirects followed, the body read to one byte past `max_bytes`."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    end = time.monotonic() + timeout_s  # one deadline from the first byte sent, headers and body included
    watchdog = _Watchdog(end)
    try:
        return _send(req, timeout_s, max_bytes, end, watchdog)
    except (OSError, http.client.HTTPException) as exc:
        if watchdog.fired:
            raise TimeoutError("the answer did not arrive within the deadline")
        raise exc if isinstance(exc, OSError) else ConnectionError(type(exc).__name__)
    finally:
        watchdog.cancel()


def _send(req: urllib.request.Request, timeout_s: float, max_bytes: int, end: float,
          watchdog: _Watchdog) -> Tuple[int, Dict[str, str], bytes]:
    try:
        resp = _opener(watchdog).open(req, timeout=timeout_s)
    except urllib.error.HTTPError as answer:  # a status outside 2xx is an answer, not a failure of the transport
        resp = answer
    except urllib.error.URLError as exc:
        reason = exc.reason
        raise reason if isinstance(reason, OSError) else ConnectionError(str(reason))
    except (http.client.HTTPException, ValueError) as exc:
        raise ConnectionError(type(exc).__name__)
    try:
        chunks, size = [], 0
        while size <= max_bytes:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("the body did not arrive within the deadline")
            sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
            if sock is not None:
                sock.settimeout(left)  # each read waits at most what is left of the deadline
            chunk = resp.read1(min(65536, max_bytes + 1 - size))
            if watchdog.fired:  # Linux reads a shut socket as a clean end: a cut answer is never a whole one
                raise TimeoutError("the body did not arrive within the deadline")
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        data = b"".join(chunks)[:max_bytes + 1]
        return resp.status if hasattr(resp, "status") else resp.code, dict(resp.headers.items()), data
    except http.client.HTTPException as exc:
        raise ConnectionError(type(exc).__name__)
    finally:
        resp.close()


def request(method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, body: Any = None,
            deadline_s: float = 30.0, retries: int = 2, max_bytes: int = DEFAULT_MAX_BYTES, backoff_base_s: float = 0.5,
            max_backoff_s: float = 8.0, max_retry_after_s: float = 30.0, insecure: bool = False,
            transport: Optional[Transport] = None, sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic, rand: Callable[[], float] = _random.random) -> Response:
    """Send one request under the rules above and return its answer, whatever its status; raise `HttpError` when
    no answer came (a connection error, the deadline, a body over the cap, a refused URL). A `dict` or `list` body is
    sent as JSON with `Content-Type: application/json` unless the caller set one; `bytes` and `str` go as they are."""
    method = str(method).upper()
    if not method or any(c not in _TOKEN for c in method):
        raise HttpError("the method is not an HTTP token", kind="refused")
    if not (isinstance(retries, int) and 0 <= retries <= 10) or isinstance(retries, bool):
        raise HttpError("retries is an integer from 0 to 10", kind="refused")
    if not (deadline_s > 0 and max_bytes > 0):
        raise HttpError("deadline_s and max_bytes are positive", kind="refused")
    check_url(url, insecure=insecure)
    sent = _check_headers(headers or {})
    data: Optional[bytes]
    if body is None:
        data = None
    elif isinstance(body, (dict, list)):
        try:
            data = json_bytes(body)
        except (ValueError, TypeError):
            raise HttpError("the body holds a value JSON cannot write (NaN, Infinity or a non-JSON type)", kind="refused")
        if not any(k.lower() == "content-type" for k in sent):
            sent["Content-Type"] = "application/json"
    elif isinstance(body, str):
        data = utf8(body)
    elif isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    else:
        raise HttpError("the body is bytes, str, a dict or a list", kind="refused")
    send = transport or urllib_transport
    where = redact_url(url)
    end = clock() + deadline_s
    attempt = 0
    while True:
        left = end - clock()
        if left <= 0:
            raise HttpError("%s %s: the deadline passed before an answer" % (method, where), url=where,
                            attempts=attempt, kind="timeout")
        attempt += 1
        status: Optional[int] = None
        failure: Optional[HttpError] = None
        try:
            status, got_headers, got = send(method, url, dict(sent), data, left, max_bytes)
        except HttpError:
            raise
        except (TimeoutError, socket.timeout):  # socket.timeout is no TimeoutError before Python 3.10
            failure = HttpError("%s %s: timed out" % (method, where), url=where, attempts=attempt, kind="timeout")
        except Exception as exc:  # noqa: BLE001 - as the Node twin: whatever the transport throws is a connection error
            failure = HttpError("%s %s: connection error (%s)" % (method, where, type(exc).__name__), url=where,
                                attempts=attempt, kind="connection")
        if failure is None:
            if len(got) > max_bytes:
                raise HttpError("%s %s: the answer is over %d bytes" % (method, where, max_bytes), status=status,
                                url=where, attempts=attempt, kind="too-large")
            answer = Response(status, got_headers, got, attempts=attempt, url=where)
            if not may_retry(method, sent, status) or attempt > retries:
                return answer
            wait = retry_after_s(answer.headers.get("retry-after"))
            if wait is not None:
                if wait > max_retry_after_s:
                    return answer  # the server asks for longer than this caller will wait
            else:
                wait = backoff_s(attempt - 1, base_s=backoff_base_s, max_s=max_backoff_s, rand=rand())
        else:
            if not may_retry(method, sent, None) or attempt > retries:
                raise failure
            answer = None
            wait = backoff_s(attempt - 1, base_s=backoff_base_s, max_s=max_backoff_s, rand=rand())
        if clock() + wait >= end:
            if answer is not None:
                return answer
            raise failure  # type: ignore[misc]
        sleep(wait)
