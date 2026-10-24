# Nemo architecture

Nemo is an always-on desktop companion: a small animated robot that lives on the
screen, wakes on hover or voice, and carries out tasks through an agent that
runs on open NVIDIA Nemotron models served by Nebius Token Factory.

## Design principles

1. **The agent core is product, the tools are plugins.** Everything the hackathon
   demo shows (clipboard help, repo security scan, web research) is a tool
   registered against a stable interface. New capabilities never touch the loop.
2. **Two execution sites.** Tools declare where they run:
   - `client` tools need the user's machine (clipboard, screenshot, open app,
     local files). The desktop app executes them.
   - `server` tools are heavy or need cloud compute (repo scan, web search).
     The service executes them, and long ones become Nebius Serverless Jobs.
3. **Safety is a layer, not a prompt.** Every tool has a risk level. The policy
   engine, not the model, decides whether a call needs the user's explicit
   confirmation. Destructive calls can never run silently.
4. **Models are tiers, not names.** The code asks for `fast`, `standard` or
   `deep`; env config maps tiers to concrete Token Factory model IDs. Swapping
   Nemotron versions, or a customer's own fine-tune, is a config change.
5. **Private by default.** Memory lives in a local SQLite file. Screen and
   clipboard content leaves the machine only when a tool call needs it.

## Components

```
apps/desktop (Electron + TypeScript)
  overlay window  transparent, always-on-top, click-through except on the robot
  robot           state machine: idle-wander, listening, thinking, acting, speaking
  voice           mic capture, VAD, speech-to-text, text-to-speech
  tool host       executes `client` tools on request from the service
        |
        |  WebSocket (JSON events, see protocol below)
        |
services/agent (Python, FastAPI)
  session         one per connection, owns the loop and pending confirmations
  loop            plan, call model, dispatch tools, stream events
  router          picks a model tier for each request
  tools           registry plus built-in tools
  safety          risk policy and confirmation gate
  memory          SQLite: conversation facts, user preferences, task history
  llm             OpenAI-compatible client pointed at Token Factory
```

## Protocol

Client to service:

| type | fields | meaning |
|---|---|---|
| `user_message` | `text` | user spoke or typed a request |
| `tool_result` | `id`, `ok`, `result` | answer to a `tool_request` |
| `confirm` | `id`, `approved` | answer to a `confirm_request` |

Service to client:

| type | fields | meaning |
|---|---|---|
| `state` | `state` | robot should show: thinking, acting, idle |
| `token` | `text` | streamed assistant text |
| `tool_request` | `id`, `name`, `args` | run this client tool and reply |
| `confirm_request` | `id`, `name`, `args`, `risk` | ask the user before proceeding |
| `final` | `text` | turn complete |
| `error` | `message` | something failed |

## Risk levels

| level | examples | policy |
|---|---|---|
| `read` | read clipboard, web search, scan repo | runs without asking |
| `write` | write clipboard, create a file | asks once per session per tool |
| `destructive` | delete, send, run a shell command | asks every time |

## Roadmap beyond the hackathon

- Plugin tools over MCP so third parties can add capabilities.
- Per-workspace policy files (what the agent may touch, which repos).
- Team mode: shared memory and audit log, admin-controlled policy.
- On-device small-model tier for offline wake-word and intent routing.
