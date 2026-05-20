# Database Dumps

`server-backup` can now attach logical database dumps to a profile with `DATABASE_DUMPS`.

## Commands

Add a dump definition interactively:

```bash
sudo server-backup db add
sudo server-backup db add --profile <profile>
```

List configured dumps:

```bash
sudo server-backup db list
```

Test connectivity:

```bash
sudo server-backup db test <name>
sudo server-backup db test --all
```

Run a temporary logical dump test:

```bash
sudo server-backup db dump-test <name>
sudo server-backup db dump-test --all
sudo server-backup db dump-test <name> --keep-output
```

## Supported Engines and Modes

Engines:

- `postgresql`
- `mysql`
- `mariadb`

Modes:

- `docker`
- `local`
- `remote`

## Profile Format

Example:

```text
DATABASE_DUMPS=(
  "name=app-postgres;engine=postgresql;mode=docker;container=postgres;user=app;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/app/app-postgres.env"
)
```

Supported keys:

- `name`
- `engine`
- `mode`
- `container`
- `host`
- `port`
- `user`
- `databases`
- `all`
- `globals`
- `secret`

## Secrets

Secrets stay outside the profile file:

- directory: `/etc/server-backup/secrets/db/<profile>/`
- file mode: `0600 root:root`
- directory mode: `0700 root:root`

Expected content:

- PostgreSQL: `PGPASSWORD="..."`
- MariaDB/MySQL: `MYSQL_PWD="..."`

Passwords are never passed on the command line. They are injected via environment variables or protected files.

## Backup Integration

During `server-backup backup run`:

- logical dumps run before `restic backup`
- dump files are written to a temporary directory under `LOCAL_DUMP_DIR`
- that temporary directory is included in the `restic backup`
- the temporary dump files are cleaned afterwards
- if a dump fails, the profile fails and restic is not launched for that profile

## Coverage Audit

`coverage audit` stays local-only and does not contact the database.

It now treats logical DB dumps as the primary coverage for DB content. A raw Docker DB volume may therefore remain optional when a matching logical dump exists.

## Scope Limits

This PR does not implement:

- DB restore
- DB container recreation
- DB disaster recovery
- deep Docker Compose DB discovery

