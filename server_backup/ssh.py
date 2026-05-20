from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


DEFAULT_SSH_DIR = Path("/etc/server-backup/ssh")
DEFAULT_SSH_CONFIG = DEFAULT_SSH_DIR / "ssh_config"
DEFAULT_KNOWN_HOSTS = DEFAULT_SSH_DIR / "known_hosts"

ConfirmFunc = Callable[[Path], bool]


class SshCommandError(RuntimeError):
    pass


def _require_command(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        raise SshCommandError(f"Required command not found: {command}")
    return resolved


def sanitize_ssh_alias(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    cleaned = cleaned.strip("-._")
    if not cleaned:
        cleaned = "target"
    return cleaned


def _backup_existing(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    shutil.copy2(path, backup_path)


def _maybe_chown_root(path: Path) -> None:
    if os.geteuid() != 0:
        return
    os.chown(path, 0, 0)


def generate_ed25519_key(private_key_path: str | Path, comment: str) -> tuple[Path, Path]:
    ssh_keygen = _require_command("ssh-keygen")
    private_path = Path(private_key_path)
    public_path = private_path.with_name(private_path.name + ".pub")
    private_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            ssh_keygen,
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            comment,
            "-f",
            str(private_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SshCommandError(result.stderr.strip() or "ssh-keygen failed")

    os.chmod(private_path, 0o600)
    os.chmod(public_path, 0o644)
    _maybe_chown_root(private_path)
    _maybe_chown_root(public_path)
    return private_path, public_path


def get_public_key(public_key_path: str | Path) -> str:
    return Path(public_key_path).read_text(encoding="utf-8").strip()


def render_ssh_config_entry(
    alias: str,
    hostname: str,
    port: int | str,
    user: str,
    identity_file: str | Path,
    known_hosts_file: str | Path,
) -> str:
    return "\n".join(
        [
            f"Host {alias}",
            f"    HostName {hostname}",
            f"    User {user}",
            f"    Port {port}",
            f"    IdentityFile {identity_file}",
            "    IdentitiesOnly yes",
            f"    UserKnownHostsFile {known_hosts_file}",
            "    StrictHostKeyChecking yes",
            "    ServerAliveInterval 30",
            "    ServerAliveCountMax 3",
            "",
        ]
    )


def _replace_host_block(existing: str, alias: str, rendered_entry: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?ms)^Host {re.escape(alias)}\n.*?(?=^Host |\Z)")
    if pattern.search(existing):
        return pattern.sub(rendered_entry, existing, count=1), True
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + rendered_entry, False


def write_ssh_config_entry(
    alias: str,
    rendered_entry: str,
    ssh_config_file: str | Path = DEFAULT_SSH_CONFIG,
) -> Path:
    config_path = Path(ssh_config_file)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    current = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated, _ = _replace_host_block(current, alias, rendered_entry)
    config_path.write_text(updated, encoding="utf-8")
    os.chmod(config_path, 0o600)
    _maybe_chown_root(config_path)
    return config_path


def remove_or_replace_ssh_config_entry(
    alias: str,
    rendered_entry: str,
    confirm: ConfirmFunc,
    ssh_config_file: str | Path = DEFAULT_SSH_CONFIG,
) -> bool:
    config_path = Path(ssh_config_file)
    current = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated, existed = _replace_host_block(current, alias, rendered_entry)
    if existed and updated == current:
        return True
    if existed and not confirm(config_path):
        return False
    if existed:
        _backup_existing(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(updated, encoding="utf-8")
    os.chmod(config_path, 0o600)
    _maybe_chown_root(config_path)
    return True


def ensure_known_hosts_file(path: str | Path = DEFAULT_KNOWN_HOSTS) -> Path:
    known_hosts = Path(path)
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    if not known_hosts.exists():
        known_hosts.write_text("", encoding="utf-8")
    os.chmod(known_hosts, 0o600)
    _maybe_chown_root(known_hosts)
    return known_hosts


def fetch_host_key(hostname: str, port: int | str) -> str:
    ssh_keyscan = _require_command("ssh-keyscan")
    result = subprocess.run(
        [ssh_keyscan, "-p", str(port), hostname],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SshCommandError(result.stderr.strip() or f"ssh-keyscan failed for {hostname}:{port}")
    return result.stdout


def host_key_fingerprints(host_key_text: str) -> str:
    ssh_keygen = _require_command("ssh-keygen")
    result = subprocess.run(
        [ssh_keygen, "-lf", "-"],
        input=host_key_text,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SshCommandError(result.stderr.strip() or "ssh-keygen fingerprint lookup failed")
    return result.stdout.strip()


def append_known_host(
    hostname: str,
    port: int | str,
    known_hosts_file: str | Path = DEFAULT_KNOWN_HOSTS,
    *,
    host_key_text: str | None = None,
) -> bool:
    known_hosts = ensure_known_hosts_file(known_hosts_file)
    host_keys = host_key_text if host_key_text is not None else fetch_host_key(hostname, port)
    existing_lines = set(known_hosts.read_text(encoding="utf-8").splitlines())
    new_lines = [line for line in host_keys.splitlines() if line and line not in existing_lines]
    if not new_lines:
        return False
    with known_hosts.open("a", encoding="utf-8") as handle:
        if known_hosts.stat().st_size > 0 and not known_hosts.read_text(encoding="utf-8").endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(new_lines) + "\n")
    os.chmod(known_hosts, 0o600)
    _maybe_chown_root(known_hosts)
    return True


def test_ssh_batch(alias: str, ssh_config_file: str | Path = DEFAULT_SSH_CONFIG) -> subprocess.CompletedProcess[str]:
    ssh = _require_command("ssh")
    return subprocess.run(
        [ssh, "-F", str(ssh_config_file), "-o", "BatchMode=yes", alias, "true"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_sftp_batch(alias: str, ssh_config_file: str | Path = DEFAULT_SSH_CONFIG) -> subprocess.CompletedProcess[str]:
    sftp = _require_command("sftp")
    return subprocess.run(
        [sftp, "-F", str(ssh_config_file), "-b", "-", alias],
        input="pwd\nls\n",
        check=False,
        capture_output=True,
        text=True,
    )
