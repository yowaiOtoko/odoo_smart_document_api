import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductResolver(models.AbstractModel):
    _name = 'invoice_api.product_resolver'
    _description = 'Product resolver using FTS + trigram (v1.1)'
    _pg_trgm_available = None

    def _trigram_available(self):
        if ProductResolver._pg_trgm_available is None:
            self.env.cr.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
            )
            ProductResolver._pg_trgm_available = self.env.cr.fetchone()[0]
        return ProductResolver._pg_trgm_available

    def _get_default_uom(self):
        Product = self.env['product.product'].with_context(active_test=True)
        service = Product.search([('type', '=', 'service')], limit=1)
        if service:
            return service.uom_id
        any_product = Product.search([], limit=1)
        if any_product:
            return any_product.uom_id
        first_uom = self.env['uom.uom'].search([], limit=1)
        if first_uom:
            return first_uom
        raise UserError(
            'Default UoM could not be resolved: no service product, no product, and no UoM found.'
        )

    def resolve_by_id(self, product_id):
        if not product_id:
            raise UserError('Product id is missing or invalid.')
        variant = self.env['product.product'].browse(int(product_id)).exists()
        if not variant or not variant.active:
            raise UserError(f'Product with id {product_id} not found or not usable.')
        return {
            'product_id': variant.id,
            'uom_id': variant.uom_id.id,
        }

    def resolve_or_create(
        self,
        name,
        company_id,
        price=None,
        detailed_type='service',
        threshold_exact=0.6,
        threshold_fuzzy=0.35,
        name_cache=None,
    ):
        if name_cache is None:
            name_cache = {}
        query = (name or '').strip()
        if not query:
            raise UserError('Product name is empty or not provided.')
        if query in name_cache:
            cached = name_cache[query]
            return {
                'product': self.env['product.template'].browse(cached['template_id']),
                'confidence': cached.get('confidence', 0.0),
                'action': cached.get('action', 'exact'),
            }

        if self._trigram_available():
            sql = """
                SELECT id,
                       ts_rank(
                           to_tsvector('french', name::text),
                           plainto_tsquery('french', %s)
                       )            AS fts_score,
                       similarity(name::text, %s) AS trigram_score
                FROM product_template
                WHERE active = true
                  AND company_id IN (%s, NULL)
                  AND (
                        to_tsvector('french', name::text)
                        @@ plainto_tsquery('french', %s)
                     OR similarity(name::text, %s) > 0.2
                  )
                ORDER BY (0.6 * ts_rank(
                              to_tsvector('french', name::text),
                              plainto_tsquery('french', %s)
                         )
                         + 0.4 * similarity(name::text, %s)) DESC
                LIMIT 1
            """
            params = (
                query,
                query,
                company_id,
                query,
                query,
                query,
                query,
            )
        else:
            sql = """
                SELECT id,
                       ts_rank(
                           to_tsvector('french', name::text),
                           plainto_tsquery('french', %s)
                       ) AS fts_score,
                       0.0 AS trigram_score
                FROM product_template
                WHERE active = true
                  AND company_id IN (%s, NULL)
                  AND (
                        to_tsvector('french', name::text)
                        @@ plainto_tsquery('french', %s)
                     OR name::text ILIKE %s
                  )
                ORDER BY ts_rank(
                             to_tsvector('french', name::text),
                             plainto_tsquery('french', %s)
                         ) DESC
                LIMIT 1
            """
            ilike_pattern = f'%{query}%'
            params = (
                query,
                company_id,
                query,
                ilike_pattern,
                query,
            )

        self.env.cr.execute(sql, params)
        row = self.env.cr.fetchone()

        if row:
            template_id, fts, trigram = row
            final_score = (0.6 * (fts or 0.0)) + (0.4 * (trigram or 0.0))
            confidence = round(min(final_score, 1.0), 3)

            if confidence >= threshold_exact:
                template = self.env['product.template'].browse(template_id)
                name_cache[query] = {
                    'template_id': template_id,
                    'confidence': confidence,
                    'action': 'exact',
                }
                return {
                    'product': template,
                    'confidence': confidence,
                    'action': 'exact',
                }

            if confidence >= threshold_fuzzy:
                template = self.env['product.template'].browse(template_id)
                name_cache[query] = {
                    'template_id': template_id,
                    'confidence': confidence,
                    'action': 'fuzzy',
                }
                return {
                    'product': template,
                    'confidence': confidence,
                    'action': 'fuzzy',
                }

        default_uom = self._get_default_uom()
        created = self.env['product.template'].create({
            'name': name,
            'type': 'service',
            'detailed_type': detailed_type,
            'list_price': price or 0.0,
            'company_id': company_id,
            'uom_id': default_uom.id,
            'uom_po_id': default_uom.id,
        })
        _logger.info(
            'Product created from name: template_id=%s name=%s',
            created.id,
            name,
        )
        name_cache[query] = {
            'template_id': created.id,
            'confidence': 0.0,
            'action': 'created',
        }
        return {
            'product': created,
            'confidence': 0.0,
            'action': 'created',
        }

    def resolve_line_item(self, line_item, name_cache, company_id):
        product_id = line_item.get('product_id')
        product_name = line_item.get('product_name')
        if product_id is not None and product_id != '':
            out = self.resolve_by_id(product_id)
        elif product_name is not None and product_name != '':
            result = self.resolve_or_create(
                name=product_name,
                company_id=company_id,
                price=line_item.get('price'),
                detailed_type=line_item.get('detailed_type', 'service'),
                name_cache=name_cache,
            )
            product = result['product']
            variant = product.product_variant_id
            out = {
                'product_id': variant.id,
                'uom_id': variant.uom_id.id,
                'confidence': result.get('confidence', 0.0),
                'action': result.get('action', 'exact'),
            }
        else:
            raise UserError(
                'Each line must have product_id or product_name; both are missing.'
            )
        out['quantity'] = line_item.get('quantity', 1)
        out['price_unit'] = line_item.get('price_unit') or line_item.get('price')
        out['discount'] = line_item.get('discount')
        out['name'] = line_item.get('name')
        out['description'] = line_item.get('description')
        return out
