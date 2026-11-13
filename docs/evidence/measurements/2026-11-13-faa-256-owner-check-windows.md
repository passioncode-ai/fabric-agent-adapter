# The Node owner check's cost on Windows (FAA-256)

Measured 2026-11-13 by the nightly `validate.yml` run 43350961753 (job `windows`, step `node test/measure_owner_check.mjs 20`,
Node v22.23.4, GitHub's hosted Windows runner), on `main` at the 0.83.0 integration:

| Side | Method | min | median | p95 | max |
|---|---|---|---|---|---|
| a server reading its peer (`peer`) | `netstat-windows` | 293.8 ms | 309.6 ms | 365.8 ms | 365.8 ms |
| a client reading the server end (`serverEnd`) | `netstat-windows` | 292.6 ms | 305.9 ms | 321.1 ms | 321.1 ms |

Every answer was `this-account`. The raw line, as the job printed it:

```
{"measure":"owner-check-per-connection","platform":"win32","node":"v22.23.4","rounds":20,"peerMs":{"min":293.8,"median":309.6,"p95":365.8,"max":365.8},"serverEndMs":{"min":292.6,"median":305.9,"p95":321.1,"max":321.1},"peerKinds":["this-account"],"peerMethods":["netstat-windows"],"serverEndKinds":["this-account"],"serverEndMethods":["netstat-windows"]}
```

For comparison, macOS (the same script, 2026-11-13): about 49 ms server side and 45 ms client side.

So one new loopback connection on Windows costs about 0.3 s of owner check on each side (two `netstat -ano` reads and
one PowerShell `GetOwnerSid`). `fabric-http.mjs`'s loopback agent opens a connection per request; a caller that sends
many requests in a row to one service keeps its own agent alive, as the hub client does.

## The hub keeps idle connections longer than the client

Fabric at `723dd1be` (2026-11-13) creates its agent surface with `createServer` in
`apps/desktop/src/main/agentSurface.ts:594` and `:624` and sets no `keepAliveTimeout` anywhere under
`apps/desktop/src/main` (`git grep -n "keepAliveTimeout\|requestTimeout" apps/desktop/src/main` prints nothing), so Node's
default of 5000 ms applies: above the kit client's 2 s idle, so the client closes an idle connection before the hub does
and never sends on a socket the hub is closing.
