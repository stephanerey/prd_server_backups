#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [--enable-timer]

Installs the initial host-level server-backup scaffolding on Debian/Ubuntu.
The timer is not enabled by default.
EOF
}

log() {
  printf '[server-backup] %s\n' "$*"
}

fail() {
  printf '[server-backup] ERROR: %s\n' "$*" >&2
  exit 1
}

is_pkg_installed() {
  local pkg="$1"
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q '^install ok installed$'
}

pkg_available() {
  local pkg="$1"
  apt-cache show "$pkg" >/dev/null 2>&1
}

ensure_dir() {
  local path="$1"
  install -d -m 0700 -o root -g root "$path"
}

copy_if_missing() {
  local src="$1"
  local dst="$2"
  local mode="$3"
  if [[ -e "$dst" ]]; then
    log "Preserving existing $dst"
    return 0
  fi
  install -m "$mode" -o root -g root "$src" "$dst"
  log "Installed $dst"
}

install_file() {
  local src="$1"
  local dst="$2"
  local mode="$3"
  install -m "$mode" -o root -g root "$src" "$dst"
  log "Updated $dst"
}

install_if_directory_exists() {
  local src="$1"
  local dst="$2"
  local mode="$3"
  local parent
  parent="$(dirname "$dst")"
  if [[ ! -d "$parent" ]]; then
    log "Skipping $dst because $parent does not exist."
    return 0
  fi
  install_file "$src" "$dst" "$mode"
}

install_python_package() {
  local src_dir="$1"
  local dst_root="/usr/local/lib/server-backup"
  local dst_pkg="$dst_root/server_backup"

  install -d -m 0755 -o root -g root "$dst_root" "$dst_pkg"
  install_file "$src_dir/__init__.py" "$dst_pkg/__init__.py" 0644
  install_file "$src_dir/backup.py" "$dst_pkg/backup.py" 0644
  install_file "$src_dir/cli.py" "$dst_pkg/cli.py" 0644
  install_file "$src_dir/config.py" "$dst_pkg/config.py" 0644
  install_file "$src_dir/coverage.py" "$dst_pkg/coverage.py" 0644
  install_file "$src_dir/db.py" "$dst_pkg/db.py" 0644
  install_file "$src_dir/docker.py" "$dst_pkg/docker.py" 0644
  install_file "$src_dir/email_report.py" "$dst_pkg/email_report.py" 0644
  install_file "$src_dir/health.py" "$dst_pkg/health.py" 0644
  install_file "$src_dir/restic.py" "$dst_pkg/restic.py" 0644
  install_file "$src_dir/restore.py" "$dst_pkg/restore.py" 0644
  install_file "$src_dir/ssh.py" "$dst_pkg/ssh.py" 0644
  install_file "$src_dir/validation.py" "$dst_pkg/validation.py" 0644
  install_file "$src_dir/validators.py" "$dst_pkg/validators.py" 0644
  install_file "$src_dir/wizard.py" "$dst_pkg/wizard.py" 0644
}

main() {
  local enable_timer="false"
  while (($#)); do
    case "$1" in
      --enable-timer)
        enable_timer="true"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
    shift
  done

  if [[ "${EUID}" -ne 0 ]]; then
    fail "This installer must be run as root."
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    fail "apt-get is required. This installer supports Debian/Ubuntu only."
  fi

  if [[ ! -r /etc/os-release ]]; then
    fail "/etc/os-release is missing. Cannot detect distribution."
  fi

  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" != "debian" && "${ID:-}" != "ubuntu" ]]; then
    case " ${ID_LIKE:-} " in
      *" debian "*) ;;
      *)
        fail "Unsupported distribution: ${PRETTY_NAME:-unknown}. Expected Debian/Ubuntu."
        ;;
    esac
  fi

  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  local packages=(
    restic
    openssh-client
    python3
    postgresql-client
  )

  if pkg_available mariadb-client; then
    packages+=(mariadb-client)
  elif pkg_available mysql-client; then
    packages+=(mysql-client)
  else
    log "Neither mariadb-client nor mysql-client is available via apt; skipping SQL client package."
  fi

  if pkg_available mailutils; then
    packages+=(mailutils)
  else
    log "mailutils is not available via apt; skipping mailutils."
  fi

  if pkg_available logrotate; then
    packages+=(logrotate)
  else
    log "logrotate is not available via apt; skipping logrotate."
  fi

  local missing_packages=()
  local pkg
  for pkg in "${packages[@]}"; do
    if ! is_pkg_installed "$pkg"; then
      missing_packages+=("$pkg")
    fi
  done

  if ((${#missing_packages[@]} > 0)); then
    log "Installing packages: ${missing_packages[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_packages[@]}"
  else
    log "Required packages are already installed."
  fi

  local secure_dirs=(
    /etc/server-backup
    /etc/server-backup/secrets
    /etc/server-backup/secrets/db
    /etc/server-backup/ssh
    /etc/server-backup/targets.d
    /etc/server-backup/profiles.d
    /etc/server-backup/hooks.d
    /etc/server-backup/hooks.d/pre-backup.d
    /etc/server-backup/hooks.d/post-backup.d
    /etc/server-backup/hooks.d/pre-profile.d
    /etc/server-backup/hooks.d/post-profile.d
    /var/cache/restic
    /var/lib/server-backup
    /var/lib/server-backup/state
    /var/lib/server-backup/reports
  )

  local dir
  for dir in "${secure_dirs[@]}"; do
    ensure_dir "$dir"
  done

  copy_if_missing "$repo_root/examples/backup.conf.example" "/etc/server-backup/backup.conf.example" 0600
  copy_if_missing "$repo_root/examples/backup.conf.example" "/etc/server-backup/backup.conf" 0600
  copy_if_missing "$repo_root/examples/targets/sftp.env.example" "/etc/server-backup/targets.d/sftp.env.example" 0600
  copy_if_missing "$repo_root/examples/profiles/docker-host.conf.example" "/etc/server-backup/profiles.d/docker-host.conf.example" 0600
  copy_if_missing "$repo_root/examples/profiles/cis-site.conf.example" "/etc/server-backup/profiles.d/cis-site.conf.example" 0600
  copy_if_missing "$repo_root/examples/profiles/system-filesystem.conf.example" "/etc/server-backup/profiles.d/system-filesystem.conf.example" 0600

  install_python_package "$repo_root/server_backup"
  install_file "$repo_root/scripts/server-backup" "/usr/local/bin/server-backup" 0755
  install_file "$repo_root/scripts/server-backup-run" "/usr/local/sbin/server-backup-run" 0755

  install_file "$repo_root/systemd/server-backup.service" "/etc/systemd/system/server-backup.service" 0644
  copy_if_missing "$repo_root/systemd/server-backup.timer" "/etc/systemd/system/server-backup.timer" 0644
  install_if_directory_exists "$repo_root/packaging/logrotate/server-backup" "/etc/logrotate.d/server-backup" 0644

  systemctl daemon-reload

  if [[ "$enable_timer" == "true" ]]; then
    systemctl enable --now server-backup.timer
    log "Enabled and started server-backup.timer"
  else
    log "Timer installation completed but remains disabled."
  fi

  cat <<'EOF'

Next steps:
  1. Run: sudo server-backup setup
  2. Run: sudo server-backup target add
  3. Run: sudo server-backup profile add
  4. Review /etc/server-backup/profiles.d/*.example
  5. Run: sudo server-backup health
  6. Run: sudo systemctl enable --now server-backup.timer
  7. Run: sudo systemctl list-timers | grep server-backup
EOF
}

main "$@"
