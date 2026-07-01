# -*- coding: utf-8 -*-
{
    'name': "Lema Bypass",
    'author': "Odoo",
    'website': "https://www.lemacore.com",
    'category': 'Extra Tools',
    'version': '18.0.0.0.1',
    'depends': ['web', 'web_enterprise', 'mail'],
    'assets':{
        'web.assets_backend': [
            'lm_bypass/static/src/**/*',
        ]
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'OPL-1',
}
