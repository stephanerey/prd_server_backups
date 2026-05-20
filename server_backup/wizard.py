from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .config import load_global_config
from .ssh import (
    DEFAULT_KNOWN_HOSTS,
    DEFAULT_SSH_CONFIG,
    DEFAULT_SSH_DIR,
    SshCommandError,
    append_known_host,
    ensure_known_hosts_file,
    fetch_host_key,
    generate_ed25519_key,
    get_public_key,
    host_key_fingerprints,
    remove_or_replace_ssh_config_entry,
    render_ssh_config_entry as ssh_render_ssh_config_entry,
    sanitize_ssh_alias,
    test_sftp_batch,
    test_ssh_batch,
)
from .validators import validate_global_config, validate_profile_config, validate_target_config


PromptFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]

DEFAULT_BACKUP_CONF_PATH = Path("/etc/server-backup/backup.conf")
DEFAULT_RESTIC_PASSWORD_FILE = Path("/etc/server-backup/secrets/restic-password")
DEFAULT_TIMER_PATH = Path("/etc/systemd/system/server-backup.timer")
DEFAULT_CONFIG_ROOT = Path("/etc/server-backup")
DEFAULT_SECRETS_DIR = DEFAULT_CONFIG_ROOT / "secrets"
DEFAULT_TARGETS_DIR = DEFAULT_CONFIG_ROOT / "targets.d"
DEFAULT_PROFILES_DIR = DEFAULT_CONFIG_ROOT / "profiles.d"

DEFAULTS = {
    "LOCAL_DUMP_DIR": "/var/tmp/server-backup",
    "LOG_FILE": "/var/log/server-backup.log",
    "STATE_DIR": "/var/lib/server-backup/state",
    "REPORT_DIR": "/var/lib/server-backup/reports",
    "RESTIC_CACHE_DIR": "/var/cache/restic",
    "RESTIC_PASSWORD_FILE": str(DEFAULT_RESTIC_PASSWORD_FILE),
    "RETENTION_DAILY": 14,
    "RETENTION_WEEKLY": 8,
    "RETENTION_MONTHLY": 12,
    "RUN_RESTIC_CHECK": True,
    "RUN_PRUNE": True,
    "RUN_COVERAGE_AUDIT": True,
    "COVERAGE_AUDIT_FAIL_ON_FAILURE": True,
    "COVERAGE_AUDIT_FAIL_ON_WARNING": False,
    "EMAIL_REPORT_ENABLED": False,
    "EMAIL_REPORT_SUBJECT_PREFIX": "[server-backup]",
    "EMAIL_REPORT_SEND_ON_SUCCESS": True,
    "EMAIL_REPORT_SEND_ON_FAILURE": True,
    "EMAIL_REPORT_COMMAND": "sendmail",
    "TIMER_TIME": "02:30",
}

TIMER_ONCALENDAR_RE = re.compile(r"^OnCalendar=\*-\*-\* \d{2}:\d{2}:00$", re.MULTILINE)
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
TARGET_NAME_RE = re.compile(r"[^a-z0-9-]+")
PROFILE_NAME_RE = re.compile(r"[^a-z0-9-]+")

GENERIC_DEFAULT_EXCLUDES = [
    "**/.cache",
    "**/cache",
    "**/tmp",
    "**/__pycache__",
    "**/node_modules",
]

SYSTEM_FILESYSTEM_DEFAULT_PATHS = [
    "/etc",
    "/root",
    "/home",
    "/srv",
    "/opt",
    "/usr/local",
    "/var/spool/cron",
    "/var/lib/server-backup/state",
]

SYSTEM_FILESYSTEM_DEFAULT_EXCLUDES = [
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/var/tmp",
    "/mnt",
    "/media",
    "/lost+found",
    "/var/cache",
    "/var/log/*.log",
    "/var/lib/docker/overlay2",
    "/var/lib/docker/image",
    "/var/lib/docker/containers/*/*.log",
    "/etc/server-backup/secrets",
    "**/.cache",
    "**/cache",
    "**/tmp",
]

DOCKER_DEFAULT_EXCLUDES = [
    "/etc/server-backup/secrets",
    "**/.cache",
    "**/cache",
    "**/tmp",
    "**/__pycache__",
    "**/node_modules",
    "/var/lib/docker/overlay2",
    "/var/lib/docker/image",
    "/var/lib/docker/containers/*/*.log",
]

CIS_DEFAULT_EXCLUDES = [
    "**/.cache",
    "**/cache",
    "**/tmp",
    "**/__pycache__",
    "**/node_modules",
    "**/.next/cache",
    "**/logs/*.log",
]


@dataclass
class SetupResult:
    ok: bool
    config_path: str | None = None
    restic_password_path: str | None = None
    timer_enabled: bool | None = None
    messages: list[str] | None = None


@dataclass
class TargetAddResult:
    ok: bool
    target_name: str | None = None
    target_path: str | None = None
    public_key: str | None = None
    messages: list[str] | None = None


@dataclass
class ProfileAddResult:
    ok: bool
    profile_name: str | None = None
    profile_path: str | None = None
    messages: list[str] | None = None


def prompt_string(prompt: str, default: str | None = None, *, input_func: PromptFunc = input) -> str:
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        raw = input_func(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print("This value is required.")


def prompt_bool(prompt: str, default: bool, *, input_func: PromptFunc = input) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        raw = input_func(f"{prompt} [{default_label}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "true", "1"}:
            return True
        if raw in {"n", "no", "false", "0"}:
            return False
        print("Please answer yes or no.")


def prompt_int(
    prompt: str,
    default: int,
    *,
    minimum: int = 1,
    input_func: PromptFunc = input,
) -> int:
    while True:
        raw = input_func(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a valid integer.")
            continue
        if value < minimum:
            print(f"Please enter an integer greater than or equal to {minimum}.")
            continue
        return value


def prompt_choice(
    prompt: str,
    choices: list[str],
    default: str,
    *,
    input_func: PromptFunc = input,
) -> str:
    choice_map = {choice.lower(): choice for choice in choices}
    choices_display = "/".join(choices)
    while True:
        raw = input_func(f"{prompt} [{default}; choices: {choices_display}]: ").strip()
        if not raw:
            return default
        selected = choice_map.get(raw.lower())
        if selected is not None:
            return selected
        print(f"Please choose one of: {choices_display}.")


def confirm_overwrite(path: Path, *, input_func: PromptFunc = input) -> bool:
    return prompt_bool(f"{path} already exists. Overwrite it?", False, input_func=input_func)


def generate_restic_password(length: int = 48) -> str:
    if length < 32:
        length = 32
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def write_file_secure(
    path: str | Path,
    content: str,
    *,
    mode: int = 0o600,
    backup_existing: bool = False,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if backup_existing and target.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_path = target.with_name(f"{target.name}.bak-{timestamp}")
        shutil.copy2(target, backup_path)

    target.write_text(content, encoding="utf-8")
    os.chmod(target, mode)

    if owner_uid is not None and owner_gid is not None:
        os.chown(target, owner_uid, owner_gid)

    return target


def write_target_file_secure(path: str | Path, content: str, *, backup_existing: bool = False) -> Path:
    return write_file_secure(
        path,
        content,
        mode=0o600,
        backup_existing=backup_existing,
        owner_uid=0,
        owner_gid=0,
    )


def _shell_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _timestamp(generated_at: str | None = None) -> str:
    return generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_backup_conf(config: dict[str, object], *, generated_at: str | None = None) -> str:
    timestamp = _timestamp(generated_at)
    lines = [
        'CONFIG_VERSION="1"',
        'GENERATED_BY="server-backup"',
        f'GENERATED_AT={_shell_quote(timestamp)}',
        "",
        f'BACKUP_NAME={_shell_quote(str(config["BACKUP_NAME"]))}',
        f'BACKUP_TAGS={_shell_quote(str(config["BACKUP_TAGS"]))}',
        "",
        f'RETENTION_DAILY={int(config["RETENTION_DAILY"])}',
        f'RETENTION_WEEKLY={int(config["RETENTION_WEEKLY"])}',
        f'RETENTION_MONTHLY={int(config["RETENTION_MONTHLY"])}',
        "",
        f'LOCAL_DUMP_DIR={_shell_quote(str(config["LOCAL_DUMP_DIR"]))}',
        f'LOG_FILE={_shell_quote(str(config["LOG_FILE"]))}',
        f'STATE_DIR={_shell_quote(str(config["STATE_DIR"]))}',
        f'REPORT_DIR={_shell_quote(str(config["REPORT_DIR"]))}',
        "",
        f'RESTIC_CACHE_DIR={_shell_quote(str(config["RESTIC_CACHE_DIR"]))}',
        f'RESTIC_PASSWORD_FILE={_shell_quote(str(config["RESTIC_PASSWORD_FILE"]))}',
        "",
        f'RUN_RESTIC_CHECK={_shell_quote(_bool_string(bool(config["RUN_RESTIC_CHECK"])))}',
        f'RUN_PRUNE={_shell_quote(_bool_string(bool(config["RUN_PRUNE"])))}',
        f'RUN_COVERAGE_AUDIT={_shell_quote(_bool_string(bool(config["RUN_COVERAGE_AUDIT"])))}',
        f'COVERAGE_AUDIT_FAIL_ON_FAILURE={_shell_quote(_bool_string(bool(config["COVERAGE_AUDIT_FAIL_ON_FAILURE"])))}',
        f'COVERAGE_AUDIT_FAIL_ON_WARNING={_shell_quote(_bool_string(bool(config["COVERAGE_AUDIT_FAIL_ON_WARNING"])))}',
        "",
        f'EMAIL_REPORT_ENABLED={_shell_quote(_bool_string(bool(config["EMAIL_REPORT_ENABLED"])))}',
        f'EMAIL_REPORT_TO={_shell_quote(str(config["EMAIL_REPORT_TO"]))}',
        f'EMAIL_REPORT_FROM={_shell_quote(str(config["EMAIL_REPORT_FROM"]))}',
        f'EMAIL_REPORT_SUBJECT_PREFIX={_shell_quote(str(config["EMAIL_REPORT_SUBJECT_PREFIX"]))}',
        f'EMAIL_REPORT_SEND_ON_SUCCESS={_shell_quote(_bool_string(bool(config["EMAIL_REPORT_SEND_ON_SUCCESS"])))}',
        f'EMAIL_REPORT_SEND_ON_FAILURE={_shell_quote(_bool_string(bool(config["EMAIL_REPORT_SEND_ON_FAILURE"])))}',
        f'EMAIL_REPORT_COMMAND={_shell_quote(str(config["EMAIL_REPORT_COMMAND"]))}',
        "",
    ]
    return "\n".join(lines)


def sanitize_target_name(name: str) -> str:
    cleaned = TARGET_NAME_RE.sub("-", name.strip().lower())
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = "target"
    return cleaned


def prompt_target_name(*, input_func: PromptFunc = input, print_func: PrintFunc = print) -> str:
    raw = prompt_string("Target name", None, input_func=input_func)
    sanitized = sanitize_target_name(raw)
    if sanitized != raw.strip():
        print_func(f"Target name will be saved as: {sanitized}")
    return sanitized


def render_target_env(config: dict[str, object], *, generated_at: str | None = None) -> str:
    timestamp = _timestamp(generated_at)
    lines = [
        'CONFIG_VERSION="1"',
        'GENERATED_BY="server-backup"',
        f'GENERATED_AT={_shell_quote(timestamp)}',
        "",
        f'TARGET_NAME={_shell_quote(str(config["TARGET_NAME"]))}',
        f'TARGET_TYPE={_shell_quote(str(config["TARGET_TYPE"]))}',
        "",
        f'SSH_HOST_ALIAS={_shell_quote(str(config["SSH_HOST_ALIAS"]))}',
        f'SSH_HOSTNAME={_shell_quote(str(config["SSH_HOSTNAME"]))}',
        f'SSH_PORT={_shell_quote(str(config["SSH_PORT"]))}',
        f'SSH_USER={_shell_quote(str(config["SSH_USER"]))}',
        f'SSH_IDENTITY_FILE={_shell_quote(str(config["SSH_IDENTITY_FILE"]))}',
        f'SSH_CONFIG_FILE={_shell_quote(str(config["SSH_CONFIG_FILE"]))}',
        f'SSH_KNOWN_HOSTS_FILE={_shell_quote(str(config["SSH_KNOWN_HOSTS_FILE"]))}',
        "",
        f'RESTIC_REPOSITORY={_shell_quote(str(config["RESTIC_REPOSITORY"]))}',
        f'RESTIC_PASSWORD_FILE={_shell_quote(str(config["RESTIC_PASSWORD_FILE"]))}',
        f'RESTIC_CACHE_DIR={_shell_quote(str(config["RESTIC_CACHE_DIR"]))}',
        "",
    ]
    return "\n".join(lines)


def render_ssh_config_entry(
    alias: str,
    hostname: str,
    port: int | str,
    user: str,
    identity_file: str | Path,
    known_hosts_file: str | Path,
) -> str:
    return ssh_render_ssh_config_entry(alias, hostname, port, user, identity_file, known_hosts_file)


def _validate_time_string(value: str) -> str:
    if not TIME_RE.fullmatch(value):
        raise ValueError("Time must use HH:MM format.")
    hours, minutes = value.split(":", 1)
    if int(hours) > 23 or int(minutes) > 59:
        raise ValueError("Time must use a valid 24-hour HH:MM value.")
    return value


def _prompt_time(default: str, *, input_func: PromptFunc = input) -> str:
    while True:
        value = prompt_string("Daily timer time (HH:MM)", default, input_func=input_func)
        try:
            return _validate_time_string(value)
        except ValueError as exc:
            print(str(exc))


def _update_timer_schedule(timer_path: Path, hhmm: str) -> None:
    if not timer_path.exists():
        raise FileNotFoundError(f"Timer file not found: {timer_path}. Run sudo ./scripts/install.sh first.")

    timer_text = timer_path.read_text(encoding="utf-8")
    replacement = f"OnCalendar=*-*-* {hhmm}:00"
    if TIMER_ONCALENDAR_RE.search(timer_text):
        updated = TIMER_ONCALENDAR_RE.sub(replacement, timer_text, count=1)
    else:
        raise ValueError(f"Could not find OnCalendar line in {timer_path}")
    timer_path.write_text(updated, encoding="utf-8")


def _run_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _ensure_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("This command must be run as root.")


def _require_installed_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}. Run sudo ./scripts/install.sh first.")


def _backup_existing_file(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    shutil.copy2(path, backup_path)


def _derive_public_key_from_private(private_key_path: Path) -> str:
    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise RuntimeError("Required command not found: ssh-keygen")
    result = subprocess.run(
        [ssh_keygen, "-y", "-f", str(private_key_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or f"Could not derive public key from {private_key_path}")
    return result.stdout.strip()


def read_public_key(public_key_path: str | Path) -> str:
    return get_public_key(public_key_path)


def generate_ssh_key(
    private_key_path: str | Path,
    comment: str,
    *,
    input_func: PromptFunc = input,
) -> tuple[Path, str]:
    private_path = Path(private_key_path)
    public_path = private_path.with_name(f"{private_path.name}.pub")

    if private_path.exists():
        reuse_existing = prompt_bool(f"Reuse existing SSH key {private_path}", True, input_func=input_func)
        if reuse_existing:
            if public_path.exists():
                return private_path, read_public_key(public_path)
            return private_path, _derive_public_key_from_private(private_path)

        if not confirm_overwrite(private_path, input_func=input_func):
            raise RuntimeError("Existing SSH key left unchanged.")
        _backup_existing_file(private_path)
        _backup_existing_file(public_path)

    generated_private, generated_public = generate_ed25519_key(private_path, comment)
    return generated_private, read_public_key(generated_public)


def ensure_known_host(
    hostname: str,
    port: int,
    known_hosts_file: str | Path,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> bool:
    ensure_known_hosts_file(known_hosts_file)

    try:
        host_key_text = fetch_host_key(hostname, port)
    except SshCommandError as exc:
        print_func(f"Could not fetch the host key for {hostname}:{port}: {exc}")
        print_func("StrictHostKeyChecking remains enabled. Add the host key manually before using this target.")
        return False

    print_func("")
    print_func(f"Fetched host key for {hostname}:{port}.")
    try:
        fingerprints = host_key_fingerprints(host_key_text)
    except SshCommandError as exc:
        print_func(f"Could not compute host-key fingerprint: {exc}")
    else:
        print_func("Host-key fingerprint(s):")
        for line in fingerprints.splitlines():
            print_func(f"  {line}")

    if not prompt_bool("Add this host key to /etc/server-backup/ssh/known_hosts", True, input_func=input_func):
        print_func("Host key not added. SFTP tests will require a manual known_hosts entry.")
        return False

    added = append_known_host(hostname, port, known_hosts_file, host_key_text=host_key_text)
    if added:
        print_func(f"Host key added to {known_hosts_file}.")
    else:
        print_func(f"Host key already present in {known_hosts_file}.")
    return True


def test_sftp_connection(
    alias: str,
    ssh_config_file: str | Path,
    *,
    print_func: PrintFunc = print,
) -> bool:
    try:
        ssh_result = test_ssh_batch(alias, ssh_config_file)
        sftp_result = test_sftp_batch(alias, ssh_config_file)
    except SshCommandError as exc:
        print_func(f"SSH/SFTP command error: {exc}")
        return False

    if ssh_result.returncode == 0:
        print_func(f"SSH batch test: OK for {alias}")
    else:
        detail = (ssh_result.stderr or ssh_result.stdout).strip() or "command rejected"
        print_func(f"SSH batch test: WARNING for {alias} ({detail})")
        print_func("This can be acceptable when the NAS only allows internal-sftp.")

    if sftp_result.returncode == 0:
        print_func(f"SFTP batch test: OK for {alias}")
        output = (sftp_result.stdout or "").strip()
        if output:
            for line in output.splitlines():
                print_func(f"  {line}")
        return True

    detail = (sftp_result.stderr or sftp_result.stdout).strip() or "SFTP connection failed"
    print_func(f"SFTP batch test: ERROR for {alias}")
    print_func(f"  {detail}")
    return False


def _global_target_defaults(global_config: dict[str, object]) -> tuple[str, str]:
    restic_password_file = str(global_config.get("RESTIC_PASSWORD_FILE", DEFAULTS["RESTIC_PASSWORD_FILE"]))
    restic_cache_dir = str(global_config.get("RESTIC_CACHE_DIR", DEFAULTS["RESTIC_CACHE_DIR"]))
    if not restic_password_file:
        restic_password_file = str(DEFAULTS["RESTIC_PASSWORD_FILE"])
    if not restic_cache_dir:
        restic_cache_dir = str(DEFAULTS["RESTIC_CACHE_DIR"])
    return restic_password_file, restic_cache_dir


def prompt_sftp_target(
    *,
    global_config: dict[str, object] | None = None,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    effective_global = global_config or {}
    target_name = prompt_target_name(input_func=input_func, print_func=print_func)
    target_type = prompt_choice("Target type", ["sftp"], "sftp", input_func=input_func)
    hostname = prompt_string("SFTP hostname or IP", None, input_func=input_func)
    ssh_port = prompt_int("SSH port", 22, minimum=1, input_func=input_func)
    if ssh_port > 65535:
        raise ValueError("SSH port must be between 1 and 65535.")
    ssh_user = prompt_string("Remote SSH user", None, input_func=input_func)

    backup_name = str(effective_global.get("BACKUP_NAME", target_name)).strip() or target_name
    default_remote_path = f"/backups/{backup_name}/restic"
    remote_path = prompt_string("Remote restic repository path", default_remote_path, input_func=input_func)

    generate_new_key = prompt_bool("Generate a dedicated SSH key for this target", True, input_func=input_func)
    default_private_key = DEFAULT_SSH_DIR / f"id_ed25519_{target_name}"
    identity_file = default_private_key
    if not generate_new_key:
        while True:
            candidate = Path(
                prompt_string("Existing SSH private key path", str(default_private_key), input_func=input_func)
            )
            if candidate.exists():
                identity_file = candidate
                break
            print_func(f"SSH private key not found: {candidate}")

    fetch_host_key_now = prompt_bool(
        "Fetch and record the NAS host key with ssh-keyscan", True, input_func=input_func
    )
    test_connection_now = prompt_bool("Test the SFTP connection now", True, input_func=input_func)

    ssh_alias = sanitize_ssh_alias(f"server-backup-{target_name}")
    restic_password_file, restic_cache_dir = _global_target_defaults(effective_global)

    return {
        "TARGET_NAME": target_name,
        "TARGET_TYPE": target_type,
        "SSH_HOST_ALIAS": ssh_alias,
        "SSH_HOSTNAME": hostname,
        "SSH_PORT": str(ssh_port),
        "SSH_USER": ssh_user,
        "SSH_IDENTITY_FILE": str(identity_file),
        "SSH_CONFIG_FILE": str(DEFAULT_SSH_CONFIG),
        "SSH_KNOWN_HOSTS_FILE": str(DEFAULT_KNOWN_HOSTS),
        "RESTIC_REPOSITORY": f"sftp:{ssh_alias}:{remote_path}",
        "RESTIC_PASSWORD_FILE": restic_password_file,
        "RESTIC_CACHE_DIR": restic_cache_dir,
        "__generate_ssh_key__": generate_new_key,
        "__fetch_host_key__": fetch_host_key_now,
        "__test_connection__": test_connection_now,
    }


def run_global_setup(
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
    backup_conf_path: Path = DEFAULT_BACKUP_CONF_PATH,
    restic_password_file: Path = DEFAULT_RESTIC_PASSWORD_FILE,
    timer_path: Path = DEFAULT_TIMER_PATH,
) -> SetupResult:
    _ensure_root()

    if not timer_path.exists():
        raise FileNotFoundError(f"Timer file not found: {timer_path}. Run sudo ./scripts/install.sh first.")

    hostname = socket.gethostname()
    print_func("server-backup setup")
    print_func("")

    backup_name = prompt_string("Backup name", hostname, input_func=input_func)
    backup_tags = prompt_string("Backup tags", hostname, input_func=input_func)
    retention_daily = prompt_int("Retention daily", int(DEFAULTS["RETENTION_DAILY"]), input_func=input_func)
    retention_weekly = prompt_int("Retention weekly", int(DEFAULTS["RETENTION_WEEKLY"]), input_func=input_func)
    retention_monthly = prompt_int("Retention monthly", int(DEFAULTS["RETENTION_MONTHLY"]), input_func=input_func)
    timer_time = _prompt_time(str(DEFAULTS["TIMER_TIME"]), input_func=input_func)

    run_restic_check = prompt_bool("Enable restic check", bool(DEFAULTS["RUN_RESTIC_CHECK"]), input_func=input_func)
    run_prune = prompt_bool("Enable prune", bool(DEFAULTS["RUN_PRUNE"]), input_func=input_func)
    run_coverage_audit = prompt_bool(
        "Enable coverage audit", bool(DEFAULTS["RUN_COVERAGE_AUDIT"]), input_func=input_func
    )
    coverage_fail_on_failure = prompt_bool(
        "Coverage audit fails on failures",
        bool(DEFAULTS["COVERAGE_AUDIT_FAIL_ON_FAILURE"]),
        input_func=input_func,
    )
    coverage_fail_on_warning = prompt_bool(
        "Coverage audit fails on warnings",
        bool(DEFAULTS["COVERAGE_AUDIT_FAIL_ON_WARNING"]),
        input_func=input_func,
    )

    email_enabled = prompt_bool("Enable email reports", bool(DEFAULTS["EMAIL_REPORT_ENABLED"]), input_func=input_func)
    email_to = ""
    email_from = ""
    email_subject_prefix = str(DEFAULTS["EMAIL_REPORT_SUBJECT_PREFIX"])
    email_send_on_success = bool(DEFAULTS["EMAIL_REPORT_SEND_ON_SUCCESS"])
    email_send_on_failure = bool(DEFAULTS["EMAIL_REPORT_SEND_ON_FAILURE"])
    email_command = str(DEFAULTS["EMAIL_REPORT_COMMAND"])
    if email_enabled:
        email_to = prompt_string("Email report recipient", "", input_func=input_func)
        email_from = prompt_string("Email report sender", "", input_func=input_func)
        email_subject_prefix = prompt_string(
            "Email report subject prefix",
            str(DEFAULTS["EMAIL_REPORT_SUBJECT_PREFIX"]),
            input_func=input_func,
        )
        email_send_on_success = prompt_bool(
            "Send email on success",
            bool(DEFAULTS["EMAIL_REPORT_SEND_ON_SUCCESS"]),
            input_func=input_func,
        )
        email_send_on_failure = prompt_bool(
            "Send email on failure",
            bool(DEFAULTS["EMAIL_REPORT_SEND_ON_FAILURE"]),
            input_func=input_func,
        )
        email_command = prompt_choice(
            "Email command",
            ["sendmail", "mail"],
            str(DEFAULTS["EMAIL_REPORT_COMMAND"]),
            input_func=input_func,
        )

    configured_restic_password_file = Path(
        prompt_string("Restic password file", str(restic_password_file), input_func=input_func)
    )
    generate_password_now = prompt_bool("Generate restic password now", True, input_func=input_func)

    config_payload: dict[str, object] = {
        "BACKUP_NAME": backup_name,
        "BACKUP_TAGS": backup_tags,
        "RETENTION_DAILY": retention_daily,
        "RETENTION_WEEKLY": retention_weekly,
        "RETENTION_MONTHLY": retention_monthly,
        "LOCAL_DUMP_DIR": DEFAULTS["LOCAL_DUMP_DIR"],
        "LOG_FILE": DEFAULTS["LOG_FILE"],
        "STATE_DIR": DEFAULTS["STATE_DIR"],
        "REPORT_DIR": DEFAULTS["REPORT_DIR"],
        "RESTIC_CACHE_DIR": DEFAULTS["RESTIC_CACHE_DIR"],
        "RESTIC_PASSWORD_FILE": str(configured_restic_password_file),
        "RUN_RESTIC_CHECK": run_restic_check,
        "RUN_PRUNE": run_prune,
        "RUN_COVERAGE_AUDIT": run_coverage_audit,
        "COVERAGE_AUDIT_FAIL_ON_FAILURE": coverage_fail_on_failure,
        "COVERAGE_AUDIT_FAIL_ON_WARNING": coverage_fail_on_warning,
        "EMAIL_REPORT_ENABLED": email_enabled,
        "EMAIL_REPORT_TO": email_to,
        "EMAIL_REPORT_FROM": email_from,
        "EMAIL_REPORT_SUBJECT_PREFIX": email_subject_prefix,
        "EMAIL_REPORT_SEND_ON_SUCCESS": email_send_on_success,
        "EMAIL_REPORT_SEND_ON_FAILURE": email_send_on_failure,
        "EMAIL_REPORT_COMMAND": email_command,
    }

    backup_existing_config = False
    if backup_conf_path.exists():
        if not confirm_overwrite(backup_conf_path, input_func=input_func):
            print_func("Existing backup.conf left unchanged.")
            return SetupResult(ok=False, config_path=str(backup_conf_path), messages=["backup.conf not overwritten"])
        backup_existing_config = True

    password_path_created: str | None = None
    if generate_password_now:
        DEFAULT_SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        backup_existing_password = False
        if configured_restic_password_file.exists():
            if not confirm_overwrite(configured_restic_password_file, input_func=input_func):
                print_func("Existing restic password file left unchanged.")
            else:
                backup_existing_password = True
                generated_password = generate_restic_password()
                write_file_secure(
                    configured_restic_password_file,
                    generated_password + "\n",
                    mode=0o600,
                    backup_existing=backup_existing_password,
                    owner_uid=0,
                    owner_gid=0,
                )
                password_path_created = str(configured_restic_password_file)
        else:
            generated_password = generate_restic_password()
            write_file_secure(
                configured_restic_password_file,
                generated_password + "\n",
                mode=0o600,
                backup_existing=False,
                owner_uid=0,
                owner_gid=0,
            )
            password_path_created = str(configured_restic_password_file)
        print_func("Restic password file handled without printing the secret.")
        print_func("Store the restic password outside this server in the restore kit.")
    else:
        print_func(
            f"Restic password file was not generated. Create {configured_restic_password_file} before repository initialization."
        )

    rendered = render_backup_conf(config_payload)
    write_file_secure(
        backup_conf_path,
        rendered,
        mode=0o600,
        backup_existing=backup_existing_config,
        owner_uid=0,
        owner_gid=0,
    )

    _update_timer_schedule(timer_path, timer_time)
    daemon_reload = _run_systemctl("daemon-reload")
    if daemon_reload.returncode != 0:
        raise RuntimeError(daemon_reload.stderr.strip() or "systemctl daemon-reload failed")

    enable_timer_now = prompt_bool("Enable and start the timer now", False, input_func=input_func)
    timer_enabled = False
    if enable_timer_now:
        enable_result = _run_systemctl("enable", "--now", "server-backup.timer")
        if enable_result.returncode != 0:
            raise RuntimeError(enable_result.stderr.strip() or "systemctl enable --now server-backup.timer failed")
        timer_enabled = True
    else:
        print_func("Timer not enabled automatically.")
        print_func("Enable it later with: sudo systemctl enable --now server-backup.timer")

    loaded = load_global_config(backup_conf_path)
    validation = validate_global_config(loaded)
    print_func("")
    print_func("Validation summary:")
    if validation.errors:
        for error in validation.errors:
            print_func(f"  error: {error}")
    if validation.warnings:
        for warning in validation.warnings:
            print_func(f"  warning: {warning}")
    if not validation.errors and not validation.warnings:
        print_func("  global configuration looks valid")

    print_func("")
    print_func("Prochaine étape :")
    print_func("  sudo server-backup target add")

    messages = []
    if validation.errors:
        messages.extend(validation.errors)
    if validation.warnings:
        messages.extend(validation.warnings)

    return SetupResult(
        ok=not validation.errors,
        config_path=str(backup_conf_path),
        restic_password_path=password_path_created,
        timer_enabled=timer_enabled,
        messages=messages,
    )


def run_target_add(
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
    backup_conf_path: Path = DEFAULT_BACKUP_CONF_PATH,
    targets_dir: Path = DEFAULT_TARGETS_DIR,
    ssh_dir: Path = DEFAULT_SSH_DIR,
    ssh_config_file: Path = DEFAULT_SSH_CONFIG,
    known_hosts_file: Path = DEFAULT_KNOWN_HOSTS,
) -> TargetAddResult:
    _ensure_root()
    _require_installed_path(DEFAULT_CONFIG_ROOT, "Configuration root")
    _require_installed_path(targets_dir, "Targets directory")
    _require_installed_path(ssh_dir, "SSH directory")

    global_config = load_global_config(backup_conf_path)

    print_func("server-backup target add")
    print_func("")
    target_payload = prompt_sftp_target(global_config=global_config, input_func=input_func, print_func=print_func)

    target_name = str(target_payload["TARGET_NAME"])
    target_path = targets_dir / f"{target_name}.env"
    backup_existing_target = False
    if target_path.exists():
        if not confirm_overwrite(target_path, input_func=input_func):
            print_func("Existing target file left unchanged.")
            return TargetAddResult(ok=False, target_name=target_name, target_path=str(target_path))
        backup_existing_target = True

    target_payload["SSH_CONFIG_FILE"] = str(ssh_config_file)
    target_payload["SSH_KNOWN_HOSTS_FILE"] = str(known_hosts_file)

    identity_file = Path(str(target_payload["SSH_IDENTITY_FILE"]))
    public_key: str
    if bool(target_payload.pop("__generate_ssh_key__", False)):
        identity_file, public_key = generate_ssh_key(
            identity_file,
            f"server-backup:{target_name}",
            input_func=input_func,
        )
        target_payload["SSH_IDENTITY_FILE"] = str(identity_file)
    else:
        if not identity_file.exists():
            raise FileNotFoundError(f"SSH private key not found: {identity_file}")
        public_path = identity_file.with_name(f"{identity_file.name}.pub")
        public_key = read_public_key(public_path) if public_path.exists() else _derive_public_key_from_private(identity_file)

    ssh_entry = render_ssh_config_entry(
        str(target_payload["SSH_HOST_ALIAS"]),
        str(target_payload["SSH_HOSTNAME"]),
        str(target_payload["SSH_PORT"]),
        str(target_payload["SSH_USER"]),
        str(target_payload["SSH_IDENTITY_FILE"]),
        str(known_hosts_file),
    )
    replaced = remove_or_replace_ssh_config_entry(
        str(target_payload["SSH_HOST_ALIAS"]),
        ssh_entry,
        lambda path: confirm_overwrite(path, input_func=input_func),
        ssh_config_file=ssh_config_file,
    )
    if not replaced:
        print_func("Existing SSH config left unchanged.")
        return TargetAddResult(ok=False, target_name=target_name, target_path=str(target_path))

    ensure_known_hosts_file(known_hosts_file)
    if bool(target_payload.pop("__fetch_host_key__", False)):
        ensure_known_host(
            str(target_payload["SSH_HOSTNAME"]),
            int(str(target_payload["SSH_PORT"])),
            known_hosts_file,
            input_func=input_func,
            print_func=print_func,
        )

    rendered_target = render_target_env(target_payload)
    write_target_file_secure(target_path, rendered_target, backup_existing=backup_existing_target)

    print_func("")
    print_func("Copier cette clé publique dans le fichier authorized_keys de l'utilisateur distant :")
    print_func(public_key)
    print_func("")
    print_func("Recommandé côté NAS :")
    print_func(
        'from="<IP_PUBLIQUE_SERVEUR>",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty '
        f"{public_key}"
    )

    test_requested = bool(target_payload.pop("__test_connection__", False))
    if test_requested:
        print_func("")
        print_func("Testing SFTP connectivity...")
        test_sftp_connection(str(target_payload["SSH_HOST_ALIAS"]), ssh_config_file, print_func=print_func)

    validation_target = {
        "__file__": str(target_path),
        "__kind__": "target",
        "__parse_warnings__": [],
        "CONFIG_VERSION": "1",
        **target_payload,
    }
    validation = validate_target_config(validation_target)
    print_func("")
    print_func("Validation summary:")
    if validation.errors:
        for error in validation.errors:
            print_func(f"  error: {error}")
    if validation.warnings:
        for warning in validation.warnings:
            print_func(f"  warning: {warning}")
    if not validation.errors and not validation.warnings:
        print_func("  target configuration looks valid")

    print_func("")
    print_func("Next step:")
    print_func(f"  sudo server-backup target test {target_name}")

    messages = [*validation.errors, *validation.warnings]
    return TargetAddResult(
        ok=not validation.errors,
        target_name=target_name,
        target_path=str(target_path),
        public_key=public_key,
        messages=messages,
    )


def write_profile_file_secure(path: str | Path, content: str, *, backup_existing: bool = False) -> Path:
    return write_file_secure(
        path,
        content,
        mode=0o600,
        backup_existing=backup_existing,
        owner_uid=0,
        owner_gid=0,
    )


def sanitize_profile_name(name: str) -> str:
    cleaned = PROFILE_NAME_RE.sub("-", name.strip().lower())
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = "profile"
    return cleaned


def prompt_profile_name(*, input_func: PromptFunc = input, print_func: PrintFunc = print) -> str:
    raw = prompt_string("Profile name", None, input_func=input_func)
    sanitized = sanitize_profile_name(raw)
    if sanitized != raw.strip():
        print_func(f"Profile name will be saved as: {sanitized}")
    return sanitized


def prompt_profile_type(*, input_func: PromptFunc = input) -> str:
    return prompt_choice(
        "Profile type",
        ["generic", "system-filesystem", "docker-host", "docker-app", "cis-site"],
        "generic",
        input_func=input_func,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _warn_if_path_missing(path_value: str, *, print_func: PrintFunc = print) -> None:
    try:
        exists = Path(path_value).exists()
    except PermissionError:
        exists = True
    if not exists:
        print_func(f"Warning: path does not exist yet: {path_value}")


def _prompt_many(
    heading: str,
    entry_prompt: str,
    *,
    defaults: list[str] | None = None,
    allow_empty: bool = False,
    check_paths: bool = False,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> list[str]:
    values: list[str] = []
    suggested = _dedupe(list(defaults or []))

    if suggested:
        print_func(f"{heading} suggestions:")
        for item in suggested:
            print_func(f"  - {item}")
        if prompt_bool(f"Use suggested {heading.lower()}", True, input_func=input_func):
            values.extend(suggested)

    print_func(f"Add {heading.lower()} one per line. Leave blank to finish.")
    while True:
        raw = input_func(f"{entry_prompt}: ").strip()
        if not raw:
            if values or allow_empty:
                break
            print_func(f"At least one {heading.lower()} entry is required.")
            continue
        values.append(raw)
        if check_paths:
            _warn_if_path_missing(raw, print_func=print_func)

    return _dedupe(values)


def prompt_backup_paths(
    *,
    defaults: list[str] | None = None,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> list[str]:
    paths = _prompt_many(
        "Backup paths",
        "Backup path",
        defaults=defaults,
        allow_empty=False,
        check_paths=True,
        input_func=input_func,
        print_func=print_func,
    )
    for path_value in paths:
        _warn_if_path_missing(path_value, print_func=print_func)
    return paths


def prompt_excludes(
    *,
    defaults: list[str] | None = None,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> list[str]:
    return _prompt_many(
        "Exclude patterns",
        "Exclude pattern",
        defaults=defaults,
        allow_empty=True,
        check_paths=False,
        input_func=input_func,
        print_func=print_func,
    )


def _prompt_missing_path_behavior(*, input_func: PromptFunc = input) -> str:
    return prompt_choice(
        "Missing-path behavior",
        ["warning", "ignore", "fail-later"],
        "warning",
        input_func=input_func,
    )


def _render_array(name: str, values: list[str]) -> list[str]:
    lines = [f"{name}=("]
    for value in values:
        lines.append(f"  {_shell_quote(value)}")
    lines.append(")")
    return lines


def render_profile_conf(config: dict[str, object], *, generated_at: str | None = None) -> str:
    timestamp = _timestamp(generated_at)
    lines = [
        'CONFIG_VERSION="1"',
        'GENERATED_BY="server-backup"',
        f'GENERATED_AT={_shell_quote(timestamp)}',
        "",
        f'PROFILE_NAME={_shell_quote(str(config["PROFILE_NAME"]))}',
        f'PROFILE_TYPE={_shell_quote(str(config["PROFILE_TYPE"]))}',
    ]

    for optional_field in (
        "APP_KIND",
        "DOCKER_INVENTORY",
        "WEB_CONTENT_CRITICAL",
        "MISSING_PATH_BEHAVIOR",
    ):
        value = config.get(optional_field)
        if value not in (None, ""):
            lines.append(f"{optional_field}={_shell_quote(str(value))}")

    lines.append("")
    lines.extend(_render_array("BACKUP_PATHS", [str(item) for item in config.get("BACKUP_PATHS", [])]))
    lines.append("")
    lines.extend(_render_array("EXCLUDES", [str(item) for item in config.get("EXCLUDES", [])]))

    for optional_array in ("CONTENT_CLASSIFICATION", "DATABASE_DUMPS"):
        values = config.get(optional_array)
        if isinstance(values, list):
            lines.append("")
            lines.extend(_render_array(optional_array, [str(item) for item in values]))

    comments = config.get("__comments__")
    if isinstance(comments, list) and comments:
        lines.append("")
        lines.extend(str(item) for item in comments)

    lines.append("")
    return "\n".join(lines)


def find_compose_files(path: str | Path) -> list[Path]:
    candidate = Path(path)
    compose_names = (
        "compose.yml",
        "compose.yaml",
        "docker-compose.yml",
        "docker-compose.yaml",
        "docker-compose.override.yml",
    )

    if candidate.is_file():
        return [candidate] if candidate.name in compose_names else []
    if not candidate.exists() or not candidate.is_dir():
        return []
    return [candidate / name for name in compose_names if (candidate / name).is_file()]


def _choose_compose_file(
    base_path: Path,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> str:
    found = find_compose_files(base_path)
    default_value = str(found[0]) if found else str(base_path / "docker-compose.yml")
    if found:
        print_func("Detected compose files:")
        for item in found:
            print_func(f"  - {item}")
    compose_file = prompt_string("Compose file path", default_value, input_func=input_func)
    _warn_if_path_missing(compose_file, print_func=print_func)
    return compose_file


def _detect_docker_summary(*, print_func: PrintFunc = print) -> None:
    docker = shutil.which("docker")
    if not docker:
        print_func("Warning: docker command not found. Continue with manual path entry.")
        return

    commands = [
        ("Running containers", [docker, "ps", "--format", "{{.Names}}"]),
        ("Docker volumes", [docker, "volume", "ls", "--format", "{{.Name}}"]),
    ]
    for label, command in commands:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "not accessible"
            print_func(f"Warning: could not inspect Docker for {label.lower()}: {detail}")
            continue
        items = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not items:
            print_func(f"{label}: none detected")
            continue
        print_func(f"{label}:")
        for item in items[:10]:
            print_func(f"  - {item}")
        if len(items) > 10:
            print_func(f"  ... and {len(items) - 10} more")


def prompt_profile_generic(
    profile_name: str,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    backup_paths = prompt_backup_paths(input_func=input_func, print_func=print_func)
    excludes = prompt_excludes(defaults=GENERIC_DEFAULT_EXCLUDES, input_func=input_func, print_func=print_func)
    return {
        "PROFILE_NAME": profile_name,
        "PROFILE_TYPE": "generic",
        "MISSING_PATH_BEHAVIOR": _prompt_missing_path_behavior(input_func=input_func),
        "BACKUP_PATHS": backup_paths,
        "EXCLUDES": excludes,
    }


def prompt_profile_system_filesystem(
    profile_name: str,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    print_func("system-filesystem is a broad filesystem backup profile. It does not replace logical DB dumps.")
    backup_paths = prompt_backup_paths(
        defaults=SYSTEM_FILESYSTEM_DEFAULT_PATHS,
        input_func=input_func,
        print_func=print_func,
    )
    excludes = prompt_excludes(
        defaults=SYSTEM_FILESYSTEM_DEFAULT_EXCLUDES,
        input_func=input_func,
        print_func=print_func,
    )
    return {
        "PROFILE_NAME": profile_name,
        "PROFILE_TYPE": "system-filesystem",
        "MISSING_PATH_BEHAVIOR": _prompt_missing_path_behavior(input_func=input_func),
        "BACKUP_PATHS": backup_paths,
        "EXCLUDES": excludes,
    }


def prompt_profile_docker_host(
    profile_name: str,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    default_paths: list[str] = []
    if prompt_bool("Scan standard Docker-host paths (/srv, /opt, /home)", True, input_func=input_func):
        for candidate in ("/srv", "/opt", "/home"):
            if Path(candidate).exists():
                default_paths.append(candidate)
            else:
                print_func(f"Warning: standard path not present: {candidate}")

    if prompt_bool("Include /etc", True, input_func=input_func):
        default_paths.append("/etc")
    if prompt_bool("Include /var/lib/server-backup/state", True, input_func=input_func):
        default_paths.append("/var/lib/server-backup/state")

    _detect_docker_summary(print_func=print_func)

    volume_paths = _prompt_many(
        "Docker volume paths",
        "Docker volume path",
        allow_empty=True,
        check_paths=True,
        input_func=input_func,
        print_func=print_func,
    )
    bind_mount_paths = _prompt_many(
        "Docker bind-mount paths",
        "Docker bind-mount path",
        allow_empty=True,
        check_paths=True,
        input_func=input_func,
        print_func=print_func,
    )
    backup_paths = prompt_backup_paths(
        defaults=default_paths + volume_paths + bind_mount_paths,
        input_func=input_func,
        print_func=print_func,
    )
    excludes = prompt_excludes(defaults=DOCKER_DEFAULT_EXCLUDES, input_func=input_func, print_func=print_func)
    docker_inventory = prompt_bool("Enable DOCKER_INVENTORY", True, input_func=input_func)

    return {
        "PROFILE_NAME": profile_name,
        "PROFILE_TYPE": "docker-host",
        "DOCKER_INVENTORY": _bool_string(docker_inventory),
        "MISSING_PATH_BEHAVIOR": _prompt_missing_path_behavior(input_func=input_func),
        "BACKUP_PATHS": backup_paths,
        "EXCLUDES": excludes,
    }


def prompt_profile_docker_app(
    profile_name: str,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    print_func(f"Using profile name '{profile_name}' as the logical Docker application name.")
    project_path = Path(prompt_string("Compose project path", f"/srv/{profile_name}", input_func=input_func))
    _warn_if_path_missing(str(project_path), print_func=print_func)
    compose_file = _choose_compose_file(project_path, input_func=input_func, print_func=print_func)
    include_env = prompt_bool("Include .env file", True, input_func=input_func)
    volume_paths = _prompt_many(
        "Docker volume or bind-mount paths",
        "Volume or bind-mount path",
        allow_empty=True,
        check_paths=True,
        input_func=input_func,
        print_func=print_func,
    )
    excludes = prompt_excludes(defaults=GENERIC_DEFAULT_EXCLUDES, input_func=input_func, print_func=print_func)
    docker_inventory = prompt_bool("Enable DOCKER_INVENTORY", True, input_func=input_func)
    has_database = prompt_bool("Does this application contain a database", False, input_func=input_func)

    backup_paths = [str(project_path)]
    compose_path = str(Path(compose_file))
    if compose_path not in backup_paths:
        backup_paths.append(compose_path)
    if include_env:
        env_path = str(project_path / ".env")
        if env_path not in backup_paths:
            backup_paths.append(env_path)
        _warn_if_path_missing(env_path, print_func=print_func)
    else:
        excludes.append(str(project_path / ".env"))
    backup_paths.extend(volume_paths)

    comments: list[str] = []
    if has_database:
        print_func("Detailed DB configuration will be implemented in PR25 with: sudo server-backup db add")
        comments = [
            "# DATABASE_DUMPS will be configured by:",
            "# sudo server-backup db add",
        ]

    return {
        "PROFILE_NAME": profile_name,
        "PROFILE_TYPE": "docker-app",
        "DOCKER_INVENTORY": _bool_string(docker_inventory),
        "MISSING_PATH_BEHAVIOR": _prompt_missing_path_behavior(input_func=input_func),
        "BACKUP_PATHS": _dedupe(backup_paths),
        "EXCLUDES": _dedupe(excludes),
        "__comments__": comments,
    }


def prompt_profile_cis_site(
    profile_name: str,
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
) -> dict[str, object]:
    print_func(f"Using profile name '{profile_name}' as the logical CIS site name.")
    project_path = Path(prompt_string("CIS project path", f"/srv/{profile_name}", input_func=input_func))
    _warn_if_path_missing(str(project_path), print_func=print_func)

    default_frontend = project_path / "frontend"
    default_backend = project_path / "backend"
    migrations_candidates = [default_backend / "alembic", default_backend / "migrations"]
    default_migrations = next((candidate for candidate in migrations_candidates if candidate.exists()), migrations_candidates[0])

    frontend_path = Path(prompt_string("Frontend path", str(default_frontend), input_func=input_func))
    backend_path = Path(prompt_string("Backend path", str(default_backend), input_func=input_func))
    migrations_path = Path(prompt_string("Migrations path", str(default_migrations), input_func=input_func))
    compose_file = _choose_compose_file(project_path, input_func=input_func, print_func=print_func)
    include_env = prompt_bool("Include .env file", True, input_func=input_func)
    pages_in_postgresql = prompt_bool("Are builder pages stored in PostgreSQL", True, input_func=input_func)
    pages_table = prompt_string("Builder pages table", "site_pages", input_func=input_func)
    has_local_media = prompt_bool("Are there local media/uploads paths to include", False, input_func=input_func)
    media_paths: list[str] = []
    if has_local_media:
        media_paths = _prompt_many(
            "Local media or uploads paths",
            "Media or uploads path",
            allow_empty=False,
            check_paths=True,
            input_func=input_func,
            print_func=print_func,
        )
    media_external = prompt_bool("Are media/assets stored externally", False, input_func=input_func)
    web_content_critical = prompt_bool("Enable WEB_CONTENT_CRITICAL", True, input_func=input_func)
    docker_inventory = prompt_bool("Enable DOCKER_INVENTORY", True, input_func=input_func)

    print_func("Database dump configuration is not implemented in this PR.")
    print_func("It will be configured later with: sudo server-backup db add")

    backup_paths = [
        str(project_path),
        str(frontend_path),
        str(backend_path),
        str(migrations_path),
        "/var/lib/server-backup/state",
    ]
    compose_path = str(Path(compose_file))
    if compose_path not in backup_paths:
        backup_paths.append(compose_path)
    if include_env:
        env_path = str(project_path / ".env")
        if env_path not in backup_paths:
            backup_paths.append(env_path)
        _warn_if_path_missing(env_path, print_func=print_func)
    media_paths = _dedupe(media_paths)
    backup_paths.extend(media_paths)

    for path_value in [str(frontend_path), str(backend_path), str(migrations_path)]:
        _warn_if_path_missing(path_value, print_func=print_func)

    excludes = prompt_excludes(defaults=CIS_DEFAULT_EXCLUDES, input_func=input_func, print_func=print_func)
    if not include_env:
        excludes.append(str(project_path / ".env"))

    content_classification = [
        f"files:{frontend_path}:frontend-renderer-and-routes",
        f"files:{backend_path}:api-models-and-migrations",
    ]
    if pages_in_postgresql:
        content_classification.insert(0, f"db:postgresql:<database-placeholder>:{pages_table}:builder-pages")
    for media_path in media_paths:
        content_classification.append(f"files:{media_path}:media-uploads")
    if media_external:
        content_classification.append("files:<external-media>:document-external-media-location")

    return {
        "PROFILE_NAME": profile_name,
        "PROFILE_TYPE": "cis-site",
        "APP_KIND": "cis-site",
        "WEB_CONTENT_CRITICAL": _bool_string(web_content_critical),
        "DOCKER_INVENTORY": _bool_string(docker_inventory),
        "MISSING_PATH_BEHAVIOR": _prompt_missing_path_behavior(input_func=input_func),
        "BACKUP_PATHS": _dedupe(backup_paths),
        "EXCLUDES": _dedupe(excludes),
        "CONTENT_CLASSIFICATION": _dedupe(content_classification),
        "__comments__": [
            "# DATABASE_DUMPS will be configured by:",
            "# sudo server-backup db add",
        ],
    }


def run_profile_add(
    *,
    input_func: PromptFunc = input,
    print_func: PrintFunc = print,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> ProfileAddResult:
    _ensure_root()
    _require_installed_path(DEFAULT_CONFIG_ROOT, "Configuration root")
    _require_installed_path(profiles_dir, "Profiles directory")

    print_func("server-backup profile add")
    print_func("")

    profile_name = prompt_profile_name(input_func=input_func, print_func=print_func)
    profile_type = prompt_profile_type(input_func=input_func)

    if profile_type == "generic":
        profile_payload = prompt_profile_generic(profile_name, input_func=input_func, print_func=print_func)
    elif profile_type == "system-filesystem":
        profile_payload = prompt_profile_system_filesystem(profile_name, input_func=input_func, print_func=print_func)
    elif profile_type == "docker-host":
        profile_payload = prompt_profile_docker_host(profile_name, input_func=input_func, print_func=print_func)
    elif profile_type == "docker-app":
        profile_payload = prompt_profile_docker_app(profile_name, input_func=input_func, print_func=print_func)
    elif profile_type == "cis-site":
        profile_payload = prompt_profile_cis_site(profile_name, input_func=input_func, print_func=print_func)
    else:
        raise ValueError(f"Unsupported profile type: {profile_type}")

    profile_path = profiles_dir / f"{profile_name}.conf"
    backup_existing_profile = False
    if profile_path.exists():
        if not confirm_overwrite(profile_path, input_func=input_func):
            print_func("Existing profile file left unchanged.")
            return ProfileAddResult(ok=False, profile_name=profile_name, profile_path=str(profile_path))
        backup_existing_profile = True

    rendered = render_profile_conf(profile_payload)
    write_profile_file_secure(profile_path, rendered, backup_existing=backup_existing_profile)

    validation_profile = {
        "__file__": str(profile_path),
        "__kind__": "profile",
        "__parse_warnings__": [],
        "CONFIG_VERSION": "1",
        **{key: value for key, value in profile_payload.items() if not str(key).startswith("__")},
    }
    validation = validate_profile_config(validation_profile)

    print_func("")
    print_func("Validation summary:")
    if validation.errors:
        for error in validation.errors:
            print_func(f"  error: {error}")
    if validation.warnings:
        for warning in validation.warnings:
            print_func(f"  warning: {warning}")
    if not validation.errors and not validation.warnings:
        print_func("  profile configuration looks valid")

    print_func("")
    print_func("Next step:")
    print_func("  sudo server-backup config validate")

    return ProfileAddResult(
        ok=not validation.errors,
        profile_name=profile_name,
        profile_path=str(profile_path),
        messages=[*validation.errors, *validation.warnings],
    )
