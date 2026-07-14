import json
import logging

from odoo import http
from odoo.addons.web.controllers.report import ReportController
from odoo.http import request


class _ApiStatusRollback(Exception):
    pass


class InvoiceAPIController(http.Controller):

    def _line_item_from_payload_item(self, item):
        price = item.get('price_unit', item.get('price'))
        payload = {
            'quantity': item.get('qty', item.get('quantity', 1)),
            'price_unit': price,
            'price': price,
            'discount': item.get('discount'),
            'name': item.get('name'),
            'description': item.get('description'),
            'detailed_type': item.get('detailed_type'),
            'tax_ids': item.get('tax_ids'),
        }
        product_id = item.get('product_id')
        if product_id is not None and product_id != '':
            payload['product_id'] = product_id
            return payload

        payload['product_name'] = item.get('name', item.get('product_name'))
        return payload

    def _partner_payload(self, partner):
        return {
            'id': partner.id,
            'name': partner.name or '',
            'email': partner.email or '',
            'phone': partner.phone or '',
            'street': partner.street or '',
            'city': partner.city or '',
            'zip': partner.zip or '',
            'country_id': [partner.country_id.id] if partner.country_id else None,
            'country_code': partner.country_id.code if partner.country_id else None,
            'is_company': bool(partner.is_company),
        }

    def _invoice_lines_payload(self, move):
        return [
            {
                'id': line.id,
                'name': line.name or '',
                'quantity': line.quantity or 0,
                'price_unit': float(line.price_unit or 0),
                'price_subtotal': float(line.price_subtotal or 0),
            }
            for line in move.invoice_line_ids
        ]

    def _quote_lines_payload(self, order):
        return [
            {
                'id': line.id,
                'name': line.name or '',
                'product_uom_qty': line.product_uom_qty or 0,
                'price_unit': float(line.price_unit or 0),
                'price_subtotal': float(line.price_subtotal or 0),
            }
            for line in order.order_line
        ]

    def _delivery_lines_payload(self, picking):
        moves = picking.move_ids
        return [
            {
                'id': move.id,
                'name': move.description_picking or '',
                'product_id': move.product_id.id,
                'product_name': move.product_id.name or '',
                'quantity': float(move.quantity or 0),
                'quantity_done': float(move.quantity or 0),
            }
            for move in moves
        ]

    @http.route(
        '/api/invoice',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def create_invoice(self, **payload):
        partner_id = payload.get('partner_id')
        items = payload.get('items', [])
        if not partner_id or not items:
            return {'error': 'Invalid payload'}
        line_items = [self._line_item_from_payload_item(it) for it in items]
        header_vals = {
            'partner_id': partner_id,
            'company_id': payload.get('company_id'),
            'journal_id': payload.get('journal_id'),
            'invoice_date': payload.get('invoice_date'),
            'payment_reference': payload.get('payment_reference'),
            'payment_term_id': payload.get('payment_term_id'),
        }
        try:
            result = request.env['account.move'].create_invoice(header_vals, line_items)
            return {'id': result['id'], 'name': result['name'], 'invoice_id': result['id'], 'invoice_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/invoice/update',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def update_invoice(self, **payload):
        invoice_id = payload.get('id') or payload.get('invoice_id')
        if not invoice_id:
            return {'error': 'Invalid payload: missing id'}
        header_vals = payload.get('header', {}) or {}
        try:
            result = request.env['account.move'].update_invoice(
                invoice_id,
                header_vals=header_vals,
                add_line_items=payload.get('items_to_add', []) or [],
                update_line_items=payload.get('items_to_update', []) or [],
                remove_line_ids=payload.get('items_to_remove', []) or [],
            )
            return {'id': result['id'], 'name': result['name'], 'invoice_id': result['id'], 'invoice_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/invoice/set_paid',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def set_invoice_paid(self, **payload):
        invoice_id = payload.get('id') or payload.get('invoice_id')
        if not invoice_id:
            return {'error': 'Invalid payload: missing id'}

        try:
            result = request.env['account.move'].set_invoice_paid(
                invoice_id,
                journal_id=payload.get('journal_id'),
                amount=payload.get('amount'),
                payment_date=payload.get('payment_date'),
                reference=payload.get('reference') or payload.get('payment_reference'),
            )
            return {
                'id': result['id'],
                'name': result['name'],
                'invoice_id': result['id'],
                'invoice_name': result['name'],
                'state': result.get('state'),
                'payment_state': result.get('payment_state'),
                'amount_residual': result.get('amount_residual'),
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/invoice/get',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def get_invoice(self, **payload):
        invoice_id = payload.get('id') or payload.get('invoice_id')
        invoice_number = payload.get('invoiceNumber') or payload.get('invoice_number')

        try:
            if invoice_id:
                move = request.env['account.move'].browse(int(invoice_id))
                if not move.exists():
                    return {'error': 'Invoice not found'}
            elif invoice_number:
                moves = request.env['account.move'].search(
                    [('name', '=', invoice_number), ('move_type', '=', 'out_invoice')],
                    limit=1,
                )
                if not moves:
                    return {'error': 'Invoice not found'}
                move = moves[0]
            else:
                return {'error': 'Invalid payload: missing id or invoiceNumber'}

            partner = move.partner_id
            invoice_date = move.invoice_date.strftime('%Y-%m-%d') if move.invoice_date else None
            invoice_date_due = move.invoice_date_due.strftime('%Y-%m-%d') if move.invoice_date_due else None

            return {
                'document': {
                    'id': move.id,
                    'name': move.name,
                    'state': move.state,
                    'payment_state': move.payment_state,
                    'invoice_date': invoice_date,
                    'invoice_date_due': invoice_date_due,
                    'payment_term_id': move.invoice_payment_term_id.id if move.invoice_payment_term_id else None,
                    'payment_term_name': move.invoice_payment_term_id.name if move.invoice_payment_term_id else None,
                    'amount_untaxed': float(move.amount_untaxed or 0),
                    'amount_total': float(move.amount_total or 0),
                    'amount_tax': float(move.amount_tax or 0),
                    'amount_residual': float(move.amount_residual or 0),
                },
                'partner': self._partner_payload(partner) if partner else None,
                'lines': self._invoice_lines_payload(move),
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/quotation',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def create_quotation(self, **payload):
        partner_id = payload.get('partner_id')
        items = payload.get('items', [])
        if not partner_id or not items:
            return {'error': 'Invalid payload'}
        line_items = [self._line_item_from_payload_item(it) for it in items]
        header_vals = {
            'partner_id': partner_id,
            'company_id': payload.get('company_id'),
            'validity_date': payload.get('validity_date'),
        }
        try:
            result = request.env['sale.order'].create_quotation(header_vals, line_items)
            return {'id': result['id'], 'name': result['name'], 'quotation_id': result['id'], 'quotation_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/quotation/update',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def update_quotation(self, **payload):
        quotation_id = payload.get('id') or payload.get('quotation_id')
        if not quotation_id:
            return {'error': 'Invalid payload: missing id'}
        header_vals = payload.get('header', {}) or {}
        try:
            result = request.env['sale.order'].update_quotation(
                quotation_id,
                header_vals=header_vals,
                add_line_items=payload.get('items_to_add', []) or [],
                update_line_items=payload.get('items_to_update', []) or [],
                remove_line_ids=payload.get('items_to_remove', []) or [],
            )
            return {'id': result['id'], 'name': result['name'], 'quotation_id': result['id'], 'quotation_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/quotation/get',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def get_quotation(self, **payload):
        quotation_id = payload.get('id') or payload.get('quotation_id')
        quote_number = payload.get('quoteNumber') or payload.get('quote_number') or payload.get('quotationNumber') or payload.get('quotation_number')

        try:
            if quotation_id:
                order = request.env['sale.order'].browse(int(quotation_id))
                if not order.exists():
                    return {'error': 'Quotation not found'}
            elif quote_number:
                orders = request.env['sale.order'].search([('name', '=', quote_number)], limit=1)
                if not orders:
                    return {'error': 'Quotation not found'}
                order = orders[0]
            else:
                return {'error': 'Invalid payload: missing id or quoteNumber'}

            partner = order.partner_id
            date_order = order.date_order.strftime('%Y-%m-%d %H:%M:%S') if order.date_order else None
            validity_date = order.validity_date.strftime('%Y-%m-%d') if order.validity_date else None

            return {
                'document': {
                    'id': order.id,
                    'name': order.name,
                    'state': order.state,
                    'date_order': date_order,
                    'validity_date': validity_date,
                    'amount_untaxed': float(order.amount_untaxed or 0),
                    'amount_total': float(order.amount_total or 0),
                    'amount_tax': float(order.amount_tax or 0),
                },
                'partner': self._partner_payload(partner) if partner else None,
                'lines': self._quote_lines_payload(order),
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/delivery',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def create_delivery(self, **payload):
        partner_id = payload.get('partner_id')
        items = payload.get('items', [])
        if not partner_id or not items:
            return {'error': 'Invalid payload'}

        line_items = [self._line_item_from_payload_item(it) for it in items]
        header_vals = {
            'partner_id': partner_id,
            'company_id': payload.get('company_id'),
            'scheduled_date': payload.get('scheduled_date'),
            'location_id': payload.get('location_id'),
            'location_dest_id': payload.get('location_dest_id'),
            'origin': payload.get('origin'),
        }

        try:
            result = request.env['stock.picking'].create_delivery(header_vals, line_items)
            return {'id': result['id'], 'name': result['name'], 'delivery_id': result['id'], 'delivery_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/delivery/update',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def update_delivery(self, **payload):
        delivery_id = payload.get('id') or payload.get('delivery_id')
        if not delivery_id:
            return {'error': 'Invalid payload: missing id'}

        header_vals = payload.get('header', {}) or {}
        try:
            result = request.env['stock.picking'].update_delivery(
                delivery_id,
                header_vals=header_vals,
                add_line_items=payload.get('items_to_add', []) or [],
                update_line_items=payload.get('items_to_update', []) or [],
                remove_line_ids=payload.get('items_to_remove', []) or [],
            )
            return {'id': result['id'], 'name': result['name'], 'delivery_id': result['id'], 'delivery_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/delivery/get',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def get_delivery(self, **payload):
        delivery_id = payload.get('id') or payload.get('delivery_id')
        delivery_name = payload.get('name') or payload.get('delivery_name')

        try:
            if delivery_id:
                picking = request.env['stock.picking'].browse(int(delivery_id))
                if not picking.exists():
                    return {'error': 'Delivery slip not found'}
            elif delivery_name:
                pickings = request.env['stock.picking'].search([('name', '=', delivery_name)], limit=1)
                if not pickings:
                    return {'error': 'Delivery slip not found'}
                picking = pickings[0]
            else:
                return {'error': 'Invalid payload: missing id or name'}

            partner = picking.partner_id
            scheduled_date = picking.scheduled_date.strftime('%Y-%m-%d') if picking.scheduled_date else None

            return {
                'document': {
                    'id': picking.id,
                    'name': picking.name,
                    'state': picking.state,
                    'origin': picking.origin,
                    'scheduled_date': scheduled_date,
                },
                'partner': self._partner_payload(partner) if partner else None,
                'lines': self._delivery_lines_payload(picking),
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/status',
        type='jsonrpc',
        auth='api_key',
        methods=['POST'],
        csrf=False,
    )
    def status(self, **payload):
        operations = {
            'create_client': False,
            'create_product': False,
            'create_quotation': False,
            'create_invoice': False,
        }

        errors = {}

        try:
            with request.env.cr.savepoint():
                try:
                    partner = request.env['res.partner'].create({
                        'name': 'API Status Test Client',
                    })
                    operations['create_client'] = True
                except Exception as e:
                    errors['create_client'] = str(e)
                    partner = None

                try:
                    product = request.env['product.product'].create({
                        'name': 'API Status Test Product',
                        'list_price': 0.0,
                    })
                    operations['create_product'] = True
                except Exception as e:
                    errors['create_product'] = str(e)
                    product = None

                if operations['create_client'] and operations['create_product']:
                    try:
                        line_items = [
                            {
                                'product_id': product.id,
                                'quantity': 1,
                                'price_unit': 0.0,
                            }
                        ]
                        header_vals = {
                            'partner_id': partner.id,
                            'company_id': None,
                            'validity_date': None,
                        }
                        request.env['sale.order'].create_quotation(header_vals, line_items)
                        operations['create_quotation'] = True
                    except Exception as e:
                        errors['create_quotation'] = str(e)

                    try:
                        invoice_header = {
                            'partner_id': partner.id,
                            'company_id': None,
                            'journal_id': None,
                            'invoice_date': None,
                            'payment_reference': None,
                        }
                        invoice_items = [
                            {
                                'product_id': product.id,
                                'quantity': 1,
                                'price_unit': 0.0,
                            }
                        ]
                        request.env['account.move'].create_invoice(invoice_header, invoice_items)
                        operations['create_invoice'] = True
                    except Exception as e:
                        errors['create_invoice'] = str(e)

                raise _ApiStatusRollback()
        except _ApiStatusRollback:
            pass
        except Exception as e:
            errors['fatal'] = str(e)

        return {
            'status': 'ok',
            'operations': operations,
            'errors': errors,
        }

    @http.route(
        '/api/report/pdf/<string:report_name>/<int:res_id>',
        type='http',
        auth='api_key',
        methods=['GET'],
        csrf=False,
    )
    def get_report_pdf(self, report_name, res_id):
        """Generate PDF report via native /report/download flow for UI parity."""
        _logger = logging.getLogger(__name__)
        try:
            requested_report_name = report_name
            report = request.env['ir.actions.report']._get_report_from_name(report_name)
            if not report or not report.exists():
                return request.make_response(
                    f'Report "{report_name}" not found', status=404,
                    headers=[('Content-Type', 'text/plain')])

            render_context = dict(request.env.context)
            if report.model == 'account.move':
                move = request.env['account.move'].browse(int(res_id))
                if not move.exists():
                    return request.make_response(
                        f'Record "{res_id}" not found', status=404,
                        headers=[('Content-Type', 'text/plain')])
                if move.company_id:
                    render_context['allowed_company_ids'] = [move.company_id.id]

                # Keep UI-like layout, but include payments when caller requests account.report_invoice.
                if report_name == 'account.report_invoice':
                    paid_report = request.env['ir.actions.report']._get_report_from_name('account.report_invoice_with_payments')
                    if paid_report and paid_report.exists():
                        report_name = 'account.report_invoice_with_payments'
                        report = paid_report

            controller = ReportController()
            download_payload = json.dumps([
                f'/report/pdf/{report_name}/{int(res_id)}',
                'qweb-pdf',
            ])
            response = controller.report_download(
                data=download_payload,
                context=json.dumps(render_context),
                token='api',
            )
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        except Exception as e:
            _logger.exception('PDF error report=%s requested=%s id=%s: %s', report_name, requested_report_name, res_id, e)
            return request.make_response(
                f'PDF error: {str(e)}', status=500,
                headers=[('Content-Type', 'text/plain')])
