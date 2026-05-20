from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from server_backup import cli
from server_backup.cli import build_parser
from server_backup.validators import ValidationResult


class DockerCliTests(unittest.TestCase):
    def test_docker_parser_supports_new_commands(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["docker", "add-missing-paths", "--profile", "docker-host", "--dry-run"])
        self.assertEqual(args.command, "docker")
        self.assertEqual(args.docker_command, "add-missing-paths")
        self.assertEqual(args.profile, "docker-host")
        self.assertTrue(args.dry_run)

    def test_cmd_docker_scan_prints_summary(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["docker", "scan"])
        with patch("server_backup.cli.load_global_config", return_value={"STATE_DIR": "/tmp/state"}), patch(
            "server_backup.cli.load_profiles",
            return_value=[],
        ), patch(
            "server_backup.cli._build_docker_inventory_payload",
            return_value={
                "docker": {"available": True, "version": "28.0.0"},
                "warnings": [],
                "running_containers": [{"name": "app", "image": "myapp:latest"}],
                "volumes": ["app_data"],
                "compose_files": ["/srv/app/docker-compose.yml"],
                "env_files": ["/srv/app/.env"],
            },
        ), patch(
            "server_backup.cli.collect_bind_mounts",
            return_value=[{"source": "/srv/app/data"}],
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_docker_scan(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Running containers: 1", stdout.getvalue())

    def test_cmd_docker_inventory_writes_reports(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["docker", "inventory"])
        with patch("server_backup.cli.load_global_config", return_value={"STATE_DIR": "/tmp/state"}), patch(
            "server_backup.cli.load_profiles",
            return_value=[],
        ), patch(
            "server_backup.cli._build_docker_inventory_payload",
            return_value={
                "docker": {"available": True},
                "running_containers": [],
                "stopped_containers": [],
                "volumes": [],
                "mounts": [],
                "compose_files": [],
                "env_files": [],
                "warnings": [],
                "state_dir": "/tmp/state",
            },
        ), patch(
            "server_backup.cli.write_docker_inventory",
            return_value={"text_report_path": "/tmp/state/docker.txt", "json_report_path": "/tmp/state/docker.json"},
        ) as mocked_write:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_docker_inventory(args)

        self.assertEqual(exit_code, 0)
        mocked_write.assert_called_once()
        self.assertIn("/tmp/state/docker.txt", stdout.getvalue())

    def test_cmd_docker_add_missing_paths_dry_run_does_not_modify(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["docker", "add-missing-paths", "--profile", "docker-host", "--dry-run"])
        with patch(
            "server_backup.cli.load_profiles",
            return_value=[{"PROFILE_NAME": "docker-host", "__file__": "/tmp/docker-host.conf"}],
        ), patch(
            "server_backup.cli.docker_available",
            return_value={"available": True},
        ), patch(
            "server_backup.cli.collect_container_mounts",
            return_value=[],
        ), patch(
            "server_backup.cli.suggest_missing_docker_paths",
            return_value=[
                {
                    "container_name": "caddy",
                    "candidate_path": "/var/lib/docker/volumes/caddy_data/_data",
                    "suggested_profile": "docker-host",
                    "category": "reverse-proxy",
                    "reason": "Reverse proxy data usually belongs in a cis-site or docker-host profile.",
                    "requires_explicit_db_confirmation": False,
                    "mount": {"is_database": False},
                    "volume_name": "caddy_data",
                }
            ],
        ), patch(
            "server_backup.cli.update_profile_backup_paths",
        ) as mocked_update:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_docker_add_missing_paths(args)

        self.assertEqual(exit_code, 0)
        self.assertFalse(mocked_update.called)
        self.assertIn("Dry-run only. No profile was modified.", stdout.getvalue())

    def test_cmd_docker_add_missing_paths_updates_profile(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["docker", "add-missing-paths", "--profile", "docker-host"])
        with patch(
            "server_backup.cli.load_profiles",
            return_value=[{"PROFILE_NAME": "docker-host", "__file__": "/tmp/docker-host.conf"}],
        ), patch(
            "server_backup.cli.docker_available",
            return_value={"available": True},
        ), patch(
            "server_backup.cli.collect_container_mounts",
            return_value=[],
        ), patch(
            "server_backup.cli.suggest_missing_docker_paths",
            return_value=[
                {
                    "container_name": "caddy",
                    "candidate_path": "/var/lib/docker/volumes/caddy_data/_data",
                    "suggested_profile": "docker-host",
                    "category": "reverse-proxy",
                    "reason": "Reverse proxy data usually belongs in a cis-site or docker-host profile.",
                    "requires_explicit_db_confirmation": False,
                    "mount": {"is_database": False},
                    "volume_name": "caddy_data",
                }
            ],
        ), patch(
            "builtins.input",
            return_value="y",
        ), patch(
            "server_backup.cli.update_profile_backup_paths",
            return_value={
                "backup_path": "/tmp/docker-host.conf.bak-20260519-000000",
                "added_paths": ["/var/lib/docker/volumes/caddy_data/_data"],
                "skipped_paths": [],
                "validation": ValidationResult(),
            },
        ) as mocked_update:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.cmd_docker_add_missing_paths(args)

        self.assertEqual(exit_code, 0)
        mocked_update.assert_called_once()
        self.assertIn("Added paths:", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
