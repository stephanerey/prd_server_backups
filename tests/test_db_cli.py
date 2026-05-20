from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser


class DbCliTests(unittest.TestCase):
    def test_db_add_parser_supports_profile(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "add", "--profile", "cis-site"])
        self.assertEqual(args.command, "db")
        self.assertEqual(args.db_command, "add")
        self.assertEqual(args.profile, "cis-site")

    def test_db_test_parser_supports_all(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "test", "--all"])
        self.assertTrue(args.all)
        self.assertIsNone(args.name)

    def test_db_dump_test_parser_supports_keep_output(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "dump-test", "app-postgres", "--keep-output"])
        self.assertEqual(args.name, "app-postgres")
        self.assertTrue(args.keep_output)

    def test_cmd_db_list_prints_redacted_entries(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "list"])
        with patch(
            "server_backup.cli.load_profiles",
            return_value=[{"PROFILE_NAME": "cis-site"}],
        ), patch(
            "server_backup.cli.list_database_dumps",
            return_value=[
                {
                    "name": "app-postgres",
                    "__profile_name__": "cis-site",
                    "engine": "postgresql",
                    "mode": "docker",
                    "container": "postgres",
                    "user": "app",
                    "databases": ["appdb"],
                    "globals": True,
                }
            ],
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_db_list(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Configured database dumps: 1", stdout.getvalue())
        self.assertIn("app-postgres", stdout.getvalue())

    def test_cmd_db_test_unknown_dump_returns_non_zero(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "test", "missing"])
        stderr = io.StringIO()
        with patch("server_backup.cli._load_database_dump_bundle", return_value=[]):
            with redirect_stderr(stderr):
                exit_code = cli.cmd_db_test(args)

        self.assertEqual(exit_code, 1)
        self.assertIn("Database dump not found: missing", stderr.getvalue())

    def test_cmd_db_dump_test_calls_runner(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["db", "dump-test", "app-postgres", "--keep-output"])
        with patch(
            "server_backup.cli._load_database_dump_bundle",
            return_value=[{"name": "app-postgres", "__profile_name__": "cis-site"}],
        ), patch(
            "server_backup.cli.run_dump_test",
            return_value={
                "status": "success",
                "keep_output": True,
                "output_cleaned": False,
                "output_dir": "/var/tmp/server-backup/db-dump-test-x",
                "files": ["/var/tmp/server-backup/db-dump-test-x/app.dump"],
                "warnings": [],
                "errors": [],
            },
        ) as mocked_dump_test:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_db_dump_test(args)

        self.assertEqual(exit_code, 0)
        mocked_dump_test.assert_called_once()
        self.assertIn("Keep output: yes", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
