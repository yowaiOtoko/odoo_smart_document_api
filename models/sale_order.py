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
        tax_field = 'tax_id' if 'tax_id' in self.env['sale.order.line']._fields else 'tax_ids'
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
            tax_ids = resolved.get('tax_ids') or []
            if tax_ids:
                clean_tax_ids = [int(t) for t in tax_ids if t]
                if clean_tax_ids:
                    line_vals[tax_field] = [(6, 0, clean_tax_ids)]
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

    @api.model
    def update_quotation(self, order_id, header_vals=None, add_line_items=None, update_line_items=None, remove_line_ids=None):
        order = self.browse(int(order_id)).exists()
        if not order:
            raise UserError(f'Quotation with id {order_id} not found.')

        resolver = self.env['invoice_api.product_resolver']
        name_cache = {}
        company_id = (header_vals or {}).get('company_id') or order.company_id.id or self.env.company.id
        tax_field = 'tax_id' if 'tax_id' in self.env['sale.order.line']._fields else 'tax_ids'

        write_vals = {}
        if header_vals:
            if header_vals.get('partner_id'):
                write_vals['partner_id'] = header_vals['partner_id']
            if header_vals.get('company_id'):
                write_vals['company_id'] = header_vals['company_id']
            if header_vals.get('validity_date'):
                write_vals['validity_date'] = header_vals['validity_date']
            if header_vals.get('date_order'):
                write_vals['date_order'] = header_vals['date_order']

        commands = []

        for item in (add_line_items or []):
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
            tax_ids = resolved.get('tax_ids') or []
            if tax_ids:
                clean_tax_ids = [int(t) for t in tax_ids if t]
                if clean_tax_ids:
                    line_vals[tax_field] = [(6, 0, clean_tax_ids)]
            commands.append((0, 0, line_vals))

        for item in (update_line_items or []):
            line_id = item.get('id')
            if not line_id:
                continue
            line = self.env['sale.order.line'].browse(int(line_id)).exists()
            if not line or line.order_id.id != order.id:
                raise UserError(f'Quotation line {line_id} not found for quotation {order.id}.')

            line_vals = {}
            if item.get('quantity') is not None:
                line_vals['product_uom_qty'] = item.get('quantity')
            if item.get('price_unit') is not None or item.get('price') is not None:
                line_vals['price_unit'] = item.get('price_unit') if item.get('price_unit') is not None else item.get('price')
            if item.get('discount') is not None:
                line_vals['discount'] = item.get('discount')
            if item.get('name') is not None or item.get('description') is not None:
                line_vals['name'] = item.get('name') or item.get('description')

            if (item.get('product_id') is not None and item.get('product_id') != '') or (item.get('product_name') is not None and item.get('product_name') != ''):
                resolved = resolver.resolve_line_item(item, name_cache, company_id)
                line_vals['product_id'] = resolved['product_id']
                if 'product_uom' in self.env['sale.order.line']._fields:
                    line_vals['product_uom'] = resolved['uom_id']
                elif 'product_uom_id' in self.env['sale.order.line']._fields:
                    line_vals['product_uom_id'] = resolved['uom_id']
                if resolved.get('price_unit') is not None:
                    line_vals['price_unit'] = resolved.get('price_unit')
                tax_ids = resolved.get('tax_ids') or []
                if tax_ids:
                    clean_tax_ids = [int(t) for t in tax_ids if t]
                    if clean_tax_ids:
                        line_vals[tax_field] = [(6, 0, clean_tax_ids)]

            if item.get('tax_ids') is not None:
                clean_tax_ids = [int(t) for t in (item.get('tax_ids') or []) if t]
                line_vals[tax_field] = [(6, 0, clean_tax_ids)] if clean_tax_ids else [(5, 0, 0)]

            if line_vals:
                commands.append((1, int(line_id), line_vals))

        for line_id in (remove_line_ids or []):
            if line_id:
                commands.append((2, int(line_id), 0))

        if commands:
            write_vals['order_line'] = commands

        if not write_vals:
            return {'id': order.id, 'name': order.name}

        order.write(write_vals)
        _logger.info('Quotation updated via API: order_id=%s name=%s', order.id, order.name)
        return {'id': order.id, 'name': order.name}
