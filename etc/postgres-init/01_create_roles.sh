#!/bin/bash
# Creates per-service Odoo roles on first DB initialization.
# Runs once (Docker entrypoint-initdb.d only executes when PGDATA is empty).
set -e

for ROLE in lema demo18e demo18c; do
    if psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1; then
        echo "Role '$ROLE' already exists — skipping."
    else
        psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "CREATE ROLE \"$ROLE\" WITH LOGIN PASSWORD \$pw\$${POSTGRES_PASSWORD}\$pw\$;"
        echo "Role '$ROLE' created."
    fi
done
