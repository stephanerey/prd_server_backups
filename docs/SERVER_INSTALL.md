# Server Install

## Prerequisites

- Debian or Ubuntu host
- `root` or `sudo`
- `systemd`
- outbound network access for package installation

This MVP runs directly on the Linux host. Docker is a backup target to inspect later, not the runtime of `server-backup`.
This PR only scaffolds the SFTP target backend. Other backends remain future work.

## Installation

From the repository root:

```bash
sudo ./scripts/install.sh
```

## What `install.sh` Creates

The installer creates these root-only paths:

- `/etc/server-backup`
- `/etc/server-backup/secrets`
- `/etc/server-backup/secrets/db`
- `/etc/server-backup/ssh`
- `/etc/server-backup/targets.d`
- `/etc/server-backup/profiles.d`
- `/etc/server-backup/hooks.d`
- `/etc/server-backup/hooks.d/pre-backup.d`
- `/etc/server-backup/hooks.d/post-backup.d`
- `/etc/server-backup/hooks.d/pre-profile.d`
- `/etc/server-backup/hooks.d/post-profile.d`
- `/var/cache/restic`
- `/var/lib/server-backup`
- `/var/lib/server-backup/state`
- `/var/lib/server-backup/reports`

It also installs:

- `/usr/local/bin/server-backup`
- `/usr/local/sbin/server-backup-run`
- `/etc/systemd/system/server-backup.service`
- `/etc/systemd/system/server-backup.timer`

The installer is idempotent:

- `/etc/server-backup/backup.conf.example` is installed if missing
- an existing live `/etc/server-backup/backup.conf` is preserved
- existing secrets are preserved
- existing SSH keys are preserved
- existing target files are preserved
- existing profile files are preserved

## Verification Commands

```bash
server-backup --help
server-backup status
sudo server-backup status
sudo server-backup health
sudo server-backup operations status
sudo server-backup config validate
systemctl status server-backup.timer
systemctl cat server-backup.service
systemctl cat server-backup.timer
```

## Global Setup Wizard

After installation, run:

```bash
sudo server-backup setup
```

The wizard currently configures only the global host-level settings:

- backup name and tags
- retention policy
- daily timer hour
- prune, check and coverage-audit flags
- email-report settings
- restic password file path
- optional restic password generation
- optional timer enablement

The installer only lays down `/etc/server-backup/backup.conf.example`.
The wizard then writes the live `/etc/server-backup/backup.conf` in `0600 root:root`.

If requested, it can also create `/etc/server-backup/secrets/restic-password` in `0600 root:root`.

The timer hour is applied to `/etc/systemd/system/server-backup.timer`, then `systemctl daemon-reload` is run. The timer is only enabled if you confirm it.

When setup completes, the next recommended command is:

```bash
sudo server-backup target add
```

Before enabling the timer, run a local health check:

```bash
sudo server-backup health
sudo server-backup operations status
```

## Add an SFTP NAS Target

After the global setup, add the first target:

```bash
sudo server-backup target add
```

The target wizard currently supports only the MVP SFTP backend. It asks for:

- target name
- NAS hostname or IP
- SSH port
- remote SSH user
- remote restic repository path
- dedicated SSH key generation or reuse
- optional host-key retrieval with `ssh-keyscan`
- optional immediate SFTP connectivity test

It writes:

- `/etc/server-backup/targets.d/<target>.env`
- `/etc/server-backup/ssh/id_ed25519_<target>`
- `/etc/server-backup/ssh/id_ed25519_<target>.pub`
- `/etc/server-backup/ssh/ssh_config`
- `/etc/server-backup/ssh/known_hosts`

The wizard displays the public key to copy into the NAS `authorized_keys` file. It never prints the private key.

Test the target after the NAS-side key installation:

```bash
sudo server-backup target test <target>
```

If no NAS is ready yet, you can still generate the files now and rerun the test later.

## Initialize the Restic Repository

After `target add` and a successful `target test`, initialize the remote repository:

```bash
sudo server-backup repo init <target>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

Important:

- `target add` must exist first
- the public SSH key must already be installed on the NAS
- `target test` should succeed before `repo init`
- `RESTIC_PASSWORD_FILE` must exist
- `repo init` creates only the repository structure
- `repo init` does not run any backup

## First Backup

Once the repository exists and at least one profile exists, you can test the backup plan:

```bash
sudo server-backup backup run --dry-run
```

Then run a real backup:

```bash
sudo server-backup backup run
```

Important:

- `repo init` must be done before `backup run`
- at least one profile must exist
- `--dry-run` contacts the target but does not create a snapshot
- a real `backup run` creates one or more restic snapshots
- local reports are written under `/var/lib/server-backup/reports`
- the latest summary is written to `/var/lib/server-backup/state/last-backup-run.json`

After the first backup, verify snapshots and retention:

```bash
sudo server-backup repo snapshots <target>
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune <target> --yes
```

With only one snapshot, prune will usually keep everything. Dry-run is still recommended before the first real prune.

## Timer Activation

The timer stays disabled until you enable it explicitly:

```bash
sudo systemctl enable --now server-backup.timer
sudo systemctl list-timers | grep server-backup
sudo systemctl status server-backup.timer --no-pager
```

To stop the timer again:

```bash
sudo systemctl disable --now server-backup.timer
```

To launch one run manually without waiting for the schedule:

```bash
sudo systemctl start server-backup.service
```

## Logging and Log Rotation

Primary operational logs are available through `journalctl`:

```bash
journalctl -u server-backup.service
```

If `logrotate` is available, the installer also installs:

```text
/etc/logrotate.d/server-backup
```

for `/var/log/server-backup.log` with:

- `weekly`
- `rotate 8`
- `compress`
- `missingok`
- `notifempty`

If that log file is not actively used in your deployment, `journalctl` remains
the main source of truth.

## Coverage Audit

After targets and profiles exist, run a local coverage audit:

```bash
sudo server-backup coverage audit
```

Useful variants:

```bash
sudo server-backup coverage audit --profile <profile>
sudo server-backup coverage audit --json
```

The audit:

- stays local to the source host
- does not contact the NAS
- does not run restic
- does not modify configuration
- does not read or print `.env` contents

Use it to detect obvious gaps, then correct the profile files manually.

## Database Dumps

After profiles exist, attach logical database dumps where needed:

```bash
sudo server-backup db add
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

Important:

- DB secrets are stored under `/etc/server-backup/secrets/db/<profile>/` in `0600 root:root`
- logical DB dumps are the primary coverage for database content
- raw Docker DB volumes can remain optional once a matching logical dump exists
- `db dump-test` creates temporary files only and cleans them unless `--keep-output` is used

After a DB dump is configured, `backup run` executes the logical dump before `restic backup`.

## Email Reports

Email delivery is optional and depends on a local MTA that already works on the host.
This project does not configure SMTP, relay authentication, DKIM, SPF or DMARC.

Supported local delivery commands:

- `/usr/sbin/sendmail -t -f <EMAIL_REPORT_FROM>`
- `mail` or `mailx`

Configure email reporting in `/etc/server-backup/backup.conf`:

- `EMAIL_REPORT_ENABLED`
- `EMAIL_REPORT_TO`
- `EMAIL_REPORT_FROM`
- `EMAIL_REPORT_SUBJECT_PREFIX`
- `EMAIL_REPORT_SEND_ON_SUCCESS`
- `EMAIL_REPORT_SEND_ON_FAILURE`
- `EMAIL_REPORT_COMMAND`

Before enabling automatic reports, verify the local mail path first:

```bash
sudo server-backup email test --to admin@example.net
```

If `EMAIL_REPORT_ENABLED="false"`, `server-backup email test` still works for diagnostics.
If `EMAIL_REPORT_FROM` is empty, the test command falls back to `server-backup@<hostname>`.
With `sendmail`, automatic delivery uses `EMAIL_REPORT_FROM` as the envelope sender via `-f`.

Important:

- a local `sendmail` success only means the message was accepted by the local MTA
- a remote provider such as Gmail can still reject it later
- SPF, DKIM or an authenticated SMTP relay remain external prerequisites

Automatic emails are sent only:

- after `backup run`
- after `repo prune`
- after `restore test`

and only when `EMAIL_REPORT_ENABLED="true"` plus the success/failure policy allows it.

## Non-Destructive Restore Test

Run a restore test regularly:

```bash
sudo server-backup restore test --target <target>
sudo server-backup restore test --target <target> --keep-output
```

Important:

- restore test always restores into `/tmp`
- it does not touch production paths
- it verifies that files were actually restored
- it generates a local report
- it should be run regularly, not only after incidents

With `--keep-output`, the restored directory remains available for manual inspection.

## Create a Backup Profile

After the target is defined, create at least one profile:

```bash
sudo server-backup profile add
```

Supported profile types in this PR:

- `generic`
- `system-filesystem`
- `docker-host`
- `docker-app`
- `cis-site`

The wizard writes `/etc/server-backup/profiles.d/<profile>.conf` in `0600 root:root`.

Use the profile types as follows:

- `generic`: manual application paths and excludes
- `system-filesystem`: broad host backup of important system trees
- `docker-host`: host-level Docker paths, bind mounts and state
- `docker-app`: one Compose-style Docker application plus its mounts
- `cis-site`: CIS website structure with frontend/backend/content classification placeholders

The wizard only generates editable configuration. It does not run a backup, a DB dump or a coverage audit in this PR.

## Timer Activation

The timer is installed but not enabled automatically unless `--enable-timer` is passed.

Manual activation:

```bash
sudo systemctl enable --now server-backup.timer
```
