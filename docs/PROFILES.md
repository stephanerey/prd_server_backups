# Profiles

Profiles define what will be backed up on the source host. They stay as plain-text files under `/etc/server-backup/profiles.d/`.

Create one interactively with:

```bash
sudo server-backup profile add
```

## Choosing a Profile Type

- `generic`: use for non-containerized apps or any manual path selection
- `system-filesystem`: use for broad host coverage of important filesystem trees
- `docker-host`: use for a host that runs multiple Docker workloads
- `docker-app`: use for one Compose-style application and its persistent mounts
- `cis-site`: use for CIS websites where content lives partly in files and partly in the database

## Recommendations

- Prefer `generic` when you already know the exact application paths.
- Prefer `system-filesystem` for host-level disaster recovery coverage, but do not treat it as a replacement for logical DB dumps.
- Prefer `docker-host` when the machine runs many containers and you want host-level config and storage paths.
- Prefer `docker-app` when you want one profile per Compose project.
- Prefer `cis-site` when the app has frontend/backend/content structure and builder pages that are expected to live in PostgreSQL.

## Docker Notes

The project now includes local Docker coverage helpers:

```bash
sudo server-backup docker scan
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
sudo server-backup docker add-missing-paths --profile <profile>
```

Useful distinctions:

- bind mounts use host paths directly, for example `/srv/my-app/data`
- named volumes usually map to `/var/lib/docker/volumes/<name>/_data`
- reverse proxy data for Caddy, nginx or Traefik is often persistent and should usually be covered
- database volumes are special: prefer a logical `DATABASE_DUMPS` entry first

The helper command `docker add-missing-paths`:

- never modifies Docker
- never launches `docker compose`
- proposes missing paths interactively
- creates a timestamped backup of the profile before writing
- preserves `EXCLUDES`, `DATABASE_DUMPS` and `CONTENT_CLASSIFICATION`

For a DB volume, the tool warns explicitly that a logical dump is preferred and that raw volume backup remains optional.

## CIS Notes

The `cis-site` profile adds:

- `APP_KIND="cis-site"`
- `WEB_CONTENT_CRITICAL="true"` by default
- `DOCKER_INVENTORY="true"` by default
- `CONTENT_CLASSIFICATION` placeholders for frontend, backend and builder-page DB content

Database dump configuration is now available separately with:

```bash
sudo server-backup db add
```
