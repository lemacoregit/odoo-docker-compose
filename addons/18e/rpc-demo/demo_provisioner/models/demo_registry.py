import secrets
import logging
import time
import threading
import psycopg2

import odoo
import xmlrpc.client
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, exceptions
from odoo.tools import config

_logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DEMO_USER_LOGIN = 'lema'
DEMO_USER_PASSWORD = 'demo12345'
PROVISION_TIMEOUT = 900     # seconds — max wall-clock for large module installs
TOKEN_EXPIRY_DAYS = 3
DOCKER_SOCKET = 'unix:///var/run/docker.sock'
# ─────────────────────────────────────────────────────────────────────────────


def _docker_client():
    """
    Return a docker.DockerClient connected via the host socket.
    Requires the docker Python package (docker==7.1.0 in requirements.txt)
    and /var/run/docker.sock mounted in this container.
    """
    try:
        import docker
        return docker.DockerClient(base_url=DOCKER_SOCKET, timeout=30)
    except ImportError:
        raise exceptions.UserError(
            'The "docker" Python package is not installed. '
            'Add docker==7.1.0 to etc/requirements.txt and restart the container.'
        )
    except Exception as exc:
        raise exceptions.UserError(
            f'Cannot connect to Docker socket: {exc}\n'
            'Make sure /var/run/docker.sock is mounted in this container.'
        )


def _exec(container, cmd, env=None, check=True):
    """
    Run a command inside a container and return (exit_code, output).
    Raises UserError when check=True and the command fails.
    """
    result = container.exec_run(
        cmd,
        stdout=True,
        stderr=True,
        environment=env or {},
        demux=False,
    )
    output = (result.output or b'').decode('utf-8', errors='replace')
    if check and result.exit_code != 0:
        raise exceptions.UserError(
            f'Command failed (exit {result.exit_code}): {" ".join(str(c) for c in cmd)}\n'
            f'{output[-2000:]}'
        )
    return result.exit_code, output


def _exec_stream(container, cmd, env=None):
    """
    Run a long-running command with streamed output.
    Returns (exit_code, full_output_str). Used for module installation.
    """
    import docker as docker_sdk
    client = docker_sdk.DockerClient(base_url=DOCKER_SOCKET, timeout=PROVISION_TIMEOUT)
    exec_id = client.api.exec_create(
        container.id, cmd,
        stdout=True, stderr=True,
        environment=env or {},
    )
    chunks = []
    for chunk in client.api.exec_start(exec_id['Id'], stream=True):
        chunks.append(chunk.decode('utf-8', errors='replace'))
    exit_code = client.api.exec_inspect(exec_id['Id']).get('ExitCode', 1)
    return exit_code, ''.join(chunks)


class DemoRegistry(models.Model):
    _name = 'demo.registry'
    _description = 'Demo Module Registry'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ── Fields ───────────────────────────────────────────────────────────────

    name = fields.Char(string='Display Name', required=True, tracking=True)
    server_id = fields.Many2one(
        comodel_name='demo.server',
        string='Demo Server',
        required=True,
        tracking=True,
        ondelete='restrict',
        help='Select the target demo server / Odoo version for this demo.',
    )
    module_name = fields.Char(
        string='Main Module Name',
        required=True,
        tracking=True,
        help='Module folder name in custom_addons, e.g.: lemacore_sale',
    )
    extra_modules = fields.Char(
        string='Extra Modules',
        help='Comma-separated, e.g.: sale,purchase,stock. Will be installed together.',
    )
    custom_addons_path = fields.Char(
        string='Custom Addons Paths',
        related='server_id.custom_addons_path',
        store=False,
        readonly=True,
        help='Comma-separated paths inside the demo container — synced from Demo Server.',
    )
    base_demo_url = fields.Char(
        string='Demo Base URL',
        related='server_id.base_demo_url',
        store=False,
        readonly=True,
        help='Public base URL — synced from Demo Server.',
    )
    demo_xmlrpc_url = fields.Char(
        string='Demo XML-RPC URL',
        related='server_id.demo_xmlrpc_url',
        store=False,
        readonly=True,
        help='Internal Docker URL for XML-RPC — always synced from Demo Server config.',
    )
    db_name = fields.Char(
        string='Database Name',
        readonly=True,
        compute='_compute_db_name',
        store=True,
    )
    token = fields.Char(string='Access Token', readonly=True, copy=False)
    token_expiry_days = fields.Integer(
        string='Token Validity (Days)',
        default=TOKEN_EXPIRY_DAYS,
        help='Number of days before the token expires (1–30).',
    )
    token_expiry = fields.Datetime(string='Token Expiry', readonly=True, copy=False)
    demo_url = fields.Char(
        string='Demo URL',
        readonly=True,
        compute='_compute_demo_url',
        store=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('provisioning', 'Processing'),
            ('active', 'Active'),
            ('error', 'Error'),
            ('deactivated', 'Deactivated'),
        ],
        default='draft',
        string='Status',
        tracking=True,
    )
    demo_user_login = fields.Char(string='Demo Login', default=DEMO_USER_LOGIN, readonly=True)
    demo_user_password = fields.Char(string='Demo Password', default=DEMO_USER_PASSWORD)
    demo_admin_login = fields.Char(string='Admin Login', default='admin')
    demo_admin_password = fields.Char(string='Admin Password', default='admin')
    with_demo = fields.Boolean(
        string='Include Demo Data',
        default=True,
        help='Install Odoo demo data alongside the module. Uncheck for a clean database without sample records.',
    )
    provision_log = fields.Text(string='Provisioning Log', readonly=True)
    last_reset = fields.Datetime(string='Last Reset', readonly=True)
    notes = fields.Text(string='Notes')
    backup_ids = fields.One2many('demo.backup', 'registry_id', string='Snapshots')

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('module_name', 'server_id.db_name_prefix')
    def _compute_db_name(self):
        for rec in self:
            if rec.module_name and rec.server_id.db_name_prefix:
                safe = rec.module_name.lower().replace('_', '').replace('-', '')
                rec.db_name = f'{rec.server_id.db_name_prefix}_{safe}'
            elif rec.module_name:
                safe = rec.module_name.lower().replace('_', '').replace('-', '')
                rec.db_name = f'lema_demo_{safe}'
            else:
                rec.db_name = False

    @api.depends('token', 'base_demo_url')
    def _compute_demo_url(self):
        for rec in self:
            if rec.token and rec.base_demo_url:
                rec.demo_url = f'{rec.base_demo_url}/demo/access?token={rec.token}'
            else:
                rec.demo_url = False

    # ── Constraints ──────────────────────────────────────────────────────────

    @api.constrains('token_expiry_days')
    def _check_token_expiry_days(self):
        for rec in self:
            if not (1 <= rec.token_expiry_days <= 30):
                raise exceptions.ValidationError('Token Validity must be between 1 and 30 days.')

    @api.constrains('module_name')
    def _check_module_name(self):
        for rec in self:
            if rec.module_name and not rec.module_name.replace('_', '').replace('-', '').isalnum():
                raise exceptions.ValidationError(
                    'Module name may only contain letters, numbers, underscores, and dashes.'
                )

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _get_container(self, client):
        """Return the docker container object for this registry's server."""
        self.ensure_one()
        try:
            return client.containers.get(self.server_id.container_name)
        except Exception:
            raise exceptions.UserError(
                f'Container "{self.server_id.container_name}" not found or not running. '
                'Make sure the demo service is up.'
            )

    def _get_pg_connection(self, dbname='postgres'):
        """Open a psycopg2 connection using the current Odoo config."""
        return psycopg2.connect(
            host=config.get('db_host', 'localhost'),
            port=int(config.get('db_port', 5432)),
            user=config.get('db_user', 'odoo'),
            password=config.get('db_password', ''),
            dbname=dbname,
            connect_timeout=10,
        )

    def _validate_module_exists(self, container):
        """Confirm the module folder exists in at least one configured addons path."""
        self.ensure_one()
        paths = [p.strip() for p in self.custom_addons_path.split(',') if p.strip()]
        for path in paths:
            code, _ = _exec(
                container,
                ['test', '-f', f'{path}/{self.module_name}/__manifest__.py'],
                check=False,
            )
            if code == 0:
                return
        checked = '\n'.join(f'  {p}/{self.module_name}/' for p in paths)
        raise exceptions.UserError(
            f'Module "{self.module_name}" was not found in any configured addons path:\n'
            f'{checked}\n'
            'Make sure the module folder exists inside the demo container.'
        )

    def _create_pg_database(self):
        """Create a fresh empty PostgreSQL database for this demo."""
        self.ensure_one()
        _logger.info('Creating database: %s', self.db_name)
        conn = self._get_pg_connection()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{self.db_name}"')
                cur.execute(
                    f'CREATE DATABASE "{self.db_name}" '
                    f'OWNER "{config.get("db_user", "odoo")}" '
                    f'ENCODING "UTF8" '
                    f'LC_COLLATE "en_US.UTF-8" '
                    f'LC_CTYPE "en_US.UTF-8" '
                    f'TEMPLATE template0'
                )
        finally:
            conn.close()

    def _install_modules_in_demo(self, container):
        """Install Odoo modules into the demo DB using streamed exec_run."""
        self.ensure_one()
        modules = self.module_name
        if self.extra_modules:
            extra = ','.join(m.strip() for m in self.extra_modules.split(',') if m.strip())
            modules += ',' + extra

        _logger.info('Installing [%s] on %s', modules, self.db_name)

        cmd = [
            'odoo',
            '-c', self.server_id.odoo_conf,
            '-d', self.db_name,
            '--db-filter', self.db_name,
            '--db_host', self.server_id.pg_host,
            '--db_port', str(self.server_id.pg_port),
            '--db_user', config.get('db_user', 'odoo'),
            '--db_password', config.get('db_password', ''),
            '-i', modules,
            '--without-demo', 'all' if not self.with_demo else 'False',
            '--stop-after-init',
            '--no-http',
        ]
        exit_code, output = _exec_stream(container, cmd)
        if exit_code != 0:
            raise exceptions.UserError(
                f'Module installation failed (exit {exit_code}):\n{output[-4000:]}'
            )
        return output

    def _wait_for_demo_server(self, max_wait=60):
        """Poll /web/health until the demo Odoo instance is ready. Raises on timeout."""
        import urllib.request
        url = f'{self.demo_xmlrpc_url}/web/health'
        for _ in range(max_wait // 2):
            try:
                urllib.request.urlopen(url, timeout=3)
                return True
            except Exception:
                time.sleep(2)
        raise exceptions.UserError(
            f'Demo server not reachable after {max_wait}s: {url}\n'
            'Check that the Demo XML-RPC URL uses the internal Docker port (e.g. :8069), '
            'not the external host port.'
        )

    def _create_demo_user(self):
        """Create or update the demo user on the freshly provisioned database."""
        self.ensure_one()
        _logger.info('Setting up demo user on %s', self.db_name)
        self._wait_for_demo_server()

        common = xmlrpc.client.ServerProxy(
            f'{self.demo_xmlrpc_url}/xmlrpc/2/common', allow_none=True,
        )
        obj = xmlrpc.client.ServerProxy(
            f'{self.demo_xmlrpc_url}/xmlrpc/2/object', allow_none=True,
        )

        # Initial auth with default 'admin' password (fresh install)
        admin_pw = 'admin'
        uid = common.authenticate(self.db_name, 'admin', admin_pw, {})
        if not uid:
            raise exceptions.UserError(
                f'Failed to authenticate as admin on {self.db_name}.'
            )

        # --- Update admin credentials ---
        new_login = self.demo_admin_login or 'admin'
        new_pw = self.demo_admin_password or 'admin'
        admin_ids = obj.execute_kw(
            self.db_name, uid, admin_pw, 'res.users', 'search',
            [[['login', '=', 'admin']]],
        )
        if admin_ids:
            obj.execute_kw(
                self.db_name, uid, admin_pw, 'res.users', 'write',
                [admin_ids, {'login': new_login, 'password': new_pw}],
            )
            # Re-authenticate with new credentials
            uid = common.authenticate(self.db_name, new_login, new_pw, {})
            if not uid:
                raise exceptions.UserError(
                    f'Re-authentication failed after updating admin on {self.db_name}.'
                )
            admin_pw = new_pw

        # --- Create or update demo user ---
        existing = obj.execute_kw(
            self.db_name, uid, admin_pw, 'res.users', 'search',
            [[['login', '=', self.demo_user_login]]],
        )
        if existing:
            obj.execute_kw(
                self.db_name, uid, admin_pw, 'res.users', 'write',
                [existing, {'password': self.demo_user_password, 'active': True}],
            )
        else:
            group_data = obj.execute_kw(
                self.db_name, uid, admin_pw, 'ir.model.data', 'search_read',
                [[['module', '=', 'base'], ['name', '=', 'group_user']]],
                {'fields': ['res_id'], 'limit': 1},
            )
            group_id = group_data[0]['res_id'] if group_data else False
            vals = {
                'name': 'Demo User',
                'login': self.demo_user_login,
                'password': self.demo_user_password,
                'sel_groups_1_10_11': 1,
            }
            if group_id:
                vals['groups_id'] = [(6, 0, [group_id])]
            obj.execute_kw(self.db_name, uid, admin_pw, 'res.users', 'create', [vals])
            _logger.info('Created demo user on %s', self.db_name)

    def _save_backup(self, container):
        """Create a clean-state pg_dump backup inside the demo container."""
        self.ensure_one()
        backup_dir = '/opt/demo/backups'
        backup_path = f'{backup_dir}/{self.module_name}.dump'

        _exec(container, ['mkdir', '-p', backup_dir])
        _exec(
            container,
            [
                'pg_dump',
                '-h', self.server_id.pg_host,
                '-p', str(self.server_id.pg_port),
                '-U', config.get('db_user', 'odoo'),
                '--format=custom', '--compress=6', '--no-owner',
                f'--file={backup_path}',
                self.db_name,
            ],
            env={'PGPASSWORD': config.get('db_password', ''), 'LANG': 'C'},
        )
        _logger.info('Backup saved: %s', backup_path)

    def _restore_backup(self, container):
        """Restore the demo database from the clean-state backup."""
        self.ensure_one()
        backup_path = f'/opt/demo/backups/{self.module_name}.dump'
        _exec(
            container,
            [
                'pg_restore',
                '-h', self.server_id.pg_host,
                '-p', str(self.server_id.pg_port),
                '-U', config.get('db_user', 'odoo'),
                '--dbname', self.db_name,
                '--no-owner',
                f'--role={config.get("db_user", "odoo")}',
                '--jobs=2',
                backup_path,
            ],
            env={'PGPASSWORD': config.get('db_password', ''), 'LANG': 'C'},
        )

    def _terminate_and_drop_db(self):
        """Terminate connections and drop the demo database."""
        self.ensure_one()
        conn = self._get_pg_connection()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                    'WHERE datname = %s AND pid <> pg_backend_pid()',
                    (self.db_name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{self.db_name}"')
        finally:
            conn.close()

    # ── Action Buttons ───────────────────────────────────────────────────────

    def button_provision(self):
        """Start async provisioning in a background thread. Returns immediately."""
        self.ensure_one()
        if self.state == 'active':
            raise exceptions.UserError(
                'Demo is already active. Use "Reset Demo" to reset it.'
            )
        if self.state == 'provisioning':
            raise exceptions.UserError('Provisioning is already in progress.')

        self.write({'state': 'provisioning', 'provision_log': '[INFO] Starting provisioning...\n'})
        self.env.cr.commit()

        record_id = self.id
        dbname = self.env.cr.dbname
        uid = self.env.uid

        def _background():
            with odoo.registry(dbname).cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                rec = env['demo.registry'].browse(record_id)

                def _log(msg):
                    rec.provision_log = (rec.provision_log or '') + msg + '\n'
                    rec.flush_recordset()
                    cr.commit()

                try:
                    client = _docker_client()
                    container = rec._get_container(client)

                    rec._validate_module_exists(container)
                    _log('[OK] Module found in demo container.')

                    rec._create_pg_database()
                    _log(f'[OK] Database "{rec.db_name}" created.')

                    _log('[INFO] Installing modules — this may take several minutes...')
                    install_log = rec._install_modules_in_demo(container)
                    _log('[OK] Modules installed successfully.')
                    _log('--- Install Log (tail) ---')
                    _log(install_log[-3000:])

                    rec._create_demo_user()
                    _log(f'[OK] Demo user "{rec.demo_user_login}" ready.')

                    rec._save_backup(container)
                    _log('[OK] Clean-state backup saved.')

                    token = secrets.token_urlsafe(40)
                    expiry = fields.Datetime.now() + relativedelta(days=rec.token_expiry_days)
                    rec.write({
                        'state': 'active',
                        'token': token,
                        'token_expiry': expiry,
                    })
                    rec.message_post(body=f'Demo provisioned. URL: {rec.demo_url}')
                    cr.commit()
                    _logger.info('Provisioning complete for %s', rec.db_name)

                except Exception as e:
                    _logger.exception('Background provisioning error for %s', rec.module_name)
                    try:
                        rec.write({
                            'state': 'error',
                            'provision_log': (rec.provision_log or '') + f'\n[ERROR] {e}',
                        })
                        cr.commit()
                    except Exception:
                        pass

        threading.Thread(target=_background, daemon=True).start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Provisioning Started',
                'message': 'Running in background. Refresh the page to monitor progress.',
                'type': 'info',
                'sticky': False,
            },
        }

    def button_reset(self):
        """Start async database reset from clean-state backup."""
        self.ensure_one()
        if self.state not in ('active', 'deactivated'):
            raise exceptions.UserError('Only active or deactivated demos can be reset.')

        client = _docker_client()
        container = self._get_container(client)
        backup_path = f'/opt/demo/backups/{self.module_name}.dump'

        code, _ = _exec(container, ['test', '-f', backup_path], check=False)
        if code != 0:
            raise exceptions.UserError(
                f'Backup not found: {backup_path}\n'
                'Re-provision the demo to create a new backup.'
            )

        self.write({'state': 'provisioning', 'provision_log': '[INFO] Starting reset...\n'})
        self.env.cr.commit()

        record_id = self.id
        dbname = self.env.cr.dbname
        uid = self.env.uid

        def _background():
            with odoo.registry(dbname).cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                rec = env['demo.registry'].browse(record_id)

                def _log(msg):
                    rec.provision_log = (rec.provision_log or '') + msg + '\n'
                    rec.flush_recordset()
                    cr.commit()

                try:
                    c = _docker_client()
                    cont = rec._get_container(c)

                    rec._terminate_and_drop_db()
                    _log(f'[OK] Old database "{rec.db_name}" dropped.')

                    conn = rec._get_pg_connection()
                    conn.autocommit = True
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                f'CREATE DATABASE "{rec.db_name}" '
                                f'OWNER "{config.get("db_user", "odoo")}"'
                            )
                    finally:
                        conn.close()
                    _log(f'[OK] Fresh database "{rec.db_name}" created.')

                    _log('[INFO] Restoring backup — this may take a few minutes...')
                    rec._restore_backup(cont)

                    new_token = secrets.token_urlsafe(40)
                    new_expiry = fields.Datetime.now() + relativedelta(days=rec.token_expiry_days)
                    rec.write({
                        'last_reset': fields.Datetime.now(),
                        'state': 'active',
                        'token': new_token,
                        'token_expiry': new_expiry,
                    })
                    rec.message_post(body='Demo reset to initial state. New token generated.')
                    cr.commit()
                    _log('[OK] Reset complete.')

                except Exception as e:
                    _logger.exception('Background reset error for %s', rec.module_name)
                    try:
                        rec.write({
                            'state': 'error',
                            'provision_log': (rec.provision_log or '') + f'\n[ERROR] {e}',
                        })
                        cr.commit()
                    except Exception:
                        pass

        threading.Thread(target=_background, daemon=True).start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reset Started',
                'message': 'Running in background. Refresh the page to monitor progress.',
                'type': 'info',
                'sticky': False,
            },
        }

    def button_regenerate_token(self):
        """Issue a new token, invalidating the previous demo URL."""
        self.ensure_one()
        if self.state not in ('active', 'deactivated'):
            raise exceptions.UserError('Only active or deactivated demos can regenerate a token.')

        new_token = secrets.token_urlsafe(40)
        new_expiry = fields.Datetime.now() + relativedelta(days=self.token_expiry_days)
        self.write({'token': new_token, 'token_expiry': new_expiry, 'state': 'active'})
        self.message_post(body='Token regenerated. The old demo URL is no longer valid.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'New Token Generated',
                'message': f'New URL: {self.demo_url}',
                'type': 'info',
                'sticky': True,
            },
        }

    def button_archive_demo(self):
        """Deactivate the demo and drop its database."""
        self.ensure_one()
        if self.db_name:
            try:
                self._terminate_and_drop_db()
                _logger.info('Database %s dropped.', self.db_name)
            except Exception as e:
                _logger.warning('Failed to drop database %s: %s', self.db_name, e)

        self.write({'state': 'deactivated', 'token': False, 'token_expiry': False, 'demo_url': False})
        self.message_post(body='Demo deactivated and database deleted.')

    def button_save_snapshot(self):
        """Save current database state as a named snapshot (.dump inside container)."""
        self.ensure_one()
        if self.state != 'active':
            raise exceptions.UserError('Only active demos can be snapshotted.')

        client = _docker_client()
        container = self._get_container(client)

        slug = fields.Datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = '/opt/demo/backups'
        backup_file = f'{backup_dir}/{self.db_name}_{slug}.dump'

        _exec(container, ['mkdir', '-p', backup_dir])
        _exec(
            container,
            [
                'pg_dump',
                '-h', config.get('db_host', 'postgres'),
                '-U', config.get('db_user', 'odoo'),
                '--format=custom', '--compress=6', '--no-owner',
                f'--file={backup_file}',
                self.db_name,
            ],
            env={'PGPASSWORD': config.get('db_password', ''), 'LANG': 'C'},
        )

        snap = self.env['demo.backup'].create({
            'name': f'Snapshot {fields.Datetime.now().strftime("%Y-%m-%d %H:%M")}',
            'registry_id': self.id,
            'backup_file': backup_file,
            'state': 'ready',
        })
        self.message_post(
            body=f'Snapshot saved: <b>{snap.name}</b> → <code>{backup_file}</code>'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Snapshot Saved',
                'message': f'Snapshot "{snap.name}" saved successfully.',
                'type': 'success',
            },
        }

    def button_download_backup(self):
        """Redirect to HTTP download endpoint — generates Odoo-compatible .zip on-the-fly."""
        self.ensure_one()
        if self.state != 'active':
            raise exceptions.UserError('Only active demos can be downloaded.')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/demo/backup/download/{self.id}',
            'target': 'self',
        }

    def button_set_to_draft(self):
        """Allow re-provisioning by resetting state to draft."""
        self.ensure_one()
        if self.state not in ('deactivated', 'error'):
            raise exceptions.UserError('Only deactivated or error demos can be set back to draft.')
        self.write({'state': 'draft'})
        self.message_post(body='Demo set back to draft.')

    def button_force_cancel(self):
        """
        Force-cancel a stuck provisioning or clean up after an error.
        Drops the partial database if it exists, then resets to draft.
        Safe to call even if the DB was never created.
        """
        self.ensure_one()
        if self.state not in ('provisioning', 'error'):
            raise exceptions.UserError('Force cancel is only available during provisioning or error state.')

        log_lines = [self.provision_log or '']
        log_lines.append('\n[WARN] Force cancel requested by user.')

        if self.db_name:
            try:
                self._terminate_and_drop_db()
                log_lines.append(f'[INFO] Partial database "{self.db_name}" dropped.')
                _logger.warning('Force cancel: dropped partial DB %s for %s', self.db_name, self.name)
            except Exception as e:
                log_lines.append(f'[INFO] Could not drop database (may not exist yet): {e}')

        self.write({
            'state': 'draft',
            'token': False,
            'token_expiry': False,
            'provision_log': '\n'.join(log_lines),
        })
        self.message_post(body='Provisioning force-cancelled. Record reset to Draft.')

    # ── Scheduled Action ────────────────────────────────────────────────────

    @api.model
    def _cron_auto_deactivate_expired(self):
        """Auto-deactivate active demos whose token has expired."""
        expired = self.search([
            ('state', '=', 'active'),
            ('token_expiry', '!=', False),
            ('token_expiry', '<', fields.Datetime.now()),
        ])
        for rec in expired:
            rec.write({'state': 'deactivated', 'token': False})
            rec.message_post(
                body=(
                    f'Demo automatically deactivated: token expired on '
                    f'{fields.Datetime.to_string(rec.token_expiry)}. '
                    f'Use "Reset" or "Regenerate Token" to reactivate.'
                )
            )
        if expired:
            _logger.info(
                'Auto-deactivated %d expired demo(s): %s',
                len(expired),
                ', '.join(expired.mapped('name')),
            )
