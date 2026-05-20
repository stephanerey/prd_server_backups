from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.email_report import (
    build_email_message,
    build_email_subject,
    sanitize_email_body,
    send_test_email,
    send_with_mail,
    send_with_sendmail,
    should_send_email,
)
from server_backup.validators import validate_global_config


class EmailReportTests(unittest.TestCase):
    def test_build_email_subject(self) -> None:
        subject = build_email_subject("backup", "success", "vps-51ab13bd", "host1")
        self.assertEqual(subject, "[server-backup] SUCCESS backup vps-51ab13bd on host1")

    def test_build_email_message_and_redaction(self) -> None:
        body = "Status: OK\nRESTIC_PASSWORD_FILE=/etc/server-backup/secrets/restic-password\nPGPASSWORD=secret\n"
        message = build_email_message("admin@example.net", "server@example.net", "Subject", body)
        self.assertIn("To: admin@example.net", message)
        self.assertIn("From: server@example.net", message)
        self.assertIn("Subject: Subject", message)
        self.assertNotIn("RESTIC_PASSWORD_FILE=/etc/server-backup/secrets/restic-password", message)
        self.assertNotIn("PGPASSWORD=secret", message)
        self.assertIn("<redacted>", message)

    def test_sanitize_email_body_redacts_sensitive_tokens(self) -> None:
        text = "TOKEN=value\nregular line\nSSH_IDENTITY_FILE=/etc/server-backup/ssh/id_ed25519\n"
        sanitized = sanitize_email_body(text)
        self.assertEqual(sanitized.count("<redacted>"), 2)
        self.assertIn("regular line", sanitized)

    def test_should_send_email_success_and_failure(self) -> None:
        email_config = {
            "enabled": True,
            "send_on_success": False,
            "send_on_failure": True,
        }
        self.assertFalse(should_send_email("success", email_config))
        self.assertTrue(should_send_email("warning", email_config))
        self.assertTrue(should_send_email("failure", email_config))

    def test_send_with_sendmail_uses_shell_false(self) -> None:
        with patch("server_backup.email_report._locate_sendmail", return_value="/usr/sbin/sendmail"), patch(
            "server_backup.email_report.subprocess.run"
        ) as mocked_run:
            mocked_run.return_value.returncode = 0
            send_with_sendmail("message", "server@example.net")

        args, kwargs = mocked_run.call_args
        self.assertEqual(args[0], ["/usr/sbin/sendmail", "-t", "-f", "server@example.net"])
        self.assertEqual(kwargs["shell"], False)

    def test_send_with_mail_uses_shell_false(self) -> None:
        with patch("server_backup.email_report._locate_mail_command", return_value="/usr/bin/mail"), patch(
            "server_backup.email_report.subprocess.run"
        ) as mocked_run:
            mocked_run.return_value.returncode = 0
            send_with_mail("admin@example.net", "server@example.net", "Subject", "Body")

        _, kwargs = mocked_run.call_args
        self.assertEqual(kwargs["shell"], False)

    def test_send_test_email_can_run_when_automatic_email_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.email_report.send_with_sendmail"
        ) as mocked_sendmail:
            mocked_sendmail.return_value.returncode = 0
            mocked_sendmail.return_value.stdout = ""
            mocked_sendmail.return_value.stderr = ""
            result = send_test_email(
                {
                    "EMAIL_REPORT_ENABLED": "false",
                    "EMAIL_REPORT_TO": "",
                    "EMAIL_REPORT_FROM": "server@example.net",
                    "EMAIL_REPORT_COMMAND": "sendmail",
                    "EMAIL_REPORT_SUBJECT_PREFIX": "[server-backup]",
                    "BACKUP_NAME": "vps-51ab13bd",
                    "STATE_DIR": str(Path(tmpdir) / "state"),
                },
                to_override="admin@example.net",
            )

        self.assertTrue(result["success"])

    def test_send_test_email_falls_back_to_hostname_sender(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.email_report.send_with_sendmail"
        ) as mocked_sendmail:
            mocked_sendmail.return_value.returncode = 0
            mocked_sendmail.return_value.stdout = ""
            mocked_sendmail.return_value.stderr = ""
            result = send_test_email(
                {
                    "EMAIL_REPORT_ENABLED": "false",
                    "EMAIL_REPORT_TO": "admin@example.net",
                    "EMAIL_REPORT_FROM": "",
                    "EMAIL_REPORT_COMMAND": "sendmail",
                    "BACKUP_NAME": "vps-51ab13bd",
                    "STATE_DIR": str(Path(tmpdir) / "state"),
                }
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["from"].startswith("server-backup@"))

    def test_validate_global_config_requires_email_fields_only_when_enabled(self) -> None:
        enabled_result = validate_global_config(
            {
                "__file__": "/etc/server-backup/backup.conf",
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "vps",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": "/var/lib/server-backup/state",
                "REPORT_DIR": "/var/lib/server-backup/reports",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RUN_RESTIC_CHECK": "true",
                "RUN_PRUNE": "true",
                "EMAIL_REPORT_ENABLED": "true",
                "EMAIL_REPORT_TO": "",
                "EMAIL_REPORT_FROM": "",
                "EMAIL_REPORT_COMMAND": "",
            }
        )
        disabled_result = validate_global_config(
            {
                "__file__": "/etc/server-backup/backup.conf",
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "vps",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": "/var/lib/server-backup/state",
                "REPORT_DIR": "/var/lib/server-backup/reports",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RUN_RESTIC_CHECK": "true",
                "RUN_PRUNE": "true",
                "EMAIL_REPORT_ENABLED": "false",
            }
        )
        self.assertTrue(enabled_result.errors)
        self.assertEqual(disabled_result.errors, [])


if __name__ == "__main__":
    unittest.main()
