from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.validation import LAST_PRODUCTION_VALIDATION_FILE, run_production_validation


class ValidationTests(unittest.TestCase):
    def _global_config(self, tmpdir: str) -> dict[str, object]:
        return {
            "BACKUP_NAME": "mes-fragrances",
            "REPORT_DIR": tmpdir,
            "STATE_DIR": tmpdir,
            "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
        }

    def _success_check(self, name: str) -> dict[str, object]:
        return {"name": name, "status": "success", "summary": f"{name} ok"}

    def test_validation_without_options_does_not_run_optional_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.validation.load_global_config",
            return_value=self._global_config(tmpdir),
        ), patch(
            "server_backup.validation.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.validation.load_profiles",
            return_value=[{"PROFILE_NAME": "mes-fragrances-cis"}],
        ), patch(
            "server_backup.validation.check_config_validate",
            return_value=self._success_check("config-validate"),
        ), patch(
            "server_backup.validation.check_health",
            return_value=self._success_check("health"),
        ), patch(
            "server_backup.validation.check_operations_status",
            return_value=self._success_check("operations-status"),
        ), patch(
            "server_backup.validation.check_repo_snapshots",
            return_value=self._success_check("repo-snapshots"),
        ), patch(
            "server_backup.validation.check_repo_check",
            return_value=self._success_check("repo-check"),
        ), patch(
            "server_backup.validation.check_db_list",
            return_value=self._success_check("db-list"),
        ), patch(
            "server_backup.validation.check_db_tests",
            return_value=self._success_check("db-test"),
        ), patch(
            "server_backup.validation.check_coverage_audit",
            return_value=self._success_check("coverage-audit"),
        ), patch(
            "server_backup.validation.maybe_email_test",
            return_value={"name": "email-test", "status": "skipped", "summary": "skipped"},
        ) as mocked_email, patch(
            "server_backup.validation.maybe_restore_test",
            return_value={"name": "restore-test", "status": "skipped", "summary": "skipped"},
        ) as mocked_restore, patch(
            "server_backup.validation.maybe_backup_dry_run",
            return_value={"name": "backup-dry-run", "status": "skipped", "summary": "skipped"},
        ) as mocked_backup:
            report = run_production_validation(target_name="nas-steph", profile_name="mes-fragrances-cis")

        self.assertEqual(report["status"], "success")
        mocked_email.assert_called_once_with(self._global_config(tmpdir), False)
        mocked_restore.assert_called_once_with("nas-steph", "mes-fragrances-cis", False)
        mocked_backup.assert_called_once_with("nas-steph", "mes-fragrances-cis", False)

    def test_validation_with_options_runs_optional_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.validation.load_global_config",
            return_value=self._global_config(tmpdir),
        ), patch(
            "server_backup.validation.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.validation.load_profiles",
            return_value=[{"PROFILE_NAME": "mes-fragrances-cis"}],
        ), patch(
            "server_backup.validation.check_config_validate",
            return_value=self._success_check("config-validate"),
        ), patch(
            "server_backup.validation.check_health",
            return_value=self._success_check("health"),
        ), patch(
            "server_backup.validation.check_operations_status",
            return_value=self._success_check("operations-status"),
        ), patch(
            "server_backup.validation.check_repo_snapshots",
            return_value=self._success_check("repo-snapshots"),
        ), patch(
            "server_backup.validation.check_repo_check",
            return_value=self._success_check("repo-check"),
        ), patch(
            "server_backup.validation.check_db_list",
            return_value=self._success_check("db-list"),
        ), patch(
            "server_backup.validation.check_db_tests",
            return_value=self._success_check("db-test"),
        ), patch(
            "server_backup.validation.check_coverage_audit",
            return_value=self._success_check("coverage-audit"),
        ), patch(
            "server_backup.validation.maybe_email_test",
            return_value=self._success_check("email-test"),
        ) as mocked_email, patch(
            "server_backup.validation.maybe_restore_test",
            return_value=self._success_check("restore-test"),
        ) as mocked_restore, patch(
            "server_backup.validation.maybe_backup_dry_run",
            return_value=self._success_check("backup-dry-run"),
        ) as mocked_backup:
            report = run_production_validation(
                target_name="nas-steph",
                profile_name="mes-fragrances-cis",
                email_test=True,
                restore_test=True,
                backup_dry_run=True,
            )

        self.assertEqual(report["status"], "success")
        mocked_email.assert_called_once_with(self._global_config(tmpdir), True)
        mocked_restore.assert_called_once_with("nas-steph", "mes-fragrances-cis", True)
        mocked_backup.assert_called_once_with("nas-steph", "mes-fragrances-cis", True)

    def test_validation_writes_text_json_and_last_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.validation.load_global_config",
            return_value=self._global_config(tmpdir),
        ), patch(
            "server_backup.validation.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.validation.load_profiles",
            return_value=[{"PROFILE_NAME": "mes-fragrances-cis"}],
        ), patch(
            "server_backup.validation.check_config_validate",
            return_value=self._success_check("config-validate"),
        ), patch(
            "server_backup.validation.check_health",
            return_value=self._success_check("health"),
        ), patch(
            "server_backup.validation.check_operations_status",
            return_value=self._success_check("operations-status"),
        ), patch(
            "server_backup.validation.check_repo_snapshots",
            return_value=self._success_check("repo-snapshots"),
        ), patch(
            "server_backup.validation.check_repo_check",
            return_value=self._success_check("repo-check"),
        ), patch(
            "server_backup.validation.check_db_list",
            return_value=self._success_check("db-list"),
        ), patch(
            "server_backup.validation.check_db_tests",
            return_value=self._success_check("db-test"),
        ), patch(
            "server_backup.validation.check_coverage_audit",
            return_value=self._success_check("coverage-audit"),
        ), patch(
            "server_backup.validation.maybe_email_test",
            return_value={"name": "email-test", "status": "skipped", "summary": "skipped"},
        ), patch(
            "server_backup.validation.maybe_restore_test",
            return_value={"name": "restore-test", "status": "skipped", "summary": "skipped"},
        ), patch(
            "server_backup.validation.maybe_backup_dry_run",
            return_value={"name": "backup-dry-run", "status": "skipped", "summary": "skipped"},
        ):
            report = run_production_validation(target_name="nas-steph")
            self.assertTrue(Path(report["text_report_path"]).exists())
            self.assertTrue(Path(report["json_report_path"]).exists())
            last_path = Path(tmpdir) / LAST_PRODUCTION_VALIDATION_FILE
            self.assertTrue(last_path.exists())
            payload = json.loads(last_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "success")

    def test_validation_report_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.validation.load_global_config",
            return_value=self._global_config(tmpdir),
        ), patch(
            "server_backup.validation.load_targets",
            return_value=[{"TARGET_NAME": "nas-steph"}],
        ), patch(
            "server_backup.validation.load_profiles",
            return_value=[{"PROFILE_NAME": "mes-fragrances-cis"}],
        ), patch(
            "server_backup.validation.check_config_validate",
            return_value={"name": "config-validate", "status": "warning", "summary": "warning", "warnings": ["RESTIC_PASSWORD_FILE=/secret"]},
        ), patch(
            "server_backup.validation.check_health",
            return_value=self._success_check("health"),
        ), patch(
            "server_backup.validation.check_operations_status",
            return_value=self._success_check("operations-status"),
        ), patch(
            "server_backup.validation.check_repo_snapshots",
            return_value=self._success_check("repo-snapshots"),
        ), patch(
            "server_backup.validation.check_repo_check",
            return_value=self._success_check("repo-check"),
        ), patch(
            "server_backup.validation.check_db_list",
            return_value=self._success_check("db-list"),
        ), patch(
            "server_backup.validation.check_db_tests",
            return_value=self._success_check("db-test"),
        ), patch(
            "server_backup.validation.check_coverage_audit",
            return_value=self._success_check("coverage-audit"),
        ), patch(
            "server_backup.validation.maybe_email_test",
            return_value={"name": "email-test", "status": "skipped", "summary": "skipped"},
        ), patch(
            "server_backup.validation.maybe_restore_test",
            return_value={"name": "restore-test", "status": "skipped", "summary": "skipped"},
        ), patch(
            "server_backup.validation.maybe_backup_dry_run",
            return_value={"name": "backup-dry-run", "status": "skipped", "summary": "skipped"},
        ):
            report = run_production_validation(target_name="nas-steph")
            text = Path(report["text_report_path"]).read_text(encoding="utf-8")
            self.assertNotIn("/secret", text)


if __name__ == "__main__":
    unittest.main()
