#!/usr/bin/env bash
# Restore a pg_dump custom-format backup. DESTRUCTIVE: replaces the current database contents.
# Usage: ./infra/scripts/restore.sh backups/smsflow-20260101T000000Z.dump
set -euo pipefail
FILE=${1:?usage: restore.sh <dump-file>}
read -r -p "This will overwrite the 'smsflow' database. Type 'restore' to continue: " ok
[[ "$ok" == "restore" ]] || { echo "aborted"; exit 1; }
docker compose stop api worker-send worker-default beat
docker compose exec -T postgres pg_restore -U smsflow -d smsflow --clean --if-exists --no-owner < "$FILE"
docker compose start api worker-send worker-default beat
echo "Restore complete. Run a wallet reconciliation: docker compose exec api python -c \"import asyncio; from app.modules.wallet.tasks import reconcile_all; asyncio.run(reconcile_all())\""
