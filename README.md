# Quotations & Invoices API (products by name or id)

Odoo addon to create **quotations** (sale.order) and **customer invoices** (account.move) from a single request. Line items can specify products by **id** or by **name**; the backend resolves or creates products and then creates the document using standard Odoo logic.

## Features

- **Single request**: Create a quotation or an invoice with a list of products in one call. No client-side product resolution or multiple RPCs.
- **Product by id or name**: Each line can use ``product_id`` (existing product) or ``product_name`` (search or create).
- **Name matching**: When using a name, the backend uses FTS + trigram fuzzy matching (French). If no acceptable match is found, a new product is created with a default UoM (service product → any product → first UoM).
- **Idempotency**: The same product name in one request resolves to the same product; repeated calls reuse existing products.
- **RPC**: The same logic is available as model methods ``sale.order.create_quotation(header_vals, line_items)`` and ``account.move.create_invoice(header_vals, line_items)`` for XML-RPC/JSON-RPC.

## HTTP endpoints

Both routes expect **JSON** body, **POST**, and use ``auth='api_key'`` (configure API key auth in Odoo). **CSRF** is disabled for these routes.

### Create customer invoice

**POST** ``/api/invoice``

**Request body**

+---------------------+------+----------+----------------------------------------+
| Field               | Type | Required | Description                            |
+=====================+======+==========+========================================+
| partner_id          | int  | yes      | Partner (customer) id                  |
+---------------------+------+----------+----------------------------------------+
| items               | list | yes      | Line items (see below)                 |
+---------------------+------+----------+----------------------------------------+
| company_id          | int  | no       | Company id (default: current company)  |
+---------------------+------+----------+----------------------------------------+
| journal_id          | int  | no       | Journal id                             |
+---------------------+------+----------+----------------------------------------+
| invoice_date        | date | no       | Invoice date                           |
+---------------------+------+----------+----------------------------------------+
| payment_reference   | str  | no       | Payment reference                      |
+---------------------+------+----------+----------------------------------------+

**Line item** (each element of ``items``): specify the product **either** by ``product_id`` **or** by ``product_name`` (or legacy ``name``).

+------------------------+--------+----------+------------------------------------------------------------------+
| Field                  | Type   | Required | Description                                                      |
+========================+========+==========+==================================================================+
| product_id             | int    | no*      | Product (variant) id. If present, this line is resolved by id.   |
+------------------------+--------+----------+------------------------------------------------------------------+
| product_name or name   | str    | no*      | Product name for search/create. Used when product_id is not set. |
+------------------------+--------+----------+------------------------------------------------------------------+
| quantity or qty        | number | no       | Quantity (default 1)                                             |
+------------------------+--------+----------+------------------------------------------------------------------+
| price_unit or price    | number | no       | Unit price (default: product list price)                         |
+------------------------+--------+----------+------------------------------------------------------------------+
| discount               | number | no       | Discount (%)                                                     |
+------------------------+--------+----------+------------------------------------------------------------------+
| name / description     | str    | no       | Line description                                                 |
+------------------------+--------+----------+------------------------------------------------------------------+

\* Each line must have either ``product_id`` or ``product_name``/``name``.

**Success response**

::


  {
    "id": 42,
    "name": "INV/2025/0001",
    "invoice_id": 42,
    "invoice_name": "INV/2025/0001"
  }

**Error response**

::


  {
    "error": "Invalid payload"
  }

or

::


  {
    "error": "Product with id 999 not found or not usable."
  }

---

### Create quotation


**POST** ``/api/quotation``

**Request body**

+----------------+------+----------+--------------------------------------------------+
| Field          | Type | Required | Description                                      |
+================+======+==========+==================================================+
| partner_id     | int  | yes      | Partner (customer) id                            |
+----------------+------+----------+--------------------------------------------------+
| items          | list | yes      | Line items (same shape as invoice)               |
+----------------+------+----------+--------------------------------------------------+
| company_id     | int  | no       | Company id (default: current company)            |
+----------------+------+----------+--------------------------------------------------+
| validity_date  | date | no       | Quotation validity date                          |
+----------------+------+----------+--------------------------------------------------+

**Line item**: same as for invoice (see above).

**Success response**

::


  {
    "id": 10,
    "name": "S00010",
    "quotation_id": 10,
    "quotation_name": "S00010"
  }

**Error response**: same structure as invoice (``{"error": "..."}``).

## Example

Create an invoice with one line by product id and one by name:

::


  POST /api/invoice
  {
    "partner_id": 5,
    "items": [
      { "product_id": 12, "quantity": 2, "price_unit": 100 },
      { "product_name": "Consulting heure", "quantity": 1, "price_unit": 80 }
    ]
  }

## Dependencies

- ``account``
- ``product``
- ``sale``

## Installation

Install the addon in your Odoo instance and ensure API key authentication is configured if you use the HTTP endpoints.

**Repo name:** To match the addon name, you can rename this repository (e.g. to ``odoo_quotation_invoice_api``) in your Git host settings (e.g. GitHub: Settings → General → Repository name). The addon directory name does not need to match.
