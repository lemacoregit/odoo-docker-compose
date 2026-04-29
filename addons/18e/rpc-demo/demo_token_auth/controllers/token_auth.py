import logging
import os
import psycopg2

import werkzeug.utils
import werkzeug.exceptions

from odoo import http
from odoo.http import request
from odoo.tools import config

_logger = logging.getLogger(__name__)

# ERP database where demo_provisioner is installed and tokens are managed.
# Override via DEMO_ERP_DB_NAME environment variable (set in docker-compose).
ERP_DB_NAME = os.environ.get('DEMO_ERP_DB_NAME', 'lema_production')


class DemoTokenAuthController(http.Controller):

    @http.route(
        '/demo/access',
        type='http',
        auth='none',
        csrf=False,
        methods=['GET'],
    )
    def demo_access(self, token=None, **kwargs):
        """
        Entry point for demo URLs.
        Flow: validate token → authenticate user → redirect to /odoo
        """
        if not token or len(token) < 10:
            return self._render_error(
                'Invalid token.',
                'Please make sure you are using the correct URL provided by the admin.'
            )

        # Look up token from ERP DB
        registry = self._lookup_token_from_erp(token)
        if not registry:
            return self._render_error(
                'Token not found or no longer active.',
                'Contact the admin to get a new demo URL.'
            )

        db_name = registry['db_name']
        login = registry['demo_user_login']
        password = registry['demo_user_password']

        _logger.info(
            'Demo access: token valid → db=%s login=%s',
            db_name, login,
        )

        try:
            # Clear any existing session (old db, old uid) so it does not
            # bleed into the new authentication. Only call logout when there
            # is actually an active session to avoid side-effects on fresh
            # browser sessions.
            if request.session.uid or request.session.db:
                request.session.logout(keep_db=False)

            # Explicitly pin the session to the target database BEFORE
            # authenticate() — this is what makes Odoo use the correct db
            # even when the browser had no session at all.
            request.session.db = db_name

            credential = {
                'login': login,
                'password': password,
                'type': 'password',
            }

            auth_info = request.session.authenticate(db_name, credential)

            # Odoo 18 returns a dict, older returns uid directly
            if isinstance(auth_info, dict):
                uid = auth_info.get('uid')
            else:
                uid = auth_info

            if not uid:
                return self._render_error(
                    'Authentication failed.',
                    'Demo user not found. Contact admin to reset the demo.'
                )

            _logger.info('Demo login successful: db=%s uid=%s', db_name, uid)
            return werkzeug.utils.redirect('/odoo', 302)

        except Exception as e:
            _logger.exception('Error during demo login to db=%s: %s', db_name, e)
            return self._render_error('A server error occurred.', str(e)[:200])

    @http.route(
        ['/web/database', '/web/database/selector', '/web/database/manager'],
        type='http',
        auth='none',
        csrf=False,
        methods=['GET', 'POST'],
        save_session=False,
    )
    def block_login_pages(self, **kwargs):
        if request.session.uid:
            return request.redirect('/odoo')
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Page Not Available</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #f4f5f7; font-family: sans-serif; }
        .wrap {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 2rem;
        }
        .card {
            background: #fff;
            border-radius: 12px;
            padding: 3rem 2.5rem;
            max-width: 480px;
            width: 100%;
            box-shadow: 0 2px 16px rgba(0,0,0,0.08);
            text-align: center;
        }
        .icon { font-size: 3rem; margin-bottom: 1rem; }
        h2 { font-size: 1.4rem; font-weight: 600; color: #2c3e50; margin-bottom: 0.75rem; }
        p { color: #666; line-height: 1.6; margin-bottom: 1.5rem; }
        .btn {
            display: inline-block;
            padding: 0.75rem 2rem;
            background: #875A7B;
            color: #fff;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
        }
        .btn:hover { background: #6b4763; }
        hr { border: none; border-top: 1px solid #eee; margin: 1.5rem 0; }
        .note { font-size: 0.85rem; color: #999; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="card">
            <div class="icon">&#128274;</div>
            <h2>This Page Is Not Available</h2>
            <p>
                Access to the database manager is not permitted.<br/>
                If you'd like to try our product demo, please visit our website.
            </p>
            <a href="https://lemacore.com" class="btn" target="_blank">Visit Lemacore.com</a>
            <hr/>
            <p class="note">
                Already have a demo link? Use the link provided by our team to sign in directly.
            </p>
        </div>
    </div>
</body>
</html>"""
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
        ])

    def _lookup_token_from_erp(self, token):
        """
        Query the ERP database directly via psycopg2 to validate the token.
        Uses the same DB connection (shared PostgreSQL).
        """
        try:
            conn = psycopg2.connect(
                host=config.get('db_host', 'postgres'),
                port=int(config.get('db_port', 5432)),
                user=config.get('db_user', 'odoo'),
                password=config.get('db_password', ''),
                dbname=ERP_DB_NAME,
                connect_timeout=5,
                options='-c statement_timeout=5000',
            )
            conn.set_session(readonly=True, autocommit=True)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        db_name,
                        demo_user_login,
                        demo_user_password
                    FROM demo_registry
                    WHERE
                        token = %s
                        AND state = 'active'
                    LIMIT 1
                """, (token,))
                row = cur.fetchone()

            conn.close()

            if row:
                return {
                    'db_name': row[0],
                    'demo_user_login': row[1],
                    'demo_user_password': row[2],
                }

        except psycopg2.OperationalError as e:
            _logger.error(
                'Cannot connect to ERP database "%s": %s',
                ERP_DB_NAME, e
            )
        except Exception as e:
            _logger.exception('Token lookup error: %s', e)

        return None

    def _render_error(self, title, message):
        """Render a clean error page using inline HTML."""
        html = f"""<!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Demo Error</title>
    <style>
    body {{ background:#f4f5f7; font-family:sans-serif; }}
    .wrap {{ display:flex; align-items:center; justify-content:center; min-height:100vh; }}
    .card {{ background:#fff; border-radius:12px; padding:3rem; max-width:480px;
            width:100%; box-shadow:0 2px 16px rgba(0,0,0,.08); text-align:center; }}
    h2 {{ color:#2c3e50; }} p {{ color:#666; }}
    a {{ display:inline-block; margin-top:1rem; padding:.75rem 2rem;
        background:#875A7B; color:#fff; border-radius:6px; text-decoration:none; }}
    </style>
    </head>
    <body><div class="wrap"><div class="card">
    <div style="font-size:3rem;color:#e74c3c">&#9888;</div>
    <h2>{title}</h2>
    <p>{message}</p>
    <a href="https://lemacore.com">Back to Lemacore</a>
    </div></div></body>
    </html>"""
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
        ], status=400)
