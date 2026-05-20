# Release Notes — v1.0.0

## Summary

`server-backup` v1.0.0 delivers the first stable host-level release of the
backup system described by the original PRD set. The validated stack covers
SFTP/restic backups, logical database dumps, coverage auditing, non-destructive
restore tests, local/email reporting, and operational runbooks.

## Validated Features

- host-level installation on Debian/Ubuntu
- global setup wizard and hand-editable configuration under `/etc/server-backup`
- isolated SSH/SFTP targets for NAS repositories
- `restic` repository init, check, snapshots, backup, prune, and restore test
- profiles for generic, system-filesystem, docker-host, docker-app, and cis-site
- logical PostgreSQL and MySQL/MariaDB dumps
- Docker inventory and coverage assistance
- email reports through a preconfigured local `sendmail` or `mail` command
- health, operations status, and production validation
- deployment, operations, troubleshooting, and release runbooks

## Known Limits

- no cloud backend beyond SFTP in v1.0.0
- no destructive disaster-recovery orchestration
- no automatic correction of coverage findings
- no automatic SMTP setup or remote NAS/VPN provisioning
- no database restore workflow in this release

## Prerequisites

- Debian or Ubuntu host
- root or sudo access
- reachable NAS over SSH/SFTP, optionally via WireGuard
- local `sendmail` or `mail` already configured if email reports are required
- restore password and secrets stored outside the protected server

## Short Installation

```bash
git clone <repo-url>
cd prd_server_backups
sudo ./scripts/install.sh
sudo server-backup setup
sudo server-backup target add
sudo server-backup repo init <target>
sudo server-backup profile add
sudo server-backup db add
```

## Short Validation

```bash
sudo server-backup health
sudo server-backup coverage audit
sudo server-backup backup run --dry-run --target <target>
sudo server-backup restore test --target <target>
sudo server-backup validate production --target <target> --profile <profile>
```

## Security Notes

- never commit secrets, SSH private keys, VPN private keys, or DB passwords
- store the `restic` password outside the server in the restore kit
- review generated reports before enabling the systemd timer
- run a restore test before considering the deployment complete
