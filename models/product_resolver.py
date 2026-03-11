from odoo import models

class ProductResolver(models.AbstractModel):
    _name = 'invoice_api.product_resolver'
    _description = 'Product resolver using FTS + trigram (v1.1)'

    def resolve_or_create(
        self,
        name,
        company_id,
        price=None,
        detailed_type='product',
        threshold_exact=0.6,
        threshold_fuzzy=0.35,
    ):
        """
        Returns:
        {
            product: recordset,
            confidence: float,
            action: exact | fuzzy | created
        }
        """

        query = name.strip()

        sql = """
            SELECT id,
                   ts_rank(
                       to_tsvector('french', name),
                       plainto_tsquery('french', %s)
                   )            AS fts_score,
                   similarity(name, %s) AS trigram_score
            FROM product_template
            WHERE active = true
              AND company_id IN (%s, NULL)
              AND (
                    to_tsvector('french', name)
                    @@ plainto_tsquery('french', %s)
                 OR similarity(name, %s) > 0.2
              )
            ORDER BY (0.6 * ts_rank(
                          to_tsvector('french', name),
                          plainto_tsquery('french', %s)
                     )
                     + 0.4 * similarity(name, %s)) DESC
            LIMIT 1
        """

        params = (
            query,          # tsquery
            query,          # trigram
            company_id,
            query,          # tsquery in WHERE
            query,          # trigram in WHERE
            query, query,   # ORDER BY
        )

        self.env.cr.execute(sql, params)
        row = self.env.cr.fetchone()

        if row:
            product_id, fts, trigram = row
            final_score = (0.6 * (fts or 0.0)) + (0.4 * (trigram or 0.0))
            confidence = round(min(final_score, 1.0), 3)

            if confidence >= threshold_exact:
                return {
                    'product': self.env['product.template'].browse(product_id),
                    'confidence': confidence,
                    'action': 'exact',
                }

            if confidence >= threshold_fuzzy:
                return {
                    'product': self.env['product.template'].browse(product_id),
                    'confidence': confidence,
                    'action': 'fuzzy',
                }

        # 🚨 No acceptable match → create product
        created = self.env['product.template'].create({
            'name': name,
            'type': 'service',
            'detailed_type': detailed_type,
            'list_price': price or 0.0,
            'company_id': company_id,
        })

        return {
            'product': created,
            'confidence': 0.0,
            'action': 'created',
        }
