# rpc-demo — Demo Provisioner & Token Auth

Two Odoo 18 modules that work together to provide **on-demand, isolated demo environments** for custom Odoo modules, accessible via a single token URL — no login required.

## Modules

| Module | Installed on | Purpose |
|---|---|---|
| `demo_provisioner` | `odoo-lema` (production) | Manage demo servers, provision databases, generate token URLs |
| `demo_token_auth` | `odoo-demo18e`, `odoo-demo18c` | Validate token, auto-login user, redirect to Odoo |

---

## How It Works

```
Admin (lema_production)          Demo Server           End User
─────────────────────────        ─────────────         ──────────────────
1. Create Demo Server record
   (container_name, db_prefix,
    xmlrpc_url, addons_path)

2. Create Demo Registry record
   (module_name, server_id,
    token_expiry_days)

3. Click "Provision"
   ├─ Validate module in container
   ├─ CREATE DATABASE lema_demo18e_<module>
   ├─ docker exec odoo -i <module> --stop-after-init
   ├─ Create demo user via XML-RPC
   ├─ pg_dump → /opt/demo/backups/<module>.dump
   └─ Generate token → build demo URL

                                                  4. User visits:
                                                     /demo/access?token=xxx
                                                         │
                                              5. Lookup token in
                                                 lema_production.demo_registry
                                                         │
                                              6. session.db = lema_demo18e_<module>
                                                 session.authenticate(demo_user)
                                                         │
                                              7. redirect /odoo  ──────────► ✅ Logged in
```

---

## Module: `demo_provisioner`

### Models

#### `demo.server` — Target server configuration

| Field | Type | Description |
|---|---|---|
| `name` | Char | Display name, e.g. `Odoo 18 Enterprise` |
| `odoo_version` | Char | e.g. `18.0` |
| `container_name` | Char | Docker container name, e.g. `odoo-18e-demo` |
| `odoo_conf` | Char | Config path inside container, e.g. `/etc/odoo/odoo.conf` |
| `db_name_prefix` | Char | DB prefix — **must match `dbfilter` pattern**, e.g. `lema_demo18e` |
| `base_demo_url` | Char | Public URL, e.g. `https://demo18e.lemacore.com` |
| `demo_xmlrpc_url` | Char | Internal Docker URL, e.g. `http://odoo-demo18e:8069` |
| `custom_addons_path` | Char | Comma-separated paths inside the container |

> **`db_name_prefix` is critical.** Generated database names follow the pattern `<db_name_prefix>_<safe_module_name>`. This must match the `dbfilter` in the demo server's `odoo.conf`:
>
> | Server | `db_name_prefix` | `dbfilter` in conf | Example DB |
> |---|---|---|---|
> | Enterprise 18 | `lema_demo18e` | `^lema_demo18e` | `lema_demo18e_sale` |
> | Community 18 | `lema_demo18c` | `^lema_demo18c` | `lema_demo18c_purchase` |

#### `demo.registry` — Per-module demo instance

| Field | Type | Description |
|---|---|---|
| `name` | Char | Display name |
| `server_id` | Many2one | Target demo server |
| `module_name` | Char | Main module folder name, e.g. `lemacore_sale` |
| `extra_modules` | Char | Additional modules to install, e.g. `sale,stock` |
| `custom_addons_path` | Char | Overrides server default |
| `db_name` | Char | Auto-computed: `<prefix>_<safe_module_name>` (read-only) |
| `demo_url` | Char | Full token URL (read-only, shown after provisioning) |
| `token` | Char | Secret access token (read-only) |
| `token_expiry_days` | Integer | Token validity (1–30 days) |
| `token_expiry` | Datetime | Computed expiry date |
| `state` | Selection | `draft → provisioning → active / error / deactivated` |
| `demo_user_login` | Char | Login for the demo user (default: `lema`) |
| `demo_user_password` | Char | Password for the demo user |
| `demo_admin_login` | Char | Admin login to set on provisioned DB |
| `demo_admin_password` | Char | Admin password to set on provisioned DB |
| `provision_log` | Text | Full provisioning output |

### Action Buttons

| Button | Available States | Description |
|---|---|---|
| **Provision** | `draft`, `error` | Full provisioning: DB + modules + user + backup + token |
| **Reset** | `active`, `deactivated` | Restore DB from clean-state backup, new token |
| **Regenerate Token** | `active`, `deactivated` | Invalidate old URL, issue new token |
| **Archive / Deactivate** | `active` | Drop DB, clear token, set deactivated |
| **Set to Draft** | `deactivated` | Allow re-provisioning |

### Scheduled Action

`Demo Provisioner: Auto-Deactivate Expired Demos` runs daily and deactivates any registry record whose `token_expiry` has passed.

### Requirements

- `/var/run/docker.sock` mounted in `odoo-lema` — already configured in `docker-compose.yml`.
- `/usr/bin/docker` mounted in `odoo-lema` — already configured in `docker-compose.yml` (fallback; not needed when using Python SDK).
- `docker==7.1.0` Python package in `etc/requirements.txt` — provisioner uses the **Docker Python SDK** (`docker-py`), not the CLI binary. No binary required.
- `pg_dump` / `pg_restore` must be available inside the **demo container** — included in all Odoo images.
- `psycopg2` is included in all Odoo 18 images.

---

## Module: `demo_token_auth`

### Environment Variable

| Variable | Default | Description |
|---|---|---|
| `DEMO_ERP_DB_NAME` | `lema_production` | Name of the production ERP database where `demo_provisioner` is installed. Set in `docker-compose.yml`. |

### Routes

#### `GET /demo/access?token=<token>`

Entry point for all demo URLs. Flow:
1. Validates token length (≥ 10 chars)
2. Queries `lema_production.demo_registry` via psycopg2 for the token
3. Verifies `state = 'active'`
4. Sets `request.session.db` to the demo's database
5. Authenticates the demo user
6. Redirects to `/odoo`

#### `GET /web/database`, `/web/database/selector`, `/web/database/manager`

Returns a blocked page — prevents end users from accessing the database manager on demo servers.

### Token Lookup Architecture

The token lookup uses a **direct psycopg2 connection** to `lema_production` (the production database). This is intentional:

- The route runs with `auth='none'` — no Odoo ORM session is available yet
- The lookup is a single read-only query with a 5-second timeout
- The session is set to `readonly=True, autocommit=True`

---

## Setup Checklist

### First-time setup after install

1. **On `odoo-lema`:** Go to *Demo Provisioner → Demo Servers* and create records for each demo service:

   ```
   Name:              Odoo 18 Enterprise Demo
   Odoo Version:      18.0
   Container Name:    odoo-18e-demo
   Odoo Conf:         /etc/odoo/odoo.conf
   DB Name Prefix:    lema_demo18e        ← must match dbfilter
   Base Demo URL:     https://demo18e.lemacore.com
   Demo XML-RPC URL:  http://odoo-demo18e:8069
   Custom Addons Path: /mnt/18e/demo-addons/apps1,/mnt/18e/demo-addons/apps2
   ```

2. **Provision a demo:**
   - Go to *Demo Provisioner → Demo Registry → New*
   - Select the server, enter the module name
   - Click **Provision**
   - Copy the generated **Demo URL** and share it

3. **Reset a demo** (e.g. after a client session):
   - Open the registry record → click **Reset**
   - A new token URL is generated

---

## Troubleshooting

**Provisioning fails: "docker Python package not installed"**
```bash
# Verify docker==7.1.0 is in etc/requirements.txt, then restart:
make restart-lema
docker exec odoo-18-lema python3 -c "import docker; print(docker.__version__)"
```

**Provisioning fails: "Cannot connect to Docker socket"**
```bash
# Verify socket is mounted and accessible:
docker exec odoo-18-lema ls -la /var/run/docker.sock
```

**Provisioning fails: "Module not found in demo container"**
- Check that the module folder exists at the configured `custom_addons_path` inside the demo container
- Verify the path is correctly mounted in `docker-compose.yml`

**Token validation fails / 400 error**
- Verify `DEMO_ERP_DB_NAME` env var matches the actual production database name
- Check PgBouncer is reachable from the demo container: `docker exec odoo-18e-demo pg_isready -h pgbouncer`
- Verify the `demo_registry` table exists in the production DB

**Demo URL returns wrong database**
- Check `db_name_prefix` on the Demo Server record
- Verify it matches the `dbfilter` pattern in the demo server's `odoo.conf`
- Example: prefix `lema_demo18e` → DB `lema_demo18e_mymodule` → must match `^lema_demo18e`
