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
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

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
        return json.loads(self.body.decode("utf-8"))


_SURROGATE = re.compile("[\ud800-\udfff]")


def utf8(text: str) -> bytes:
    """Text as UTF-8 the way `TextEncoder` writes it: a lone surrogate becomes U+FFFD instead of an error."""
    return _SURROGATE.sub("\ufffd", text).encode("utf-8")


def json_bytes(value: Any) -> bytes:
    """Compact JSON as `JSON.stringify` writes it, in UTF-8: a lone surrogate escaped as `\\uXXXX`, and NaN or
    Infinity refused (`ValueError`) rather than written as a token no JSON reader accepts."""
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return _SURROGATE.sub(lambda m: "\\u%04x" % ord(m.group()), text).encode("utf-8")


def redact_url(url: str) -> str:
    """The URL as it may appear in an error or a log line: scheme, host, port and path; no userinfo, query or
    fragment, which is where keys and tokens ride."""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return "<unparseable url>"
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
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
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
    if hh > 23 or mm > 59 or ss > 60:
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


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout_s: float,
                     max_bytes: int) -> Tuple[int, Dict[str, str], bytes]:
    """The default transport: urllib, no redirects followed, the body read to one byte past `max_bytes`."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        resp = _OPENER.open(req, timeout=timeout_s)
    except urllib.error.HTTPError as answer:  # a status outside 2xx is an answer, not a failure of the transport
        resp = answer
    except urllib.error.URLError as exc:
        reason = exc.reason
        raise reason if isinstance(reason, OSError) else ConnectionError(str(reason))
    except (http.client.HTTPException, ValueError) as exc:
        raise ConnectionError(type(exc).__name__)
    end = time.monotonic() + timeout_s
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
        except ValueError:
            raise HttpError("the body holds a number JSON cannot write (NaN or Infinity)", kind="refused")
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
        except TimeoutError:
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
