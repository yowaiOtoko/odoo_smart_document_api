# Quotations and Invoices API

Odoo 19 module to create, update, and fetch quotations and customer invoices through API routes. Product lines can be resolved by product id or product name (with fuzzy matching).

## What this module provides

- Create quotation: POST /api/quotation
- Update quotation: POST /api/quotation/update
- Get quotation: POST /api/quotation/get
- Create invoice: POST /api/invoice
- Update invoice: POST /api/invoice/update
- Get invoice: POST /api/invoice/get
- Mark invoice as paid: POST /api/invoice/set_paid
- Health and capability check: POST /api/status

All routes use:

- auth='api_key'
- methods=['POST']
- type='jsonrpc'
- csrf=False

## Magic link login (token link auth)

Send a single-use, expiring link so a user can open an Odoo web session
without entering credentials.

- Create token: POST /api/token_link (auth='api_key')
- Revoke token: POST /api/token_link/revoke (auth='api_key')
- Consume link: GET /smart-doc/login/<token> (auth='public')

### Create a token

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "user_id": 2,
    "expires_in": 24,
    "redirect": "/web#id=5&model=account.move&view_type=form"
  },
  "id": 1
}
```

- `user_id`: existing internal `res.users` id (required).
- `expires_in`: token lifetime in hours (default 24, clamped 1..168).
- `redirect`: optional same-host relative path used after login
  (open-redirect guard rejects absolute/external URLs). Defaults to `/web`.

Response:

```json
{
  "token": "9b3L...",
  "path": "/smart-doc/login/9b3L...",
  "url": "https://odoo.example.com/smart-doc/login/9b3L...",
  "user_id": 2,
  "expires_at": "2026-08-02T10:00:00+00:00"
}
```

Send `url` to the user. Opening it logs the user into the Odoo web client
and redirects to `redirect` (or the web home). The token works once and
expires automatically; only the SHA-256 hash of the token is stored.

### Revoke a token

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {"token": "9b3L..."},
  "id": 2
}
```

## Installation

1. Copy module into your custom addons path.
2. Update apps list in Odoo.
3. Install module: Quotations and Invoices API.
4. Ensure API key auth is enabled in your Odoo deployment.
5. Generate API key for integration user.

## Permissions needed

Integration user should have rights to:

- Contacts (read/create partners)
- Sales (quotation read/write/create)
- Invoicing (invoice read/write/create, payment registration)
- Products (read/create when product name fallback creates missing product)

If user has missing ACLs, API returns error with Odoo exception message.

## JSON-RPC request format

Because routes use type='jsonrpc', send payload with params object.

Example envelope:

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "partner_id": 5,
    "items": [
      {"product_id": 12, "quantity": 2, "price_unit": 100}
    ]
  },
  "id": 1
}
```

## Example payloads

### Create invoice

Route: POST /api/invoice

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "partner_id": 5,
    "company_id": 1,
    "invoice_date": "2026-05-25",
    "payment_reference": "WHATSAPP-INV-001",
    "items": [
      {"product_id": 12, "quantity": 2, "price_unit": 100},
      {"product_name": "Consulting hour", "quantity": 1, "price_unit": 80}
    ]
  },
  "id": 2
}
```

### Create quotation

Route: POST /api/quotation

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "partner_id": 5,
    "validity_date": "2026-06-30",
    "items": [
      {"product_name": "Onboarding package", "quantity": 1, "price_unit": 300}
    ]
  },
  "id": 3
}
```

### Update invoice header and lines

Route: POST /api/invoice/update

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "id": 42,
    "header": {
      "payment_reference": "WHATSAPP-INV-001-UPDATED"
    },
    "items_to_add": [
      {"product_name": "Extra service", "quantity": 1, "price_unit": 50}
    ],
    "items_to_update": [],
    "items_to_remove": []
  },
  "id": 4
}
```

### Set invoice paid

Route: POST /api/invoice/set_paid

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "id": 42,
    "journal_id": 7,
    "amount": 280.0,
    "payment_date": "2026-05-25",
    "reference": "PAID-WHATSAPP"
  },
  "id": 5
}
```

## Successful responses

Create responses (`/api/invoice`, `/api/quotation`) return the created document
with the same payload as `/api/invoice/get` and `/api/quotation/get`
(`document`, `partner`, `lines`), so no read-back call is needed. The flat
`id`/`name` keys are kept for callers written against older versions.

```json
{
  "id": 42,
  "name": "INV/2026/0001",
  "invoice_id": 42,
  "invoice_name": "INV/2026/0001",
  "document": {
    "id": 42,
    "name": "INV/2026/0001",
    "state": "draft",
    "payment_state": "not_paid",
    "invoice_date": "2026-05-25",
    "invoice_date_due": "2026-06-24",
    "amount_untaxed": 280.0,
    "amount_total": 336.0,
    "amount_tax": 56.0,
    "amount_residual": 336.0
  },
  "partner": {"id": 5, "name": "ACME", "country_code": "FR"},
  "lines": [{"id": 77, "name": "Consulting hour", "quantity": 1, "price_unit": 80.0, "price_subtotal": 80.0}]
}
```

## Error responses

Typical error shape:

```json
{
  "error": "Invalid payload"
}
```

Other frequent errors:

- Missing partner_id or empty items
- Product id not found
- Missing rights on account.move or sale.order
- Validation errors from business rules
