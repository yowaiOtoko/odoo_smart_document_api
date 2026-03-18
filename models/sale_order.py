import logging
from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def create_quotation(self, header_vals, line_items):
        if not line_items:
            raise UserError('At least one line item is required.')
        resolver = self.env['invoice_api.product_resolver']
        name_cache = {}
        company_id = header_vals.get('company_id') or self.env.company.id
        lines_vals = []
        for item in line_items:
            resolved = resolver.resolve_line_item(item, name_cache, company_id)
            product = self.env['product.product'].browse(resolved['product_id'])
            line_vals = {
                'product_id': resolved['product_id'],
                'product_uom_qty': resolved.get('quantity', 1),
                'price_unit': resolved.get('price_unit') if resolved.get('price_unit') is not None else product.list_price,
            }
            if 'product_uom' in self.env['sale.order.line']._fields:
                line_vals['product_uom'] = resolved['uom_id']
            elif 'product_uom_id' in self.env['sale.order.line']._fields:
                line_vals['product_uom_id'] = resolved['uom_id']
            if resolved.get('discount') is not None:
                line_vals['discount'] = resolved['discount']
            if resolved.get('name') or resolved.get('description'):
                line_vals['name'] = resolved.get('name') or resolved.get('description')
            lines_vals.append((0, 0, line_vals))
        order_vals = {
            'partner_id': header_vals.get('partner_id'),
            'company_id': company_id,
            'order_line': lines_vals,
        }
        if header_vals.get('validity_date'):
            order_vals['validity_date'] = header_vals['validity_date']
        order = self.create(order_vals)
        _logger.info('Quotation created via API: order_id=%s name=%s', order.id, order.name)
        return {'id': order.id, 'name': order.name}
