from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.db import (
    build_postgres_dump_command,
    build_postgres_test_command,
    parse_database_dump_spec,
    read_db_secret_file,
    render_database_dump_spec,
    update_profile_database_dumps,
    write_db_secret_file,
)


class DbHelpersTests(unittest.TestCase):
    def test_parse_and_render_database_dump_spec_roundtrip(self) -> None:
        raw = (
            "name=app-postgres;engine=postgresql;mode=docker;container=postgres;"
            "user=app;databases=appdb,analytics;globals=true;"
            "secret=/etc/server-backup/secrets/db/app/postgres.env"
        )
        parsed = parse_database_dump_spec(raw)
        self.assertEqual(parsed["name"], "app-postgres")
        self.assertEqual(parsed["engine"], "postgresql")
        self.assertEqual(parsed["mode"], "docker")
        self.assertEqual(parsed["databases"], ["appdb", "analytics"])
        self.assertTrue(parsed["globals"])

        rendered = render_database_dump_spec(parsed)
        reparsed = parse_database_dump_spec(rendered)
        self.assertEqual(reparsed["name"], "app-postgres")
        self.assertEqual(reparsed["databases"], ["appdb", "analytics"])
        self.assertTrue(reparsed["globals"])

    def test_write_and_read_db_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_path = Path(tmpdir) / "db" / "postgres.env"
            with patch("server_backup.db.os.geteuid", return_value=1000):
                write_db_secret_file(secret_path, "postgresql", "super-secret")

            self.assertTrue(secret_path.exists())
            self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(secret_path.parent.stat().st_mode), 0o700)
            secret_values = read_db_secret_file(secret_path)
            self.assertEqual(secret_values["PGPASSWORD"], "super-secret")

    def test_postgres_commands_do_not_contain_password_arguments(self) -> None:
        spec = {
            "name": "app-postgres",
            "engine": "postgresql",
            "mode": "docker",
            "container": "postgres",
            "user": "app",
            "databases": ["appdb"],
        }
        test_command = build_postgres_test_command(spec)
        dump_command = build_postgres_dump_command(spec, "appdb")
        self.assertIn("PGPASSWORD", test_command)
        self.assertIn("PGPASSWORD", dump_command)
        self.assertFalse(any("super-secret" in part for part in test_command))
        self.assertFalse(any("super-secret" in part for part in dump_command))

    def test_update_profile_database_dumps_preserves_profile_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.conf"
            profile_path.write_text(
                "\n".join(
                    [
                        'CONFIG_VERSION="1"',
                        'GENERATED_BY="server-backup"',
                        'GENERATED_AT="example"',
                        "",
                        'PROFILE_NAME="cis-site"',
                        'PROFILE_TYPE="cis-site"',
                        'WEB_CONTENT_CRITICAL="true"',
                        "",
                        "BACKUP_PATHS=(",
                        '  "/srv/cis-project"',
                        '  "/srv/cis-project/frontend"',
                        ")",
                        "",
                        "EXCLUDES=(",
                        '  "**/.cache"',
                        ")",
                        "",
                        "CONTENT_CLASSIFICATION=(",
                        '  "files:/srv/cis-project/frontend:frontend"',
                        ")",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            dump_spec = (
                "name=app-postgres;engine=postgresql;mode=local;host=localhost;port=5432;"
                "user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"
            )

            update_profile_database_dumps(profile_path, dump_spec)
            content = profile_path.read_text(encoding="utf-8")
            backups = list(profile_path.parent.glob("profile.conf.bak-*"))

        self.assertIn('PROFILE_NAME="cis-site"', content)
        self.assertIn('"/srv/cis-project/frontend"', content)
        self.assertIn("DATABASE_DUMPS=(", content)
        self.assertIn("name=app-postgres;engine=postgresql", content)
        self.assertTrue(backups)


if __name__ == "__main__":
    unittest.main()
