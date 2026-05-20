from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path
from typing import Any

from .config import load_profiles, parse_config_file
from .wizard import (
    confirm_overwrite,
    prompt_bool,
    prompt_choice,
    prompt_int,
    prompt_string,
    render_profile_conf,
    write_file_secure,
)


DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_DB_SECRETS_DIR = Path("/etc/server-backup/secrets/db")
DEFAULT_DB_DUMP_DIR = Path("/var/tmp/server-backup")
POSTGRES_ENGINES = {"postgres", "postgresql"}
MYSQL_ENGINES = {"mysql", "mariadb"}
SPEC_ORDER = (
    "name",
    "engine",
    "mode",
    "container",
    "host",
    "port",
    "user",
    "databases",
    "all",
    "globals",
    "secret",
)
SECRET_FIELD_NAMES = {"secret", "password", "pgpassword", "mysql_pwd"}
SENSITIVE_VALUES = ("PASSWORD", "SECRET", "TOKEN", "KEY", "PGPASSWORD", "MYSQL_PWD")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return sanitized or "database-dump"


def _boolish(value: object) -> bool:
    return str(value).strip().lower() == "true"


def _shell_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _engine_secret_key(engine: str) -> str:
    lowered = str(engine).strip().lower()
    if lowered in POSTGRES_ENGINES:
        return "PGPASSWORD"
    if lowered in MYSQL_ENGINES:
        return "MYSQL_PWD"
    raise ValueError(f"Unsupported database engine: {engine}")


def _default_db_name(spec: dict[str, Any]) -> str:
    databases = spec.get("databases", [])
    if isinstance(databases, list) and databases:
        return str(databases[0])
    engine = str(spec.get("engine", "")).strip().lower()
    if engine in POSTGRES_ENGINES:
        return "postgres"
    return "mysql"


def parse_database_dump_spec(spec: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"__raw_spec__": spec}
    for raw_item in spec.split(";"):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid DATABASE_DUMPS entry segment: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in {"all", "globals"}:
            parsed[key] = value.lower() == "true"
        elif key == "databases":
            parsed[key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            parsed[key] = value

    if "name" not in parsed or not str(parsed.get("name", "")).strip():
        raise ValueError("DATABASE_DUMPS entry is missing name=...")
    if "engine" not in parsed or not str(parsed.get("engine", "")).strip():
        raise ValueError(f"DATABASE_DUMPS entry {parsed['name']} is missing engine=...")
    parsed["engine"] = str(parsed["engine"]).strip().lower()
    parsed["mode"] = str(parsed.get("mode", "local")).strip().lower()
    parsed.setdefault("databases", [])
    parsed.setdefault("all", False)
    parsed.setdefault("globals", False)
    return parsed


def render_database_dump_spec(spec: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in SPEC_ORDER:
        if key not in spec:
            continue
        value = spec[key]
        if value in (None, "", []):
            continue
        if key == "databases":
            if isinstance(value, list):
                value = ",".join(str(item).strip() for item in value if str(item).strip())
        elif key in {"all", "globals"}:
            value = "true" if bool(value) else "false"
        parts.append(f"{key}={value}")

    for key in sorted(spec):
        if key.startswith("__") or key in SPEC_ORDER:
            continue
        value = spec[key]
        if value in (None, "", []):
            continue
        parts.append(f"{key}={value}")
    return ";".join(parts)


def load_database_dumps_from_profiles(profiles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if profiles is None:
        profiles = load_profiles(DEFAULT_PROFILES_DIR)
    dumps: list[dict[str, Any]] = []
    for profile in profiles:
        raw_dumps = profile.get("DATABASE_DUMPS", [])
        if not isinstance(raw_dumps, list):
            continue
        for spec in raw_dumps:
            parsed = parse_database_dump_spec(str(spec))
            parsed["__profile_name__"] = str(profile.get("PROFILE_NAME", ""))
            parsed["__profile_file__"] = str(profile.get("__file__", ""))
            parsed["__profile_type__"] = str(profile.get("PROFILE_TYPE", ""))
            dumps.append(parsed)
    return sorted(
        dumps,
        key=lambda item: (
            str(item.get("__profile_name__", "")).strip(),
            str(item.get("name", "")).strip(),
        ),
    )


def select_database_dump(name: str, dumps: list[dict[str, Any]]) -> dict[str, Any]:
    for dump in dumps:
        if str(dump.get("name", "")).strip() == name:
            return dump
    raise ValueError(f"Database dump not found: {name}")


def redact_db_config(config: Any) -> Any:
    if isinstance(config, dict):
        redacted: dict[str, Any] = {}
        for key, value in config.items():
            lowered = str(key).lower()
            if lowered in SECRET_FIELD_NAMES or any(token in str(key).upper() for token in SENSITIVE_VALUES):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_db_config(value)
        return redacted
    if isinstance(config, list):
        return [redact_db_config(item) for item in config]
    return config


def list_database_dumps(profiles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    dumps = load_database_dumps_from_profiles(profiles)
    return [redact_db_config(dump) for dump in dumps]


def write_db_secret_file(
    path: str | Path,
    engine: str,
    password: str,
    *,
    backup_existing: bool = False,
) -> Path:
    secret_path = Path(path)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_path.parent, 0o700)
    content = f"{_engine_secret_key(engine)}={_shell_quote(password)}\n"
    owner_uid = 0 if os.geteuid() == 0 else None
    owner_gid = 0 if os.geteuid() == 0 else None
    return write_file_secure(
        secret_path,
        content,
        mode=0o600,
        backup_existing=backup_existing,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def read_db_secret_file(path: str | Path) -> dict[str, str]:
    parsed = parse_config_file(path)
    if parsed.get("__missing__"):
        raise FileNotFoundError(f"Database secret file not found: {path}")
    secret_values: dict[str, str] = {}
    for key in ("PGPASSWORD", "MYSQL_PWD"):
        value = str(parsed.get(key, "")).strip()
        if value:
            secret_values[key] = value
    if not secret_values:
        raise ValueError(f"Database secret file does not contain PGPASSWORD or MYSQL_PWD: {path}")
    return secret_values


def discover_db_tools() -> dict[str, str | None]:
    return {
        "docker": shutil.which("docker"),
        "psql": shutil.which("psql"),
        "pg_dump": shutil.which("pg_dump"),
        "pg_dumpall": shutil.which("pg_dumpall"),
        "pg_restore": shutil.which("pg_restore"),
        "mysql": shutil.which("mysql") or shutil.which("mariadb"),
        "mysqldump": shutil.which("mariadb-dump") or shutil.which("mysqldump"),
    }


def build_postgres_test_command(spec: dict[str, Any]) -> list[str]:
    database = _default_db_name(spec)
    user = str(spec.get("user", "")).strip()
    mode = str(spec.get("mode", "local")).strip().lower()
    if mode == "docker":
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD",
            str(spec.get("container", "")).strip(),
            "psql",
            f"--username={user}",
            f"--dbname={database}",
            "--command=SELECT 1;",
        ]
    host = str(spec.get("host", "localhost")).strip() or "localhost"
    port = str(spec.get("port", "5432")).strip() or "5432"
    return [
        "psql",
        "-h",
        host,
        "-p",
        port,
        f"--username={user}",
        f"--dbname={database}",
        "--command=SELECT 1;",
    ]


def build_postgres_dump_command(spec: dict[str, Any], database: str) -> list[str]:
    user = str(spec.get("user", "")).strip()
    mode = str(spec.get("mode", "local")).strip().lower()
    base = ["pg_dump", f"--username={user}", "--format=custom", "--compress=0", database]
    if mode == "docker":
        return ["docker", "exec", "-i", "-e", "PGPASSWORD", str(spec.get("container", "")).strip(), *base]
    host = str(spec.get("host", "localhost")).strip() or "localhost"
    port = str(spec.get("port", "5432")).strip() or "5432"
    return ["pg_dump", "-h", host, "-p", port, f"--username={user}", "--format=custom", "--compress=0", database]


def build_postgres_globals_command(spec: dict[str, Any]) -> list[str]:
    user = str(spec.get("user", "")).strip()
    mode = str(spec.get("mode", "local")).strip().lower()
    if mode == "docker":
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD",
            str(spec.get("container", "")).strip(),
            "pg_dumpall",
            "--globals-only",
            f"--username={user}",
        ]
    host = str(spec.get("host", "localhost")).strip() or "localhost"
    port = str(spec.get("port", "5432")).strip() or "5432"
    return ["pg_dumpall", "-h", host, "-p", port, "--globals-only", f"--username={user}"]


def build_mysql_test_command(spec: dict[str, Any]) -> list[str]:
    database = _default_db_name(spec)
    user = str(spec.get("user", "")).strip()
    mode = str(spec.get("mode", "local")).strip().lower()
    if mode == "docker":
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "MYSQL_PWD",
            str(spec.get("container", "")).strip(),
            "sh",
            "-lc",
            (
                'if command -v mariadb >/dev/null 2>&1; then '
                'exec mariadb "--user=$1" "--database=$2" --execute="SELECT 1;"; '
                'else exec mysql "--user=$1" "--database=$2" --execute="SELECT 1;"; fi'
            ),
            "db-shell",
            user,
            database,
        ]
    host = str(spec.get("host", "localhost")).strip() or "localhost"
    port = str(spec.get("port", "3306")).strip() or "3306"
    client = discover_db_tools().get("mysql") or "mysql"
    return [
        str(client),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        f"--database={database}",
        "--execute=SELECT 1;",
    ]


def build_mysql_dump_command(spec: dict[str, Any], database: str | None = None) -> list[str]:
    user = str(spec.get("user", "")).strip()
    mode = str(spec.get("mode", "local")).strip().lower()
    database_arg = database or ""
    if mode == "docker":
        database_mode = "--all-databases" if _boolish(spec.get("all", False)) else database_arg
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "MYSQL_PWD",
            str(spec.get("container", "")).strip(),
            "sh",
            "-lc",
            (
                'if command -v mariadb-dump >/dev/null 2>&1; then '
                'exec mariadb-dump --single-transaction --routines --triggers --events "--user=$1" "$2"; '
                'else exec mysqldump --single-transaction --routines --triggers --events "--user=$1" "$2"; fi'
            ),
            "db-dump",
            user,
            database_mode,
        ]
    host = str(spec.get("host", "localhost")).strip() or "localhost"
    port = str(spec.get("port", "3306")).strip() or "3306"
    dump_tool = discover_db_tools().get("mysqldump") or "mysqldump"
    command = [
        str(dump_tool),
        "--single-transaction",
        "--routines",
        "--triggers",
        "--events",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
    ]
    if _boolish(spec.get("all", False)):
        command.append("--all-databases")
    elif database_arg:
        command.append(database_arg)
    return command


def run_db_command(
    command: list[str],
    env: dict[str, str],
    *,
    timeout: int | float | None = None,
    output_path: str | Path | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    merged_env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    merged_env.update(env)
    if output_path is not None:
        output_target = Path(output_path)
        output_target.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if text else "wb"
        encoding = "utf-8" if text else None
        with output_target.open(mode, encoding=encoding) as handle:
            return subprocess.run(
                command,
                check=False,
                stdout=handle,
                stderr=subprocess.PIPE,
                env=merged_env,
                shell=False,
                text=text,
                timeout=timeout,
            )
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=merged_env,
        shell=False,
        text=text,
        timeout=timeout,
    )


def _db_command_summary(command: list[str]) -> str:
    parts: list[str] = []
    for item in command:
        if any(token in item.upper() for token in SENSITIVE_VALUES):
            parts.append(item.split("=", 1)[0] if "=" in item else item)
        else:
            parts.append(item)
    return " ".join(parts)


def _require_tool(name: str, value: str | None) -> str:
    if not value:
        raise RuntimeError(f"Required database tool is not available: {name}")
    return value


def _database_list(spec: dict[str, Any]) -> list[str]:
    databases = spec.get("databases", [])
    if isinstance(databases, list) and databases:
        return [str(item).strip() for item in databases if str(item).strip()]
    if _boolish(spec.get("all", False)):
        return []
    return [_default_db_name(spec)]


def _secret_env_for_spec(spec: dict[str, Any]) -> dict[str, str]:
    secret_path = str(spec.get("secret", "")).strip()
    if not secret_path:
        raise ValueError(f"Database dump {spec.get('name', '<unknown>')} does not define a secret file.")
    secret_env = read_db_secret_file(secret_path)
    key = _engine_secret_key(str(spec.get("engine", "")).strip())
    if key not in secret_env:
        raise ValueError(f"Secret file {secret_path} does not provide {key}.")
    return {key: secret_env[key]}


def test_database_connection(spec: dict[str, Any]) -> dict[str, Any]:
    engine = str(spec.get("engine", "")).strip().lower()
    tools = discover_db_tools()
    if engine in POSTGRES_ENGINES:
        _require_tool("psql", tools.get("psql"))
        if str(spec.get("mode", "local")).strip().lower() == "docker":
            _require_tool("docker", tools.get("docker"))
        command = build_postgres_test_command(spec)
    elif engine in MYSQL_ENGINES:
        if str(spec.get("mode", "local")).strip().lower() == "docker":
            _require_tool("docker", tools.get("docker"))
        else:
            _require_tool("mysql", tools.get("mysql"))
        command = build_mysql_test_command(spec)
    else:
        raise ValueError(f"Unsupported database engine: {engine}")

    secret_env = _secret_env_for_spec(spec)
    completed = run_db_command(command, secret_env, text=True)
    stdout = (completed.stdout or "").strip() if isinstance(completed.stdout, str) else ""
    stderr = (completed.stderr or "").strip() if isinstance(completed.stderr, str) else ""
    return {
        "name": str(spec.get("name", "")),
        "command_summary": _db_command_summary(command),
        "success": completed.returncode == 0,
        "status": "success" if completed.returncode == 0 else "failure",
        "stdout": stdout,
        "stderr": stderr,
        "error": "" if completed.returncode == 0 else (stderr or stdout or "Database connection test failed."),
    }


def _verify_postgres_custom_dump(path: Path, tools: dict[str, str | None]) -> list[str]:
    warnings: list[str] = []
    pg_restore = tools.get("pg_restore")
    if not pg_restore:
        warnings.append(f"pg_restore is not available to inspect {path.name}.")
        return warnings
    completed = run_db_command([str(pg_restore), "--list", str(path)], {}, text=True)
    if completed.returncode != 0:
        warnings.append(f"pg_restore --list failed for {path.name}: {(completed.stderr or completed.stdout or '').strip()}")
    return warnings


def _verify_sql_dump(path: Path) -> list[str]:
    warnings: list[str] = []
    if not path.exists() or path.stat().st_size == 0:
        warnings.append(f"Dump file is empty: {path}")
        return warnings
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as handle:
            preview = handle.read(65536)
    else:
        preview = path.read_text(encoding="utf-8", errors="ignore")[:65536]
    if not any(token in preview.upper() for token in ("CREATE", "INSERT", "COPY")):
        warnings.append(f"Dump file {path.name} does not contain obvious SQL statements in the preview.")
    return warnings


def run_database_dump(
    spec: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    engine = str(spec.get("engine", "")).strip().lower()
    mode = str(spec.get("mode", "local")).strip().lower()
    tools = discover_db_tools()
    if engine in POSTGRES_ENGINES:
        _require_tool("pg_dump", tools.get("pg_dump"))
        _require_tool("pg_dumpall", tools.get("pg_dumpall"))
        if mode == "docker":
            _require_tool("docker", tools.get("docker"))
    elif engine in MYSQL_ENGINES:
        if mode == "docker":
            _require_tool("docker", tools.get("docker"))
        else:
            _require_tool("mysqldump", tools.get("mysqldump"))
    else:
        raise ValueError(f"Unsupported database engine: {engine}")

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    secret_env = _secret_env_for_spec(spec)
    result: dict[str, Any] = {
        "name": str(spec.get("name", "")),
        "profile_name": str(spec.get("__profile_name__", "")),
        "engine": engine,
        "mode": mode,
        "output_dir": str(output_root),
        "files": [],
        "warnings": [],
        "errors": [],
        "status": "success",
        "commands": [],
    }

    if engine in POSTGRES_ENGINES:
        for database in _database_list(spec):
            dump_file = output_root / f"{_sanitize_name(str(spec.get('name', 'db')))}-{_sanitize_name(database)}.dump"
            command = build_postgres_dump_command(spec, database)
            completed = run_db_command(command, secret_env, output_path=dump_file, text=False)
            result["commands"].append(_db_command_summary(command))
            if completed.returncode != 0:
                stderr = completed.stderr.decode("utf-8", errors="ignore") if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
                result["errors"].append(stderr.strip() or f"pg_dump failed for {database}")
                continue
            if not dump_file.exists() or dump_file.stat().st_size == 0:
                result["errors"].append(f"Dump file is empty: {dump_file}")
                continue
            result["files"].append(str(dump_file))
            result["warnings"].extend(_verify_postgres_custom_dump(dump_file, tools))

        if _boolish(spec.get("globals", False)):
            globals_file = output_root / f"{_sanitize_name(str(spec.get('name', 'db')))}-globals.sql"
            command = build_postgres_globals_command(spec)
            completed = run_db_command(command, secret_env, output_path=globals_file, text=True)
            result["commands"].append(_db_command_summary(command))
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip() if isinstance(completed.stderr, str) else ""
                result["errors"].append(stderr or "pg_dumpall --globals-only failed")
            elif not globals_file.exists() or globals_file.stat().st_size == 0:
                result["errors"].append(f"Dump file is empty: {globals_file}")
            else:
                result["files"].append(str(globals_file))
                result["warnings"].extend(_verify_sql_dump(globals_file))
    else:
        databases = _database_list(spec)
        if _boolish(spec.get("all", False)):
            dump_targets = [None]
        else:
            dump_targets = databases
        for database in dump_targets:
            suffix = "all" if database is None else _sanitize_name(database)
            dump_file = output_root / f"{_sanitize_name(str(spec.get('name', 'db')))}-{suffix}.sql"
            command = build_mysql_dump_command(spec, database)
            completed = run_db_command(command, secret_env, output_path=dump_file, text=True)
            result["commands"].append(_db_command_summary(command))
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip() if isinstance(completed.stderr, str) else ""
                result["errors"].append(stderr or "mysqldump failed")
                continue
            if not dump_file.exists() or dump_file.stat().st_size == 0:
                result["errors"].append(f"Dump file is empty: {dump_file}")
                continue
            result["files"].append(str(dump_file))
            result["warnings"].extend(_verify_sql_dump(dump_file))

    if result["errors"]:
        result["status"] = "failure"
    elif result["warnings"]:
        result["status"] = "warning"
    return result


def run_dump_test(spec: dict[str, Any], *, keep_output: bool = False) -> dict[str, Any]:
    DEFAULT_DB_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = Path(
        tempfile.mkdtemp(
            prefix=f"db-dump-test-{_sanitize_name(str(spec.get('name', 'db')))}-",
            dir=str(DEFAULT_DB_DUMP_DIR),
        )
    )
    result: dict[str, Any]
    try:
        result = run_database_dump(spec, output_dir)
    except Exception:
        if not keep_output and output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        raise

    result["keep_output"] = keep_output
    result["output_cleaned"] = False
    if not keep_output and output_dir.exists():
        shutil.rmtree(output_dir)
        result["output_cleaned"] = True
    return result


def update_profile_database_dumps(
    profile_path: str | Path,
    dump_spec: dict[str, Any] | str,
) -> Path:
    path = Path(profile_path)
    profile = parse_config_file(path)
    raw_dumps = profile.get("DATABASE_DUMPS", [])
    if not isinstance(raw_dumps, list):
        raw_dumps = []
    rendered_spec = dump_spec if isinstance(dump_spec, str) else render_database_dump_spec(dump_spec)
    parsed_new = parse_database_dump_spec(rendered_spec)

    updated: list[str] = []
    replaced = False
    for raw_spec in raw_dumps:
        parsed_existing = parse_database_dump_spec(str(raw_spec))
        if str(parsed_existing.get("name", "")) == str(parsed_new.get("name", "")):
            updated.append(rendered_spec)
            replaced = True
        else:
            updated.append(str(raw_spec))
    if not replaced:
        updated.append(rendered_spec)

    profile["DATABASE_DUMPS"] = updated
    rendered = render_profile_conf(profile)
    owner_uid = 0 if os.geteuid() == 0 else None
    owner_gid = 0 if os.geteuid() == 0 else None
    write_file_secure(
        path,
        rendered,
        mode=0o600,
        backup_existing=True,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    return path


def _prompt_database_name(input_func=input) -> str:
    return prompt_string("Database dump logical name", input_func=input_func)


def _choose_profile(profile_name: str | None = None, *, input_func=input) -> dict[str, Any]:
    profiles = load_profiles(DEFAULT_PROFILES_DIR)
    if not profiles:
        raise ValueError("No profiles are configured. Run sudo server-backup profile add first.")
    if profile_name:
        for profile in profiles:
            if str(profile.get("PROFILE_NAME", "")).strip() == profile_name:
                return profile
        raise ValueError(f"Profile not found: {profile_name}")
    choices = [str(profile.get("PROFILE_NAME", "")) for profile in profiles]
    selected = prompt_choice("Profile", choices, choices[0], input_func=input_func)
    for profile in profiles:
        if str(profile.get("PROFILE_NAME", "")).strip() == selected:
            return profile
    raise ValueError(f"Profile not found: {selected}")


def _prompt_secret_path(profile_name: str, dump_name: str, *, input_func=input) -> Path:
    default = DEFAULT_DB_SECRETS_DIR / profile_name / f"{_sanitize_name(dump_name)}.env"
    return Path(prompt_string("Secret file path", str(default), input_func=input_func))


def _prompt_secret_file(secret_path: Path, engine: str, *, input_func=input) -> Path:
    create_secret = prompt_bool("Create or replace the DB secret file now", True, input_func=input_func)
    if create_secret:
        backup_existing = False
        if secret_path.exists():
            if not confirm_overwrite(secret_path, input_func=input_func):
                return secret_path
            backup_existing = True
        password = getpass("Database password: ")
        if not password:
            raise ValueError("Database password cannot be empty.")
        write_db_secret_file(secret_path, engine, password, backup_existing=backup_existing)
        return secret_path
    if not secret_path.exists():
        raise ValueError(f"Secret file does not exist yet: {secret_path}")
    return secret_path


def run_db_add(profile_name: str | None = None, *, input_func=input) -> dict[str, Any]:
    profile = _choose_profile(profile_name, input_func=input_func)
    selected_profile_name = str(profile.get("PROFILE_NAME", ""))
    dump_name = _prompt_database_name(input_func=input_func)
    engine = prompt_choice("Database engine", ["postgresql", "mysql"], "postgresql", input_func=input_func)
    mode = prompt_choice("Database mode", ["docker", "local", "remote"], "docker", input_func=input_func)

    spec: dict[str, Any] = {
        "name": dump_name,
        "engine": engine,
        "mode": mode,
        "__profile_name__": selected_profile_name,
        "__profile_file__": str(profile.get("__file__", "")),
    }

    if mode == "docker":
        spec["container"] = prompt_string("Docker container name", input_func=input_func)
    else:
        default_host = "localhost" if mode == "local" else ""
        default_port = 5432 if engine in POSTGRES_ENGINES else 3306
        spec["host"] = prompt_string("Host", default_host, input_func=input_func)
        spec["port"] = str(prompt_int("Port", default_port, minimum=1, input_func=input_func))

    spec["user"] = prompt_string("Database user", input_func=input_func)

    if engine in POSTGRES_ENGINES:
        databases_raw = prompt_string("Databases (comma separated)", "postgres", input_func=input_func)
        spec["databases"] = [item.strip() for item in databases_raw.split(",") if item.strip()]
        spec["globals"] = prompt_bool("Dump PostgreSQL globals", True, input_func=input_func)
    else:
        dump_all = prompt_bool("Dump all databases", False, input_func=input_func)
        spec["all"] = dump_all
        if dump_all:
            spec["databases"] = []
        else:
            databases_raw = prompt_string("Databases (comma separated)", "mysql", input_func=input_func)
            spec["databases"] = [item.strip() for item in databases_raw.split(",") if item.strip()]

    secret_path = _prompt_secret_path(selected_profile_name, dump_name, input_func=input_func)
    spec["secret"] = str(_prompt_secret_file(secret_path, engine, input_func=input_func))

    rendered_spec = render_database_dump_spec(spec)
    profile_path = Path(str(profile.get("__file__", "")))
    update_profile_database_dumps(profile_path, rendered_spec)

    test_result = None
    if prompt_bool("Test database connection now", True, input_func=input_func):
        test_result = test_database_connection(spec)
        if not test_result["success"]:
            raise RuntimeError(test_result["error"])

    dump_test_result = None
    if prompt_bool("Run dump test now", True, input_func=input_func):
        dump_test_result = run_dump_test(spec, keep_output=False)
        if dump_test_result["status"] == "failure":
            raise RuntimeError("; ".join(dump_test_result.get("errors", [])) or "Database dump test failed.")

    return {
        "ok": True,
        "profile_name": selected_profile_name,
        "profile_path": str(profile_path),
        "dump_name": dump_name,
        "spec": redact_db_config(spec),
        "test_result": redact_db_config(test_result) if test_result else None,
        "dump_test_result": redact_db_config(dump_test_result) if dump_test_result else None,
    }
