import logging
from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _invoice_api_resolve_payment_term_id(self, company_id, partner_id, explicit_term_id=None):
        company_id = int(company_id) if company_id else self.env.company.id
        PaymentTerm = self.env['account.payment.term']
        if explicit_term_id not in (None, False, ''):
            term = PaymentTerm.browse(int(explicit_term_id))
            if (
                term.exists()
                and (not term.company_id or term.company_id.id == company_id)
            ):
                return term.id
            raise UserError('Invalid payment_term_id.')
        if partner_id:
            partner = self.env['res.partner'].browse(int(partner_id)).with_company(company_id)
            if partner.property_payment_term_id:
                return partner.property_payment_term_id.id
        company = self.env['res.company'].browse(company_id)
        if 'account_payment_term_id' in company._fields and company.account_payment_term_id:
            return company.account_payment_term_id.id
        for xml_id in (
            'account.account_payment_term_30days',
            'account.account_payment_term_30_days',
        ):
            term = self.env.ref(xml_id, raise_if_not_found=False)
            if (
                term
                and term._name == 'account.payment.term'
                and (not term.company_id or term.company_id.id == company_id)
            ):
                return term.id
        term = PaymentTerm.search(
            [('company_id', 'in', [False, company_id])],
            order='sequence, id',
            limit=1,
        )
        return term.id if term else False

    @api.model
    def create_invoice(self, header_vals, line_items):
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
                'quantity': resolved.get('quantity', 1),
                'price_unit': resolved.get('price_unit') if resolved.get('price_unit') is not None else product.list_price,
                'product_uom_id': resolved['uom_id'],
            }
            if resolved.get('discount') is not None:
                line_vals['discount'] = resolved['discount']
            if resolved.get('name') or resolved.get('description'):
                line_vals['name'] = resolved.get('name') or resolved.get('description')
            lines_vals.append((0, 0, line_vals))
        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': header_vals.get('partner_id'),
            'company_id': company_id,
            'invoice_line_ids': lines_vals,
        }
        if header_vals.get('journal_id'):
            move_vals['journal_id'] = header_vals['journal_id']
        if header_vals.get('invoice_date'):
            move_vals['invoice_date'] = header_vals['invoice_date']
        if header_vals.get('payment_reference'):
            move_vals['payment_reference'] = header_vals['payment_reference']
        pt_id = self._invoice_api_resolve_payment_term_id(
            company_id,
            header_vals.get('partner_id'),
            header_vals.get('payment_term_id'),
        )
        if pt_id:
            move_vals['invoice_payment_term_id'] = pt_id
        move = self.create(move_vals)
        _logger.info('Customer invoice created via API: move_id=%s name=%s', move.id, move.name)
        return {'id': move.id, 'name': move.name}

    @api.model
    def update_invoice(self, move_id, header_vals=None, add_line_items=None, update_line_items=None, remove_line_ids=None):
        move = self.browse(int(move_id)).exists()
        if not move:
            raise UserError(f'Invoice with id {move_id} not found.')
        if move.move_type != 'out_invoice':
            raise UserError('Only customer invoices (out_invoice) can be updated with this API.')

        resolver = self.env['invoice_api.product_resolver']
        name_cache = {}
        company_id = (header_vals or {}).get('company_id') or move.company_id.id or self.env.company.id

        write_vals = {}
        if header_vals:
            if header_vals.get('partner_id'):
                write_vals['partner_id'] = header_vals['partner_id']
            if header_vals.get('company_id'):
                write_vals['company_id'] = header_vals['company_id']
            if header_vals.get('journal_id'):
                write_vals['journal_id'] = header_vals['journal_id']
            if header_vals.get('invoice_date'):
                write_vals['invoice_date'] = header_vals['invoice_date']
            if header_vals.get('invoice_date_due'):
                write_vals['invoice_date_due'] = header_vals['invoice_date_due']
            if header_vals.get('payment_reference'):
                write_vals['payment_reference'] = header_vals['payment_reference']
            if 'payment_term_id' in header_vals or 'invoice_payment_term_id' in header_vals:
                raw = header_vals.get('payment_term_id', header_vals.get('invoice_payment_term_id'))
                if raw in (False, None, ''):
                    write_vals['invoice_payment_term_id'] = False
                else:
                    pt_id = self._invoice_api_resolve_payment_term_id(
                        company_id,
                        header_vals.get('partner_id') or move.partner_id.id,
                        raw,
                    )
                    write_vals['invoice_payment_term_id'] = pt_id or False

        commands = []

        for item in (add_line_items or []):
            resolved = resolver.resolve_line_item(item, name_cache, company_id)
            product = self.env['product.product'].browse(resolved['product_id'])
            line_vals = {
                'product_id': resolved['product_id'],
                'quantity': resolved.get('quantity', 1),
                'price_unit': resolved.get('price_unit') if resolved.get('price_unit') is not None else product.list_price,
                'product_uom_id': resolved['uom_id'],
            }
            if resolved.get('discount') is not None:
                line_vals['discount'] = resolved['discount']
            if resolved.get('name') or resolved.get('description'):
                line_vals['name'] = resolved.get('name') or resolved.get('description')
            commands.append((0, 0, line_vals))

        for item in (update_line_items or []):
            line_id = item.get('id')
            if not line_id:
                continue
            line = self.env['account.move.line'].browse(int(line_id)).exists()
            if not line or line.move_id.id != move.id:
                raise UserError(f'Invoice line {line_id} not found for invoice {move.id}.')

            line_vals = {}
            if item.get('quantity') is not None:
                line_vals['quantity'] = item.get('quantity')
            if item.get('price_unit') is not None or item.get('price') is not None:
                line_vals['price_unit'] = item.get('price_unit') if item.get('price_unit') is not None else item.get('price')
            if item.get('discount') is not None:
                line_vals['discount'] = item.get('discount')
            if item.get('name') is not None or item.get('description') is not None:
                line_vals['name'] = item.get('name') or item.get('description')

            if (item.get('product_id') is not None and item.get('product_id') != '') or (item.get('product_name') is not None and item.get('product_name') != ''):
                resolved = resolver.resolve_line_item(item, name_cache, company_id)
                line_vals['product_id'] = resolved['product_id']
                line_vals['product_uom_id'] = resolved['uom_id']
                if resolved.get('price_unit') is not None:
                    line_vals['price_unit'] = resolved.get('price_unit')

            if line_vals:
                commands.append((1, int(line_id), line_vals))

        for line_id in (remove_line_ids or []):
            if line_id:
                commands.append((2, int(line_id), 0))

        if commands:
            write_vals['invoice_line_ids'] = commands

        if not write_vals:
            return {'id': move.id, 'name': move.name}

        move.write(write_vals)
        _logger.info('Customer invoice updated via API: move_id=%s name=%s', move.id, move.name)
        return {'id': move.id, 'name': move.name}
