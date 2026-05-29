# Tattler

A Discord self-bot that observes messages in joined servers, matches them
against configured rules, and dispatches webhook notifications. Rules can
match either message text (`type: message`, regex) or Discord invite
metadata (`type: invite`, structured + regex).

> ⚠️ Self-bots violate Discord's Terms of Service. Use at your own risk.

## Quick start

Install deps and run tests:

    uv sync
    uv run pytest

Run locally against a config file:

    export TATTLER_DISCORD_TOKEN="..."
    export TATTLER_CONFIG_PATH="./config.yaml"
    uv run python -m tattler

## Configuration

See `docs/superpowers/specs/2026-05-25-tattler-design.md` for the base
config schema and `docs/superpowers/specs/2026-05-29-invite-rules-design.md`
for the invite-rule schema and template placeholders. `config.example.yaml`
contains commented examples of both rule types.

## Deployment

- Container image is built from the multi-stage `Dockerfile`.
- A Helm chart is provided in `helm/tattler/`.

Install with Helm:

    helm install tattler ./helm/tattler \
      --set image.tag=0.1.0 \
      --set existingSecret=tattler-token
