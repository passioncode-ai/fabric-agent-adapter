// A fixture conversation for the probe (check_service.py, rule board.responder): a scripted board a responder can run against without Fabric.
// Part of the Node board connector (FAA-65, layer L4); the twin of fabric_board_fixture.py. Node 20+, no dependency.
import fs from 'node:fs';
import path from 'node:path';
import { Backoff, HubError, MCP_PROTOCOL_VERSION, normalProject, postMcp, toolAnswer } from './fabric-hub.mjs';
import { COMMS_PROTOCOL, RESPOND_TOOLS } from './fabric-board-shapes.mjs';
import { BoardSession, Responder } from './fabric-board-session.mjs';

const FIXTURE_PROJECT = '3f2a6b1c-0d4e-4f5a-8b6c-7d8e9f0a1b2c';

const FIXTURE_DIGEST = `sha256:${'a'.repeat(64)}`;

function fixtureAnswers(variant) {
  const lease = '2026-10-13T10:02:00Z';
  const status = { protocol: COMMS_PROTOCOL, board: { state: 'ready' }, project: FIXTURE_PROJECT, responders: [], transport: { telegram: 'off' }, unread: 0, idempotency: { epoch: 3 } };
  if (variant === 'no-epoch') delete status.idempotency;
  const request = { id: 'req_A1b2C3d4E5', state: 'claimed', effect: 'not_started', revision: 2 };
  return {
    'com.status': status,
    'com.enroll': { ok: true, repeated: false, slot: { project: FIXTURE_PROJECT, capability: 'fixture.render', generation: 2, leaseExpiresAt: lease } },
    'com.claim': { ok: true, repeated: false, message: 'msg_K9j8H7g6F5', request, attempt: { id: 'att_Zx9Cv8Bn7M', generation: 2, digest: FIXTURE_DIGEST, leaseExpiresAt: lease } },
    'com.get': { id: 'msg_K9j8H7g6F5', thread: 'thr_8Hc2kQ9xA1', kind: 'request', at: '2026-10-13T10:00:00Z', digest: FIXTURE_DIGEST,
      sender: { project: 'proj-requester', principal: { kind: 'agent', id: 's-1', provenance: 'trusted' } }, body: { text: 'Render the fixture.' },
      request: { id: 'req_A1b2C3d4E5', target: FIXTURE_PROJECT, capability: 'fixture.render', state: 'claimed', effect: 'not_started', revision: 2 } },
    'com.accept': variant === 'fenced' ? { error: { code: 'fenced', message: 'A newer responder holds this slot; this call was not committed.', retryable: false } }
      : { ok: true, repeated: false, request: { ...request, state: 'accepted', revision: 3 } },
    'com.complete': { ok: true, repeated: false, request: { ...request, state: 'completed', revision: 4 } },
  };
}

/** One scripted conversation per path through this kit, with no Fabric; answers the problems found (empty: it passes). */
export async function selfCheck() {
  const os = await import('node:os');
  const problems = [];
  for (const variant of ['whole', 'fenced', 'no-epoch']) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-board-fixture-'));
    try {
      const root = path.join(tmp, 'fabric');
      fs.mkdirSync(root, { mode: 0o700 });
      const door = path.join(root, 'hub-door-token');
      fs.writeFileSync(door, 'd'.repeat(43), { mode: 0o600 });
      fs.writeFileSync(path.join(root, 'hub.json'), JSON.stringify({ protocol: 'fabric-hub/0.1', origin: 'http://127.0.0.1:47070', mcp: '/mcp', doorTokenFile: door, pid: process.pid, startedAt: '2026-10-13T10:00:00Z' }));
      const cred = path.join(tmp, 'credential');
      fs.writeFileSync(cred, 'c'.repeat(43), { mode: 0o600 });
      const answers = fixtureAnswers(variant);
      const calls = [];
      const handled = [];
      const post = async (origin, body, bearer, { method = 'POST' } = {}) => {
        if (method === 'DELETE') return { status: 200, headers: {}, body: null };
        if (body.method === 'initialize') return { status: 200, headers: { 'mcp-session-id': 'fixture-session' }, body: { jsonrpc: '2.0', id: body.id, result: { protocolVersion: MCP_PROTOCOL_VERSION } } };
        if (body.method !== 'tools/call') return { status: 202, headers: {}, body: null };
        const tool = body.params.name;
        calls.push([tool, body.params.arguments]);
        if (tool === 'fabric.board.join') return { status: 200, headers: {}, body: { jsonrpc: '2.0', id: body.id, result: { structuredContent: { session: { bearer: 'b'.repeat(43), sessionId: 's-fixture', projectId: FIXTURE_PROJECT, capabilities: ['fixture.render'] } } } } };
        const value = answers[tool] ?? { error: { code: 'unsupported_capability', message: 'not in the fixture', retryable: false } };
        return { status: 200, headers: {}, body: { jsonrpc: '2.0', id: body.id, result: { content: [{ type: 'text', text: JSON.stringify(value) }] } } };
      };
      const { HubClient } = await import('./fabric-hub.mjs');
      const responder = new Responder({ hub: new HubClient(root, { post }), projectId: FIXTURE_PROJECT, capabilities: ['fixture.render'], credentialFile: cred,
        checkpointFile: path.join(tmp, 'checkpoint.json'), handler: (request) => { handled.push(request.body); return { state: 'completed', summary: 'Rendered.' }; },
        admit: () => null, now: () => 0, rand: () => 0.5, sessionFactory: (grant) => new BoardSession(grant, { post }) });
      await responder.step();
      const tools = calls.map(([t]) => t);
      if (tools.some((t) => !RESPOND_TOOLS.has(t) && t !== 'fabric.board.join')) problems.push(`${variant}: a tool outside the respond scope was sent`);
      if (variant === 'whole') {
        if (tools.join(',') !== 'fabric.board.join,com.status,com.enroll,com.claim,com.get,com.accept,com.complete') problems.push(`whole: the calls were ${tools.join(', ')}`);
        const accept = calls.find(([t]) => t === 'com.accept')?.[1]?.fence ?? {};
        if (accept.digest !== FIXTURE_DIGEST || accept.generation !== 2 || accept.attempt !== 'att_Zx9Cv8Bn7M') problems.push('whole: com.accept did not carry the claim\'s exact fence');
        if (handled.join('|') !== 'Render the fixture.') problems.push('whole: the handler did not see the request once');
        if (Object.keys(responder.checkpoint.entries).length) problems.push('whole: the checkpoint kept a settled request');
      } else if (variant === 'fenced') {
        if (handled.length || tools.includes('com.complete')) problems.push('fenced: the kit kept acting after com.accept answered fenced');
      } else if (tools.includes('com.enroll') || responder.state !== 'down') problems.push('no-epoch: the kit did not fail closed without an idempotency epoch');
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  }
  return problems;
}
