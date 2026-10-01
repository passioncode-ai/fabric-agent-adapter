#!/usr/bin/env python3
"""Check one structured dashboard handoff from stdin. No I/O effects; exit 0/1.

The caller supplies a trusted host resolver result and observed device/host context.
This is an output correctness gate, not authentication, discovery, or a relay.
"""
import json
import re
import sys
from urllib.parse import parse_qs, urlsplit


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


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
    if deep.netloc == 'service':
        require(deep.path in ('/' + service, '/' + service + '/') and set(query) <= {'path'}, 'wrong_service_or_parameter')
    else:
        require(deep.netloc == 'open' and deep.path in ('', '/') and query.get('service') == [service] and set(query) <= {'service', 'path'}, 'invalid_legacy_link')
    require('path' not in query or len(query['path']) == 1, 'duplicate_path')
    page = query.get('path', [None])[0]
    require(page is None or safe_path(page), 'unsafe_path')
    require(plain.scheme == 'http' and plain.hostname in ('127.0.0.1', 'localhost', '::1') and plain.port is not None
            and not plain.username and not plain.password, 'invalid_http_fallback')
    http_page = plain.path + ('?' + plain.query if plain.query else '') + ('#' + plain.fragment if plain.fragment else '')
    require(safe_path(http_page) and http_page == (page or '/'), 'mismatched_page')
    sensitive = {'token', 'access_token', 'refresh_token', 'password', 'secret', 'login_code'}
    page_query = parse_qs(urlsplit(http_page).query)
    require(not sensitive.intersection(k.lower() for k in page_query), 'credential_query')
    require(urlsplit(http_page).path != '/fabric/v1/login', 'login_link_is_not_dashboard')
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
