from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_profiles, parse_config_file, redact_config
from .db import parse_database_dump_spec
from .validators import validate_profile_config
from .wizard import render_profile_conf, write_file_secure


DEFAULT_PROFILES_DIR = Path("/etc/server-backup/profiles.d")
DEFAULT_STATE_DIR = Path("/var/lib/server-backup/state")
COMPOSE_FILENAMES = (
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.override.yml",
)
DB_NAME_HINTS = ("postgres", "postgresql", "pgdata", "mysql", "mariadb", "database")
DB_DESTINATION_HINTS = ("/var/lib/postgresql", "/var/lib/mysql", "/var/lib/mariadb")
REVERSE_PROXY_HINTS = ("caddy", "nginx", "traefik")
REVERSE_PROXY_DESTINATION_HINTS = ("/etc/caddy", "/etc/nginx", "/data", "/config")


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
    except (FileNotFoundError, PermissionError, OSError):
        return None


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
    result: list[str] = []
    for profile in profiles:
        raw_paths = profile.get("BACKUP_PATHS", [])
        if isinstance(raw_paths, list):
            result.extend(str(item).strip() for item in raw_paths if str(item).strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for item in result:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


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


def _lowered_parts(*values: str) -> str:
    return " ".join(value.strip().lower() for value in values if value and value.strip())


def docker_available() -> dict[str, Any]:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {"available": False, "reason": "docker not installed", "docker_bin": None, "version": ""}
    try:
        result = subprocess.run(
            [docker_bin, "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError as exc:
        return {"available": False, "reason": str(exc), "docker_bin": docker_bin, "version": ""}
    if result.returncode != 0:
        return {
            "available": False,
            "reason": (result.stderr or result.stdout or "docker unavailable").strip(),
            "docker_bin": docker_bin,
            "version": "",
        }
    return {
        "available": True,
        "reason": "",
        "docker_bin": docker_bin,
        "version": (result.stdout or "").strip(),
    }


def run_docker_command(args: list[str], timeout: int | float | None = None) -> subprocess.CompletedProcess[str]:
    availability = docker_available()
    if not availability.get("available"):
        raise RuntimeError(f"Docker is unavailable: {availability.get('reason', 'unknown reason')}")
    docker_bin = str(availability["docker_bin"])
    return subprocess.run(
        [docker_bin, *args],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=timeout,
    )


def inspect_container(container_id_or_name: str) -> dict[str, Any]:
    result = run_docker_command(["inspect", container_id_or_name])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"docker inspect failed for {container_id_or_name}").strip())
    payload = json.loads(result.stdout or "[]")
    if not payload:
        raise RuntimeError(f"Container not found: {container_id_or_name}")
    item = payload[0]
    labels = item.get("Config", {}).get("Labels", {}) or {}
    ports = item.get("NetworkSettings", {}).get("Ports", {}) or {}
    networks = item.get("NetworkSettings", {}).get("Networks", {}) or {}
    return {
        "id": item.get("Id", ""),
        "name": str(item.get("Name", "")).lstrip("/"),
        "image": item.get("Config", {}).get("Image", ""),
        "image_name": item.get("Config", {}).get("Image", ""),
        "state": item.get("State", {}).get("Status", ""),
        "running": bool(item.get("State", {}).get("Running", False)),
        "status": item.get("State", {}).get("Status", ""),
        "mounts": item.get("Mounts", []) or [],
        "ports": ports,
        "labels": labels,
        "compose_project": labels.get("com.docker.compose.project", ""),
        "compose_service": labels.get("com.docker.compose.service", ""),
        "networks": sorted(networks.keys()),
    }


def list_containers(*, all_containers: bool = False) -> list[dict[str, Any]]:
    args = ["ps", "-aq"] if all_containers else ["ps", "-q"]
    result = run_docker_command(args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "docker ps failed").strip())
    container_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    containers: list[dict[str, Any]] = []
    for container_id in container_ids:
        try:
            containers.append(inspect_container(container_id))
        except RuntimeError:
            continue
    return containers


def inspect_volume(volume_name: str) -> dict[str, Any]:
    result = run_docker_command(["volume", "inspect", volume_name])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"docker volume inspect failed for {volume_name}").strip())
    payload = json.loads(result.stdout or "[]")
    if not payload:
        raise RuntimeError(f"Volume not found: {volume_name}")
    item = payload[0]
    return {
        "name": item.get("Name", ""),
        "driver": item.get("Driver", ""),
        "mountpoint": item.get("Mountpoint", ""),
        "labels": item.get("Labels", {}) or {},
        "scope": item.get("Scope", ""),
        "options": item.get("Options", {}) or {},
    }


def list_volumes() -> list[str]:
    result = run_docker_command(["volume", "ls", "-q"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "docker volume ls failed").strip())
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def collect_container_mounts(*, all_containers: bool = False) -> list[dict[str, Any]]:
    mounts: list[dict[str, Any]] = []
    for container in list_containers(all_containers=all_containers):
        for mount in container.get("mounts", []):
            mounts.append(
                {
                    "container_id": container.get("id", ""),
                    "container_name": container.get("name", ""),
                    "image": container.get("image", ""),
                    "compose_project": container.get("compose_project", ""),
                    "compose_service": container.get("compose_service", ""),
                    "type": str(mount.get("Type", "")),
                    "source": str(mount.get("Source", "")),
                    "destination": str(mount.get("Destination", "")),
                    "name": str(mount.get("Name", "")),
                    "read_write": bool(mount.get("RW", True)),
                }
            )
    return mounts


def collect_named_volumes(*, all_containers: bool = False) -> list[dict[str, Any]]:
    return [mount for mount in collect_container_mounts(all_containers=all_containers) if str(mount.get("type", "")) == "volume"]


def collect_bind_mounts(*, all_containers: bool = False) -> list[dict[str, Any]]:
    return [mount for mount in collect_container_mounts(all_containers=all_containers) if str(mount.get("type", "")) == "bind"]


def discover_compose_files(search_paths: list[str]) -> list[str]:
    found: set[str] = set()
    for search_path in search_paths:
        candidate = Path(search_path)
        if not _safe_exists(candidate):
            continue
        if candidate.is_file() and candidate.name in COMPOSE_FILENAMES:
            found.add(str(candidate))
            continue
        if not candidate.is_dir():
            continue
        base_depth = len(candidate.parts)
        for root, dirs, files in os.walk(candidate):
            root_path = Path(root)
            current_depth = len(root_path.parts) - base_depth
            if current_depth > 4:
                dirs[:] = []
                continue
            for filename in files:
                if filename in COMPOSE_FILENAMES:
                    found.add(str(root_path / filename))
    return sorted(found)


def discover_env_files_near_compose(compose_files: list[str]) -> list[str]:
    found: set[str] = set()
    for compose_file in compose_files:
        env_file = Path(compose_file).parent / ".env"
        if _safe_exists(env_file):
            found.add(str(env_file))
    return sorted(found)


def docker_volume_data_path(volume_name: str) -> str:
    return f"/var/lib/docker/volumes/{volume_name}/_data"


def classify_docker_mount(mount: dict[str, Any]) -> dict[str, Any]:
    container_name = str(mount.get("container_name", ""))
    image = str(mount.get("image", ""))
    volume_name = str(mount.get("name", ""))
    destination = str(mount.get("destination", ""))
    source = str(mount.get("source", ""))
    mount_type = str(mount.get("type", ""))
    haystack = _lowered_parts(container_name, image, volume_name, destination, source)

    has_reverse_proxy_hint = any(token in haystack for token in REVERSE_PROXY_HINTS)
    destination_lower = destination.lower()
    is_db = any(token in haystack for token in DB_NAME_HINTS) or any(token in destination_lower for token in DB_DESTINATION_HINTS)
    is_reverse_proxy = has_reverse_proxy_hint or any(
        token in destination_lower for token in ("/etc/caddy", "/etc/nginx")
    )

    if mount_type == "bind":
        path = source
        kind = "bind-mount"
    elif mount_type == "volume":
        path = docker_volume_data_path(volume_name) if volume_name else source
        kind = "named-volume"
    else:
        path = source
        kind = mount_type or "unknown"

    if is_db:
        category = "database"
    elif is_reverse_proxy:
        category = "reverse-proxy"
    elif mount_type == "bind":
        category = "application-bind"
    else:
        category = "application-volume"

    return {
        **mount,
        "kind": kind,
        "category": category,
        "candidate_path": path,
        "is_database": is_db,
        "is_reverse_proxy": is_reverse_proxy,
    }


def compare_mounts_to_backup_paths(mounts: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    backup_paths = _all_profile_backup_paths(profiles)
    results: list[dict[str, Any]] = []
    for mount in mounts:
        classified = classify_docker_mount(mount)
        candidate_path = str(classified.get("candidate_path", "")).strip()
        logical_dump_coverage = False
        if classified.get("is_database"):
            container_name = str(classified.get("container_name", "")).strip()
            for profile in profiles:
                for dump_spec in _profile_database_dumps(profile):
                    if str(dump_spec.get("mode", "")).strip().lower() != "docker":
                        continue
                    if str(dump_spec.get("container", "")).strip() == container_name:
                        logical_dump_coverage = True
                        break
                if logical_dump_coverage:
                    break

        covered_by_path = bool(candidate_path and _path_is_covered(candidate_path, backup_paths))
        covered = covered_by_path or logical_dump_coverage
        status = "covered" if covered_by_path else ("covered-by-logical-dump" if logical_dump_coverage else "uncovered")

        results.append(
            {
                **classified,
                "covered": covered,
                "covered_by_path": covered_by_path,
                "covered_by_logical_dump": logical_dump_coverage,
                "coverage_status": status,
            }
        )
    return results


def _best_profile_for_path(path: str, profiles: list[dict[str, Any]], preferred_types: tuple[str, ...]) -> dict[str, Any] | None:
    normalized_path = str(path)
    typed_profiles = [profile for profile in profiles if str(profile.get("PROFILE_TYPE", "")).strip() in preferred_types]
    for profile in typed_profiles:
        raw_paths = profile.get("BACKUP_PATHS", [])
        if not isinstance(raw_paths, list):
            continue
        for backup_path in raw_paths:
            candidate = str(backup_path).strip()
            if not candidate:
                continue
            try:
                if os.path.commonpath([normalized_path, candidate]) == candidate:
                    return profile
            except ValueError:
                continue
    return typed_profiles[0] if typed_profiles else None


def suggest_missing_docker_paths(profiles: list[dict[str, Any]], mounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage = compare_mounts_to_backup_paths(mounts, profiles)
    suggestions: list[dict[str, Any]] = []
    cis_profiles = [profile for profile in profiles if str(profile.get("PROFILE_TYPE", "")).strip() == "cis-site"]
    docker_host_profiles = [profile for profile in profiles if str(profile.get("PROFILE_TYPE", "")).strip() == "docker-host"]
    docker_app_profiles = [profile for profile in profiles if str(profile.get("PROFILE_TYPE", "")).strip() == "docker-app"]

    for mount in coverage:
        if mount.get("coverage_status") != "uncovered":
            continue

        candidate_path = str(mount.get("candidate_path", "")).strip()
        if not candidate_path:
            continue

        reason = ""
        profile: dict[str, Any] | None = None
        requires_explicit_db_confirmation = False

        if mount.get("is_database"):
            requires_explicit_db_confirmation = True
            if mount.get("covered_by_logical_dump"):
                reason = "This looks like a database volume. A logical DATABASE_DUMPS entry is preferred. Raw volume backup is optional."
            else:
                reason = "This looks like a database volume. A logical DATABASE_DUMPS entry is preferred before adding the raw volume."
            profile = cis_profiles[0] if cis_profiles else (docker_app_profiles[0] if docker_app_profiles else (docker_host_profiles[0] if docker_host_profiles else None))
        elif mount.get("is_reverse_proxy"):
            profile = cis_profiles[0] if cis_profiles else (docker_host_profiles[0] if docker_host_profiles else None)
            reason = "Reverse proxy data usually belongs in a cis-site or docker-host profile."
        elif str(mount.get("type", "")) == "bind":
            profile = _best_profile_for_path(candidate_path, profiles, ("cis-site", "docker-app"))
            if profile is None and docker_host_profiles:
                profile = docker_host_profiles[0]
            reason = "Bind mounts under application directories usually belong in a docker-app or cis-site profile."
        else:
            profile = docker_host_profiles[0] if docker_host_profiles else None
            if profile is None and cis_profiles:
                profile = cis_profiles[0]
            reason = "Unknown named volumes can usually be added to docker-host first, then refined later."

        suggestions.append(
            {
                "container_name": mount.get("container_name", ""),
                "volume_name": mount.get("name", ""),
                "candidate_path": candidate_path,
                "category": mount.get("category", ""),
                "suggested_profile": str(profile.get("PROFILE_NAME", "")) if profile else "",
                "reason": reason,
                "requires_explicit_db_confirmation": requires_explicit_db_confirmation,
                "mount": mount,
            }
        )
    return suggestions


def render_docker_inventory_text(inventory: dict[str, Any]) -> str:
    safe_inventory = redact_config(inventory)
    lines = [
        "server-backup docker inventory",
        "",
        f"Hostname: {safe_inventory.get('hostname', '')}",
        f"Timestamp: {safe_inventory.get('timestamp', '')}",
        f"Docker available: {'yes' if safe_inventory.get('docker', {}).get('available') else 'no'}",
        f"Docker version: {safe_inventory.get('docker', {}).get('version', '')}",
        "",
        f"Containers running: {len(safe_inventory.get('running_containers', []))}",
        f"Containers stopped: {len(safe_inventory.get('stopped_containers', []))}",
        f"Images: {len(safe_inventory.get('images', []))}",
        f"Volumes: {len(safe_inventory.get('volumes', []))}",
        f"Networks: {len(safe_inventory.get('networks', []))}",
        f"Mounts: {len(safe_inventory.get('mounts', []))}",
        f"Compose files: {len(safe_inventory.get('compose_files', []))}",
        f".env files: {len(safe_inventory.get('env_files', []))}",
        "",
    ]
    if safe_inventory.get("warnings"):
        lines.append("Warnings:")
        for warning in safe_inventory["warnings"]:
            lines.append(f"  - {warning}")
        lines.append("")
    for container in safe_inventory.get("running_containers", []):
        lines.append(
            f"Container {container.get('name', '<unknown>')} "
            f"[image={container.get('image', '')} state={container.get('state', '')}]"
        )
        for network in container.get("networks", []):
            lines.append(f"  network: {network}")
        for port_name, mappings in (container.get("ports", {}) or {}).items():
            lines.append(f"  port {port_name}: {mappings}")
        for mount in safe_inventory.get("mounts", []):
            if mount.get("container_name") != container.get("name"):
                continue
            lines.append(
                f"  mount: {mount.get('type', '')} "
                f"{mount.get('name') or mount.get('source', '')} -> {mount.get('destination', '')}"
            )
        lines.append("")
    if safe_inventory.get("compose_files"):
        lines.append("Compose files:")
        for compose_file in safe_inventory["compose_files"]:
            lines.append(f"  - {compose_file}")
        lines.append("")
    if safe_inventory.get("env_files"):
        lines.append(".env files:")
        for env_file in safe_inventory["env_files"]:
            lines.append(f"  - {env_file}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_docker_inventory_json(inventory: dict[str, Any]) -> str:
    return json.dumps(redact_config(inventory), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def write_docker_inventory(inventory: dict[str, Any], state_dir: str | Path) -> dict[str, str]:
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    try:
        state_path.chmod(0o700)
    except PermissionError:
        pass
    stamp = _report_stamp()
    text_path = state_path / f"docker-inventory-{stamp}.txt"
    json_path = state_path / f"docker-inventory-{stamp}.json"
    text_path.write_text(render_docker_inventory_text(inventory), encoding="utf-8")
    json_path.write_text(render_docker_inventory_json(inventory), encoding="utf-8")
    return {"text_report_path": str(text_path), "json_report_path": str(json_path)}


def backup_profile_file(profile_path: str | Path) -> Path:
    source = Path(profile_path)
    if not source.exists():
        raise FileNotFoundError(f"Profile file not found: {source}")
    backup_path = source.with_name(f"{source.name}.bak-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(source, backup_path)
    return backup_path


def update_profile_backup_paths(profile_path: str | Path, paths_to_add: list[str]) -> dict[str, Any]:
    path = Path(profile_path)
    profile = parse_config_file(path)
    raw_paths = profile.get("BACKUP_PATHS", [])
    if not isinstance(raw_paths, list):
        raw_paths = []
    existing_paths = [str(item).strip() for item in raw_paths if str(item).strip()]

    added_paths: list[str] = []
    skipped_paths: list[str] = []
    merged_paths = list(existing_paths)
    for candidate in [str(item).strip() for item in paths_to_add if str(item).strip()]:
        if candidate in merged_paths:
            skipped_paths.append(candidate)
            continue
        merged_paths.append(candidate)
        added_paths.append(candidate)

    if not added_paths:
        return {
            "profile_path": str(path),
            "backup_path": "",
            "added_paths": [],
            "skipped_paths": skipped_paths,
            "validation": validate_profile_config(profile),
        }

    profile["BACKUP_PATHS"] = merged_paths
    rendered = render_profile_conf(profile)
    backup_path = backup_profile_file(path)
    owner_uid = 0 if os.geteuid() == 0 else None
    owner_gid = 0 if os.geteuid() == 0 else None
    write_file_secure(
        path,
        rendered,
        mode=0o600,
        backup_existing=False,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    updated_profile = parse_config_file(path)
    validation = validate_profile_config(updated_profile)
    return {
        "profile_path": str(path),
        "backup_path": str(backup_path),
        "added_paths": added_paths,
        "skipped_paths": skipped_paths,
        "validation": validation,
    }
