# Clean up after yourself

The operator's rule (board message `bfc0e14e`, 2026-11-12, FAA-301). What you created for a task is yours to remove
when the task is done; what anyone else holds is not.

## After a merge

- **Remove your own worktrees and branches** once the branch is merged: `git worktree remove <path>`, then
  `git branch -d <branch>` and `git push origin --delete <branch>`, then **`git fetch --prune`**.
- **A branch with commits found nowhere else is archived before it is deleted**: `git push origin
  <branch>:refs/archive/<YYYY-MM-DD>/<branch>` (and the same ref locally), checked with `git ls-remote origin
  'refs/archive/*'`, then deleted. `git branch --contains` and `git log <branch> --not --remotes` tell you whether it
  holds such commits.
- **Remove build output and dependency folders** (`node_modules`, `dist`, `build`, `.next`, `target`, `.venv`,
  `coverage`) in your own abandoned or merged copies. Prune tool caches only with their own commands.
- **Stop your own processes**: dev servers, browsers, watchers and test runs you started.

## Never

- another session's worktree, a worktree Git marks `locked` (`git worktree list --porcelain`), or a process you did not
  start;
- **a Git-tracked file**: before removing a folder, `git -C <repo> ls-files -- <dir>` must print nothing;
- a name list built across a whole disk or projects folder: remove what you named, one path at a time.

## The checklist

- [ ] Merged branches: worktree, local branch and remote branch removed; `git fetch --prune` run.
- [ ] Unique commits archived under `refs/archive/<date>/` before any delete.
- [ ] Build and dependency folders removed only after `git ls-files -- <dir>` printed nothing.
- [ ] Own processes stopped; nothing of another session's touched.
