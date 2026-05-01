#!/bin/bash
# Ensures per-service Odoo roles exist with LOGIN + CREATEDB privileges.
# Safe to run on both fresh and existing databases — fully idempotent.
set -e

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:=postgres}"
: "${PG_HOST:=db}"

ROLES=(lema demo18e demo18c)

for ROLE in "${ROLES[@]}"; do
    EXISTS=$(psql -h "$PG_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'")

    if [ "$EXISTS" = "1" ]; then
        psql -h "$PG_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "ALTER ROLE \"$ROLE\" WITH LOGIN CREATEDB PASSWORD \$pw\$${POSTGRES_PASSWORD}\$pw\$;"
        echo "[db-init] Role '$ROLE' already exists — privileges ensured."
    else
        psql -h "$PG_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "CREATE ROLE \"$ROLE\" WITH LOGIN CREATEDB PASSWORD \$pw\$${POSTGRES_PASSWORD}\$pw\$;"
        echo "[db-init] Role '$ROLE' created."
    fi
done

echo "[db-init] All roles ready."
