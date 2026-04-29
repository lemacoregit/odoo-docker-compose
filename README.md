# Odoo Docker Compose

Production-grade multi-instance Odoo 18 deployment using Docker Compose.

## Overview

Three isolated Odoo instances share a single PostgreSQL database server and Redis session store, managed through PgBouncer connection pooling.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Reverse Proxy / CDN                         │
└───────────┬─────────────────────┬──────────────────┬───────────────┘
            │                     │                  │
    ┌───────▼──────┐   ┌──────────▼──────┐  ┌───────▼──────────┐
    │  odoo-lema   │   │  odoo-demo18e   │  │  odoo-demo18c    │
    │  Production  │   │  Demo Enterp.   │  │  Demo Community  │
    │  Odoo 18 E   │   │  Odoo 18 E      │  │  Odoo 18 C       │
    │  4w + 2cron  │   │  4w, no cron    │  │  4w, no cron     │
    └──────┬───────┘   └────────┬────────┘  └────────┬─────────┘
           │                    │                     │
           └────────────────────┴─────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │       PgBouncer        │
                    │  Session pool · :6433  │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │     PostgreSQL 15      │
                    │      :5432             │
                    └───────────────────────┘

           ┌────────────────────────────────────┐
           │         Redis 8 (sessions)         │
           │   Shared · 512 MB · LRU · :6379    │
           └────────────────────────────────────┘
```

## Services

| Service | Image | Role | HTTP Port | Longpoll Port |
|---|---|---|---|---|
| `odoo-lema` | `mraldirs1231/odoo18e:latest` | Production ERP | `ODOO_LEMA_HTTP_PORT` | `ODOO_LEMA_LONGPOLLING_PORT` |
| `odoo-demo18e` | `mraldirs1231/odoo18e:latest` | Demo — Enterprise | `ODOO_DEMO18E_HTTP_PORT` | `ODOO_DEMO18E_LONGPOLLING_PORT` |
| `odoo-demo18c` | `odoo:18.0` | Demo — Community | `ODOO_DEMO18C_HTTP_PORT` | `ODOO_DEMO18C_LONGPOLLING_PORT` |
| `db` | `postgres:15` | Database server | `POSTGRES_PORT` | — |
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
make health-demo18e
make health-demo18c
```

## Directory Structure

```
odoo-docker-compose/
├── docker-compose.yml          # Service orchestration
├── .env.example                # Environment variable template
├── entrypoint.sh               # Container init script (wait-for-db, pip install)
├── Makefile                    # Developer shortcuts
├── addons/
│   ├── redis/
│   │   └── lm_session_redis/   # Redis-backed session store module
│   ├── 18e/
│   │   ├── bpass/              # Enterprise subscription bypass
│   │   ├── default/            # Shared Enterprise addons
│   │   ├── lema/               # Production-only addons
│   │   └── rpc-demo/           # Demo provisioner + token auth
│   └── 18c/
│       └── default/            # Community addons
├── etc/
│   ├── conf/                   # Odoo config files (see etc/conf/README.md)
│   ├── logs/                   # Log output (all services)
│   ├── filestore/              # File attachments (per-DB subdirectory)
│   ├── sessions/               # Filesystem sessions (unused — Redis is active)
│   ├── addons/                 # Extra addons writable mount
│   └── requirements.txt        # Extra Python packages installed at startup
└── github/
    ├── deploy.template.yml     # GitHub Actions CI/CD workflow
    └── script/
        └── upgrade_modules.py  # XML-RPC module upgrade utility
```

## Addon Paths

| Service | Addons mounted |
|---|---|
| `odoo-lema` | `redis`, `18e/bpass`, `18e/default`, `18e/rpc-demo`, `18e/lema` |
| `odoo-demo18e` | `redis`, `18e/bpass`, `18e/default`, `18e/rpc-demo`, `18e/demo/apps1`, `18e/demo/apps2` |
| `odoo-demo18c` | `redis`, `18e/rpc-demo`, `18c/default`, `18c/demo/apps1`, `18c/demo/apps2` |

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
make db-backup DB=lema_production
make db-restore DB=lema_production FILE=backups/lema_production_20250101.sql
make db-list

# Redis
make redis-cli
make redis-sessions

# Module upgrade
make upgrade MODULES=sale,purchase SERVICE=lema
make upgrade-dry MODULES=my_module SERVICE=demo18e
```

## CI/CD — GitHub Actions

The workflow file is at `github/deploy.template.yml`. Copy it to `.github/workflows/deploy.yml` in your repository.

**Deploy flow:**

```
push to main
    └─► detect-changes (scan git diff for __manifest__.py paths)
            ├─► deploy-lema      (git pull → restart → health check → module upgrade)
            └─► deploy-demo18e ──┐
                deploy-demo18c ──┘  (parallel, after lema, restart → health check → upgrade)
                    └─► notify  (email with per-service status)
```

**Manual dispatch inputs:**

| Input | Description |
|---|---|
| `force_modules` | Comma-separated modules to force-upgrade |
| `action` | `deploy` or `rollback` |
| `target` | `all` / `lema` / `demos` / `demo18e` / `demo18c` |

### Required GitHub Secrets / Variables

| Secret / Var | Description |
|---|---|
| `SSH_PRIVATE_KEY` | Private key for server SSH access |
| `SSH_HOST` | Server hostname or IP |
| `SSH_USER` | SSH username |
| `COMPOSE_PROJECT_PATH` | Path to this directory on the server |
| `ODOO_ADDONS_PATH` | Path to the git repository on the server |
| `ODOO_LEMA_URL` | Public URL of odoo-lema (e.g. `https://erp.lemacore.com`) |
| `ODOO_LEMA_DB` | Production database name (e.g. `lema_production`) |
| `ODOO_DEMO18E_URL` | Public URL of odoo-demo18e |
| `ODOO_DEMO18E_DB` | Demo Enterprise database name |
| `ODOO_DEMO18C_URL` | Public URL of odoo-demo18c |
| `ODOO_DEMO18C_DB` | Demo Community database name |
| `ODOO_LEMA_HTTP_PORT` | HTTP port of odoo-lema on the server |
| `ODOO_DEMO18E_HTTP_PORT` | HTTP port of odoo-demo18e on the server |
| `ODOO_DEMO18C_HTTP_PORT` | HTTP port of odoo-demo18c on the server |
| `ODOO_ADMIN_USER` | Odoo admin username for XML-RPC upgrade |
| `ODOO_ADMIN_PASSWORD` | Odoo admin password for XML-RPC upgrade |
| `EMAIL_RECIPIENTS` | Comma-separated notification recipients |
| `SMTP_SERVER` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP credentials |
| `EMAIL_FROM` | Sender address |

## Demo Provisioner

The `demo_provisioner` module (installed on `odoo-lema`) allows on-demand creation of isolated demo databases for any custom module. Each demo gets a unique token URL for passwordless access.

See [`addons/18e/rpc-demo/README.md`](addons/18e/rpc-demo/README.md) for full details.

## Security Notes

- All services run as `user: root` — required due to volume mount permissions. Consider fixing ownership in the Docker image for a hardened deployment.
- The `odoo-lema` container mounts `/var/run/docker.sock` to allow the demo provisioner to run `docker exec` commands. Restrict access to this container accordingly.
- Redis has `FLUSHALL`, `FLUSHDB`, `DEBUG`, and `SHUTDOWN` commands disabled.
- PgBouncer uses `SCRAM-SHA-256` authentication.

## Troubleshooting

**Container fails to start:**
```bash
make logs-lema        # check startup errors
make ps               # verify dependency services are healthy
```

**Module upgrade fails in CI:**
```bash
python3 github/script/upgrade_modules.py --help
make upgrade-dry MODULES=my_module SERVICE=lema   # test locally first
```

**Demo provisioning fails:**
```bash
# Verify docker socket is accessible inside the container
docker exec odoo-18-lema which docker
docker exec odoo-18-lema docker ps
```
