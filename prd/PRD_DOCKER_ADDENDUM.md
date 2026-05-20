# PRD Addendum — Sauvegarde des serveurs Docker

Ce document complète `PRD.md`. Il est normatif pour l'implémentation Codex dès qu'un serveur cible héberge des conteneurs Docker, Docker Compose ou une base PostgreSQL/MariaDB/MySQL exécutée dans un conteneur.

## 1. Objectif

Le système de backup doit permettre de reconstruire rapidement un serveur Docker après incident.

La restauration cible doit permettre :

1. réinstaller un serveur Linux vierge ;
2. réinstaller Docker et Docker Compose ;
3. restaurer les fichiers de configuration et projets Compose ;
4. restaurer les volumes persistants ou bind mounts ;
5. restaurer les bases de données depuis dumps cohérents ;
6. relancer les stacks avec `docker compose up -d` ;
7. vérifier les services exposés, reverse proxy inclus.

Le backup applicatif ne vise pas à cloner bit à bit l'OS complet. Les backups provider, par exemple image VPS OVH, couvrent ce besoin court terme. Le template restic doit sauvegarder ce qui est nécessaire pour reconstruire proprement les applications.

---

## 2. Politique : ce qui doit être backupé

### Toujours sauvegarder

- `/etc` ou au minimum les sous-dossiers critiques :
  - `/etc/systemd/system` ;
  - `/etc/ssh/sshd_config` et `/etc/ssh/sshd_config.d` ;
  - `/etc/cron.d`, `/etc/cron.daily`, `/etc/crontab` ;
  - `/etc/nginx` si présent ;
  - `/etc/caddy` si Caddy hors Docker ;
  - `/etc/letsencrypt` si certificats hors Docker ;
  - `/etc/fail2ban` si présent ;
  - `/etc/ufw` ou règles firewall documentées si présent.
- répertoires applicatifs : `/srv`, `/opt`, chemins custom ;
- fichiers Docker Compose :
  - `docker-compose.yml` ;
  - `compose.yml` ;
  - `docker-compose.override.yml` ;
  - `.env` associés ;
  - scripts d'init/deploy ;
  - configuration CI/CD locale si présente.
- volumes Docker persistants identifiés ;
- bind mounts Docker identifiés ;
- configurations reverse proxy : Caddy, Traefik, nginx ;
- données Caddy persistantes si Caddy en conteneur : volume ou bind mount contenant `/data` et `/config` ;
- dumps cohérents des bases PostgreSQL/MariaDB/MySQL ;
- inventaire système pour faciliter restauration.

### Ne pas sauvegarder par défaut

- `/var/lib/docker` en entier ;
- couches d'images Docker ;
- conteneurs arrêtés non documentés ;
- caches applicatifs ;
- logs volumineux ;
- `/tmp`, `/var/tmp` hors dumps temporaires ;
- `/proc`, `/sys`, `/dev`, `/run` ;
- images Docker téléchargeables depuis registry.

Justification : `/var/lib/docker` est gros, changeant, difficile à sauvegarder de manière cohérente pendant l'exécution et contient beaucoup d'éléments reconstructibles. Les données persistantes doivent être sauvegardées au niveau volumes/bind mounts et les bases via dumps.

---

## 3. Inventaire Docker obligatoire

Le système doit fournir une commande :

```bash
sudo server-backup docker inventory
```

Elle doit produire un fichier sous :

```text
/var/lib/server-backup/state/docker-inventory-YYYYMMDD-HHMMSS.txt
```

Le fichier doit contenir au minimum :

- hostname ;
- date ;
- version Docker ;
- version Docker Compose si disponible ;
- sortie `docker ps -a` ;
- liste des images `docker images` ;
- liste des volumes `docker volume ls` ;
- liste des networks `docker network ls` ;
- pour chaque conteneur :
  - nom ;
  - image ;
  - état ;
  - restart policy ;
  - ports exposés ;
  - mounts ;
  - networks ;
  - labels Compose ;
  - variables d'environnement non sensibles si possible.

Le backup doit inclure le dernier inventaire Docker généré.

Les secrets ne doivent pas être affichés dans l'inventaire. Les variables dont le nom contient `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, `PASS`, `PWD` doivent être masquées.

---

## 4. Découverte des projets Docker Compose

Le wizard doit proposer un profil `docker-host` ou `docker-compose`.

Il doit demander :

- chemins probables des projets Compose ;
- ex. `/srv`, `/opt`, `/home`, chemin custom ;
- s'il faut scanner automatiquement les fichiers :
  - `compose.yml` ;
  - `docker-compose.yml` ;
  - `docker-compose.yaml` ;
  - `docker-compose.override.yml`.

Commande attendue :

```bash
sudo server-backup docker scan
```

La commande doit lister les projets trouvés, par exemple :

```text
/srv/caddy/compose.yml
/srv/cis/compose.yml
/srv/postgres/compose.yml
/srv/app/compose.yml
```

Le wizard doit permettre de sélectionner les projets à inclure.

---

## 5. Volumes Docker et bind mounts

Le wizard doit identifier les mounts de chaque conteneur sélectionné avec `docker inspect`.

Pour chaque mount :

- type `bind` : proposer d'ajouter le chemin source à `BACKUP_PATHS` ;
- type `volume` : proposer d'ajouter le chemin réel du volume, typiquement `/var/lib/docker/volumes/<volume>/_data` ;
- type `tmpfs` : ignorer par défaut ;
- readonly : sauvegarder si utile pour reconstruction, mais ne pas le considérer comme données critiques.

Le profil généré doit inclure explicitement les chemins retenus.

Exemple :

```bash
BACKUP_PATHS=(
  "/srv"
  "/etc"
  "/var/lib/docker/volumes/caddy_data/_data"
  "/var/lib/docker/volumes/caddy_config/_data"
  "/var/lib/docker/volumes/cis_data/_data"
)
```

Exclusions recommandées :

```bash
EXCLUDES=(
  "**/cache"
  "**/.cache"
  "**/tmp"
  "**/logs/*.log"
  "/var/lib/docker/overlay2"
  "/var/lib/docker/image"
  "/var/lib/docker/containers/*/*.log"
)
```

---

## 6. Bases de données dans Docker

Si PostgreSQL est dans un conteneur, le backup doit privilégier `pg_dump` ou `pg_dumpall` via Docker plutôt qu'une copie brute du volume.

### Configuration profile attendue

Ajouter un bloc optionnel dans les profiles :

```bash
DOCKER_POSTGRES_DUMPS=(
  "container=postgres;database=appdb;user=appuser;output=appdb.dump"
)
```

Option alternative pour dump global :

```bash
DOCKER_POSTGRES_DUMPALL=(
  "container=postgres;user=postgres;output=postgres-all.sql"
)
```

Le wizard doit demander :

- nom du conteneur PostgreSQL ;
- nom de la base ;
- utilisateur ;
- méthode d'authentification ;
- dump base unique ou dumpall ;
- commande de test.

### Commande attendue

Exemple base unique :

```bash
docker exec -e PGPASSWORD="$PGPASSWORD" "$container" \
  pg_dump --username="$user" --format=custom --compress=0 "$database" \
  > "$dump_file"
```

Exemple dumpall :

```bash
docker exec -e PGPASSWORD="$PGPASSWORD" "$container" \
  pg_dumpall --username="$user" \
  > "$dump_file"
```

Les mots de passe ne doivent jamais être stockés dans le repo. Ils peuvent être stockés côté serveur dans un fichier root-only sous :

```text
/etc/server-backup/secrets/db/<profile>/<name>.env
```

Permissions :

```text
0600 root:root
```

Exemple :

```bash
PGPASSWORD="secret"
```

Le rapport email ne doit jamais inclure ces valeurs.

---

## 7. Cohérence de restauration

Pour les bases de données :

- le dump logique est obligatoire ;
- le volume DB peut être sauvegardé en plus, mais ne remplace pas le dump ;
- la restauration documentée doit utiliser le dump logique.

Pour les applications stateless :

- sauvegarder Compose + `.env` + bind mounts persistants suffit.

Pour Caddy en conteneur :

- sauvegarder `Caddyfile` ou config dynamique ;
- sauvegarder volume `/data` pour certificats et state ;
- sauvegarder volume `/config` si utilisé ;
- documenter qu'il peut aussi régénérer des certificats Let's Encrypt si DNS/ports OK.

---

## 8. Fichiers de profil Docker — exemple

Exemple `/etc/server-backup/profiles.d/docker-host.conf` :

```bash
PROFILE_NAME="docker-host"
PROFILE_TYPE="docker-host"

BACKUP_PATHS=(
  "/etc"
  "/srv"
  "/opt"
  "/var/lib/server-backup/state"
  "/var/lib/docker/volumes/caddy_data/_data"
  "/var/lib/docker/volumes/caddy_config/_data"
  "/var/lib/docker/volumes/cis_data/_data"
)

EXCLUDES=(
  "/etc/server-backup/secrets"
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/__pycache__"
  "**/node_modules"
  "/var/lib/docker/overlay2"
  "/var/lib/docker/image"
  "/var/lib/docker/containers/*/*.log"
)

DOCKER_INVENTORY="true"

DOCKER_POSTGRES_DUMPS=(
  "container=postgres;database=appdb;user=appuser;secret=/etc/server-backup/secrets/db/docker-host/postgres-appdb.env;output=postgres-appdb.dump"
)
```

Note : exclure `/etc/server-backup/secrets` du backup par défaut évite qu'un dépôt restic compromis donne accès aux secrets de connexion. Si l'opérateur veut sauvegarder les secrets, il doit le faire volontairement et comprendre l'impact. Le mot de passe restic lui-même ne doit jamais être stocké dans le dépôt qu'il protège.

---

## 9. Wizard Docker attendu

Ajouter les commandes :

```bash
sudo server-backup docker scan
sudo server-backup docker inventory
sudo server-backup profile add --type docker-host
```

Questions wizard :

- scanner `/srv` ?
- scanner `/opt` ?
- scanner `/home` ?
- ajouter un chemin custom ?
- inclure `/etc` complet ou seulement sous-dossiers critiques ?
- inclure les projets Compose détectés ?
- analyser les mounts des conteneurs actifs ?
- inclure les bind mounts détectés ?
- inclure les volumes nommés détectés ?
- conteneur PostgreSQL à dumper ?
- base PostgreSQL à dumper ?
- utilisateur PostgreSQL ?
- chemin du fichier secret `PGPASSWORD` ?
- générer un fichier secret root-only ?
- tester le dump maintenant ?

---

## 10. Rapport email Docker

Le rapport email doit inclure si applicable :

- nombre de conteneurs actifs ;
- nombre de conteneurs arrêtés ;
- nombre de projets Compose détectés ;
- volumes inclus ;
- dumps DB générés ;
- échecs de dump ;
- chemin de l'inventaire Docker ;
- avertissement si un conteneur a un volume persistant non inclus.

---

## 11. Critères d'acceptation spécifiques Docker

- Le wizard peut générer un profil `docker-host`.
- Le système peut scanner les Compose files.
- Le système peut inventorier les conteneurs Docker sans exposer les secrets.
- Les bind mounts détectés peuvent être ajoutés au backup.
- Les volumes nommés détectés peuvent être ajoutés explicitement au backup.
- Une base PostgreSQL en conteneur peut être dumpée avec `docker exec`.
- Le backup inclut les fichiers Compose, `.env`, volumes persistants sélectionnés, dumps DB et inventaire Docker.
- La documentation de restauration Docker explique comment repartir d'un serveur vierge.

---

## 12. Plan PR supplémentaire

Ajouter ces PR au plan de réalisation :

### PR16 — Docker discovery et inventory

- Implémenter `server-backup docker scan`.
- Implémenter `server-backup docker inventory`.
- Masquer les secrets dans l'inventaire.
- Sauvegarder l'inventaire sous `/var/lib/server-backup/state`.

### PR17 — Profil docker-host

- Ajouter wizard `profile add --type docker-host`.
- Détecter bind mounts et volumes nommés.
- Générer `profiles.d/docker-host.conf`.
- Ajouter exemple `examples/profiles/docker-host.conf.example`.

### PR18 — Dumps PostgreSQL Docker

- Ajouter support `DOCKER_POSTGRES_DUMPS`.
- Ajouter secrets root-only sous `/etc/server-backup/secrets/db/...`.
- Tester `docker exec pg_dump`.
- Intégrer résultat dans rapport email.

### PR19 — Documentation restauration Docker

- Créer `docs/DOCKER_RESTORE.md`.
- Décrire restauration serveur vierge + Docker + Compose + volumes + DB.
- Inclure checklist de validation post-restore.
