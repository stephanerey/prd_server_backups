from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.backup import (
    LAST_BACKUP_RUN_FILE,
    build_backup_tags,
    build_restic_backup_args,
    normalize_backup_paths,
    normalize_excludes,
    run_backup,
    validate_backup_paths,
    write_backup_report,
)
from server_backup.validators import ValidationResult


class BackupHelpersTests(unittest.TestCase):
    def test_normalize_backup_paths_and_excludes(self) -> None:
        profile = {
            "BACKUP_PATHS": ["/etc", " /srv/app ", ""],
            "EXCLUDES": ["**/.cache", "  **/tmp  ", ""],
        }
        self.assertEqual(normalize_backup_paths(profile), ["/etc", "/srv/app"])
        self.assertEqual(normalize_excludes(profile), ["**/.cache", "**/tmp"])

    def test_build_backup_tags_splits_backup_tags(self) -> None:
        tags = build_backup_tags(
            {"BACKUP_NAME": "mes-fragrances", "BACKUP_TAGS": "prod docker prod"},
            {"PROFILE_NAME": "system-filesystem", "PROFILE_TYPE": "system-filesystem"},
        )
        self.assertEqual(
            tags,
            ["server-backup", "mes-fragrances", "system-filesystem", "prod", "docker"],
        )

    def test_build_restic_backup_args_adds_dry_run_tags_and_excludes(self) -> None:
        args = build_restic_backup_args(
            {"BACKUP_NAME": "mes-fragrances", "BACKUP_TAGS": "prod"},
            {
                "PROFILE_NAME": "system-filesystem",
                "PROFILE_TYPE": "system-filesystem",
                "__resolved_backup_paths__": ["/etc", "/srv/app"],
                "EXCLUDES": ["**/.cache", "**/tmp"],
            },
            dry_run=True,
        )
        self.assertEqual(args[0], "backup")
        self.assertIn("--dry-run", args)
        self.assertIn("--exclude", args)
        self.assertIn("/etc", args)
        self.assertIn("/srv/app", args)
        self.assertIn("server-backup", args)
        self.assertIn("prod", args)

    def test_validate_backup_paths_warns_for_partial_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "existing"
            existing.mkdir()
            result = validate_backup_paths(
                {
                    "PROFILE_NAME": "partial",
                    "BACKUP_PATHS": [str(existing), str(Path(tmpdir) / "missing")],
                }
            )

        self.assertEqual(result["existing_paths"], [str(existing)])
        self.assertEqual(len(result["missing_paths"]), 1)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["warnings"])

    def test_validate_backup_paths_fails_if_all_paths_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_backup_paths(
                {
                    "PROFILE_NAME": "missing-all",
                    "BACKUP_PATHS": [str(Path(tmpdir) / "missing-a"), str(Path(tmpdir) / "missing-b")],
                }
            )

        self.assertEqual(result["existing_paths"], [])
        self.assertTrue(result["errors"])

    def test_write_backup_report_writes_txt_json_and_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            report = {
                "hostname": "test-host",
                "backup_name": "mes-fragrances",
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-19T00:01:00Z",
                "duration_seconds": 60.0,
                "dry_run": True,
                "status": "warning",
                "targets_requested": 1,
                "profiles_requested": 1,
                "target_results": [],
                "warnings": ["warning"],
                "errors": [],
                "state_dir": str(state_dir),
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            }

            with patch("server_backup.backup._report_stamp", return_value="20260519-120000"):
                paths = write_backup_report(report, report_dir)

            text_path = Path(paths["text_report_path"])
            json_path = Path(paths["json_report_path"])
            last_run_path = Path(paths["last_run_path"])
            self.assertTrue(text_path.exists())
            self.assertTrue(json_path.exists())
            self.assertTrue(last_run_path.exists())
            self.assertNotIn(
                "/etc/server-backup/secrets/restic-password",
                text_path.read_text(encoding="utf-8"),
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["RESTIC_PASSWORD_FILE"], "<redacted>")
            self.assertTrue((state_dir / LAST_BACKUP_RUN_FILE).exists())

    def test_run_backup_uses_lock(self) -> None:
        global_config = {
            "CONFIG_VERSION": "1",
            "BACKUP_NAME": "mes-fragrances",
            "REPORT_DIR": "/tmp/reports",
            "STATE_DIR": "/tmp/state",
        }
        target = {"TARGET_NAME": "nas-steph"}
        profile = {"PROFILE_NAME": "system-filesystem"}

        with patch("server_backup.backup.load_backup_context", return_value=(global_config, [target], [profile])), patch(
            "server_backup.backup.validate_global_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.backup.restic_repo_lock",
            return_value=contextlib.nullcontext("/run/server-backup-repo.lock"),
        ) as mocked_lock, patch(
            "server_backup.backup.run_backup_all_targets",
            return_value={"status": "success", "target_results": [], "warnings": [], "errors": []},
        ), patch(
            "server_backup.backup.write_backup_report",
            return_value={
                "text_report_path": "/tmp/reports/report.txt",
                "json_report_path": "/tmp/reports/report.json",
                "last_run_path": "/tmp/state/last-backup-run.json",
            },
        ):
            report = run_backup(dry_run=True)

        self.assertEqual(report["status"], "success")
        mocked_lock.assert_called_once_with(timeout_seconds=30)

    def test_run_backup_writes_partial_report_when_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            global_config = {
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "mes-fragrances",
                "REPORT_DIR": str(report_dir),
                "STATE_DIR": str(state_dir),
            }
            target = {"TARGET_NAME": "nas-steph"}
            profile = {"PROFILE_NAME": "system-filesystem"}

            with patch("server_backup.backup.load_backup_context", return_value=(global_config, [target], [profile])), patch(
                "server_backup.backup.validate_global_config",
                return_value=ValidationResult(),
            ), patch(
                "server_backup.backup.restic_repo_lock",
                return_value=contextlib.nullcontext("/run/server-backup-repo.lock"),
            ), patch(
                "server_backup.backup.run_backup_all_targets",
                return_value={
                    "status": "interrupted",
                    "target_results": [],
                    "warnings": [],
                    "errors": ["Operation interrupted by user. No report may have been completed."],
                    "interrupted": True,
                },
            ):
                report = run_backup(dry_run=True)
                self.assertEqual(report["status"], "interrupted")
                self.assertTrue(Path(report["text_report_path"]).exists())
                self.assertTrue(Path(report["json_report_path"]).exists())
                self.assertTrue((state_dir / LAST_BACKUP_RUN_FILE).exists())


if __name__ == "__main__":
    unittest.main()
