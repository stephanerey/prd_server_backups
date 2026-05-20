from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backup import run_backup
from .config import load_global_config, load_profiles, load_targets, redact_config
from .coverage import run_coverage_audit
from .db import list_database_dumps, load_database_dumps_from_profiles, test_database_connection
from .email_report import redact_sensitive_lines, send_test_email
from .health import build_operations_status, run_health_check
from .restic import (
    OperationInterruptedError,
    check_repository,
    explain_restic_failure,
    list_snapshots,
    restic_repo_lock,
    select_target,
    validate_restic_preflight,
)
from .restore import run_restore_test
from .validators import validate_all


DEFAULT_BACKUP_CONF = Path("/etc/server-backup/backup.conf")
DEFAULT_TARGETS_DIR = Path("/etc/server-backup/targets.d")
DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_REPORT_DIR = Path("/var/lib/server-backup/reports")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
LAST_PRODUCTION_VALIDATION_FILE = "last-production-validation.json"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _status_from_checks(checks: list[dict[str, Any]]) -> str:
    statuses = {str(check.get("status", "success")).lower() for check in checks}
    statuses.discard("skipped")
    if "failure" in statuses:
        return "failure"
    if "warning" in statuses:
        return "warning"
    return "success"


def _make_check(name: str, status: str, summary: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "summary": summary,
    }
    payload.update(extra)
    return payload


def _redact_sensitive_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_sensitive_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_strings(item) for item in value]
    if isinstance(value, str):
        redacted = redact_sensitive_lines(value)
        return redacted if redacted == value else "<redacted>"
    return value


def _select_target_for_validation(target_name: str | None, targets: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if target_name:
        return select_target(target_name, targets), warnings
    if len(targets) == 1:
        return targets[0], warnings
    if not targets:
        warnings.append("No target is configured; target-specific checks were skipped.")
    else:
        warnings.append("Multiple targets are configured; target-specific checks were skipped because --target was not provided.")
    return None, warnings


def check_config_validate(global_config: dict[str, Any], targets: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    result = validate_all(global_config, targets, profiles)
    status = "failure" if result.errors else ("warning" if result.warnings else "success")
    summary = "Configuration validation passed."
    if result.errors:
        summary = f"Configuration validation found {len(result.errors)} error(s)."
    elif result.warnings:
        summary = f"Configuration validation found {len(result.warnings)} warning(s)."
    return _make_check(
        "config-validate",
        status,
        summary,
        errors=result.errors,
        warnings=result.warnings,
    )


def check_health(global_config: dict[str, Any], targets: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    report = run_health_check(global_config, targets, profiles)
    summary = f"Health status is {str(report.get('status', 'failure')).upper()}."
    return _make_check(
        "health",
        str(report.get("status", "failure")).lower(),
        summary,
        report=report,
    )


def check_operations_status(global_config: dict[str, Any], targets: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    report = build_operations_status(global_config, targets, profiles)
    status = "warning" if report.get("warnings") else "success"
    summary = f"Operations status loaded with {len(report.get('warnings', []))} warning(s)."
    return _make_check(
        "operations-status",
        status,
        summary,
        report=report,
        warnings=report.get("warnings", []),
    )


def check_repo_snapshots(global_config: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        return _make_check("repo-snapshots", "skipped", "Repository snapshot check skipped because no target was selected.")

    preflight = validate_restic_preflight(global_config, target)
    if preflight.errors:
        return _make_check("repo-snapshots", "failure", "Restic preflight failed for repo snapshots.", errors=preflight.errors, warnings=preflight.warnings)

    try:
        with restic_repo_lock(timeout_seconds=30):
            result = list_snapshots(target, global_config)
    except (RuntimeError, OperationInterruptedError) as exc:
        return _make_check("repo-snapshots", "failure", str(exc), errors=[str(exc)])

    output = (result.stdout or "").strip()
    if result.returncode != 0:
        return _make_check("repo-snapshots", "failure", explain_restic_failure(result), stdout=output, stderr=(result.stderr or "").strip())
    if not output:
        return _make_check("repo-snapshots", "warning", "Repository is reachable but no snapshots were found.", stdout="")
    return _make_check("repo-snapshots", "success", "Repository snapshots listed successfully.", stdout=output)


def check_repo_check(global_config: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        return _make_check("repo-check", "skipped", "Repository check skipped because no target was selected.")

    preflight = validate_restic_preflight(global_config, target)
    if preflight.errors:
        return _make_check("repo-check", "failure", "Restic preflight failed for repo check.", errors=preflight.errors, warnings=preflight.warnings)

    try:
        with restic_repo_lock(timeout_seconds=30):
            result = check_repository(target, global_config)
    except (RuntimeError, OperationInterruptedError) as exc:
        return _make_check("repo-check", "failure", str(exc), errors=[str(exc)])

    if result.returncode != 0:
        return _make_check(
            "repo-check",
            "failure",
            explain_restic_failure(result),
            stdout=(result.stdout or "").strip(),
            stderr=(result.stderr or "").strip(),
        )
    return _make_check(
        "repo-check",
        "success",
        "Repository check succeeded.",
        stdout=(result.stdout or "").strip(),
    )


def check_db_list(profiles: list[dict[str, Any]], profile_name: str | None = None) -> dict[str, Any]:
    dumps = list_database_dumps(profiles)
    if profile_name:
        dumps = [dump for dump in dumps if str(dump.get("__profile_name__", "")).strip() == profile_name]
    return _make_check(
        "db-list",
        "success",
        f"Found {len(dumps)} configured database dump definition(s).",
        dumps=redact_config(dumps),
    )


def check_db_tests(profiles: list[dict[str, Any]], profile_name: str | None = None) -> dict[str, Any]:
    dumps = load_database_dumps_from_profiles(profiles)
    if profile_name:
        dumps = [dump for dump in dumps if str(dump.get("__profile_name__", "")).strip() == profile_name]
    if not dumps:
        return _make_check("db-test", "skipped", "No matching database dump definitions were found.")

    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    for dump in dumps:
        result = test_database_connection(dump)
        results.append(redact_config(result))
        warnings.extend(result.get("warnings", []))
        if not result.get("success"):
            errors.append(f"Database connection test failed for {dump.get('name', '<unknown>')}")
            stderr = str(result.get("stderr", "")).strip()
            if stderr:
                errors.append(stderr)

    status = "failure" if errors else ("warning" if warnings else "success")
    summary = "Database connection tests completed."
    if errors:
        summary = f"Database connection tests failed for {len([r for r in results if not r.get('success')])} dump definition(s)."
    return _make_check("db-test", status, summary, results=results, warnings=_dedupe(warnings), errors=_dedupe(errors))


def check_coverage_audit(profile_name: str | None = None) -> dict[str, Any]:
    report = run_coverage_audit(profile_name=profile_name, output_dir=None)
    return _make_check(
        "coverage-audit",
        str(report.get("status", "failure")).lower(),
        f"Coverage audit completed with status {str(report.get('status', 'failure')).upper()}.",
        report={
            "status": report.get("status", ""),
            "text_report_path": report.get("text_report_path", ""),
            "json_report_path": report.get("json_report_path", ""),
            "summary": report.get("summary", {}),
        },
    )


def maybe_email_test(global_config: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return _make_check("email-test", "skipped", "Email test not requested.")
    result = send_test_email(global_config)
    status = "success" if result.get("success") else "failure"
    summary = "Email test sent successfully." if result.get("success") else f"Email test failed: {result.get('error', 'unknown error')}"
    return _make_check("email-test", status, summary, result=redact_config(result))


def maybe_restore_test(target_name: str | None, profile_name: str | None, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return _make_check("restore-test", "skipped", "Restore test not requested.")
    if not target_name:
        return _make_check("restore-test", "failure", "Restore test requires --target when using validate production.")
    report = run_restore_test(target=target_name, snapshot="latest", profile_name=profile_name, includes=None, output_dir=None, keep_output=False)
    return _make_check(
        "restore-test",
        str(report.get("status", "failure")).lower(),
        f"Restore test completed with status {str(report.get('status', 'failure')).upper()}.",
        report={
            "status": report.get("status", ""),
            "text_report_path": report.get("text_report_path", ""),
            "json_report_path": report.get("json_report_path", ""),
        },
    )


def maybe_backup_dry_run(target_name: str | None, profile_name: str | None, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return _make_check("backup-dry-run", "skipped", "Backup dry-run not requested.")
    report = run_backup(dry_run=True, target_name=target_name, profile_name=profile_name)
    return _make_check(
        "backup-dry-run",
        str(report.get("status", "failure")).lower(),
        f"Backup dry-run completed with status {str(report.get('status', 'failure')).upper()}.",
        report={
            "status": report.get("status", ""),
            "text_report_path": report.get("text_report_path", ""),
            "json_report_path": report.get("json_report_path", ""),
        },
    )


def render_validation_report_text(report: dict[str, Any]) -> str:
    safe_report = _redact_sensitive_strings(redact_config(report))
    lines = [
        "server-backup production validation report",
        "",
        f"Hostname: {safe_report.get('hostname', '')}",
        f"BACKUP_NAME: {safe_report.get('backup_name', '')}",
        f"Start: {safe_report.get('start_time', '')}",
        f"End: {safe_report.get('end_time', '')}",
        f"Duration: {safe_report.get('duration_seconds', 0):.2f}s",
        f"Target: {safe_report.get('target_name', '') or '<auto>'}",
        f"Profile: {safe_report.get('profile_name', '') or '<all>'}",
        f"Overall: {str(safe_report.get('status', 'failure')).upper()}",
        "",
        "Checks:",
    ]
    for check in safe_report.get("checks", []):
        lines.append(f"  - {check.get('name', '')}: {str(check.get('status', 'failure')).upper()} - {check.get('summary', '')}")
    if safe_report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for warning in safe_report["warnings"]:
            lines.append(f"  - {warning}")
    if safe_report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for error in safe_report["errors"]:
            lines.append(f"  - {error}")
    if safe_report.get("text_report_path") or safe_report.get("json_report_path"):
        lines.append("")
        lines.append("Reports:")
        if safe_report.get("text_report_path"):
            lines.append(f"  {safe_report['text_report_path']}")
        if safe_report.get("json_report_path"):
            lines.append(f"  {safe_report['json_report_path']}")
    return "\n".join(lines).rstrip() + "\n"


def render_validation_report_json(report: dict[str, Any]) -> str:
    return json.dumps(_redact_sensitive_strings(redact_config(report)), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def write_validation_report(report: dict[str, Any], report_dir: str | Path) -> dict[str, str]:
    report_root = Path(report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = _report_stamp()
    text_path = report_root / f"production-validation-{stamp}.txt"
    json_path = report_root / f"production-validation-{stamp}.json"
    text_path.write_text(render_validation_report_text(report), encoding="utf-8")
    json_path.write_text(render_validation_report_json(report), encoding="utf-8")

    state_dir = Path(str(report.get("state_dir") or DEFAULT_STATE_DIR))
    state_dir.mkdir(parents=True, exist_ok=True)
    last_path = state_dir / LAST_PRODUCTION_VALIDATION_FILE
    last_payload = {
        "hostname": report.get("hostname", ""),
        "backup_name": report.get("backup_name", ""),
        "start_time": report.get("start_time", ""),
        "end_time": report.get("end_time", ""),
        "duration_seconds": report.get("duration_seconds", 0),
        "target_name": report.get("target_name", ""),
        "profile_name": report.get("profile_name", ""),
        "status": report.get("status", ""),
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
    }
    last_path.write_text(
        json.dumps(_redact_sensitive_strings(redact_config(last_payload)), indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "last_production_validation_path": str(last_path),
    }


def run_production_validation(
    *,
    target_name: str | None = None,
    profile_name: str | None = None,
    email_test: bool = False,
    restore_test: bool = False,
    backup_dry_run: bool = False,
) -> dict[str, Any]:
    start = datetime.now(UTC)
    global_config = load_global_config(DEFAULT_BACKUP_CONF)
    targets = load_targets(DEFAULT_TARGETS_DIR)
    profiles = load_profiles(DEFAULT_PROFILES_DIR)

    selected_target, selection_warnings = _select_target_for_validation(target_name, targets)
    checks: list[dict[str, Any]] = [
        check_config_validate(global_config, targets, profiles),
        check_health(global_config, targets, profiles),
        check_operations_status(global_config, targets, profiles),
        check_repo_snapshots(global_config, selected_target),
        check_repo_check(global_config, selected_target),
        check_db_list(profiles, profile_name=profile_name),
        check_db_tests(profiles, profile_name=profile_name),
        check_coverage_audit(profile_name=profile_name),
        maybe_email_test(global_config, email_test),
        maybe_restore_test(str(selected_target.get("TARGET_NAME", "")) if selected_target else target_name, profile_name, restore_test),
        maybe_backup_dry_run(str(selected_target.get("TARGET_NAME", "")) if selected_target else target_name, profile_name, backup_dry_run),
    ]

    warnings = _dedupe(selection_warnings)
    errors: list[str] = []
    for check in checks:
        warnings.extend(check.get("warnings", []))
        errors.extend(check.get("errors", []))

    status = _status_from_checks(checks)
    if errors:
        status = "failure"
    elif warnings and status == "success":
        status = "warning"

    end = datetime.now(UTC)
    report = {
        "hostname": socket.gethostname(),
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round((end - start).total_seconds(), 3),
        "target_name": target_name or (str(selected_target.get("TARGET_NAME", "")) if selected_target else ""),
        "profile_name": profile_name or "",
        "status": status,
        "checks": checks,
        "warnings": _dedupe(warnings),
        "errors": _dedupe(errors),
        "state_dir": str(global_config.get("STATE_DIR") or DEFAULT_STATE_DIR),
    }
    report_dir = Path(str(global_config.get("REPORT_DIR") or DEFAULT_REPORT_DIR))
    report.update(write_validation_report(report, report_dir))
    return report


__all__ = [
    "LAST_PRODUCTION_VALIDATION_FILE",
    "check_config_validate",
    "check_coverage_audit",
    "check_db_list",
    "check_db_tests",
    "check_health",
    "check_operations_status",
    "check_repo_check",
    "check_repo_snapshots",
    "maybe_backup_dry_run",
    "maybe_email_test",
    "maybe_restore_test",
    "render_validation_report_json",
    "render_validation_report_text",
    "run_production_validation",
    "write_validation_report",
]
