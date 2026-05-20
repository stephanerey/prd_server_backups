from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.config import parse_config_file
from server_backup.validators import validate_profile_config
from server_backup.wizard import render_profile_conf


class ProfileRenderingTests(unittest.TestCase):
    def test_render_generic_profile(self) -> None:
        rendered = render_profile_conf(
            {
                "PROFILE_NAME": "generic-app",
                "PROFILE_TYPE": "generic",
                "MISSING_PATH_BEHAVIOR": "warning",
                "BACKUP_PATHS": ["/srv/my-app", "/etc/my-app"],
                "EXCLUDES": ["**/.cache", "**/cache", "**/tmp"],
            },
            generated_at="2026-01-01T00:00:00Z",
        )
        self.assertIn('PROFILE_NAME="generic-app"', rendered)
        self.assertIn('PROFILE_TYPE="generic"', rendered)
        self.assertIn('MISSING_PATH_BEHAVIOR="warning"', rendered)

    def test_render_system_filesystem_profile(self) -> None:
        rendered = render_profile_conf(
            {
                "PROFILE_NAME": "system-filesystem",
                "PROFILE_TYPE": "system-filesystem",
                "BACKUP_PATHS": ["/etc", "/root", "/var/lib/server-backup/state"],
                "EXCLUDES": ["/proc", "/sys", "/tmp"],
            }
        )
        self.assertIn('PROFILE_TYPE="system-filesystem"', rendered)
        self.assertIn('  "/etc"', rendered)
        self.assertIn('  "/proc"', rendered)

    def test_render_docker_host_profile(self) -> None:
        rendered = render_profile_conf(
            {
                "PROFILE_NAME": "docker-host",
                "PROFILE_TYPE": "docker-host",
                "DOCKER_INVENTORY": "true",
                "BACKUP_PATHS": ["/etc", "/srv", "/var/lib/server-backup/state"],
                "EXCLUDES": ["/etc/server-backup/secrets", "/var/lib/docker/overlay2"],
            }
        )
        self.assertIn('PROFILE_TYPE="docker-host"', rendered)
        self.assertIn('DOCKER_INVENTORY="true"', rendered)

    def test_render_docker_app_profile(self) -> None:
        rendered = render_profile_conf(
            {
                "PROFILE_NAME": "my-docker-app",
                "PROFILE_TYPE": "docker-app",
                "DOCKER_INVENTORY": "true",
                "BACKUP_PATHS": ["/srv/my-docker-app", "/var/lib/docker/volumes/my_app_data/_data"],
                "EXCLUDES": ["**/.cache", "**/node_modules"],
                "__comments__": [
                    "# DATABASE_DUMPS will be configured by:",
                    "# sudo server-backup db add",
                ],
            }
        )
        self.assertIn('PROFILE_TYPE="docker-app"', rendered)
        self.assertIn("# DATABASE_DUMPS will be configured by:", rendered)

    def test_render_cis_site_profile_and_validate_warning_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "cis project"
            frontend = project / "frontend"
            backend = project / "backend"
            alembic = backend / "alembic"
            state_dir = Path(tmpdir) / "state"
            for path in (frontend, alembic, state_dir):
                path.mkdir(parents=True, exist_ok=True)

            rendered = render_profile_conf(
                {
                    "PROFILE_NAME": "cis-site",
                    "PROFILE_TYPE": "cis-site",
                    "APP_KIND": "cis-site",
                    "WEB_CONTENT_CRITICAL": "true",
                    "DOCKER_INVENTORY": "true",
                    "BACKUP_PATHS": [
                        str(project),
                        str(frontend),
                        str(backend),
                        str(alembic),
                        str(state_dir),
                    ],
                    "EXCLUDES": ["**/.cache", "**/.next/cache"],
                    "CONTENT_CLASSIFICATION": [
                        "db:postgresql:<database-placeholder>:site_pages:builder-pages",
                        f"files:{frontend}:frontend-renderer-and-routes",
                        f"files:{backend}:api-models-and-migrations",
                    ],
                    "__comments__": [
                        "# DATABASE_DUMPS will be configured by:",
                        "# sudo server-backup db add",
                    ],
                }
            )

            profile_path = Path(tmpdir) / "cis-site.conf"
            profile_path.write_text(rendered, encoding="utf-8")
            parsed = parse_config_file(profile_path)
            result = validate_profile_config(parsed)

        self.assertEqual(result.errors, [])
        self.assertTrue(any("DATABASE_DUMPS" in message for message in result.warnings))
        self.assertIn("CONTENT_CLASSIFICATION", parsed)

    def test_generated_profile_is_parsable_with_spaces(self) -> None:
        rendered = render_profile_conf(
            {
                "PROFILE_NAME": "generic-app",
                "PROFILE_TYPE": "generic",
                "BACKUP_PATHS": ["/srv/My App", "/etc/My App"],
                "EXCLUDES": ["**/.cache"],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "generic.conf"
            profile_path.write_text(rendered, encoding="utf-8")
            parsed = parse_config_file(profile_path)

        self.assertEqual(parsed["BACKUP_PATHS"], ["/srv/My App", "/etc/My App"])


if __name__ == "__main__":
    unittest.main()
