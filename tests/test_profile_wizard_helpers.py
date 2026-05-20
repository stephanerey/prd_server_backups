from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server_backup.wizard import find_compose_files, prompt_profile_type, sanitize_profile_name


class ProfileWizardHelpersTests(unittest.TestCase):
    def test_sanitize_profile_name(self) -> None:
        self.assertEqual(sanitize_profile_name("My App"), "my-app")
        self.assertEqual(sanitize_profile_name("___"), "profile")

    def test_find_compose_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            compose.write_text("services: {}\n", encoding="utf-8")
            override.write_text("services: {}\n", encoding="utf-8")

            found = find_compose_files(root)

        self.assertEqual([path.name for path in found], ["docker-compose.yml", "docker-compose.override.yml"])

    def test_prompt_profile_type_accepts_valid_choice(self) -> None:
        answers = iter(["cis-site"])
        result = prompt_profile_type(input_func=lambda _: next(answers))
        self.assertEqual(result, "cis-site")


if __name__ == "__main__":
    unittest.main()
