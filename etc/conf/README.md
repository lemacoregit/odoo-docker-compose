# Configuration Files

Odoo and Redis configuration files for all services.

## Files

| File | Service | Description |
|---|---|---|
| `lema.conf` | `odoo-lema` | Production ERP — full workers, cron enabled |
| `18e.conf` | `odoo-demo18e` | Demo Enterprise — workers only, no cron |
| `18c.conf` | `odoo-demo18c` | Demo Community — workers only, no cron |
| `redis.conf` | `redis` | Session store — LRU eviction, no persistence, restricted commands |

---

## lema.conf — Production

```ini
workers = 4           # HTTP worker processes
max_cron_threads = 2  # background job threads (0 = disabled)
db_maxconn = 16       # max connections per worker to PgBouncer
```

**Worker capacity:**
- 4 workers × ~6 concurrent requests each = ~24 concurrent HTTP requests
- 2 cron threads handle scheduled actions (auto-backup, mail queue, etc.)
- Total connections to PgBouncer: `(4 + 2) × db_maxconn` — keep within PgBouncer `DEFAULT_POOL_SIZE`

**Memory limits:**

| Setting | Value | Purpose |
|---|---|---|
| `limit_memory_soft` | 2 GB | Worker restarts gracefully when exceeded |
| `limit_memory_hard` | 3 GB | Worker is killed immediately when exceeded |

**Timeout limits:**

| Setting | Value | Notes |
|---|---|---|
| `limit_time_cpu` | 600 s | CPU time per request before kill |
| `limit_time_real` | 1200 s | Wall-clock time per request |
| `limit_request` | 8192 | Max requests per worker before restart |

**`server_wide_modules`:** `base,web,lm_session_redis`

---

## 18e.conf — Demo Enterprise

Same structure as `lema.conf` with these differences:

| Setting | Value | Reason |
|---|---|---|
| `max_cron_threads` | `0` | Demo servers do not run scheduled actions |
| `limit_time_cpu` | `120 s` | Shorter — demos should not run long operations |
| `limit_time_real` | `600 s` | Shorter timeout |
| `dbfilter` | `^lema_demo18e` | Restricts access to databases with this prefix |
| `list_db` | `false` | Hides the database selector from the login page |

**`server_wide_modules`:** `base,web,lm_session_redis,demo_token_auth`

> `demo_token_auth` is loaded as a server-wide module so the `/demo/access` route is
> available even before a database is selected in the session.

---

## 18c.conf — Demo Community

Identical to `18e.conf` except:

| Setting | Value |
|---|---|
| `dbfilter` | `^lema_demo18c` |
| `logfile` | `/etc/odoo/logs/odoo-18c.log` |
| `addons_path` | Points to `18c/` instead of `18e/` paths |

---

## redis.conf — Session Store

Redis is used exclusively as a **session store** — no data persistence is enabled.

### Key settings

| Setting | Value | Reason |
|---|---|---|
| `maxmemory` | `512mb` | Hard cap for session data |
| `maxmemory-policy` | `allkeys-lru` | Evict least-recently-used sessions when full |
| `save ""` | (persistence disabled) | Sessions do not need to survive a Redis restart |
| `appendonly no` | | No AOF — session loss on restart is acceptable |

### Disabled commands

The following commands are blocked to prevent accidental or malicious data loss:

```
FLUSHALL  FLUSHDB  DEBUG  SHUTDOWN
```

### Connection sizing

```
3 Odoo services × (4 workers + 2 gevent) × 1 connection each = 18 connections
Add headroom for burst traffic → maxclients 50 (set via requirepass + maxmemory)
```

---

## dbfilter Alignment

The `dbfilter` in each demo conf must match the `db_name_prefix` configured on the corresponding `demo.server` record inside `odoo-lema`. If they diverge, the demo service will refuse connections to provisioned databases.

| Service | `dbfilter` | `DemoServer.db_name_prefix` | Example DB |
|---|---|---|---|
| `odoo-demo18e` | `^lema_demo18e` | `lema_demo18e` | `lema_demo18e_sale` |
| `odoo-demo18c` | `^lema_demo18c` | `lema_demo18c` | `lema_demo18c_purchase` |

> Pattern `^lema_demo18e` matches any database whose name **starts with** `lema_demo18e`,
> so both the base service database and all provisioned demo databases are accessible.

---

## Tuning Guide

### Increasing workers

Edit `workers` in the relevant `.conf` file, then restart the service:

```bash
make restart-lema
```

Calculate memory impact before increasing:
```
Required RAM ≈ (workers + max_cron_threads) × limit_memory_soft
```

For `workers=4, max_cron_threads=2`: `6 × 2 GB = 12 GB` worst-case.

### Adjusting timeouts for slow modules

If a specific module has long-running operations (e.g. report generation, data import):
- Increase `limit_time_real` to allow more wall-clock time
- Increase `limit_time_cpu` proportionally
- Consider dedicated workers or a separate Odoo instance for heavy jobs

### Redis memory pressure

If Redis logs `OOM command not allowed` errors, either:
1. Increase `maxmemory` in `redis.conf` (and update the Docker resource limit in `docker-compose.yml`)
2. Reduce `ODOO_SESSION_REDIS_EXPIRATION` in `.env` to expire sessions sooner
