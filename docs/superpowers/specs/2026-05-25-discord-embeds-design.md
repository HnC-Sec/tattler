# Discord Embed Reporting — Design

## Goal

Send Discord webhook notifications as rich embeds instead of plain `{"content": ...}` messages. Rules gain an optional `embed:` block whose fields default to useful values and may be overridden per-rule. A global `embed_author` setting controls the default embed author (defaulting to `"Tattler bot"`).

Generic webhooks are unchanged.

## Config schema

### Globals

```yaml
globals:
  embed_author: "Tattler bot"   # default; string only
```

`embed_author` defaults to `"Tattler bot"` when omitted.

### Per-rule `embed:` block

All string fields support the same template placeholders the existing `message` field uses (e.g. `{author}`, `{channel_name}`, `{message_link}`, …).

```yaml
rules:
  - name: name_mention
    pattern: "(?i)\\bjavert\\b"
    message: "{author} said {content}"   # see "Message vs embed.description" below
    webhooks: [alerts]
    embed:                                # optional
      title: "{rule_name}"               # default: rule name
      description: "{content}"            # default: rule's `message` template
      url: "{message_link}"               # default: message link
      author: "Tattler bot"               # default: globals.embed_author
      color: "#ff5555"                    # accepts "#rrggbb", "0xRRGGBB", or int
      footer: "from {guild_name}"         # no default
```

All embed fields are optional. Defaults are applied per-field when missing. Unknown keys are rejected (`extra="forbid"`).

### Color

Accepts:
- Hex string: `"#ff5555"` or `"#FF5555"`
- Hex string with `0x` prefix: `"0xFF5555"`
- Integer: `16734293`

Normalized to an integer at config-load time. Malformed values raise a `ValidationError`. No default — when absent, the embed has no color (Discord renders gray).

### Message vs `embed.description`

The top-level `message` field becomes optional, but a rule MUST provide at least one of:
- `message`, or
- `embed.description`

If both are present, `embed.description` is used as the embed description; `message` is then only used by `generic` webhooks. If only `message` is present, it serves as both the default embed description AND the generic webhook payload.

Rules with neither raise a `ValidationError` at load time.

## Architecture

### Models (`src/tattler/config/models.py`)

New `EmbedConfig` model:

```python
class EmbedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    description: str | None = None
    url: str | None = None
    author: str | None = None
    color: int | None = None        # normalized via field_validator
    footer: str | None = None
```

`GlobalConfig` gains `embed_author: str = "Tattler bot"`.

`RuleConfig`:
- `message: str | None = None`
- `embed: EmbedConfig | None = None`
- Model-level validator: `message or (embed and embed.description)` must be truthy.

### Formatter signature

All formatters share one signature:

```python
class WebhookFormatter(Protocol):
    def format(
        self,
        event: MatchEvent,
        rule: RuleConfig,
        globals: GlobalConfig,
    ) -> dict[str, Any]: ...
```

Each formatter renders the templates it needs. Rendering uses the existing `template.render()` (safe-formatter; missing placeholders render as empty string).

### `DiscordFormatter`

Builds `{"embeds": [embed]}`. For each embed field:

| Field | Default (when `embed` absent OR field absent) | Override |
|---|---|---|
| `title` | rule name | rendered template |
| `description` | rendered `rule.message` | rendered template |
| `url` | `event.message_link` | rendered template |
| `author.name` | `globals.embed_author` | rendered template |
| `color` | omitted | normalized int from `embed.color` |
| `footer.text` | omitted | rendered template |

Rules:
- All string overrides (`title`, `description`, `url`, `author`, `footer`) are run through the template engine, so any may reference `{author}`, `{channel_name}`, etc.
- Defaults are literal values (the rule name, the message link, the global author string) — no template rendering needed.
- When a rendered string is empty (`""`), omit that field from the payload. To suppress a default, set the field to `""`. `null` / unset means "use the default".

Payload shape (Discord embed):

```json
{
  "embeds": [
    {
      "title": "name_mention",
      "description": "alice said hi",
      "url": "https://discord.com/channels/.../...",
      "author": {"name": "Tattler bot"},
      "color": 16734293,
      "footer": {"text": "from my-server"}
    }
  ]
}
```

### `GenericFormatter`

Adopts the new signature. Renders `rule.message` if present; otherwise renders `embed.description` (since one of the two is guaranteed). Rest of the generic envelope is unchanged.

### Worker (`src/tattler/notifier/worker.py`)

No longer pre-renders `rendered_message`. Looks up the rule and globals from the current config (via `config_provider`) and hands `(event, rule, globals)` to whichever formatter the webhook uses. If the rule referenced by the event is no longer present in the current config (e.g. removed during hot-reload), the worker logs a warning and drops the event.

### Template engine

Unchanged. The existing `render()` handles each templated embed field individually.

## Tests

### `tests/unit/test_config_models.py`

- `embed` block parses with all fields; defaults applied.
- Color normalization: `"#ff5555"`, `"0xFF5555"`, `"#FF5555"`, and `16734293` all yield the same int.
- Malformed color raises `ValidationError`: `"red"`, `"#zzz"`, `"#fffffff"`, negative, > 0xFFFFFF.
- `message` may be omitted iff `embed.description` is set.
- Both missing → `ValidationError`.
- Unknown key inside `embed:` → `ValidationError`.
- `globals.embed_author` defaults to `"Tattler bot"` when omitted.

### `tests/unit/test_webhooks_discord.py`

- Defaults: with no `embed:` block, payload is `{"embeds":[{title: rule.name, description: rendered message, url: event.message_link, author: {name: "Tattler bot"}}]}`.
- Per-rule `embed_author` global override propagates to the default author.
- Per-rule overrides: each field independently overrides its default and is rendered with placeholders.
- Color renders as an integer in the payload.
- Empty rendered field is omitted from the payload (e.g. `url: ""` removes the URL).
- `footer` becomes `{"footer": {"text": "..."}}`.
- `color`-only override leaves all other defaults intact.

### `tests/unit/test_webhooks_generic.py`

- Generic payload uses `rule.message` when present.
- Generic payload falls back to rendered `embed.description` when `message` is absent.
- New formatter signature does not break existing envelope structure.

### `tests/unit/test_notifier_worker.py`

- Discord path produces `{"embeds": [...]}` end-to-end via the worker.
- Generic path unchanged.
- Worker resolves rule via `config_provider`; unknown rule (post hot-reload) is logged and dropped.

### Integration (`tests/integration/test_pipeline.py`)

- Update any pipeline-level assertions that currently expect `{"content": "..."}` for Discord webhooks; they now expect the embed structure.

### Example config

`config.example.yaml`: add `globals.embed_author` and show an `embed:` block (mix of defaulted and overridden fields). Update the comment block to document embed semantics.

## Out of scope

- Embed thumbnail, image, fields[], and timestamp override.
- Multiple embeds per message.
- Author `icon_url` / `url` (only `name` is supported in this iteration).
- Passing embed config through to generic webhooks.

All of these can be added later without breaking changes.
