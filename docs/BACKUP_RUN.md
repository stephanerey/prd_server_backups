# Backup Run

`server-backup backup run` is the first command in the MVP that creates real restic snapshots.

## Commands

Dry-run all configured targets and profiles:

```bash
sudo server-backup backup run --dry-run
```

Real backup on all configured targets and profiles:

```bash
sudo server-backup backup run
```

Limit the run to one target:

```bash
sudo server-backup backup run --target <target>
```

Limit the run to one profile:

```bash
sudo server-backup backup run --profile system-filesystem
```

Limit the run to one target and one profile:

```bash
sudo server-backup backup run --target <target> --profile system-filesystem
```

## Behavior

- without `--target`, all configured targets are attempted
- without `--profile`, all configured profiles are attempted
- one failing target does not stop the others
- one failing profile does not stop the other profiles on the same target
- the overall exit code is non-zero if at least one target or profile fails
- `--dry-run` reaches the repository but does not create a snapshot
- `--dry-run` still scans local files and can therefore take several minutes
- pressing `Ctrl+C` interrupts the run, releases the local lock and may leave only a partial report

Each target/profile pair runs its own `restic backup` command with tags built from:

- `server-backup`
- `BACKUP_NAME`
- `PROFILE_NAME`
- `PROFILE_TYPE`
- each whitespace-separated token from `BACKUP_TAGS`

## Database Dumps Before Restic

If a profile declares `DATABASE_DUMPS`, `server-backup` now runs those logical dumps before the matching `restic backup`.

Behavior:

- each configured dump writes into a temporary directory under `LOCAL_DUMP_DIR`
- dump files are appended to the paths passed to `restic backup`
- temporary dump files are always cleaned after the profile run
- if a logical dump fails, that profile fails and `restic backup` is not started for it
- the backup report records dump status, files, warnings and errors

This applies to both real backups and `--dry-run`. Dry-run still validates dump creation and still scans local files.

## Missing Paths

- if a profile path exists, it is included
- if a profile path does not exist, a warning is recorded
- if all profile paths are missing, that profile fails and no restic backup is launched for it

Filesystem profiles do not replace logical DB backups. When a database matters, add `DATABASE_DUMPS` to the relevant profile.

The same applies to Docker storage paths added to `BACKUP_PATHS`:

- once a bind mount or named volume path is added to a profile, it is included in the next `restic backup`
- this does not modify Docker itself
- database volumes remain a special case where logical dumps are preferred

## Reports

Every `backup run` writes:

- `/var/lib/server-backup/reports/backup-run-YYYYMMDD-HHMMSS.txt`
- `/var/lib/server-backup/reports/backup-run-YYYYMMDD-HHMMSS.json`
- `/var/lib/server-backup/state/last-backup-run.json`

The reports include:

- start/end time
- duration
- dry-run flag
- target/profile results
- included paths
- missing paths
- excludes
- command summaries without secrets
- filtered stdout/stderr

The reports never include:

- restic password contents
- SSH private keys
- tokens or secrets

## Locking

`backup run` uses the same local flock-based lock as the `repo` commands:

- preferred: `/run/server-backup-repo.lock`
- fallback: `/tmp/server-backup-repo.lock`

Only one local restic operation can run at a time.

## Frequent Errors

- no target configured
- no profile configured
- repository not initialized
- bad restic password
- SFTP target unreachable
- missing local profile paths
- another local restic operation already running
- interrupted run with only a partial report written

## Difference from Repo Commands

- `repo init` prepares the repository
- `repo check` verifies repository integrity
- `repo snapshots` lists snapshots
- `backup run` is the command that actually creates snapshots
