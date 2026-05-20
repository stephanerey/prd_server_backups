from __future__ import annotations

import fnmatch
import json
import shutil
import shlex
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_global_config, load_profiles, load_targets, redact_config
from .db import load_database_dumps_from_profiles, run_database_dump
from .email_report import send_email_report
from .restic import (
    INTERRUPTED_MESSAGE,
    build_restic_base_command,
    build_restic_env,
    explain_restic_failure,
    OperationInterruptedError,
    repo_is_initialized,
    restic_repo_lock,
    run_restic_command,
    select_target,
    validate_restic_preflight,
)
from .validators import validate_global_config, validate_profile_config


DEFAULT_BACKUP_CONF = Path("/etc/server-backup/backup.conf")
DEFAULT_TARGETS_DIR = Path("/etc/server-backup/targets.d")
DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_REPORT_DIR = Path("/var/lib/server-backup/reports")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
LAST_BACKUP_RUN_FILE = "last-backup-run.json"


def load_backup_context() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        load_global_config(DEFAULT_BACKUP_CONF),
        load_targets(DEFAULT_TARGETS_DIR),
        load_profiles(DEFAULT_PROFILES_DIR),
    )


def collect_profiles(
    profiles: list[dict[str, Any]],
    profile_name: str | None = None,
) -> list[dict[str, Any]]:
    if profile_name is None:
        if not profiles:
            raise ValueError("No profiles are configured. Run sudo server-backup profile add.")
        return profiles

    for profile in profiles:
        if str(profile.get("PROFILE_NAME", "")).strip() == profile_name:
            return [profile]
    raise ValueError(f"Profile not found: {profile_name}")


def collect_targets(
    targets: list[dict[str, Any]],
    target_name: str | None = None,
) -> list[dict[str, Any]]:
    if target_name is None:
        if not targets:
            raise ValueError("No targets are configured. Run sudo server-backup target add.")
        return targets
    return [select_target(target_name, targets)]


def normalize_backup_paths(profile: dict[str, Any]) -> list[str]:
    value = profile.get("BACKUP_PATHS", [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_excludes(profile: dict[str, Any]) -> list[str]:
    value = profile.get("EXCLUDES", [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def validate_backup_paths(profile: dict[str, Any]) -> dict[str, Any]:
    existing_paths: list[str] = []
    missing_paths: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    for backup_path in normalize_backup_paths(profile):
        try:
            path_exists = Path(backup_path).exists()
        except PermissionError:
            path_exists = True

        if path_exists:
            existing_paths.append(backup_path)
        else:
            missing_paths.append(backup_path)
            warnings.append(
                f"{profile.get('PROFILE_NAME', '<unknown>')}: missing path: {backup_path}"
            )

    if not existing_paths:
        errors.append(
            f"{profile.get('PROFILE_NAME', '<unknown>')}: no existing BACKUP_PATHS remain for this profile"
        )

    return {
        "existing_paths": existing_paths,
        "missing_paths": missing_paths,
        "warnings": warnings,
        "errors": errors,
    }


def build_backup_tags(global_config: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    raw_tags: list[str] = ["server-backup"]
    backup_name = str(global_config.get("BACKUP_NAME", "")).strip()
    profile_name = str(profile.get("PROFILE_NAME", "")).strip()
    profile_type = str(profile.get("PROFILE_TYPE", "")).strip()
    backup_tags = str(global_config.get("BACKUP_TAGS", "")).strip().split()

    if backup_name:
        raw_tags.append(backup_name)
    if profile_name:
        raw_tags.append(profile_name)
    if profile_type:
        raw_tags.append(profile_type)
    raw_tags.extend(tag for tag in backup_tags if tag)

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        if not tag or tag in seen:
            continue
        deduped.append(tag)
        seen.add(tag)
    return deduped


def build_restic_backup_args(
    global_config: dict[str, Any],
    profile: dict[str, Any],
    dry_run: bool = False,
) -> list[str]:
    args = ["backup"]
    if dry_run:
        args.append("--dry-run")

    for tag in build_backup_tags(global_config, profile):
        args.extend(["--tag", tag])

    for exclude in normalize_excludes(profile):
        args.extend(["--exclude", exclude])

    paths = profile.get("__resolved_backup_paths__")
    if isinstance(paths, list):
        args.extend(str(path) for path in paths if str(path).strip())
    else:
        args.extend(normalize_backup_paths(profile))
    return args


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _dedupe_messages(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        if not message or message in seen:
            continue
        result.append(message)
        seen.add(message)
    return result


def _status_from_parts(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "failure"
    if warnings:
        return "warning"
    return "success"


def _aggregate_status(results: list[dict[str, Any]]) -> str:
    statuses = {str(result.get("status", "success")) for result in results}
    if "failure" in statuses:
        return "failure"
    if "warning" in statuses:
        return "warning"
    return "success"


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _sanitize_command_output(text: str) -> str:
    return text.replace("\x00", "").strip()


def _target_name(target: dict[str, Any]) -> str:
    return str(target.get("TARGET_NAME", "<unknown>"))


def _profile_name(profile: dict[str, Any]) -> str:
    return str(profile.get("PROFILE_NAME", "<unknown>"))


def _dump_name(dump_result: dict[str, Any]) -> str:
    return str(dump_result.get("name", "<unknown>"))


def _safe_name_for_path(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "-" for character in value).strip("-") or "item"


def _path_exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except PermissionError:
        return True


def _filter_profile_database_dumps(profile: dict[str, Any]) -> list[dict[str, Any]]:
    profile_name = _profile_name(profile)
    all_dumps = load_database_dumps_from_profiles([profile])
    return [dump for dump in all_dumps if str(dump.get("__profile_name__", "")).strip() == profile_name]


def _create_profile_dump_dir(global_config: dict[str, Any], target_name: str, profile_name: str) -> Path:
    base_dir = Path(str(global_config.get("LOCAL_DUMP_DIR") or "/var/tmp/server-backup"))
    base_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"backup-db-dumps-{target_name}-{profile_name}-"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(base_dir)))


def _exclude_covers_path(pattern: str, path: str | Path) -> bool:
    candidate = Path(path).as_posix()
    raw_pattern = str(pattern).strip()
    if not raw_pattern:
        return False
    if raw_pattern.startswith("/"):
        normalized = Path(raw_pattern).as_posix().rstrip("/")
        return candidate == normalized or candidate.startswith(f"{normalized}/")
    return fnmatch.fnmatch(candidate, raw_pattern)


def _cleanup_dump_dir(path: Path | None) -> None:
    if path is None:
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def run_backup_for_target(
    global_config: dict[str, Any],
    target: dict[str, Any],
    profiles: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    target_name = _target_name(target)
    target_result: dict[str, Any] = {
        "target_name": target_name,
        "target_type": str(target.get("TARGET_TYPE", "")),
        "repository": str(target.get("RESTIC_REPOSITORY", "")),
        "profile_results": [],
        "warnings": [],
        "errors": [],
        "status": "success",
    }

    preflight = validate_restic_preflight(global_config, target)
    target_result["warnings"].extend(preflight.warnings)
    if preflight.errors:
        target_result["errors"].extend(preflight.errors)
        target_result["status"] = "failure"
        target_result["warnings"] = _dedupe_messages(target_result["warnings"])
        target_result["errors"] = _dedupe_messages(target_result["errors"])
        return target_result

    try:
        initialized = repo_is_initialized(target, global_config)
    except OperationInterruptedError as exc:
        target_result["errors"].append(str(exc))
        target_result["warnings"] = _dedupe_messages(target_result["warnings"])
        target_result["errors"] = _dedupe_messages(target_result["errors"])
        target_result["status"] = "interrupted"
        target_result["interrupted"] = True
        return target_result
    except RuntimeError as exc:
        target_result["errors"].append(str(exc))
        target_result["status"] = "failure"
        target_result["warnings"] = _dedupe_messages(target_result["warnings"])
        target_result["errors"] = _dedupe_messages(target_result["errors"])
        return target_result

    if not initialized:
        target_result["errors"].append(
            f"Repository is not initialized yet for target {target_name}. Run sudo server-backup repo init {target_name}."
        )
        target_result["status"] = "failure"
        target_result["warnings"] = _dedupe_messages(target_result["warnings"])
        target_result["errors"] = _dedupe_messages(target_result["errors"])
        return target_result

    restic_env = build_restic_env(global_config, target)

    for profile in profiles:
        profile_validation = validate_profile_config(profile)
        path_validation = validate_backup_paths(profile)
        profile_name = _profile_name(profile)
        profile_result: dict[str, Any] = {
            "profile_name": profile_name,
            "profile_type": str(profile.get("PROFILE_TYPE", "")),
            "status": "success",
            "paths_requested": normalize_backup_paths(profile),
            "paths_included": path_validation["existing_paths"],
            "paths_missing": path_validation["missing_paths"],
            "excludes": normalize_excludes(profile),
            "tags": build_backup_tags(global_config, profile),
            "command_summary": "",
            "stdout": "",
            "stderr": "",
            "warnings": [],
            "errors": [],
            "interrupted": False,
            "database_dumps": [],
            "database_dump_dir": "",
        }
        profile_result["warnings"].extend(profile_validation.warnings)
        profile_result["warnings"].extend(path_validation["warnings"])

        if profile_validation.errors:
            profile_result["errors"].extend(profile_validation.errors)
            profile_result["status"] = "failure"
            profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
            profile_result["errors"] = _dedupe_messages(profile_result["errors"])
            target_result["profile_results"].append(profile_result)
            continue

        if path_validation["errors"]:
            profile_result["errors"].extend(path_validation["errors"])
            profile_result["status"] = "failure"
            profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
            profile_result["errors"] = _dedupe_messages(profile_result["errors"])
            target_result["profile_results"].append(profile_result)
            continue

        dump_dir: Path | None = None
        dump_paths: list[str] = []
        effective_excludes = normalize_excludes(profile)

        try:
            database_dumps = _filter_profile_database_dumps(profile)
        except ValueError as exc:
            profile_result["errors"].append(str(exc))
            profile_result["status"] = "failure"
            profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
            profile_result["errors"] = _dedupe_messages(profile_result["errors"])
            target_result["profile_results"].append(profile_result)
            continue

        try:
            if database_dumps:
                dump_dir = _create_profile_dump_dir(global_config, target_name, profile_name)
                profile_result["database_dump_dir"] = str(dump_dir)

                for dump_spec in database_dumps:
                    dump_name = str(dump_spec.get("name", "<unknown>"))
                    dump_output_dir = dump_dir / _safe_name_for_path(dump_name)
                    print(
                        f"Running database dump {'dry-run ' if dry_run else ''}"
                        f"for target {target_name}, profile {profile_name}, dump {dump_name}."
                    )
                    try:
                        dump_result = run_database_dump(dump_spec, dump_output_dir)
                    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
                        dump_result = {
                            "name": dump_name,
                            "engine": str(dump_spec.get("engine", "")),
                            "mode": str(dump_spec.get("mode", "")),
                            "output_dir": str(dump_output_dir),
                            "files": [],
                            "warnings": [],
                            "errors": [str(exc)],
                            "status": "failure",
                            "commands": [],
                        }

                    dump_result["warnings"] = _dedupe_messages(list(dump_result.get("warnings", [])))
                    dump_result["errors"] = _dedupe_messages(list(dump_result.get("errors", [])))
                    profile_result["database_dumps"].append(dump_result)
                    profile_result["warnings"].extend(dump_result["warnings"])

                    if dump_result.get("status") == "failure":
                        profile_result["errors"].extend(
                            f"Database dump {dump_name} failed: {message}"
                            for message in dump_result.get("errors", [])
                        )
                        continue

                    for dump_file in dump_result.get("files", []):
                        if _path_exists(dump_file):
                            dump_paths.append(str(dump_file))
                        else:
                            profile_result["warnings"].append(
                                f"Database dump {dump_name} declared a missing dump file: {dump_file}"
                            )

                if not profile_result["errors"] and not dump_paths:
                    profile_result["errors"].append(
                        f"{profile_name}: DATABASE_DUMPS are configured but produced no dump files"
                    )

                if dump_dir is not None and dump_paths:
                    effective_excludes = [
                        exclude
                        for exclude in effective_excludes
                        if not _exclude_covers_path(exclude, dump_dir)
                    ]

            if profile_result["errors"]:
                profile_result["status"] = "failure"
                profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
                profile_result["errors"] = _dedupe_messages(profile_result["errors"])
                target_result["profile_results"].append(profile_result)
                continue

            effective_profile = dict(profile)
            effective_profile["EXCLUDES"] = effective_excludes
            effective_profile["__resolved_backup_paths__"] = path_validation["existing_paths"] + dump_paths
            backup_args = build_restic_backup_args(global_config, effective_profile, dry_run=dry_run)
            command = build_restic_base_command(target) + backup_args
            profile_result["command_summary"] = _format_command(command)
            profile_result["excludes"] = effective_excludes
            profile_result["paths_included"] = path_validation["existing_paths"] + dump_paths
            mode_label = "dry-run" if dry_run else "backup"
            print(
                f"Running restic backup {mode_label} for target {target_name}, "
                f"profile {profile_name}. This may take several minutes..."
            )

            completed = run_restic_command(command, restic_env)
            profile_result["stdout"] = _sanitize_command_output(completed.stdout or "")
            profile_result["stderr"] = _sanitize_command_output(completed.stderr or "")
            if completed.returncode != 0:
                profile_result["errors"].append(explain_restic_failure(completed))

            profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
            profile_result["errors"] = _dedupe_messages(profile_result["errors"])
            profile_result["status"] = _status_from_parts(
                profile_result["errors"],
                profile_result["warnings"],
            )
            target_result["profile_results"].append(profile_result)
        except OperationInterruptedError as exc:
            profile_result["errors"].append(str(exc))
            profile_result["status"] = "interrupted"
            profile_result["warnings"] = _dedupe_messages(profile_result["warnings"])
            profile_result["errors"] = _dedupe_messages(profile_result["errors"])
            target_result["profile_results"].append(profile_result)
            target_result["errors"].append(str(exc))
            target_result["warnings"] = _dedupe_messages(target_result["warnings"])
            target_result["errors"] = _dedupe_messages(target_result["errors"])
            target_result["status"] = "interrupted"
            target_result["interrupted"] = True
            return target_result
        finally:
            _cleanup_dump_dir(dump_dir)

    target_result["warnings"] = _dedupe_messages(target_result["warnings"])
    target_result["errors"] = _dedupe_messages(target_result["errors"])
    target_result["status"] = _aggregate_status(target_result["profile_results"])
    if target_result["errors"]:
        target_result["status"] = "failure"
    elif target_result["warnings"] and target_result["status"] == "success":
        target_result["status"] = "warning"
    return target_result


def run_backup_all_targets(
    global_config: dict[str, Any],
    targets: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    target_results: list[dict[str, Any]] = []
    interrupted = False
    for target in targets:
        target_result = run_backup_for_target(global_config, target, profiles, dry_run=dry_run)
        target_results.append(target_result)
        if target_result.get("interrupted"):
            interrupted = True
            break
    warnings: list[str] = []
    errors: list[str] = []
    for target_result in target_results:
        warnings.extend(target_result.get("warnings", []))
        errors.extend(target_result.get("errors", []))
    return {
        "status": "interrupted" if interrupted else _aggregate_status(target_results),
        "target_results": target_results,
        "warnings": _dedupe_messages(warnings),
        "errors": _dedupe_messages(errors),
        "interrupted": interrupted,
    }


def render_backup_report_text(report: dict[str, Any]) -> str:
    safe_report = redact_config(report)
    lines = [
        "server-backup backup run report",
        "",
        f"Hostname: {safe_report.get('hostname', '')}",
        f"BACKUP_NAME: {safe_report.get('backup_name', '')}",
        f"Start: {safe_report.get('start_time', '')}",
        f"End: {safe_report.get('end_time', '')}",
        f"Duration: {safe_report.get('duration_seconds', 0):.2f}s",
        f"Dry-run: {'yes' if safe_report.get('dry_run') else 'no'}",
        f"Interrupted: {'yes' if safe_report.get('interrupted') else 'no'}",
        f"Overall: {safe_report.get('status', 'failure').upper()}",
        "",
        f"Targets: {safe_report.get('targets_requested', 0)}",
        f"Profiles: {safe_report.get('profiles_requested', 0)}",
        "",
    ]

    if safe_report.get("warnings"):
        lines.append("Warnings:")
        for warning in safe_report["warnings"]:
            lines.append(f"  - {warning}")
        lines.append("")

    if safe_report.get("errors"):
        lines.append("Errors:")
        for error in safe_report["errors"]:
            lines.append(f"  - {error}")
        lines.append("")

    if safe_report.get("email_report"):
        email_report = safe_report["email_report"]
        lines.append("Email report:")
        lines.append(f"  attempted: {'yes' if email_report.get('attempted') else 'no'}")
        lines.append(f"  success: {'yes' if email_report.get('success') else 'no'}")
        if email_report.get("to"):
            lines.append(f"  to: {email_report.get('to')}")
        if email_report.get("subject"):
            lines.append(f"  subject: {email_report.get('subject')}")
        if email_report.get("error"):
            lines.append(f"  error: {email_report.get('error')}")
        lines.append("")

    for target_result in safe_report.get("target_results", []):
        lines.append(
            f"Target {target_result.get('target_name', '<unknown>')} [{str(target_result.get('status', 'failure')).upper()}]"
        )
        lines.append(f"  Repository: {target_result.get('repository', '')}")
        for warning in target_result.get("warnings", []):
            lines.append(f"  Warning: {warning}")
        for error in target_result.get("errors", []):
            lines.append(f"  Error: {error}")

        for profile_result in target_result.get("profile_results", []):
            lines.append(
                f"  Profile {profile_result.get('profile_name', '<unknown>')} "
                f"[{str(profile_result.get('status', 'failure')).upper()}]"
            )
            lines.append(f"    Type: {profile_result.get('profile_type', '')}")
            lines.append(
                f"    Paths included: {', '.join(profile_result.get('paths_included', [])) or '<none>'}"
            )
            lines.append(
                f"    Paths missing: {', '.join(profile_result.get('paths_missing', [])) or '<none>'}"
            )
            lines.append(
                f"    Excludes: {', '.join(profile_result.get('excludes', [])) or '<none>'}"
            )
            lines.append(
                f"    Tags: {', '.join(profile_result.get('tags', [])) or '<none>'}"
            )
            if profile_result.get("database_dumps"):
                lines.append("    Database dumps:")
                for dump_result in profile_result.get("database_dumps", []):
                    lines.append(
                        f"      - {dump_result.get('name', '<unknown>')} "
                        f"[{str(dump_result.get('status', 'failure')).upper()}]"
                    )
                    if dump_result.get("files"):
                        lines.append(
                            f"        files: {', '.join(dump_result.get('files', []))}"
                        )
                    for warning in dump_result.get("warnings", []):
                        lines.append(f"        warning: {warning}")
                    for error in dump_result.get("errors", []):
                        lines.append(f"        error: {error}")
            if profile_result.get("command_summary"):
                lines.append(f"    Command: {profile_result['command_summary']}")
            for warning in profile_result.get("warnings", []):
                lines.append(f"    Warning: {warning}")
            for error in profile_result.get("errors", []):
                lines.append(f"    Error: {error}")
            if profile_result.get("stdout"):
                lines.append("    stdout:")
                for line in str(profile_result["stdout"]).splitlines():
                    lines.append(f"      {line}")
            if profile_result.get("stderr"):
                lines.append("    stderr:")
                for line in str(profile_result["stderr"]).splitlines():
                    lines.append(f"      {line}")
        lines.append("")

    if safe_report.get("text_report_path") or safe_report.get("json_report_path"):
        lines.append("Reports:")
        if safe_report.get("text_report_path"):
            lines.append(f"  {safe_report['text_report_path']}")
        if safe_report.get("json_report_path"):
            lines.append(f"  {safe_report['json_report_path']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_backup_report_json(report: dict[str, Any]) -> str:
    return json.dumps(redact_config(report), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def write_backup_report(report: dict[str, Any], report_dir: str | Path) -> dict[str, str]:
    report_path = Path(report_dir)
    state_dir = Path(str(report.get("state_dir") or DEFAULT_STATE_DIR))
    report_path.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    existing_text_path = str(report.get("text_report_path", "")).strip()
    existing_json_path = str(report.get("json_report_path", "")).strip()
    if existing_text_path and existing_json_path:
        text_path = Path(existing_text_path)
        json_path = Path(existing_json_path)
    else:
        stamp = _report_stamp()
        text_path = report_path / f"backup-run-{stamp}.txt"
        json_path = report_path / f"backup-run-{stamp}.json"

    report["text_report_path"] = str(text_path)
    report["json_report_path"] = str(json_path)

    text_path.write_text(render_backup_report_text(report), encoding="utf-8")
    json_path.write_text(render_backup_report_json(report), encoding="utf-8")

    last_run_path = state_dir / LAST_BACKUP_RUN_FILE
    last_run_payload = {
        "hostname": report.get("hostname", ""),
        "backup_name": report.get("backup_name", ""),
        "start_time": report.get("start_time", ""),
        "end_time": report.get("end_time", ""),
        "duration_seconds": report.get("duration_seconds", 0),
        "dry_run": bool(report.get("dry_run")),
        "interrupted": bool(report.get("interrupted")),
        "status": report.get("status", "failure"),
        "targets_requested": report.get("targets_requested", 0),
        "profiles_requested": report.get("profiles_requested", 0),
        "warnings": report.get("warnings", []),
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "email_report": report.get("email_report", {}),
    }
    last_run_path.write_text(
        json.dumps(last_run_payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "last_run_path": str(last_run_path),
    }


def run_backup(
    dry_run: bool = False,
    target_name: str | None = None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    start = datetime.now(UTC)
    report: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "backup_name": "",
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": "",
        "duration_seconds": 0.0,
        "dry_run": dry_run,
        "status": "failure",
        "targets_requested": 0,
        "profiles_requested": 0,
        "target_results": [],
        "warnings": [],
        "errors": [],
        "interrupted": False,
        "text_report_path": "",
        "json_report_path": "",
        "state_dir": str(DEFAULT_STATE_DIR),
    }

    global_config, targets, profiles = load_backup_context()
    report["backup_name"] = str(global_config.get("BACKUP_NAME", "")).strip()
    report["state_dir"] = str(global_config.get("STATE_DIR") or DEFAULT_STATE_DIR)
    report_dir = Path(str(global_config.get("REPORT_DIR") or DEFAULT_REPORT_DIR))

    global_validation = validate_global_config(global_config)
    report["warnings"].extend(global_validation.warnings)
    if global_validation.errors:
        report["errors"].extend(global_validation.errors)
    elif global_config.get("__missing__"):
        report["errors"].append("backup.conf is missing. Run sudo server-backup setup first.")

    selected_targets: list[dict[str, Any]] = []
    selected_profiles: list[dict[str, Any]] = []

    if not report["errors"]:
        try:
            selected_targets = collect_targets(targets, target_name=target_name)
        except ValueError as exc:
            report["errors"].append(str(exc))

    if not report["errors"]:
        try:
            selected_profiles = collect_profiles(profiles, profile_name=profile_name)
        except ValueError as exc:
            report["errors"].append(str(exc))

    report["targets_requested"] = len(selected_targets)
    report["profiles_requested"] = len(selected_profiles)

    if not report["errors"]:
        try:
            with restic_repo_lock(timeout_seconds=30):
                backup_result = run_backup_all_targets(
                    global_config,
                    selected_targets,
                    selected_profiles,
                    dry_run=dry_run,
                )
        except RuntimeError as exc:
            report["errors"].append(str(exc))
        else:
            report["target_results"] = backup_result["target_results"]
            report["warnings"].extend(backup_result["warnings"])
            report["errors"].extend(backup_result["errors"])
            report["status"] = backup_result["status"]
            report["interrupted"] = bool(backup_result.get("interrupted"))

    report["warnings"] = _dedupe_messages(report["warnings"])
    report["errors"] = _dedupe_messages(report["errors"])
    if report.get("interrupted"):
        if INTERRUPTED_MESSAGE not in report["errors"]:
            report["errors"].append(INTERRUPTED_MESSAGE)
            report["errors"] = _dedupe_messages(report["errors"])
        report["status"] = "interrupted"
    elif report["status"] != "failure":
        report["status"] = _status_from_parts(report["errors"], report["warnings"])

    end = datetime.now(UTC)
    report["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    report["duration_seconds"] = round((end - start).total_seconds(), 3)

    paths = write_backup_report(report, report_dir)
    report.update(paths)

    if report.get("text_report_path") and not report.get("interrupted"):
        text_path = Path(str(report["text_report_path"]))
        report_text = text_path.read_text(encoding="utf-8") if text_path.exists() else render_backup_report_text(report)
        email_result = send_email_report("backup", str(report.get("status", "failure")), report_text, global_config)
        report["email_report"] = email_result
        if email_result.get("attempted") and not email_result.get("success"):
            report["warnings"].append(f"Email report failed: {email_result.get('error', 'unknown error')}")
        report["warnings"] = _dedupe_messages(report["warnings"])
        if report.get("status") != "failure":
            report["status"] = _status_from_parts(report["errors"], report["warnings"])
        write_backup_report(report, report_dir)
    return report
