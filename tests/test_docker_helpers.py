from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.docker import (
    classify_docker_mount,
    compare_mounts_to_backup_paths,
    discover_compose_files,
    discover_env_files_near_compose,
    docker_volume_data_path,
    suggest_missing_docker_paths,
)


class DockerHelpersTests(unittest.TestCase):
    def test_docker_volume_data_path(self) -> None:
        self.assertEqual(
            docker_volume_data_path("my_volume"),
            "/var/lib/docker/volumes/my_volume/_data",
        )

    def test_classify_database_volume(self) -> None:
        classified = classify_docker_mount(
            {
                "container_name": "postgres",
                "image": "postgres:17",
                "type": "volume",
                "name": "pgdata",
                "source": "/var/lib/docker/volumes/pgdata/_data",
                "destination": "/var/lib/postgresql/data",
            }
        )
        self.assertTrue(classified["is_database"])
        self.assertEqual(classified["category"], "database")

    def test_classify_reverse_proxy_volume(self) -> None:
        classified = classify_docker_mount(
            {
                "container_name": "caddy",
                "image": "caddy:2",
                "type": "volume",
                "name": "caddy_data",
                "source": "/var/lib/docker/volumes/caddy_data/_data",
                "destination": "/data",
            }
        )
        self.assertTrue(classified["is_reverse_proxy"])
        self.assertEqual(classified["category"], "reverse-proxy")

    def test_classify_bind_mount(self) -> None:
        classified = classify_docker_mount(
            {
                "container_name": "app",
                "image": "myapp:latest",
                "type": "bind",
                "source": "/srv/my-app/data",
                "destination": "/data",
                "name": "",
            }
        )
        self.assertEqual(classified["kind"], "bind-mount")
        self.assertEqual(classified["candidate_path"], "/srv/my-app/data")

    def test_compare_mounts_detects_covered_and_uncovered(self) -> None:
        profiles = [{"PROFILE_NAME": "docker-host", "BACKUP_PATHS": ["/srv/my-app", "/var/lib/docker/volumes/caddy_data/_data"]}]
        mounts = [
            {
                "container_name": "app",
                "image": "myapp:latest",
                "type": "bind",
                "source": "/srv/my-app/data",
                "destination": "/data",
                "name": "",
            },
            {
                "container_name": "cache",
                "image": "redis:7",
                "type": "volume",
                "source": "/var/lib/docker/volumes/redis_data/_data",
                "destination": "/data",
                "name": "redis_data",
            },
        ]
        results = compare_mounts_to_backup_paths(mounts, profiles)
        by_container = {item["container_name"]: item for item in results}
        self.assertEqual(by_container["app"]["coverage_status"], "covered")
        self.assertEqual(by_container["cache"]["coverage_status"], "uncovered")

    def test_database_volume_with_logical_dump_is_covered_by_dump(self) -> None:
        profiles = [
            {
                "PROFILE_NAME": "cis-site",
                "PROFILE_TYPE": "cis-site",
                "BACKUP_PATHS": ["/srv/cis"],
                "DATABASE_DUMPS": [
                    "name=app-postgres;engine=postgresql;mode=docker;container=postgres;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/cis-site/app-postgres.env"
                ],
            }
        ]
        mounts = [
            {
                "container_name": "postgres",
                "image": "postgres:17",
                "type": "volume",
                "source": "/var/lib/docker/volumes/pgdata/_data",
                "destination": "/var/lib/postgresql/data",
                "name": "pgdata",
            }
        ]
        results = compare_mounts_to_backup_paths(mounts, profiles)
        self.assertEqual(results[0]["coverage_status"], "covered-by-logical-dump")

    def test_suggest_missing_docker_paths_prefers_docker_host_for_reverse_proxy(self) -> None:
        profiles = [
            {"PROFILE_NAME": "docker-host", "PROFILE_TYPE": "docker-host", "BACKUP_PATHS": ["/etc"]},
            {"PROFILE_NAME": "cis-site", "PROFILE_TYPE": "cis-site", "BACKUP_PATHS": ["/srv/cis"]},
        ]
        mounts = [
            {
                "container_name": "caddy",
                "image": "caddy:2",
                "type": "volume",
                "source": "/var/lib/docker/volumes/caddy_data/_data",
                "destination": "/data",
                "name": "caddy_data",
            }
        ]
        suggestions = suggest_missing_docker_paths(profiles, mounts)
        self.assertEqual(len(suggestions), 1)
        self.assertIn(suggestions[0]["suggested_profile"], {"docker-host", "cis-site"})

    def test_env_files_are_detected_without_reading_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "project"
            project.mkdir()
            compose = project / "docker-compose.yml"
            env_file = project / ".env"
            compose.write_text("services: {}\n", encoding="utf-8")
            env_file.write_text("SECRET=value\n", encoding="utf-8")

            compose_files = discover_compose_files([str(project)])
            env_files = discover_env_files_near_compose(compose_files)

        self.assertEqual(compose_files, [str(compose)])
        self.assertEqual(env_files, [str(env_file)])


if __name__ == "__main__":
    unittest.main()
