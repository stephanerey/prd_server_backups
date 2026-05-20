from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import stat
from typing import Any

from .config import config_file_exists


SYSTEM_PATHS = (
    Path("/etc/server-backup"),
    Path("/etc/server-backup/targets.d"),
    Path("/etc/server-backup/profiles.d"),
    Path("/var/cache/restic"),
    Path("/var/lib/server-backup"),
)

GLOBAL_REQUIRED_FIELDS = (
    "CONFIG_VERSION",
    "BACKUP_NAME",
    "RETENTION_DAILY",
    "RETENTION_WEEKLY",
    "RETENTION_MONTHLY",
    "LOCAL_DUMP_DIR",
    "LOG_FILE",
    "STATE_DIR",
    "REPORT_DIR",
    "RESTIC_CACHE_DIR",
    "RESTIC_PASSWORD_FILE",
    "RUN_RESTIC_CHECK",
    "RUN_PRUNE",
)

TARGET_REQUIRED_FIELDS = (
    "CONFIG_VERSION",
    "TARGET_NAME",
    "TARGET_TYPE",
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD_FILE",
    "RESTIC_CACHE_DIR",
)

SFTP_REQUIRED_FIELDS = (
    "SSH_HOST_ALIAS",
    "SSH_HOSTNAME",
    "SSH_PORT",
    "SSH_USER",
    "SSH_IDENTITY_FILE",
)

PROFILE_REQUIRED_FIELDS = (
    "CONFIG_VERSION",
    "PROFILE_NAME",
    "PROFILE_TYPE",
    "BACKUP_PATHS",
)

FUTURE_TARGET_TYPES = {"rest-server", "s3", "rclone"}
SUPPORTED_PROFILE_TYPES = {"generic", "docker-host", "docker-app", "cis-site", "system-filesystem"}


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def extend(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if other.errors:
            self.ok = False


def _has_value(config: dict[str, Any], key: str) -> bool:
    value = config.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list):
        return len(value) > 0
    return True


def _add_parse_warnings(result: ValidationResult, config: dict[str, Any]) -> None:
    for warning in config.get("__parse_warnings__", []):
        result.add_warning(str(warning))


def _require_fields(config: dict[str, Any], fields: tuple[str, ...], result: ValidationResult) -> None:
    for field_name in fields:
        if not _has_value(config, field_name):
            result.add_error(f"{config.get('__file__', '<unknown>')}: missing required field '{field_name}'")


def _validate_positive_int(config: dict[str, Any], field_name: str, result: ValidationResult) -> None:
    if not _has_value(config, field_name):
        return
    try:
        value = int(str(config[field_name]))
    except (TypeError, ValueError):
        result.add_error(f"{config.get('__file__', '<unknown>')}: field '{field_name}' must be a positive integer")
        return
    if value <= 0:
        result.add_error(f"{config.get('__file__', '<unknown>')}: field '{field_name}' must be a positive integer")


def _validate_path_list(profile: dict[str, Any], field_name: str, result: ValidationResult) -> list[str]:
    value = profile.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list):
        result.add_error(f"{profile.get('__file__', '<unknown>')}: field '{field_name}' must be a Bash-style array")
        return []
    return [str(item) for item in value]


def _safe_path_exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except PermissionError:
        return True


def _safe_stat(path: str | Path):
    try:
        return Path(path).stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _warn_if_missing_path(
    target: dict[str, Any],
    field_name: str,
    result: ValidationResult,
    *,
    warn_if_field_missing: bool,
) -> None:
    value = str(target.get(field_name, "")).strip()
    if not value:
        if warn_if_field_missing:
            result.add_warning(
                f"{target.get('__file__', '<unknown>')}: field '{field_name}' is recommended for SFTP targets"
            )
        return
    if not _safe_path_exists(value):
        result.add_warning(f"{target.get('__file__', '<unknown>')}: referenced path does not exist: {value}")


def _warn_if_permissions_open(
    target: dict[str, Any],
    field_name: str,
    *,
    expected_mode: int,
    result: ValidationResult,
) -> None:
    value = str(target.get(field_name, "")).strip()
    if not value:
        return
    path_stat = _safe_stat(value)
    if path_stat is None:
        return
    current_mode = stat.S_IMODE(path_stat.st_mode)
    if current_mode != expected_mode:
        result.add_warning(
            f"{target.get('__file__', '<unknown>')}: {field_name} should use permissions {oct(expected_mode)}, found {oct(current_mode)}"
        )


def _warn_if_missing_target_path(
    target: dict[str, Any],
    field_name: str,
    result: ValidationResult,
) -> None:
    value = str(target.get(field_name, "")).strip()
    if not value:
        return
    if not _safe_path_exists(value):
        result.add_warning(f"{target.get('__file__', '<unknown>')}: referenced path does not exist: {value}")


def validate_global_config(config: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    if config.get("__missing__"):
        result.add_error(f"{config.get('__file__', '<unknown>')}: global configuration file not found")
        return result

    _add_parse_warnings(result, config)
    _require_fields(config, GLOBAL_REQUIRED_FIELDS, result)

    for field_name in ("RETENTION_DAILY", "RETENTION_WEEKLY", "RETENTION_MONTHLY"):
        _validate_positive_int(config, field_name, result)

    if str(config.get("EMAIL_REPORT_ENABLED", "")).lower() == "true":
        for field_name in ("EMAIL_REPORT_TO", "EMAIL_REPORT_FROM", "EMAIL_REPORT_COMMAND"):
            if not _has_value(config, field_name):
                result.add_error(f"{config.get('__file__', '<unknown>')}: missing required email field '{field_name}'")

        command = str(config.get("EMAIL_REPORT_COMMAND", "")).strip()
        if command and command not in {"sendmail", "mail"}:
            result.add_error(
                f"{config.get('__file__', '<unknown>')}: EMAIL_REPORT_COMMAND must be 'sendmail' or 'mail'"
            )

    for path in SYSTEM_PATHS:
        if not _safe_path_exists(path):
            result.add_warning(f"Expected system path does not exist yet: {path}")

    return result


def validate_target_config(target: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    _add_parse_warnings(result, target)
    _require_fields(target, TARGET_REQUIRED_FIELDS, result)

    target_type = str(target.get("TARGET_TYPE", "")).strip()
    if target_type == "sftp":
        _require_fields(target, SFTP_REQUIRED_FIELDS, result)
        if _has_value(target, "SSH_PORT"):
            try:
                port = int(str(target["SSH_PORT"]))
            except (TypeError, ValueError):
                result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_PORT must be an integer")
            else:
                if port < 1 or port > 65535:
                    result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_PORT must be between 1 and 65535")
        _warn_if_missing_path(target, "SSH_IDENTITY_FILE", result, warn_if_field_missing=False)
        _warn_if_missing_path(target, "SSH_CONFIG_FILE", result, warn_if_field_missing=True)
        _warn_if_missing_path(target, "SSH_KNOWN_HOSTS_FILE", result, warn_if_field_missing=True)
        _warn_if_missing_target_path(target, "RESTIC_PASSWORD_FILE", result)
        _warn_if_missing_target_path(target, "RESTIC_CACHE_DIR", result)
        _warn_if_permissions_open(target, "SSH_IDENTITY_FILE", expected_mode=0o600, result=result)
        _warn_if_permissions_open(target, "SSH_CONFIG_FILE", expected_mode=0o600, result=result)
        _warn_if_permissions_open(target, "SSH_KNOWN_HOSTS_FILE", expected_mode=0o600, result=result)
        _warn_if_permissions_open(target, "RESTIC_PASSWORD_FILE", expected_mode=0o600, result=result)
    elif target_type in FUTURE_TARGET_TYPES:
        result.add_warning(
            f"Target type '{target_type}' is recognized as future backend but not implemented in MVP."
        )
    elif target_type:
        result.add_error(f"{target.get('__file__', '<unknown>')}: unsupported TARGET_TYPE '{target_type}'")

    return result


def validate_profile_config(profile: dict[str, Any]) -> ValidationResult:
    from .db import parse_database_dump_spec

    result = ValidationResult()
    _add_parse_warnings(result, profile)
    _require_fields(profile, PROFILE_REQUIRED_FIELDS, result)

    profile_type = str(profile.get("PROFILE_TYPE", "")).strip()
    if profile_type and profile_type not in SUPPORTED_PROFILE_TYPES:
        result.add_error(f"{profile.get('__file__', '<unknown>')}: unsupported PROFILE_TYPE '{profile_type}'")

    backup_paths = _validate_path_list(profile, "BACKUP_PATHS", result)
    for backup_path in backup_paths:
        if not _safe_path_exists(backup_path):
            result.add_warning(f"{profile.get('__file__', '<unknown>')}: BACKUP_PATHS entry does not exist: {backup_path}")

    if "EXCLUDES" in profile:
        _validate_path_list(profile, "EXCLUDES", result)
    if "DATABASE_DUMPS" in profile:
        dumps = profile.get("DATABASE_DUMPS")
        if not isinstance(dumps, list):
            result.add_error(f"{profile.get('__file__', '<unknown>')}: DATABASE_DUMPS must be a list")
        else:
            seen_dump_names: set[str] = set()
            for raw_spec in dumps:
                try:
                    parsed_spec = parse_database_dump_spec(str(raw_spec))
                except ValueError as exc:
                    result.add_error(f"{profile.get('__file__', '<unknown>')}: {exc}")
                    continue
                dump_name = str(parsed_spec.get("name", "")).strip()
                if dump_name in seen_dump_names:
                    result.add_error(
                        f"{profile.get('__file__', '<unknown>')}: duplicate DATABASE_DUMPS entry name={dump_name}"
                    )
                seen_dump_names.add(dump_name)

    app_kind = str(profile.get("APP_KIND", "")).strip()
    is_cis_profile = profile_type == "cis-site" or app_kind == "cis-site"
    if is_cis_profile:
        if str(profile.get("WEB_CONTENT_CRITICAL", "")).lower() != "true":
            result.add_warning(f"{profile.get('__file__', '<unknown>')}: WEB_CONTENT_CRITICAL=\"true\" is recommended for CIS profiles")
        if not _has_value(profile, "DATABASE_DUMPS"):
            result.add_warning(f"{profile.get('__file__', '<unknown>')}: DATABASE_DUMPS is recommended for CIS profiles")
        if not _has_value(profile, "CONTENT_CLASSIFICATION"):
            result.add_warning(
                f"{profile.get('__file__', '<unknown>')}: CONTENT_CLASSIFICATION is recommended for CIS profiles"
            )
        else:
            _validate_path_list(profile, "CONTENT_CLASSIFICATION", result)

    if profile_type in {"docker-host", "docker-app", "cis-site"} and not _has_value(profile, "DOCKER_INVENTORY"):
        result.add_warning(f"{profile.get('__file__', '<unknown>')}: DOCKER_INVENTORY is recommended for Docker-aware profiles")

    return result


def validate_all(global_config: dict[str, Any], targets: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> ValidationResult:
    result = ValidationResult()
    result.extend(validate_global_config(global_config))

    if not targets:
        result.add_warning("No targets are configured.")
    for target in targets:
        result.extend(validate_target_config(target))

    if not profiles:
        result.add_warning("No profiles are configured.")
    for profile in profiles:
        result.extend(validate_profile_config(profile))

    return result
