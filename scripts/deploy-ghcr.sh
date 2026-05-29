#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

COMPOSE_FILE="${FZU_CHAT_COMPOSE_FILE:-docker-compose.prod.yml}"
VERSION="${FZU_CHAT_VERSION:-latest}"
WARN_THRESHOLD="${FZU_CHAT_DISK_WARN_THRESHOLD:-85}"
BLOCK_THRESHOLD="${FZU_CHAT_DISK_BLOCK_THRESHOLD:-90}"

usage_percent="$(df -P . | awk 'NR==2 {gsub("%", "", $5); print $5}')"
if [[ -n "$usage_percent" && "$usage_percent" -ge "$BLOCK_THRESHOLD" ]]; then
  echo "Refusing deploy: disk usage is ${usage_percent}% (block threshold ${BLOCK_THRESHOLD}%)." >&2
  exit 1
fi
if [[ -n "$usage_percent" && "$usage_percent" -ge "$WARN_THRESHOLD" ]]; then
  echo "Warning: disk usage is ${usage_percent}% (warn threshold ${WARN_THRESHOLD}%)." >&2
fi

if [[ -z "${REDIS_PASSWORD:-}" ]]; then
  echo "REDIS_PASSWORD must be set for production deploy." >&2
  exit 1
fi

export FZU_CHAT_VERSION="$VERSION"

if docker compose -f "$COMPOSE_FILE" pull fzu-chat redis; then
  docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
else
  echo "Image pull failed; building the production image locally and using $COMPOSE_FILE." >&2
  docker build -t "ghcr.io/lyc280705/fzu-chat:${VERSION}" .
  docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
fi

docker compose -f "$COMPOSE_FILE" ps
