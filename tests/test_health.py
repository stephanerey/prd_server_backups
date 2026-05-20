from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from server_backup.health import build_operations_status, run_health_check
from server_backup.validators import ValidationResult


class HealthTests(unittest.TestCase):
    def _base_global(self, state_dir: str) -> dict[str, object]:
        return {
            "CONFIG_VERSION": "1",
            "BACKUP_NAME": "mes-fragrances",
            "RETENTION_DAILY": "14",
            "RETENTION_WEEKLY": "8",
            "RETENTION_MONTHLY": "12",
            "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
            "LOG_FILE": "/var/log/server-backup.log",
            "STATE_DIR": state_dir,
            "REPORT_DIR": "/var/lib/server-backup/reports",
            "RESTIC_CACHE_DIR": "/var/cache/restic",
            "RESTIC_PASSWORD_FILE": "/tmp/restic-password",
            "RUN_RESTIC_CHECK": "true",
            "RUN_PRUNE": "true",
            "RUN_COVERAGE_AUDIT": "true",
            "EMAIL_REPORT_ENABLED": "false",
            "__file__": "/etc/server-backup/backup.conf",
        }

    def _base_operations(self) -> dict[str, object]:
        return {
            "timer": {
                "file_exists": True,
                "enabled": "yes",
                "enabled_detail": "enabled",
                "next_run": "Thu 2026-05-21 02:30:00 UTC",
                "next_run_detail": "ok",
            },
            "target_count": 1,
            "profile_count": 1,
            "db_dump_count": 0,
            "last_backup": {
                "present": True,
                "status": "success",
                "date": "2026-05-20T00:00:00Z",
                "report": "/tmp/backup.txt",
            },
            "last_prune": {
                "present": True,
                "status": "success",
                "date": "2026-05-19T00:00:00Z",
                "report": "/tmp/prune.txt",
            },
            "last_restore_test": {
                "present": True,
                "status": "warning",
                "date": "2026-05-10T00:00:00Z",
                "report": "/tmp/restore.txt",
            },
            "last_coverage_audit": {
                "present": True,
                "status": "success",
                "date": "2026-05-19T00:00:00Z",
                "report": "/tmp/coverage.txt",
            },
            "last_email": {
                "present": True,
                "status": "success",
                "date": "2026-05-19T00:00:00Z",
                "kind": "backup",
                "subject": "[server-backup] SUCCESS backup test on host",
                "command": "sendmail",
            },
            "warnings": [],
        }

    def test_health_fails_when_backup_conf_missing(self) -> None:
        with patch("server_backup.health.build_operations_status", return_value=self._base_operations()), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(True, "email ok"),
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(global_config={"__missing__": True}, targets=[{"TARGET_NAME": "t"}], profiles=[{"PROFILE_NAME": "p"}])

        self.assertEqual(report["status"], "FAILURE")
        self.assertTrue(any(check["code"] == "global-config-missing" for check in report["checks"]))

    def test_health_fails_when_no_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.health.validate_global_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_profile_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(True, "email ok"),
        ), patch(
            "server_backup.health.build_operations_status",
            return_value=self._base_operations(),
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(
                global_config=self._base_global(tmpdir),
                targets=[],
                profiles=[{"PROFILE_NAME": "p"}],
            )

        self.assertEqual(report["status"], "FAILURE")
        self.assertTrue(any(check["code"] == "targets-missing" for check in report["checks"]))

    def test_health_fails_when_no_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.health.validate_global_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_target_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(True, "email ok"),
        ), patch(
            "server_backup.health.build_operations_status",
            return_value=self._base_operations(),
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(
                global_config=self._base_global(tmpdir),
                targets=[{"TARGET_NAME": "t"}],
                profiles=[],
            )

        self.assertEqual(report["status"], "FAILURE")
        self.assertTrue(any(check["code"] == "profiles-missing" for check in report["checks"]))

    def test_health_warns_when_last_backup_is_old(self) -> None:
        operations = self._base_operations()
        operations["last_backup"] = {
            "present": True,
            "status": "success",
            "date": "2026-05-18T00:00:00Z",
            "report": "/tmp/backup.txt",
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.health.validate_global_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_target_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_profile_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(True, "email ok"),
        ), patch(
            "server_backup.health.build_operations_status",
            return_value=operations,
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(
                global_config=self._base_global(tmpdir),
                targets=[{"TARGET_NAME": "t"}],
                profiles=[{"PROFILE_NAME": "p"}],
                now=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
            )

        self.assertEqual(report["status"], "WARNING")
        self.assertTrue(any(check["code"] == "last-backup-stale" for check in report["checks"]))

    def test_health_warns_when_timer_disabled(self) -> None:
        operations = self._base_operations()
        operations["timer"]["enabled"] = "no"
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "server_backup.health.validate_global_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_target_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_profile_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(True, "email ok"),
        ), patch(
            "server_backup.health.build_operations_status",
            return_value=operations,
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(
                global_config=self._base_global(tmpdir),
                targets=[{"TARGET_NAME": "t"}],
                profiles=[{"PROFILE_NAME": "p"}],
            )

        self.assertEqual(report["status"], "WARNING")
        self.assertTrue(any(check["code"] == "timer-enabled" for check in report["checks"]))

    def test_health_warns_when_email_enabled_but_command_missing(self) -> None:
        global_config = self._base_global("/tmp/state")
        global_config["EMAIL_REPORT_ENABLED"] = "true"
        global_config["EMAIL_REPORT_COMMAND"] = "sendmail"
        with patch("server_backup.health.validate_global_config", return_value=ValidationResult()), patch(
            "server_backup.health.validate_target_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health.validate_profile_config",
            return_value=ValidationResult(),
        ), patch(
            "server_backup.health._restic_available",
            return_value=(True, "restic available"),
        ), patch(
            "server_backup.health._email_command_available",
            return_value=(False, "sendmail is configured but not available"),
        ), patch(
            "server_backup.health.build_operations_status",
            return_value=self._base_operations(),
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            report = run_health_check(
                global_config=global_config,
                targets=[{"TARGET_NAME": "t"}],
                profiles=[{"PROFILE_NAME": "p"}],
            )

        self.assertEqual(report["status"], "WARNING")
        self.assertTrue(any(check["code"] == "email-command" for check in report["checks"]))

    def test_build_operations_status_reads_local_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "last-backup-run.json").write_text(
                '{"end_time":"2026-05-20T00:00:00Z","status":"success","text_report_path":"/tmp/backup.txt"}\n',
                encoding="utf-8",
            )
            (state_dir / "last-coverage-audit.json").write_text(
                '{"end_time":"2026-05-20T00:00:00Z","status":"success","text_report_path":"/tmp/coverage.txt"}\n',
                encoding="utf-8",
            )
            (state_dir / "last-restore-test.json").write_text(
                '{"end_time":"2026-05-19T00:00:00Z","status":"warning","text_report_path":"/tmp/restore.txt"}\n',
                encoding="utf-8",
            )
            (state_dir / "last-prune-run.json").write_text(
                '{"end_time":"2026-05-19T00:00:00Z","status":"success","text_report_path":"/tmp/prune.txt"}\n',
                encoding="utf-8",
            )
            (state_dir / "last-email-report.json").write_text(
                '{"sent_at":"2026-05-20T00:00:00Z","success":true,"kind":"backup","subject":"ok","command":"sendmail"}\n',
                encoding="utf-8",
            )
            global_config = self._base_global(str(state_dir))
            profiles = [{"PROFILE_NAME": "p", "BACKUP_PATHS": ["/srv/app"]}]
            with patch("server_backup.health.timer_enabled_status", return_value=("no", "disabled")), patch(
                "server_backup.health.timer_next_run",
                return_value=("unknown", "next run not available"),
            ), patch(
                "server_backup.health.load_database_dumps_from_profiles",
                return_value=[],
            ):
                operations = build_operations_status(
                    global_config=global_config,
                    targets=[{"TARGET_NAME": "nas-steph"}],
                    profiles=profiles,
                    now=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
                )

        self.assertEqual(operations["target_count"], 1)
        self.assertEqual(operations["profile_count"], 1)
        self.assertEqual(operations["timer"]["enabled"], "no")
        self.assertEqual(operations["last_backup"]["status"], "success")
        self.assertIn("server-backup.timer is not enabled", operations["warnings"])


if __name__ == "__main__":
    unittest.main()
