from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_backup.restic import (
    INTERRUPTED_MESSAGE,
    OperationInterruptedError,
    build_restic_base_command,
    build_restic_env,
    build_sftp_command,
    explain_restic_failure,
    restic_repo_lock,
    run_restic_command,
    select_target,
    validate_restic_preflight,
)


class ResticHelpersTests(unittest.TestCase):
    def test_build_sftp_command(self) -> None:
        command = build_sftp_command(
            {
                "SSH_CONFIG_FILE": "/etc/server-backup/ssh/ssh_config",
                "SSH_HOST_ALIAS": "server-backup-nas-steph",
            }
        )
        self.assertEqual(command, "ssh -F /etc/server-backup/ssh/ssh_config server-backup-nas-steph -s sftp")

    def test_build_restic_env_uses_target_values(self) -> None:
        env = build_restic_env(
            {
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
            },
            {
                "RESTIC_REPOSITORY": "sftp:alias:/repo",
                "RESTIC_PASSWORD_FILE": "/etc/server-backup/secrets/restic-password",
                "RESTIC_CACHE_DIR": "/var/cache/restic",
            },
        )
        self.assertEqual(env["RESTIC_REPOSITORY"], "sftp:alias:/repo")
        self.assertEqual(env["RESTIC_PASSWORD_FILE"], "/etc/server-backup/secrets/restic-password")
        self.assertEqual(env["RESTIC_CACHE_DIR"], "/var/cache/restic")

    def test_build_restic_base_command_uses_shell_false_style_args(self) -> None:
        with patch("server_backup.restic.shutil.which", return_value="/usr/bin/restic"):
            command = build_restic_base_command(
                {
                    "SSH_CONFIG_FILE": "/etc/server-backup/ssh/ssh_config",
                    "SSH_HOST_ALIAS": "server-backup-nas-steph",
                }
            )
        self.assertEqual(command[0], "restic")
        self.assertIn("sftp.command=ssh -F /etc/server-backup/ssh/ssh_config server-backup-nas-steph -s sftp", command[2])

    def test_select_target_by_name(self) -> None:
        target = select_target("nas-steph", [{"TARGET_NAME": "nas-steph"}])
        self.assertEqual(target["TARGET_NAME"], "nas-steph")

    def test_select_target_missing_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Target not found"):
            select_target("missing", [{"TARGET_NAME": "nas-steph"}])

    def test_validate_restic_preflight_detects_missing_password_and_ssh_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            private_key = Path(tmpdir) / "id_ed25519"
            known_hosts = Path(tmpdir) / "known_hosts"
            private_key.write_text("private", encoding="utf-8")
            known_hosts.write_text("host ssh-ed25519 AAAA\n", encoding="utf-8")
            private_key.chmod(0o600)
            known_hosts.chmod(0o600)

            with patch("server_backup.restic.shutil.which", return_value="/usr/bin/restic"):
                result = validate_restic_preflight(
                    {
                        "RESTIC_PASSWORD_FILE": str(Path(tmpdir) / "missing-password"),
                        "RESTIC_CACHE_DIR": str(Path(tmpdir) / "cache"),
                    },
                    {
                        "__file__": "/etc/server-backup/targets.d/nas-steph.env",
                        "__kind__": "target",
                        "__parse_warnings__": [],
                        "CONFIG_VERSION": "1",
                        "TARGET_NAME": "nas-steph",
                        "TARGET_TYPE": "sftp",
                        "RESTIC_REPOSITORY": "sftp:alias:/repo",
                        "RESTIC_PASSWORD_FILE": str(Path(tmpdir) / "missing-password"),
                        "RESTIC_CACHE_DIR": str(Path(tmpdir) / "cache"),
                        "SSH_HOST_ALIAS": "alias",
                        "SSH_HOSTNAME": "10.0.0.1",
                        "SSH_PORT": "22",
                        "SSH_USER": "backup",
                        "SSH_IDENTITY_FILE": str(private_key),
                        "SSH_CONFIG_FILE": str(Path(tmpdir) / "missing-ssh-config"),
                        "SSH_KNOWN_HOSTS_FILE": str(known_hosts),
                    },
                )

        self.assertTrue(any("RESTIC_PASSWORD_FILE not found" in message for message in result.errors))
        self.assertTrue(any("SSH_CONFIG_FILE not found" in message for message in result.errors))

    def test_run_restic_command_uses_subprocess_without_shell(self) -> None:
        with patch("server_backup.restic.subprocess.run") as mocked_run:
            mocked_run.return_value.returncode = 0
            run_restic_command(["restic", "snapshots"], {"RESTIC_REPOSITORY": "x"}, timeout=30)

        _, kwargs = mocked_run.call_args
        self.assertEqual(kwargs["shell"], False)

    def test_run_restic_command_converts_keyboard_interrupt(self) -> None:
        with patch("server_backup.restic.subprocess.run", side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(OperationInterruptedError, INTERRUPTED_MESSAGE):
                run_restic_command(["restic", "snapshots"], {"RESTIC_REPOSITORY": "x"}, timeout=30)

    def test_explain_restic_failure_classifies_damaged_repository(self) -> None:
        class Result:
            stdout = ""
            stderr = "Fatal: config or key abc is damaged: ciphertext verification failed"

        message = explain_restic_failure(Result())  # type: ignore[arg-type]
        self.assertIn("damaged or unreadable", message)

    def test_restic_repo_lock_can_be_acquired_and_reacquired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "repo.lock"
            with restic_repo_lock(timeout_seconds=0, lock_path=lock_path):
                self.assertTrue(lock_path.exists())

            with restic_repo_lock(timeout_seconds=0, lock_path=lock_path):
                self.assertTrue(lock_path.exists())

    def test_restic_repo_lock_second_process_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "repo.lock"
            env = os.environ.copy()
            repo_root = Path(__file__).resolve().parents[1]
            env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
            script = """
from server_backup.restic import restic_repo_lock
import sys
try:
    with restic_repo_lock(timeout_seconds=0.2, lock_path=sys.argv[1]):
        print("child-acquired")
except RuntimeError as exc:
    print(str(exc))
    raise SystemExit(1)
"""
            with restic_repo_lock(timeout_seconds=0, lock_path=lock_path):
                result = subprocess.run(
                    [sys.executable, "-c", script, str(lock_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Another server-backup restic operation is already running.", result.stdout)


if __name__ == "__main__":
    unittest.main()
