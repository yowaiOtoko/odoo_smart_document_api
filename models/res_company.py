import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    """Complete the FR e-invoicing onboarding as soon as a token exists.

    `l10n_fr_einvoicing` writes the token from its OAuth callback, and needs a
    second fact before an invoice can be emitted: the directory status on the
    company partner (`fr_directory_entity_type`, filled by an annuaire lookup).
    That second fact used to come only from the hourly
    `smart_doc.einvoicing.autosetup` cron, so for up to an hour after a
    successful connection the company still looked unauthorized: the WhatsApp
    agent answered "connect SUPER PDP" to a user who had just done it, and a
    post made in that window raised "Entity type is not set on partner ...".

    `models/ir_http.py` calls this at the end of every request whose session
    knows the onboarding company, which includes the callback itself — the
    token and the directory status are then written by the same request.
    """

    _inherit = 'res.company'

    def _smart_doc_complete_onboarding(self):
        """Resolve what is still missing for these companies to emit.

        No-op when the tenant has no token yet (nothing to complete) or when the
        directory status is already known (private/public/no/private_inactive),
        so token refreshes and ordinary page loads cost one search.

        Never raises: a failing annuaire lookup must not break the page the user
        is waiting for. The hourly cron, and the agent's status route on demand,
        both retry.
        """
        if 'fr.einvoicing.token' not in self.env:
            return

        autosetup = self.env['smart_doc.einvoicing.autosetup']
        for company in self:
            partner = company.partner_id
            if not partner or partner.fr_directory_entity_type:
                continue
            if not self.env['fr.einvoicing.token'].sudo().search_count(
                [('company_id', '=', company.id)]
            ):
                continue
            try:
                with self.env.cr.savepoint():
                    autosetup._complete_company(company)
            except Exception as error:  # noqa: BLE001 - see the docstring
                _logger.warning(
                    'FR e-invoicing onboarding completion failed for company '
                    '%s: %s',
                    company.display_name,
                    error,
                )
