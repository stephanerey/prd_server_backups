from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class OperationsStatusCliTests(unittest.TestCase):
    def test_operations_status_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["operations", "status"])
        self.assertEqual(args.command, "operations")
        self.assertEqual(args.operations_command, "status")

    def test_health_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["health"])
        self.assertEqual(args.command, "health")

    def test_cmd_health_outputs_warning_without_secrets(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["health"])
        with patch(
            "server_backup.cli.run_health_check",
            return_value={
                "status": "WARNING",
                "checks": [
                    {"severity": "SUCCESS", "code": "global-config", "message": "backup.conf is present and valid"},
                    {"severity": "WARNING", "code": "timer-enabled", "message": "server-backup.timer is not enabled"},
                ],
                "recommendations": ["Run sudo systemctl enable --now server-backup.timer"],
            },
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_health(args)

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Overall: WARNING", output)
        self.assertNotIn("RESTIC_PASSWORD_FILE", output)

    def test_cmd_operations_status_reads_summary_without_network(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["operations", "status"])
        with patch(
            "server_backup.cli._load_config_bundle",
            return_value=(
                {"BACKUP_NAME": "mes-fragrances", "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password"},
                [{"TARGET_NAME": "nas-steph"}],
                [{"PROFILE_NAME": "mes-fragrances-cis"}],
            ),
        ), patch(
            "server_backup.cli.build_operations_status",
            return_value={
                "target_count": 1,
                "profile_count": 1,
                "db_dump_count": 1,
                "timer": {"enabled": "no", "next_run": "unknown"},
                "last_backup": {"present": True, "date": "2026-05-20T00:00:00Z", "status": "success", "report": "/tmp/backup.txt"},
                "last_prune": {"present": True, "date": "2026-05-19T00:00:00Z", "status": "success", "report": "/tmp/prune.txt"},
                "last_restore_test": {"present": True, "date": "2026-05-19T00:00:00Z", "status": "warning", "report": "/tmp/restore.txt"},
                "last_coverage_audit": {"present": True, "date": "2026-05-20T00:00:00Z", "status": "success", "report": "/tmp/coverage.txt"},
                "last_email": {"present": True, "date": "2026-05-20T00:00:00Z", "status": "success", "kind": "backup"},
                "warnings": ["server-backup.timer is not enabled"],
            },
        ) as mocked_summary:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_operations_status(args)

        self.assertEqual(exit_code, 0)
        mocked_summary.assert_called_once()
        output = stdout.getvalue()
        self.assertIn("server-backup operations status", output)
        self.assertIn("db dumps: 1", output)
        self.assertIn("server-backup.timer is not enabled", output)
        self.assertNotIn("RESTIC_PASSWORD_FILE", output)


if __name__ == "__main__":
    unittest.main()
