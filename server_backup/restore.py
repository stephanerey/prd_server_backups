from __future__ import annotations

import gzip
import json
import shlex
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backup import collect_profiles, collect_targets, load_backup_context, normalize_backup_paths
from .config import redact_config
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
    validate_restic_preflight,
)


DEFAULT_REPORT_DIR = Path("/var/lib/server-backup/reports")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
LAST_RESTORE_TEST_FILE = "last-restore-test.json"
DEFAULT_RESTORE_PREFIX = "server-backup-restore-test-"
DANGEROUS_OUTPUT_DIRS = {
    "/",
    "/etc",
    "/srv",
    "/opt",
    "/var",
    "/var/lib",
    "/var/lib/docker",
    "/home",
    "/root",
}
COMPOSE_FILENAMES = {
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.override.yml",
}
DB_DUMP_SUFFIXES = (".dump", ".sql", ".sql.gz", ".backup")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _dedupe(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for message in messages:
        if not message or message in seen:
            continue
        deduped.append(message)
        seen.add(message)
    return deduped


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


def _sanitize_output(text: str) -> str:
    return text.replace("\x00", "").strip()


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _map_restored_path(output_dir: Path, source_path: str) -> Path:
    return output_dir / source_path.lstrip("/")


def _is_explicit_output_dir_safe(path: Path) -> bool:
    path_str = str(path)
    if path_str in DANGEROUS_OUTPUT_DIRS:
        return False
    return path_str.startswith("/tmp/")


def _can_cleanup_output_dir(path: Path, explicit_output: bool) -> bool:
    path_str = str(path)
    if path_str.startswith(f"/tmp/{DEFAULT_RESTORE_PREFIX}"):
        return True
    return explicit_output and _is_explicit_output_dir_safe(path)


def _validate_output_dir(path: Path, *, explicit_output: bool) -> None:
    path_str = str(path)
    if explicit_output:
        if path_str in DANGEROUS_OUTPUT_DIRS:
            raise ValueError(f"Refusing dangerous restore output directory: {path}")
        if not _is_explicit_output_dir_safe(path):
            raise ValueError("Explicit restore output directories must be absent and under /tmp.")
    if path.exists():
        raise ValueError(f"Restore output directory already exists: {path}")


def build_restore_output_dir(base_dir: str | Path = "/tmp") -> Path:
    base = Path(base_dir)
    stamp = _report_stamp()
    candidate = base / f"{DEFAULT_RESTORE_PREFIX}{stamp}"
    index = 1
    while candidate.exists():
        candidate = base / f"{DEFAULT_RESTORE_PREFIX}{stamp}-{index}"
        index += 1
    return candidate


def build_restic_restore_args(
    snapshot: str,
    output_dir: str | Path,
    includes: list[str] | None = None,
) -> list[str]:
    args = ["restore", snapshot, "--target", str(output_dir)]
    for include in includes or []:
        if str(include).strip():
            args.extend(["--include", str(include).strip()])
    return args


def validate_restore_preflight(global_config: dict[str, Any], target: dict[str, Any]):
    result = validate_restic_preflight(global_config, target)
    if result.errors:
        return result
    try:
        initialized = repo_is_initialized(target, global_config)
    except OperationInterruptedError:
        raise
    except RuntimeError as exc:
        result.add_error(str(exc))
        return result
    if not initialized:
        result.add_error(
            f"Repository is not initialized yet for target {target.get('TARGET_NAME', '<unknown>')}."
        )
    return result


def check_restored_files(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    result = {
        "output_dir_exists": root.exists(),
        "file_count": 0,
        "dir_count": 0,
        "total_size_bytes": 0,
        "status": "success",
        "warnings": [],
        "errors": [],
    }

    if not root.exists():
        result["errors"].append(f"Restore output directory was not created: {root}")
        result["status"] = "failure"
        return result

    entries = list(root.rglob("*"))
    if not entries:
        result["errors"].append(f"Restore output directory is empty: {root}")
        result["status"] = "failure"
        return result

    for entry in entries:
        try:
            if entry.is_dir():
                result["dir_count"] += 1
            elif entry.is_file():
                result["file_count"] += 1
                result["total_size_bytes"] += entry.stat().st_size
        except OSError as exc:
            result["warnings"].append(f"Could not inspect restored entry {entry}: {exc}")

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    result["status"] = _status_from_parts(result["errors"], result["warnings"])
    return result


def check_profile_expected_paths(output_dir: str | Path, profile: dict[str, Any]) -> dict[str, Any]:
    root = Path(output_dir)
    backup_paths = normalize_backup_paths(profile)
    found_paths: list[str] = []
    missing_paths: list[str] = []
    warnings: list[str] = []

    for backup_path in backup_paths:
        restored_path = _map_restored_path(root, backup_path)
        if restored_path.exists():
            found_paths.append(str(restored_path))
        else:
            missing_paths.append(backup_path)
            warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: restored path not found: {backup_path}")

    status = "success" if found_paths and not missing_paths else "warning"
    if not found_paths:
        status = "warning"

    return {
        "profile_name": str(profile.get("PROFILE_NAME", "<unknown>")),
        "profile_type": str(profile.get("PROFILE_TYPE", "")),
        "found_paths": found_paths,
        "missing_paths": missing_paths,
        "warnings": _dedupe(warnings),
        "errors": [],
        "status": status,
    }


def collect_restore_checks(
    output_dir: str | Path,
    profiles: list[dict[str, Any]],
    profile_name: str | None = None,
) -> list[dict[str, Any]]:
    if profile_name is not None:
        profiles = [profile for profile in profiles if str(profile.get("PROFILE_NAME", "")).strip() == profile_name]
    return [check_profile_expected_paths(output_dir, profile) for profile in profiles]


def _read_sql_preview(path: Path) -> str:
    if path.name.endswith(".sql.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as handle:
            return handle.read(65536)
    return path.read_text(encoding="utf-8", errors="ignore")[:65536]


def check_db_dump_files_if_present(output_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(output_dir)
    results: list[dict[str, Any]] = []
    pg_restore = shutil.which("pg_restore")

    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        if not any(entry.name.endswith(suffix) for suffix in DB_DUMP_SUFFIXES):
            continue

        dump_result = {
            "path": str(entry),
            "status": "success",
            "warnings": [],
            "errors": [],
        }

        try:
            if entry.suffix in {".dump", ".backup"}:
                if not pg_restore:
                    dump_result["warnings"].append("pg_restore not available; PostgreSQL custom dump readability not checked.")
                else:
                    completed = subprocess.run(
                        [pg_restore, "--list", str(entry)],
                        check=False,
                        capture_output=True,
                        text=True,
                        shell=False,
                    )
                    if completed.returncode != 0:
                        dump_result["errors"].append(
                            _sanitize_output(completed.stderr or completed.stdout or f"pg_restore --list failed for {entry}")
                        )
            else:
                if entry.stat().st_size == 0:
                    dump_result["errors"].append(f"SQL dump file is empty: {entry}")
                else:
                    preview = _read_sql_preview(entry).upper()
                    if not any(token in preview for token in ("CREATE", "INSERT", "COPY")):
                        dump_result["warnings"].append(f"SQL dump does not contain expected SQL keywords near the beginning: {entry}")
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            dump_result["errors"].append(f"Could not inspect dump file {entry}: {exc}")

        dump_result["warnings"] = _dedupe(dump_result["warnings"])
        dump_result["errors"] = _dedupe(dump_result["errors"])
        dump_result["status"] = _status_from_parts(dump_result["errors"], dump_result["warnings"])
        results.append(dump_result)

    return results


def check_cis_files_if_present(output_dir: str | Path, profile: dict[str, Any]) -> dict[str, Any]:
    root = Path(output_dir)
    warnings: list[str] = []
    checks: list[str] = []
    app_kind = str(profile.get("APP_KIND", "")).strip()
    profile_type = str(profile.get("PROFILE_TYPE", "")).strip()
    if app_kind != "cis-site" and profile_type != "cis-site":
        return {
            "profile_name": str(profile.get("PROFILE_NAME", "<unknown>")),
            "status": "success",
            "warnings": [],
            "errors": [],
            "checks": [],
        }

    backup_paths = normalize_backup_paths(profile)
    frontend_candidates = [path for path in backup_paths if "/frontend" in path]
    backend_candidates = [path for path in backup_paths if "/backend" in path]
    migration_candidates = [path for path in backup_paths if "/alembic" in path or "/migrations" in path]

    for label, candidates in (
        ("frontend", frontend_candidates),
        ("backend", backend_candidates),
        ("migrations", migration_candidates),
    ):
        if not candidates:
            warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: no {label} path declared in BACKUP_PATHS")
            continue
        restored_any = any(_map_restored_path(root, candidate).exists() for candidate in candidates)
        if restored_any:
            checks.append(f"{label} present")
        else:
            warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: {label} path not found in restored output")

    compose_found = any(path.name in COMPOSE_FILENAMES for path in root.rglob("*") if path.is_file())
    if compose_found:
        checks.append("compose file present")
    else:
        warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: no compose file found in restored output")

    content_classification = profile.get("CONTENT_CLASSIFICATION", [])
    if isinstance(content_classification, list) and content_classification:
        checks.append("CONTENT_CLASSIFICATION present")
        if any("site_pages" in str(entry) for entry in content_classification):
            checks.append("site_pages declared in CONTENT_CLASSIFICATION")
        else:
            warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: site_pages not found in CONTENT_CLASSIFICATION")
    else:
        warnings.append(f"{profile.get('PROFILE_NAME', '<unknown>')}: CONTENT_CLASSIFICATION missing")

    return {
        "profile_name": str(profile.get("PROFILE_NAME", "<unknown>")),
        "status": "warning" if warnings else "success",
        "warnings": _dedupe(warnings),
        "errors": [],
        "checks": checks,
    }


def _is_cis_profile(profile: dict[str, Any]) -> bool:
    return str(profile.get("APP_KIND", "")).strip() == "cis-site" or str(profile.get("PROFILE_TYPE", "")).strip() == "cis-site"


def _check_included_paths(output_dir: Path, includes: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for include in includes:
        restored_path = _map_restored_path(output_dir, include)
        found = restored_path.exists()
        checks.append(
            {
                "include": include,
                "restored_path": str(restored_path),
                "status": "success" if found else "warning",
                "warnings": [] if found else [f"Included path not found in restored output: {include}"],
                "errors": [],
            }
        )
    return checks


def _extract_restored_snapshot_id(snapshot: str, stdout: str, stderr: str) -> str:
    if snapshot != "latest":
        return snapshot
    combined = f"{stdout}\n{stderr}"
    for token in combined.replace(",", " ").split():
        lowered = token.strip().lower()
        if len(lowered) >= 8 and all(char in "0123456789abcdef" for char in lowered[:8]):
            return lowered
    return snapshot


def render_restore_report_text(report: dict[str, Any]) -> str:
    safe_report = redact_config(report)
    lines = [
        "server-backup restore test report",
        "",
        f"Hostname: {safe_report.get('hostname', '')}",
        f"BACKUP_NAME: {safe_report.get('backup_name', '')}",
        f"Start: {safe_report.get('start_time', '')}",
        f"End: {safe_report.get('end_time', '')}",
        f"Duration: {safe_report.get('duration_seconds', 0):.2f}s",
        f"Interrupted: {'yes' if safe_report.get('interrupted') else 'no'}",
        f"Target: {safe_report.get('target_name', '')}",
        f"Requested snapshot: {safe_report.get('requested_snapshot', '')}",
        f"Restored snapshot: {safe_report.get('restored_snapshot', '')}",
        f"Output dir: {safe_report.get('output_dir', '')}",
        f"Keep output: {'yes' if safe_report.get('keep_output') else 'no'}",
        f"Output cleaned: {'yes' if safe_report.get('output_cleaned') else 'no'}",
        f"Profile: {safe_report.get('profile_name', '') or '<all>'}",
        f"Includes: {', '.join(safe_report.get('includes', [])) or '<none>'}",
        f"Files restored: {safe_report.get('restored_files', {}).get('file_count', 0)}",
        f"Approx size: {safe_report.get('restored_files', {}).get('total_size_bytes', 0)} bytes",
        f"Overall: {str(safe_report.get('status', 'failure')).upper()}",
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

    if safe_report.get("command_summary"):
        lines.append(f"Command: {safe_report['command_summary']}")
        lines.append("")

    if safe_report.get("stdout"):
        lines.append("stdout:")
        for line in str(safe_report["stdout"]).splitlines():
            lines.append(f"  {line}")
        lines.append("")

    if safe_report.get("stderr"):
        lines.append("stderr:")
        for line in str(safe_report["stderr"]).splitlines():
            lines.append(f"  {line}")
        lines.append("")

    if safe_report.get("include_checks"):
        lines.append("Include checks:")
        for check in safe_report["include_checks"]:
            lines.append(f"  - {check.get('include')}: {str(check.get('status', 'failure')).upper()}")
        lines.append("")

    if safe_report.get("profile_checks"):
        lines.append("Profile checks:")
        for check in safe_report["profile_checks"]:
            lines.append(f"  - {check.get('profile_name')}: {str(check.get('status', 'failure')).upper()}")
            for warning in check.get("warnings", []):
                lines.append(f"    warning: {warning}")
        lines.append("")

    if safe_report.get("db_checks"):
        lines.append("DB dump checks:")
        for check in safe_report["db_checks"]:
            lines.append(f"  - {check.get('path')}: {str(check.get('status', 'failure')).upper()}")
        lines.append("")

    if safe_report.get("cis_checks"):
        lines.append("CIS checks:")
        for check in safe_report["cis_checks"]:
            lines.append(f"  - {check.get('profile_name')}: {str(check.get('status', 'failure')).upper()}")
        lines.append("")

    if safe_report.get("text_report_path") or safe_report.get("json_report_path"):
        lines.append("Reports:")
        if safe_report.get("text_report_path"):
            lines.append(f"  {safe_report['text_report_path']}")
        if safe_report.get("json_report_path"):
            lines.append(f"  {safe_report['json_report_path']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_restore_report_json(report: dict[str, Any]) -> str:
    return json.dumps(redact_config(report), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def update_last_restore_test(report: dict[str, Any]) -> str | None:
    if str(report.get("status", "failure")) == "failure":
        return None
    state_dir = Path(str(report.get("state_dir") or DEFAULT_STATE_DIR))
    state_dir.mkdir(parents=True, exist_ok=True)
    last_path = state_dir / LAST_RESTORE_TEST_FILE
    payload = {
        "hostname": report.get("hostname", ""),
        "backup_name": report.get("backup_name", ""),
        "start_time": report.get("start_time", ""),
        "end_time": report.get("end_time", ""),
        "duration_seconds": report.get("duration_seconds", 0),
        "target_name": report.get("target_name", ""),
        "requested_snapshot": report.get("requested_snapshot", ""),
        "restored_snapshot": report.get("restored_snapshot", ""),
        "output_dir": report.get("output_dir", ""),
        "keep_output": bool(report.get("keep_output")),
        "status": report.get("status", "failure"),
        "interrupted": bool(report.get("interrupted")),
        "warnings": report.get("warnings", []),
        "text_report_path": report.get("text_report_path", ""),
        "json_report_path": report.get("json_report_path", ""),
        "email_report": report.get("email_report", {}),
    }
    last_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    return str(last_path)


def write_restore_report(report: dict[str, Any], report_dir: str | Path) -> dict[str, str]:
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    existing_text_path = str(report.get("text_report_path", "")).strip()
    existing_json_path = str(report.get("json_report_path", "")).strip()
    if existing_text_path and existing_json_path:
        text_path = Path(existing_text_path)
        json_path = Path(existing_json_path)
    else:
        stamp = _report_stamp()
        text_path = report_path / f"restore-test-{stamp}.txt"
        json_path = report_path / f"restore-test-{stamp}.json"
    report["text_report_path"] = str(text_path)
    report["json_report_path"] = str(json_path)
    text_path.write_text(render_restore_report_text(report), encoding="utf-8")
    json_path.write_text(render_restore_report_json(report), encoding="utf-8")
    return {"text_report_path": str(text_path), "json_report_path": str(json_path)}


def run_restore_test(
    target: str,
    snapshot: str = "latest",
    profile_name: str | None = None,
    includes: list[str] | None = None,
    output_dir: str | None = None,
    keep_output: bool = False,
) -> dict[str, Any]:
    start = datetime.now(UTC)
    includes = [value.strip() for value in (includes or []) if str(value).strip()]
    global_config, targets, profiles = load_backup_context()

    report: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": "",
        "duration_seconds": 0.0,
        "target_name": target,
        "requested_snapshot": snapshot or "latest",
        "restored_snapshot": snapshot or "latest",
        "output_dir": "",
        "keep_output": keep_output,
        "output_cleaned": False,
        "profile_name": profile_name or "",
        "includes": includes,
        "command_summary": "",
        "stdout": "",
        "stderr": "",
        "restored_files": {},
        "include_checks": [],
        "profile_checks": [],
        "db_checks": [],
        "cis_checks": [],
        "warnings": [],
        "errors": [],
        "status": "failure",
        "interrupted": False,
        "state_dir": str(global_config.get("STATE_DIR", DEFAULT_STATE_DIR)),
    }

    explicit_output = output_dir is not None
    restore_invoked = False
    chosen_output = Path(output_dir) if output_dir is not None else build_restore_output_dir("/tmp")
    report["output_dir"] = str(chosen_output)

    try:
        selected_targets = collect_targets(targets, target_name=target)
        selected_profiles = collect_profiles(profiles, profile_name=profile_name) if profile_name else profiles
    except ValueError as exc:
        report["errors"].append(str(exc))
        selected_targets = []
        selected_profiles = []

    try:
        _validate_output_dir(chosen_output, explicit_output=explicit_output)
    except ValueError as exc:
        report["errors"].append(str(exc))

    if selected_targets:
        target_config = selected_targets[0]
        try:
            preflight = validate_restore_preflight(global_config, target_config)
        except OperationInterruptedError as exc:
            report["errors"].append(str(exc))
            report["interrupted"] = True
            preflight = None
        if preflight is not None:
            report["warnings"].extend(preflight.warnings)
            report["errors"].extend(preflight.errors)
    else:
        target_config = None

    if not report["errors"] and target_config is not None:
        env = build_restic_env(global_config, target_config)
        command = build_restic_base_command(target_config) + build_restic_restore_args(
            report["requested_snapshot"],
            chosen_output,
            includes=includes,
        )
        report["command_summary"] = _format_command(command)

        try:
            with restic_repo_lock(timeout_seconds=30):
                restore_invoked = True
                completed = run_restic_command(command, env)
        except RuntimeError as exc:
            report["errors"].append(str(exc))
            if isinstance(exc, OperationInterruptedError):
                report["interrupted"] = True
        else:
            report["stdout"] = _sanitize_output(completed.stdout or "")
            report["stderr"] = _sanitize_output(completed.stderr or "")
            report["restored_snapshot"] = _extract_restored_snapshot_id(
                report["requested_snapshot"],
                report["stdout"],
                report["stderr"],
            )
            if completed.returncode != 0:
                report["errors"].append(explain_restic_failure(completed))
            else:
                report["restored_files"] = check_restored_files(chosen_output)
                report["warnings"].extend(report["restored_files"].get("warnings", []))
                report["errors"].extend(report["restored_files"].get("errors", []))

                if includes:
                    report["include_checks"] = _check_included_paths(chosen_output, includes)
                    for check in report["include_checks"]:
                        report["warnings"].extend(check.get("warnings", []))
                        report["errors"].extend(check.get("errors", []))
                else:
                    report["profile_checks"] = collect_restore_checks(chosen_output, selected_profiles, profile_name=profile_name)
                    for check in report["profile_checks"]:
                        report["warnings"].extend(check.get("warnings", []))
                        report["errors"].extend(check.get("errors", []))

                    report["db_checks"] = check_db_dump_files_if_present(chosen_output)
                    for check in report["db_checks"]:
                        report["warnings"].extend(check.get("warnings", []))
                        report["errors"].extend(check.get("errors", []))

                    report["cis_checks"] = [
                        check_cis_files_if_present(chosen_output, profile)
                        for profile in selected_profiles
                        if _is_cis_profile(profile)
                    ]
                    for check in report["cis_checks"]:
                        report["warnings"].extend(check.get("warnings", []))
                        report["errors"].extend(check.get("errors", []))

    report["warnings"] = _dedupe(report["warnings"])
    report["errors"] = _dedupe(report["errors"])

    if report.get("interrupted"):
        if INTERRUPTED_MESSAGE not in report["errors"]:
            report["errors"].append(INTERRUPTED_MESSAGE)
        report["status"] = "interrupted"
    elif not report["errors"]:
        child_statuses: list[dict[str, Any]] = []
        child_statuses.extend(report.get("include_checks", []))
        child_statuses.extend(report.get("profile_checks", []))
        child_statuses.extend(report.get("db_checks", []))
        child_statuses.extend(report.get("cis_checks", []))
        if child_statuses:
            report["status"] = _aggregate_status(child_statuses)
        else:
            report["status"] = _status_from_parts(report["errors"], report["warnings"])
    if not report.get("interrupted"):
        report["status"] = _status_from_parts(report["errors"], report["warnings"]) if report["errors"] or report["warnings"] else report.get("status", "success")
    if not report.get("interrupted") and not report["errors"] and any(collection for collection in (report.get("include_checks"), report.get("profile_checks"), report.get("db_checks"), report.get("cis_checks"))):
        statuses = []
        statuses.extend(report.get("include_checks", []))
        statuses.extend(report.get("profile_checks", []))
        statuses.extend(report.get("db_checks", []))
        statuses.extend(report.get("cis_checks", []))
        report["status"] = _aggregate_status(statuses)
    elif not report.get("interrupted") and not report["errors"] and not report["warnings"]:
        report["status"] = "success"

    cleanup_warning: str | None = None
    if restore_invoked and chosen_output.exists() and not keep_output:
        if _can_cleanup_output_dir(chosen_output, explicit_output):
            try:
                shutil.rmtree(chosen_output)
                report["output_cleaned"] = True
            except OSError as exc:
                cleanup_warning = f"Could not remove restore output directory {chosen_output}: {exc}"
        else:
            cleanup_warning = f"Restore output directory not removed because it is outside the allowed cleanup scope: {chosen_output}"

    if cleanup_warning:
        report["warnings"].append(cleanup_warning)
        report["warnings"] = _dedupe(report["warnings"])
        if report["status"] == "success":
            report["status"] = "warning"

    end = datetime.now(UTC)
    report["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    report["duration_seconds"] = round((end - start).total_seconds(), 3)
    report_dir = str(global_config.get("REPORT_DIR", DEFAULT_REPORT_DIR))
    report.update(write_restore_report(report, report_dir))
    if report.get("text_report_path") and not report.get("interrupted"):
        text_path = Path(str(report["text_report_path"]))
        report_text = text_path.read_text(encoding="utf-8") if text_path.exists() else render_restore_report_text(report)
        email_result = send_email_report("restore-test", str(report.get("status", "failure")), report_text, global_config)
        report["email_report"] = email_result
        if email_result.get("attempted") and not email_result.get("success"):
            report["warnings"].append(f"Email report failed: {email_result.get('error', 'unknown error')}")
        report["warnings"] = _dedupe(report["warnings"])
        if report.get("status") != "failure":
            report["status"] = _status_from_parts(report["errors"], report["warnings"])
        report.update(write_restore_report(report, report_dir))
    last_path = update_last_restore_test(report)
    if last_path:
        report["last_restore_test_path"] = last_path
    return report
