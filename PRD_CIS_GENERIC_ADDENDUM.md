# PRD Addendum — Couverture générique des sites web réalisés avec CIS

Ce document complète `PRD_SITE_CONTENT_ADDENDUM.md`.

Objectif : définir une stratégie générique pour sauvegarder correctement tout site web réalisé avec CIS, sans dépendre d'un site ou d'un nom de projet particulier.

## 1. Principe générique CIS

Un site web réalisé avec CIS doit être considéré comme un service web critique pouvant avoir un stockage hybride :

- contenu éditable du builder/CMS stocké en base PostgreSQL ;
- blocs de contenu structurés stockés en JSON/JSONB ;
- rendu dynamique via API backend ;
- composants de rendu stockés dans le code frontend ;
- routes publiques ou marketing potentiellement codées en dur dans le frontend ;
- médias, uploads ou assets éventuellement stockés en fichiers, volumes Docker ou stockage externe.

Conséquence backup :

```text
Un site CIS doit être sauvegardé comme un ensemble cohérent :
- base PostgreSQL CIS ;
- backend CIS ;
- frontend CIS ;
- migrations DB ;
- fichiers Compose ;
- fichiers .env ;
- volumes/bind mounts persistants ;
- médias/uploads/assets si locaux ;
- inventaire Docker.
```

Un dump PostgreSQL seul ne suffit pas à reconstruire le site complet.

Une sauvegarde des fichiers seule ne suffit pas non plus si les pages builder sont stockées en base.

---

## 2. Données PostgreSQL critiques CIS

Pour les sites CIS, le wizard doit supposer par défaut que les pages éditables du builder/CMS sont stockées en PostgreSQL, sauf indication contraire de l'opérateur.

Le système doit permettre de déclarer une ou plusieurs tables critiques de contenu, par exemple :

```text
site_pages
pages
cms_pages
builder_pages
```

Pour un schéma CIS standard, la table attendue est :

```text
site_pages
```

Les données critiques typiques sont :

```text
slug
title
blocks
status
navigation
SEO metadata
publication state
page ordering
```

Le champ `blocks` ou équivalent peut être en JSON/JSONB et contenir le contenu structuré des pages éditables.

Le backup doit donc obligatoirement inclure un dump logique PostgreSQL de la base CIS.

Configuration recommandée :

```bash
DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=<postgres_container>;user=<db_user>;databases=<cis_database>;globals=true;secret=/etc/server-backup/secrets/db/<profile>/postgres.env"
)
```

Le dump doit inclure :

```text
structure SQL
données
tables de contenu CIS
données JSON/JSONB des blocs
index
contraintes
séquences
fonctions/triggers éventuels
extensions utilisées
```

Pour PostgreSQL, il faut aussi proposer et recommander :

```text
pg_dumpall --globals-only
```

afin de sauvegarder les rôles et objets globaux nécessaires à une restauration propre.

---

## 3. Code applicatif critique CIS

Le rendu des pages dépend du code applicatif. Le backup doit inclure le repository ou le répertoire déployé CIS.

Chemins candidats à inclure selon l'organisation du projet :

```text
<cis_project>/backend
<cis_project>/frontend
<cis_project>/backend/alembic
<cis_project>/backend/migrations
<cis_project>/frontend/components
<cis_project>/frontend/app
<cis_project>/frontend/pages
<cis_project>/frontend/src
<cis_project>/compose.yml
<cis_project>/docker-compose.yml
<cis_project>/.env
<cis_project>/scripts
```

Le wizard ne doit pas imposer ces noms, mais les détecter comme candidats si présents.

Règle : si un site CIS est marqué `WEB_CONTENT_CRITICAL=true`, le frontend et le backend doivent être inclus ou explicitement exclus avec justification.

Les composants visuels qui affichent les blocs builder sont des fichiers applicatifs. Les pages publiques ou marketing codées en dur dans le frontend sont également des fichiers applicatifs. Elles ne sont pas récupérables depuis PostgreSQL.

---

## 4. Médias, uploads et assets

Même si les pages builder sont en base, un site CIS peut référencer des médias ou fichiers persistants.

Le wizard doit rechercher explicitement les chemins suivants dans les bind mounts, volumes Docker et répertoires applicatifs CIS :

```text
uploads
upload
media
medias
assets
public
static
storage
files
images
img
content
data
documents
attachments
```

Tout chemin contenant des médias ou uploads utilisés par les pages doit être inclus dans `BACKUP_PATHS`, sauf si l'opérateur confirme que les médias sont externes, par exemple stockage objet ou URLs externes.

Si aucun chemin média/upload n'est trouvé, le système doit émettre un warning non bloquant :

```text
WARNING: CIS service is marked web-content-critical and builder pages are DB-backed, but no media/uploads path was classified. Confirm whether the site uses external media URLs only or local persistent media.
```

---

## 5. Questions wizard spécifiques CIS

Lorsqu'un service est déclaré comme `cis-site` ou `web-content-critical`, le wizard doit demander :

```text
Nom logique du site CIS ?
Chemin du projet CIS ?
Le site est-il déployé via Docker Compose ?
Chemin du compose.yml/docker-compose.yml ?
Chemin du fichier .env ?
Nom du conteneur backend ?
Nom du conteneur frontend ?
Nom du conteneur PostgreSQL ?
Nom de la base PostgreSQL ?
Utilisateur PostgreSQL ?
Secret PGPASSWORD à créer ou fichier existant ?
Les pages builder sont-elles stockées en DB ?
Table de pages attendue, ex. site_pages ?
Y a-t-il des pages codées en dur dans le frontend ?
Y a-t-il des médias/uploads locaux ?
Y a-t-il un stockage média externe ?
Inclure les volumes détectés ?
Inclure les bind mounts détectés ?
Tester la connexion DB maintenant ?
Tester un dump DB maintenant ?
```

Le wizard doit pouvoir répondre automatiquement à une partie de ces questions via scan Docker et scan fichiers, mais doit laisser l'opérateur valider.

---

## 6. Exemple de profil CIS générique

Exemple indicatif à adapter au serveur réel :

```bash
PROFILE_NAME="cis-site"
PROFILE_TYPE="docker-app"
APP_KIND="cis-site"
WEB_CONTENT_CRITICAL="true"

BACKUP_PATHS=(
  "/srv/<cis_project>"
  "/var/lib/server-backup/state"
  "/var/lib/docker/volumes/<cis_data_volume>/_data"
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
  "name=cis-postgres;engine=postgresql;mode=docker;container=<postgres_container>;user=<db_user>;databases=<cis_database>;globals=true;secret=/etc/server-backup/secrets/db/cis-site/postgres.env"
)

CONTENT_CLASSIFICATION=(
  "db:postgresql:<cis_database>:site_pages:builder-pages"
  "files:/srv/<cis_project>/frontend:frontend-renderer-and-routes"
  "files:/srv/<cis_project>/backend:api-models-and-migrations"
)
```

---

## 7. Coverage audit spécifique CIS

`server-backup coverage audit` doit vérifier pour tout service avec `APP_KIND="cis-site"` ou `WEB_CONTENT_CRITICAL="true"` :

- un dump PostgreSQL est configuré ;
- la configuration DB indique la base CIS ;
- la table de pages attendue est déclarée ou détectée ;
- le répertoire frontend est inclus ;
- le répertoire backend est inclus ;
- les migrations DB sont incluses ;
- les fichiers Compose sont inclus ;
- les fichiers `.env` sont inclus ou explicitement exclus ;
- les volumes/bind mounts du service CIS sont inclus ou explicitement ignorés ;
- les chemins médias/uploads/assets sont classifiés ;
- le dump PostgreSQL globals est activé ou explicitement désactivé.

Warnings attendus :

```text
WARNING: CIS service is web-content-critical but no PostgreSQL dump is configured.
WARNING: CIS builder pages are DB-backed but PostgreSQL globals dump is disabled.
WARNING: CIS frontend files are not covered by BACKUP_PATHS.
WARNING: CIS backend files are not covered by BACKUP_PATHS.
WARNING: CIS migrations are not covered by BACKUP_PATHS.
WARNING: CIS media/uploads path not classified.
WARNING: CIS .env detected but not included.
WARNING: CIS Docker volume detected but not included or explicitly ignored.
```

---

## 8. Restauration générique d'un site CIS

La documentation `docs/DOCKER_RESTORE.md` doit inclure un scénario générique CIS :

1. restaurer le projet CIS ;
2. restaurer les fichiers `.env` nécessaires ;
3. restaurer les volumes/bind mounts persistants ;
4. restaurer les médias/uploads/assets locaux si présents ;
5. restaurer les globals PostgreSQL si nécessaire ;
6. restaurer la base PostgreSQL CIS ;
7. relancer la stack Docker ;
8. vérifier l'API backend de pages ;
9. vérifier le rendu frontend des pages builder ;
10. vérifier les pages codées en dur ;
11. vérifier médias/uploads/assets ;
12. vérifier que les pages builder sont présentes dans l'interface d'administration.

Aucune restauration destructive ne doit être lancée sans confirmation explicite.

---

## 9. Critères d'acceptation spécifiques CIS

- Le wizard permet de déclarer un service comme `cis-site`.
- Le wizard demande si les pages builder sont stockées en DB, fichiers ou hybride.
- Le wizard propose PostgreSQL comme stockage par défaut pour les pages builder CIS.
- Le profil généré inclut le dump PostgreSQL CIS.
- Le profil généré inclut backend, frontend, migrations, Compose et `.env`.
- Le profil généré classe les médias/uploads/assets comme inclus, exclus ou externes.
- Le coverage audit alerte si les tables de pages CIS ne sont pas couvertes par un dump.
- Le coverage audit alerte si le frontend ou le backend CIS ne sont pas couverts.
- La procédure de restauration vérifie à la fois les pages DB-backed, les pages codées en dur et les médias.

---

## 10. PR supplémentaire

### PR26 — Generic CIS site backup profile

- Ajouter le type d'application `cis-site` dans le wizard.
- Ajouter les questions spécifiques CIS.
- Ajouter la détection de tables de pages configurables, avec `site_pages` comme défaut.
- Ajouter la classification frontend/backend/migrations/media.
- Ajouter les règles `coverage audit` spécifiques CIS.
- Ajouter une section générique de restauration CIS dans `docs/DOCKER_RESTORE.md`.
