import logging

from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _post_dispatch(cls, response):
        # The FR e-invoicing OAuth callback (l10n_fr_einvoicing) stores the
        # token and remembers the company in the session; finishing the
        # onboarding here means the token and the directory status both exist
        # before the user's browser gets the answer. `_post_dispatch` rather
        # than an override of the module's own method: this module does not
        # depend on l10n_fr_einvoicing (a tenant can have e-invoicing off), so
        # the load order of the two addons would decide the MRO — this hook
        # does not care about it.
        try:
            company_id = request.session.get('fr_ctc_company_id')
            if company_id:
                company = request.env['res.company'].sudo().browse(company_id)
                if company.exists():
                    company._smart_doc_complete_onboarding()
        except Exception as error:  # noqa: BLE001 - never break the response
            _logger.warning(
                'Could not complete the FR e-invoicing onboarding after the '
                'request: %s',
                error,
            )
        super()._post_dispatch(response)

    @classmethod
    def _auth_method_api_key(cls):
        api_key = request.httprequest.headers.get('API-KEY') or request.httprequest.environ.get('HTTP_API_KEY')
        if not api_key:
            raise AccessDenied()
        uid = request.env['res.users.apikeys']._check_credentials(scope='rpc', key=api_key)
        if not uid:
            raise AccessDenied()
        request.update_env(user=uid)
        return True
