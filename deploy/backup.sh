#!/usr/bin/env bash
# Бэкап базы без остановки бота (SQLite online backup).
# В cron: 0 4 * * * /opt/shopbot/deploy/backup.sh >> /var/log/shopbot-backup.log 2>&1

set -euo pipefail

DB="${DB_PATH:-/opt/shopbot/shop.db}"
DEST="${BACKUP_DIR:-/opt/shopbot/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M%S)
sqlite3 "$DB" ".backup '$DEST/shop-$STAMP.db'"
gzip -f "$DEST/shop-$STAMP.db"
find "$DEST" -name 'shop-*.db.gz' -mtime "+$KEEP_DAYS" -delete
echo "$(date -Is) backup ok: $DEST/shop-$STAMP.db.gz"
