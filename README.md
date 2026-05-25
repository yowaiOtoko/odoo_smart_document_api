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

Typical create response:

```json
{
  "id": 42,
  "name": "INV/2026/0001",
  "invoice_id": 42,
  "invoice_name": "INV/2026/0001"
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
