# PRD Addendum — Contenu de site web / CIS / CMS

Ce document complète `PRD.md` et `PRD_DOCKER_ADDENDUM.md`.

Objectif : garantir que le contenu réel des sites web hébergés, notamment CIS, est bien sauvegardé et restaurable.

## 1. Principe

Le système de backup doit sauvegarder le contenu applicatif réel, pas seulement les fichiers de déploiement.

Pour un site web, le contenu peut être stocké à plusieurs endroits :

- fichiers statiques dans un bind mount ;
- fichiers statiques dans un volume Docker ;
- uploads utilisateurs ;
- médias ;
- thèmes/templates ;
- configuration applicative ;
- contenu éditorial stocké en base de données ;
- index ou assets générés ;
- cache reconstructible.

Le wizard doit aider à distinguer :

```text
contenu critique à sauvegarder
contenu reconstructible à exclure
contenu incertain à signaler
```

---

## 2. CIS doit être traité comme un service applicatif critique

Si un serveur contient un conteneur CIS, le wizard Docker doit détecter CIS comme application à sauvegarder.

Le backup doit inclure :

- le projet Docker Compose de CIS ;
- le fichier `.env` de CIS si présent ;
- les bind mounts utilisés par CIS ;
- les volumes Docker nommés utilisés par CIS ;
- les répertoires contenant pages, assets, médias ou uploads ;
- les fichiers de configuration CIS ;
- les dumps des bases utilisées par CIS ;
- l'inventaire Docker mentionnant image, version, ports, networks et mounts CIS.

Si CIS stocke ses pages dans PostgreSQL, le dump PostgreSQL couvre les pages.

Si CIS stocke ses pages comme fichiers, le ou les répertoires concernés doivent être inclus explicitement dans `BACKUP_PATHS`.

Si CIS stocke une partie en base et une partie en fichiers, les deux doivent être sauvegardés.

---

## 3. Questions wizard obligatoires pour chaque service web

Pour chaque service détecté, par exemple CIS, Caddy, CMS, application web custom, le wizard doit demander :

- ce service contient-il du contenu utilisateur ou éditorial critique ?
- les pages sont-elles stockées en fichiers, en base de données, ou les deux ?
- existe-t-il un répertoire `uploads`, `media`, `public`, `static`, `content`, `data`, `storage` ou équivalent ?
- existe-t-il une base PostgreSQL/MariaDB/MySQL associée ?
- faut-il inclure les volumes Docker nommés détectés ?
- faut-il inclure les bind mounts détectés ?
- quels chemins sont des caches reconstructibles à exclure ?

Le wizard doit afficher les mounts Docker détectés pour le conteneur concerné avant génération du profil.

---

## 4. Détection automatique de chemins de contenu

Lors de `server-backup docker scan` ou du wizard `profile add --type docker-host`, le système doit signaler comme candidats critiques les chemins contenant ces noms :

```text
content
contents
data
uploads
upload
media
medias
public
static
assets
storage
files
pages
www
html
site
sites
cms
```

Pour chaque chemin candidat, le wizard doit proposer :

```text
[include] sauvegarder
[exclude] ignorer
[cache] exclure comme cache reconstructible
[unknown] marquer comme à vérifier
```

Les chemins marqués `unknown` doivent apparaître dans le rapport email comme warning jusqu'à validation explicite.

---

## 5. Exemple de profil pour CIS

Exemple si CIS utilise un projet Compose sous `/srv/cis`, un volume Docker `cis_data` et une base PostgreSQL dans le conteneur `postgres` :

```bash
PROFILE_NAME="cis"
PROFILE_TYPE="docker-app"

BACKUP_PATHS=(
  "/srv/cis"
  "/var/lib/docker/volumes/cis_data/_data"
  "/var/lib/server-backup/state"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/logs/*.log"
  "**/node_modules"
)

DOCKER_INVENTORY="true"

DOCKER_POSTGRES_DUMPS=(
  "container=postgres;database=cis;user=cis_user;secret=/etc/server-backup/secrets/db/cis/postgres-cis.env;output=postgres-cis.dump"
)
```

Exemple si CIS a un bind mount explicite pour les pages :

```bash
BACKUP_PATHS=(
  "/srv/cis"
  "/srv/cis/content"
  "/srv/cis/uploads"
)
```

---

## 6. Restauration attendue pour un service web

La documentation `docs/DOCKER_RESTORE.md` doit inclure une section par service web critique.

Pour CIS, la restauration doit couvrir :

1. restauration du projet Compose ;
2. restauration des fichiers `.env` nécessaires ;
3. restauration des volumes ou bind mounts contenant pages/assets/uploads ;
4. restauration du dump PostgreSQL si utilisé ;
5. redémarrage de la stack ;
6. test HTTP via Caddy/reverse proxy ;
7. vérification visuelle ou endpoint santé ;
8. contrôle que les pages et médias attendus sont présents.

---

## 7. Rapport email

Le rapport email doit mentionner pour chaque service web critique :

- service détecté ;
- chemins de contenu inclus ;
- volumes inclus ;
- bases dumpées ;
- chemins candidats non classifiés ;
- warnings si aucun contenu persistant n'a été trouvé ;
- warnings si une application web a une base détectée sans dump configuré ;
- warnings si un volume Docker persistant est détecté mais non inclus.

---

## 8. Critères d'acceptation

- Le wizard permet de marquer un service comme `web-content-critical`.
- CIS peut être déclaré comme service critique.
- Les volumes et bind mounts de CIS sont inspectés.
- Le wizard demande où sont stockées les pages du site.
- Si les pages sont en DB, un dump DB est obligatoire.
- Si les pages sont en fichiers, les chemins sont ajoutés à `BACKUP_PATHS`.
- Si le stockage est inconnu, le système génère un warning exploitable.
- La restauration Docker documente explicitement comment vérifier que le contenu du site est revenu.

---

## 9. PR supplémentaire

Ajouter au plan de réalisation :

### PR20 — Web content critical services

- Ajouter classification `web-content-critical` dans le wizard.
- Ajouter détection des chemins candidats de contenu.
- Ajouter questions spécifiques pour CIS/CMS/applications web.
- Ajouter warnings pour volumes ou bases non sauvegardés.
- Ajouter section restauration de contenu web dans `docs/DOCKER_RESTORE.md`.
