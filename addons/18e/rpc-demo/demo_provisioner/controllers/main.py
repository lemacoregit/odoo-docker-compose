import logging
import os
import tarfile
import tempfile
import zipfile
from datetime import datetime

from odoo import http
from odoo.http import request
from odoo.tools import config

_logger = logging.getLogger(__name__)


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
                # ── 1. pg_dump plain SQL → stdout (no file written in container) ──
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

                # ── 2. filestore (skipped silently if directory not found) ──
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
