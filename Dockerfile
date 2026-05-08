# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install uv and curl for tdl binary
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps via uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Install tdl (Linux x86_64) - version pin via build arg
ARG TDL_VERSION=0.20.2
RUN set -eux; \
  curl -fsSL -o /tmp/tdl.tar.gz "https://github.com/iyear/tdl/releases/download/v${TDL_VERSION}/tdl_Linux_64bit.tar.gz"; \
  tar -xzf /tmp/tdl.tar.gz -C /usr/local/bin tdl; \
  chmod +x /usr/local/bin/tdl; \
  rm -f /tmp/tdl.tar.gz

# Copy app
COPY tdl_bot ./tdl_bot
COPY app.py ./app.py

# Runtime: mount config + downloads
ENV TDL_BOT_CONFIG=/app/tdl_bot_config.toml

CMD ["/app/.venv/bin/python", "app.py"]
