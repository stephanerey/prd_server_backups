from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from server_backup.config import parse_config_file, redact_config


class ConfigParserTests(unittest.TestCase):
    def _write(self, content: str, name: str = "backup.conf") -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / name
        path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
        return path

    def test_parses_quoted_and_unquoted_values(self) -> None:
        path = self._write(
            """
            KEY1="value one"
            KEY2='value two'
            KEY3=value3
            """
        )
        parsed = parse_config_file(path)
        self.assertEqual(parsed["KEY1"], "value one")
        self.assertEqual(parsed["KEY2"], "value two")
        self.assertEqual(parsed["KEY3"], "value3")

    def test_parses_simple_bash_arrays(self) -> None:
        path = self._write(
            """
            BACKUP_PATHS=(
              "/srv/app"
              "/etc"
            )
            """
        )
        parsed = parse_config_file(path)
        self.assertEqual(parsed["BACKUP_PATHS"], ["/srv/app", "/etc"])

    def test_ignores_comments_and_blank_lines(self) -> None:
        path = self._write(
            """
            # comment

            KEY=value
            """
        )
        parsed = parse_config_file(path)
        self.assertEqual(parsed["KEY"], "value")
        self.assertEqual(parsed["__parse_warnings__"], [])

    def test_redacts_sensitive_values(self) -> None:
        payload = {
            "PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
            "NORMAL": "visible",
            "MYSQL_PWD": "secret",
        }
        redacted = redact_config(payload)
        self.assertEqual(redacted["PASSWORD_FILE"], "<redacted>")
        self.assertEqual(redacted["MYSQL_PWD"], "<redacted>")
        self.assertEqual(redacted["NORMAL"], "visible")

    def test_example_paths_get_expected_kind(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "examples" / "targets"
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / "sftp.env.example"
        file_path.write_text('TARGET_NAME="example"\n', encoding="utf-8")
        parsed = parse_config_file(file_path)
        self.assertEqual(parsed["__kind__"], "target")


if __name__ == "__main__":
    unittest.main()
