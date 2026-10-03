#!/usr/bin/env node
// A complete ONLINE Fabric service (fabric-service/0.1, remote placement — DEC-0019): the four
// protocol routes and a dashboard page, Node.js 20+, no dependencies beside the kit.
//
// It runs two ways, the two an online service meets in practice:
//   - terminating TLS itself:   --tls-cert cert.pem --tls-key key.pem
//   - behind a platform router that ends TLS (a PaaS): no TLS flags; the router's
//     `x-forwarded-proto` must say https or the request is refused.
//
//   node sample-remote-service.mjs --origin https://agent.example.com --port 8443 \
//     --token-file token --session-key-file session.key [--tls-cert c.pem --tls-key k.pem]
//
// Secrets come from files (or from the platform as FABRIC_SERVICE_TOKEN / FABRIC_SESSION_KEY),
// never from an argument vector.

import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import * as k from './fabric-service.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const origin = args.origin ?? process.env.FABRIC_SERVICE_ORIGIN;
const port = Number(args.port ?? process.env.PORT ?? 8443);
const token = args['token-file'] ? fs.readFileSync(args['token-file'], 'utf8').trim() : String(process.env.FABRIC_SERVICE_TOKEN ?? '').trim();
const key = args['session-key-file'] ? fs.readFileSync(args['session-key-file']) : Buffer.from(String(process.env.FABRIC_SESSION_KEY ?? ''), 'base64');
if (!origin || k.remoteOriginProblems(origin).length) { console.error(`origin: ${k.remoteOriginProblems(origin).join('; ') || 'missing'}`); process.exit(2); }
if (token.length < 16) { console.error('the service token is missing or shorter than 16 characters'); process.exit(2); }

const startedAt = k.nowIso();
const codes = new k.LoginCodes(null, 120, { store: new k.MemoryCodeStore(), key });
const events = [k.makeEvent('1', startedAt, 'service.started', 'info', 'The example agent started.')];
const tlsSelf = Boolean(args['tls-cert']);

function send(res, status, body, headers = {}) {
  const payload = body === null ? '' : (typeof body === 'string' ? body : JSON.stringify(body));
  res.writeHead(status, { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...(body === null || typeof body === 'string' ? {} : { 'Content-Type': 'application/json' }), ...headers });
  res.end(payload);
}

function handler(req, res) {
  const url = new URL(req.url, origin);
  const refusal = k.checkRemoteRequest(origin, req.headers.host, req.headers.origin, req.headers['sec-fetch-site'], tlsSelf ? undefined : (req.headers['x-forwarded-proto'] ?? 'http'));
  if (refusal) return send(res, 403, refusal, { 'Content-Type': 'text/plain; charset=utf-8' });
  const authorized = k.tokenMatches(req.headers.authorization, token);

  if (req.method === 'GET' && url.pathname === '/.well-known/fabric-service') {
    if (!k.wellKnownAllowed('remote', req.headers.authorization, token)) return send(res, 401, null);
    return send(res, 200, k.buildWellKnown({
      id: 'example-agent', instance: 'default', name: 'Example Agent', version: '0.1.0', build: { commit: '0000000' },
      startedAt, status: 'ready', degraded: [],
      surfaces: { dashboard: { path: '/', login: true }, events: { path: '/fabric/v1/events' } },
      summary: [{ label: 'Jobs today', value: events.length }],
    }));
  }
  if (req.method === 'GET' && url.pathname === '/fabric/v1/events') {
    if (!authorized) return send(res, 401, null);
    return k.eventsPage(async (after, limit) => events.filter((e) => after === null || Number(e.id) > Number(after)).slice(-limit), url.searchParams.get('after'), k.parseLimit(url.searchParams.get('limit'))).then((page) => send(res, 200, page));
  }
  if (req.method === 'POST' && url.pathname === '/fabric/v1/login-code') {
    if (!authorized) return send(res, 401, null);
    return send(res, 200, codes.issue());
  }
  if (req.method === 'GET' && url.pathname === '/fabric/v1/login') {
    const session = codes.redeem(url.searchParams.get('code'));
    if (!session) return send(res, 403, 'This login link has expired or was used. Open the dashboard from Fabric again.', { 'Content-Type': 'text/plain; charset=utf-8' });
    return send(res, 302, null, { Location: '/', 'Set-Cookie': k.remoteSessionCookieHeader(session) });
  }
  if (req.method === 'GET' && url.pathname === '/') {
    if (!codes.sessionValid(k.cookieValue(req.headers.cookie, k.REMOTE_SESSION_COOKIE))) return send(res, 401, 'Sign in from Fabric Dashboards.', { 'Content-Type': 'text/plain; charset=utf-8' });
    return send(res, 200, '<!doctype html><meta charset="utf-8"><title>Example Agent</title><h1>Example Agent</h1>', { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': "default-src 'none'" });
  }
  return send(res, 404, null);
}

const server = tlsSelf
  ? https.createServer({ cert: fs.readFileSync(args['tls-cert']), key: fs.readFileSync(args['tls-key']) }, handler)
  : http.createServer(handler);
server.listen(port, tlsSelf ? '127.0.0.1' : '0.0.0.0', () => console.log(`example agent on ${origin} (listening on ${port}${tlsSelf ? ', TLS' : ', behind a TLS router'})`));
for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => server.close(() => process.exit(0)));
