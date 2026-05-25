# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

RUN groupadd -g 1000 tattler && useradd -u 1000 -g tattler -m -d /home/tattler tattler

WORKDIR /app
COPY --from=builder --chown=tattler:tattler /app /app

USER tattler

ENV TATTLER_CONFIG_PATH=/etc/tattler/config.yaml \
    TATTLER_LIVE_PATH=/tmp/tattler.live \
    TATTLER_READY_PATH=/tmp/tattler.ready \
    PATH=/app/.venv/bin:$PATH

ENTRYPOINT ["python", "-m", "tattler"]
