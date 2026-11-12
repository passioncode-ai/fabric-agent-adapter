# A2A: serving a card and the binding, calling a peer

A service that other agents reach over the open A2A protocol (version 1.0, the contract's A2A peer profile) serves a
public Agent Card, answers A2A's JSON-RPC binding, and may call other A2A agents. The kit's module is
`fabric_a2a_server.py` with its Node twin `fabric-a2a-server.mjs` (FAA-10); `fabric_a2a.py` reads the card and the
well-known member (DEC-0122), and `check_service_a2a.py` holds the probe's A2A rules.

## The card

```python
from fabric_a2a import a2a_surface
from fabric_a2a_server import agent_card

card = agent_card(name="Example Agent", description="Drafts notes.", version="0.2.0",
                  url="http://127.0.0.1:47000/a2a/v1", capabilities=[{"name": "notes.draft", "description": "Drafts a note."}],
                  security_schemes={"own": {"apiKeySecurityScheme": {"location": "header", "name": "X-Example-Key"}}})
# serve card at GET /.well-known/agent-card.json, without the service token; declare it:
well_known["surfaces"]["a2a"] = a2a_surface()
```

- Each capability is one `AgentSkill`; its id is the capability's name, the id the provider manifest's A2A profile
  lists in `skillIds`.
- One interface: the JSON-RPC binding at `url`, `protocolVersion` 1.0. On a local placement the URL is on the service's
  loopback origin; on a remote one it is https.
- `agent_card` runs `agent_card_findings` before it returns, so a card that names a member about the running process,
  holds a value shaped like a credential, names the descriptor's token header as its scheme, or marks a Fabric
  extension required is never served.
- **The interface never takes the descriptor's token** (DEC-0122 item 3). It has its own scheme (an API key of its own,
  OAuth, or none on a loopback interface trusted under HA-3), and the service's `authorize` turns the request's headers
  into a caller.

## The binding

```python
from fabric_a2a_server import A2ABinding, agent_message, text_of

def handler(start):                      # a new message
    if text_of(start.message) == "ping":
        return agent_message("pong")     # a reply with no task
    start.start("notes.draft")           # or a task: a job in the interop job store
    run_in_background(start.task_id)     # the service moves the job: working, request_input, complete, fail

binding = A2ABinding(jobs, handler, skills=["notes.draft"], authorize=lambda headers: keys.get(headers.get("x-example-key")))
status, body = binding.handle(request_body_bytes, request_headers)   # POST /a2a/v1
```

| A2A 1.0 | The kit |
|---|---|
| `SendMessage` | the handler replies (`{message}`) or starts a job (`{task}`); a message with `taskId` answers an input-required task |
| `SendStreamingMessage` | `binding.stream(params, caller, rid=...)`: server-sent events, the task first, then a `statusUpdate` at each change, ending at a terminal or input-required state |
| `GetTask` | the job as a Task |
| `CancelTask` | `JobStore.cancel`; an ended task answers -32002 |
| task id | the job id; only the caller that started it reads, answers or cancels it (any other gets -32001) |
| `TASK_STATE_WORKING`, `_INPUT_REQUIRED`, `_COMPLETED`, `_FAILED`, `_CANCELED` | job `working`, `input_required`, `completed`, `failed`, `cancelled` |
| an input-required question | the job's elicitation requests in the status message's data part; the answer is a data part `{inputResponses}` as `fabric.job.get` takes it, or plain text for a question of one field |
| the result | the job's result envelope as the artifact `result`, one data part |
| a failure | the status message names the job's error message and its code in a data part |

JSON-RPC codes follow A2A 1.0 section 5.4: -32001 task not found, -32002 not cancelable, -32004 unsupported, -32009 an
`A2A-Version` header that is not 1.0; -32700, -32600, -32601 and -32602 are JSON-RPC's own. A caller `authorize`
refuses gets HTTP 401; a body over 1 MiB gets 413.

## Calling a peer

```python
from fabric_a2a_server import A2AClient

client = A2AClient(["https://peer.example"], credential_env="EXAMPLE_PEER_KEY")
peer = client.discover("https://peer.example")          # {card, url}
answer = client.call(peer["url"], "Draft a note about Monday.")
client.get(peer["url"], answer["task"]["id"]); client.cancel(peer["url"], answer["task"]["id"])
```

- **Only the operator's origins.** The client reaches an origin in its list, and the interface the card names must be
  on one too.
- **The key from the environment.** `credential_env` names a variable that `use_secret.py run --vault-only <project>
  <NAME> -- <command>` fills; the client never reads a key file beside the agent, and an error never carries the key.
- **Bounded.** Each call has a deadline (30 s) and a size cap (1 MiB) through `fabric_http`, follows no redirect and
  never retries a `SendMessage`. A plain `http://` URL is refused unless it is loopback (and then its listener must be
  this account's) or the client is built with `insecure=True`.

## The probe

`check_service_a2a.py <origin> [--key-env NAME] [--probe-text TEXT]` reads `surfaces.a2a`, the card, the interface and
the binding's refusals (`a2a.surface`, `a2a.card`, `a2a.interface`, `a2a.task-not-found`, `a2a.cancel-not-found`,
`a2a.method-not-found`); `a2a.task-states` runs only with a message the service names as safe to send, since any
message may start real work. An interface that answers 401 without `--key-env` makes the binding rows NOT_RUN.

It is a command of its own, not a part of `check_service.py`: that probe's `a2a.card` reads the public card with no
Authorization header and never calls the card's interfaces (D5), while this one calls the interface with the
interface's own key. Run both for a service that serves A2A.

## Not here yet

- The interop test against a live Hermes A2A endpoint (`a2a_discover`, `a2a_call`): it waits for a Hermes A2A endpoint
  reachable on this machine (FAA-10).
- The sample service serving both MCP and A2A, and `check_service.py` running these rows: the integrator wires them.
- The REST and gRPC bindings, push notifications and `ListTasks`.
