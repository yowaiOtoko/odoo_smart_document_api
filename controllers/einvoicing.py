import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

ONBOARDING_STARTED_KEY = 'smart_doc.einvoicing.onboarding_started_%s'


class EinvoicingOnboardingController(http.Controller):
    """Accredited-platform onboarding, owned by Odoo.

    `l10n_fr_einvoicing` authenticates against SUPER PDP with a PUBLIC client
    (client id only, no secret, PKCE) and stores one token per company in
    `fr.einvoicing.token`. pyfrctc refreshes that token through
    `_fr_ctc_write_token`, which writes the ROTATED token back, so a grant
    shared with another application (the WhatsApp agent) would make the two
    sides invalidate each other. The grant therefore has to be created here,
    inside the tenant's own browser session: `state` and `code_verifier` live
    in the Odoo session.
    """

    ONBOARDING_PATH = '/smart-doc/einvoicing/onboarding'
    STATUS_PATH = '/smart-doc/einvoicing/status'

    @http.route(ONBOARDING_PATH, type='http', auth='user')
    def einvoicing_onboarding(self, **kwargs):
        """Start the Authorization Code flow and redirect to SUPER PDP."""
        company = request.env.company.sudo()
        if not hasattr(company, '_fr_ctc_authorization_code_redirect'):
            _logger.warning(
                'e-invoicing onboarding requested but l10n_fr_einvoicing is not installed (company %s)',
                company.display_name,
            )
            return request.not_found()

        # The module only builds the authorize URL for these two values, and the
        # callback reads them back. They are also what makes posting raise
        # "Entity type is not set on partner ..." until the annuaire lookup ran,
        # so a start that is never completed is cleaned up by the autosetup cron
        # (see smart_doc.einvoicing.autosetup).
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

        request.env['ir.config_parameter'].sudo().set_param(
            ONBOARDING_STARTED_KEY % company.id, fields.Datetime.now()
        )

        action = company._fr_ctc_authorization_code_redirect()
        _logger.info(
            'Redirecting company %s to the accredited platform for onboarding',
            company.display_name,
        )

        return request.redirect(action['url'], local=False, code=303)

    @http.route(STATUS_PATH, type='json', auth='api_key', methods=['POST'])
    def einvoicing_status(self, **kwargs):
        """Authorization state of the tenant, for the WhatsApp agent.

        The agent must not keep its own SUPER PDP grant: it only needs to know
        whether THIS tenant can emit, which is exactly "a token exists AND the
        company partner is registered in the annuaire".
        """
        company = request.env.company.sudo()
        has_module = 'fr.einvoicing.token' in request.env
        has_token = False
        if has_module:
            has_token = bool(
                request.env['fr.einvoicing.token']
                .sudo()
                .search_count([('company_id', '=', company.id)])
            )
        entity_type = company.partner_id.fr_directory_entity_type if hasattr(
            company, 'fr_ctc_accredited_platform'
        ) else False

        # A token appears the second the user finishes the consent, while the
        # annuaire status is only filled by the hourly autosetup cron: without
        # this, the agent answers "you must connect SUPER PDP" to a user who
        # just did exactly that, and invites them to click the link again.
        if has_token and entity_type not in ('private', 'public'):
            entity_type = self._resolve_directory_entity_type(company)

        return {
            'platform': company.fr_ctc_accredited_platform if hasattr(
                company, 'fr_ctc_accredited_platform'
            ) else False,
            'auth_method': company.fr_ctc_auth_method if hasattr(
                company, 'fr_ctc_auth_method'
            ) else False,
            'has_token': has_token,
            'directory_entity_type': entity_type,
            'authorized': bool(has_token) and entity_type in ('private', 'public'),
        }

    def _resolve_directory_entity_type(self, company):
        """Look the company up in the annuaire, right now.

        Same call as `smart_doc.einvoicing.autosetup` makes, run on demand
        because this is the moment the agent needs the answer. Any failure
        (no network, platform error) only logs: the caller then answers with
        whatever the tenant currently holds instead of raising at the agent.
        """
        partner = company.partner_id
        if not partner or not hasattr(partner, '_fr_directory_sync_logs'):
            return partner.fr_directory_entity_type if partner else False

        try:
            with request.env.cr.savepoint():
                partner._fr_directory_sync_logs(
                    company, request.env._('WhatsApp agent status check')
                )
        except Exception as error:  # noqa: BLE001 - never break the status route
            _logger.warning(
                'Could not read the annuaire status of %s on demand: %s',
                partner.display_name,
                error,
            )

        return partner.fr_directory_entity_type
