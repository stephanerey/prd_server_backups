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


class CoverageCliTests(unittest.TestCase):
    def test_coverage_audit_parser_supports_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["coverage", "audit", "--json", "--profile", "cis-site", "--output-dir", "/tmp/report-dir"])
        self.assertEqual(args.command, "coverage")
        self.assertEqual(args.coverage_command, "audit")
        self.assertTrue(args.json)
        self.assertEqual(args.profile, "cis-site")
        self.assertEqual(args.output_dir, "/tmp/report-dir")

    def test_cmd_coverage_audit_calls_run_coverage_audit(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["coverage", "audit", "--profile", "cis-site"])
        with patch(
            "server_backup.cli.run_coverage_audit",
            return_value={
                "targets_count": 1,
                "profiles_count": 1,
                "status": "warning",
                "summary": {"SUCCESS": 0, "WARNING": 1, "FAILURE": 0},
                "generic_findings": [],
                "target_findings": [],
                "profile_findings": [{"severity": "WARNING", "code": "x", "message": "warning"}],
                "docker_findings": [],
                "cis_findings": [],
                "text_report_path": "/tmp/coverage.txt",
                "json_report_path": "/tmp/coverage.json",
            },
        ) as mocked_run:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_coverage_audit(args)

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once_with(profile_name="cis-site", output_dir=None)
        self.assertIn("server-backup coverage audit", stdout.getvalue())

    def test_cmd_coverage_audit_json_prints_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["coverage", "audit", "--json"])
        with patch(
            "server_backup.cli.run_coverage_audit",
            return_value={"status": "success", "summary": {"SUCCESS": 1, "WARNING": 0, "FAILURE": 0}},
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_coverage_audit(args)
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "success")

    def test_status_reads_last_coverage_audit_without_running_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir()
            last_path = state_dir / "last-coverage-audit.json"
            last_path.write_text(
                json.dumps(
                    {
                        "end_time": "2026-05-19T16:00:00Z",
                        "status": "warning",
                        "text_report_path": "/tmp/coverage.txt",
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
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = cli.cmd_status(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Last Coverage Audit:", stdout.getvalue())
        self.assertIn("status: warning", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
