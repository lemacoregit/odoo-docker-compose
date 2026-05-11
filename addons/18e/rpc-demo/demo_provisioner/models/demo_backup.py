import logging
from odoo import models, fields, exceptions
from odoo.tools import config

_logger = logging.getLogger(__name__)


class DemoBackup(models.Model):
    _name = 'demo.backup'
    _description = 'Demo Database Snapshot'
    _order = 'create_date desc'

    name = fields.Char(string='Snapshot Name', required=True)
    registry_id = fields.Many2one(
        comodel_name='demo.registry',
        string='Demo Registry',
        required=True,
        ondelete='cascade',
    )
    backup_file = fields.Char(string='Backup File', readonly=True)
    note = fields.Text(string='Note')
    state = fields.Selection(
        selection=[('ready', 'Ready'), ('failed', 'Failed')],
        default='ready',
        string='Status',
        readonly=True,
    )

    def button_restore_snapshot(self):
        self.ensure_one()
        from .demo_registry import _docker_client, _exec

        registry = self.registry_id
        if registry.state not in ('active', 'deactivated'):
            raise exceptions.UserError(
                'Only active or deactivated demos can be restored from a snapshot.'
            )

        client = _docker_client()
        container = registry._get_container(client)

        code, _ = _exec(container, ['test', '-f', self.backup_file], check=False)
        if code != 0:
            raise exceptions.UserError(
                f'Snapshot file not found in container: {self.backup_file}\n'
                'The file may have been deleted manually.'
            )

        registry._terminate_and_drop_db()

        conn = registry._get_pg_connection()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f'CREATE DATABASE "{registry.db_name}" '
                    f'OWNER "{config.get("db_user", "odoo")}"'
                )
        finally:
            conn.close()

        _exec(
            container,
            [
                'pg_restore',
                '-h', config.get('db_host', 'postgres'),
                '-U', config.get('db_user', 'odoo'),
                '--dbname', registry.db_name,
                '--no-owner',
                f'--role={config.get("db_user", "odoo")}',
                '--jobs=2',
                self.backup_file,
            ],
            env={'PGPASSWORD': config.get('db_password', ''), 'LANG': 'C'},
        )

        registry.write({'last_reset': fields.Datetime.now()})
        registry.message_post(
            body=f'Database restored from snapshot: <b>{self.name}</b>'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Restore Successful',
                'message': f'Database restored from snapshot: {self.name}',
                'type': 'success',
            },
        }

    def button_delete_snapshot(self):
        self.ensure_one()
        from .demo_registry import _docker_client, _exec

        name = self.name
        client = _docker_client()
        container = self.registry_id._get_container(client)
        _exec(container, ['rm', '-f', self.backup_file], check=False)
        self.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Snapshot Deleted',
                'message': f'Snapshot "{name}" has been deleted.',
                'type': 'info',
            },
        }
