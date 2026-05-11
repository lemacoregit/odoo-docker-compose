import json
import logging
import os
import psycopg2
import tarfile
import tempfile
import zipfile
from datetime import datetime

from odoo import http
from odoo.http import request
from odoo.tools import config

_logger = logging.getLogger(__name__)


def _build_manifest(registry):
    """
    Generate an Odoo-compatible manifest.json by querying the demo database directly.
    Matches the format produced by Odoo's own backup tool (odoo/service/db.py).
    """
    conn = psycopg2.connect(
        host=config.get('db_host', 'localhost'),
        port=int(config.get('db_port', 5432)),
        user=config.get('db_user', 'odoo'),
        password=config.get('db_password', ''),
        dbname=registry.db_name,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version')")
            pg_version = cur.fetchone()[0]

            cur.execute(
                'SELECT name, latest_version FROM ir_module_module WHERE state = %s',
                ('installed',),
            )
            modules = {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    odoo_version = (registry.server_id.odoo_version or '18.0').strip()
    try:
        major = int(odoo_version.split('.')[0])
    except (ValueError, IndexError):
        major = 18

    manifest = {
        'odoo_dump': '1',
        'db_name': registry.db_name,
        'version': odoo_version,
        'version_info': [major, 0, 0, 'final', 0, ''],
        'major_version': odoo_version,
        'pg_version': pg_version,
        'modules': modules,
    }
    return json.dumps(manifest, indent=4)


class DemoProvisionerController(http.Controller):

    @http.route('/demo/registry/status', type='json', auth='user')
    def registry_status(self, registry_id=None, **kwargs):
        """Endpoint for checking the status of a demo registry record. Expects a JSON request with 'registry_id'."""
        if not registry_id:
            return {'error': 'registry_id required'}

        record = request.env['demo.registry'].sudo().browse(int(registry_id))
        if not record.exists():
            return {'error': 'Record tidak ditemukan'}

        return {
            'state': record.state,
            'demo_url': record.demo_url,
            'provision_log': (record.provision_log or '')[-1000:],
        }

    @http.route('/demo/backup/download/<int:registry_id>', type='http', auth='user', methods=['GET'])
    def download_backup(self, registry_id, **kwargs):
        """
        Generate and stream an Odoo-compatible .zip backup of the demo database.
        Contains dump.sql (plain SQL) + filestore/ directory.
        Nothing is written to the provisioner database or disk — generated fully on-the-fly.
        """
        from ..models.demo_registry import _docker_client

        registry = request.env['demo.registry'].browse(registry_id)
        if not registry.exists() or registry.state != 'active':
            return request.not_found()

        tmp_path = None
        tar_path = None
        try:
            client = _docker_client()
            try:
                container = client.containers.get(registry.server_id.container_name)
            except Exception as e:
                raise Exception(
                    f'Container "{registry.server_id.container_name}" not found or not running: {e}'
                )

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'{registry.db_name}_{timestamp}.zip'

            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip')
            os.close(tmp_fd)

            with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # ── 1. manifest.json (Odoo-compatible metadata) ──────────────
                manifest_json = _build_manifest(registry)
                zf.writestr('manifest.json', manifest_json)

                # ── 2. pg_dump plain SQL → stdout (nothing written in container) ──
                result = container.exec_run(
                    [
                        'pg_dump',
                        '-h', config.get('db_host', 'postgres'),
                        '-U', config.get('db_user', 'odoo'),
                        '--format=plain',
                        '--no-owner',
                        '--no-privileges',
                        registry.db_name,
                    ],
                    stdout=True,
                    stderr=False,
                    environment={
                        'PGPASSWORD': config.get('db_password', ''),
                        'LANG': 'C',
                    },
                )
                if result.exit_code not in (0, None):
                    raise Exception(
                        f'pg_dump failed (exit {result.exit_code}). '
                        'Check container logs for details.'
                    )
                zf.writestr('dump.sql', result.output or b'')

                # ── 3. filestore (skipped gracefully if directory not found) ──
                filestore_base = (
                    registry.server_id.filestore_base or '/var/lib/odoo/filestore'
                ).rstrip('/')
                filestore_path = f'{filestore_base}/{registry.db_name}'

                check = container.exec_run(
                    ['test', '-d', filestore_path],
                    stdout=False,
                    stderr=False,
                )
                if check.exit_code == 0:
                    bits, _ = container.get_archive(filestore_path)

                    tar_fd, tar_path = tempfile.mkstemp(suffix='.tar')
                    os.close(tar_fd)
                    with open(tar_path, 'wb') as tar_file:
                        for chunk in bits:
                            tar_file.write(chunk)

                    with tarfile.open(tar_path) as tf:
                        for member in tf.getmembers():
                            if not member.isfile():
                                continue
                            parts = member.name.split('/', 1)
                            if len(parts) < 2:
                                continue
                            fobj = tf.extractfile(member)
                            if fobj:
                                zf.writestr(f'filestore/{parts[1]}', fobj.read())
                else:
                    _logger.warning(
                        'Filestore not found at %s for db %s — '
                        'check "Filestore Base Path" in Demo Server settings.',
                        filestore_path, registry.db_name,
                    )

            file_size = os.path.getsize(tmp_path)
            with open(tmp_path, 'rb') as f:
                data = f.read()

            _logger.info(
                'Backup download: %s (%s bytes) for registry %s',
                filename, file_size, registry_id,
            )

            return request.make_response(
                data,
                headers=[
                    ('Content-Type', 'application/zip'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', str(file_size)),
                ],
            )

        except Exception:
            _logger.exception('Backup download failed for registry %s', registry_id)
            raise

        finally:
            for path in (tmp_path, tar_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
