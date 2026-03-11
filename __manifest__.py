{
    'name': 'Invoice API with Fuzzy Product Matching',
    'version': '1.0.0',
    'category': 'Accounting',
    'summary': 'Create invoices via API with fuzzy product matching and confidence scores',
    'depends': [
        'account',
        'product',
    ],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
}
