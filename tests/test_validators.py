from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.validators import (
    validate_global_config,
    validate_profile_config,
    validate_target_config,
)


class ValidatorTests(unittest.TestCase):
    def test_validate_global_config_minimal(self) -> None:
        config = {
            "__file__": "/etc/server-backup/backup.conf",
            "__kind__": "global",
            "__parse_warnings__": [],
            "CONFIG_VERSION": "1",
            "BACKUP_NAME": "example",
            "RETENTION_DAILY": "14",
            "RETENTION_WEEKLY": "8",
            "RETENTION_MONTHLY": "12",
            "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
            "LOG_FILE": "/var/log/server-backup.log",
            "STATE_DIR": "/var/lib/server-backup/state",
            "REPORT_DIR": "/var/lib/server-backup/reports",
            "RESTIC_CACHE_DIR": "/var/cache/restic",
            "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            "RUN_RESTIC_CHECK": "true",
            "RUN_PRUNE": "true",
        }
        result = validate_global_config(config)
        self.assertEqual(result.errors, [])

    def test_validate_target_sftp_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            private_key = Path(tmpdir) / "id_ed25519"
            ssh_config = Path(tmpdir) / "ssh_config"
            known_hosts = Path(tmpdir) / "known_hosts"
            private_key.write_text("private", encoding="utf-8")
            ssh_config.write_text("Host test\n", encoding="utf-8")
            known_hosts.write_text("example ssh-ed25519 AAAA\n", encoding="utf-8")
            private_key.chmod(0o600)
            ssh_config.chmod(0o600)
            known_hosts.chmod(0o600)

            target = {
                "__file__": "/etc/server-backup/targets.d/nas.env",
                "__kind__": "target",
                "__parse_warnings__": [],
                "CONFIG_VERSION": "1",
                "TARGET_NAME": "nas",
                "TARGET_TYPE": "sftp",
                "RESTIC_REPOSITORY": "sftp:alias:/repo",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
                "SSH_HOST_ALIAS": "alias",
                "SSH_HOSTNAME": "backup.example.net",
                "SSH_PORT": "22",
                "SSH_USER": "backup",
                "SSH_IDENTITY_FILE": str(private_key),
                "SSH_CONFIG_FILE": str(ssh_config),
                "SSH_KNOWN_HOSTS_FILE": str(known_hosts),
            }
            result = validate_target_config(target)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    def test_validate_profile_minimal(self) -> None:
        profile = {
            "__file__": "/etc/server-backup/profiles.d/example.conf",
            "__kind__": "profile",
            "__parse_warnings__": [],
            "CONFIG_VERSION": "1",
            "PROFILE_NAME": "example",
            "PROFILE_TYPE": "generic",
            "BACKUP_PATHS": ["/definitely/missing/path"],
        }
        result = validate_profile_config(profile)
        self.assertEqual(result.errors, [])
        self.assertTrue(result.warnings)

    def test_warning_on_future_target_backend(self) -> None:
        target = {
            "__file__": "/etc/server-backup/targets.d/future.env",
            "__kind__": "target",
            "__parse_warnings__": [],
            "CONFIG_VERSION": "1",
            "TARGET_NAME": "future",
            "TARGET_TYPE": "s3",
            "RESTIC_REPOSITORY": "s3:something",
            "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            "RESTIC_CACHE_DIR": "/var/cache/restic",
        }
        result = validate_target_config(target)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("future backend" in message for message in result.warnings))

    def test_warning_on_missing_sftp_support_files(self) -> None:
        target = {
            "__file__": "/etc/server-backup/targets.d/nas.env",
            "__kind__": "target",
            "__parse_warnings__": [],
            "CONFIG_VERSION": "1",
            "TARGET_NAME": "nas",
            "TARGET_TYPE": "sftp",
            "RESTIC_REPOSITORY": "sftp:alias:/repo",
            "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            "RESTIC_CACHE_DIR": "/var/cache/restic",
            "SSH_HOST_ALIAS": "alias",
            "SSH_HOSTNAME": "backup.example.net",
            "SSH_PORT": "22",
            "SSH_USER": "backup",
            "SSH_IDENTITY_FILE": "/missing/id_ed25519",
        }
        result = validate_target_config(target)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("SSH_CONFIG_FILE" in message for message in result.warnings))
        self.assertTrue(any("SSH_KNOWN_HOSTS_FILE" in message for message in result.warnings))

    def test_warning_on_missing_recommended_cis_fields(self) -> None:
        profile = {
            "__file__": "/etc/server-backup/profiles.d/cis.conf",
            "__kind__": "profile",
            "__parse_warnings__": [],
            "CONFIG_VERSION": "1",
            "PROFILE_NAME": "cis",
            "PROFILE_TYPE": "cis-site",
            "BACKUP_PATHS": ["/srv/cis"],
        }
        result = validate_profile_config(profile)
        self.assertEqual(result.errors, [])
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
