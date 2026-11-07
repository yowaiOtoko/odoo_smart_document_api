import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductResolver(models.AbstractModel):
    _name = 'invoice_api.product_resolver'
    _description = 'Product resolver using FTS + trigram (v1.1)'
    _pg_trgm_available = None

    #: ir.config_parameter key overriding the revenue account used for services.
    SERVICE_INCOME_ACCOUNT_PARAM = 'odoo_smart_document_api.service_income_account_id'
    #: French PCG prefix for "Ventes de prestations de services".
    SERVICE_INCOME_ACCOUNT_CODE_PREFIX = '706'
    _service_income_accounts = None

    def _trigram_available(self):
        if ProductResolver._pg_trgm_available is None:
            self.env.cr.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
            )
            ProductResolver._pg_trgm_available = self.env.cr.fetchone()[0]
        return ProductResolver._pg_trgm_available

    def _get_default_uom(self):
        """The plain "Units" unit (UNECE C62) used for a new product.

        Copying the UoM of an existing product looks harmless but is arbitrary:
        ``uom.uom._order`` is ``factor DESC, id``, so on a database that has no
        product yet the first record is whatever the data ranks highest (in
        practice millimetres), and every product created afterwards inherits it
        through the "first service product" branch. Invoices then read
        "1 mm". What a line is counted in has to be an explicit decision, so the
        unit category is pinned here and product data never decides it.
        """
        unit = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
        if unit:
            return unit

        Unit = self.env['uom.uom'].with_context(active_test=True)
        # Non-standard data (the xmlid was dropped): match the reference unit of
        # the "Unit" category instead of trusting the model's default order.
        reference = Unit.search(
            [('category_id.name', 'in', ['Unit', 'Units']), ('uom_type', '=', 'reference')],
            limit=1,
        )
        if reference:
            return reference
        named = Unit.search([('name', 'in', ['Unit', 'Units'])], limit=1)
        if named:
            return named
        raise UserError(
            'Default UoM could not be resolved: the "Units" unit (uom.product_uom_unit) '
            'is missing from this database.'
        )

    def _get_service_income_account(self, company_id):
        """Revenue account to book services on, or an empty recordset.

        Odoo takes a line's income account from its product, which falls back to
        the product-category default. On a French chart that default is
        707000 "Ventes de marchandises" (goods), so a *service* needs
        706000 "Ventes de prestations de services" set explicitly. Charts that
        have no such account simply resolve to nothing.
        """
        company_id = int(company_id) if company_id else self.env.company.id
        if ProductResolver._service_income_accounts is None:
            ProductResolver._service_income_accounts = {}
        cache = ProductResolver._service_income_accounts
        if company_id in cache:
            return cache[company_id]

        Account = self.env['account.account'].with_company(company_id)
        account = Account.browse()
        override = self.env['ir.config_parameter'].sudo().get_param(
            self.SERVICE_INCOME_ACCOUNT_PARAM
        )
        if override:
            try:
                candidate = Account.browse(int(override)).exists()
            except (TypeError, ValueError):
                candidate = Account.browse()
            if candidate and company_id in candidate.company_ids.ids:
                account = candidate
        if not account:
            candidates = [
                acc
                for acc in Account.search([('account_type', '=', 'income')])
                if (acc.code or '').startswith(self.SERVICE_INCOME_ACCOUNT_CODE_PREFIX)
            ]
            candidates.sort(key=lambda acc: acc.code)
            if candidates:
                account = candidates[0]

        cache[company_id] = account
        return account

    def _assign_service_income_account(self, template, company_id):
        """Book a service product on the services account when it has none.

        ``template`` is a ``product.template`` (what ``resolve_or_create``
        returns). Only products without their own income account are touched, so
        a tenant that deliberately configured an account keeps it. Goods (consu)
        products are left alone - the category default is already the goods
        account.
        """
        template = template.with_company(company_id)
        if template.type != 'service' or template.property_account_income_id:
            return
        account = self._get_service_income_account(company_id)
        if account:
            template.property_account_income_id = account.id

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
        create_vals = {
            'name': name,
            'type': 'service',
            'list_price': price or 0.0,
            'company_id': company_id,
            'uom_id': default_uom.id,
        }
        if 'detailed_type' in self.env['product.template']._fields:
            create_vals['detailed_type'] = detailed_type
        if 'uom_po_id' in self.env['product.template']._fields:
            create_vals['uom_po_id'] = default_uom.id
        created = self.env['product.template'].create(create_vals)
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
        detailed_type = line_item.get('detailed_type')
        if detailed_type == 'product':
            detailed_type = 'consu'
        if detailed_type not in ('service', 'consu'):
            detailed_type = 'service' if bool(line_item.get('is_service')) else 'consu'

        if product_id is not None and product_id != '':
            out = self.resolve_by_id(product_id)
        elif product_name is not None and product_name != '':
            result = self.resolve_or_create(
                name=product_name,
                company_id=company_id,
                price=line_item.get('price'),
                detailed_type=detailed_type,
                name_cache=name_cache,
            )
            product = result['product']
            self._assign_service_income_account(product, company_id)
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
        out['detailed_type'] = detailed_type
        out['tax_ids'] = line_item.get('tax_ids')
        return out
