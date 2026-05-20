from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class BackupCliTests(unittest.TestCase):
    def test_backup_run_parser_supports_dry_run_target_and_profile(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["backup", "run", "--dry-run", "--target", "nas-steph", "--profile", "safe-profile"]
        )
        self.assertEqual(args.command, "backup")
        self.assertEqual(args.backup_command, "run")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.target, "nas-steph")
        self.assertEqual(args.profile, "safe-profile")

    def test_cmd_backup_run_calls_run_backup(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["backup", "run", "--dry-run", "--target", "nas-steph"])

        with patch(
            "server_backup.cli.run_backup",
            return_value={
                "targets_requested": 1,
                "profiles_requested": 1,
                "dry_run": True,
                "status": "success",
                "target_results": [],
                "text_report_path": "/var/lib/server-backup/reports/report.txt",
                "json_report_path": "/var/lib/server-backup/reports/report.json",
            },
        ) as mocked_run:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_backup_run(args)

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once_with(dry_run=True, target_name="nas-steph", profile_name=None)
        self.assertIn("Dry-run: yes", stdout.getvalue())

    def test_cmd_backup_run_returns_non_zero_on_failure(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["backup", "run", "--profile", "missing-profile"])

        with patch(
            "server_backup.cli.run_backup",
            return_value={
                "targets_requested": 1,
                "profiles_requested": 0,
                "dry_run": False,
                "status": "failure",
                "target_results": [],
                "text_report_path": "/var/lib/server-backup/reports/report.txt",
                "json_report_path": "/var/lib/server-backup/reports/report.json",
            },
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_backup_run(args)

        self.assertEqual(exit_code, 1)

    def test_cmd_backup_run_returns_non_zero_on_interrupt_without_stacktrace(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["backup", "run", "--dry-run", "--target", "nas-steph"])

        with patch(
            "server_backup.cli.run_backup",
            return_value={
                "targets_requested": 1,
                "profiles_requested": 1,
                "dry_run": True,
                "status": "interrupted",
                "warnings": [],
                "errors": ["Operation interrupted by user. No report may have been completed."],
                "target_results": [],
                "text_report_path": "/var/lib/server-backup/reports/report.txt",
                "json_report_path": "/var/lib/server-backup/reports/report.json",
            },
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_backup_run(args)

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Operation interrupted by user. No report may have been completed.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
