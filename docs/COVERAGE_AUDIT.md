# Coverage Audit

`server-backup coverage audit` performs a local-only audit of the backup scope.

It is meant to catch obvious gaps before an incident.

## Commands

Run the full local audit:

```bash
sudo server-backup coverage audit
```

Limit the audit to one profile:

```bash
sudo server-backup coverage audit --profile <profile>
```

Print the redacted JSON report to stdout:

```bash
sudo server-backup coverage audit --json
```

Write reports to another directory:

```bash
sudo server-backup coverage audit --output-dir /tmp/server-backup-audit
```

## Severity Levels

- `SUCCESS`
- `WARNING`
- `FAILURE`

Exit code:

- `0` for `SUCCESS` or `WARNING`
- non-zero for `FAILURE`

## What It Checks

Generic checks:

- `backup.conf` present and locally valid
- at least one target
- at least one profile
- `RESTIC_PASSWORD_FILE` present locally
- `RESTIC_CACHE_DIR` present locally
- previous backup and restore-test state files
- automatic email disabled or enabled

Profile checks:

- missing `BACKUP_PATHS`
- missing local paths
- profiles with no existing path left
- CIS profile placeholders still missing

Docker checks when Docker is available:

- active containers
- local bind mounts
- local named volumes
- mount paths not covered by any profile
- compose directories and adjacent `.env` files not covered
- DB container storage marked as logically covered when a matching `DATABASE_DUMPS` entry exists
- reverse-proxy volumes such as Caddy, nginx or Traefik data/config paths

CIS checks:

- `WEB_CONTENT_CRITICAL`
- `CONTENT_CLASSIFICATION`
- `DATABASE_DUMPS`
- likely frontend/backend/migrations coverage
- media/uploads/assets classification hints

When a Docker database volume belongs to a container already covered by a logical dump:

- the logical dump is treated as the primary coverage
- the raw DB volume stays optional
- the audit reports that explicitly instead of flagging the DB volume as uncovered

When a reverse proxy volume is not covered:

- the audit reports it as a Docker warning
- the operator can review it with `server-backup docker coverage`
- the operator can then decide whether to add it to `BACKUP_PATHS`

Useful Docker-oriented commands:

```bash
sudo server-backup docker scan
sudo server-backup docker inventory
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
sudo server-backup docker add-missing-paths --profile <profile> --dry-run
```

## What It Does Not Do

- no NAS access
- no restic call
- no `docker compose`
- no DB connection
- no automatic profile correction
- no configuration rewrite

## Reports

Each run writes:

- `/var/lib/server-backup/reports/coverage-audit-YYYYMMDD-HHMMSS.txt`
- `/var/lib/server-backup/reports/coverage-audit-YYYYMMDD-HHMMSS.json`
- `/var/lib/server-backup/state/last-coverage-audit.json`

## Security

The audit never prints:

- `.env` contents
- passwords
- SSH private keys
- tokens or secrets

It reports coverage gaps, not secret values.
