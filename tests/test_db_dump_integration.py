from __future__ import annotations

import contextlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.backup import render_backup_report_text, run_backup, run_backup_for_target
from server_backup.validators import ValidationResult


class DbDumpIntegrationTests(unittest.TestCase):
    def test_run_backup_for_target_includes_database_dump_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing_path = Path(tmpdir) / "existing"
            existing_path.mkdir()
            dump_file = Path(tmpdir) / "dumps" / "app-postgres-appdb.dump"
            dump_file.parent.mkdir()
            dump_file.write_bytes(b"dump")

            profile = {
                "CONFIG_VERSION": "1",
                "PROFILE_NAME": "cis-site",
                "PROFILE_TYPE": "cis-site",
                "WEB_CONTENT_CRITICAL": "true",
                "DOCKER_INVENTORY": "true",
                "CONTENT_CLASSIFICATION": [
                    "db:postgresql:appdb:site_pages:builder-pages",
                    "files:/srv/app/frontend:frontend",
                    "files:/srv/app/backend:backend",
                    "files:/srv/app/uploads:media",
                ],
                "BACKUP_PATHS": [str(existing_path)],
                "DATABASE_DUMPS": ["name=app-postgres;engine=postgresql;mode=docker;container=db;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"],
            }
            target = {"TARGET_NAME": "nas-steph", "TARGET_TYPE": "sftp", "RESTIC_REPOSITORY": "sftp:nas-steph:/repo"}

            with patch("server_backup.backup.validate_restic_preflight", return_value=ValidationResult()), patch(
                "server_backup.backup.repo_is_initialized",
                return_value=True,
            ), patch(
                "server_backup.backup.build_restic_env",
                return_value={},
            ), patch(
                "server_backup.backup.load_database_dumps_from_profiles",
                return_value=[
                    {
                        "name": "app-postgres",
                        "engine": "postgresql",
                        "mode": "docker",
                        "container": "db",
                        "user": "app",
                        "databases": ["appdb"],
                        "globals": True,
                        "__profile_name__": "cis-site",
                    }
                ],
            ), patch(
                "server_backup.backup.run_database_dump",
                return_value={
                    "name": "app-postgres",
                    "status": "success",
                    "files": [str(dump_file)],
                    "warnings": [],
                    "errors": [],
                    "commands": ["docker exec -i -e PGPASSWORD db pg_dump --username=app --format=custom --compress=0 appdb"],
                },
            ), patch(
                "server_backup.backup.build_restic_base_command",
                return_value=["restic"],
            ), patch(
                "server_backup.backup.run_restic_command",
                return_value=subprocess.CompletedProcess(["restic"], 0, stdout="ok", stderr=""),
            ) as mocked_restic:
                result = run_backup_for_target({"BACKUP_NAME": "mes-fragrances", "LOCAL_DUMP_DIR": tmpdir}, target, [profile], dry_run=True)

        self.assertEqual(result["status"], "success")
        profile_result = result["profile_results"][0]
        self.assertEqual(profile_result["database_dumps"][0]["status"], "success")
        called_args = mocked_restic.call_args.args[0]
        self.assertIn(str(existing_path), called_args)
        self.assertIn(str(dump_file), called_args)

    def test_database_dump_failure_blocks_restic_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing_path = Path(tmpdir) / "existing"
            existing_path.mkdir()
            profile = {
                "CONFIG_VERSION": "1",
                "PROFILE_NAME": "cis-site",
                "PROFILE_TYPE": "cis-site",
                "WEB_CONTENT_CRITICAL": "true",
                "DOCKER_INVENTORY": "true",
                "CONTENT_CLASSIFICATION": [
                    "db:postgresql:appdb:site_pages:builder-pages",
                    "files:/srv/app/frontend:frontend",
                    "files:/srv/app/backend:backend",
                    "files:/srv/app/uploads:media",
                ],
                "BACKUP_PATHS": [str(existing_path)],
                "DATABASE_DUMPS": ["name=app-postgres;engine=postgresql;mode=docker;container=db;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"],
            }
            target = {"TARGET_NAME": "nas-steph", "TARGET_TYPE": "sftp", "RESTIC_REPOSITORY": "sftp:nas-steph:/repo"}

            with patch("server_backup.backup.validate_restic_preflight", return_value=ValidationResult()), patch(
                "server_backup.backup.repo_is_initialized",
                return_value=True,
            ), patch(
                "server_backup.backup.build_restic_env",
                return_value={},
            ), patch(
                "server_backup.backup.load_database_dumps_from_profiles",
                return_value=[
                    {
                        "name": "app-postgres",
                        "engine": "postgresql",
                        "mode": "docker",
                        "container": "db",
                        "user": "app",
                        "databases": ["appdb"],
                        "__profile_name__": "cis-site",
                    }
                ],
            ), patch(
                "server_backup.backup.run_database_dump",
                return_value={
                    "name": "app-postgres",
                    "status": "failure",
                    "files": [],
                    "warnings": [],
                    "errors": ["pg_dump failed"],
                    "commands": [],
                },
            ), patch(
                "server_backup.backup.run_restic_command",
            ) as mocked_restic:
                result = run_backup_for_target({"BACKUP_NAME": "mes-fragrances", "LOCAL_DUMP_DIR": tmpdir}, target, [profile], dry_run=False)

        self.assertEqual(result["status"], "failure")
        self.assertFalse(mocked_restic.called)
        self.assertIn("Database dump app-postgres failed", result["profile_results"][0]["errors"][0])

    def test_backup_report_mentions_database_dumps(self) -> None:
        report = {
            "hostname": "host",
            "backup_name": "mes-fragrances",
            "start_time": "2026-05-19T00:00:00Z",
            "end_time": "2026-05-19T00:01:00Z",
            "duration_seconds": 60.0,
            "dry_run": True,
            "interrupted": False,
            "status": "warning",
            "targets_requested": 1,
            "profiles_requested": 1,
            "warnings": [],
            "errors": [],
            "target_results": [
                {
                    "target_name": "nas-steph",
                    "status": "warning",
                    "repository": "sftp:nas-steph:/repo",
                    "warnings": [],
                    "errors": [],
                    "profile_results": [
                        {
                            "profile_name": "cis-site",
                            "profile_type": "cis-site",
                            "status": "warning",
                            "paths_included": ["/etc"],
                            "paths_missing": [],
                            "excludes": [],
                            "tags": ["server-backup"],
                            "database_dumps": [
                                {
                                    "name": "app-postgres",
                                    "status": "warning",
                                    "files": ["/var/tmp/server-backup/app-postgres.dump"],
                                    "warnings": ["pg_restore is not available"],
                                    "errors": [],
                                }
                            ],
                            "warnings": [],
                            "errors": [],
                            "stdout": "",
                            "stderr": "",
                        }
                    ],
                }
            ],
        }

        rendered = render_backup_report_text(report)
        self.assertIn("Database dumps:", rendered)
        self.assertIn("app-postgres", rendered)

    def test_run_backup_uses_lock_with_database_dumps(self) -> None:
        global_config = {
            "CONFIG_VERSION": "1",
            "BACKUP_NAME": "mes-fragrances",
            "REPORT_DIR": "/tmp/reports",
            "STATE_DIR": "/tmp/state",
        }
        target = {"TARGET_NAME": "nas-steph"}
        profile = {"PROFILE_NAME": "cis-site"}

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


if __name__ == "__main__":
    unittest.main()
