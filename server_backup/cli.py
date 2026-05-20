from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from . import __version__
from .backup import LAST_BACKUP_RUN_FILE, run_backup
from .coverage import LAST_COVERAGE_AUDIT_FILE, render_coverage_report_json, run_coverage_audit
from .config import (
    ConfigPermissionError,
    config_file_exists,
    load_global_config,
    load_profiles,
    load_targets,
    parse_config_file,
    redact_config,
)
from .db import (
    list_database_dumps,
    load_database_dumps_from_profiles,
    redact_db_config,
    run_db_add,
    run_dump_test,
    select_database_dump,
    test_database_connection,
)
from .docker import (
    backup_profile_file,
    collect_bind_mounts,
    collect_container_mounts,
    collect_named_volumes,
    compare_mounts_to_backup_paths,
    discover_compose_files as docker_discover_compose_files,
    discover_env_files_near_compose,
    docker_available,
    list_containers as docker_list_containers,
    list_volumes as docker_list_volumes,
    suggest_missing_docker_paths,
    update_profile_backup_paths,
    write_docker_inventory,
)
from .email_report import LAST_EMAIL_REPORT_FILE, send_test_email
from .health import build_operations_status, run_health_check, timer_enabled_status as health_timer_enabled_status, timer_next_run as health_timer_next_run
from .restic import (
    INTERRUPTED_MESSAGE,
    LAST_PRUNE_RUN_FILE,
    OperationInterruptedError,
    check_repository,
    explain_restic_failure,
    init_repository,
    list_snapshots,
    parse_retention_values,
    prune_all_repositories,
    repo_is_initialized,
    restic_repo_lock,
    select_target,
    validate_retention_config,
    validate_restic_preflight,
)
from .restore import LAST_RESTORE_TEST_FILE, run_restore_test
from .ssh import DEFAULT_KNOWN_HOSTS, DEFAULT_SSH_CONFIG, SshCommandError, test_sftp_batch, test_ssh_batch
from .validation import LAST_PRODUCTION_VALIDATION_FILE, run_production_validation
from .validators import (
    ValidationResult,
    validate_all,
    validate_global_config,
    validate_profile_config,
    validate_target_config,
)
from .wizard import run_global_setup, run_profile_add, run_target_add, sanitize_target_name


CONFIG_ROOT = Path("/etc/server-backup")
CACHE_ROOT = Path("/var/cache/restic")
DATA_ROOT = Path("/var/lib/server-backup")
TARGETS_DIR = CONFIG_ROOT / "targets.d"
PROFILES_DIR = CONFIG_ROOT / "profiles.d"
BACKUP_CONF = CONFIG_ROOT / "backup.conf"
DEFAULT_TIMER_PATH = Path("/etc/systemd/system/server-backup.timer")
LAST_BACKUP_RUN_PATH = DATA_ROOT / "state" / LAST_BACKUP_RUN_FILE
LAST_PRUNE_RUN_PATH = DATA_ROOT / "state" / LAST_PRUNE_RUN_FILE
LAST_RESTORE_TEST_PATH = DATA_ROOT / "state" / LAST_RESTORE_TEST_FILE
LAST_EMAIL_REPORT_PATH = DATA_ROOT / "state" / LAST_EMAIL_REPORT_FILE
LAST_COVERAGE_AUDIT_PATH = DATA_ROOT / "state" / LAST_COVERAGE_AUDIT_FILE
LAST_PRODUCTION_VALIDATION_PATH = DATA_ROOT / "state" / LAST_PRODUCTION_VALIDATION_FILE

NOT_IMPLEMENTED_MESSAGE = "Not implemented yet. This command will be implemented in a future PR."


@dataclass(frozen=True)
class StatusCheck:
    label: str
    path: Path


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except PermissionError:
        return True


def _is_accessible(path: Path) -> bool:
    try:
        path.stat()
        return True
    except PermissionError:
        return False
    except FileNotFoundError:
        return False


def _status_marker(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def _validation_status(result: ValidationResult) -> str:
    if result.errors:
        return "ERROR"
    if result.warnings:
        return "WARNING"
    return "OK"


def _boolish_to_yes_no(value: object) -> str:
    return "yes" if str(value).strip().lower() == "true" else "no"


def _load_config_bundle() -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    return load_global_config(BACKUP_CONF), load_targets(TARGETS_DIR), load_profiles(PROFILES_DIR)


def _target_path(target_name: str) -> Path:
    return TARGETS_DIR / f"{sanitize_target_name(target_name)}.env"


def _load_target_by_name(target_name: str) -> dict[str, object] | None:
    direct_path = _target_path(target_name)
    if config_file_exists(direct_path):
        return parse_config_file(direct_path)

    for target in load_targets(TARGETS_DIR):
        if str(target.get("TARGET_NAME", "")).strip() == target_name:
            return target
    return None


def _load_database_dump_bundle() -> list[dict[str, object]]:
    profiles = load_profiles(PROFILES_DIR)
    return load_database_dumps_from_profiles(profiles)


def _select_profile_by_name(profile_name: str, profiles: list[dict[str, object]]) -> dict[str, object]:
    for profile in profiles:
        if str(profile.get("PROFILE_NAME", "")).strip() == profile_name:
            return profile
    raise ValueError(f"Profile not found: {profile_name}")


def _print_validation(result: ValidationResult) -> None:
    for message in result.errors:
        print(f"  error: {message}")
    for message in result.warnings:
        print(f"  warning: {message}")


def _resolve_repo_targets(
    target_name: str | None,
    all_targets: bool,
    targets: list[dict[str, object]],
) -> list[dict[str, object]]:
    if all_targets:
        if not targets:
            raise ValueError("No targets are configured.")
        return targets
    if not target_name:
        raise ValueError("Provide a target name or use --all.")
    return [select_target(target_name, targets)]


def _run_repo_operation_for_target(
    label: str,
    target: dict[str, object],
    global_config: dict[str, object],
    operation,
) -> int:
    target_name = str(target.get("TARGET_NAME", "<unknown>"))
    print(f"server-backup repo {label} {target_name}")
    print("")

    preflight = validate_restic_preflight(global_config, target)
    print(f"Preflight: {_validation_status(preflight)}")
    _print_validation(preflight)
    if preflight.errors:
        return 1

    try:
        return int(operation(target_name, target, global_config))
    except OperationInterruptedError:
        print(INTERRUPTED_MESSAGE)
        return 130
    except RuntimeError as exc:
        print(str(exc))
        return 1


def _run_repo_command(
    command_name: str,
    target_name: str | None,
    all_targets: bool,
    operation,
) -> int:
    try:
        global_config = load_global_config(BACKUP_CONF)
        targets = load_targets(TARGETS_DIR)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    if global_config.get("__missing__"):
        print("backup.conf is missing. Run sudo server-backup setup first.")
        return 1

    try:
        selected_targets = _resolve_repo_targets(target_name, all_targets, targets)
    except ValueError as exc:
        print(str(exc))
        return 1

    try:
        with restic_repo_lock(timeout_seconds=30):
            if all_targets:
                overall = 0
                for index, target in enumerate(selected_targets):
                    if index:
                        print("")
                    target_exit = _run_repo_operation_for_target(command_name, target, global_config, operation)
                    if target_exit == 130:
                        return 130
                    if target_exit != 0:
                        overall = target_exit
                return overall

            return _run_repo_operation_for_target(command_name, selected_targets[0], global_config, operation)
    except KeyboardInterrupt:
        print(INTERRUPTED_MESSAGE)
        return 130
    except RuntimeError as exc:
        print(str(exc))
        return 1


def _print_messages(title: str, messages: list[str]) -> None:
    print(title)
    for message in messages:
        print(f"  - {message}")


def _print_permission_denied() -> None:
    print("Permission denied. Run with sudo to inspect root-only configuration.")


def _load_last_backup_run(path: Path) -> dict[str, object] | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (PermissionError, OSError, json.JSONDecodeError):
        return None


def _confirm_prune() -> bool:
    raw = input("This operation can permanently remove snapshots and prune repository data. Continue? [y/N]: ")
    return raw.strip().lower() in {"y", "yes"}


def _timer_enabled_status() -> tuple[str, str]:
    return health_timer_enabled_status()


def _timer_next_run() -> tuple[str, str]:
    return health_timer_next_run()


def cmd_setup(_: argparse.Namespace) -> int:
    try:
        result = run_global_setup()
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0 if result.ok else 1


def cmd_target_add(_: argparse.Namespace) -> int:
    try:
        result = run_target_add()
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0 if result.ok else 1


def cmd_target_test(args: argparse.Namespace) -> int:
    try:
        target = _load_target_by_name(args.target)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    if target is None:
        print(f"Target not found: {args.target}")
        print("Run sudo server-backup target add first.")
        return 1

    validation = validate_target_config(target)
    print(f"server-backup target test {target.get('TARGET_NAME', args.target)}")
    print("")
    print(f"Validation: {_validation_status(validation)}")
    for message in validation.errors:
        print(f"  error: {message}")
    for message in validation.warnings:
        print(f"  warning: {message}")

    if validation.errors:
        return 1

    target_type = str(target.get("TARGET_TYPE", "")).strip()
    if target_type != "sftp":
        print(f"Target type '{target_type or '<missing>'}' is not supported for testing in the MVP.")
        return 1

    ssh_alias = str(target.get("SSH_HOST_ALIAS", "")).strip()
    ssh_config_file = Path(str(target.get("SSH_CONFIG_FILE", DEFAULT_SSH_CONFIG))).expanduser()
    ssh_identity_file = Path(str(target.get("SSH_IDENTITY_FILE", ""))).expanduser()
    ssh_known_hosts_file = Path(str(target.get("SSH_KNOWN_HOSTS_FILE", DEFAULT_KNOWN_HOSTS))).expanduser()

    missing_paths: list[str] = []
    if not ssh_alias:
        missing_paths.append("SSH_HOST_ALIAS is missing")
    if not ssh_config_file.exists():
        missing_paths.append(f"SSH config file not found: {ssh_config_file}")
    if not ssh_identity_file.exists():
        missing_paths.append(f"SSH identity file not found: {ssh_identity_file}")
    if not ssh_known_hosts_file.exists():
        missing_paths.append(f"SSH known_hosts file not found: {ssh_known_hosts_file}")

    if missing_paths:
        print("")
        for message in missing_paths:
            print(f"ERROR: {message}")
        return 1

    try:
        ssh_result = test_ssh_batch(ssh_alias, ssh_config_file)
        sftp_result = test_sftp_batch(ssh_alias, ssh_config_file)
    except SshCommandError as exc:
        print(f"Command error: {exc}")
        return 1

    print("")
    if ssh_result.returncode == 0:
        print(f"SSH batch test: OK for {ssh_alias}")
    else:
        detail = (ssh_result.stderr or ssh_result.stdout).strip() or "command rejected"
        print(f"SSH batch test: WARNING for {ssh_alias}")
        print(f"  {detail}")
        print("  This is non-fatal if the NAS only exposes internal-sftp.")

    if sftp_result.returncode == 0:
        print(f"SFTP batch test: OK for {ssh_alias}")
        output = (sftp_result.stdout or "").strip()
        if output:
            for line in output.splitlines():
                print(f"  {line}")
        return 0

    detail = (sftp_result.stderr or sftp_result.stdout).strip() or "SFTP connection failed"
    print(f"SFTP batch test: ERROR for {ssh_alias}")
    print(f"  {detail}")
    return 1


def cmd_profile_add(_: argparse.Namespace) -> int:
    try:
        result = run_profile_add()
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0 if result.ok else 1


def cmd_db_add(args: argparse.Namespace) -> int:
    try:
        result = run_db_add(profile_name=args.profile)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup db add")
    print("")
    print(f"Profile: {result.get('profile_name', '<unknown>')}")
    print(f"Dump name: {result.get('dump_name', '<unknown>')}")
    print("DATABASE_DUMPS entry added to profile.")
    if result.get("test_result"):
        print("Connection test: OK")
    if result.get("dump_test_result"):
        print(f"Dump test: {str(result['dump_test_result'].get('status', 'failure')).upper()}")
    return 0


def cmd_db_list(_: argparse.Namespace) -> int:
    try:
        dumps = list_database_dumps(load_profiles(PROFILES_DIR))
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup db list")
    print("")
    print(f"Configured database dumps: {len(dumps)}")
    for dump in dumps:
        databases = dump.get("databases", [])
        databases_display = ",".join(databases) if isinstance(databases, list) and databases else "<default>"
        globals_enabled = "true" if dump.get("globals") else "false"
        all_enabled = "true" if dump.get("all") else "false"
        print(
            f"  - {dump.get('name', '<unknown>')} | profile={dump.get('__profile_name__', '<unknown>')} "
            f"| engine={dump.get('engine', '<unknown>')} | mode={dump.get('mode', '<unknown>')}"
        )
        if dump.get("container"):
            print(f"    container={dump.get('container')}")
        else:
            print(
                f"    host={dump.get('host', '<unknown>')} port={dump.get('port', '<unknown>')}"
            )
        print(
            f"    user={dump.get('user', '<unknown>')} | databases={databases_display} "
            f"| all={all_enabled} | globals={globals_enabled}"
        )
    return 0


def _resolve_database_dumps_for_command(name: str | None, all_dumps: bool) -> list[dict[str, object]]:
    dumps = _load_database_dump_bundle()
    if all_dumps:
        if not dumps:
            raise ValueError("No database dumps are configured. Run sudo server-backup db add.")
        return dumps
    if not name:
        raise ValueError("Provide a database dump name or use --all.")
    return [select_database_dump(name, dumps)]


def cmd_db_test(args: argparse.Namespace) -> int:
    try:
        selected_dumps = _resolve_database_dumps_for_command(args.name, args.all)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    overall = 0
    for index, dump in enumerate(selected_dumps):
        if index:
            print("")
        result = test_database_connection(dump)
        redacted = redact_db_config(result)
        print(f"server-backup db test {dump.get('name', '<unknown>')}")
        print("")
        print(f"Profile: {dump.get('__profile_name__', '<unknown>')}")
        print(f"Command: {redacted.get('command_summary', '')}")
        print(f"Status: {str(redacted.get('status', 'failure')).upper()}")
        if redacted.get("stdout"):
            print("stdout:")
            for line in str(redacted["stdout"]).splitlines():
                print(f"  {line}")
        if redacted.get("stderr"):
            print("stderr:")
            for line in str(redacted["stderr"]).splitlines():
                print(f"  {line}")
        if not redacted.get("success"):
            overall = 1
    return overall


def cmd_db_dump_test(args: argparse.Namespace) -> int:
    try:
        selected_dumps = _resolve_database_dumps_for_command(args.name, args.all)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    overall = 0
    for index, dump in enumerate(selected_dumps):
        if index:
            print("")
        try:
            result = run_dump_test(dump, keep_output=bool(args.keep_output))
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
            print(f"server-backup db dump-test {dump.get('name', '<unknown>')}")
            print("")
            print(str(exc))
            overall = 1
            continue

        redacted = redact_db_config(result)
        print(f"server-backup db dump-test {dump.get('name', '<unknown>')}")
        print("")
        print(f"Profile: {dump.get('__profile_name__', '<unknown>')}")
        print(f"Status: {str(redacted.get('status', 'failure')).upper()}")
        print(f"Keep output: {'yes' if redacted.get('keep_output') else 'no'}")
        print(f"Output dir: {redacted.get('output_dir', '')}")
        print(f"Output cleaned: {'yes' if redacted.get('output_cleaned') else 'no'}")
        if redacted.get("files"):
            print("Files:")
            for dump_file in redacted.get("files", []):
                print(f"  {dump_file}")
        for warning in redacted.get("warnings", []):
            print(f"Warning: {warning}")
        for error in redacted.get("errors", []):
            print(f"Error: {error}")
        if redacted.get("status") == "failure":
            overall = 1
    return overall


def cmd_repo_init(args: argparse.Namespace) -> int:
    def _operation(target_name: str, target: dict[str, object], global_config: dict[str, object]) -> int:
        try:
            if repo_is_initialized(target, global_config):
                print("Repository already initialized.")
                return 0
        except OperationInterruptedError:
            raise
        except RuntimeError as exc:
            print(str(exc))
            return 1

        result = init_repository(target, global_config)
        if result.returncode == 0:
            print("Repository initialized successfully.")
            output = (result.stdout or "").strip()
            if output:
                print(output)
            return 0

        print(explain_restic_failure(result))
        return 1

    return _run_repo_command("init", args.target, args.all, _operation)


def cmd_repo_check(args: argparse.Namespace) -> int:
    def _operation(_: str, target: dict[str, object], global_config: dict[str, object]) -> int:
        result = check_repository(target, global_config)
        if result.returncode == 0:
            print("Repository check succeeded.")
            output = (result.stdout or "").strip()
            if output:
                print(output)
            return 0

        print(explain_restic_failure(result))
        return 1

    return _run_repo_command("check", args.target, args.all, _operation)


def cmd_repo_snapshots(args: argparse.Namespace) -> int:
    def _operation(_: str, target: dict[str, object], global_config: dict[str, object]) -> int:
        result = list_snapshots(target, global_config)
        if result.returncode == 0:
            output = (result.stdout or "").strip()
            if output:
                print(output)
            else:
                print("No snapshots found.")
            return 0

        print(explain_restic_failure(result))
        return 1

    return _run_repo_command("snapshots", args.target, args.all, _operation)


def cmd_repo_prune(args: argparse.Namespace) -> int:
    if not args.all and not args.target:
        parser = getattr(args, "_parser", None)
        if parser is not None:
            parser.print_help()
        else:
            print("Provide a target name or use --all.")
        return 1

    try:
        global_config = load_global_config(BACKUP_CONF)
        targets = load_targets(TARGETS_DIR)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    if global_config.get("__missing__"):
        print("backup.conf is missing. Run sudo server-backup setup first.")
        return 1

    retention_validation = validate_retention_config(global_config)
    if retention_validation.errors:
        for message in retention_validation.errors:
            print(message)
        return 1

    try:
        selected_targets = _resolve_repo_targets(args.target, args.all, targets)
    except ValueError as exc:
        print(str(exc))
        return 1

    if not args.dry_run and not args.yes:
        try:
            retention = parse_retention_values(global_config)
        except ValueError as exc:
            print(str(exc))
            return 1
        print("server-backup repo prune")
        print("")
        print("Destructive operation:")
        print(f"  targets: {len(selected_targets)}")
        print(
            "  retention: "
            f"daily={retention['RETENTION_DAILY']} weekly={retention['RETENTION_WEEKLY']} monthly={retention['RETENTION_MONTHLY']}"
        )
        print("  mode: real prune")
        print("")
        if not _confirm_prune():
            print("Prune cancelled. No changes made.")
            return 0

    try:
        report = prune_all_repositories(
            global_config,
            selected_targets,
            dry_run=bool(args.dry_run),
            yes=bool(args.yes),
        )
    except KeyboardInterrupt:
        print(INTERRUPTED_MESSAGE)
        return 130

    print("server-backup repo prune")
    print("")
    print(f"Targets: {report.get('targets_requested', 0)}")
    print(f"Dry-run: {'yes' if report.get('dry_run') else 'no'}")
    retention = report.get("retention", {})
    print(
        "Retention: "
        f"daily={retention.get('RETENTION_DAILY', '?')} "
        f"weekly={retention.get('RETENTION_WEEKLY', '?')} "
        f"monthly={retention.get('RETENTION_MONTHLY', '?')}"
    )
    print("")
    for warning in report.get("warnings", []):
        print(f"Warning: {warning}")
    for error in report.get("errors", []):
        print(f"Error: {error}")
    if report.get("warnings") or report.get("errors"):
        print("")

    for target_result in report.get("target_results", []):
        print(f"Target {target_result.get('target_name', '<unknown>')}: {str(target_result.get('status', 'failure')).upper()}")
        if target_result.get("command_summary"):
            print(f"  command: {target_result.get('command_summary')}")
        for warning in target_result.get("warnings", []):
            print(f"  warning: {warning}")
        for error in target_result.get("errors", []):
            print(f"  error: {error}")
        if target_result.get("stdout"):
            print("  stdout:")
            for line in str(target_result["stdout"]).splitlines():
                print(f"    {line}")
        if target_result.get("stderr"):
            print("  stderr:")
            for line in str(target_result["stderr"]).splitlines():
                print(f"    {line}")
        print("")

    print(f"Overall: {str(report.get('status', 'failure')).upper()}")
    print("")
    print("Reports:")
    print(f"  {report.get('text_report_path', '')}")
    print(f"  {report.get('json_report_path', '')}")
    if report.get("status") == "interrupted":
        print("")
        print(INTERRUPTED_MESSAGE)
        return 130
    return 1 if report.get("status") == "failure" else 0


def cmd_config_validate(_: argparse.Namespace) -> int:
    try:
        global_config, targets, profiles = _load_config_bundle()
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    print("server-backup config validate")
    print("")

    global_result = validate_global_config(global_config)
    print(f"Global config: {_validation_status(global_result)}")
    if global_result.errors:
        _print_messages("Global errors:", global_result.errors)
    if global_result.warnings:
        _print_messages("Global warnings:", global_result.warnings)

    print("")
    print(f"Targets: {len(targets)}")
    for target in targets:
        result = validate_target_config(target)
        name = str(target.get("TARGET_NAME", target.get("__file__", "<unknown>")))
        print(f"  - {name}: {_validation_status(result)}")
        for message in result.errors:
            print(f"    error: {message}")
        for message in result.warnings:
            print(f"    warning: {message}")

    print("")
    print(f"Profiles: {len(profiles)}")
    for profile in profiles:
        result = validate_profile_config(profile)
        name = str(profile.get("PROFILE_NAME", profile.get("__file__", "<unknown>")))
        print(f"  - {name}: {_validation_status(result)}")
        for message in result.errors:
            print(f"    error: {message}")
        for message in result.warnings:
            print(f"    warning: {message}")

    print("")
    overall = validate_all(global_config, targets, profiles)
    print(f"Overall: {_validation_status(overall)}")
    if overall.errors:
        _print_messages("Overall errors:", overall.errors)
    if overall.warnings:
        _print_messages("Overall warnings:", overall.warnings)
    if overall.errors:
        return 1
    return 0


def cmd_config_show(_: argparse.Namespace) -> int:
    try:
        global_config, targets, profiles = _load_config_bundle()
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    payload = {
        "global": redact_config(global_config),
        "targets": redact_config(targets),
        "profiles": redact_config(profiles),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    try:
        report = run_health_check()
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup health")
    print("")
    print(f"Overall: {str(report.get('status', 'FAILURE')).upper()}")
    print("")
    print("Checks:")
    for check in report.get("checks", []):
        print(f"  [{check.get('severity', 'FAILURE')}] {check.get('code', '')}: {check.get('message', '')}")
    recommendations = report.get("recommendations", [])
    if recommendations:
        print("")
        print("Recommendations:")
        for recommendation in recommendations:
            print(f"  - {recommendation}")

    return 1 if str(report.get("status", "FAILURE")).upper() == "FAILURE" else 0


def cmd_operations_status(_: argparse.Namespace) -> int:
    try:
        global_config, targets, profiles = _load_config_bundle()
        operations = build_operations_status(global_config, targets, profiles)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup operations status")
    print("")
    print("Counts:")
    print(f"  targets: {operations.get('target_count', 0)}")
    print(f"  profiles: {operations.get('profile_count', 0)}")
    print(f"  db dumps: {operations.get('db_dump_count', 0)}")

    timer = operations.get("timer", {})
    print("")
    print("Timer:")
    print(f"  enabled: {timer.get('enabled', 'unknown')}")
    print(f"  next run: {timer.get('next_run', 'unknown')}")

    for section_name, payload in (
        ("Last Backup", operations.get("last_backup", {})),
        ("Last Prune", operations.get("last_prune", {})),
        ("Last Restore Test", operations.get("last_restore_test", {})),
        ("Last Coverage Audit", operations.get("last_coverage_audit", {})),
    ):
        print("")
        print(f"{section_name}:")
        if not payload.get("present"):
            print("  status: missing")
            continue
        print(f"  date: {payload.get('date', '<unknown>')}")
        print(f"  status: {payload.get('status', '<unknown>')}")
        print(f"  report: {payload.get('report', '<unknown>')}")

    last_email = operations.get("last_email", {})
    print("")
    print("Last Email:")
    if not last_email.get("present"):
        print("  status: missing")
    else:
        print(f"  date: {last_email.get('date', '<unknown>')}")
        print(f"  status: {last_email.get('status', '<unknown>')}")
        print(f"  kind: {last_email.get('kind', '<unknown>')}")

    warnings = operations.get("warnings", [])
    if warnings:
        print("")
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    return 0


def cmd_backup_run(args: argparse.Namespace) -> int:
    try:
        report = run_backup(
            dry_run=bool(args.dry_run),
            target_name=args.target,
            profile_name=args.profile,
        )
    except KeyboardInterrupt:
        print(INTERRUPTED_MESSAGE)
        return 130
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup backup run")
    print("")
    print(f"Targets: {report.get('targets_requested', 0)}")
    print(f"Profiles: {report.get('profiles_requested', 0)}")
    print(f"Dry-run: {'yes' if report.get('dry_run') else 'no'}")
    print("")

    for warning in report.get("warnings", []):
        print(f"Warning: {warning}")
    for error in report.get("errors", []):
        print(f"Error: {error}")
    if report.get("warnings") or report.get("errors"):
        print("")

    for target_result in report.get("target_results", []):
        print(f"Target {target_result.get('target_name', '<unknown>')}:")
        for profile_result in target_result.get("profile_results", []):
            profile_status = str(profile_result.get("status", "failure")).upper()
            print(f"  profile {profile_result.get('profile_name', '<unknown>')}: {profile_status}")
            for dump_result in profile_result.get("database_dumps", []):
                print(
                    f"    db dump {dump_result.get('name', '<unknown>')}: "
                    f"{str(dump_result.get('status', 'failure')).upper()}"
                )
            for missing_path in profile_result.get("paths_missing", []):
                print(f"    missing path: {missing_path}")
            for warning in profile_result.get("warnings", []):
                print(f"    warning: {warning}")
            for error in profile_result.get("errors", []):
                print(f"    error: {error}")
        for warning in target_result.get("warnings", []):
            print(f"  warning: {warning}")
        for error in target_result.get("errors", []):
            print(f"  error: {error}")
        print("")

    print(f"Overall: {str(report.get('status', 'failure')).upper()}")
    print("")
    print("Reports:")
    print(f"  {report.get('text_report_path', '')}")
    print(f"  {report.get('json_report_path', '')}")

    if report.get("status") == "interrupted":
        print("")
        print(INTERRUPTED_MESSAGE)
        return 130
    return 1 if report.get("status") == "failure" else 0


def cmd_restore_test(args: argparse.Namespace) -> int:
    if not args.target:
        print("Target is required. Use --target <target>.")
        return 1

    try:
        report = run_restore_test(
            target=args.target,
            snapshot=args.snapshot or "latest",
            profile_name=args.profile,
            includes=args.include,
            output_dir=args.output_dir,
            keep_output=bool(args.keep_output),
        )
    except KeyboardInterrupt:
        print(INTERRUPTED_MESSAGE)
        return 130
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup restore test")
    print("")
    print(f"Target: {report.get('target_name', '<unknown>')}")
    print(f"Requested snapshot: {report.get('requested_snapshot', 'latest')}")
    print(f"Restored snapshot: {report.get('restored_snapshot', 'latest')}")
    print(f"Output dir: {report.get('output_dir', '')}")
    print(f"Keep output: {'yes' if report.get('keep_output') else 'no'}")
    print(f"Output cleaned: {'yes' if report.get('output_cleaned') else 'no'}")
    print("")

    for warning in report.get("warnings", []):
        print(f"Warning: {warning}")
    for error in report.get("errors", []):
        print(f"Error: {error}")
    if report.get("warnings") or report.get("errors"):
        print("")

    if report.get("profile_checks"):
        for check in report["profile_checks"]:
            print(f"Profile {check.get('profile_name', '<unknown>')}: {str(check.get('status', 'failure')).upper()}")
            for warning in check.get("warnings", []):
                print(f"  warning: {warning}")
            for error in check.get("errors", []):
                print(f"  error: {error}")
        print("")

    if report.get("include_checks"):
        for check in report["include_checks"]:
            print(f"Include {check.get('include', '<unknown>')}: {str(check.get('status', 'failure')).upper()}")
        print("")

    print(f"Files restored: {report.get('restored_files', {}).get('file_count', 0)}")
    print(f"Approx size: {report.get('restored_files', {}).get('total_size_bytes', 0)} bytes")
    print("")
    print(f"Overall: {str(report.get('status', 'failure')).upper()}")
    print("")
    print("Reports:")
    print(f"  {report.get('text_report_path', '')}")
    print(f"  {report.get('json_report_path', '')}")

    if report.get("status") == "interrupted":
        print("")
        print(INTERRUPTED_MESSAGE)
        return 130
    return 1 if report.get("status") == "failure" else 0


def _docker_search_paths(profiles: list[dict[str, object]]) -> list[str]:
    search_paths = ["/srv", "/opt", "/home"]
    for profile in profiles:
        raw_paths = profile.get("BACKUP_PATHS", [])
        if isinstance(raw_paths, list):
            search_paths.extend(str(item).strip() for item in raw_paths if str(item).strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for path in search_paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _build_docker_inventory_payload(
    global_config: dict[str, object],
    profiles: list[dict[str, object]],
) -> dict[str, object]:
    availability = docker_available()
    payload: dict[str, object] = {
        "hostname": Path("/etc/hostname").read_text(encoding="utf-8").strip() if Path("/etc/hostname").exists() else "",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "docker": availability,
        "running_containers": [],
        "stopped_containers": [],
        "images": [],
        "volumes": [],
        "networks": [],
        "mounts": [],
        "compose_files": [],
        "env_files": [],
        "warnings": [],
        "state_dir": str(global_config.get("STATE_DIR") or DATA_ROOT / "state"),
    }
    if not availability.get("available"):
        payload["warnings"] = [str(availability.get("reason", "docker unavailable"))]
        return payload

    try:
        containers = docker_list_containers(all_containers=True)
        payload["running_containers"] = [container for container in containers if container.get("running")]
        payload["stopped_containers"] = [container for container in containers if not container.get("running")]
    except RuntimeError as exc:
        payload["warnings"] = [str(exc)]
        return payload

    try:
        payload["volumes"] = docker_list_volumes()
    except RuntimeError as exc:
        payload.setdefault("warnings", []).append(str(exc))

    try:
        payload["mounts"] = collect_container_mounts(all_containers=True)
    except RuntimeError as exc:
        payload.setdefault("warnings", []).append(str(exc))

    version_available = docker_available()
    docker_bin = version_available.get("docker_bin")
    if docker_bin:
        try:
            images_result = subprocess.run(
                [str(docker_bin), "image", "ls", "--format", "{{json .}}"],
                check=False,
                capture_output=True,
                text=True,
            )
            if images_result.returncode == 0:
                payload["images"] = [
                    json.loads(line) for line in images_result.stdout.splitlines() if line.strip()
                ]
        except (OSError, json.JSONDecodeError):
            pass
        try:
            networks_result = subprocess.run(
                [str(docker_bin), "network", "ls", "--format", "{{json .}}"],
                check=False,
                capture_output=True,
                text=True,
            )
            if networks_result.returncode == 0:
                payload["networks"] = [
                    json.loads(line) for line in networks_result.stdout.splitlines() if line.strip()
                ]
        except (OSError, json.JSONDecodeError):
            pass

    compose_files = docker_discover_compose_files(_docker_search_paths(profiles))
    payload["compose_files"] = compose_files
    payload["env_files"] = discover_env_files_near_compose(compose_files)
    return payload


def cmd_docker_scan(_: argparse.Namespace) -> int:
    try:
        global_config = load_global_config(BACKUP_CONF)
        profiles = load_profiles(PROFILES_DIR)
        inventory = _build_docker_inventory_payload(global_config, profiles)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup docker scan")
    print("")
    print(f"Docker available: {'yes' if inventory.get('docker', {}).get('available') else 'no'}")
    if inventory.get("docker", {}).get("version"):
        print(f"Docker version: {inventory['docker']['version']}")
    if inventory.get("warnings"):
        for warning in inventory["warnings"]:
            print(f"Warning: {warning}")
        return 0
    print(f"Running containers: {len(inventory.get('running_containers', []))}")
    print(f"Named volumes: {len(inventory.get('volumes', []))}")
    print(f"Bind mounts: {len(collect_bind_mounts(all_containers=True))}")
    print(f"Compose files: {len(inventory.get('compose_files', []))}")
    print(f".env files: {len(inventory.get('env_files', []))}")
    print("")
    for container in inventory.get("running_containers", []):
        print(f"- {container.get('name', '<unknown>')} | image={container.get('image', '')}")
    return 0


def cmd_docker_inventory(_: argparse.Namespace) -> int:
    try:
        global_config = load_global_config(BACKUP_CONF)
        profiles = load_profiles(PROFILES_DIR)
        inventory = _build_docker_inventory_payload(global_config, profiles)
        paths = write_docker_inventory(inventory, inventory.get("state_dir", DATA_ROOT / "state"))
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup docker inventory")
    print("")
    print(f"Running containers: {len(inventory.get('running_containers', []))}")
    print(f"Stopped containers: {len(inventory.get('stopped_containers', []))}")
    print(f"Volumes: {len(inventory.get('volumes', []))}")
    print(f"Mounts: {len(inventory.get('mounts', []))}")
    print(f"Compose files: {len(inventory.get('compose_files', []))}")
    print(f".env files: {len(inventory.get('env_files', []))}")
    print("")
    print("Reports:")
    print(f"  {paths.get('text_report_path', '')}")
    print(f"  {paths.get('json_report_path', '')}")
    return 0


def cmd_docker_coverage(_: argparse.Namespace) -> int:
    try:
        profiles = load_profiles(PROFILES_DIR)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    availability = docker_available()
    print("server-backup docker coverage")
    print("")
    if not availability.get("available"):
        print(f"Docker unavailable: {availability.get('reason', 'unknown reason')}")
        return 0

    mounts = collect_container_mounts(all_containers=False)
    coverage = compare_mounts_to_backup_paths(mounts, profiles)
    compose_files = docker_discover_compose_files(_docker_search_paths(profiles))
    env_files = discover_env_files_near_compose(compose_files)
    backup_paths: list[str] = []
    for profile in profiles:
        raw_paths = profile.get("BACKUP_PATHS", [])
        if isinstance(raw_paths, list):
            backup_paths.extend(str(item).strip() for item in raw_paths if str(item).strip())

    for status_name in ("covered", "covered-by-logical-dump", "uncovered"):
        matching = [item for item in coverage if item.get("coverage_status") == status_name]
        if not matching:
            continue
        print(f"{status_name}:")
        for item in matching:
            label = item.get("name") or item.get("candidate_path") or item.get("destination")
            print(
                f"  - {item.get('container_name', '<unknown>')} | {item.get('type', '')} | "
                f"{label} | category={item.get('category', '')}"
            )
        print("")

    uncovered_compose = []
    for compose_file in compose_files:
        compose_path = Path(compose_file)
        covered = any(
            str(compose_path) == backup_path or str(compose_path).startswith(f"{backup_path.rstrip('/')}/")
            for backup_path in backup_paths
        )
        if not covered:
            uncovered_compose.append(compose_file)
    uncovered_env = []
    for env_file in env_files:
        covered = any(
            str(env_file) == backup_path or str(env_file).startswith(f"{backup_path.rstrip('/')}/")
            for backup_path in backup_paths
        )
        if not covered:
            uncovered_env.append(env_file)

    print(f"Compose files uncovered: {len(uncovered_compose)}")
    for item in uncovered_compose:
        print(f"  - {item}")
    print(f".env files uncovered: {len(uncovered_env)}")
    for item in uncovered_env:
        print(f"  - {item}")
    return 0


def cmd_docker_suggest_profile_updates(_: argparse.Namespace) -> int:
    try:
        profiles = load_profiles(PROFILES_DIR)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    availability = docker_available()
    print("server-backup docker suggest-profile-updates")
    print("")
    if not availability.get("available"):
        print(f"Docker unavailable: {availability.get('reason', 'unknown reason')}")
        return 0

    suggestions = suggest_missing_docker_paths(profiles, collect_container_mounts(all_containers=False))
    if not suggestions:
        print("No missing Docker paths were found.")
        return 0

    for suggestion in suggestions:
        suggested_profile = suggestion.get("suggested_profile") or "<choose-profile>"
        mount = suggestion.get("mount", {})
        volume_name = suggestion.get("volume_name", "")
        if volume_name:
            command = f"sudo server-backup docker add-missing-paths --profile {suggested_profile} --volume {volume_name}"
        else:
            command = f"sudo server-backup docker add-missing-paths --profile {suggested_profile}"
        print(
            f"- container={suggestion.get('container_name', '<unknown>')} "
            f"path={suggestion.get('candidate_path', '')} "
            f"category={suggestion.get('category', '')}"
        )
        print(f"  reason: {suggestion.get('reason', '')}")
        if mount.get("is_database"):
            print("  note: This looks like a database volume. A logical DATABASE_DUMPS entry is preferred. Raw volume backup is optional.")
        print(f"  suggested command: {command}")
    return 0


def cmd_docker_add_missing_paths(args: argparse.Namespace) -> int:
    try:
        profiles = load_profiles(PROFILES_DIR)
        profile = _select_profile_by_name(args.profile, profiles)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    availability = docker_available()
    if not availability.get("available"):
        print(f"Docker unavailable: {availability.get('reason', 'unknown reason')}")
        return 1

    suggestions = suggest_missing_docker_paths(profiles, collect_container_mounts(all_containers=False))
    filtered = []
    for suggestion in suggestions:
        if args.volume and suggestion.get("volume_name") != args.volume:
            continue
        if args.all_volumes and not suggestion.get("volume_name"):
            continue
        if suggestion.get("suggested_profile") not in ("", args.profile):
            continue
        filtered.append(suggestion)

    if not args.volume and not args.all_volumes:
        filtered = [item for item in filtered if item.get("suggested_profile") in ("", args.profile)]

    if not filtered:
        print("No candidate Docker paths were found for this profile.")
        return 0

    print("server-backup docker add-missing-paths")
    print("")
    print(f"Profile: {args.profile}")
    selected_paths: list[str] = []
    for suggestion in filtered:
        candidate_path = str(suggestion.get("candidate_path", "")).strip()
        if not candidate_path:
            continue
        print(f"Candidate: {candidate_path}")
        print(f"  container: {suggestion.get('container_name', '<unknown>')}")
        print(f"  category: {suggestion.get('category', '')}")
        print(f"  reason: {suggestion.get('reason', '')}")
        if suggestion.get("requires_explicit_db_confirmation"):
            print("  This looks like a database volume. A logical DATABASE_DUMPS entry is preferred. Raw volume backup is optional.")
        if args.dry_run:
            print("  action: would add")
            selected_paths.append(candidate_path)
            continue
        if input(f"Add this path to {args.profile}? [y/N]: ").strip().lower() in {"y", "yes"}:
            selected_paths.append(candidate_path)
        else:
            print("  skipped")

    if args.dry_run:
        print("")
        print("Dry-run only. No profile was modified.")
        if selected_paths:
            print("Paths that would be added:")
            for path in selected_paths:
                print(f"  - {path}")
        return 0

    if not selected_paths:
        print("No paths selected. Profile unchanged.")
        return 0

    try:
        result = update_profile_backup_paths(str(profile.get("__file__", "")), selected_paths)
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("")
    if result.get("backup_path"):
        print(f"Profile backup: {result.get('backup_path')}")
    if result.get("added_paths"):
        print("Added paths:")
        for path in result["added_paths"]:
            print(f"  - {path}")
    if result.get("skipped_paths"):
        print("Already present:")
        for path in result["skipped_paths"]:
            print(f"  - {path}")
    validation = result.get("validation")
    if isinstance(validation, ValidationResult):
        print(f"Validation: {_validation_status(validation)}")
        _print_validation(validation)
        return 1 if validation.errors else 0
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    checks = [
        StatusCheck("/etc/server-backup", CONFIG_ROOT),
        StatusCheck("/etc/server-backup/backup.conf", BACKUP_CONF),
        StatusCheck("/etc/server-backup/targets.d", TARGETS_DIR),
        StatusCheck("/etc/server-backup/profiles.d", PROFILES_DIR),
        StatusCheck("/var/cache/restic", CACHE_ROOT),
        StatusCheck("/var/lib/server-backup", DATA_ROOT),
    ]

    permission_denied = False
    global_config: dict[str, object] | None = None
    targets: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []

    try:
        global_config, targets, profiles = _load_config_bundle()
    except ConfigPermissionError:
        permission_denied = True

    print("server-backup status")
    print(f"Version: {__version__}")
    print("")
    print("Paths:")
    for check in checks:
        exists = _safe_exists(check.path)
        line = f"  [{_status_marker(exists)}] {check.label}"
        if exists and not _is_accessible(check.path):
            line += " (present, root-only)"
        print(line)

    print("")
    print("Global Config:")
    if not config_file_exists(BACKUP_CONF):
        print("  backup.conf: absent")
    elif permission_denied or global_config is None:
        print("  backup.conf: present, root-only")
        print("  CONFIG_VERSION: unknown")
        print("  BACKUP_NAME: unknown")
    else:
        global_result = validate_global_config(global_config)
        print(f"  backup.conf: found")
        print(f"  CONFIG_VERSION: {global_config.get('CONFIG_VERSION', '<missing>')}")
        print(f"  BACKUP_NAME: {global_config.get('BACKUP_NAME', '<missing>')}")
        print(
            "  retention: "
            f"daily={global_config.get('RETENTION_DAILY', '<missing>')} "
            f"weekly={global_config.get('RETENTION_WEEKLY', '<missing>')} "
            f"monthly={global_config.get('RETENTION_MONTHLY', '<missing>')}"
        )
        print(f"  email enabled: {_boolish_to_yes_no(global_config.get('EMAIL_REPORT_ENABLED', ''))}")
        print(f"  coverage audit enabled: {_boolish_to_yes_no(global_config.get('RUN_COVERAGE_AUDIT', ''))}")
        print(f"  prune enabled: {_boolish_to_yes_no(global_config.get('RUN_PRUNE', ''))}")
        print(f"  check enabled: {_boolish_to_yes_no(global_config.get('RUN_RESTIC_CHECK', ''))}")
        password_file = global_config.get("RESTIC_PASSWORD_FILE", "")
        password_exists = "yes" if str(password_file) and config_file_exists(str(password_file)) else "no"
        print(f"  restic password file exists: {password_exists}")
        print(f"  email command: {global_config.get('EMAIL_REPORT_COMMAND', '<missing>') or '<missing>'}")
        print(f"  email recipient: {global_config.get('EMAIL_REPORT_TO', '<empty>') or '<empty>'}")
        print(f"  validation: {_validation_status(global_result)}")

    timer_enabled, timer_enabled_note = _timer_enabled_status()
    timer_next_run, timer_next_note = _timer_next_run()
    print("")
    print("Timer:")
    print(f"  file: {'found' if config_file_exists(DEFAULT_TIMER_PATH) else 'missing'}")
    print(f"  enabled: {timer_enabled}")
    if timer_enabled_note != "server-backup.timer is enabled":
        print(f"  enabled detail: {timer_enabled_note}")
    print(f"  next run: {timer_next_run}")
    if timer_next_note != "ok":
        print(f"  timer detail: {timer_next_note}")

    last_backup_run_path = LAST_BACKUP_RUN_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_backup_run_path = Path(configured_state_dir) / LAST_BACKUP_RUN_FILE

    print("")
    print("Last Backup Run:")
    last_backup_run = _load_last_backup_run(last_backup_run_path)
    if last_backup_run is None:
        print("  status: no previous backup report found")
    else:
        print(f"  date: {last_backup_run.get('end_time', '<unknown>')}")
        print(f"  status: {last_backup_run.get('status', '<unknown>')}")
        print(f"  report: {last_backup_run.get('text_report_path', '<unknown>')}")

    last_prune_run_path = LAST_PRUNE_RUN_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_prune_run_path = Path(configured_state_dir) / LAST_PRUNE_RUN_FILE

    print("")
    print("Last Prune Run:")
    last_prune_run = _load_last_backup_run(last_prune_run_path)
    if last_prune_run is None:
        print("  status: no previous prune report found")
    else:
        print(f"  date: {last_prune_run.get('end_time', '<unknown>')}")
        print(f"  status: {last_prune_run.get('status', '<unknown>')}")
        print(f"  report: {last_prune_run.get('text_report_path', '<unknown>')}")

    last_restore_test_path = LAST_RESTORE_TEST_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_restore_test_path = Path(configured_state_dir) / LAST_RESTORE_TEST_FILE

    print("")
    print("Last Restore Test:")
    last_restore_test = _load_last_backup_run(last_restore_test_path)
    if last_restore_test is None:
        print("  status: no previous restore-test report found")
    else:
        print(f"  date: {last_restore_test.get('end_time', '<unknown>')}")
        print(f"  status: {last_restore_test.get('status', '<unknown>')}")
        print(f"  report: {last_restore_test.get('text_report_path', '<unknown>')}")

    last_email_report_path = LAST_EMAIL_REPORT_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_email_report_path = Path(configured_state_dir) / LAST_EMAIL_REPORT_FILE

    print("")
    print("Last Email Report:")
    last_email_report = _load_last_backup_run(last_email_report_path)
    if last_email_report is None:
        print("  status: no previous email report found")
    else:
        print(f"  date: {last_email_report.get('sent_at', '<unknown>')}")
        print(f"  success: {'yes' if last_email_report.get('success') else 'no'}")
        print(f"  kind: {last_email_report.get('kind', '<unknown>')}")
        print(f"  subject: {last_email_report.get('subject', '<unknown>')}")

    last_coverage_audit_path = LAST_COVERAGE_AUDIT_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_coverage_audit_path = Path(configured_state_dir) / LAST_COVERAGE_AUDIT_FILE

    print("")
    print("Last Coverage Audit:")
    last_coverage_audit = _load_last_backup_run(last_coverage_audit_path)
    if last_coverage_audit is None:
        print("  status: no previous coverage audit report found")
    else:
        print(f"  date: {last_coverage_audit.get('end_time', '<unknown>')}")
        print(f"  status: {last_coverage_audit.get('status', '<unknown>')}")
        print(f"  report: {last_coverage_audit.get('text_report_path', '<unknown>')}")

    last_production_validation_path = LAST_PRODUCTION_VALIDATION_PATH
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        configured_state_dir = str(global_config.get("STATE_DIR", "")).strip()
        if configured_state_dir:
            last_production_validation_path = Path(configured_state_dir) / LAST_PRODUCTION_VALIDATION_FILE

    print("")
    print("Last Production Validation:")
    last_production_validation = _load_last_backup_run(last_production_validation_path)
    if last_production_validation is None:
        print("  status: no previous production validation report found")
    else:
        print(f"  date: {last_production_validation.get('end_time', '<unknown>')}")
        print(f"  status: {last_production_validation.get('status', '<unknown>')}")
        print(f"  report: {last_production_validation.get('text_report_path', '<unknown>')}")

    operations_summary: dict[str, object] | None = None
    if not permission_denied and global_config is not None and not global_config.get("__missing__"):
        try:
            operations_summary = build_operations_status(global_config, targets, profiles)
        except (RuntimeError, ValueError, PermissionError, FileNotFoundError):
            operations_summary = None

    if operations_summary and operations_summary.get("warnings"):
        print("")
        print("Reminders:")
        for warning in list(operations_summary.get("warnings", []))[:4]:
            print(f"  - {warning}")

    print("")
    print("Targets:")
    if permission_denied:
        print("  configured: unknown")
        print("  note: directory is present but requires root to inspect")
    elif targets:
        print(f"  configured: {len(targets)}")
        for target in targets:
            result = validate_target_config(target)
            safe_target = redact_config(target)
            target_name = safe_target.get("TARGET_NAME", "<missing>")
            target_type = safe_target.get("TARGET_TYPE", "<missing>")
            repository = safe_target.get("RESTIC_REPOSITORY", "<missing>")
            ssh_alias = safe_target.get("SSH_HOST_ALIAS", "<missing>")
            ssh_host = safe_target.get("SSH_HOSTNAME", "<missing>")
            ssh_port = safe_target.get("SSH_PORT", "<missing>")
            ssh_user = safe_target.get("SSH_USER", "<missing>")
            password_file_path = str(target.get("RESTIC_PASSWORD_FILE", "")).strip()
            ssh_config_path = str(target.get("SSH_CONFIG_FILE", DEFAULT_SSH_CONFIG)).strip()
            ssh_key_path = str(target.get("SSH_IDENTITY_FILE", "")).strip()
            known_hosts_path = str(target.get("SSH_KNOWN_HOSTS_FILE", DEFAULT_KNOWN_HOSTS)).strip()
            password_file_exists = "yes" if password_file_path and config_file_exists(password_file_path) else "no"
            ssh_config_exists = "yes" if ssh_config_path and config_file_exists(ssh_config_path) else "no"
            ssh_key_exists = "yes" if ssh_key_path and config_file_exists(ssh_key_path) else "no"
            known_hosts_exists = "yes" if known_hosts_path and config_file_exists(known_hosts_path) else "no"
            print(f"  - {target_name} | type={target_type} | validation={_validation_status(result)}")
            print(
                f"    alias={ssh_alias} host={ssh_host} port={ssh_port} user={ssh_user}"
            )
            print(
                "    "
                f"repository={repository} | password_file={password_file_exists} | ssh_config={ssh_config_exists} "
                f"| ssh_key={ssh_key_exists} | known_hosts={known_hosts_exists}"
            )
    else:
        print("  configured: 0")
        print("  note: add a target under /etc/server-backup/targets.d/")

    print("")
    print("Profiles:")
    if permission_denied:
        print("  configured: unknown")
        print("  note: directory is present but requires root to inspect")
    elif profiles:
        print(f"  configured: {len(profiles)}")
        for profile in profiles:
            result = validate_profile_config(profile)
            profile_name = profile.get("PROFILE_NAME", "<missing>")
            profile_type = profile.get("PROFILE_TYPE", "<missing>")
            backup_paths = profile.get("BACKUP_PATHS", [])
            path_count = len(backup_paths) if isinstance(backup_paths, list) else 0
            database_dumps = profile.get("DATABASE_DUMPS", [])
            database_dump_count = len(database_dumps) if isinstance(database_dumps, list) else 0
            docker_inventory = profile.get("DOCKER_INVENTORY")
            web_content_critical = profile.get("WEB_CONTENT_CRITICAL")
            extra_bits: list[str] = []
            if docker_inventory not in (None, ""):
                extra_bits.append(f"docker_inventory={docker_inventory}")
            if web_content_critical not in (None, ""):
                extra_bits.append(f"web_content_critical={web_content_critical}")
            if database_dump_count:
                extra_bits.append(f"database_dumps={database_dump_count}")
            extra = ""
            if extra_bits:
                extra = " | " + " | ".join(extra_bits)
            print(
                f"  - {profile_name} | type={profile_type} | backup_paths={path_count}{extra} | validation={_validation_status(result)}"
            )
    else:
        print("  configured: 0")
        print("  note: add a profile under /etc/server-backup/profiles.d/")

    print("")
    missing = [check.label for check in checks if not _safe_exists(check.path)]
    if missing:
        print("Overall: incomplete")
        _print_messages("Missing required paths:", missing)
        print("Next action: run sudo ./scripts/install.sh")
    elif permission_denied:
        print("Overall: base directories present")
        _print_permission_denied()
        print("Next action: run sudo server-backup status")
    else:
        assert global_config is not None
        overall = validate_all(global_config, targets, profiles)
        print(f"Overall: {_validation_status(overall)}")
        if overall.errors:
            _print_messages("Errors:", overall.errors)
        if overall.warnings:
            _print_messages("Warnings:", overall.warnings)

        if not config_file_exists(BACKUP_CONF):
            print("Next action: create /etc/server-backup/backup.conf and rerun server-backup config validate")
        elif overall.errors:
            print("Next action: fix validation errors and rerun server-backup config validate")
        elif not targets:
            print("Next action: run sudo server-backup target add")
        elif not profiles:
            print("Next action: run sudo server-backup profile add")
        else:
            print("Next action: run server-backup config validate after each manual config change")

    return 0


def cmd_not_implemented(args: argparse.Namespace) -> int:
    command = getattr(args, "_command_display", "command")
    print(f"{command}: {NOT_IMPLEMENTED_MESSAGE}", file=sys.stderr)
    return 3


def cmd_email_test(_: argparse.Namespace) -> int:
    try:
        global_config = load_global_config(BACKUP_CONF)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2

    if global_config.get("__missing__"):
        print("backup.conf is missing. Run sudo server-backup setup first.")
        return 1

    if str(global_config.get("EMAIL_REPORT_ENABLED", "")).lower() != "true":
        print("Email reports are disabled for automatic reports, but sending test email anyway.")

    result = send_test_email(global_config, to_override=getattr(_, "to", None))
    if result.get("success"):
        print("Email test sent successfully.")
        print(f"  to: {result.get('to', '')}")
        print(f"  subject: {result.get('subject', '')}")
        print(f"  command: {result.get('command', '')}")
        return 0

    print("Email test failed.")
    if result.get("error"):
        print(f"  error: {result.get('error')}")
    print(f"  command: {result.get('command', '')}")
    return 1


def cmd_coverage_audit(args: argparse.Namespace) -> int:
    try:
        report = run_coverage_audit(profile_name=args.profile, output_dir=args.output_dir)
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(render_coverage_report_json(report), end="")
    else:
        print("server-backup coverage audit")
        print("")
        print(f"Targets: {report.get('targets_count', 0)}")
        print(f"Profiles: {report.get('profiles_count', 0)}")
        print(f"Overall: {str(report.get('status', 'failure')).upper()}")
        print("")
        print("Summary:")
        summary = report.get("summary", {})
        print(f"  success: {summary.get('SUCCESS', 0)}")
        print(f"  warning: {summary.get('WARNING', 0)}")
        print(f"  failure: {summary.get('FAILURE', 0)}")
        print("")
        for section_name, key in (
            ("Generic findings", "generic_findings"),
            ("Target findings", "target_findings"),
            ("Profile findings", "profile_findings"),
            ("Docker findings", "docker_findings"),
            ("CIS findings", "cis_findings"),
        ):
            findings = report.get(key, [])
            if not findings:
                continue
            print(f"{section_name}:")
            for finding in findings:
                print(f"  [{finding.get('severity', 'SUCCESS')}] {finding.get('code', '')}: {finding.get('message', '')}")
            print("")
        print("Reports:")
        print(f"  {report.get('text_report_path', '')}")
        print(f"  {report.get('json_report_path', '')}")

    return 1 if report.get("status") == "failure" else 0


def cmd_validate_production(args: argparse.Namespace) -> int:
    try:
        report = run_production_validation(
            target_name=args.target,
            profile_name=args.profile,
            email_test=bool(args.email_test),
            restore_test=bool(args.restore_test),
            backup_dry_run=bool(args.backup_dry_run),
        )
    except ConfigPermissionError:
        _print_permission_denied()
        return 2
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("server-backup validate production")
    print("")
    print(f"Target: {report.get('target_name', '') or '<auto>'}")
    print(f"Profile: {report.get('profile_name', '') or '<all>'}")
    print(f"Overall: {str(report.get('status', 'failure')).upper()}")
    print("")
    print("Checks:")
    for check in report.get("checks", []):
        print(f"  - {check.get('name', '')}: {str(check.get('status', 'failure')).upper()} - {check.get('summary', '')}")
    if report.get("warnings"):
        print("")
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    if report.get("errors"):
        print("")
        print("Errors:")
        for error in report["errors"]:
            print(f"  - {error}")
    print("")
    print("Reports:")
    print(f"  {report.get('text_report_path', '')}")
    print(f"  {report.get('json_report_path', '')}")
    return 1 if report.get("status") == "failure" else 0


def _set_stub(subparser: argparse.ArgumentParser, command_display: str) -> None:
    subparser.set_defaults(func=cmd_not_implemented, _command_display=command_display)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="server-backup",
        description="Host-level backup scaffolding CLI for the server-backup MVP.",
    )
    parser.set_defaults(func=None)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser("status", help="Show installation and configuration status.")
    status_parser.set_defaults(func=cmd_status)

    health_parser = subparsers.add_parser("health", help="Run a local operational health check.")
    health_parser.set_defaults(func=cmd_health)

    operations_parser = subparsers.add_parser("operations", help="Operations-oriented status commands.")
    operations_subparsers = operations_parser.add_subparsers(dest="operations_command")

    operations_status_parser = operations_subparsers.add_parser("status", help="Show a synthetic local operations status view.")
    operations_status_parser.set_defaults(func=cmd_operations_status)

    config_parser = subparsers.add_parser("config", help="Inspect and validate configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    config_validate_parser = config_subparsers.add_parser("validate", help="Validate configuration files.")
    config_validate_parser.set_defaults(func=cmd_config_validate)

    config_show_parser = config_subparsers.add_parser("show", help="Show a redacted configuration view.")
    config_show_parser.set_defaults(func=cmd_config_show)

    setup_parser = subparsers.add_parser("setup", help="Run the interactive global setup wizard.")
    setup_parser.set_defaults(func=cmd_setup)

    target_parser = subparsers.add_parser("target", help="Manage backup targets.")
    target_subparsers = target_parser.add_subparsers(dest="target_command")

    target_add_parser = target_subparsers.add_parser("add", help="Run the interactive SFTP target wizard.")
    target_add_parser.set_defaults(func=cmd_target_add)

    target_test_parser = target_subparsers.add_parser("test", help="Test target SSH/SFTP connectivity.")
    target_test_parser.add_argument("target", help="Target name.")
    target_test_parser.set_defaults(func=cmd_target_test)

    repo_parser = subparsers.add_parser("repo", help="Manage restic repositories.")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command")

    repo_init_parser = repo_subparsers.add_parser("init", help="Initialize a restic repository for a target.")
    repo_init_parser.add_argument("target", nargs="?", help="Target name.")
    repo_init_parser.add_argument("--all", action="store_true", help="Run on all configured targets.")
    repo_init_parser.set_defaults(func=cmd_repo_init)

    repo_check_parser = repo_subparsers.add_parser("check", help="Run restic check for a target.")
    repo_check_parser.add_argument("target", nargs="?", help="Target name.")
    repo_check_parser.add_argument("--all", action="store_true", help="Run on all configured targets.")
    repo_check_parser.set_defaults(func=cmd_repo_check)

    repo_snapshots_parser = repo_subparsers.add_parser("snapshots", help="List restic snapshots for a target.")
    repo_snapshots_parser.add_argument("target", nargs="?", help="Target name.")
    repo_snapshots_parser.add_argument("--all", action="store_true", help="Run on all configured targets.")
    repo_snapshots_parser.set_defaults(func=cmd_repo_snapshots)

    repo_prune_parser = repo_subparsers.add_parser("prune", help="Apply restic retention policy to a target.")
    repo_prune_parser.add_argument("target", nargs="?", help="Target name.")
    repo_prune_parser.add_argument("--all", action="store_true", help="Run on all configured targets.")
    repo_prune_parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without deleting snapshots.")
    repo_prune_parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation for real prune.")
    repo_prune_parser.set_defaults(func=cmd_repo_prune, _parser=repo_prune_parser)

    profile_parser = subparsers.add_parser("profile", help="Manage backup profiles.")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command")

    profile_add_parser = profile_subparsers.add_parser("add", help="Run the interactive profile wizard.")
    profile_add_parser.set_defaults(func=cmd_profile_add)

    db_parser = subparsers.add_parser("db", help="Manage database backup definitions.")
    db_subparsers = db_parser.add_subparsers(dest="db_command")

    db_add_parser = db_subparsers.add_parser("add", help="Run the interactive database dump wizard.")
    db_add_parser.add_argument("--profile", help="Attach the database dump to the named profile.")
    db_add_parser.set_defaults(func=cmd_db_add)

    db_list_parser = db_subparsers.add_parser("list", help="List configured database dump definitions.")
    db_list_parser.set_defaults(func=cmd_db_list)

    db_test_parser = db_subparsers.add_parser("test", help="Test database connectivity for one or more dump definitions.")
    db_test_parser.add_argument("name", nargs="?", help="Database dump name.")
    db_test_parser.add_argument("--all", action="store_true", help="Run the test for all configured database dumps.")
    db_test_parser.set_defaults(func=cmd_db_test)

    db_dump_test_parser = db_subparsers.add_parser("dump-test", help="Run a temporary logical dump test.")
    db_dump_test_parser.add_argument("name", nargs="?", help="Database dump name.")
    db_dump_test_parser.add_argument("--all", action="store_true", help="Run the dump test for all configured database dumps.")
    db_dump_test_parser.add_argument("--keep-output", action="store_true", help="Keep the temporary dump directory for inspection.")
    db_dump_test_parser.set_defaults(func=cmd_db_dump_test)

    docker_parser = subparsers.add_parser("docker", help="Docker discovery helpers.")
    docker_subparsers = docker_parser.add_subparsers(dest="docker_command")

    docker_scan_parser = docker_subparsers.add_parser("scan", help="Scan local Docker containers, mounts and Compose files.")
    docker_scan_parser.set_defaults(func=cmd_docker_scan)

    docker_inventory_parser = docker_subparsers.add_parser("inventory", help="Write a local Docker inventory report.")
    docker_inventory_parser.set_defaults(func=cmd_docker_inventory)

    docker_coverage_parser = docker_subparsers.add_parser("coverage", help="Compare Docker mounts against configured profiles.")
    docker_coverage_parser.set_defaults(func=cmd_docker_coverage)

    docker_suggest_parser = docker_subparsers.add_parser(
        "suggest-profile-updates",
        help="Suggest which Docker paths should be added to which profile.",
    )
    docker_suggest_parser.set_defaults(func=cmd_docker_suggest_profile_updates)

    docker_add_missing_parser = docker_subparsers.add_parser(
        "add-missing-paths",
        help="Interactively add missing Docker paths to a chosen profile.",
    )
    docker_add_missing_parser.add_argument("--profile", required=True, help="Profile name to update.")
    docker_add_missing_parser.add_argument("--dry-run", action="store_true", help="Show what would be added without modifying the profile.")
    docker_add_missing_parser.add_argument("--volume", help="Limit the proposal to one named volume.")
    docker_add_missing_parser.add_argument("--all-volumes", action="store_true", help="Only consider named volumes.")
    docker_add_missing_parser.set_defaults(func=cmd_docker_add_missing_paths)

    coverage_parser = subparsers.add_parser("coverage", help="Coverage audit commands.")
    coverage_subparsers = coverage_parser.add_subparsers(dest="coverage_command")

    coverage_audit_parser = coverage_subparsers.add_parser("audit", help="Run a local coverage audit.")
    coverage_audit_parser.add_argument("--json", action="store_true", help="Print the redacted JSON report to stdout.")
    coverage_audit_parser.add_argument("--profile", help="Limit audit to one profile.")
    coverage_audit_parser.add_argument("--output-dir", help="Alternative report directory for coverage audit output.")
    coverage_audit_parser.set_defaults(func=cmd_coverage_audit)

    validate_parser = subparsers.add_parser("validate", help="Final non-destructive validation commands.")
    validate_subparsers = validate_parser.add_subparsers(dest="validate_command")

    validate_production_parser = validate_subparsers.add_parser(
        "production",
        help="Run a non-destructive production validation sequence.",
    )
    validate_production_parser.add_argument("--target", help="Target name for target-specific checks.")
    validate_production_parser.add_argument("--profile", help="Limit profile-specific checks to one profile.")
    validate_production_parser.add_argument("--email-test", action="store_true", help="Also send a real email test.")
    validate_production_parser.add_argument("--restore-test", action="store_true", help="Also run a non-destructive restore test.")
    validate_production_parser.add_argument("--backup-dry-run", action="store_true", help="Also run backup run --dry-run.")
    validate_production_parser.set_defaults(func=cmd_validate_production)

    backup_parser = subparsers.add_parser("backup", help="Backup execution commands.")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command")

    backup_run_parser = backup_subparsers.add_parser("run", help="Run restic backups for configured targets.")
    backup_run_parser.add_argument("--dry-run", action="store_true", help="Run restic backup with --dry-run.")
    backup_run_parser.add_argument("--target", help="Only run against the named target.")
    backup_run_parser.add_argument("--profile", help="Only run the named profile.")
    backup_run_parser.set_defaults(func=cmd_backup_run)

    restore_parser = subparsers.add_parser("restore", help="Restore commands.")
    restore_subparsers = restore_parser.add_subparsers(dest="restore_command")

    restore_test_parser = restore_subparsers.add_parser("test", help="Run a non-destructive restore test.")
    restore_test_parser.add_argument("--target", required=True, help="Target name.")
    restore_test_parser.add_argument("--snapshot", default="latest", help="Snapshot ID or 'latest'.")
    restore_test_parser.add_argument("--profile", help="Limit profile checks to one profile.")
    restore_test_parser.add_argument("--include", action="append", help="Limit restore to one or more repository paths.")
    restore_test_parser.add_argument("--output-dir", help="Restore output directory. Must be absent and under /tmp.")
    restore_test_parser.add_argument("--keep-output", action="store_true", help="Keep restored output directory after checks.")
    restore_test_parser.set_defaults(func=cmd_restore_test)

    email_parser = subparsers.add_parser("email", help="Email report commands.")
    email_subparsers = email_parser.add_subparsers(dest="email_command")

    email_test_parser = email_subparsers.add_parser("test", help="Send a real email test using the local MTA.")
    email_test_parser.add_argument("--to", help="Override recipient for the test email.")
    email_test_parser.set_defaults(func=cmd_email_test)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0

    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
