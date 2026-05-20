from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class RestoreCliTests(unittest.TestCase):
    def test_restore_test_parser_defaults_snapshot_to_latest(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["restore", "test", "--target", "nas-steph"])
        self.assertEqual(args.command, "restore")
        self.assertEqual(args.restore_command, "test")
        self.assertEqual(args.target, "nas-steph")
        self.assertEqual(args.snapshot, "latest")

    def test_restore_test_parser_supports_profile_include_and_keep_output(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "restore",
                "test",
                "--target",
                "nas-steph",
                "--profile",
                "system-filesystem-test",
                "--include",
                "/var/lib/server-backup/state",
                "--keep-output",
            ]
        )
        self.assertEqual(args.profile, "system-filesystem-test")
        self.assertEqual(args.include, ["/var/lib/server-backup/state"])
        self.assertTrue(args.keep_output)

    def test_restore_test_requires_target(self) -> None:
        parser = build_parser()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                parser.parse_args(["restore", "test"])

    def test_cmd_restore_test_calls_run_restore_test(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["restore", "test", "--target", "nas-steph"])

        with patch(
            "server_backup.cli.run_restore_test",
            return_value={
                "target_name": "nas-steph",
                "requested_snapshot": "latest",
                "restored_snapshot": "df472f9c",
                "output_dir": "/tmp/server-backup-restore-test-20260519",
                "keep_output": False,
                "output_cleaned": True,
                "warnings": [],
                "errors": [],
                "restored_files": {"file_count": 1, "total_size_bytes": 444},
                "status": "success",
                "text_report_path": "/var/lib/server-backup/reports/restore.txt",
                "json_report_path": "/var/lib/server-backup/reports/restore.json",
            },
        ) as mocked_restore:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_restore_test(args)

        self.assertEqual(exit_code, 0)
        mocked_restore.assert_called_once_with(
            target="nas-steph",
            snapshot="latest",
            profile_name=None,
            includes=None,
            output_dir=None,
            keep_output=False,
        )
        self.assertIn("server-backup restore test", stdout.getvalue())

    def test_cmd_restore_test_returns_non_zero_on_interrupt(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["restore", "test", "--target", "nas-steph"])

        with patch(
            "server_backup.cli.run_restore_test",
            return_value={
                "target_name": "nas-steph",
                "requested_snapshot": "latest",
                "restored_snapshot": "latest",
                "output_dir": "/tmp/server-backup-restore-test-20260519",
                "keep_output": False,
                "output_cleaned": False,
                "warnings": [],
                "errors": ["Operation interrupted by user. No report may have been completed."],
                "restored_files": {"file_count": 0, "total_size_bytes": 0},
                "status": "interrupted",
                "text_report_path": "/var/lib/server-backup/reports/restore.txt",
                "json_report_path": "/var/lib/server-backup/reports/restore.json",
            },
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_restore_test(args)

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Operation interrupted by user. No report may have been completed.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
