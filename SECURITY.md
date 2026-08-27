# Security

Report vulnerabilities privately to the maintainers of the `passioncode-ai`
organization. Do not open a public issue containing credentials, private provider URLs,
or customer project data.

The adapter must not write secret values to manifests, fixtures, probes, logs, or command
arguments. Generated and external provider outputs are untrusted. Live probes must be
bounded and non-publishing until explicit scoped grants exist in a project binding.

