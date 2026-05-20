from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.restic import (
    LAST_PRUNE_RUN_FILE,
    build_forget_args,
    parse_retention_values,
    prune_all_repositories,
    validate_retention_config,
)


class PruneHelpersTests(unittest.TestCase):
    def test_build_forget_args_real(self) -> None:
        args = build_forget_args(
            {
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
            }
        )
        self.assertEqual(
            args,
            [
                "forget",
                "--keep-daily",
                "14",
                "--keep-weekly",
                "8",
                "--keep-monthly",
                "12",
                "--prune",
            ],
        )

    def test_build_forget_args_dry_run(self) -> None:
        args = build_forget_args(
            {
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
            },
            dry_run=True,
        )
        self.assertIn("--dry-run", args)
        self.assertNotIn("--prune", args)

    def test_parse_retention_values_accepts_zero_when_one_positive(self) -> None:
        values = parse_retention_values(
            {
                "RETENTION_DAILY": "0",
                "RETENTION_WEEKLY": "1",
                "RETENTION_MONTHLY": "0",
            }
        )
        self.assertEqual(values["RETENTION_WEEKLY"], 1)

    def test_validate_retention_config_rejects_all_zero(self) -> None:
        result = validate_retention_config(
            {
                "__file__": "/etc/server-backup/backup.conf",
                "RETENTION_DAILY": "0",
                "RETENTION_WEEKLY": "0",
                "RETENTION_MONTHLY": "0",
            }
        )
        self.assertTrue(result.errors)

    def test_prune_all_repositories_writes_report_and_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            global_config = {
                "BACKUP_NAME": "mes-fragrances",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "REPORT_DIR": str(report_dir),
                "STATE_DIR": str(state_dir),
            }

            with patch(
                "server_backup.restic.restic_repo_lock",
                return_value=contextlib.nullcontext("/run/server-backup-repo.lock"),
            ) as mocked_lock, patch(
                "server_backup.restic.prune_repository",
                return_value={
                    "target_name": "nas-steph",
                    "repository": "sftp:server-backup-nas-steph:/repo",
                    "status": "success",
                    "command_summary": "restic forget ...",
                    "stdout": "kept 1 snapshot",
                    "stderr": "",
                    "warnings": [],
                    "errors": [],
                },
            ):
                report = prune_all_repositories(global_config, [{"TARGET_NAME": "nas-steph"}], dry_run=True, yes=False)

            self.assertEqual(report["status"], "success")
            self.assertTrue(Path(report["text_report_path"]).exists())
            self.assertTrue(Path(report["json_report_path"]).exists())
            self.assertTrue((state_dir / LAST_PRUNE_RUN_FILE).exists())
            payload = json.loads(Path(report["json_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["backup_name"], "mes-fragrances")
            mocked_lock.assert_called_once_with(timeout_seconds=30)

    def test_prune_all_repositories_records_retention_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            global_config = {
                "BACKUP_NAME": "mes-fragrances",
                "RETENTION_DAILY": "-1",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "REPORT_DIR": str(Path(tmpdir) / "reports"),
                "STATE_DIR": str(Path(tmpdir) / "state"),
            }
            report = prune_all_repositories(global_config, [{"TARGET_NAME": "nas-steph"}], dry_run=True, yes=False)

        self.assertEqual(report["status"], "failure")
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
