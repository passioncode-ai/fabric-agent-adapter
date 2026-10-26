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
SECRET_VALUE = re.compile(r'(^bearer\s.+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}'
                          r'|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})', re.I | re.S)
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
    return bool(JWT_SHAPE.search(value) or SECRET_VALUE.search(value) or long_secret)


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
            and len(path) <= 2048 and not re.search(r'[\\\x00-\x1f\x7f]', path))


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
    query = parse_qs(deep.query, keep_blank_values=True, strict_parsing=True)
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
    else:
        raise ValueError('unsupported_dashboard_action')
    return {'ok': True, 'kind': kind}


def main():
    try:
        raw = sys.stdin.read(65537)
        require(len(raw) <= 65536, 'input_too_large')
        result = check(json.loads(raw))
    except (ValueError, TypeError, KeyError, AttributeError):
        # Fixed reasons only: never echo a submitted URL, token or JSON blob.
        result = {'ok': False, 'reason': 'dashboard_handoff_refused'}
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
