# Odoo Docker Compose

Single-instance Odoo 19 deployment using Docker Compose, with PgBouncer connection pooling and a Redis-backed session store.

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Reverse Proxy / CDN                         │
└───────────────────────────────┬───────────────────────────────────┘
                                 │
                       ┌─────────▼─────────┐
                       │     odoo-lema      │
                       │  Odoo 19 · 4w+2cron│
                       └─────────┬─────────┘
                                 │
                       ┌─────────▼─────────┐
                       │      PgBouncer      │
                       │  Session pool ·:8613│
                       └─────────┬─────────┘
                                 │
                       ┌─────────▼─────────┐
                       │    PostgreSQL 16    │
                       │       :5432         │
                       └───────────────────┘

                       ┌───────────────────┐
                       │   Redis 8 (sessions) │
                       │  512 MB · LRU · :6379 │
                       └───────────────────┘
```

## Services

| Service | Image | Role | HTTP Port | Longpoll Port |
|---|---|---|---|---|
| `odoo-lema` | built from `Dockerfile` (base: `mraldirs1231/lemaerp19e:19.0.2`) | Odoo 19 application server | `ODOO_LEMA_HTTP_PORT` | `ODOO_LEMA_LONGPOLLING_PORT` |
| `db` | `postgres:16` | Database server | `POSTGRES_PORT` | — |
| `pgbouncer` | `edoburu/pgbouncer:latest` | Connection pool | `PG_BOUNCER_PORT` | — |
| `redis` | `redis:8.2.5` | Session store | `REDIS_EXTERNAL_PORT` | — |

## Quick Start

### 1. Configure environment

```bash
make setup        # copies .env.example → .env
# Edit .env with your passwords and ports
make validate-env # verify all required variables are set
```

### 2. Start all services

```bash
make up
make ps   # check service status
```

### 3. Check health

```bash
make health-lema
```

## Directory Structure

```
odoo-docker-compose/
├── docker-compose.yml          # Service orchestration
├── Dockerfile                  # odoo-lema image build
├── .env.example                # Environment variable template
├── entrypoint.sh               # Container init script (wait-for-db)
├── Makefile                    # Developer shortcuts
├── addons/
│   └── apps/                   # Custom addons mounted at /mnt/apps-addons
│       ├── lm_bypass/
│       ├── lm_session_redis/   # Redis-backed session store module
│       └── lm_web/
├── etc/
│   ├── conf/
│   │   ├── odoo.conf           # Odoo configuration (addons_path, workers, limits)
│   │   └── redis.conf          # Redis configuration (persistence, security)
│   └── requirements.txt        # Extra Python packages installed at build time
└── .claude/
    └── settings.json
```

Directories referenced in `docker-compose.yml` but not present in the repository (`addons/default`, `addons/custom`, `etc/logs`, `etc/filestore`, `etc/sessions`, `etc/addons`, `etc/postgres`) are created automatically by Docker as empty bind mounts on first `up`. They map to Odoo's internal `data_dir` (`/etc/odoo`) and to the additional addon paths declared in `odoo.conf`.

## Addon Paths

`odoo.conf` declares:

```
addons_path = /mnt/apps-addons, /mnt/default-addons, /mnt/custom-addons
```

| Container path | Host source | Status |
|---|---|---|
| `/mnt/apps-addons` | `./addons/apps` | populated (`lm_bypass`, `lm_session_redis`, `lm_web`) |
| `/mnt/default-addons` | `./addons/default` | empty, reserved for shared addons |
| `/mnt/custom-addons` | `./addons/custom` | empty, reserved for custom addons |

`/etc/odoo/addons` (mounted from `./etc/addons`) is separate from the paths above — it is Odoo's own `data_dir` addons folder, used when Odoo installs/writes modules dynamically at runtime rather than addons placed manually via `addons_path`.

## Makefile Reference

```bash
make help          # full command list

# Services
make up / down / restart / ps
make start-lema    # individual service
make logs-lema     # tail logs
make shell-lema    # bash inside container
make health-lema   # check /web/health

# Database
make db-backup DB=<name>
make db-restore DB=<name> FILE=backups/<name>.sql
make db-list

# Redis
make redis-cli
make redis-sessions

# Module upgrade
make upgrade MODULES=sale,purchase SERVICE=lema
make upgrade-dry MODULES=my_module SERVICE=lema
```

## Security Notes

- The `odoo-lema` container mounts `/var/run/docker.sock` and `/usr/bin/docker`. Restrict access to this container accordingly, as it grants effective control over the Docker host.
- Redis has `FLUSHALL`, `FLUSHDB`, `DEBUG`, and `SHUTDOWN` commands disabled.
- PgBouncer uses `SCRAM-SHA-256` authentication.
- `db`, `pgbouncer`, and `redis` ports are published to the host; restrict these at the firewall/network level if external access is not required.

## Troubleshooting

**Container fails to start:**
```bash
make logs-lema        # check startup errors
make ps               # verify dependency services are healthy
```

**Module upgrade fails:**
```bash
make upgrade-dry MODULES=my_module SERVICE=lema   # test locally first
```
