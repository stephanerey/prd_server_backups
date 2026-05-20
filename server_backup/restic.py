from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import stat
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import redact_config
from .email_report import send_email_report
from .validators import ValidationResult, validate_target_config


NOT_INITIALIZED_PATTERNS = (
    "is there a repository at the following location",
    "unable to open config file",
    "config file does not exist",
    "no such file or directory",
    "repository does not exist",
)

DEFAULT_REPO_LOCK_PATH = Path("/run/server-backup-repo.lock")
FALLBACK_REPO_LOCK_PATH = Path("/tmp/server-backup-repo.lock")
LAST_PRUNE_RUN_FILE = "last-prune-run.json"
INTERRUPTED_MESSAGE = "Operation interrupted by user. No report may have been completed."


class OperationInterruptedError(RuntimeError):
    pass


def _safe_exists(path: str | Path) -> bool:
    try:
        return Path(path).exists()
    except PermissionError:
        return True


def _safe_stat(path: str | Path):
    try:
        return Path(path).stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def require_restic_available() -> str:
    restic = shutil.which("restic")
    if not restic:
        raise RuntimeError("restic is not installed or not available in PATH.")
    return restic


def _open_lock_file(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return lock_path.open("a+", encoding="utf-8")


def _resolve_lock_path(lock_path: str | Path | None = None) -> Path:
    if lock_path is not None:
        return Path(lock_path)
    return DEFAULT_REPO_LOCK_PATH


@contextmanager
def restic_repo_lock(
    timeout_seconds: int | float = 30,
    *,
    lock_path: str | Path | None = None,
):
    preferred_path = _resolve_lock_path(lock_path)
    try:
        handle = _open_lock_file(preferred_path)
        selected_path = preferred_path
    except OSError:
        if preferred_path != DEFAULT_REPO_LOCK_PATH:
            raise
        selected_path = FALLBACK_REPO_LOCK_PATH
        handle = _open_lock_file(selected_path)

    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)

    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate()
                handle.write(f"{os.getpid()}\n")
                handle.flush()
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Another server-backup restic operation is already running. Lock file: {selected_path}"
                    )
                time.sleep(0.1)

        yield selected_path
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def select_target(name: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    for target in targets:
        if str(target.get("TARGET_NAME", "")).strip() == name:
            return target
    raise ValueError(f"Target not found: {name}")


def build_sftp_command(target: dict[str, Any]) -> str:
    ssh_config_file = str(target.get("SSH_CONFIG_FILE", "")).strip()
    ssh_host_alias = str(target.get("SSH_HOST_ALIAS", "")).strip()
    return f"ssh -F {shlex.quote(ssh_config_file)} {shlex.quote(ssh_host_alias)} -s sftp"


def build_restic_env(global_config: dict[str, Any], target: dict[str, Any]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    repository = str(target.get("RESTIC_REPOSITORY") or global_config.get("RESTIC_REPOSITORY") or "").strip()
    password_file = str(target.get("RESTIC_PASSWORD_FILE") or global_config.get("RESTIC_PASSWORD_FILE") or "").strip()
    cache_dir = str(target.get("RESTIC_CACHE_DIR") or global_config.get("RESTIC_CACHE_DIR") or "").strip()

    env["RESTIC_REPOSITORY"] = repository
    env["RESTIC_PASSWORD_FILE"] = password_file
    env["RESTIC_CACHE_DIR"] = cache_dir
    env["LC_ALL"] = "C"
    return env


def build_restic_base_command(target: dict[str, Any]) -> list[str]:
    require_restic_available()
    return ["restic", "-o", f"sftp.command={build_sftp_command(target)}"]


def run_restic_command(
    args: list[str],
    env: dict[str, str],
    timeout: int | float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            shell=False,
            timeout=timeout,
        )
    except KeyboardInterrupt as exc:
        raise OperationInterruptedError(INTERRUPTED_MESSAGE) from None


def _sanitize_output(text: str) -> str:
    return text.strip()


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = _sanitize_output(result.stdout or "")
    stderr = _sanitize_output(result.stderr or "")
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def _looks_uninitialized(output: str) -> bool:
    lowered = output.lower()
    if "wrong password or no key found" in lowered:
        return False
    return any(pattern in lowered for pattern in NOT_INITIALIZED_PATTERNS)


def _classify_error(output: str) -> str | None:
    lowered = output.lower()
    if "wrong password or no key found" in lowered:
        return "Restic password is incorrect or does not match this repository."
    if "ciphertext verification failed" in lowered:
        return "Repository metadata is damaged or unreadable with the current password."
    if "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        return "SSH host-key validation failed. Update /etc/server-backup/ssh/known_hosts."
    if "permission denied" in lowered or "publickey" in lowered or "authentication failed" in lowered:
        return "SSH authentication failed."
    if "could not resolve hostname" in lowered or "name or service not known" in lowered:
        return "DNS resolution failed for the target host."
    if "temporary failure in name resolution" in lowered:
        return "DNS resolution failed for the target host."
    if "no route to host" in lowered or "network is unreachable" in lowered:
        return "The NAS is unreachable over the network."
    if "connection refused" in lowered:
        return "The NAS refused the SSH/SFTP connection."
    if "connection timed out" in lowered:
        return "The NAS did not answer before the timeout."
    if "subsystem request failed" in lowered or "sftp" in lowered and "connection closed" in lowered:
        return "The SFTP subsystem failed on the target."
    if _looks_uninitialized(output):
        return "Repository is not initialized yet."
    return None


def validate_restic_preflight(global_config: dict[str, Any], target: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    try:
        require_restic_available()
    except RuntimeError as exc:
        result.add_error(str(exc))
        return result

    target_validation = validate_target_config(target)
    result.extend(target_validation)

    if str(target.get("TARGET_TYPE", "")).strip() != "sftp":
        result.add_error(f"{target.get('__file__', '<unknown>')}: TARGET_TYPE must be 'sftp' for restic MVP commands")

    repository = str(target.get("RESTIC_REPOSITORY", "")).strip()
    if not repository:
        result.add_error(f"{target.get('__file__', '<unknown>')}: RESTIC_REPOSITORY is missing")

    password_file = str(target.get("RESTIC_PASSWORD_FILE") or global_config.get("RESTIC_PASSWORD_FILE") or "").strip()
    if not password_file:
        result.add_error(f"{target.get('__file__', '<unknown>')}: RESTIC_PASSWORD_FILE is missing")
    else:
        password_path = Path(password_file)
        if not password_path.exists():
            result.add_error(f"RESTIC_PASSWORD_FILE not found: {password_path}")
        else:
            try:
                with password_path.open("rb"):
                    pass
            except PermissionError:
                result.add_error(f"Permission denied while reading RESTIC_PASSWORD_FILE: {password_path}")
            password_stat = _safe_stat(password_path)
            if password_stat is not None:
                mode = stat.S_IMODE(password_stat.st_mode)
                if mode != 0o600:
                    result.add_warning(
                        f"RESTIC_PASSWORD_FILE should use permissions 0o600, found {oct(mode)}: {password_path}"
                    )

    cache_dir = str(target.get("RESTIC_CACHE_DIR") or global_config.get("RESTIC_CACHE_DIR") or "").strip()
    if not cache_dir:
        result.add_error(f"{target.get('__file__', '<unknown>')}: RESTIC_CACHE_DIR is missing")
    else:
        cache_path = Path(cache_dir)
        try:
            cache_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            result.add_error(f"Permission denied while creating RESTIC_CACHE_DIR: {cache_path}")
        except OSError as exc:
            result.add_error(f"Could not create RESTIC_CACHE_DIR {cache_path}: {exc}")

    ssh_config_file = str(target.get("SSH_CONFIG_FILE", "")).strip()
    ssh_identity_file = str(target.get("SSH_IDENTITY_FILE", "")).strip()
    ssh_known_hosts_file = str(target.get("SSH_KNOWN_HOSTS_FILE", "")).strip()
    ssh_host_alias = str(target.get("SSH_HOST_ALIAS", "")).strip()

    if not ssh_host_alias:
        result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_HOST_ALIAS is missing")
    if not ssh_config_file:
        result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_CONFIG_FILE is missing")
    elif not _safe_exists(ssh_config_file):
        result.add_error(f"SSH_CONFIG_FILE not found: {ssh_config_file}")

    if not ssh_identity_file:
        result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_IDENTITY_FILE is missing")
    elif not _safe_exists(ssh_identity_file):
        result.add_error(f"SSH_IDENTITY_FILE not found: {ssh_identity_file}")

    if not ssh_known_hosts_file:
        result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_KNOWN_HOSTS_FILE is missing")
    elif not _safe_exists(ssh_known_hosts_file):
        result.add_error(f"SSH_KNOWN_HOSTS_FILE not found: {ssh_known_hosts_file}")

    ssh_port = str(target.get("SSH_PORT", "")).strip()
    if ssh_port:
        try:
            port_number = int(ssh_port)
        except ValueError:
            result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_PORT must be an integer")
        else:
            if port_number < 1 or port_number > 65535:
                result.add_error(f"{target.get('__file__', '<unknown>')}: SSH_PORT must be between 1 and 65535")

    return result


def repo_is_initialized(target: dict[str, Any], global_config: dict[str, Any]) -> bool:
    env = build_restic_env(global_config, target)
    command = build_restic_base_command(target) + ["cat", "config"]
    result = run_restic_command(command, env)
    if result.returncode == 0:
        return True

    output = _combined_output(result)
    if _looks_uninitialized(output):
        return False

    classified = _classify_error(output)
    if classified:
        raise RuntimeError(f"{classified}\n{output}".strip())
    raise RuntimeError(output or "Could not determine whether the repository is initialized.")


def init_repository(target: dict[str, Any], global_config: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = build_restic_env(global_config, target)
    command = build_restic_base_command(target) + ["init"]
    return run_restic_command(command, env)


def check_repository(target: dict[str, Any], global_config: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = build_restic_env(global_config, target)
    command = build_restic_base_command(target) + ["check"]
    return run_restic_command(command, env)


def list_snapshots(target: dict[str, Any], global_config: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = build_restic_env(global_config, target)
    command = build_restic_base_command(target) + ["snapshots"]
    return run_restic_command(command, env)


def parse_retention_values(global_config: dict[str, Any]) -> dict[str, int]:
    values: dict[str, int] = {}
    for field_name in ("RETENTION_DAILY", "RETENTION_WEEKLY", "RETENTION_MONTHLY"):
        raw = str(global_config.get(field_name, "")).strip()
        if raw == "":
            raise ValueError(f"{global_config.get('__file__', '<unknown>')}: {field_name} is missing")
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise ValueError(f"{global_config.get('__file__', '<unknown>')}: {field_name} must be an integer") from exc
        if parsed < 0:
            raise ValueError(f"{global_config.get('__file__', '<unknown>')}: {field_name} must be zero or a positive integer")
        values[field_name] = parsed

    if all(value == 0 for value in values.values()):
        raise ValueError("At least one retention value must be greater than zero.")
    return values


def validate_retention_config(global_config: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    try:
        parse_retention_values(global_config)
    except ValueError as exc:
        result.add_error(str(exc))
    return result


def build_forget_args(global_config: dict[str, Any], dry_run: bool = False) -> list[str]:
    retention = parse_retention_values(global_config)
    args = [
        "forget",
        "--keep-daily",
        str(retention["RETENTION_DAILY"]),
        "--keep-weekly",
        str(retention["RETENTION_WEEKLY"]),
        "--keep-monthly",
        str(retention["RETENTION_MONTHLY"]),
    ]
    if dry_run:
        args.append("--dry-run")
    else:
        args.append("--prune")
    return args


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


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


def _dedupe_messages(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for message in messages:
        if not message or message in seen:
            continue
        deduped.append(message)
        seen.add(message)
    return deduped


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _render_prune_report_text(report: dict[str, Any]) -> str:
    safe_report = redact_config(report)
    lines = [
        "server-backup prune run report",
        "",
        f"Hostname: {safe_report.get('hostname', '')}",
        f"BACKUP_NAME: {safe_report.get('backup_name', '')}",
        f"Start: {safe_report.get('start_time', '')}",
        f"End: {safe_report.get('end_time', '')}",
        f"Duration: {safe_report.get('duration_seconds', 0):.2f}s",
        f"Dry-run: {'yes' if safe_report.get('dry_run') else 'no'}",
        f"Interrupted: {'yes' if safe_report.get('interrupted') else 'no'}",
        (
            "Retention: "
            f"daily={safe_report.get('retention', {}).get('RETENTION_DAILY', '')} "
            f"weekly={safe_report.get('retention', {}).get('RETENTION_WEEKLY', '')} "
            f"monthly={safe_report.get('retention', {}).get('RETENTION_MONTHLY', '')}"
        ),
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

    for target_result in safe_report.get("target_results", []):
        lines.append(
            f"Target {target_result.get('target_name', '<unknown>')} [{str(target_result.get('status', 'failure')).upper()}]"
        )
        lines.append(f"  Repository: {target_result.get('repository', '')}")
        if target_result.get("command_summary"):
            lines.append(f"  Command: {target_result.get('command_summary', '')}")
        for warning in target_result.get("warnings", []):
            lines.append(f"  Warning: {warning}")
        for error in target_result.get("errors", []):
            lines.append(f"  Error: {error}")
        if target_result.get("stdout"):
            lines.append("  stdout:")
            for line in str(target_result["stdout"]).splitlines():
                lines.append(f"    {line}")
        if target_result.get("stderr"):
            lines.append("  stderr:")
            for line in str(target_result["stderr"]).splitlines():
                lines.append(f"    {line}")
        lines.append("")

    if safe_report.get("text_report_path") or safe_report.get("json_report_path"):
        lines.append("Reports:")
        if safe_report.get("text_report_path"):
            lines.append(f"  {safe_report['text_report_path']}")
        if safe_report.get("json_report_path"):
            lines.append(f"  {safe_report['json_report_path']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_prune_report_json(report: dict[str, Any]) -> str:
    return json.dumps(redact_config(report), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def _write_prune_report(report: dict[str, Any], report_dir: str | Path, state_dir: str | Path) -> dict[str, str]:
    report_path = Path(report_dir)
    state_path = Path(state_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    state_path.mkdir(parents=True, exist_ok=True)

    existing_text_path = str(report.get("text_report_path", "")).strip()
    existing_json_path = str(report.get("json_report_path", "")).strip()
    if existing_text_path and existing_json_path:
        text_path = Path(existing_text_path)
        json_path = Path(existing_json_path)
    else:
        stamp = _report_stamp()
        text_path = report_path / f"prune-run-{stamp}.txt"
        json_path = report_path / f"prune-run-{stamp}.json"

    report["text_report_path"] = str(text_path)
    report["json_report_path"] = str(json_path)
    text_path.write_text(_render_prune_report_text(report), encoding="utf-8")
    json_path.write_text(_render_prune_report_json(report), encoding="utf-8")

    last_run_path = state_path / LAST_PRUNE_RUN_FILE
    summary = {
        "hostname": report.get("hostname", ""),
        "backup_name": report.get("backup_name", ""),
        "start_time": report.get("start_time", ""),
        "end_time": report.get("end_time", ""),
        "duration_seconds": report.get("duration_seconds", 0),
        "dry_run": bool(report.get("dry_run")),
        "interrupted": bool(report.get("interrupted")),
        "status": report.get("status", "failure"),
        "targets_requested": report.get("targets_requested", 0),
        "retention": report.get("retention", {}),
        "warnings": report.get("warnings", []),
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "email_report": report.get("email_report", {}),
    }
    last_run_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "text_report_path": str(text_path),
        "json_report_path": str(json_path),
        "last_run_path": str(last_run_path),
    }


def prune_repository(
    target: dict[str, Any],
    global_config: dict[str, Any],
    dry_run: bool = False,
    yes: bool = False,
) -> dict[str, Any]:
    target_name = str(target.get("TARGET_NAME", "<unknown>"))
    retention = parse_retention_values(global_config)
    result: dict[str, Any] = {
        "target_name": target_name,
        "repository": str(target.get("RESTIC_REPOSITORY", "")),
        "dry_run": dry_run,
        "retention": retention,
        "status": "success",
        "command_summary": "",
        "stdout": "",
        "stderr": "",
        "warnings": [],
        "errors": [],
        "interrupted": False,
    }

    preflight = validate_restic_preflight(global_config, target)
    result["warnings"].extend(preflight.warnings)
    if preflight.errors:
        result["errors"].extend(preflight.errors)
        result["warnings"] = _dedupe_messages(result["warnings"])
        result["errors"] = _dedupe_messages(result["errors"])
        result["status"] = "failure"
        return result

    try:
        initialized = repo_is_initialized(target, global_config)
    except OperationInterruptedError as exc:
        result["errors"].append(str(exc))
        result["interrupted"] = True
        result["warnings"] = _dedupe_messages(result["warnings"])
        result["errors"] = _dedupe_messages(result["errors"])
        result["status"] = "interrupted"
        return result
    except RuntimeError as exc:
        result["errors"].append(str(exc))
        result["warnings"] = _dedupe_messages(result["warnings"])
        result["errors"] = _dedupe_messages(result["errors"])
        result["status"] = "failure"
        return result

    if not initialized:
        result["errors"].append(
            f"Repository is not initialized yet for target {target_name}. Run sudo server-backup repo init {target_name}."
        )
        result["warnings"] = _dedupe_messages(result["warnings"])
        result["errors"] = _dedupe_messages(result["errors"])
        result["status"] = "failure"
        return result

    env = build_restic_env(global_config, target)
    command = build_restic_base_command(target) + build_forget_args(global_config, dry_run=dry_run)
    result["command_summary"] = _format_command(command)
    try:
        completed = run_restic_command(command, env)
    except OperationInterruptedError as exc:
        result["errors"].append(str(exc))
        result["interrupted"] = True
        result["warnings"] = _dedupe_messages(result["warnings"])
        result["errors"] = _dedupe_messages(result["errors"])
        result["status"] = "interrupted"
        return result
    result["stdout"] = _sanitize_output(completed.stdout or "")
    result["stderr"] = _sanitize_output(completed.stderr or "")
    if completed.returncode != 0:
        result["errors"].append(explain_restic_failure(completed))
    elif dry_run:
        result["warnings"].append("Dry-run only. No snapshots were removed and no prune was executed.")
    elif not yes:
        result["warnings"].append("Prune executed without explicit --yes flag tracking in result object.")

    result["warnings"] = _dedupe_messages(result["warnings"])
    result["errors"] = _dedupe_messages(result["errors"])
    result["status"] = _status_from_parts(result["errors"], result["warnings"])
    return result


def prune_all_repositories(
    global_config: dict[str, Any],
    targets: list[dict[str, Any]],
    dry_run: bool = False,
    yes: bool = False,
) -> dict[str, Any]:
    start = datetime.now(UTC)
    report: dict[str, Any] = {
        "hostname": os.uname().nodename,
        "backup_name": str(global_config.get("BACKUP_NAME", "")),
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": "",
        "duration_seconds": 0.0,
        "dry_run": dry_run,
        "retention": {},
        "targets_requested": len(targets),
        "target_results": [],
        "warnings": [],
        "errors": [],
        "status": "failure",
        "interrupted": False,
        "text_report_path": "",
        "json_report_path": "",
    }

    try:
        report["retention"] = parse_retention_values(global_config)
    except ValueError as exc:
        report["errors"].append(str(exc))
    else:
        if not targets:
            report["errors"].append("No targets are configured.")

    if not report["errors"]:
        try:
            with restic_repo_lock(timeout_seconds=30):
                target_results: list[dict[str, Any]] = []
                for target in targets:
                    target_results.append(prune_repository(target, global_config, dry_run=dry_run, yes=yes))
                    if target_results[-1].get("interrupted"):
                        report["interrupted"] = True
                        break
                report["target_results"] = target_results
        except RuntimeError as exc:
            report["errors"].append(str(exc))

    for target_result in report.get("target_results", []):
        report["warnings"].extend(target_result.get("warnings", []))
        report["errors"].extend(target_result.get("errors", []))

    report["warnings"] = _dedupe_messages(report["warnings"])
    report["errors"] = _dedupe_messages(report["errors"])
    if report.get("interrupted"):
        report["status"] = "interrupted"
    elif report["target_results"]:
        report["status"] = _aggregate_status(report["target_results"])
    if not report.get("interrupted"):
        report["status"] = _status_from_parts(report["errors"], report["warnings"]) if report["errors"] or report["warnings"] else report["status"]
    if not report.get("interrupted") and not report["errors"] and not report["warnings"] and report["target_results"]:
        report["status"] = _aggregate_status(report["target_results"])

    end = datetime.now(UTC)
    report["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    report["duration_seconds"] = round((end - start).total_seconds(), 3)
    report_dir = str(global_config.get("REPORT_DIR", "/var/lib/server-backup/reports"))
    state_dir = str(global_config.get("STATE_DIR", "/var/lib/server-backup/state"))
    report.update(_write_prune_report(report, report_dir, state_dir))

    if report.get("text_report_path") and not report.get("interrupted"):
        text_path = Path(str(report["text_report_path"]))
        report_text = text_path.read_text(encoding="utf-8") if text_path.exists() else _render_prune_report_text(report)
        email_result = send_email_report("prune", str(report.get("status", "failure")), report_text, global_config)
        report["email_report"] = email_result
        if email_result.get("attempted") and not email_result.get("success"):
            report["warnings"].append(f"Email report failed: {email_result.get('error', 'unknown error')}")
        report["warnings"] = _dedupe_messages(report["warnings"])
        if report.get("status") != "failure":
            report["status"] = _status_from_parts(report["errors"], report["warnings"])
        report.update(_write_prune_report(report, report_dir, state_dir))
    return report


def explain_restic_failure(result: subprocess.CompletedProcess[str]) -> str:
    output = _combined_output(result)
    classified = _classify_error(output)
    if classified and output:
        return f"{classified}\n{output}"
    if classified:
        return classified
    return output or "Command failed without additional output."
