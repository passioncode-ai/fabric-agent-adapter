# Recipe: a key-delivery door

A door is the command a service's owner ships so an agent gets a key for one recipient without anybody seeing it: it
asks the issuer for the key and hands it on sealed. This template (FAA-238) asks once, prints the key as one
`fabric-credential-envelope/1` (contract DEC-0111, [credentials](https://github.com/passioncode-ai/fabric-agent-contract/blob/main/docs/specification/credentials.md#the-envelope))
on stdout, and **writes into no store**: the receiver writes the recipient's slot. Twins: `door.py` and `door.mjs`,
the same flags, exit codes and line. Tests: `test/test_recipe_key_delivery_door.py` (both twins, a fake issuer and a
test sealer that encrypts nothing).

It follows Project Observatory's V2 spec (*Receive a key from an external issue door*, sections 3.2 and 8, agreed on
board thread `e7fbd27d`) until Observatory's OBS-360 ships `receive`: the receiver is

```bash
python "$(project-observatory full-path)/tools/vault.py" receive PROJECT ENV NAME --from-command --json -- \
  python3 door.py --slot EXAMPLE_KEY --provider example-issuer --agent-ref urn:fabric:agent:example:example-agent \
    --recipient m-b#kem --context personal --issuer-command "example-issuer mint" --seal-command "example-sealer"
```

so the agent names the door and the slot and sees only the receiver's answer, never the key. A plan that says the door
"writes into the recipient's slot" is met this way: the slot is written, by the receiver that runs the door. When
OBS-360 lands with other names, the door's line and exit codes stay; only the command above changes.

## The two commands

The door owner supplies them; a value crosses only their stdin and stdout, in memory, and never argv, the environment,
a file or a log.

- `--issuer-command` reads the request on stdin (`{slot, provider, agentRef, context, requestId?}`: names only) and
  prints `{"value": "<key>", "credentialExpiresAt"?: "<RFC 3339>"}`, or `{"refused": {"code": "<slug>"}}`. Exit 75
  (`EX_TEMPFAIL`) is a transport failure; any other non-zero exit is a refusal.
- `--seal-command` reads `{"value", "header"}` (the header fields the door fixes: type, recipient, context, agentRef,
  slot, provider, and in an organization's context requestId and credentialExpiresAt) and prints the envelope: HPKE
  base mode suite `[16, 1, 1]` to the recipient's `#kem`, signed as DEC-0111 says (the contract's `sealCredential`; its
  sequence per `(context, agentRef, slot)` is the sealer's to keep). The standard library has no HPKE, so the template
  never seals by itself.

Before printing, the door checks the envelope against the schema's shape at the adapter's pin and against what it
asked for (the same slot, recipient, context, agentRef, provider and requestId; `exp` at most 24 hours after `iat`;
`credentialExpiresAt` at most 30 days, in an organization's context only), and refuses an envelope that carries the
value in clear. It decrypts and verifies nothing: that is the target's `checkCredentialEnvelope`. A child's stderr is
never forwarded, and the door's own messages never hold the value.

## Exit codes

As Observatory's `receive --from-command` maps them (V2 section 8, from the access agent's door):

| Exit | Means | Observatory reads |
|---|---|---|
| 0 | delivered: the envelope is the one line on stdout | the envelope |
| 2 | usage: a flag missing or out of shape (an organization's context needs `--request-id`, a personal one takes none) | `issuer-usage` |
| 3 | the issuer refused (its code, when it gave a slug) | `issuer-refused` |
| 4 | no key in the issuer's answer | `issuer-no-key` |
| 5 | the store refused: the sealer refused, or its envelope fails the checks above | `store-refused` |
| 1 | a transport failure that outlived its retries | `issuer-command-failed` |

Only a transport failure is retried: three tries in all, one and then two seconds apart. A refusal, a missing key and a
sealing failure are answered at once, since asking again would ask the issuer for a second key.
