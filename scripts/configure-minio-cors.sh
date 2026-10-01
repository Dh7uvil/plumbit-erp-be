#!/usr/bin/env sh
# Recreate local MinIO with chat CORS origins (community MinIO uses MINIO_API_CORS_ALLOW_ORIGIN).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"

echo "Recreating MinIO so MINIO_API_CORS_ALLOW_ORIGIN from docker-compose.yml takes effect..."
docker compose -f "$ROOT/docker-compose.yml" up -d --force-recreate minio
docker compose -f "$ROOT/docker-compose.yml" run --rm minio-init
echo "Done. Presigned PUT uploads from the frontend should work against http://127.0.0.1:9000."
