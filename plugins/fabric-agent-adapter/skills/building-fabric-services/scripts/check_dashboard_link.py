#!/usr/bin/env python3
"""Check one structured dashboard handoff from stdin. No I/O effects; exit 0/1.

The caller supplies a trusted host resolver result and observed device/host context.
This is an output correctness gate, not authentication, discovery, or a relay.
"""
import json
import re
import sys
from urllib.parse import parse_qs, parse_qsl, unquote, urlsplit


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# Credential names and values: the same rules as fabric-button.js (credentialName, secretValue).
CREDENTIAL_WORDS = {
    'token', 'secret', 'password', 'passwd', 'pass', 'passphrase', 'credential', 'credentials', 'cookie',
    'authorization', 'bearer', 'jwt', 'otp', 'apikey', 'signature', 'sig', 'accesstoken', 'idtoken', 'authtoken',
    'refreshtoken', 'sessionid', 'sessiontoken', 'logincode', 'authcode', 'privatekey', 'clientsecret', 'secretkey',
    'accesskey'}
CREDENTIAL_PAIRS = {
    'key': {'private', 'api', 'access', 'secret', 'session', 'auth', 'signing', 'encryption', 'master', 'client', 'login',
            'refresh'},
    'auth': {'token', 'code', 'header'},
    'session': {'token', 'id'},
    'code': {'login', 'auth', 'access', 'session'}}
JWT_SHAPE = re.compile(r'eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*')
URL_BASE64_RUN = re.compile(r'[A-Za-z0-9_-]*')


def has_jwt(text):
    # Whether JWT_SHAPE matches anywhere, read in one pass (the contract's hasJwt, FAA-313): the expression backtracks
    # from every `eyJ` of a long run, quadratic in it, while every `eyJ` of one run shares that run's end, so only its
    # first is tried. The kit's fabric_secrets.has_jwt reads the same way; this file stands alone, so it has its own.
    at = text.find('eyJ')
    while at >= 0:
        one = URL_BASE64_RUN.match(text, at + 3).end()
        if one - at - 3 >= 2 and text[one:one + 1] == '.':
            two = URL_BASE64_RUN.match(text, one + 1).end()
            if two - one - 1 >= 2 and text[two:two + 1] == '.':
                return True
        at = text.find('eyJ', one)
    return False


# The contract's SECRET_VALUE at the pin (DEC-0151): `Bearer ` at a value's start in any case, or a provider key with its
# prefix in its canonical case after a boundary (the start, a character that is no ASCII letter or digit, or an escape);
# an `sk-` key holds a digit and an upper-case letter with 16 or more characters, or a digit with 32 or more.
SECRET_VALUE = re.compile(r'(^[Bb][Ee][Aa][Rr][Ee][Rr]\s.+|(?:^|[^A-Za-z0-9]|%[0-9A-Fa-f]{2}|\\[nrt"\']|\\u[0-9A-Fa-f]{4}'
                          r'|\\x[0-9A-Fa-f]{2}|\\[bfv0ae]|\\[0-7]{1,3}|%25[0-9A-Fa-f]{2}|\x1b\[[0-9;:]*m'
                          r'|(?:\\u001[bB]|\\x1[bB]|\\e|\\033|\\33)\[[0-9;:]*m)'
                          r'(?:sk-(?=[A-Za-z0-9_-]{0,255}?[0-9])(?:(?=[A-Za-z0-9_-]{0,255}?[A-Z])[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{32,})'
                          r'|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}))', re.S)
LONG_RUN = re.compile(r'[A-Za-z0-9+/=_-]{40,}')


def name_words(name):
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    return [w.lower() for w in re.split(r'[\s._-]+', name) if w]


def credential_name(name):
    split = name_words(name)
    words = set(split) | {w[:-1] for w in split if len(w) > 2 and w.endswith('s')}
    if words & CREDENTIAL_WORDS:
        return True
    if len(split) == 1 and words & set(CREDENTIAL_PAIRS):
        return True
    return any(w in words and words & pairs for w, pairs in CREDENTIAL_PAIRS.items())


def secret_value(value):
    long_secret = any(re.search(r'[a-z]', run) and re.search(r'[A-Z]', run) and re.search(r'[0-9]', run)
                      for run in LONG_RUN.findall(value))
    return bool(has_jwt(value) or SECRET_VALUE.search(value) or long_secret)


def carries_credential(text):
    # A query or fragment whose names or values could be a credential: refused even with an empty value.
    return (secret_value(text) or secret_value(unquote(text))
            or any(credential_name(name) or secret_value(name) or secret_value(value)
                   for name, value in parse_qsl(text, keep_blank_values=True)))


def login_path(path):
    # The path a server routes: refuse what normalises differently in different servers, then compare.
    decoded = unquote(path)
    require(not re.search(r'%2f|%5c', path, re.I) and '\\' not in decoded, 'encoded_separator')
    segments = decoded.split('/')[1:]
    require(not any(seg in ('.', '..') for seg in segments), 'dot_segment')
    require(all(seg for seg in segments[:-1]), 'empty_segment')
    return '/'.join([''] + [seg for seg in segments if seg]).lower() == '/fabric/v1/login'


def safe_path(path):
    return (isinstance(path, str) and path.startswith('/') and not path.startswith('//')
            and len(path) <= 2048 and not re.search(r'[\\\x00-\x1f\x7f]', path)
            # JavaScript's whitespace (\s), which the contract's parseDashboardsLink refuses in a page (DEC-0123)
            and not re.search('[ \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]', path))


def check(data):
    require(isinstance(data, dict), 'invalid_input')
    resolved, host, action = (data.get(k) for k in ('resolved', 'host', 'action'))
    require(all(isinstance(v, dict) for v in (resolved, host, action)), 'missing_context')
    service, native, http = (resolved.get(k) for k in ('service', 'open_link', 'http_url'))
    require(isinstance(service, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*', service), 'invalid_service')
    require(isinstance(native, str) and isinstance(http, str), 'missing_resolved_links')
    require(not re.search(r'[\\\x00-\x20\x7f]', native + http), 'unsafe_url')
    deep, plain = urlsplit(native), urlsplit(http)
    require(deep.scheme == 'fabric-dashboards' and not deep.username and not deep.password and not deep.port and not deep.fragment, 'invalid_deep_link')
    # An empty query is no fields: Python 3.9's strict parse_qs raises on '' where 3.11 and later answer {}.
    query = parse_qs(deep.query, keep_blank_values=True, strict_parsing=True) if deep.query else {}
    # DEC-0123 PL-1: only the service form; the legacy open?service= link is refused (FAC-SEM-143, since 0.51.0).
    require(deep.netloc == 'service', 'not_service_link')
    require(deep.path in ('/' + service, '/' + service + '/') and set(query) <= {'path'}, 'wrong_service_or_parameter')
    require('path' not in query or len(query['path']) == 1, 'duplicate_path')
    page = query.get('path', [None])[0]
    require(page is None or safe_path(page), 'unsafe_path')
    require(plain.scheme == 'http' and plain.hostname in ('127.0.0.1', 'localhost', '::1') and plain.port is not None
            and not plain.username and not plain.password, 'invalid_http_fallback')
    http_page = plain.path + ('?' + plain.query if plain.query else '') + ('#' + plain.fragment if plain.fragment else '')
    require(safe_path(http_page) and http_page == (page or '/'), 'mismatched_page')
    sensitive = {'token', 'access_token', 'refresh_token', 'password', 'secret', 'login_code', 'code', 'api_key',
                 'apikey', 'key', 'auth'}
    parts = urlsplit(http_page)
    places = [parts.query, parts.fragment] + parts.fragment.split('?', 1)[1:]
    require(not any(sensitive.intersection(k.lower() for k in parse_qs(p, keep_blank_values=True)) for p in places),
            'credential_query')
    require(not any(carries_credential(p) for p in places), 'credential_query')
    require(not login_path(parts.path), 'login_link_is_not_dashboard')
    state = host.get('state')
    require(state in ('available', 'not_installed', 'unknown', 'incompatible', 'handler_mismatch', 'unsupported'), 'unknown_host_state')
    target, viewer = data.get('target_device'), data.get('viewer_device')
    require(all(isinstance(v, str) and 0 < len(v) <= 200 for v in (target, viewer)), 'missing_device')
    fallback = data.get('fallback', 'if_absent')
    require(fallback in ('if_absent', 'never'), 'invalid_fallback')
    # DEC-0154 PL-3 and HA-2 (FAA-251): who listens on http_url's port, as the host read it from the socket table
    # (fabric_peer_owner's kinds, or check_service.py's foreign-user). A browser opens a raw loopback address only
    # after that listener is this OS account's; absent, it is unknown.
    owner = data.get('listener_owner', 'unknown')
    require(owner in ('this-account', 'another-account', 'system', 'unknown', 'none', 'foreign-user'), 'invalid_listener_owner')
    kind = action.get('kind')
    if kind == 'remote_open':
        require(set(action) <= {'kind', 'device_id', 'service', 'path'}, 'unexpected_action_field')
        require(action.get('device_id') == target and action.get('service') == service and action.get('path') == page, 'wrong_remote_target')
        require(viewer != target, 'remote_action_on_local_device')
    elif kind == 'native_link':
        require(set(action) == {'kind', 'url'} and action.get('url') == native, 'not_host_provided_link')
        require(viewer == target, 'wrong_viewer_device')
        require(state == 'available', 'host_unavailable')
    elif kind == 'browser_link':
        require(set(action) == {'kind', 'url'} and action.get('url') == http, 'not_resolved_http_url')
        require(viewer == target, 'wrong_viewer_device')
        require(state == 'not_installed' and fallback == 'if_absent', 'browser_fallback_forbidden')
        require(owner == 'this-account', 'listener_not_this_account')
    else:
        raise ValueError('unsupported_dashboard_action')
    return {'ok': True, 'kind': kind}


def read_input(limit=65536):
    # The handoff's bytes, decoded as UTF-8 with a byte order mark dropped: Windows before Python 3.15 decodes a text
    # stdin with its code page, which misreads a Cyrillic handoff (FAA-210). A stream without bytes is read as text.
    stream = getattr(sys.stdin, 'buffer', None)
    raw = stream.read(limit + 1) if stream is not None else sys.stdin.read(limit + 1)
    require(len(raw) <= limit, 'input_too_large')
    return raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw.lstrip('\ufeff')


def main():
    try:
        result = check(json.loads(read_input()))
    # RecursionError: Python 3.9 to 3.13 raise it on a deeply nested document under the cap
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        # Fixed reasons only: never echo a submitted URL, token or JSON blob.
        result = {'ok': False, 'reason': 'dashboard_handoff_refused'}
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
