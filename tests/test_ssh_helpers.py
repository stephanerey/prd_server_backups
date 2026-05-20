from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.ssh import ensure_known_hosts_file, render_ssh_config_entry, sanitize_ssh_alias


class SshHelpersTests(unittest.TestCase):
    def test_sanitize_ssh_alias(self) -> None:
        self.assertEqual(sanitize_ssh_alias("server backup/nas"), "server-backup-nas")
        self.assertEqual(sanitize_ssh_alias(""), "target")

    def test_render_ssh_config_entry(self) -> None:
        rendered = render_ssh_config_entry(
            "server-backup-nas-home",
            "backup.example.net",
            2222,
            "backup-user",
            "/etc/server-backup/ssh/id_ed25519_nas-home",
            "/etc/server-backup/ssh/known_hosts",
        )
        self.assertIn("Host server-backup-nas-home", rendered)
        self.assertIn("HostName backup.example.net", rendered)
        self.assertIn("Port 2222", rendered)
        self.assertIn("StrictHostKeyChecking yes", rendered)

    def test_ensure_known_hosts_file_creates_root_only_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "known_hosts"
            created = ensure_known_hosts_file(path)
            self.assertEqual(created, path)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
