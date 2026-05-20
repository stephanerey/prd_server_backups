from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.restore import (
    LAST_RESTORE_TEST_FILE,
    build_restore_output_dir,
    build_restic_restore_args,
    check_profile_expected_paths,
    check_restored_files,
    run_restore_test,
    update_last_restore_test,
    write_restore_report,
)
from server_backup.validators import ValidationResult


class RestoreHelpersTests(unittest.TestCase):
    def test_build_restore_output_dir_uses_tmp_prefix(self) -> None:
        path = build_restore_output_dir()
        self.assertTrue(str(path).startswith("/tmp/server-backup-restore-test-"))

    def test_build_restic_restore_args_latest_with_includes(self) -> None:
        args = build_restic_restore_args("latest", "/tmp/output", includes=["/etc", "/srv/app"])
        self.assertEqual(
            args,
            ["restore", "latest", "--target", "/tmp/output", "--include", "/etc", "--include", "/srv/app"],
        )

    def test_check_profile_expected_paths_maps_into_restore_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            restored = Path(tmpdir) / "var/lib/server-backup/state"
            restored.mkdir(parents=True)
            result = check_profile_expected_paths(
                tmpdir,
                {
                    "PROFILE_NAME": "system-filesystem",
                    "BACKUP_PATHS": ["/var/lib/server-backup/state", "/etc"],
                },
            )

        self.assertEqual(result["status"], "warning")
        self.assertEqual(len(result["found_paths"]), 1)
        self.assertEqual(result["missing_paths"], ["/etc"])

    def test_check_restored_files_detects_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = Path(tmpdir) / "var/lib/server-backup/state/sample.txt"
            sample.parent.mkdir(parents=True)
            sample.write_text("hello", encoding="utf-8")
            result = check_restored_files(tmpdir)

        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["file_count"], 1)
        self.assertGreaterEqual(result["total_size_bytes"], 5)

    def test_write_restore_report_and_update_last_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            report = {
                "hostname": "test-host",
                "backup_name": "mes-fragrances",
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-19T00:01:00Z",
                "duration_seconds": 60.0,
                "target_name": "nas-steph",
                "requested_snapshot": "latest",
                "restored_snapshot": "df472f9c",
                "output_dir": "/tmp/server-backup-restore-test-20260519",
                "keep_output": True,
                "output_cleaned": False,
                "includes": [],
                "warnings": [],
                "errors": [],
                "status": "success",
                "state_dir": str(state_dir),
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            }
            paths = write_restore_report(report, report_dir)
            report.update(paths)
            last_path = update_last_restore_test(report)

            self.assertTrue(Path(paths["text_report_path"]).exists())
            self.assertTrue(Path(paths["json_report_path"]).exists())
            payload = json.loads(Path(paths["json_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["RESTIC_PASSWORD_FILE"], "<redacted>")
            self.assertIsNotNone(last_path)
            self.assertTrue((state_dir / LAST_RESTORE_TEST_FILE).exists())

    def test_run_restore_test_rejects_dangerous_output_dir(self) -> None:
        with patch(
            "server_backup.restore.load_backup_context",
            return_value=(
                {"BACKUP_NAME": "mes-fragrances", "REPORT_DIR": "/tmp", "STATE_DIR": "/tmp"},
                [{"TARGET_NAME": "nas-steph"}],
                [],
            ),
        ):
            report = run_restore_test("nas-steph", output_dir="/etc")

        self.assertEqual(report["status"], "failure")
        self.assertTrue(report["errors"])

    def test_run_restore_test_rejects_existing_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "restore-out"
            existing.mkdir()
            with patch(
                "server_backup.restore.load_backup_context",
                return_value=(
                    {"BACKUP_NAME": "mes-fragrances", "REPORT_DIR": str(Path(tmpdir) / "reports"), "STATE_DIR": str(Path(tmpdir) / "state")},
                    [{"TARGET_NAME": "nas-steph"}],
                    [],
                ),
            ):
                report = run_restore_test("nas-steph", output_dir=str(existing))

        self.assertEqual(report["status"], "failure")
        self.assertTrue(any("already exists" in message for message in report["errors"]))

    def test_run_restore_test_keep_output_false_removes_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "restore-out"
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"

            def _fake_restore(command, env):
                restored = output_dir / "var/lib/server-backup/state"
                restored.mkdir(parents=True, exist_ok=True)
                (restored / "sample.txt").write_text("hello", encoding="utf-8")
                return type("Completed", (), {"returncode": 0, "stdout": "restored snapshot df472f9c", "stderr": ""})()

            with patch(
                "server_backup.restore.load_backup_context",
                return_value=(
                    {"BACKUP_NAME": "mes-fragrances", "REPORT_DIR": str(report_dir), "STATE_DIR": str(state_dir)},
                    [{"TARGET_NAME": "nas-steph", "RESTIC_REPOSITORY": "sftp:alias:/repo"}],
                    [{"PROFILE_NAME": "state", "BACKUP_PATHS": ["/var/lib/server-backup/state"]}],
                ),
            ), patch(
                "server_backup.restore.validate_restore_preflight",
                return_value=ValidationResult(),
            ), patch(
                "server_backup.restore.build_restic_env",
                return_value={},
            ), patch(
                "server_backup.restore.build_restic_base_command",
                return_value=["restic"],
            ), patch(
                "server_backup.restore.run_restic_command",
                side_effect=_fake_restore,
            ), patch(
                "server_backup.restore.restic_repo_lock",
                return_value=contextlib.nullcontext("/run/server-backup-repo.lock"),
            ):
                report = run_restore_test("nas-steph", output_dir=str(output_dir), keep_output=False)

            self.assertIn(report["status"], {"success", "warning"})
            self.assertFalse(output_dir.exists())
            self.assertTrue(report["output_cleaned"])

    def test_run_restore_test_keep_output_true_preserves_directory_and_uses_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "restore-out"
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"

            def _fake_restore(command, env):
                restored = output_dir / "var/lib/server-backup/state"
                restored.mkdir(parents=True, exist_ok=True)
                (restored / "sample.txt").write_text("hello", encoding="utf-8")
                return type("Completed", (), {"returncode": 0, "stdout": "restored snapshot df472f9c", "stderr": ""})()

            with patch(
                "server_backup.restore.load_backup_context",
                return_value=(
                    {"BACKUP_NAME": "mes-fragrances", "REPORT_DIR": str(report_dir), "STATE_DIR": str(state_dir)},
                    [{"TARGET_NAME": "nas-steph", "RESTIC_REPOSITORY": "sftp:alias:/repo"}],
                    [{"PROFILE_NAME": "state", "BACKUP_PATHS": ["/var/lib/server-backup/state"]}],
                ),
            ), patch(
                "server_backup.restore.validate_restore_preflight",
                return_value=ValidationResult(),
            ), patch(
                "server_backup.restore.build_restic_env",
                return_value={},
            ), patch(
                "server_backup.restore.build_restic_base_command",
                return_value=["restic"],
            ), patch(
                "server_backup.restore.run_restic_command",
                side_effect=_fake_restore,
            ), patch(
                "server_backup.restore.restic_repo_lock",
                return_value=contextlib.nullcontext("/run/server-backup-repo.lock"),
            ) as mocked_lock:
                report = run_restore_test("nas-steph", output_dir=str(output_dir), keep_output=True)

            self.assertIn(report["status"], {"success", "warning"})
            self.assertTrue(output_dir.exists())
            self.assertFalse(report["output_cleaned"])
            mocked_lock.assert_called_once_with(timeout_seconds=30)


if __name__ == "__main__":
    unittest.main()
