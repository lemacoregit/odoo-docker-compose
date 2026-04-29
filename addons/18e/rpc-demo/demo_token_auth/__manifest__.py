{
    'name': 'Demo Token Auth',
    'version': '18.0.1.0.0',
    'summary': 'Token-based auto-login for the lemacore.com demo server',
    'description': """
        Installed on the demo server (demo.lemacore.com).
        Handles URL: demo.lemacore.com/demo/access?token=xxx
        - Validates token from the ERP database
        - Auto-logs in the demo user to the corresponding database
        - Redirects directly to Odoo without a login form
    """,
    'author': 'Lemacore',
    'website': 'https://lemacore.com',
    'category': 'Technical',
    'depends': ['base', 'web'],
    'data': [
        'views/token_login_template.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
