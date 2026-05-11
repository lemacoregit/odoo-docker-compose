from odoo import models, fields, api


class DemoServer(models.Model):
    _name = 'demo.server'
    _description = 'Demo Server Configuration'
    _order = 'name'

    name = fields.Char(
        string='Server Name',
        required=True,
        help='e.g.: Odoo 18 Demo Server',
    )
    odoo_version = fields.Char(
        string='Odoo Version',
        required=True,
        help='e.g.: 18.0',
    )
    container_name = fields.Char(
        string='Docker Container Name',
        required=True,
        help='Name of the Docker container running the demo Odoo instance. e.g.: odoo-demo18e',
    )
    odoo_conf = fields.Char(
        string='Odoo Config Path',
        required=True,
        default='/etc/odoo/odoo.conf',
        help='Path to odoo.conf inside the Docker container.',
    )
    base_demo_url = fields.Char(
        string='Demo Base URL',
        required=True,
        help='Public base URL of the demo server. e.g.: https://demo.lemacore.com',
    )
    demo_xmlrpc_url = fields.Char(
        string='Demo XML-RPC URL',
        required=True,
        help='Internal Docker URL for XML-RPC calls. e.g.: http://odoo-demo18e:8069',
    )
    db_name_prefix = fields.Char(
        string='Database Name Prefix',
        required=True,
        help=(
            'Prefix used when generating database names for provisioned demos. '
            'Must match the dbfilter pattern in odoo.conf. '
            'e.g.: lema_demo18e → generates lema_demo18e_sale, lema_demo18e_purchase'
        ),
    )
    custom_addons_path = fields.Char(
        string='Default Custom Addons Path',
        required=True,
        default='/mnt/extra-addons',
        help=(
            'Default comma-separated paths inside the container where custom modules are located. '
            'Can be overridden per demo registry. '
            'e.g.: /mnt/18e/demo-addons/apps1,/mnt/18e/demo-addons/apps2'
        ),
    )
    filestore_base = fields.Char(
        string='Filestore Base Path',
        default='/var/lib/odoo/filestore',
        help='Path to Odoo filestore directory inside the demo container. Used when generating .zip backups.',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    registry_count = fields.Integer(
        string='Demos',
        compute='_compute_registry_count',
    )

    def _compute_registry_count(self):
        counts_data = self.env['demo.registry'].read_group(
            [('server_id', 'in', self.ids)],
            ['server_id'],
            ['server_id'],
        )
        counts = {d['server_id'][0]: d['server_id_count'] for d in counts_data}
        for rec in self:
            rec.registry_count = counts.get(rec.id, 0)

    def action_view_registries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Demos — {self.name}',
            'res_model': 'demo.registry',
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }
