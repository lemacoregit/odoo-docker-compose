# Copyright 2016-2024 Lema Core Technologies (http://www.lemacore.com)
# License OPL-3 or later (http://www.gnu.org/licenses/agpl.html)


{
    "name": "Lema - Sessions in Redis",
    "summary": "Store web sessions in Redis",
    "version": "18.0.1.0.0",
    "author": "Lema Core Technologies",
    "license": "OPL-3",
    "category": "Extra Tools",
    "depends": ["base"],
    "excludes": [
        "auth_session_timeout",
    ],
    "external_dependencies": {
        "python": ["redis"],
    },
    "website": "https://www.lemacore.com",
    "installable": True,
}
