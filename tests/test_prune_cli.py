from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class PruneCliTests(unittest.TestCase):
    def test_repo_prune_parser_supports_target_and_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "prune", "nas-steph", "--dry-run", "--yes"])
        self.assertEqual(args.command, "repo")
        self.assertEqual(args.repo_command, "prune")
        self.assertEqual(args.target, "nas-steph")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.yes)

    def test_repo_prune_requires_target_or_all(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "prune"])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = cli.cmd_repo_prune(args)
        self.assertEqual(exit_code, 1)
        self.assertIn("usage:", stdout.getvalue())

    def test_repo_prune_dry_run_does_not_prompt_confirmation(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "prune", "nas-steph", "--dry-run"])
        with patch("server_backup.cli.load_global_config", return_value={"RETENTION_DAILY": "14", "RETENTION_WEEKLY": "8", "RETENTION_MONTHLY": "12"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.validate_retention_config",
            return_value=type("R", (), {"errors": []})(),
        ), patch(
            "server_backup.cli.prune_all_repositories",
            return_value={
                "targets_requested": 1,
                "dry_run": True,
                "retention": {"RETENTION_DAILY": 14, "RETENTION_WEEKLY": 8, "RETENTION_MONTHLY": 12},
                "warnings": [],
                "errors": [],
                "target_results": [],
                "status": "warning",
                "text_report_path": "/tmp/prune.txt",
                "json_report_path": "/tmp/prune.json",
            },
        ) as mocked_prune, patch("server_backup.cli._confirm_prune") as mocked_confirm:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_repo_prune(args)

        self.assertEqual(exit_code, 0)
        mocked_prune.assert_called_once()
        mocked_confirm.assert_not_called()

    def test_repo_prune_real_without_yes_prompts_confirmation(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "prune", "nas-steph"])
        with patch("server_backup.cli.load_global_config", return_value={"RETENTION_DAILY": "14", "RETENTION_WEEKLY": "8", "RETENTION_MONTHLY": "12"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.validate_retention_config",
            return_value=type("R", (), {"errors": []})(),
        ), patch(
            "server_backup.cli.parse_retention_values",
            return_value={"RETENTION_DAILY": 14, "RETENTION_WEEKLY": 8, "RETENTION_MONTHLY": 12},
        ), patch(
            "server_backup.cli._confirm_prune",
            return_value=False,
        ) as mocked_confirm, patch("server_backup.cli.prune_all_repositories") as mocked_prune:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_repo_prune(args)

        self.assertEqual(exit_code, 0)
        mocked_confirm.assert_called_once()
        mocked_prune.assert_not_called()

    def test_repo_prune_returns_non_zero_on_interrupt(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "prune", "nas-steph", "--dry-run"])
        with patch("server_backup.cli.load_global_config", return_value={"RETENTION_DAILY": "14", "RETENTION_WEEKLY": "8", "RETENTION_MONTHLY": "12"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.validate_retention_config",
            return_value=type("R", (), {"errors": []})(),
        ), patch(
            "server_backup.cli.prune_all_repositories",
            return_value={
                "targets_requested": 1,
                "dry_run": True,
                "retention": {"RETENTION_DAILY": 14, "RETENTION_WEEKLY": 8, "RETENTION_MONTHLY": 12},
                "warnings": [],
                "errors": ["Operation interrupted by user. No report may have been completed."],
                "target_results": [],
                "status": "interrupted",
                "text_report_path": "/tmp/prune.txt",
                "json_report_path": "/tmp/prune.json",
            },
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_repo_prune(args)

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Operation interrupted by user. No report may have been completed.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
