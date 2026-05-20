from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.config import parse_config_file
from server_backup.docker import update_profile_backup_paths


class DockerProfileUpdateTests(unittest.TestCase):
    def test_update_profile_backup_paths_adds_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "docker-host.conf"
            profile_path.write_text(
                "\n".join(
                    [
                        'CONFIG_VERSION="1"',
                        'GENERATED_BY="server-backup"',
                        'GENERATED_AT="example"',
                        "",
                        'PROFILE_NAME="docker-host"',
                        'PROFILE_TYPE="docker-host"',
                        'DOCKER_INVENTORY="true"',
                        "",
                        "BACKUP_PATHS=(",
                        '  "/etc"',
                        ")",
                        "",
                        "EXCLUDES=(",
                        '  "/etc/server-backup/secrets"',
                        ")",
                        "",
                        "DATABASE_DUMPS=(",
                        '  "name=db;engine=postgresql;mode=docker;container=postgres;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/app/db.env"',
                        ")",
                        "",
                        "CONTENT_CLASSIFICATION=(",
                        '  "files:/srv/app/frontend:frontend"',
                        ")",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("server_backup.docker.os.geteuid", return_value=1000):
                result = update_profile_backup_paths(
                    profile_path,
                    ["/etc", "/var/lib/docker/volumes/caddy_data/_data"],
                )
            parsed = parse_config_file(profile_path)
            backups = list(profile_path.parent.glob("docker-host.conf.bak-*"))

        self.assertEqual(result["added_paths"], ["/var/lib/docker/volumes/caddy_data/_data"])
        self.assertEqual(parsed["BACKUP_PATHS"], ["/etc", "/var/lib/docker/volumes/caddy_data/_data"])
        self.assertEqual(parsed["EXCLUDES"], ["/etc/server-backup/secrets"])
        self.assertTrue(parsed["DATABASE_DUMPS"])
        self.assertTrue(parsed["CONTENT_CLASSIFICATION"])
        self.assertTrue(backups)

    def test_update_profile_backup_paths_no_changes_when_all_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "docker-host.conf"
            profile_path.write_text(
                "\n".join(
                    [
                        'CONFIG_VERSION="1"',
                        'GENERATED_BY="server-backup"',
                        'GENERATED_AT="example"',
                        "",
                        'PROFILE_NAME="docker-host"',
                        'PROFILE_TYPE="docker-host"',
                        "",
                        "BACKUP_PATHS=(",
                        '  "/etc"',
                        ")",
                        "",
                        "EXCLUDES=(",
                        ")",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("server_backup.docker.os.geteuid", return_value=1000):
                result = update_profile_backup_paths(profile_path, ["/etc"])

        self.assertEqual(result["added_paths"], [])
        self.assertEqual(result["skipped_paths"], ["/etc"])
        self.assertEqual(result["backup_path"], "")


if __name__ == "__main__":
    unittest.main()
