from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    normalized_name = fields.Char(index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'name' in vals:
                vals['normalized_name'] = self._normalize(vals['name'])
        return super().create(vals_list)

    @staticmethod
    def _normalize(name):
        return ' '.join(name.lower().strip().split())
