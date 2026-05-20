from __future__ import annotations

import unittest

from server_backup.config import parse_config_file
from server_backup.wizard import generate_restic_password, render_backup_conf


class WizardRenderingTests(unittest.TestCase):
    def test_render_backup_conf_contains_expected_fields(self) -> None:
        rendered = render_backup_conf(
            {
                "BACKUP_NAME": "my-host",
                "BACKUP_TAGS": "my-host prod",
                "RETENTION_DAILY": 14,
                "RETENTION_WEEKLY": 8,
                "RETENTION_MONTHLY": 12,
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": "/var/lib/server-backup/state",
                "REPORT_DIR": "/var/lib/server-backup/reports",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RUN_RESTIC_CHECK": True,
                "RUN_PRUNE": True,
                "RUN_COVERAGE_AUDIT": True,
                "COVERAGE_AUDIT_FAIL_ON_FAILURE": True,
                "COVERAGE_AUDIT_FAIL_ON_WARNING": False,
                "EMAIL_REPORT_ENABLED": False,
                "EMAIL_REPORT_TO": "",
                "EMAIL_REPORT_FROM": "",
                "EMAIL_REPORT_SUBJECT_PREFIX": "[server-backup]",
                "EMAIL_REPORT_SEND_ON_SUCCESS": True,
                "EMAIL_REPORT_SEND_ON_FAILURE": True,
                "EMAIL_REPORT_COMMAND": "sendmail",
            },
            generated_at="2026-01-01T00:00:00Z",
        )

        self.assertIn('CONFIG_VERSION="1"', rendered)
        self.assertIn('BACKUP_NAME="my-host"', rendered)
        self.assertIn('EMAIL_REPORT_ENABLED="false"', rendered)

    def test_render_backup_conf_quotes_strings(self) -> None:
        rendered = render_backup_conf(
            {
                "BACKUP_NAME": 'host "quoted"',
                "BACKUP_TAGS": "a b",
                "RETENTION_DAILY": 14,
                "RETENTION_WEEKLY": 8,
                "RETENTION_MONTHLY": 12,
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": "/var/lib/server-backup/state",
                "REPORT_DIR": "/var/lib/server-backup/reports",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RUN_RESTIC_CHECK": True,
                "RUN_PRUNE": True,
                "RUN_COVERAGE_AUDIT": True,
                "COVERAGE_AUDIT_FAIL_ON_FAILURE": True,
                "COVERAGE_AUDIT_FAIL_ON_WARNING": False,
                "EMAIL_REPORT_ENABLED": False,
                "EMAIL_REPORT_TO": "",
                "EMAIL_REPORT_FROM": "",
                "EMAIL_REPORT_SUBJECT_PREFIX": "[server-backup]",
                "EMAIL_REPORT_SEND_ON_SUCCESS": True,
                "EMAIL_REPORT_SEND_ON_FAILURE": True,
                "EMAIL_REPORT_COMMAND": "sendmail",
            }
        )
        self.assertIn('BACKUP_NAME="host \\"quoted\\""', rendered)

    def test_generate_restic_password_length(self) -> None:
        password = generate_restic_password()
        self.assertGreaterEqual(len(password), 32)
        self.assertTrue(password.strip())

    def test_rendered_backup_conf_is_parsable(self) -> None:
        rendered = render_backup_conf(
            {
                "BACKUP_NAME": "my-host",
                "BACKUP_TAGS": "my-host",
                "RETENTION_DAILY": 14,
                "RETENTION_WEEKLY": 8,
                "RETENTION_MONTHLY": 12,
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": "/var/lib/server-backup/state",
                "REPORT_DIR": "/var/lib/server-backup/reports",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RUN_RESTIC_CHECK": True,
                "RUN_PRUNE": True,
                "RUN_COVERAGE_AUDIT": True,
                "COVERAGE_AUDIT_FAIL_ON_FAILURE": True,
                "COVERAGE_AUDIT_FAIL_ON_WARNING": False,
                "EMAIL_REPORT_ENABLED": False,
                "EMAIL_REPORT_TO": "",
                "EMAIL_REPORT_FROM": "",
                "EMAIL_REPORT_SUBJECT_PREFIX": "[server-backup]",
                "EMAIL_REPORT_SEND_ON_SUCCESS": True,
                "EMAIL_REPORT_SEND_ON_FAILURE": True,
                "EMAIL_REPORT_COMMAND": "sendmail",
            }
        )
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.conf"
            path.write_text(rendered, encoding="utf-8")
            parsed = parse_config_file(path)

        self.assertEqual(parsed["BACKUP_NAME"], "my-host")
        self.assertEqual(parsed["EMAIL_REPORT_ENABLED"], "false")
        self.assertEqual(parsed["CONFIG_VERSION"], "1")


if __name__ == "__main__":
    unittest.main()
