#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${FZU_CHAT_COMPOSE_FILE:-docker-compose.prod.yml}"
TARGET_VERSION="${1:-${FZU_CHAT_ROLLBACK_VERSION:-}}"

if [[ -z "$TARGET_VERSION" ]]; then
  echo "Usage: scripts/rollback.sh <tag-or-image-version>" >&2
  exit 1
fi
if [[ -z "${REDIS_PASSWORD:-}" ]]; then
  echo "REDIS_PASSWORD must be set for rollback." >&2
  exit 1
fi

cd "$ROOT_DIR"
export FZU_CHAT_VERSION="$TARGET_VERSION"

docker compose -f "$COMPOSE_FILE" pull fzu-chat
docker compose -f "$COMPOSE_FILE" up -d fzu-chat
docker compose -f "$COMPOSE_FILE" ps
