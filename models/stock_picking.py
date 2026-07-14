import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _delivery_api_picking_type_id(self, company_id):
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('warehouse_id.company_id', '=', int(company_id)),
        ], limit=1)

        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'outgoing')
            ], limit=1)

        if not picking_type:
            raise UserError('No outgoing picking type found.')

        return picking_type.id

    @api.model
    def create_delivery(self, header_vals, line_items):
        if not line_items:
            raise UserError('At least one line item is required.')

        company_id = header_vals.get('company_id') or self.env.company.id
        partner_id = header_vals.get('partner_id')
        if not partner_id:
            raise UserError('partner_id is required.')

        resolver = self.env['invoice_api.product_resolver']
        name_cache = {}

        picking_type_id = self._delivery_api_picking_type_id(company_id)
        picking_type = self.env['stock.picking.type'].browse(picking_type_id)

        move_vals = []
        for item in line_items:
            resolved = resolver.resolve_line_item(item, name_cache, company_id)
            quantity = float(resolved.get('quantity') or 1)

            line = {
                'description_picking': resolved.get('name') or resolved.get('description') or item.get('product_name') or 'Product',
                'product_id': resolved['product_id'],
                'quantity': quantity,
                'product_uom': resolved['uom_id'],
                'location_id': header_vals.get('location_id') or picking_type.default_location_src_id.id,
                'location_dest_id': header_vals.get('location_dest_id') or picking_type.default_location_dest_id.id,
            }
            move_vals.append((0, 0, line))

        picking_vals = {
            'partner_id': int(partner_id),
            'company_id': int(company_id),
            'picking_type_id': picking_type_id,
            'origin': header_vals.get('origin'),
            'scheduled_date': header_vals.get('scheduled_date'),
            'location_id': header_vals.get('location_id') or picking_type.default_location_src_id.id,
            'location_dest_id': header_vals.get('location_dest_id') or picking_type.default_location_dest_id.id,
            'move_ids': move_vals,
        }

        if not picking_vals.get('origin'):
            picking_vals.pop('origin', None)
        if not picking_vals.get('scheduled_date'):
            picking_vals.pop('scheduled_date', None)

        picking = self.create(picking_vals)
        _logger.info('Delivery slip created via API: picking_id=%s name=%s', picking.id, picking.name)
        return {'id': picking.id, 'name': picking.name}

    @api.model
    def update_delivery(self, picking_id, header_vals=None, add_line_items=None, update_line_items=None, remove_line_ids=None):
        picking = self.browse(int(picking_id)).exists()
        if not picking:
            raise UserError(f'Delivery slip with id {picking_id} not found.')

        resolver = self.env['invoice_api.product_resolver']
        name_cache = {}
        company_id = (header_vals or {}).get('company_id') or picking.company_id.id or self.env.company.id

        write_vals = {}
        if header_vals:
            if header_vals.get('partner_id'):
                write_vals['partner_id'] = header_vals['partner_id']
            if header_vals.get('scheduled_date'):
                write_vals['scheduled_date'] = header_vals['scheduled_date']
            if header_vals.get('origin') is not None:
                write_vals['origin'] = header_vals.get('origin')

        commands = []

        for item in (add_line_items or []):
            resolved = resolver.resolve_line_item(item, name_cache, company_id)
            quantity = float(resolved.get('quantity') or 1)
            line_vals = {
                'description_picking': resolved.get('name') or resolved.get('description') or item.get('product_name') or 'Product',
                'product_id': resolved['product_id'],
                'quantity': quantity,
                'product_uom': resolved['uom_id'],
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            }
            commands.append((0, 0, line_vals))

        for item in (update_line_items or []):
            line_id = item.get('id')
            if not line_id:
                continue

            move = self.env['stock.move'].browse(int(line_id)).exists()
            if not move or move.picking_id.id != picking.id:
                raise UserError(f'Delivery line {line_id} not found for delivery {picking.id}.')

            line_vals = {}
            if item.get('quantity') is not None:
                quantity = float(item.get('quantity'))
                line_vals['quantity'] = quantity

            if item.get('name') is not None or item.get('description') is not None:
                line_vals['description_picking'] = item.get('name') or item.get('description')

            if (item.get('product_id') is not None and item.get('product_id') != '') or (item.get('product_name') is not None and item.get('product_name') != ''):
                resolved = resolver.resolve_line_item(item, name_cache, company_id)
                line_vals['product_id'] = resolved['product_id']
                line_vals['product_uom'] = resolved['uom_id']

            if line_vals:
                commands.append((1, int(line_id), line_vals))

        for line_id in (remove_line_ids or []):
            if line_id:
                commands.append((2, int(line_id), 0))

        if commands:
            write_vals['move_ids'] = commands

        if write_vals:
            picking.write(write_vals)

        _logger.info('Delivery slip updated via API: picking_id=%s name=%s', picking.id, picking.name)
        return {'id': picking.id, 'name': picking.name}
