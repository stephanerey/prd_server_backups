# Email Reports

`server-backup` can send local text reports after:

- `backup run`
- `repo prune`
- `restore test`

It can also send a manual test message with:

```bash
sudo server-backup email test
sudo server-backup email test --to admin@example.net
```

## Scope

This project only uses an already working local mail transport.

Supported commands:

- `/usr/sbin/sendmail -t -f <EMAIL_REPORT_FROM>`
- `mail`
- `mailx`

Out of scope:

- SMTP configuration
- relay authentication
- DKIM
- SPF
- DMARC
- MTA installation or administration

## Configuration

Relevant fields in `/etc/server-backup/backup.conf`:

```bash
EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="admin@example.net"
EMAIL_REPORT_FROM="server-backup@example.net"
EMAIL_REPORT_SUBJECT_PREFIX="[server-backup]"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
EMAIL_REPORT_COMMAND="sendmail"
```

Rules:

- if `EMAIL_REPORT_ENABLED="false"`, automatic reports are skipped
- `server-backup email test` can still be used for diagnostics
- if `EMAIL_REPORT_TO` is empty, use `--to`
- if `EMAIL_REPORT_FROM` is empty, `email test` falls back to `server-backup@<hostname>`
- automatic reports require `EMAIL_REPORT_FROM` when enabled

## Automatic Send Policy

Automatic sending follows:

- `EMAIL_REPORT_SEND_ON_SUCCESS="true"` for successful runs
- `EMAIL_REPORT_SEND_ON_FAILURE="true"` for warning or failure runs

If delivery fails:

- the main backup/prune/restore result stays visible
- the email error is added as a warning when possible
- local report files are still kept on disk

## Redaction

Before sending, report bodies are sanitized.

Any line containing one of these tokens is replaced with `<redacted>`:

- `PASSWORD`
- `SECRET`
- `TOKEN`
- `KEY`
- `PGPASSWORD`
- `MYSQL_PWD`
- `RESTIC_PASSWORD`
- `RESTIC_PASSWORD_FILE`
- `SSH_IDENTITY_FILE`
- `PRIVATE`
- `PASSPHRASE`

The goal is to keep operational context while never mailing sensitive values.

## Local State

Each email attempt updates:

- `/var/lib/server-backup/state/last-email-report.json`

This state file stores metadata only:

- report kind
- status
- recipient
- sender
- subject
- command used
- timestamp
- success or failure
- sanitized error if delivery failed

It does not store the raw unsanitized mail body.

## Troubleshooting

Useful checks:

```bash
sudo server-backup status
sudo server-backup config validate
sudo server-backup email test --to admin@example.net
```

Common failure cases:

- `EMAIL_REPORT_TO` missing
- `EMAIL_REPORT_FROM` missing for automatic reports
- `EMAIL_REPORT_COMMAND` invalid
- `sendmail` missing
- `mail` or `mailx` missing
- local MTA installed but not configured

If the mail path is not working yet, fix the host MTA first. `server-backup`
will not configure SMTP for you.

Important delivery note:

- `sendmail` can accept the message locally and still have the remote provider reject it later
- with `sendmail`, `server-backup` sets the envelope sender with `-f EMAIL_REPORT_FROM`
- Gmail and similar providers may still reject the message if SPF or DKIM does not align
- for reliable Gmail delivery, you still need valid SPF/DKIM or an authenticated SMTP relay outside this project
