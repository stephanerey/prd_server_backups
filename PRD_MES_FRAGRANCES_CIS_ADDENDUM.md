# PRD Addendum — Couverture spécifique mes-fragrances.com / CIS

Ce document complète `PRD_SITE_CONTENT_ADDENDUM.md` avec les informations connues sur le stockage des pages du site `mes-fragrances.com` réalisé avec CIS.

## 1. Conclusion fonctionnelle

Pour `mes-fragrances.com`, le stockage du site est hybride :

- les pages éditables du builder/CMS sont stockées en base PostgreSQL ;
- les blocs de contenu des pages builder sont stockés en JSONB ;
- le frontend Next.js rend dynamiquement ces pages via l'API backend ;
- les composants React qui affichent les blocs sont des fichiers du repository ;
- certaines pages publiques ou marketing restent codées en dur dans les fichiers Next.js.

Conséquence backup :

```text
Il faut sauvegarder à la fois :
- la base PostgreSQL CIS ;
- le code backend CIS ;
- le code frontend Next.js ;
- les fichiers de configuration et .env ;
- les volumes/bind mounts applicatifs ;
- les éventuels médias/uploads/assets persistants.
```

Un dump PostgreSQL seul ne suffit pas à reconstruire le site complet.

Une sauvegarde des fichiers seule ne suffit pas non plus, car les pages builder sont en base.

---

## 2. Données PostgreSQL critiques

Les pages builder sont stockées en PostgreSQL dans la table :

```text
site_pages
```

Le modèle backend stocke notamment :

```text
slug
title
blocks
status
navigation
```

Le champ `blocks` est en JSONB et contient le contenu structuré des pages éditables.

Le backend lit et écrit ces pages via l'API :

```text
/api/v1/site/pages
```

Le backup doit donc obligatoirement inclure un dump logique PostgreSQL de la base CIS.

Configuration recommandée :

```bash
DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=postgres;user=cis_user;databases=cis;globals=true;secret=/etc/server-backup/secrets/db/cis/postgres.env"
)
```

Adapter `container`, `user` et `databases` aux noms réels du serveur.

Le dump doit inclure :

```text
structure SQL
données
table site_pages
JSONB blocks
index
contraintes
séquences
fonctions/triggers éventuels
extensions utilisées
```

Pour PostgreSQL, il faut aussi activer :

```text
pg_dumpall --globals-only
```

afin de sauvegarder les rôles et objets globaux nécessaires à une restauration propre.

---

## 3. Fichiers applicatifs critiques

Le rendu des pages dépend du code applicatif. Le backup doit inclure le repository ou le répertoire déployé CIS, notamment :

```text
mes-fragrances_CIS/backend
mes-fragrances_CIS/frontend
mes-fragrances_CIS/backend/alembic
mes-fragrances_CIS/frontend/components/site
mes-fragrances_CIS/frontend/app
compose.yml ou docker-compose.yml
.env applicatifs
scripts de déploiement
```

Les composants visuels qui affichent les blocs sont dans le frontend, notamment le renderer et le catalogue de blocs.

Les pages Next.js codées en dur, comme certaines pages marketing, sont également des fichiers du frontend. Elles ne sont pas récupérables depuis PostgreSQL.

---

## 4. Médias, uploads et assets

Même si les pages builder sont en base, le site peut référencer des médias ou fichiers persistants.

Le wizard doit rechercher explicitement les chemins suivants dans les bind mounts, volumes Docker et répertoires applicatifs CIS :

```text
uploads
media
medias
assets
public
static
storage
files
images
content
data
```

Tout chemin contenant des médias ou uploads utilisés par les pages doit être inclus dans `BACKUP_PATHS`.

Si aucun chemin média/upload n'est trouvé, le système doit émettre un warning non bloquant :

```text
WARNING: CIS pages are stored in PostgreSQL, but no media/uploads path was classified. Confirm whether the site uses external media URLs only or local persistent media.
```

---

## 5. Exemple de profil CIS mes-fragrances.com

Exemple indicatif à adapter au serveur réel :

```bash
PROFILE_NAME="mes-fragrances-cis"
PROFILE_TYPE="docker-app"
WEB_CONTENT_CRITICAL="true"

BACKUP_PATHS=(
  "/srv/mes-fragrances_CIS"
  "/var/lib/server-backup/state"
  "/var/lib/docker/volumes/cis_data/_data"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/__pycache__"
  "**/node_modules"
  "**/.next/cache"
  "**/logs/*.log"
)

DOCKER_INVENTORY="true"

DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=postgres;user=cis_user;databases=cis;globals=true;secret=/etc/server-backup/secrets/db/mes-fragrances-cis/postgres.env"
)

CONTENT_CLASSIFICATION=(
  "db:postgresql:cis:site_pages:builder-pages"
  "files:/srv/mes-fragrances_CIS/frontend:nextjs-pages-and-components"
  "files:/srv/mes-fragrances_CIS/backend:api-and-models"
)
```

---

## 6. Coverage audit spécifique CIS

`server-backup coverage audit` doit vérifier pour un service marqué `WEB_CONTENT_CRITICAL=true` :

- un dump PostgreSQL est configuré ;
- la base configurée contient ou doit contenir la table `site_pages` ;
- le répertoire frontend est inclus ;
- le répertoire backend est inclus ;
- les migrations Alembic sont incluses ;
- les fichiers Compose et `.env` sont inclus ;
- les volumes/bind mounts du conteneur CIS sont inclus ou explicitement ignorés ;
- les chemins médias/uploads/assets sont classifiés.

Warnings attendus :

```text
WARNING: CIS service is web-content-critical but no PostgreSQL dump is configured.
WARNING: CIS builder pages are DB-backed but PostgreSQL globals dump is disabled.
WARNING: CIS frontend renderer files are not covered by BACKUP_PATHS.
WARNING: CIS media/uploads path not classified.
WARNING: CIS .env detected but not included.
```

---

## 7. Restauration spécifique mes-fragrances.com

La documentation `docs/DOCKER_RESTORE.md` doit inclure un scénario CIS :

1. restaurer le projet CIS ;
2. restaurer les fichiers `.env` ;
3. restaurer les volumes/bind mounts persistants ;
4. restaurer la base PostgreSQL ;
5. restaurer les globals PostgreSQL si nécessaire ;
6. relancer la stack Docker ;
7. vérifier l'API `/api/v1/site/pages` ;
8. vérifier le rendu frontend `/site/[slug]` ;
9. vérifier les pages Next.js codées en dur ;
10. vérifier médias/uploads/assets ;
11. vérifier que les pages builder sont présentes dans l'interface d'administration.

---

## 8. Critères d'acceptation spécifiques

- Le wizard permet de déclarer `mes-fragrances-cis` comme service web critique.
- Le wizard demande si les pages builder sont stockées en DB, fichiers ou hybride.
- Le profil généré inclut le dump PostgreSQL CIS.
- Le profil généré inclut le frontend et le backend CIS.
- Le profil généré inclut Compose et `.env`.
- Le coverage audit alerte si `site_pages` n'est pas couverte par un dump.
- Le coverage audit alerte si le renderer frontend n'est pas couvert.
- La procédure de restauration vérifie à la fois les pages DB-backed et les pages codées en dur.
