# Docker Coverage

`server-backup` can inspect Docker locally to help the operator improve backup coverage without modifying containers or Compose projects.

## Commands

Scan the local Docker state:

```bash
sudo server-backup docker scan
```

Write a local inventory report:

```bash
sudo server-backup docker inventory
```

Compare Docker mounts with profile `BACKUP_PATHS`:

```bash
sudo server-backup docker coverage
```

Show suggested profile updates:

```bash
sudo server-backup docker suggest-profile-updates
```

Interactively add missing Docker paths to one profile:

```bash
sudo server-backup docker add-missing-paths --profile <profile>
sudo server-backup docker add-missing-paths --profile <profile> --dry-run
sudo server-backup docker add-missing-paths --profile <profile> --volume <volume-name>
sudo server-backup docker add-missing-paths --profile <profile> --all-volumes
```

## Safety

These commands:

- do not modify Docker
- do not launch `docker compose`
- do not read `.env` contents
- do not print secrets
- only modify a profile after explicit confirmation

When a profile is modified:

- a timestamped backup of the profile is created first
- the updated file is written back in `0600 root:root`

## DB Volumes

Database volumes are handled differently from ordinary application storage.

Preferred order:

1. configure `DATABASE_DUMPS`
2. confirm that `db test` and `db dump-test` succeed
3. optionally add the raw DB volume only if you still want block-level filesystem coverage

If a matching logical dump exists, coverage tooling treats it as the primary protection for DB content.

## Reverse Proxy Volumes

Reverse proxy volumes for tools such as Caddy, nginx and Traefik often contain certificates, ACME state, config or data directories.

Those paths are usually worth covering explicitly in a profile.

## Compose and `.env`

`docker scan`, `docker inventory` and `docker coverage` look for Compose files under:

- `/srv`
- `/opt`
- `/home`
- existing profile `BACKUP_PATHS`

They also detect adjacent `.env` files, but they only record the path, never the content.

## Limits

This PR does not implement:

- automatic correction without confirmation
- Docker restore
- `docker compose up`
- volume migration
- volume deletion
- container modification

