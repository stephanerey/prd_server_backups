# Restore Test

`server-backup restore test` performs a non-destructive validation of an existing restic snapshot.

## Commands

Restore the latest snapshot into a temporary directory:

```bash
sudo server-backup restore test --target <target>
```

Keep the restored output for inspection:

```bash
sudo server-backup restore test --target <target> --keep-output
```

Restore a specific snapshot:

```bash
sudo server-backup restore test --target <target> --snapshot <snapshot-id>
```

Limit checks to one profile:

```bash
sudo server-backup restore test --target <target> --profile <profile>
```

Limit the restore to one or more paths:

```bash
sudo server-backup restore test --target <target> --include /var/lib/server-backup/state
```

## Safety

- restore test never restores directly into production paths
- default output is under `/tmp/server-backup-restore-test-*`
- dangerous output paths such as `/`, `/etc`, `/srv`, `/opt` and `/var/lib/docker` are refused
- an existing output directory is refused
- without `--keep-output`, the temporary restore directory is removed after checks
- pressing `Ctrl+C` interrupts the restore test, releases the local restic lock and may leave only a partial report

## What It Verifies

- the snapshot can actually be restored
- the output directory is created
- files or directories are present after restore
- file count and approximate restored size
- expected profile paths when profile checks are available
- dump files if present in the restored tree
- CIS-specific file layout checks when applicable

## Reports

Each restore test writes:

- `/var/lib/server-backup/reports/restore-test-YYYYMMDD-HHMMSS.txt`
- `/var/lib/server-backup/reports/restore-test-YYYYMMDD-HHMMSS.json`

Successful or warning restore tests also update:

- `/var/lib/server-backup/state/last-restore-test.json`

## Limits

This PR does not:

- restore a database into a running instance
- start Docker Compose
- run application services
- perform a full disaster recovery

It is a restore validation step, not a production restore workflow.
