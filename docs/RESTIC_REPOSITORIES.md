# Restic Repositories

This PR covers repository lifecycle commands and the first real `backup run`.

## Commands

Initialize one target:

```bash
sudo server-backup repo init <target>
```

Check one target:

```bash
sudo server-backup repo check <target>
```

List snapshots for one target:

```bash
sudo server-backup repo snapshots <target>
```

Apply retention to one target:

```bash
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune <target> --yes
```

Run the same action on all configured targets:

```bash
sudo server-backup repo init --all
sudo server-backup repo check --all
sudo server-backup repo snapshots --all
sudo server-backup repo prune --all --dry-run
sudo server-backup repo prune --all --yes
```

## What These Commands Do

- `repo init` creates the remote restic repository structure
- `repo check` runs `restic check`
- `repo snapshots` lists existing snapshots
- `repo prune` applies the retention policy from `backup.conf`

They do not:

- prune snapshots
- perform restore tests

## Backups and Snapshots

Repository commands prepare and inspect the repository.

The command that actually creates snapshots is:

```bash
sudo server-backup backup run
```

After the first successful backup, use:

```bash
sudo server-backup repo snapshots <target>
```

to verify that a snapshot now exists.

`repo snapshots` only lists repository contents.

`restore test` is different:

- it uses an existing snapshot
- it restores files into a temporary directory
- it never restores directly into production paths
- it verifies that the restored files are readable

## Retention and Prune

`repo prune` uses:

- `RETENTION_DAILY`
- `RETENTION_WEEKLY`
- `RETENTION_MONTHLY`

Dry-run mode uses:

```bash
restic forget --keep-daily N --keep-weekly N --keep-monthly N --dry-run
```

Real prune uses:

```bash
restic forget --keep-daily N --keep-weekly N --keep-monthly N --prune
```

Important:

- dry-run does not delete anything
- real prune is destructive
- real prune asks for confirmation unless `--yes` is provided
- run a dry-run before the first real prune

Operational difference:

- `forget` removes snapshot references according to retention rules
- `prune` removes now-unreferenced repository data
- in this CLI, real prune uses `forget ... --prune`

## Local Locking

Only one local restic operation is allowed at a time on the same host.

The CLI takes a local flock-based lock before any restic command:

- preferred lock file: `/run/server-backup-repo.lock`
- fallback lock file: `/tmp/server-backup-repo.lock`

Default timeout:

- `30` seconds

The same lock is used by:

- `server-backup repo init`
- `server-backup repo check`
- `server-backup repo snapshots`
- `server-backup repo prune`
- `server-backup backup run`

If the lock is already held, the command exits with a clear error instead of waiting indefinitely.

If you interrupt a long-running repository command with `Ctrl+C`:

- the local lock is released
- the CLI exits without a Python stacktrace
- the operation may stop before any report is fully written

## SSH Behavior

The repository commands do not depend on `/root/.ssh/config`.

They build a dedicated SFTP transport command from:

- `/etc/server-backup/ssh/ssh_config`
- the target `SSH_HOST_ALIAS`

Equivalent form:

```text
ssh -F /etc/server-backup/ssh/ssh_config <alias> -s sftp
```

## Frequent Errors

- repository not initialized yet
- another local `server-backup repo` operation is already running
- SSH host-key validation failed
- SSH authentication failed
- DNS failure or NAS unreachable
- wrong restic password
- damaged repository metadata
- profile path missing locally

## Local Reports

Each prune run writes:

- `/var/lib/server-backup/reports/prune-run-YYYYMMDD-HHMMSS.txt`
- `/var/lib/server-backup/reports/prune-run-YYYYMMDD-HHMMSS.json`
- `/var/lib/server-backup/state/last-prune-run.json`

## Password Safety

- `RESTIC_PASSWORD_FILE` is required
- its content is never printed by the CLI
- losing the password makes encrypted backups unusable
