# server-backup

`server-backup` is a host-level backup toolkit for Debian/Ubuntu servers.
It manages local configuration, isolated SSH/SFTP targets, `restic`
repositories, application profiles, logical database dumps, coverage audits,
non-destructive restore tests, email reports, and operations runbooks.

## Status

Version `1.0.0` is prepared for production use on the validated reference VPS.
The project runs directly on the Linux host. Docker is inspected and backed up
as workload data; it is not the runtime for `server-backup` itself.

## Main Features

- idempotent host-level installer
- interactive global setup wizard
- isolated SFTP targets with dedicated SSH keys and `known_hosts`
- `restic` repository init, snapshots, check, backup, prune, and restore test
- profiles for `generic`, `system-filesystem`, `docker-host`, `docker-app`, and `cis-site`
- PostgreSQL and MySQL/MariaDB logical dump support
- Docker inventory and coverage assistance
- local text/JSON reports for backup, prune, restore, coverage, validation, and email
- local health checks and operations status
- systemd service/timer and optional logrotate integration

## Architecture

```text
Linux host
├── /etc/server-backup              hand-editable configuration
├── /var/lib/server-backup          reports and state
├── /var/cache/restic               restic cache
├── /var/tmp/server-backup          temporary dump and restore workdirs
└── server-backup
     ├── target SFTP over SSH/WireGuard
     ├── restic repository per target
     ├── optional logical DB dumps
     ├── coverage audit and restore test
     └── local and email reports
```

## Quick Install

```bash
git clone https://github.com/stephanerey/prd_server_backups.git
cd prd_server_backups
sudo ./scripts/install.sh
sudo server-backup setup
```

`install.sh` installs `/etc/server-backup/backup.conf.example` but does not
create a live `/etc/server-backup/backup.conf` anymore. Use
`sudo server-backup setup` to generate the real configuration.

## Quick Configuration Flow

```bash
sudo server-backup target add
sudo server-backup target test <target>
sudo server-backup repo init <target>
sudo server-backup profile add
sudo server-backup db add
sudo server-backup coverage audit
sudo server-backup backup run --dry-run --target <target>
```

## Main Commands

```bash
sudo server-backup status
sudo server-backup health
sudo server-backup operations status
sudo server-backup config validate
sudo server-backup backup run --dry-run
sudo server-backup repo check <target>
sudo server-backup restore test --target <target>
sudo server-backup coverage audit
sudo server-backup validate production --target <target> --profile <profile>
```

## Security and Secrets

- never commit `/etc/server-backup` runtime files into Git
- keep `RESTIC_PASSWORD_FILE`, DB secrets, SSH private keys, and VPN secrets root-only
- never store the `restic` password in the repository it protects
- keep the restore kit outside the source server
- review reports before enabling automatic scheduling

## Useful Documentation

- [Server install guide](docs/SERVER_INSTALL.md)
- [Deployment runbook](docs/DEPLOYMENT_RUNBOOK.md)
- [Operations runbook](docs/OPERATIONS_RUNBOOK.md)
- [Final validation](docs/FINAL_VALIDATION.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Restore kit](docs/RESTORE_KIT.md)
- [Scheduling policy](docs/SCHEDULING_POLICY.md)
- [Database dumps](docs/DATABASE_DUMPS.md)
- [Docker coverage](docs/DOCKER_COVERAGE.md)
- [Postfix OVH relay](docs/POSTFIX_OVH_RELAY.md)

## Historical PRD Documents

The original design documents are kept for traceability in [prd/README.md](prd/README.md).
They explain how the feature set was specified before the implementation was completed.

## Developer History

Historical Codex implementation prompts are kept in [codex_prompts/README.md](codex_prompts/README.md).
They are useful for maintenance history, not for a normal installation.
