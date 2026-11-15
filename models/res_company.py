import logging
import time

from odoo import models

_logger = logging.getLogger(__name__)

# Distinguishes this trigger from the cron in `fr.einvoicing.log` and in the
# partner chatter ("Directory sync. Origin: ..."), which is where an operator
# looks when a tenant reports that the platform is still not connected.
SYNC_ORIGIN = 'Right after the platform authorization'


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

        Never raises: a slow or failing annuaire must not break the page the
        user is waiting for (pyfrctc bounds every HTTP call at 30 s, and this
        block runs in a savepoint, so a timeout only costs time). Everything
        that happens here is logged with the company, the outcome and the
        duration; the hourly cron, and the agent's status route on demand, both
        retry.
        """
        if 'fr.einvoicing.token' not in self.env:
            return

        autosetup = self.env['smart_doc.einvoicing.autosetup']
        for company in self:
            partner = company.partner_id
            if not partner:
                _logger.info(
                    'FR e-invoicing onboarding: company %s has no partner, '
                    'skipping',
                    company.display_name,
                )
                continue
            if partner.fr_directory_entity_type:
                # Already known: nothing to do, and no log line either — this
                # runs on every request of the onboarding session.
                continue
            if not self.env['fr.einvoicing.token'].sudo().search_count(
                [('company_id', '=', company.id)]
            ):
                # Normal right after the onboarding was started: the token only
                # exists once the user has authorized.
                continue

            started = time.monotonic()
            _logger.info(
                'FR e-invoicing onboarding of %s (company %s): token found, '
                'resolving the directory status (origin: %s)',
                partner.display_name,
                company.id,
                SYNC_ORIGIN,
            )
            try:
                with self.env.cr.savepoint():
                    autosetup._complete_company(company, SYNC_ORIGIN)
            except Exception:  # noqa: BLE001 - see the docstring
                # exception(), not warning(): the traceback is what tells an
                # annuaire timeout apart from a SUPER PDP error or a bad token.
                _logger.exception(
                    'FR e-invoicing onboarding of %s (company %s) FAILED after '
                    '%.1fs while resolving the directory status; the request '
                    'stays successful and the hourly autosetup cron will retry',
                    partner.display_name,
                    company.id,
                    time.monotonic() - started,
                )
                continue

            _logger.info(
                'FR e-invoicing onboarding of %s (company %s): directory status '
                '%s, platform crons %s, done in %.1fs',
                partner.display_name,
                company.id,
                partner.fr_directory_entity_type or 'still unknown',
                'enabled'
                if partner.fr_directory_entity_type in ('private', 'public')
                else 'left untouched',
                time.monotonic() - started,
            )
