from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class ValidationCliTests(unittest.TestCase):
    def test_validate_production_parser_supports_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "validate",
                "production",
                "--target",
                "nas-steph",
                "--profile",
                "mes-fragrances-cis",
                "--email-test",
                "--restore-test",
                "--backup-dry-run",
            ]
        )
        self.assertEqual(args.command, "validate")
        self.assertEqual(args.validate_command, "production")
        self.assertEqual(args.target, "nas-steph")
        self.assertEqual(args.profile, "mes-fragrances-cis")
        self.assertTrue(args.email_test)
        self.assertTrue(args.restore_test)
        self.assertTrue(args.backup_dry_run)

    def test_cmd_validate_production_calls_runner(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["validate", "production", "--target", "nas-steph"])
        with patch(
            "server_backup.cli.run_production_validation",
            return_value={
                "target_name": "nas-steph",
                "profile_name": "",
                "status": "warning",
                "checks": [{"name": "health", "status": "warning", "summary": "timer disabled"}],
                "warnings": ["timer disabled"],
                "errors": [],
                "text_report_path": "/tmp/validation.txt",
                "json_report_path": "/tmp/validation.json",
            },
        ) as mocked_run:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_validate_production(args)

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once_with(
            target_name="nas-steph",
            profile_name=None,
            email_test=False,
            restore_test=False,
            backup_dry_run=False,
        )
        self.assertIn("server-backup validate production", stdout.getvalue())

    def test_status_reads_last_production_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir()
            last_path = state_dir / "last-production-validation.json"
            last_path.write_text(
                json.dumps(
                    {
                        "end_time": "2026-05-20T10:00:00Z",
                        "status": "success",
                        "text_report_path": "/tmp/production-validation.txt",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            global_config = {
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "mes-fragrances",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "RUN_RESTIC_CHECK": "true",
                "RUN_PRUNE": "true",
                "RUN_COVERAGE_AUDIT": "true",
                "EMAIL_REPORT_ENABLED": "false",
                "EMAIL_REPORT_COMMAND": "sendmail",
                "EMAIL_REPORT_TO": "",
                "RESTIC_PASSWORD_FILE": "/tmp/restic-password",
                "STATE_DIR": str(state_dir),
            }
            parser = build_parser()
            args = parser.parse_args(["status"])
            with patch("server_backup.cli._load_config_bundle", return_value=(global_config, [], [])), patch(
                "server_backup.cli._safe_exists",
                return_value=True,
            ), patch(
                "server_backup.cli._is_accessible",
                return_value=True,
            ), patch(
                "server_backup.cli._timer_enabled_status",
                return_value=("no", "disabled"),
            ), patch(
                "server_backup.cli._timer_next_run",
                return_value=("unknown", "next run not available"),
            ), patch(
                "server_backup.cli.config_file_exists",
                return_value=True,
            ), patch(
                "server_backup.cli.build_operations_status",
                return_value=None,
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = cli.cmd_status(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Last Production Validation:", stdout.getvalue())
        self.assertIn("status: success", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
