{
    'name': 'Demo Provisioner',
    'version': '18.0.1.3.0',
    'summary': 'Provisioning and management of custom Odoo module demo databases',
    'description': """
        Module for managing custom module demo environments.
        - Input custom module name from addons path
        - Automatically provision a new database
        - Generate token URL for direct access without manual login
        - Reset demo database to its initial state
    """,
    'author': 'Lemacore',
    'website': 'https://lemacore.com',
    'category': 'Technical',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/demo_server_views.xml',
        'views/demo_registry_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
