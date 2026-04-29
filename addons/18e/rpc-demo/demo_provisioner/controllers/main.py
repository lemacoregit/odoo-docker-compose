from odoo import http
from odoo.http import request


class DemoProvisionerController(http.Controller):

    @http.route('/demo/registry/status', type='json', auth='user')
    def registry_status(self, registry_id=None, **kwargs):
        """Endpoint for checking the status of a demo registry record. Expects a JSON request with 'registry_id'."""
        if not registry_id:
            return {'error': 'registry_id required'}

        record = request.env['demo.registry'].sudo().browse(int(registry_id))
        if not record.exists():
            return {'error': 'Record tidak ditemukan'}

        return {
            'state': record.state,
            'demo_url': record.demo_url,
            'provision_log': (record.provision_log or '')[-1000:],
        }
