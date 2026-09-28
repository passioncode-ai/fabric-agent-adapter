# Migrating an existing service

Order matters: each step leaves the service answering.

1. **Measure first.** Run `check_service.py --descriptor <draft>` against a descriptor
   written by hand into a temporary `--services-dir`; keep the `FAIL` list as the
   migration's checklist.
2. **Add the well-known route and the build identity.** Read-only, no risk.
3. **Add the events view** over the existing log, then the login-code routes. Keep the
   service's old login path until the operator has switched.
4. **Move the lock to the top of startup** — before the startup hook that resumes jobs.
   Test: a second copy exits 75 and the first copy's running jobs are untouched.
5. **Move state out of the code tree** if it lives there: copy to the OS data
   directory, switch the paths, keep the old tree read-only for one release, then
   delete it with the operator's consent.
6. **Regenerate the plist** from `launchd_plist`, pointing at a release; delete stray
   `.plist.bak` files from `~/Library/LaunchAgents` after moving them elsewhere.
7. **Write the descriptor** from the installer; resolve any port claim it refuses by
   moving the newcomer, never the established service.
8. **Re-run the probe** until nothing `FAIL`s; record the table in the service's
   verification document.

## Estate notes (measured 2026-09-28)

| Service | Needs |
|---|---|
| `sshlg-brand-agent` board, 8710 | lock, well-known (today `/healthz` → `{"ok":true}`), events view over `plan/journal.jsonl`, token + login code, data out of the repository, logging fixed (`basicConfig` in `cli.main`) |
| `mobile-publisher`, 8795 | lock before the startup hook (a second copy re-queues running jobs), well-known with commit, events view over the `events` table, descriptor with header `X-Publisher-Token` |
| `asset-foundry`, 8787 (+ preview instance 8791) | already locked by store; well-known with commit; one activity index over `jobs/*/events.jsonl`; preview becomes instance `preview`; plist off the worktree venv; remote chain (gateway, tunnel, 7-day token) watched |
| Project Observatory server, 47311 | well-known beside the heavy `/health`; lock; events view over the `events` table; its `fabric-agent.json` gains the extension key |
| `copylot-agent` | move off 8791 (claimed); lock; become a launchd service before a descriptor |
| `webpilot` | move off 8787 (claimed); an HTTP health route; lock |
