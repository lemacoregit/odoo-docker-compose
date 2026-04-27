# Copyright 2016-2024 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)


{
    "name": "Lema - Sessions in Redis",
    "summary": "Store web sessions in Redis",
    "version": "18.0.1.0.0",
    "author": "Lema Core Technologies",
    "license": "AGPL-3",
    "category": "Extra Tools",
    "depends": ["base"],
    "excludes": [
        "auth_session_timeout",
    ],
    "external_dependencies": {
        "python": ["redis"],
    },
    "website": "https://lemacore.com",
    "installable": True,
}
