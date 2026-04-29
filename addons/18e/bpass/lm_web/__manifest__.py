# -*- coding: utf-8 -*-
{
    "name": "Lema Web",
    'author': "Lema Core Technologies",
    'website': "https://www.lemacore.com",
    'version': '1.0',
    "category": "Extra Tools",
    'license': 'OPL-1',
    "summary": "Replace default web routing behavior",
    "depends": ["web",'base','website'],
    "data": [
        'data/data.xml',
        'views/ir_config_parameter_views.xml',
        'views/website_templates.xml',
      ],
    "assets": {
        "web.assets_backend": [
            "lm_web/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    'uninstall_hook': '_uninstall_cleanup',
}
