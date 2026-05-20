from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backup import LAST_BACKUP_RUN_FILE
from .config import load_global_config, load_profiles, load_targets
from .coverage import LAST_COVERAGE_AUDIT_FILE
from .db import load_database_dumps_from_profiles
from .docker import docker_available
from .email_report import LAST_EMAIL_REPORT_FILE
from .restic import LAST_PRUNE_RUN_FILE
from .restore import LAST_RESTORE_TEST_FILE
from .validators import validate_all, validate_global_config, validate_profile_config, validate_target_config


DEFAULT_BACKUP_CONF = Path("/etc/server-backup/backup.conf")
DEFAULT_TARGETS_DIR = Path("/etc/server-backup/targets.d")
DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
DEFAULT_TIMER_PATH = Path("/etc/systemd/system/server-backup.timer")

DEFAULT_BACKUP_MAX_AGE_HOURS = 30
DEFAULT_RESTORE_TEST_MAX_AGE_DAYS = 30
DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS = 7
DEFAULT_PRUNE_MAX_AGE_DAYS = 14


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_systemctl(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["systemctl", *args],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except FileNotFoundError:
        return None


def timer_enabled_status() -> tuple[str, str]:
    result = _run_systemctl("is-enabled", "server-backup.timer")
    if result is None:
        return "unknown", "systemctl not available"
    if result.returncode == 0:
        return "yes", "server-backup.timer is enabled"
    detail = (result.stdout or result.stderr).strip() or "disabled"
    return "no", detail


def timer_next_run() -> tuple[str, str]:
    result = _run_systemctl("show", "server-backup.timer", "--property=NextElapseUSecRealtime", "--value")
    if result is None:
        return "unknown", "systemctl not available"
    if result.returncode != 0:
        return "unknown", (result.stderr or result.stdout).strip() or "could not inspect timer"
    value = (result.stdout or "").strip()
    if not value:
        return "unknown", "next run not available"
    return value, "ok"


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (PermissionError, OSError, json.JSONDecodeError):
        return None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_hours(value: object, *, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max((now - parsed).total_seconds() / 3600.0, 0.0)


def _age_days(value: object, *, now: datetime) -> float | None:
    hours = _age_hours(value, now=now)
    if hours is None:
        return None
    return hours / 24.0


def _boolish(value: object) -> bool:
    return str(value).strip().lower() == "true"


def _resolve_state_dir(global_config: dict[str, Any]) -> Path:
    configured = str(global_config.get("STATE_DIR", "")).strip()
    return Path(configured) if configured else DEFAULT_STATE_DIR


def _state_paths(global_config: dict[str, Any]) -> dict[str, Path]:
    state_dir = _resolve_state_dir(global_config)
    return {
        "state_dir": state_dir,
        "last_backup": state_dir / LAST_BACKUP_RUN_FILE,
        "last_prune": state_dir / LAST_PRUNE_RUN_FILE,
        "last_restore_test": state_dir / LAST_RESTORE_TEST_FILE,
        "last_coverage_audit": state_dir / LAST_COVERAGE_AUDIT_FILE,
        "last_email_report": state_dir / LAST_EMAIL_REPORT_FILE,
    }


def _profiles_require_docker(profiles: list[dict[str, Any]]) -> bool:
    for profile in profiles:
        profile_type = str(profile.get("PROFILE_TYPE", "")).strip()
        app_kind = str(profile.get("APP_KIND", "")).strip()
        if profile_type in {"docker-host", "docker-app", "cis-site"}:
            return True
        if app_kind == "cis-site":
            return True
        if str(profile.get("DOCKER_INVENTORY", "")).strip().lower() == "true":
            return True
    return False


def _email_command_available(global_config: dict[str, Any]) -> tuple[bool, str]:
    if not _boolish(global_config.get("EMAIL_REPORT_ENABLED", "")):
        return True, "email reports disabled"

    command = str(global_config.get("EMAIL_REPORT_COMMAND", "")).strip()
    if command == "sendmail":
        sendmail = Path("/usr/sbin/sendmail")
        if sendmail.exists() or shutil.which("sendmail"):
            return True, "sendmail available"
        return False, "sendmail is configured but not available"
    if command == "mail":
        if shutil.which("mail") or shutil.which("mailx"):
            return True, "mail/mailx available"
        return False, "mail is configured but mail/mailx is not available"
    return False, "EMAIL_REPORT_COMMAND is invalid or missing"


def _restic_available() -> tuple[bool, str]:
    if shutil.which("restic"):
        return True, "restic available"
    return False, "restic is not installed or not available in PATH"


def _check_result(severity: str, code: str, message: str, recommendation: str = "") -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "recommendation": recommendation,
    }


def _resolve_report_status(checks: list[dict[str, str]]) -> str:
    severities = {check["severity"] for check in checks}
    if "FAILURE" in severities:
        return "FAILURE"
    if "WARNING" in severities:
        return "WARNING"
    return "SUCCESS"


def _collect_recommendations(checks: list[dict[str, str]]) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()
    for check in checks:
        recommendation = check.get("recommendation", "").strip()
        if not recommendation or recommendation in seen:
            continue
        recommendations.append(recommendation)
        seen.add(recommendation)
    return recommendations


def _last_state_summary(payload: dict[str, Any] | None, date_key: str) -> dict[str, Any]:
    if payload is None:
        return {"present": False, "status": "missing", "date": "", "report": ""}
    return {
        "present": True,
        "status": str(payload.get("status", "unknown")),
        "date": str(payload.get(date_key, "")),
        "report": str(payload.get("text_report_path", "")),
    }


def build_operations_status(
    global_config: dict[str, Any] | None = None,
    targets: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if global_config is None:
        global_config = load_global_config(DEFAULT_BACKUP_CONF)
    if targets is None:
        targets = load_targets(DEFAULT_TARGETS_DIR)
    if profiles is None:
        profiles = load_profiles(DEFAULT_PROFILES_DIR)

    current_time = now or datetime.now(UTC)
    state_paths = _state_paths(global_config)
    last_backup = _load_json_file(state_paths["last_backup"])
    last_prune = _load_json_file(state_paths["last_prune"])
    last_restore = _load_json_file(state_paths["last_restore_test"])
    last_coverage = _load_json_file(state_paths["last_coverage_audit"])
    last_email = _load_json_file(state_paths["last_email_report"])

    timer_enabled, timer_enabled_detail = timer_enabled_status()
    timer_next, timer_next_detail = timer_next_run()
    db_dumps = load_database_dumps_from_profiles(profiles)

    warnings: list[str] = []
    if timer_enabled != "yes":
        warnings.append("server-backup.timer is not enabled")

    backup_age_hours = _age_hours(last_backup.get("end_time"), now=current_time) if last_backup else None
    if backup_age_hours is None:
        warnings.append("No previous backup run report found")
    elif backup_age_hours > DEFAULT_BACKUP_MAX_AGE_HOURS:
        warnings.append(f"Last backup run is older than {DEFAULT_BACKUP_MAX_AGE_HOURS} hours")

    restore_age_days = _age_days(last_restore.get("end_time"), now=current_time) if last_restore else None
    if restore_age_days is None:
        warnings.append("No previous restore test report found")
    elif restore_age_days > DEFAULT_RESTORE_TEST_MAX_AGE_DAYS:
        warnings.append(f"Last restore test is older than {DEFAULT_RESTORE_TEST_MAX_AGE_DAYS} days")

    coverage_age_days = _age_days(last_coverage.get("end_time"), now=current_time) if last_coverage else None
    if coverage_age_days is None:
        warnings.append("No previous coverage audit report found")
    elif coverage_age_days > DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS:
        warnings.append(f"Last coverage audit is older than {DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS} days")

    prune_age_days = _age_days(last_prune.get("end_time"), now=current_time) if last_prune else None
    if prune_age_days is None:
        warnings.append("No previous prune report found")
    elif prune_age_days > DEFAULT_PRUNE_MAX_AGE_DAYS:
        warnings.append(f"Last prune run is older than {DEFAULT_PRUNE_MAX_AGE_DAYS} days")

    return {
        "generated_at": _timestamp(),
        "hostname": socket.gethostname(),
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "timer": {
            "file_exists": DEFAULT_TIMER_PATH.exists(),
            "enabled": timer_enabled,
            "enabled_detail": timer_enabled_detail,
            "next_run": timer_next,
            "next_run_detail": timer_next_detail,
        },
        "target_count": len(targets),
        "profile_count": len(profiles),
        "db_dump_count": len(db_dumps),
        "last_backup": _last_state_summary(last_backup, "end_time"),
        "last_prune": _last_state_summary(last_prune, "end_time"),
        "last_restore_test": _last_state_summary(last_restore, "end_time"),
        "last_coverage_audit": _last_state_summary(last_coverage, "end_time"),
        "last_email": {
            "present": last_email is not None,
            "status": "success" if last_email and last_email.get("success") else ("failure" if last_email else "missing"),
            "date": str((last_email or {}).get("sent_at", "")),
            "kind": str((last_email or {}).get("kind", "")),
            "subject": str((last_email or {}).get("subject", "")),
            "command": str((last_email or {}).get("command", "")),
        },
        "warnings": warnings,
    }


def run_health_check(
    global_config: dict[str, Any] | None = None,
    targets: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if global_config is None:
        global_config = load_global_config(DEFAULT_BACKUP_CONF)
    if targets is None:
        targets = load_targets(DEFAULT_TARGETS_DIR)
    if profiles is None:
        profiles = load_profiles(DEFAULT_PROFILES_DIR)

    current_time = now or datetime.now(UTC)
    checks: list[dict[str, str]] = []

    if global_config.get("__missing__"):
        checks.append(
            _check_result(
                "FAILURE",
                "global-config-missing",
                "backup.conf is missing",
                "Run sudo server-backup setup",
            )
        )
    else:
        global_validation = validate_global_config(global_config)
        if global_validation.errors:
            checks.append(
                _check_result(
                    "FAILURE",
                    "global-config-invalid",
                    f"backup.conf has validation errors: {len(global_validation.errors)}",
                    "Run sudo server-backup config validate and fix the reported errors",
                )
            )
        elif global_validation.warnings:
            checks.append(
                _check_result(
                    "WARNING",
                    "global-config-warning",
                    f"backup.conf has validation warnings: {len(global_validation.warnings)}",
                    "Review sudo server-backup config validate",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "global-config", "backup.conf is present and valid"))

    if not targets:
        checks.append(
            _check_result(
                "FAILURE",
                "targets-missing",
                "No target is configured",
                "Run sudo server-backup target add",
            )
        )
    else:
        invalid_targets = [target for target in targets if validate_target_config(target).errors]
        if invalid_targets:
            checks.append(
                _check_result(
                    "FAILURE",
                    "targets-invalid",
                    f"{len(invalid_targets)} target(s) have validation errors",
                    "Run sudo server-backup config validate and fix target configuration errors",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "targets", f"{len(targets)} target(s) configured"))

    if not profiles:
        checks.append(
            _check_result(
                "FAILURE",
                "profiles-missing",
                "No profile is configured",
                "Run sudo server-backup profile add",
            )
        )
    else:
        invalid_profiles = [profile for profile in profiles if validate_profile_config(profile).errors]
        if invalid_profiles:
            checks.append(
                _check_result(
                    "FAILURE",
                    "profiles-invalid",
                    f"{len(invalid_profiles)} profile(s) have validation errors",
                    "Run sudo server-backup config validate and fix profile configuration errors",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "profiles", f"{len(profiles)} profile(s) configured"))

    restic_ok, restic_detail = _restic_available()
    checks.append(
        _check_result(
            "SUCCESS" if restic_ok else "FAILURE",
            "restic-available",
            restic_detail,
            "" if restic_ok else "Install restic and rerun sudo ./scripts/install.sh",
        )
    )

    password_file = str(global_config.get("RESTIC_PASSWORD_FILE", "")).strip()
    if password_file:
        password_path = Path(password_file)
        if password_path.exists():
            checks.append(_check_result("SUCCESS", "restic-password-file", "RESTIC_PASSWORD_FILE exists"))
        else:
            checks.append(
                _check_result(
                    "FAILURE",
                    "restic-password-file-missing",
                    f"RESTIC_PASSWORD_FILE is missing: {password_path}",
                    "Recreate the password file or rerun sudo server-backup setup",
                )
            )
        cache_dir = str(global_config.get("RESTIC_CACHE_DIR", "")).strip()
        if cache_dir and Path(cache_dir).exists():
            checks.append(_check_result("SUCCESS", "restic-cache-dir", "RESTIC_CACHE_DIR exists"))
        elif cache_dir:
            checks.append(
                _check_result(
                    "FAILURE",
                    "restic-cache-dir-missing",
                    f"RESTIC_CACHE_DIR is missing: {cache_dir}",
                    "Create the cache directory or rerun sudo ./scripts/install.sh",
                )
            )
    else:
        checks.append(
            _check_result(
                "FAILURE",
                "restic-password-file-unset",
                "RESTIC_PASSWORD_FILE is not configured",
                "Run sudo server-backup setup",
            )
        )

    if _profiles_require_docker(profiles):
        docker_state = docker_available()
        docker_ok = bool(docker_state.get("available"))
        checks.append(
            _check_result(
                "SUCCESS" if docker_ok else "FAILURE",
                "docker-available",
                docker_state.get("reason", "") if not docker_ok else "docker available",
                "" if docker_ok else "Install or fix Docker on this host before relying on docker-host, docker-app or cis-site profiles",
            )
        )

    email_ok, email_detail = _email_command_available(global_config)
    email_severity = "SUCCESS" if email_ok else "WARNING"
    email_recommendation = "" if email_ok else "Install the configured mail command or disable EMAIL_REPORT_ENABLED until the local MTA is ready"
    checks.append(_check_result(email_severity, "email-command", email_detail, email_recommendation))

    operations = build_operations_status(global_config, targets, profiles, now=current_time)
    timer = operations["timer"]
    checks.append(
        _check_result(
            "SUCCESS" if timer.get("file_exists") else "FAILURE",
            "timer-file",
            "server-backup.timer is installed" if timer.get("file_exists") else "server-backup.timer is missing",
            "" if timer.get("file_exists") else "Run sudo ./scripts/install.sh",
        )
    )
    checks.append(
        _check_result(
            "SUCCESS" if timer.get("enabled") == "yes" else "WARNING",
            "timer-enabled",
            "server-backup.timer is enabled" if timer.get("enabled") == "yes" else "server-backup.timer is not enabled",
            "" if timer.get("enabled") == "yes" else "Run sudo systemctl enable --now server-backup.timer after validating the deployment",
        )
    )

    last_backup = operations["last_backup"]
    if not last_backup.get("present"):
        checks.append(
            _check_result(
                "WARNING",
                "last-backup-missing",
                "No previous backup run report found",
                "Run sudo server-backup backup run --dry-run, then a real backup",
            )
        )
    else:
        backup_age_hours = _age_hours(last_backup.get("date"), now=current_time)
        if backup_age_hours is not None and backup_age_hours > DEFAULT_BACKUP_MAX_AGE_HOURS:
            checks.append(
                _check_result(
                    "WARNING",
                    "last-backup-stale",
                    f"Last backup run is older than {DEFAULT_BACKUP_MAX_AGE_HOURS} hours",
                    "Run sudo server-backup backup run or verify the timer",
                )
            )
        elif str(last_backup.get("status", "")).lower() not in {"success", "warning"}:
            checks.append(
                _check_result(
                    "WARNING",
                    "last-backup-status",
                    f"Last backup run status is {last_backup.get('status', 'unknown')}",
                    "Inspect the last backup report and rerun the backup if needed",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "last-backup", "Last backup run is recent enough"))

    last_restore = operations["last_restore_test"]
    if not last_restore.get("present"):
        checks.append(
            _check_result(
                "WARNING",
                "last-restore-test-missing",
                "No previous restore test report found",
                "Run sudo server-backup restore test --target <target>",
            )
        )
    else:
        restore_age_days = _age_days(last_restore.get("date"), now=current_time)
        if restore_age_days is not None and restore_age_days > DEFAULT_RESTORE_TEST_MAX_AGE_DAYS:
            checks.append(
                _check_result(
                    "WARNING",
                    "last-restore-test-stale",
                    f"Last restore test is older than {DEFAULT_RESTORE_TEST_MAX_AGE_DAYS} days",
                    "Run sudo server-backup restore test --target <target>",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "last-restore-test", "Last restore test is recent enough"))

    last_coverage = operations["last_coverage_audit"]
    if not last_coverage.get("present"):
        checks.append(
            _check_result(
                "WARNING",
                "last-coverage-audit-missing",
                "No previous coverage audit report found",
                "Run sudo server-backup coverage audit",
            )
        )
    else:
        coverage_age_days = _age_days(last_coverage.get("date"), now=current_time)
        if coverage_age_days is not None and coverage_age_days > DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS:
            checks.append(
                _check_result(
                    "WARNING",
                    "last-coverage-audit-stale",
                    f"Last coverage audit is older than {DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS} days",
                    "Run sudo server-backup coverage audit",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "last-coverage-audit", "Last coverage audit is recent enough"))

    last_prune = operations["last_prune"]
    if not last_prune.get("present"):
        checks.append(
            _check_result(
                "WARNING",
                "last-prune-missing",
                "No previous prune report found",
                "Run sudo server-backup repo prune <target> --dry-run",
            )
        )
    else:
        prune_age_days = _age_days(last_prune.get("date"), now=current_time)
        if prune_age_days is not None and prune_age_days > DEFAULT_PRUNE_MAX_AGE_DAYS:
            checks.append(
                _check_result(
                    "WARNING",
                    "last-prune-stale",
                    f"Last prune run is older than {DEFAULT_PRUNE_MAX_AGE_DAYS} days",
                    "Run sudo server-backup repo prune <target> --dry-run",
                )
            )
        else:
            checks.append(_check_result("SUCCESS", "last-prune", "Last prune run is recent enough"))

    status = _resolve_report_status(checks)
    return {
        "generated_at": _timestamp(),
        "hostname": socket.gethostname(),
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "status": status,
        "checks": checks,
        "recommendations": _collect_recommendations(checks),
        "thresholds": {
            "BACKUP_MAX_AGE_HOURS": DEFAULT_BACKUP_MAX_AGE_HOURS,
            "RESTORE_TEST_MAX_AGE_DAYS": DEFAULT_RESTORE_TEST_MAX_AGE_DAYS,
            "COVERAGE_AUDIT_MAX_AGE_DAYS": DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS,
            "PRUNE_MAX_AGE_DAYS": DEFAULT_PRUNE_MAX_AGE_DAYS,
        },
        "operations": operations,
    }


__all__ = [
    "DEFAULT_BACKUP_MAX_AGE_HOURS",
    "DEFAULT_COVERAGE_AUDIT_MAX_AGE_DAYS",
    "DEFAULT_PRUNE_MAX_AGE_DAYS",
    "DEFAULT_RESTORE_TEST_MAX_AGE_DAYS",
    "build_operations_status",
    "run_health_check",
    "timer_enabled_status",
    "timer_next_run",
]
