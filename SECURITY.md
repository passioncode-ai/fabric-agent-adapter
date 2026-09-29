# Security

Report vulnerabilities privately to contact@passioncode.ai. Do not open a public issue
containing credentials, private provider URLs, or customer project data.

The adapter must not write secret values to manifests, fixtures, probes, logs, or command
arguments. Generated and external provider outputs are untrusted. Live probes must be
bounded and non-publishing until explicit scoped grants exist in a project binding.


## What the installers and scripts touch

- `npx @passioncode-ai/fabric-agent-adapter` and `install.sh` write only
  `~/.agents/skills/<skill>`; `--target claude` writes `~/.claude/skills/<skill>` and is
  refused while the plugin is installed; `--prune-shadow` moves shadowing copies into
  `~/.claude/skills-shadow-backup/`.
- `building-fabric-services/scripts/check_service.py` reads a descriptor and the token
  file it names, talks only to `127.0.0.1:<port>`, and redeems one login code it asked
  for itself (creating one dashboard session). It never prints the token.
- The service kits create the service token (0600) and the instance lock in the
  service's own data directory, and write a launchd plist and a descriptor only when an
  installer calls them. The token is readable by any process of the same user; the
  protocol defends against web pages and mistakes, not against hostile local code.
