// FAA-256: what the kit's owner check costs per new loopback connection, measured where it runs (the nightly Windows
// job: two `netstat -ano` reads and one PowerShell GetOwnerSid there, each capped at 5 s). It connects to a loopback
// server ROUNDS times on a new connection each time and times both sides' reads: the server's `peer` (who connected)
// and the client's `serverEnd` (who accepted). Prints one JSON line; it is a measurement, never a gate (exit 0 unless
// the reads cannot run at all). Run: node test/measure_owner_check.mjs [ROUNDS]
import net from 'node:net';
import { performance } from 'node:perf_hooks';
import { peer, serverEnd } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-peer-owner.mjs';

const rounds = Math.max(1, Math.min(50, Number.parseInt(process.argv[2] ?? '10', 10) || 10));

const quantile = (values, q) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
};
const summary = (values) => ({ min: Math.min(...values), median: quantile(values, 0.5), p95: quantile(values, 0.95),
  max: Math.max(...values) });
const round = (ms) => Math.round(ms * 10) / 10;

async function once(server) {
  const accepted = new Promise((resolve) => server.once('connection', resolve));
  const client = net.connect(server.address().port, '127.0.0.1');
  await new Promise((resolve, reject) => { client.once('connect', resolve); client.once('error', reject); });
  const socket = await accepted;
  const started = performance.now();
  const who = await peer(socket);
  const peerMs = performance.now() - started;
  const again = performance.now();
  const end = await serverEnd(client);
  const endMs = performance.now() - again;
  client.destroy();
  socket.destroy();
  return { peerMs, endMs, peerKind: who.kind, peerMethod: who.method, endKind: end.kind, endMethod: end.method };
}

const server = net.createServer();
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const runs = [];
try {
  for (let i = 0; i < rounds; i += 1) runs.push(await once(server));
} finally {
  server.close();
}
const peerTimes = runs.map((r) => r.peerMs);
const endTimes = runs.map((r) => r.endMs);
const kinds = (key) => [...new Set(runs.map((r) => r[key]))];
console.log(JSON.stringify({
  measure: 'owner-check-per-connection', platform: process.platform, node: process.version, rounds,
  peerMs: Object.fromEntries(Object.entries(summary(peerTimes)).map(([k, v]) => [k, round(v)])),
  serverEndMs: Object.fromEntries(Object.entries(summary(endTimes)).map(([k, v]) => [k, round(v)])),
  peerKinds: kinds('peerKind'), peerMethods: kinds('peerMethod'), serverEndKinds: kinds('endKind'), serverEndMethods: kinds('endMethod'),
}));
