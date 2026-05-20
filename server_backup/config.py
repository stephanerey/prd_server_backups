from __future__ import annotations

import re
from pathlib import Path
from typing import Any


GLOBAL_CONFIG_PATH = Path("/etc/server-backup/backup.conf")
TARGETS_DIR = Path("/etc/server-backup/targets.d")
PROFILES_DIR = Path("/etc/server-backup/profiles.d")

SUPPORTED_SUFFIXES = {
    "global": (".conf",),
    "target": (".env",),
    "profile": (".conf",),
}

SENSITIVE_TOKENS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "PGPASSWORD",
    "MYSQL_PWD",
    "PASS",
    "PWD",
)

_ARRAY_START_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=\(\s*$")
_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class ConfigPermissionError(PermissionError):
    def __init__(self, path: str):
        super().__init__(f"Permission denied while reading configuration: {path}")
        self.path = path


def config_file_exists(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.exists()
    except PermissionError:
        return True


def list_config_files(directory: str | Path, suffixes: tuple[str, ...] | list[str]) -> list[Path]:
    config_dir = Path(directory)
    allowed_suffixes = tuple(suffixes)

    try:
        if not config_dir.exists() or not config_dir.is_dir():
            return []
        return sorted(
            path for path in config_dir.iterdir() if path.is_file() and any(path.name.endswith(suffix) for suffix in allowed_suffixes)
        )
    except PermissionError as exc:
        raise ConfigPermissionError(str(config_dir)) from exc


def _infer_kind(path: Path) -> str:
    if path.name in {"backup.conf", "backup.conf.example"}:
        return "global"
    if path.parent.name in {"targets.d", "targets"}:
        return "target"
    if path.parent.name in {"profiles.d", "profiles"}:
        return "profile"
    return "config"


def _unquote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def parse_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    result: dict[str, Any] = {
        "__file__": str(config_path),
        "__kind__": _infer_kind(config_path),
        "__parse_warnings__": [],
    }

    if not config_file_exists(config_path):
        result["__missing__"] = True
        return result

    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except PermissionError as exc:
        raise ConfigPermissionError(str(config_path)) from exc

    current_array_name: str | None = None
    current_array_values: list[str] = []

    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()

        if current_array_name is not None:
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == ")":
                result[current_array_name] = current_array_values
                current_array_name = None
                current_array_values = []
                continue
            current_array_values.append(_unquote(stripped))
            continue

        if not stripped or stripped.startswith("#"):
            continue

        array_match = _ARRAY_START_RE.match(stripped)
        if array_match:
            current_array_name = array_match.group(1)
            current_array_values = []
            continue

        scalar_match = _SCALAR_RE.match(stripped)
        if scalar_match:
            key = scalar_match.group(1)
            value = scalar_match.group(2)
            result[key] = _unquote(value)
            continue

        result["__parse_warnings__"].append(f"{config_path}:{lineno}: unsupported line ignored")

    if current_array_name is not None:
        result["__parse_warnings__"].append(f"{config_path}: unterminated array '{current_array_name}'")
        result[current_array_name] = current_array_values

    return result


def load_global_config(path: str | Path = GLOBAL_CONFIG_PATH) -> dict[str, Any]:
    return parse_config_file(path)


def load_targets(path: str | Path = TARGETS_DIR) -> list[dict[str, Any]]:
    return [parse_config_file(config_file) for config_file in list_config_files(path, SUPPORTED_SUFFIXES["target"])]


def load_profiles(path: str | Path = PROFILES_DIR) -> list[dict[str, Any]]:
    return [parse_config_file(config_file) for config_file in list_config_files(path, SUPPORTED_SUFFIXES["profile"])]


def _is_sensitive_key(key: str) -> bool:
    upper_key = key.upper()
    return any(token in upper_key for token in SENSITIVE_TOKENS)


def redact_config(config: Any) -> Any:
    if isinstance(config, dict):
        redacted: dict[str, Any] = {}
        for key, value in config.items():
            if isinstance(key, str) and _is_sensitive_key(key) and not key.startswith("__"):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_config(value)
        return redacted

    if isinstance(config, list):
        return [redact_config(value) for value in config]

    return config
