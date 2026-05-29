#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STORAGE_DIR="${FZU_CHAT_STORAGE_DIR:-$ROOT_DIR/app/storage}"
BACKUP_DIR="${FZU_CHAT_BACKUP_DIR:-$ROOT_DIR/backups/sqlite}"
RETENTION_DAYS="${FZU_CHAT_BACKUP_RETENTION_DAYS:-14}"
PASSPHRASE="${FZU_CHAT_BACKUP_PASSPHRASE:-}"
PASSPHRASE_FILE="${FZU_CHAT_BACKUP_PASSPHRASE_FILE:-}"

if [[ -z "$PASSPHRASE" && -n "$PASSPHRASE_FILE" && -f "$PASSPHRASE_FILE" ]]; then
  PASSPHRASE="$(<"$PASSPHRASE_FILE")"
fi
if [[ -z "$PASSPHRASE" ]]; then
  echo "Set FZU_CHAT_BACKUP_PASSPHRASE or FZU_CHAT_BACKUP_PASSPHRASE_FILE before running backups." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

timestamp="$(date +%Y%m%d%H%M%S)"
manifest="$work_dir/MANIFEST.txt"
: > "$manifest"

shopt -s nullglob
for db in "$STORAGE_DIR"/*.sqlite; do
  name="$(basename "$db")"
  sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
  sqlite3 "$db" ".backup '$work_dir/$name'"
  sha256sum "$work_dir/$name" >> "$manifest"
done
shopt -u nullglob

archive="$BACKUP_DIR/fzu-chat-sqlite-$timestamp.tar.gz.enc"
tar -C "$work_dir" -czf - . \
  | openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:$PASSPHRASE" -out "$archive"

find "$BACKUP_DIR" -name 'fzu-chat-sqlite-*.tar.gz.enc' -mtime +"$RETENTION_DAYS" -delete
echo "$archive"
