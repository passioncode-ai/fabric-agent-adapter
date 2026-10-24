# 2026-10-24: the Node package reader narrows a folder swap (0.48.3)

**Objective.** The next rows after 0.48.2, the operator's standing request («давай доделывай все сам автономно и
выбирай лучшие решения для меня и в итоге заливай все обнови доки и новая версия»): FAA-84 (documented and pinned, PR
[#185](https://github.com/passioncode-ai/fabric-agent-adapter/pull/185)) and FAA-91.

**Done.** 0.48.3: `readFolder` in `fabric-package.mjs` checks each folder after every file it reads, beside the checks
before and after listing; a folder swapped for a link while a file is read is refused as a symlink.
`references/package.md` names what is still not seen (a swap made and undone between two checks: Node has no openat).
The release also carries FAA-84's recipe README.

**Checks actually run.** The new Node test (`FAA-91`) red on the old code (the swap went unseen), green after; the
package suite 19 of 19. Full suites: Python 1018 tests OK (28 skipped by environment flags), Node 324 tests 0 fail;
`validate.py` and both `claude plugin validate --strict` exit 0. The hosted suite runs in `release.yml` before the publish.

**Context.** Earlier on 2026-10-24 the Mac's disk reached 207 MB free with swap at 15 of 16 GB (commands failed with
ENOSPC); the operator was notified through the communicator. At this handoff: 5.3 GB free, swap 12 GB.

**Open.** FAA-87 (the operator's `npm login`), FAA-89, FAA-98, FAA-60, FAA-88, FAA-106 and FAA-103 on demand.

**Exact next task.** FAA-87 once the operator has run `npm login`; otherwise FAA-89 (watch-mail delays Stop-hook
delivery: document it in `session-hooks.md`).
