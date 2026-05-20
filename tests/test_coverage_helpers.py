from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.coverage import (
    LAST_COVERAGE_AUDIT_FILE,
    check_backup_paths,
    check_cis_site_coverage,
    check_docker_mount_coverage,
    check_env_files_coverage,
    render_coverage_report_json,
    run_coverage_audit,
    write_coverage_report,
)


class CoverageHelpersTests(unittest.TestCase):
    def test_profile_without_backup_paths_is_failure(self) -> None:
        findings = check_backup_paths({"PROFILE_NAME": "broken", "BACKUP_PATHS": []})
        self.assertTrue(any(finding["severity"] == "FAILURE" for finding in findings))

    def test_profile_with_missing_path_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "existing"
            existing.mkdir()
            findings = check_backup_paths(
                {
                    "PROFILE_NAME": "mixed",
                    "BACKUP_PATHS": [str(existing), str(Path(tmpdir) / "missing")],
                }
            )
        self.assertTrue(any(finding["severity"] == "WARNING" for finding in findings))

    def test_profile_with_all_missing_paths_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            findings = check_backup_paths(
                {
                    "PROFILE_NAME": "missing",
                    "BACKUP_PATHS": [str(Path(tmpdir) / "a"), str(Path(tmpdir) / "b")],
                }
            )
        self.assertTrue(any(finding["code"] == "profile-no-existing-paths" for finding in findings))

    def test_cis_site_without_database_dumps_and_content_classification_warns(self) -> None:
        findings = check_cis_site_coverage(
            {
                "PROFILE_NAME": "cis-site",
                "PROFILE_TYPE": "cis-site",
                "WEB_CONTENT_CRITICAL": "true",
                "BACKUP_PATHS": ["/srv/app/frontend", "/srv/app/backend"],
            }
        )
        codes = {finding["code"] for finding in findings}
        self.assertIn("cis-missing-database-dumps", codes)
        self.assertIn("cis-missing-content-classification", codes)

    def test_cis_site_with_database_dumps_no_longer_warns_about_missing_dump(self) -> None:
        findings = check_cis_site_coverage(
            {
                "PROFILE_NAME": "cis-site",
                "PROFILE_TYPE": "cis-site",
                "WEB_CONTENT_CRITICAL": "true",
                "BACKUP_PATHS": ["/srv/app/frontend", "/srv/app/backend", "/srv/app/backend/alembic"],
                "CONTENT_CLASSIFICATION": [
                    "db:postgresql:appdb:site_pages:builder-pages",
                    "files:/srv/app/frontend:frontend",
                    "files:/srv/app/backend:backend",
                    "files:/srv/app/uploads:media",
                ],
                "DATABASE_DUMPS": [
                    "name=app-postgres;engine=postgresql;mode=docker;container=db;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"
                ],
            }
        )
        codes = {finding["code"] for finding in findings}
        self.assertNotIn("cis-missing-database-dumps", codes)

    def test_docker_mount_non_covered_warns(self) -> None:
        findings = check_docker_mount_coverage(
            [{"PROFILE_NAME": "generic", "BACKUP_PATHS": ["/etc"]}],
            [{"container_name": "app", "type": "bind", "source": "/srv/app/data", "destination": "/data", "name": ""}],
        )
        self.assertTrue(any(finding["code"] == "docker-bind-uncovered" for finding in findings))

    def test_db_docker_volume_is_considered_covered_by_logical_dump(self) -> None:
        findings = check_docker_mount_coverage(
            [
                {
                    "PROFILE_NAME": "cis-site",
                    "PROFILE_TYPE": "cis-site",
                    "BACKUP_PATHS": ["/etc"],
                    "DATABASE_DUMPS": [
                        "name=app-postgres;engine=postgresql;mode=docker;container=db;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"
                    ],
                }
            ],
            [
                {
                    "container_name": "db",
                    "type": "volume",
                    "source": "/var/lib/docker/volumes/app_db/_data",
                    "destination": "/var/lib/postgresql/data",
                    "name": "app_db",
                }
            ],
        )
        codes = {finding["code"] for finding in findings}
        self.assertIn("docker-db-covered-by-logical-dump", codes)
        self.assertNotIn("docker-volume-uncovered", codes)

    def test_env_file_non_covered_warns_without_reading_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "project"
            project.mkdir()
            compose = project / "docker-compose.yml"
            env_file = project / ".env"
            compose.write_text("services: {}\n", encoding="utf-8")
            env_file.write_text("SECRET=value\n", encoding="utf-8")
            findings = check_env_files_coverage(
                [{"PROFILE_NAME": "generic", "BACKUP_PATHS": ["/etc"]}],
                [str(compose)],
            )
        self.assertTrue(any(finding["code"] == "env-file-uncovered" for finding in findings))
        self.assertFalse(any("SECRET=value" in finding["message"] for finding in findings))

    def test_write_coverage_report_writes_txt_json_and_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            report = {
                "hostname": "test-host",
                "backup_name": "mes-fragrances",
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-19T00:01:00Z",
                "duration_seconds": 60.0,
                "status": "warning",
                "targets_count": 1,
                "profiles_count": 1,
                "summary": {"SUCCESS": 0, "WARNING": 1, "FAILURE": 0},
                "generic_findings": [],
                "target_findings": [],
                "profile_findings": [],
                "docker_findings": [],
                "cis_findings": [],
                "recommendations": [],
                "state_dir": str(state_dir),
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            }
            paths = write_coverage_report(report, report_dir)
            self.assertTrue(Path(paths["text_report_path"]).exists())
            self.assertTrue(Path(paths["json_report_path"]).exists())
            self.assertTrue((state_dir / LAST_COVERAGE_AUDIT_FILE).exists())
            payload = json.loads(Path(paths["json_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["RESTIC_PASSWORD_FILE"], "<redacted>")

    def test_run_coverage_audit_fails_when_no_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            global_config = {
                "__file__": "/etc/server-backup/backup.conf",
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "mes-fragrances",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": str(state_dir),
                "REPORT_DIR": str(report_dir),
                "RESTIC_CACHE_DIR": str(Path(tmpdir) / "cache"),
                "RESTIC_PASSWORD_FILE": str(Path(tmpdir) / "restic-password"),
                "RUN_RESTIC_CHECK": "true",
                "RUN_PRUNE": "true",
                "EMAIL_REPORT_ENABLED": "false",
            }
            Path(global_config["RESTIC_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(global_config["RESTIC_PASSWORD_FILE"]).write_text("secret\n", encoding="utf-8")
            profile_dir = Path(tmpdir) / "profile"
            profile_dir.mkdir()
            profile = {
                "__file__": "/etc/server-backup/profiles.d/generic.conf",
                "CONFIG_VERSION": "1",
                "PROFILE_NAME": "generic",
                "PROFILE_TYPE": "generic",
                "BACKUP_PATHS": [str(profile_dir)],
            }

            with patch("server_backup.coverage.load_global_config", return_value=global_config), patch(
                "server_backup.coverage.load_targets",
                return_value=[],
            ), patch(
                "server_backup.coverage.load_profiles",
                return_value=[profile],
            ), patch(
                "server_backup.coverage.collect_docker_inventory_light",
                return_value={"available": False, "reason": "docker not installed", "containers": [], "volumes": [], "warnings": []},
            ), patch(
                "server_backup.coverage.collect_docker_mounts",
                return_value=[],
            ):
                report = run_coverage_audit()

        self.assertEqual(report["status"], "failure")
        self.assertTrue(any(finding["code"] == "no-targets" for finding in report["target_findings"]))

    def test_run_coverage_audit_fails_when_no_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            state_dir = Path(tmpdir) / "state"
            global_config = {
                "__file__": "/etc/server-backup/backup.conf",
                "CONFIG_VERSION": "1",
                "BACKUP_NAME": "mes-fragrances",
                "RETENTION_DAILY": "14",
                "RETENTION_WEEKLY": "8",
                "RETENTION_MONTHLY": "12",
                "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
                "LOG_FILE": "/var/log/server-backup.log",
                "STATE_DIR": str(state_dir),
                "REPORT_DIR": str(report_dir),
                "RESTIC_CACHE_DIR": str(Path(tmpdir) / "cache"),
                "RESTIC_PASSWORD_FILE": str(Path(tmpdir) / "restic-password"),
                "RUN_RESTIC_CHECK": "true",
                "RUN_PRUNE": "true",
                "EMAIL_REPORT_ENABLED": "false",
            }
            Path(global_config["RESTIC_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(global_config["RESTIC_PASSWORD_FILE"]).write_text("secret\n", encoding="utf-8")

            with patch("server_backup.coverage.load_global_config", return_value=global_config), patch(
                "server_backup.coverage.load_targets",
                return_value=[{"TARGET_NAME": "nas-steph", "TARGET_TYPE": "sftp", "CONFIG_VERSION": "1", "RESTIC_REPOSITORY": "sftp:x:/repo", "RESTIC_PASSWORD_FILE": global_config["RESTIC_PASSWORD_FILE"], "RESTIC_CACHE_DIR": global_config["RESTIC_CACHE_DIR"], "SSH_HOST_ALIAS": "x", "SSH_HOSTNAME": "127.0.0.1", "SSH_PORT": "22", "SSH_USER": "backup", "SSH_IDENTITY_FILE": "/tmp/key"}],
            ), patch(
                "server_backup.coverage.load_profiles",
                return_value=[],
            ), patch(
                "server_backup.coverage.collect_docker_inventory_light",
                return_value={"available": False, "reason": "docker not installed", "containers": [], "volumes": [], "warnings": []},
            ), patch(
                "server_backup.coverage.collect_docker_mounts",
                return_value=[],
            ):
                report = run_coverage_audit()

        self.assertEqual(report["status"], "failure")
        self.assertTrue(any(finding["code"] == "no-profiles" for finding in report["profile_findings"]))

    def test_run_coverage_audit_refuses_dangerous_output_dir(self) -> None:
        with patch("server_backup.coverage.load_global_config", return_value={"BACKUP_NAME": "mes-fragrances"}), patch(
            "server_backup.coverage.load_targets",
            return_value=[],
        ), patch(
            "server_backup.coverage.load_profiles",
            return_value=[],
        ):
            with self.assertRaisesRegex(ValueError, "Refusing dangerous coverage report output directory"):
                run_coverage_audit(output_dir="/etc")

    def test_render_coverage_report_json_redacts_secrets(self) -> None:
        rendered = render_coverage_report_json({"RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password"})
        self.assertIn("<redacted>", rendered)


if __name__ == "__main__":
    unittest.main()
