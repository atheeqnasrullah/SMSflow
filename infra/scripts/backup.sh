#!/usr/bin/env bash
# Logical backup of the SMSFlow database (in addition to managed PITR backups in production).
# Usage: BACKUP_DIR=/backups ./infra/scripts/backup.sh
set -euo pipefail
BACKUP_DIR=${BACKUP_DIR:-./backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
docker compose exec -T postgres pg_dump -U smsflow -d smsflow -Fc > "$BACKUP_DIR/smsflow-$STAMP.dump"
# Encrypt at rest if a recipient is configured
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  gpg --batch --yes -r "$BACKUP_GPG_RECIPIENT" -e "$BACKUP_DIR/smsflow-$STAMP.dump" && rm "$BACKUP_DIR/smsflow-$STAMP.dump"
fi
find "$BACKUP_DIR" -name 'smsflow-*' -mtime +${RETENTION_DAYS:-14} -delete
echo "Backup written to $BACKUP_DIR (smsflow-$STAMP)"
