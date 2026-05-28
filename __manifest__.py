{
    'name': 'Quotations & Invoices API (products by name or id)',
    'version': '19.0.1.0.9',
    'category': 'Accounting',
    'summary': 'Create quotations and invoices via API with products by name or id, fuzzy matching',
    'author': 'yowaiOtoko',
    'description': 'API endpoints to create and update quotations/invoices with product resolution by id or name and fuzzy matching.',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'product',
        'sale',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'sequence': 1,
}
