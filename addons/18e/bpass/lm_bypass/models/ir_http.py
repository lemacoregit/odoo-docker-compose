from odoo import api, fields, models

class Http(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super(Http, self).session_info()
        result['warning'] = False
        result['expiration_date'] = False
        result['expiration_reason'] = False
        return result
