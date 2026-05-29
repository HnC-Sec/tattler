# Invite Rules — Design

## Summary

Add a second kind of rule to tattler: invite rules. Tattler already observes
messages and matches them against regex `message` rules. This adds the ability
to detect Discord invite URLs in observed messages, resolve them via the
Discord API, and fire notifications based on structured properties of the
invite (target guild, member count, vanity flag, etc.) in addition to regex
matching against the resolved guild/channel/inviter names.

Rules in `config.yaml` gain a `type` field. `type: message` (default,
backwards-compatible) keeps existing behavior. `type: invite` opts a rule into
invite-driven matching.

## Goals

- Detect Discord invite codes posted in messages on any server the bot
  observes.
- Resolve each unique code via the Discord HTTP API (`GET /invites/{code}`
  with `with_counts=true` and `with_expiration=true`).
- Let rules match against the resolved invite metadata using both structured
  conditions (target guild ID, member count, vanity status, etc.) and a
  regex pattern over guild/channel/inviter names.
- Reuse the existing webhook, rate-limit, and embed plumbing — invite rules
  are first-class rules, not a parallel subsystem.
- Cache invite resolutions to keep API traffic low.
- Optionally fire rules for invites that fail to resolve (expired, deleted,
  or fake codes — useful for scam detection).

## Non-Goals

- Enumerating server-wide invite lists (`GET /channels/{id}/invites`,
  `GET /guilds/{id}/invites`). Only invites *posted in observed messages*
  are inspected.
- Reacting to invite-create / invite-delete gateway events.
- Persistent cache. The TTL cache is in-memory only and resets on restart.
- Acting on resolved invites (joining, kicking, deleting messages, etc.).
  Tattler remains observe-and-notify.

## Configuration

### Rule schema becomes a tagged union

`RuleConfig` becomes a discriminated union on the `type` field. The default
value is `"message"`, so every existing config remains valid without edits.

Common fields shared by both variants (unchanged from today):

- `name` — unique label.
- `include` / `exclude` — snowflake filters for **where the message was
  posted**. Same semantics as today; merged with `globals.include/exclude`.
- `rate_limit_seconds` — optional override of
  `globals.default_rate_limit_seconds`. Same per-(rule, channel) keying.
- `message` — optional template string. Either `message` or
  `embed.description` is still required.
- `webhooks` — required, list of named webhooks.
- `embed` — optional embed overrides (title, description, url, author,
  color, footer).

#### `type: message` (default)

Identical to today's `RuleConfig`. Required field: `pattern` (Python regex,
validated at load time).

#### `type: invite` (new)

```yaml
- name: scam_invite
  type: invite
  webhooks: [alerts]

  # Optional regex over "{guild_name}\n{channel_name}\n{inviter_name}" for
  # resolved invites, or over the bare invite code for unresolved invites
  # when match_unresolved is true. Validated at load time.
  pattern: "(?i)nitro|giveaway|free"

  # Target-guild snowflake filters. Both optional.
  #   - exclude wins over include.
  #   - empty include => any target guild allowed (subject to exclude).
  #   - skipped (treated as "no info") for unresolved invites.
  target_guild_include: []
  target_guild_exclude: [123456789012345678]

  # Numeric thresholds on approximate_member_count. Both optional.
  # If either is set and the invite is unresolved, the rule does not match
  # unless match_unresolved is true (in which case these are skipped).
  min_members: 0
  max_members: 50

  # Boolean flags. Each is optional; if set, the resolved invite must match.
  # `vanity` checks guild.vanity_url_code == code.
  # `has_expiry` checks whether expires_at is non-null.
  vanity: false
  has_expiry: true

  # Allow-list of verification levels. Empty / omitted => any level.
  # Values: "none" | "low" | "medium" | "high" | "highest".
  verification_level: [none, low]

  # If true, the rule also fires for invites that failed to resolve.
  # In that case the only conditions evaluated are:
  #   - common snowflake include/exclude (posting location)
  #   - pattern matched against the bare invite code string
  # Resolution-dependent conditions (target_guild_*, min/max_members,
  # vanity, has_expiry, verification_level) are skipped for unresolved
  # invites. The rule is rejected at load time if match_unresolved is true
  # AND no condition is set that can be evaluated on an unresolved invite.
  match_unresolved: false

  # Standard embed overrides; supports {invite_*} placeholders.
  embed:
    title: "Suspicious invite posted"
    description: |
      Author: {author}
      Target: {invite_guild_name} ({invite_member_count} members)
      Code: {invite_code}
```

All structured conditions are AND-ed together. A rule with no `pattern` and
no structured conditions is rejected at load time (would match every invite
— almost certainly a config mistake).

### New globals

```yaml
globals:
  invite_cache_ttl_seconds: 600      # default 10 min for resolved entries
  invite_cache_max_entries: 1024     # LRU bound
```

Unresolved sentinels are cached with a shorter TTL of
`min(invite_cache_ttl_seconds, 60)` to avoid hammering the API on bad codes
while still recovering from transient failures within a reasonable window.

### Validation

- Pydantic discriminator on `RuleConfig.type` selects the variant.
- `MessageRule` keeps the existing `pattern` regex validation.
- `InviteRule.pattern` is optional; when present, it's compiled at load time
  to surface errors early.
- `InviteRule.verification_level` values are checked against the allowed set.
- `InviteRule.min_members <= max_members` when both are set.
- `match_unresolved: true` requires at least one unresolved-safe condition
  (`pattern` or the rule's `include`/`exclude`).
- The existing "rule must define either `message` or `embed.description`"
  validator applies to both variants.
- `extra="forbid"` on both variants — unknown fields raise at load.

## Components

### `tattler/invites.py` (new)

```python
INVITE_RE: re.Pattern  # extracts invite codes from message text

def extract_invite_codes(text: str) -> list[str]:
    """Return de-duplicated invite codes in first-seen order."""

@dataclass(frozen=True)
class InviteView:
    code: str
    resolved: bool
    guild_id: int | None
    guild_name: str
    guild_features: tuple[str, ...]
    channel_id: int | None
    channel_name: str
    inviter_id: int | None
    inviter_name: str
    approximate_member_count: int | None
    approximate_presence_count: int | None
    expires_at: datetime | None
    is_vanity: bool
    verification_level: str   # "" when unresolved

class InviteResolver:
    def __init__(
        self,
        client: discord.Client,
        ttl_seconds: int = 600,
        max_entries: int = 1024,
    ) -> None: ...

    async def resolve(self, code: str) -> InviteView: ...
```

**Extraction regex** (case-sensitive on host, code charset matches Discord's):

```
(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/([a-zA-Z0-9-]+)
```

**Resolver behavior:**

- TTL cache keyed by code, LRU-trimmed at `max_entries`.
- Cache hit returns the stored `InviteView` directly.
- Cache miss calls `await client.fetch_invite(code, with_counts=True,
  with_expiration=True)` inside `asyncio.wait_for(..., timeout=5)`.
- On `discord.NotFound`, `discord.HTTPException`, `asyncio.TimeoutError`,
  or any other `Exception` (logged at `.exception` level), returns an
  unresolved `InviteView(code=code, resolved=False, ...)` with all other
  fields zero/empty/None.
- Unresolved sentinels are also cached, with TTL =
  `min(ttl_seconds, 60)`.
- `verification_level` is mapped from `discord.VerificationLevel` to the
  lowercase string set documented above.
- `is_vanity` = `True` iff the resolved invite's guild has
  `vanity_url_code == code`.
- Resolver is created from `Config.globals.invite_cache_*` and re-created
  on hot reload when those globals change.

### `tattler/matcher.py` (modified)

`Matcher.evaluate` becomes async and accepts an `InviteResolver`:

```python
async def evaluate(
    self,
    msg: MessageView,
    invite_resolver: InviteResolver,
) -> AsyncIterator[MatchEvent]:
```

Flow:

1. Compute `snowflakes`, global include/exclude, `searchable_text` (unchanged).
2. For each `MessageRule`: same logic as today; `yield` on match. No
   resolver use.
3. Determine which `InviteRule`s pass the common snowflake filter for this
   message. If none, return.
4. Cheap early-out: if `msg.content` contains none of `"discord.gg"`,
   `"discord.com/invite"`, `"discordapp.com/invite"`, return.
5. `codes = extract_invite_codes(msg.content)`.
6. For each code (sequential in v1), `view = await invite_resolver.resolve(code)`,
   then for each candidate invite rule, evaluate conditions in order:
   - `target_guild_include` / `target_guild_exclude` against `view.guild_id`
     (skipped if unresolved).
   - `min_members` / `max_members` against
     `view.approximate_member_count` (rule does not match if unresolved
     and `match_unresolved` is false; skipped if true).
   - `vanity` / `has_expiry` / `verification_level` (same unresolved
     rule).
   - `pattern` — if set, matched against
     `"{guild_name}\n{channel_name}\n{inviter_name}"` for resolved invites;
     matched against the bare code string when unresolved (only reachable
     when `match_unresolved: true`).
7. `yield MatchEvent(..., invite=view)` once per matching (rule, code).

### `tattler/events.py` (modified)

```python
@dataclass(frozen=True)
class MatchEvent:
    ...                       # existing fields unchanged
    invite: InviteView | None = None
```

### `tattler/notifier/template.py` (modified)

`_event_values` gains an `{invite_*}` family of placeholders, all rendering
to `""` when `event.invite is None` (mirrors existing safe-missing
behavior):

- `invite_code`
- `invite_resolved` ("True"/"False")
- `invite_guild_id`, `invite_guild_name`
- `invite_channel_id`, `invite_channel_name`
- `invite_inviter_id`, `invite_inviter_name`
- `invite_member_count` (approximate_member_count)
- `invite_presence_count` (approximate_presence_count)
- `invite_expires_at` (ISO 8601 or `""`)
- `invite_is_vanity` ("True"/"False")
- `invite_verification_level`

### `tattler/discord_client.py` (modified)

- `TattlerClient.__init__` constructs an `InviteResolver` using the current
  globals.
- `_handle` becomes:

  ```python
  matcher = Matcher(self._config_provider())
  async for event in matcher.evaluate(view, self._invite_resolver):
      await self._bus.publish(event)
  ```

- Hot reload: if globals' invite cache settings change, build a fresh
  `InviteResolver` (drops the cache; acceptable on reload).

## Data Flow

```
on_message / on_message_edit
        │
        ▼
_extract_view  ──► MessageView
        │
        ▼
Matcher.evaluate (async)
        │
        ├──► message rules: regex over searchable_text  ──► MatchEvent
        │
        └──► any invite rule passes posting-snowflake filter?
                  │
                  ▼ yes; "discord.gg" / "/invite/" in content?
                  │
                  ▼ yes
              extract_invite_codes
                  │
                  ▼ per code
              InviteResolver.resolve  ──► InviteView (cached or fetched)
                  │
                  ▼
              evaluate each candidate invite rule's conditions
                  │
                  ▼ pass
              MatchEvent(invite=view)
        │
        ▼
EventBus.publish → notifier worker → webhook
```

## Error Handling

- Extraction is regex-only; cannot fail.
- All `fetch_invite` failures are caught inside `InviteResolver.resolve`
  and converted to unresolved `InviteView`s. Logged at INFO with the
  failing code (no token / no PII).
- Resolver call has a 5-second `asyncio.wait_for` timeout so a slow Discord
  API does not block other message processing for long.
- An exception escaping the matcher invite branch is caught at the
  `_handle` level the same way the existing message-rule path is
  (`logger.exception` in `_handle`'s outer try). Invite-rule failure
  never affects message-rule processing for the same message.
- Config validation errors at load time follow today's behavior: invalid
  config is rejected; on hot reload, the previous valid config remains in
  effect.

## Backwards Compatibility

- Rules without `type` parse as `type: message` — every existing config
  works unchanged.
- `MatchEvent.invite` defaults to `None`; message-rule consumers (template
  renderer, webhook adapters) ignore it.
- Existing `{...}` template placeholders are unchanged. New `{invite_*}`
  placeholders render to `""` for message-rule events.

## Testing

Test files mirror the existing `tests/` layout.

1. **`tests/test_invite_extract.py`** — extraction regex coverage: URLs
   with/without scheme, `discord.gg`, `discord.com/invite`,
   `discordapp.com/invite`, query strings, duplicates dedup'd in order,
   no false positives on adjacent text.

2. **`tests/test_invite_resolver.py`** — fake `discord.Client` with stubbed
   `fetch_invite`. Cases: cache hit / miss, TTL expiry, LRU eviction,
   `NotFound` → unresolved, `HTTPException` → unresolved, timeout →
   unresolved, short-TTL caching of unresolved sentinels, `is_vanity`
   true when `guild.vanity_url_code == code`.

3. **`tests/test_matcher_invites.py`** — each condition (target
   include/exclude, min/max members, regex on names, vanity, has_expiry,
   verification_level) with hit and miss cases. Unresolved invite with
   `match_unresolved: true` and `false`. Multi-invite message → N events.
   Posting-location snowflake filter still applies. No invite-looking
   substring in content → resolver not called.

4. **`tests/test_config_invite_rules.py`** — tagged-union parsing (`type`
   omitted = message), invite rule with no `pattern` but with structured
   conditions is valid, rule with no conditions at all is rejected,
   `match_unresolved: true` with only resolution-dependent conditions is
   rejected, `min_members > max_members` is rejected, unknown
   `verification_level` value is rejected, embed/message defaults still
   required.

5. **`tests/test_template_invite.py`** — every `{invite_*}` placeholder
   renders correctly for a resolved invite, renders `""` for an unresolved
   invite where appropriate, renders `""` for message-rule events.

6. **`tests/test_integration_invites.py`** — end-to-end with an injected
   fake `InviteResolver`. Message arrives → invite extracted → resolver
   called → event published with `invite` populated → embed contains
   rendered `{invite_*}` fields.

## Docs

- `config.example.yaml` — new commented invite-rule example and the new
  `globals.invite_cache_*` knobs.
- `README.md` — template placeholder list expanded with the `{invite_*}`
  family; brief mention of the new rule type.

## Open Questions

None blocking for v1. Possible future extensions (out of scope here):

- Parallel resolution of multiple invites in one message via
  `asyncio.gather`.
- Reacting to gateway invite-create / invite-delete events.
- Enumerating server-wide invite lists for periodic auditing.
