#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${FZU_CHAT_COMPOSE_FILE:-docker-compose.prod.yml}"
VERSION="${FZU_CHAT_VERSION:-latest}"
WARN_THRESHOLD="${FZU_CHAT_DISK_WARN_THRESHOLD:-85}"
BLOCK_THRESHOLD="${FZU_CHAT_DISK_BLOCK_THRESHOLD:-90}"

cd "$ROOT_DIR"

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
  echo "Image pull failed; falling back to local build with docker-compose.yml." >&2
  docker compose -f docker-compose.yml build fzu-chat
  docker compose -f docker-compose.yml up -d --remove-orphans
fi

docker compose -f "$COMPOSE_FILE" ps
