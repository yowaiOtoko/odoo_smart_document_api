from odoo import http
from odoo.http import request


class _ApiStatusRollback(Exception):
    pass


class InvoiceAPIController(http.Controller):

    def _line_item_from_payload_item(self, item):
        price = item.get('price_unit', item.get('price'))
        if 'product_id' in item:
            return {'product_id': item['product_id'], 'quantity': item.get('qty', item.get('quantity', 1)), 'price_unit': price, 'price': price, 'discount': item.get('discount'), 'name': item.get('name'), 'description': item.get('description')}
        return {'product_name': item.get('name', item.get('product_name')), 'quantity': item.get('qty', item.get('quantity', 1)), 'price_unit': price, 'price': price, 'discount': item.get('discount'), 'name': item.get('name'), 'description': item.get('description')}

    @http.route(
        '/api/invoice',
        type='json',
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
        }
        try:
            result = request.env['account.move'].create_invoice(header_vals, line_items)
            return {'id': result['id'], 'name': result['name'], 'invoice_id': result['id'], 'invoice_name': result['name']}
        except Exception as e:
            return {'error': str(e)}

    @http.route(
        '/api/quotation',
        type='json',
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
        '/api/status',
        type='json',
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
