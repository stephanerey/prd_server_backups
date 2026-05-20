from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.config import parse_config_file
from server_backup.validators import validate_target_config
from server_backup.wizard import render_target_env, sanitize_target_name


class TargetRenderingTests(unittest.TestCase):
    def test_sanitize_target_name(self) -> None:
        self.assertEqual(sanitize_target_name("NAS Home"), "nas-home")
        self.assertEqual(sanitize_target_name("___"), "target")

    def test_render_target_env_contains_expected_fields(self) -> None:
        rendered = render_target_env(
            {
                "TARGET_NAME": "nas-home",
                "TARGET_TYPE": "sftp",
                "SSH_HOST_ALIAS": "server-backup-nas-home",
                "SSH_HOSTNAME": "backup.example.net",
                "SSH_PORT": "2222",
                "SSH_USER": "backup-user",
                "SSH_IDENTITY_FILE": "/etc/server-backup/ssh/id_ed25519_nas-home",
                "SSH_CONFIG_FILE": "/etc/server-backup/ssh/ssh_config",
                "SSH_KNOWN_HOSTS_FILE": "/etc/server-backup/ssh/known_hosts",
                "RESTIC_REPOSITORY": "sftp:server-backup-nas-home:/backups/pyparfums-prod/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
            },
            generated_at="2026-01-01T00:00:00Z",
        )
        self.assertIn('CONFIG_VERSION="1"', rendered)
        self.assertIn('TARGET_NAME="nas-home"', rendered)
        self.assertIn('SSH_CONFIG_FILE="/etc/server-backup/ssh/ssh_config"', rendered)
        self.assertIn('RESTIC_REPOSITORY="sftp:server-backup-nas-home:/backups/pyparfums-prod/restic"', rendered)

    def test_rendered_target_env_is_parsable(self) -> None:
        rendered = render_target_env(
            {
                "TARGET_NAME": "nas-home",
                "TARGET_TYPE": "sftp",
                "SSH_HOST_ALIAS": "server-backup-nas-home",
                "SSH_HOSTNAME": "backup.example.net",
                "SSH_PORT": "2222",
                "SSH_USER": "backup-user",
                "SSH_IDENTITY_FILE": "/etc/server-backup/ssh/id_ed25519_nas-home",
                "SSH_CONFIG_FILE": "/etc/server-backup/ssh/ssh_config",
                "SSH_KNOWN_HOSTS_FILE": "/etc/server-backup/ssh/known_hosts",
                "RESTIC_REPOSITORY": "sftp:server-backup-nas-home:/backups/pyparfums-prod/restic",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nas-home.env"
            path.write_text(rendered, encoding="utf-8")
            parsed = parse_config_file(path)

        self.assertEqual(parsed["TARGET_NAME"], "nas-home")
        self.assertEqual(parsed["SSH_HOST_ALIAS"], "server-backup-nas-home")
        self.assertEqual(parsed["RESTIC_REPOSITORY"], "sftp:server-backup-nas-home:/backups/pyparfums-prod/restic")

    def test_generated_target_config_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            private_key = Path(tmpdir) / "id_ed25519_nas-home"
            ssh_config = Path(tmpdir) / "ssh_config"
            known_hosts = Path(tmpdir) / "known_hosts"
            private_key.write_text("private", encoding="utf-8")
            ssh_config.write_text("Host test\n", encoding="utf-8")
            known_hosts.write_text("example ssh-ed25519 AAAA\n", encoding="utf-8")
            private_key.chmod(0o600)
            ssh_config.chmod(0o600)
            known_hosts.chmod(0o600)

            rendered = render_target_env(
                {
                    "TARGET_NAME": "nas-home",
                    "TARGET_TYPE": "sftp",
                    "SSH_HOST_ALIAS": "server-backup-nas-home",
                    "SSH_HOSTNAME": "backup.example.net",
                    "SSH_PORT": "2222",
                    "SSH_USER": "backup-user",
                    "SSH_IDENTITY_FILE": str(private_key),
                    "SSH_CONFIG_FILE": str(ssh_config),
                    "SSH_KNOWN_HOSTS_FILE": str(known_hosts),
                    "RESTIC_REPOSITORY": "sftp:server-backup-nas-home:/backups/pyparfums-prod/restic",
                    "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                    "RESTIC_CACHE_DIR": "/var/cache/restic",
                }
            )
            env_path = Path(tmpdir) / "nas-home.env"
            env_path.write_text(rendered, encoding="utf-8")
            parsed = parse_config_file(env_path)

        result = validate_target_config(parsed)
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
