import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    """Complete the FR e-invoicing onboarding the moment the token lands.

    `l10n_fr_einvoicing` hands pyfrctc a `token_updater` (this method), so it is
    called by the OAuth callback as soon as the code is exchanged — before the
    user is even redirected back. The directory status, on the other hand, was
    only ever resolved by the hourly `smart_doc.einvoicing.autosetup` cron, so
    for up to an hour after a successful connection the company looked
    unauthorized: the WhatsApp agent answered "connect SUPER PDP" to a user who
    had just done it, and a post made in that window raised "Entity type is not
    set on partner ...".

    Calling the autosetup routine right here removes the window: the token and
    the directory status are written by the same request. It is the same
    idempotent code the cron runs, and it is a no-op once the status is known,
    so the token refreshes that also come through this method cost nothing.
    """

    _inherit = 'res.company'

    def _fr_ctc_write_token(self, new_token):
        result = super()._fr_ctc_write_token(new_token)
        # A refresh happening INSIDE the directory sync would come back here
        # while the status is still empty; the flag stops that recursion.
        if not self.env.context.get('smart_doc_einvoicing_sync'):
            self._smart_doc_complete_onboarding()
        return result

    def _smart_doc_complete_onboarding(self):
        """Resolve what is still missing for this company to be able to emit.

        Never raises: the token is already stored at this point, and a failure
        of the directory lookup must not turn a successful authorization into
        an error page for the user. The hourly cron, and the status route on
        demand, both retry.
        """
        autosetup = self.env['smart_doc.einvoicing.autosetup'].with_context(
            smart_doc_einvoicing_sync=True
        )
        for company in self:
            partner = company.partner_id
            if not partner or partner.fr_directory_entity_type:
                continue
            try:
                with self.env.cr.savepoint():
                    autosetup._complete_company(company)
            except Exception as error:  # noqa: BLE001 - see the docstring
                _logger.warning(
                    'FR e-invoicing onboarding completion after token write '
                    'failed for company %s: %s',
                    company.display_name,
                    error,
                )
