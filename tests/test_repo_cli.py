from __future__ import annotations

import contextlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser
from server_backup.restic import OperationInterruptedError
from server_backup.validators import ValidationResult


class RepoCliTests(unittest.TestCase):
    def test_repo_snapshots_all_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "snapshots", "--all"])
        self.assertEqual(args.command, "repo")
        self.assertEqual(args.repo_command, "snapshots")
        self.assertTrue(args.all)

    def test_repo_init_target_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "init", "nas-steph"])
        self.assertEqual(args.target, "nas-steph")
        self.assertFalse(args.all)

    def test_repo_command_uses_lock(self) -> None:
        with patch("server_backup.cli.load_global_config", return_value={"CONFIG_VERSION": "1"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.restic_repo_lock",
            return_value=contextlib.nullcontext("/tmp/server-backup-repo.lock"),
        ) as mocked_lock, patch(
            "server_backup.cli._run_repo_operation_for_target",
            return_value=0,
        ), patch(
            "server_backup.cli.validate_restic_preflight",
            return_value=ValidationResult(),
        ):
            exit_code = cli._run_repo_command("snapshots", "nas-steph", False, lambda *_args: 0)

        self.assertEqual(exit_code, 0)
        mocked_lock.assert_called_once_with(timeout_seconds=30)

    def test_repo_command_returns_non_zero_on_interrupt(self) -> None:
        with patch("server_backup.cli.load_global_config", return_value={"CONFIG_VERSION": "1"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.restic_repo_lock",
            return_value=contextlib.nullcontext("/tmp/server-backup-repo.lock"),
        ), patch(
            "server_backup.cli._run_repo_operation_for_target",
            return_value=130,
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli._run_repo_command("snapshots", "nas-steph", False, lambda *_args: 0)

        self.assertNotEqual(exit_code, 0)

    def test_repo_init_handles_interrupted_repo_is_initialized(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["repo", "init", "nas-steph"])
        with patch("server_backup.cli.load_global_config", return_value={"CONFIG_VERSION": "1"}), patch(
            "server_backup.cli.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.cli.validate_restic_preflight",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.cli.restic_repo_lock",
            return_value=contextlib.nullcontext("/tmp/server-backup-repo.lock"),
        ), patch(
            "server_backup.cli.repo_is_initialized",
            side_effect=OperationInterruptedError("Operation interrupted by user. No report may have been completed."),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_repo_init(args)

        self.assertEqual(exit_code, 130)
        self.assertIn("Operation interrupted by user. No report may have been completed.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
