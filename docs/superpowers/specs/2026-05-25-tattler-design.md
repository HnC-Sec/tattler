# Tattler — Design Spec

**Date:** 2026-05-25
**Status:** Approved (pending user review of written spec)

## Summary

Tattler is a Python application that connects to Discord as a self-bot, observes
every message sent in servers the account is in, evaluates messages against a
configurable set of regex rules, and dispatches webhook notifications when rules
match. The application is structured so that regex matching is one of potentially
many future event sources feeding a single notification subsystem.

**Operator-facing acknowledgement:** Using a user account as a self-bot violates
Discord's Terms of Service and risks account termination. This was an explicit
choice by the project owner.

## Goals

- Connect to Discord as a self-bot using a user token.
- Observe all messages (new + edited) in joined servers.
- Match messages against configured regex rules with snowflake-based scoping.
- Send formatted notifications to one or more named webhook destinations.
- Be deployable as a container in Kubernetes via a Helm chart.
- Make it easy to add new event sources later (matchers, schedulers, etc.) without
  changing the notification subsystem.

## Non-Goals

- No reply / interaction behavior on Discord (read-only observation).
- No metrics endpoint (Prometheus or otherwise).
- No HTTP API for runtime rule mutation.
- No persistent rate-limit state (in-memory only).
- No horizontal scaling — singleton deployment.
- No tests against a live Discord gateway.

## High-Level Architecture

```
┌────────────────────┐
│ discord.py-self    │  Discord gateway client (self-bot)
│ DiscordClient      │  Subscribes to on_message + on_message_edit
└─────────┬──────────┘
          │ Message objects
          ▼
┌────────────────────┐
│ Matcher            │  Iterates rules, evaluates regexes against
│                    │  content + embeds + attachments, applies
│                    │  global + per-rule include/exclude snowflake
│                    │  filters
└─────────┬──────────┘
          │ MatchEvent
          ▼
┌────────────────────┐
│ Event bus          │  asyncio.Queue
└─────────┬──────────┘
          │ Event
          ▼
┌────────────────────┐
│ Notifier worker    │  Consumes events, applies per-(rule, channel)
│                    │  rate limit, renders message template,
│                    │  dispatches to configured named webhook(s)
└─────────┬──────────┘
          │ HTTP POST (httpx)
          ▼
┌────────────────────┐
│ Webhook formatters │  generic (raw JSON) / discord (Discord
│                    │  webhook shape). Bounded retry w/ backoff.
└────────────────────┘

Side processes:
  - ConfigLoader: loads YAML, watches the file for changes,
    atomically swaps the live config object on validation success.
  - HealthFile manager: touches /tmp/tattler.live on each gateway
    heartbeat; touches /tmp/tattler.ready when gateway connected and
    config loaded. Used by Kubernetes exec probes.
```

### Why an internal event bus?

Matchers publish `MatchEvent`s onto an `asyncio.Queue`; the notifier worker
consumes them. This decouples event sources from delivery, so adding new event
sources later does not change the notifier, and a slow webhook never blocks the
Discord event loop.

## Module Layout

```
tattler/
├── pyproject.toml              # uv-managed
├── Dockerfile
├── helm/tattler/               # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── deployment.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── _helpers.tpl
├── src/tattler/
│   ├── __init__.py
│   ├── __main__.py             # entrypoint: load config, wire bus, start client
│   ├── config/
│   │   ├── models.py           # pydantic models for config schema
│   │   ├── loader.py           # load + validate YAML
│   │   └── watcher.py          # file-watch + hot reload
│   ├── events.py               # Event dataclasses (MatchEvent, etc.)
│   ├── bus.py                  # thin wrapper around asyncio.Queue
│   ├── discord_client.py       # discord.py-self client + handlers
│   ├── matcher.py              # rule evaluation, snowflake filtering
│   ├── notifier/
│   │   ├── worker.py           # queue consumer + rate limiter + dispatcher
│   │   ├── rate_limit.py       # in-memory per-(rule, channel) cooldown
│   │   ├── template.py         # placeholder rendering
│   │   └── webhooks/
│   │       ├── base.py         # WebhookFormatter protocol
│   │       ├── generic.py      # generic JSON formatter
│   │       └── discord.py      # Discord webhook formatter
│   └── health.py               # liveness/readiness file touches
└── tests/
    ├── unit/
    └── integration/
```

## Config Schema (YAML)

The discord token is **never** in this file. It is sourced from the
`TATTLER_DISCORD_TOKEN` environment variable. Startup fails fast if the variable
is unset.

```yaml
# Global filters: applied before any per-rule filter.
# Each list is a list of Discord snowflake IDs (guild/channel/user/role/etc.).
# Exclude takes precedence over include.
# Empty include = "everything allowed"; empty exclude = "nothing excluded".
globals:
  include: []
  exclude: []
  default_rate_limit_seconds: 30

# Named webhook destinations. Each rule references one or more by name.
webhooks:
  alerts:
    url: https://discord.com/api/webhooks/...
    format: discord                 # "discord" | "generic"
    timeout_seconds: 5
    retries: 3                      # bounded retry with exponential backoff
    backoff_base_seconds: 1.0       # delays: 1s, 2s, 4s (then drop)
  audit:
    url: https://my-service/ingest
    format: generic
    timeout_seconds: 5
    retries: 3
    backoff_base_seconds: 1.0

# Regex rules
rules:
  - name: profanity_check
    pattern: "(?i)\\b(badword1|badword2)\\b"
    include: []                     # snowflakes; merged with globals.include
    exclude: []                     # snowflakes; merged with globals.exclude
    rate_limit_seconds: 60          # optional; falls back to globals.default_rate_limit_seconds
    message: "Rule {rule_name} matched in #{channel_name} by {author}: {content}"
    webhooks: [alerts]              # required, non-empty list of names defined in `webhooks:` above
```

### Validation rules

The config loader rejects (at startup and on hot-reload) any of:

- A rule whose `webhooks` list is empty or references a name not defined in
  the top-level `webhooks:` map.
- A rule with an invalid regex `pattern`.
- A webhook with `format` not in `{discord, generic}`.
- A rule missing `name`, `pattern`, `message`, or `webhooks`.

Rule `name` values must be unique within the config.

### Template placeholders

Available in the `message` field of each rule:

| Placeholder | Meaning |
|---|---|
| `{rule_name}` | The rule's `name` |
| `{author}` | Display name of the message author |
| `{author_id}` | Snowflake of the author |
| `{channel_name}` | Channel name (or `DM` for DMs) |
| `{channel_id}` | Snowflake of the channel |
| `{guild_name}` | Guild name (or empty for DMs) |
| `{guild_id}` | Snowflake of the guild (or empty for DMs) |
| `{content}` | The raw message content |
| `{message_id}` | Snowflake of the message |
| `{message_link}` | URL to the message |
| `{timestamp}` | ISO 8601 timestamp of the message (creation or edit) |
| `{match}` | The full regex match |
| `{match_groups}` | Capture groups joined by `,` |
| `{is_edit}` | `true` if this fired from an edit event, else `false` |

Missing values render as the empty string. Template rendering never crashes.

### Filter semantics

For a given message, collect the message's associated snowflakes: guild ID,
channel ID, author ID, and author role IDs. Let:

- `effective_exclude = globals.exclude ∪ rule.exclude`
- `effective_include = globals.include ∪ rule.include`

The message passes the filter if and only if:

1. The intersection of the message's snowflakes with `effective_exclude` is empty.
2. **AND** either `effective_include` is empty, or the message has at least one
   snowflake in `effective_include`.

Exclude always wins over include.

## Data Flow & Key Behaviors

### Startup sequence

1. Read `TATTLER_DISCORD_TOKEN` from env. Fail fast if missing.
2. Load YAML config from `TATTLER_CONFIG_PATH` (default `/etc/tattler/config.yaml`).
3. Validate via pydantic models. Fail fast on validation errors.
4. Compile all regex patterns. Fail fast on invalid regex.
5. Construct the `asyncio.Queue` event bus.
6. Start the config file watcher task.
7. Start the notifier worker task.
8. Start the health-file heartbeat task.
9. Connect the discord.py-self client and run forever.

### Per-message flow

Triggered by both `on_message` and `on_message_edit`:

1. Build a `RawMessage` view: `content` plus all embed titles, descriptions, and
   field text plus all attachment filenames, concatenated into a single
   searchable text blob. Carry the message's snowflakes alongside.
2. Pass to `Matcher.evaluate(message)`.
3. For each rule:
   - Apply the combined include/exclude snowflake filter; skip on fail.
   - Run the compiled regex against the searchable blob; skip on no match.
   - Emit a `MatchEvent` onto the bus (one event per matching rule).
4. The Discord handler returns immediately — it never awaits webhook I/O.

### Notifier worker loop

1. `await bus.get()` → `MatchEvent`.
2. Check the rate limiter with key `(rule_name, channel_id)`. If the last fire
   for this key is within the rule's cooldown window, drop the event (log at
   DEBUG) and continue.
3. Stamp the rate limiter with the current time.
4. Render the rule's `message` template.
5. For each named webhook in the rule:
   - Look up the webhook config; format the payload according to its `format`.
   - POST via `httpx.AsyncClient` with `timeout_seconds`.
   - On failure (timeout, connection error, 5xx, 429): retry with exponential
     backoff (`backoff_base_seconds * 2^attempt`) up to `retries` times, then
     log at WARNING and drop.
   - On 2xx: log at INFO.
   - On non-429 4xx: log at WARNING; do not retry.

### Hot reload

The config watcher detects writes to the config file, then:

1. Load and validate the new config.
2. Compile new regexes.
3. On validation or compile failure: log at ERROR, keep the old config running.
4. On success: atomic swap of the live config reference. In-flight events keep
   their original rule references. New events see the new config. Rate-limiter
   state is preserved across reload (keyed by rule name).

### Shutdown

On SIGTERM:

1. Stop accepting new gateway events.
2. Drain the bus with a 10-second grace timeout.
3. Close the httpx client.
4. Disconnect the Discord client.
5. Remove the readiness file.

### Webhook payload formats

**`generic` format:**

```json
{
  "rule_name": "profanity_check",
  "message": "<rendered template>",
  "event": {
    "author": "...",
    "author_id": "...",
    "channel_name": "...",
    "channel_id": "...",
    "guild_name": "...",
    "guild_id": "...",
    "content": "...",
    "message_id": "...",
    "message_link": "...",
    "timestamp": "2026-05-25T14:23:00Z",
    "match": "...",
    "match_groups": ["..."],
    "is_edit": false
  }
}
```

**`discord` format:**

```json
{
  "content": "<rendered template>"
}
```

## Testing Strategy

Test framework: `pytest` + `pytest-asyncio`. HTTP mocking: `respx` or
`httpx.MockTransport`.

### Unit tests

- `test_config.py` — valid YAML loads; invalid regex rejected; unknown webhook
  name in a rule rejected; missing required fields rejected; defaults fill in
  correctly.
- `test_matcher.py` — pattern matches against content, embed text, attachment
  filenames; include/exclude snowflake logic (empty include = allow all; exclude
  wins over include; global ∪ per-rule merge); edits re-evaluate via the same
  path.
- `test_rate_limit.py` — first event passes, second within window dropped,
  event after window passes; per-(rule, channel) isolation; different channels
  for the same rule do not interfere.
- `test_template.py` — all placeholders render correctly; missing fields render
  as the empty string and do not raise.
- `test_webhooks_generic.py` / `test_webhooks_discord.py` — payload shape
  correctness; HTTP errors trigger retry with the configured backoff; retries
  exhausted result in drop + WARNING log.
- `test_health.py` — files touched on heartbeat; readiness file removed on
  shutdown.

### Integration test

`tests/integration/test_pipeline.py` — end-to-end without a real Discord
connection. Build a fake message dataclass with snowflakes + content, push it
through the `Matcher`, observe the `MatchEvent` on the bus, let the notifier
consume it, and assert the mocked HTTP endpoint received the expected payload.
Cover the happy path plus rate-limit suppression.

### Out of scope

- No tests against the real Discord gateway.
- No load or performance testing.

## Deployment

### Dockerfile (multi-stage)

- **Stage 1 (builder):** `python:3.12-slim` + `uv`. Copy `pyproject.toml` and
  `uv.lock`, run `uv sync --frozen --no-dev` into `/app/.venv`. Copy source.
- **Stage 2 (runtime):** `python:3.12-slim`. Copy `/app` from builder. Run as
  non-root (uid 1000). `WORKDIR /app`. `ENTRYPOINT ["/app/.venv/bin/python",
  "-m", "tattler"]`. Config mounted at `/etc/tattler/config.yaml` (overridable
  via `TATTLER_CONFIG_PATH`). Health files at `/tmp/tattler.live` and
  `/tmp/tattler.ready`.

### Helm chart (`helm/tattler/`)

- `Chart.yaml` — basic metadata. `appVersion` tracks the image tag.
- `values.yaml` — exposes:
  - `image.repository`, `image.tag`, `image.pullPolicy`
  - `discordToken` — rendered into a `Secret`; or `existingSecret` to reference
    one managed out-of-band.
  - `config` — the full tattler YAML config, inlined and rendered into a
    `ConfigMap`.
  - `resources` (requests/limits), `nodeSelector`, `tolerations`, `affinity`.
  - `replicaCount: 1`. Strategy is `Recreate` — Tattler is a singleton; adding
    replicas would multiply notifications.
- `templates/deployment.yaml`:
  - Mounts the ConfigMap at `/etc/tattler/config.yaml`.
  - Env: `TATTLER_DISCORD_TOKEN` from `secretKeyRef`.
  - **Liveness probe:** `exec` checking that `/tmp/tattler.live` has been
    modified within the last minute (e.g. `find /tmp/tattler.live -mmin -1 |
    grep .`). `initialDelaySeconds`, `periodSeconds`, `failureThreshold` are
    exposed via values.
  - **Readiness probe:** `exec stat /tmp/tattler.ready`.
  - SecurityContext: `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, with
    an `emptyDir` mount for `/tmp`.
- `templates/configmap.yaml`, `templates/secret.yaml`, `templates/_helpers.tpl`.

### Intentionally out of scope

- No HorizontalPodAutoscaler — singleton.
- No Service — no inbound traffic; health checks are exec probes.
- No ServiceMonitor — no metrics endpoint.
- No NetworkPolicy in the chart — left to the deploying cluster's conventions.

## Tooling

- **Dependency management:** `uv` with a committed `uv.lock`.
- **Test runner:** `pytest` (with `pytest-asyncio` for async tests).
- **HTTP client:** `httpx` (async).
- **Discord client:** `discord.py-self` (most actively maintained self-bot fork
  of `discord.py`).
- **Config validation:** `pydantic`.
- **File watching:** `watchfiles`.
- **Logging:** stdlib `logging`, plain-text format, configured at startup.

## Open Questions

None at spec time. All decisions captured above.
