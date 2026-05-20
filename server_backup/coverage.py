from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_global_config, load_profiles, load_targets, redact_config
from .db import parse_database_dump_spec
from .docker import (
    collect_container_mounts as docker_collect_container_mounts,
    compare_mounts_to_backup_paths,
    discover_compose_files as docker_discover_compose_files,
    discover_env_files_near_compose,
    docker_available,
    list_containers as docker_list_containers,
    list_volumes as docker_list_volumes,
)
from .validators import validate_global_config, validate_profile_config, validate_target_config


DEFAULT_BACKUP_CONF = Path("/etc/server-backup/backup.conf")
DEFAULT_TARGETS_DIR = Path("/etc/server-backup/targets.d")
DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_REPORT_DIR = Path("/var/lib/server-backup/reports")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
LAST_BACKUP_RUN_FILE = "last-backup-run.json"
LAST_RESTORE_TEST_FILE = "last-restore-test.json"
LAST_COVERAGE_AUDIT_FILE = "last-coverage-audit.json"
COMPOSE_FILENAMES = {
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.override.yml",
}
DOCKER_AWARE_PROFILE_TYPES = {"docker-host", "docker-app", "cis-site"}
DANGEROUS_OUTPUT_DIRS = {
    Path("/"),
    Path("/etc"),
    Path("/srv"),
    Path("/opt"),
    Path("/var/lib/docker"),
}
SENSITIVE_MESSAGE_TOKENS = (
    "RESTIC_PASSWORD_FILE",
    "SSH_IDENTITY_FILE",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "PGPASSWORD",
    "MYSQL_PWD",
)
DB_STORAGE_DESTINATIONS = {
    "/var/lib/postgresql/data",
    "/var/lib/postgresql",
    "/var/lib/mysql",
    "/var/lib/mariadb",
}


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _safe_exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except PermissionError:
        return True


def _safe_stat(path: str | Path):
    try:
        return Path(path).stat()
    except (FileNotFoundError, OSError, PermissionError):
        return None


def _is_dangerous_output_dir(path: Path) -> bool:
    candidate = path.resolve(strict=False)
    for dangerous in DANGEROUS_OUTPUT_DIRS:
        if candidate == dangerous or dangerous in candidate.parents:
            return True
    return False


def _ensure_report_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _status_from_findings(findings: list[dict[str, Any]]) -> str:
    severities = {str(finding.get("severity", "SUCCESS")).upper() for finding in findings}
    if "FAILURE" in severities:
        return "failure"
    if "WARNING" in severities:
        return "warning"
    return "success"


def _sanitize_message(message: str) -> str:
    upper = message.upper()
    if "RESTIC_PASSWORD_FILE" in upper:
        return "RESTIC_PASSWORD_FILE is missing or invalid."
    if "SSH_IDENTITY_FILE" in upper:
        return "SSH_IDENTITY_FILE is missing or invalid."
    if any(token in upper for token in SENSITIVE_MESSAGE_TOKENS):
        return "<redacted>"
    return message


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for finding in findings:
        key = (
            str(finding.get("severity", "")),
            str(finding.get("code", "")),
            str(finding.get("message", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _path_is_covered(path: str | Path, backup_paths: list[str]) -> bool:
    candidate = str(path)
    for backup_path in backup_paths:
        if not backup_path:
            continue
        backup_candidate = str(backup_path)
        if candidate == backup_candidate:
            return True
        try:
            if os.path.commonpath([candidate, backup_candidate]) == backup_candidate:
                return True
        except ValueError:
            continue
    return False


def _all_profile_backup_paths(profiles: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for profile in profiles:
        raw = profile.get("BACKUP_PATHS", [])
        if isinstance(raw, list):
            paths.extend(str(item).strip() for item in raw if str(item).strip())
    return paths


def _profile_database_dumps(profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw_dumps = profile.get("DATABASE_DUMPS", [])
    if not isinstance(raw_dumps, list):
        return []
    parsed: list[dict[str, Any]] = []
    for raw_spec in raw_dumps:
        try:
            parsed.append(parse_database_dump_spec(str(raw_spec)))
        except ValueError:
            continue
    return parsed


def _mount_is_probable_db_storage(mount: dict[str, Any]) -> bool:
    destination = str(mount.get("destination", "")).strip().lower()
    return any(destination == candidate or destination.startswith(f"{candidate}/") for candidate in DB_STORAGE_DESTINATIONS)


def _dump_covers_docker_container(mount: dict[str, Any], profiles: list[dict[str, Any]]) -> bool:
    container_name = str(mount.get("container_name", "")).strip()
    if not container_name or not _mount_is_probable_db_storage(mount):
        return False
    for profile in profiles:
        for dump_spec in _profile_database_dumps(profile):
            if str(dump_spec.get("mode", "")).strip().lower() != "docker":
                continue
            if str(dump_spec.get("container", "")).strip() == container_name:
                return True
    return False


def classify_finding(severity: str, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "severity": str(severity).upper(),
        "code": code,
        "message": _sanitize_message(message),
        "details": redact_config(details or {}),
    }


def check_backup_paths(profile: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    profile_name = str(profile.get("PROFILE_NAME", "<unknown>"))
    raw_paths = profile.get("BACKUP_PATHS", [])

    if not isinstance(raw_paths, list) or not raw_paths:
        findings.append(
            classify_finding(
                "FAILURE",
                "profile-no-backup-paths",
                f"Profile {profile_name} does not define any BACKUP_PATHS.",
                {"profile_name": profile_name},
            )
        )
        return findings

    existing_paths = 0
    for backup_path in [str(item).strip() for item in raw_paths if str(item).strip()]:
        if _safe_exists(backup_path):
            existing_paths += 1
        else:
            findings.append(
                classify_finding(
                    "WARNING",
                    "profile-missing-path",
                    f"Profile {profile_name} references a missing BACKUP_PATH: {backup_path}",
                    {"profile_name": profile_name, "path": backup_path},
                )
            )

    if existing_paths == 0:
        findings.append(
            classify_finding(
                "FAILURE",
                "profile-no-existing-paths",
                f"Profile {profile_name} has no existing BACKUP_PATHS.",
                {"profile_name": profile_name},
            )
        )

    return findings


def check_profile_excludes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    excludes = profile.get("EXCLUDES")
    profile_name = str(profile.get("PROFILE_NAME", "<unknown>"))
    if excludes is not None and not isinstance(excludes, list):
        findings.append(
            classify_finding(
                "WARNING",
                "profile-invalid-excludes",
                f"Profile {profile_name} uses an invalid EXCLUDES format.",
                {"profile_name": profile_name},
            )
        )
    return findings


def collect_targets_coverage(global_config: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    target_results: list[dict[str, Any]] = []

    if not targets:
        findings.append(
            classify_finding(
                "FAILURE",
                "no-targets",
                "No targets are configured.",
            )
        )
        return {"findings": findings, "target_results": target_results}

    for target in targets:
        target_name = str(target.get("TARGET_NAME", "<unknown>"))
        result = validate_target_config(target)
        target_findings: list[dict[str, Any]] = []
        for error in result.errors:
            target_findings.append(
                classify_finding(
                    "FAILURE",
                    "target-invalid",
                    f"Target {target_name} is invalid: {_sanitize_message(error)}",
                    {"target_name": target_name},
                )
            )
        for warning in result.warnings:
            target_findings.append(
                classify_finding(
                    "WARNING",
                    "target-warning",
                    f"Target {target_name} warning: {_sanitize_message(warning)}",
                    {"target_name": target_name},
                )
            )
        target_results.append(
            {
                "target_name": target_name,
                "target_type": str(target.get("TARGET_TYPE", "")),
                "status": _status_from_findings(target_findings),
                "findings": target_findings,
            }
        )
        findings.extend(target_findings)

    password_file = str(global_config.get("RESTIC_PASSWORD_FILE", "")).strip()
    if not password_file or not _safe_exists(password_file):
        findings.append(
            classify_finding(
                "FAILURE",
                "restic-password-file-missing",
                "RESTIC_PASSWORD_FILE is not available locally.",
            )
        )
    cache_dir = str(global_config.get("RESTIC_CACHE_DIR", "")).strip()
    if not cache_dir or not _safe_exists(cache_dir):
        findings.append(
            classify_finding(
                "FAILURE",
                "restic-cache-dir-missing",
                "RESTIC_CACHE_DIR is not available locally.",
                {"path": cache_dir or "<missing>"},
            )
        )

    return {"findings": _dedupe_findings(findings), "target_results": target_results}


def check_cis_site_coverage(profile: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    profile_name = str(profile.get("PROFILE_NAME", "<unknown>"))
    profile_type = str(profile.get("PROFILE_TYPE", "")).strip()
    app_kind = str(profile.get("APP_KIND", "")).strip()
    web_content_critical = str(profile.get("WEB_CONTENT_CRITICAL", "")).strip().lower()

    is_cis = profile_type == "cis-site" or app_kind == "cis-site" or web_content_critical == "true"
    if not is_cis:
        return findings

    backup_paths = [str(item).strip() for item in profile.get("BACKUP_PATHS", []) if str(item).strip()] if isinstance(profile.get("BACKUP_PATHS"), list) else []
    classification = profile.get("CONTENT_CLASSIFICATION", [])
    classification_entries = [str(item).strip() for item in classification if str(item).strip()] if isinstance(classification, list) else []

    if "WEB_CONTENT_CRITICAL" not in profile:
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-web-content-critical",
                f"CIS profile {profile_name} does not declare WEB_CONTENT_CRITICAL.",
                {"profile_name": profile_name},
            )
        )
    if not classification_entries:
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-content-classification",
                f"CIS profile {profile_name} does not declare CONTENT_CLASSIFICATION.",
                {"profile_name": profile_name},
            )
        )
    database_dumps = _profile_database_dumps(profile)
    if not database_dumps:
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-database-dumps",
                f"CIS profile {profile_name} does not declare DATABASE_DUMPS yet.",
                {"profile_name": profile_name},
            )
        )

    lowered_paths = [path.lower() for path in backup_paths]
    if not any("/frontend" in path or path.endswith("frontend") for path in lowered_paths):
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-frontend-path",
                f"CIS profile {profile_name} does not appear to cover a frontend path.",
                {"profile_name": profile_name},
            )
        )
    if not any("/backend" in path or path.endswith("backend") for path in lowered_paths):
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-backend-path",
                f"CIS profile {profile_name} does not appear to cover a backend path.",
                {"profile_name": profile_name},
            )
        )
    if not any("/alembic" in path or "/migrations" in path or path.endswith("alembic") or path.endswith("migrations") for path in lowered_paths):
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-migrations-path",
                f"CIS profile {profile_name} does not appear to cover migrations.",
                {"profile_name": profile_name},
            )
        )

    lowered_classification = [entry.lower() for entry in classification_entries]
    if classification_entries and not any("site_pages" in entry or "builder-pages" in entry for entry in lowered_classification):
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-pages-table",
                f"CIS profile {profile_name} does not mention a builder pages table such as site_pages.",
                {"profile_name": profile_name},
            )
        )
    if not any(token in entry for entry in lowered_classification for token in ("media", "upload", "asset")):
        findings.append(
            classify_finding(
                "WARNING",
                "cis-missing-media-classification",
                f"CIS profile {profile_name} does not classify media/uploads/assets.",
                {"profile_name": profile_name},
            )
        )

    return findings


def collect_profiles_coverage(global_config: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    profile_results: list[dict[str, Any]] = []

    if not profiles:
        findings.append(
            classify_finding(
                "FAILURE",
                "no-profiles",
                "No profiles are configured.",
            )
        )
        return {"findings": findings, "profile_results": profile_results}

    for profile in profiles:
        profile_name = str(profile.get("PROFILE_NAME", "<unknown>"))
        result = validate_profile_config(profile)
        profile_findings: list[dict[str, Any]] = []

        for error in result.errors:
            profile_findings.append(
                classify_finding(
                    "FAILURE",
                    "profile-invalid",
                    f"Profile {profile_name} is invalid: {_sanitize_message(error)}",
                    {"profile_name": profile_name},
                )
            )
        for warning in result.warnings:
            profile_findings.append(
                classify_finding(
                    "WARNING",
                    "profile-warning",
                    f"Profile {profile_name} warning: {_sanitize_message(warning)}",
                    {"profile_name": profile_name},
                )
            )

        profile_findings.extend(check_backup_paths(profile))
        profile_findings.extend(check_profile_excludes(profile))
        profile_findings.extend(check_cis_site_coverage(profile))
        profile_findings = _dedupe_findings(profile_findings)

        profile_results.append(
            {
                "profile_name": profile_name,
                "profile_type": str(profile.get("PROFILE_TYPE", "")),
                "status": _status_from_findings(profile_findings),
                "findings": profile_findings,
            }
        )
        findings.extend(profile_findings)

    state_dir = Path(str(global_config.get("STATE_DIR", DEFAULT_STATE_DIR)))
    if not (state_dir / LAST_BACKUP_RUN_FILE).exists():
        findings.append(
            classify_finding(
                "WARNING",
                "backup-never-run",
                "No previous backup run report was found.",
            )
        )
    if not (state_dir / LAST_RESTORE_TEST_FILE).exists():
        findings.append(
            classify_finding(
                "WARNING",
                "restore-test-never-run",
                "No previous restore test report was found.",
            )
        )
    if str(global_config.get("EMAIL_REPORT_ENABLED", "")).strip().lower() != "true":
        findings.append(
            classify_finding(
                "WARNING",
                "email-disabled",
                "Automatic email reports are disabled.",
            )
        )

    return {"findings": _dedupe_findings(findings), "profile_results": profile_results}


def check_docker_availability() -> dict[str, Any]:
    availability = docker_available()
    return {
        "available": bool(availability.get("available")),
        "reason": str(availability.get("reason", "")),
        "docker_bin": availability.get("docker_bin"),
    }


def collect_docker_inventory_light() -> dict[str, Any]:
    availability = check_docker_availability()
    if not availability.get("available"):
        return {
            "available": False,
            "reason": availability.get("reason", "docker unavailable"),
            "containers": [],
            "volumes": [],
            "warnings": [],
        }

    warnings: list[str] = []
    try:
        containers = docker_list_containers(all_containers=False)
    except RuntimeError as exc:
        warnings.append(str(exc))
        containers = []
    try:
        volumes = docker_list_volumes()
    except RuntimeError as exc:
        warnings.append(str(exc))
        volumes = []

    return {
        "available": True,
        "reason": "",
        "containers": containers,
        "volumes": volumes,
        "warnings": warnings,
    }


def collect_docker_mounts() -> list[dict[str, Any]]:
    try:
        return docker_collect_container_mounts(all_containers=False)
    except RuntimeError:
        return []


def check_docker_mount_coverage(profiles: list[dict[str, Any]], docker_mounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in compare_mounts_to_backup_paths(docker_mounts, profiles):
        container_name = str(item.get("container_name", "<unknown>"))
        candidate_path = str(item.get("candidate_path", "")).strip()
        volume_name = str(item.get("name", "")).strip()
        if item.get("coverage_status") == "covered":
            continue
        if item.get("coverage_status") == "covered-by-logical-dump":
            findings.append(
                classify_finding(
                    "SUCCESS",
                    "docker-db-covered-by-logical-dump",
                    f"Docker DB storage for container {container_name} is primarily covered by a logical DATABASE_DUMPS entry.",
                    {"container_name": container_name, "destination": item.get("destination", "")},
                )
            )
            continue
        if item.get("is_database"):
            findings.append(
                classify_finding(
                    "WARNING",
                    "docker-db-volume-uncovered",
                    f"Docker database storage for container {container_name} is not covered by BACKUP_PATHS and no matching logical dump was found.",
                    {"container_name": container_name, "path": candidate_path, "volume_name": volume_name},
                )
            )
            continue
        if item.get("is_reverse_proxy"):
            findings.append(
                classify_finding(
                    "WARNING",
                    "docker-reverse-proxy-uncovered",
                    f"Reverse proxy Docker data for container {container_name} is not covered: {volume_name or candidate_path}",
                    {"container_name": container_name, "path": candidate_path, "volume_name": volume_name},
                )
            )
            continue
        if str(item.get("type", "")) == "bind":
            findings.append(
                classify_finding(
                    "WARNING",
                    "docker-bind-uncovered",
                    f"Docker bind mount for container {container_name} is not covered: {candidate_path}",
                    {"container_name": container_name, "source": candidate_path},
                )
            )
            continue
        findings.append(
            classify_finding(
                "WARNING",
                "docker-volume-uncovered",
                f"Docker volume for container {container_name} is not covered: {volume_name or candidate_path}",
                {"container_name": container_name, "volume_name": volume_name, "path": candidate_path},
            )
        )
    return findings


def discover_compose_files(search_paths: list[str]) -> list[str]:
    return docker_discover_compose_files(search_paths)


def check_env_files_coverage(profiles: list[dict[str, Any]], compose_files: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    backup_paths = _all_profile_backup_paths(profiles)

    for compose_file in compose_files:
        compose_path = Path(compose_file)
        parent_dir = compose_path.parent
        if not _path_is_covered(parent_dir, backup_paths) and not _path_is_covered(compose_path, backup_paths):
            findings.append(
                classify_finding(
                    "WARNING",
                    "compose-parent-uncovered",
                    f"Compose directory is not fully covered: {parent_dir}",
                    {"compose_file": str(compose_path)},
                )
            )
    for env_file in discover_env_files_near_compose(compose_files):
        env_path = Path(env_file)
        if not _path_is_covered(env_path, backup_paths):
            findings.append(
                classify_finding(
                    "WARNING",
                    "env-file-uncovered",
                    f"A .env file exists next to {env_path.parent.name} but is not covered by any BACKUP_PATH.",
                    {"env_file": str(env_path)},
                )
            )
    return findings


def _build_recommendations(findings: list[dict[str, Any]]) -> list[str]:
    codes = {str(finding.get("code", "")) for finding in findings}
    recommendations: list[str] = []
    if "no-targets" in codes:
        recommendations.append("Add at least one target with: sudo server-backup target add")
    if "no-profiles" in codes:
        recommendations.append("Add at least one profile with: sudo server-backup profile add")
    if any(code.startswith("profile-") for code in codes):
        recommendations.append("Review profile BACKUP_PATHS and fix missing or invalid paths.")
    if "docker-db-volume-uncovered" in codes:
        recommendations.append("Configure a logical DATABASE_DUMPS entry for uncovered Docker databases before relying on raw volume backups.")
    if "docker-reverse-proxy-uncovered" in codes:
        recommendations.append("Add reverse-proxy volumes such as Caddy, nginx or Traefik data/config paths to an appropriate profile.")
    if any(code.startswith("docker-") or code.startswith("compose-") or code.startswith("env-file-") for code in codes):
        recommendations.append("Review Docker-related profiles and ensure bind mounts, volumes and .env files are covered.")
    if any(code.startswith("cis-") for code in codes):
        recommendations.append("Complete CIS coverage with CONTENT_CLASSIFICATION and DATABASE_DUMPS where logical database dumps are required.")
    if "backup-never-run" in codes:
        recommendations.append("Run a backup dry-run or real backup to confirm operational coverage.")
    if "restore-test-never-run" in codes:
        recommendations.append("Run sudo server-backup restore test --target <target> regularly.")
    return recommendations


def render_coverage_report_text(report: dict[str, Any]) -> str:
    safe_report = redact_config(report)
    lines = [
        "server-backup coverage audit report",
        "",
        f"Hostname: {safe_report.get('hostname', '')}",
        f"BACKUP_NAME: {safe_report.get('backup_name', '')}",
        f"Start: {safe_report.get('start_time', '')}",
        f"End: {safe_report.get('end_time', '')}",
        f"Duration: {safe_report.get('duration_seconds', 0):.2f}s",
        f"Overall: {str(safe_report.get('status', 'failure')).upper()}",
        f"Targets: {safe_report.get('targets_count', 0)}",
        f"Profiles: {safe_report.get('profiles_count', 0)}",
        "",
        "Summary:",
        f"  success: {safe_report.get('summary', {}).get('SUCCESS', 0)}",
        f"  warning: {safe_report.get('summary', {}).get('WARNING', 0)}",
        f"  failure: {safe_report.get('summary', {}).get('FAILURE', 0)}",
        "",
    ]

    for section_name, section in (
        ("Generic findings", safe_report.get("generic_findings", [])),
        ("Target findings", safe_report.get("target_findings", [])),
        ("Profile findings", safe_report.get("profile_findings", [])),
        ("Docker findings", safe_report.get("docker_findings", [])),
        ("CIS findings", safe_report.get("cis_findings", [])),
    ):
        if not section:
            continue
        lines.append(f"{section_name}:")
        for finding in section:
            lines.append(f"  [{finding.get('severity', 'SUCCESS')}] {finding.get('code', '')}: {finding.get('message', '')}")
        lines.append("")

    if safe_report.get("recommendations"):
        lines.append("Recommendations:")
        for recommendation in safe_report["recommendations"]:
            lines.append(f"  - {recommendation}")
        lines.append("")

    if safe_report.get("docker", {}).get("available") is False:
        lines.append(f"Docker: unavailable ({safe_report.get('docker', {}).get('reason', 'unknown')})")
        lines.append("")

    if safe_report.get("text_report_path") or safe_report.get("json_report_path"):
        lines.append("Reports:")
        if safe_report.get("text_report_path"):
            lines.append(f"  {safe_report['text_report_path']}")
        if safe_report.get("json_report_path"):
            lines.append(f"  {safe_report['json_report_path']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_coverage_report_json(report: dict[str, Any]) -> str:
    return json.dumps(redact_config(report), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def write_coverage_report(report: dict[str, Any], report_dir: str | Path) -> dict[str, str]:
    report_path = Path(report_dir)
    _ensure_report_dir(report_path)
    state_dir = Path(str(report.get("state_dir") or DEFAULT_STATE_DIR))
    _ensure_report_dir(state_dir)

    existing_text_path = str(report.get("text_report_path", "")).strip()
    existing_json_path = str(report.get("json_report_path", "")).strip()
    if existing_text_path and existing_json_path:
        text_path = Path(existing_text_path)
        json_path = Path(existing_json_path)
    else:
        stamp = _report_stamp()
        text_path = report_path / f"coverage-audit-{stamp}.txt"
        json_path = report_path / f"coverage-audit-{stamp}.json"

    report["text_report_path"] = str(text_path)
    report["json_report_path"] = str(json_path)
    text_path.write_text(render_coverage_report_text(report), encoding="utf-8")
    json_path.write_text(render_coverage_report_json(report), encoding="utf-8")
    last_path = update_last_coverage_audit(report)
    return {
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "last_coverage_audit_path": last_path,
    }


def update_last_coverage_audit(report: dict[str, Any]) -> str:
    state_dir = Path(str(report.get("state_dir") or DEFAULT_STATE_DIR))
    _ensure_report_dir(state_dir)
    last_path = state_dir / LAST_COVERAGE_AUDIT_FILE
    payload = {
        "hostname": report.get("hostname", ""),
        "backup_name": report.get("backup_name", ""),
        "start_time": report.get("start_time", ""),
        "end_time": report.get("end_time", ""),
        "duration_seconds": report.get("duration_seconds", 0),
        "status": report.get("status", "failure"),
        "targets_count": report.get("targets_count", 0),
        "profiles_count": report.get("profiles_count", 0),
        "summary": report.get("summary", {}),
        "text_report_path": report.get("text_report_path", ""),
        "json_report_path": report.get("json_report_path", ""),
    }
    last_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    return str(last_path)


def run_coverage_audit(profile_name: str | None = None, output_dir: str | None = None) -> dict[str, Any]:
    start = datetime.now(UTC)
    global_config = load_global_config(DEFAULT_BACKUP_CONF)
    targets = load_targets(DEFAULT_TARGETS_DIR)
    profiles = load_profiles(DEFAULT_PROFILES_DIR)

    if profile_name:
        filtered = [profile for profile in profiles if str(profile.get("PROFILE_NAME", "")).strip() == profile_name]
        if not filtered:
            raise ValueError(f"Profile not found: {profile_name}")
        profiles = filtered

    report_dir = Path(output_dir) if output_dir else Path(str(global_config.get("REPORT_DIR") or DEFAULT_REPORT_DIR))
    if output_dir and _is_dangerous_output_dir(report_dir):
        raise ValueError(f"Refusing dangerous coverage report output directory: {report_dir}")

    state_dir = str(global_config.get("STATE_DIR") or DEFAULT_STATE_DIR)

    report: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": "",
        "duration_seconds": 0.0,
        "status": "failure",
        "targets_count": len(targets),
        "profiles_count": len(profiles),
        "summary": {"SUCCESS": 0, "WARNING": 0, "FAILURE": 0},
        "generic_findings": [],
        "target_findings": [],
        "profile_findings": [],
        "docker_findings": [],
        "cis_findings": [],
        "recommendations": [],
        "docker": {},
        "state_dir": state_dir,
        "text_report_path": "",
        "json_report_path": "",
    }

    generic_findings: list[dict[str, Any]] = []
    global_validation = validate_global_config(global_config)
    for error in global_validation.errors:
        generic_findings.append(classify_finding("FAILURE", "global-invalid", _sanitize_message(error)))
    for warning in global_validation.warnings:
        generic_findings.append(classify_finding("WARNING", "global-warning", _sanitize_message(warning)))

    targets_data = collect_targets_coverage(global_config, targets)
    profiles_data = collect_profiles_coverage(global_config, profiles)

    docker_inventory = collect_docker_inventory_light()
    docker_findings: list[dict[str, Any]] = []
    docker_mounts: list[dict[str, Any]] = []
    docker_aware_profiles = [
        profile for profile in profiles if str(profile.get("PROFILE_TYPE", "")).strip() in DOCKER_AWARE_PROFILE_TYPES
    ]
    if docker_inventory.get("available"):
        docker_findings.extend(
            classify_finding("WARNING", "docker-warning", warning)
            for warning in docker_inventory.get("warnings", [])
            if warning
        )
        docker_mounts = collect_docker_mounts()
        docker_findings.extend(check_docker_mount_coverage(profiles, docker_mounts))
    elif docker_aware_profiles:
        docker_findings.append(
            classify_finding(
                "WARNING",
                "docker-unavailable",
                f"Docker is unavailable locally: {docker_inventory.get('reason', 'unknown reason')}",
            )
        )

    compose_search_paths = _all_profile_backup_paths(profiles)
    compose_files = discover_compose_files(compose_search_paths)
    docker_findings.extend(check_env_files_coverage(profiles, compose_files))

    cis_findings: list[dict[str, Any]] = []
    for profile in profiles:
        cis_findings.extend(check_cis_site_coverage(profile))

    report["docker"] = {
        "available": bool(docker_inventory.get("available")),
        "reason": docker_inventory.get("reason", ""),
        "containers_count": len(docker_inventory.get("containers", [])),
        "volumes_count": len(docker_inventory.get("volumes", [])),
        "mounts_count": len(docker_mounts),
        "compose_files_count": len(compose_files),
    }

    report["generic_findings"] = _dedupe_findings(generic_findings)
    report["target_findings"] = _dedupe_findings(targets_data["findings"])
    report["profile_findings"] = _dedupe_findings(profiles_data["findings"])
    report["docker_findings"] = _dedupe_findings(docker_findings)
    report["cis_findings"] = _dedupe_findings(cis_findings)

    all_findings: list[dict[str, Any]] = []
    for key in ("generic_findings", "target_findings", "profile_findings", "docker_findings", "cis_findings"):
        all_findings.extend(report[key])
    all_findings = _dedupe_findings(all_findings)

    summary = {"SUCCESS": 0, "WARNING": 0, "FAILURE": 0}
    for finding in all_findings:
        summary[str(finding.get("severity", "SUCCESS")).upper()] += 1
    report["summary"] = summary
    report["status"] = _status_from_findings(all_findings)
    report["recommendations"] = _build_recommendations(all_findings)

    end = datetime.now(UTC)
    report["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    report["duration_seconds"] = round((end - start).total_seconds(), 3)
    report.update(write_coverage_report(report, report_dir))
    return report
