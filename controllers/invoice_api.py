from odoo import http
from odoo.http import request

class InvoiceAPIController(http.Controller):

    @http.route(
        '/api/invoice',
        type='json',
        auth='api_key',
        methods=['POST'],
        csrf=False
    )
    def create_invoice(self, **payload):

        env = request.env
        company = env.company
        resolver = env['invoice_api.product_resolver']

        partner_id = payload.get('partner_id')
        items = payload.get('items', [])

        if not partner_id or not items:
            return {'error': 'Invalid payload'}

        lines = []
        debug = []

        for item in items:
            result = resolver.resolve_or_create(
                name=item['name'],
                price=item.get('price'),
                company_id=company.id,
                detailed_type=item.get('detailed_type', 'product'),
            )

            product = result['product']

            lines.append((0, 0, {
                'product_id': product.product_variant_id.id,
                'quantity': item.get('qty', 1),
                'price_unit': item.get('price', product.list_price),
                'name': item.get('name'),
                'product_match_confidence': result['confidence'],
                'product_match_action': result['action'],
            }))

            debug.append({
                'input_name': item['name'],
                'product_id': product.id,
                'product_name': product.name,
                'confidence': result['confidence'],
                'action': result['action'],
            })

        invoice = env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner_id,
            'invoice_line_ids': lines,
            'company_id': company.id,
        })

        return {
            'invoice_id': invoice.id,
            'invoice_name': invoice.name,
            'lines': debug,
        }
