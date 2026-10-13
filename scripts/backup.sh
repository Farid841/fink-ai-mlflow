#!/bin/bash
# Backup of the MLflow stack: Postgres dump + mirror of the RustFS buckets.
# Usage: scripts/backup.sh [backup_dir]   (default: /opt/backups/mlflow)
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${1:-/opt/backups/mlflow}"
KEEP_DAYS=14

# .env is not sourced: some of its values contain unquoted spaces
env_get() { grep -E "^$1=" .env | cut -d= -f2- | tr -d '"' | xargs; }

mkdir -p "$BACKUP_DIR/postgres" "$BACKUP_DIR/rustfs"

# Postgres: one compressed dump per day, old ones are dropped
dump="$BACKUP_DIR/postgres/mlflow-$(date +%F).sql.gz"
docker compose exec -T postgres sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$dump.tmp"
mv "$dump.tmp" "$dump"
find "$BACKUP_DIR/postgres" -name 'mlflow-*.sql.gz' -mtime +"$KEEP_DAYS" -delete

# RustFS: incremental mirror. Objects deleted in RustFS are kept in the backup.
docker compose run --rm -T -v "$BACKUP_DIR/rustfs:/backup" --entrypoint /bin/sh rustfs-create-buckets -c "
  set -e
  mc alias set rustfs http://rustfs:$(env_get RUSTFS_PORT) '$(env_get RUSTFS_ACCESS_KEY)' '$(env_get RUSTFS_SECRET_KEY)' > /dev/null
  for bucket in $(env_get RUSTFS_BUCKET) $(env_get RUSTFS_BUCKET_DEV); do
    if mc stat rustfs/\$bucket > /dev/null 2>&1; then
      mc mirror --overwrite --quiet rustfs/\$bucket /backup/\$bucket
    else
      echo \"Bucket \$bucket does not exist, skipped\"
    fi
  done
"

echo "Backup done: $dump"
