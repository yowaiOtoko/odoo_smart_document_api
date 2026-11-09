import logging
from datetime import datetime, timedelta

from odoo import api, models

_logger = logging.getLogger(__name__)

# Same xids as the cron list in wa-erp-saas-installer: they are the only thing
# that actually sends the flows, and l10n_fr_einvoicing ships them inactive.
CRON_XIDS = (
    'l10n_fr_einvoicing.fr_einvoicing_flow_out_cron',
    'l10n_fr_einvoicing.fr_einvoicing_flow_in_cron',
    'l10n_fr_einvoicing.fr_directory_update_cron',
)

# Margin given to a user who started the onboarding and never finished it.
ONBOARDING_TIMEOUT_HOURS = 24


class EinvoicingAutosetup(models.AbstractModel):
    """Finish the FR e-invoicing onboarding of a tenant, without a click.

    `l10n_fr_einvoicing` requires two things before an invoice can be emitted:

    * a token in `fr.einvoicing.token` (written by the onboarding we start in
      controllers/einvoicing.py), and
    * a directory status on the company partner (`fr_directory_entity_type`),
      which is what `account_move._post()` -> `_fr_ctc_is_vat_registered(
      raise_if_misconfigured=True)` checks before it lets an invoice be posted.

    The annuaire lookup needs a SUPER PDP session, so it can only run once the
    token exists — and it must run BEFORE the platform is enabled, otherwise
    every post raises "Entity type is not set on partner ..." and invoice
    validation from WhatsApp breaks. This cron does exactly that, in one
    transaction, and is idempotent (it stops as soon as the status is set).
    """

    _name = 'smart_doc.einvoicing.autosetup'
    _description = 'Complete the FR e-invoicing onboarding of a tenant'

    @api.model
    def _cron_complete_onboarding(self):
        if 'fr.einvoicing.token' not in self.env:
            # l10n_fr_einvoicing is not installed on this database.
            return

        for company in self.env['res.company'].sudo().search([]):
            try:
                with self.env.cr.savepoint():
                    self._complete_company(company)
            except Exception as error:  # noqa: BLE001 - a cron must never die
                _logger.warning(
                    'FR e-invoicing autosetup failed for company %s: %s',
                    company.display_name,
                    error,
                )

    @api.model
    def _complete_company(self, company):
        if not hasattr(company, 'fr_ctc_accredited_platform'):
            return

        partner = company.partner_id
        if not partner:
            return

        token = (
            self.env['fr.einvoicing.token']
            .sudo()
            .search([('company_id', '=', company.id)], limit=1)
        )

        if not token:
            self._cancel_abandoned_onboarding(company)
            return

        if (
            company.fr_ctc_accredited_platform != 'superpdp'
            or company.fr_ctc_auth_method != 'authorization_code'
        ):
            company.write(
                {
                    'fr_ctc_accredited_platform': 'superpdp',
                    'fr_ctc_auth_method': 'authorization_code',
                }
            )

        if partner.fr_directory_entity_type not in ('private', 'public'):
            partner._fr_directory_sync_logs(
                company, self.env._('Automatic setup')
            )
            _logger.info(
                'FR e-invoicing directory status of %s resolved to %s',
                partner.display_name,
                partner.fr_directory_entity_type,
            )

        if partner.fr_directory_entity_type in ('private', 'public'):
            self._enable_crons()
            self.env['ir.config_parameter'].sudo().search(
                [('key', 'like', 'smart_doc.einvoicing.onboarding_started_%')]
            ).unlink()

    @api.model
    def _cancel_abandoned_onboarding(self, company):
        """Put a company that never finished the onboarding back in the safe state.

        With the platform enabled and no directory status, every sale document
        post raises a UserError (the customer cannot be invoiced at all). If the
        onboarding was started more than ONBOARDING_TIMEOUT_HOURS ago and no
        token ever arrived, the module's own "not onboarded" state is restored.
        """
        param_key = 'smart_doc.einvoicing.onboarding_started_%s' % company.id
        started = self.env['ir.config_parameter'].sudo().search(
            [('key', '=', param_key)], limit=1
        )
        if not started:
            return

        try:
            started_at = datetime.fromisoformat(str(started.value))
        except (TypeError, ValueError):
            started.sudo().unlink()
            return

        if datetime.now() - started_at < timedelta(hours=ONBOARDING_TIMEOUT_HOURS):
            return

        company.write(
            {
                'fr_ctc_accredited_platform': False,
                'fr_ctc_auth_method': False,
            }
        )
        self._disable_crons()
        started.sudo().unlink()
        _logger.info(
            'FR e-invoicing onboarding of company %s was abandoned; platform disabled again',
            company.display_name,
        )

    @api.model
    def _enable_crons(self):
        for xid in CRON_XIDS:
            cron = self.env.ref(xid, raise_if_not_found=False)
            if cron and not cron.active:
                cron.sudo().active = True

    @api.model
    def _disable_crons(self):
        for xid in CRON_XIDS:
            cron = self.env.ref(xid, raise_if_not_found=False)
            if cron and cron.active:
                cron.sudo().active = False
