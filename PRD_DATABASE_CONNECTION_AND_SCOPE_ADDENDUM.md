# PRD Addendum — Connexion DB et périmètre des dumps

Ce document complète `PRD.md` et les addendums Docker.

Objectif : rendre explicite ce que le wizard doit demander pour les bases de données et ce que le backup DB couvre réellement.

## 1. Principe

Le système de backup doit sauvegarder les bases de données de manière logique avec les outils natifs :

- PostgreSQL : `pg_dump`, `pg_dumpall` ;
- PostgreSQL dans Docker : `docker exec ... pg_dump` ou `docker exec ... pg_dumpall` ;
- MariaDB/MySQL : `mariadb-dump` ou `mysqldump`.

Un dump logique est obligatoire pour toute base critique.

La sauvegarde brute du volume Docker de la base peut être faite en complément, mais ne remplace pas le dump logique.

---

## 2. Ce qui est sauvegardé pour PostgreSQL

### Dump d'une base avec `pg_dump`

Un dump `pg_dump` d'une base sélectionnée doit inclure :

- schémas ;
- tables ;
- données ;
- index ;
- contraintes ;
- séquences ;
- vues ;
- vues matérialisées si présentes ;
- fonctions ;
- triggers ;
- types ;
- extensions référencées ;
- privilèges et ownership dans la limite de ce que `pg_dump` exporte pour la base.

Il ne couvre pas automatiquement les objets globaux du cluster PostgreSQL :

- rôles/users ;
- mots de passe des rôles ;
- tablespaces ;
- paramètres globaux du serveur ;
- autres bases non sélectionnées.

### Dump des objets globaux PostgreSQL

Le wizard doit proposer l'option :

```bash
POSTGRES_DUMP_GLOBALS="true"
```

Commande attendue :

```bash
pg_dumpall --globals-only > "$dump_file"
```

Pour PostgreSQL dans Docker :

```bash
docker exec -e PGPASSWORD="$PGPASSWORD" "$container" \
  pg_dumpall --globals-only --username="$user" \
  > "$dump_file"
```

### Dump de toutes les bases

Le wizard doit proposer trois modes :

```text
single-database : sauvegarder une ou plusieurs bases explicitement listées
all-databases   : sauvegarder toutes les bases utilisateur détectées
globals-only    : sauvegarder uniquement rôles/tablespaces/objets globaux
```

Le mode recommandé pour une application est :

```text
pg_dump par base applicative critique
+ pg_dumpall --globals-only
```

---

## 3. Ce qui est sauvegardé pour MariaDB/MySQL

Un dump `mariadb-dump` ou `mysqldump` d'une base sélectionnée doit inclure :

- structure des tables ;
- données ;
- vues ;
- triggers ;
- routines/procédures/fonctions ;
- events si option activée ;
- contraintes selon moteur et version.

Commande attendue :

```bash
mariadb-dump --single-transaction --routines --triggers --events "$database" > "$dump_file"
```

Le wizard doit proposer :

```text
single-database
all-databases
```

Pour `all-databases` :

```bash
mariadb-dump --all-databases --single-transaction --routines --triggers --events > "$dump_file"
```

---

## 4. Informations que le wizard doit demander pour chaque DB

### Questions communes

Pour chaque base critique, le wizard doit demander :

- moteur : PostgreSQL, MariaDB/MySQL ;
- mode d'exécution : local host, conteneur Docker, remote host ;
- nom logique de la base dans le backup ;
- base unique ou toutes les bases ;
- inclure objets globaux si PostgreSQL ;
- tester la connexion maintenant ;
- tester un dump maintenant ;
- fichier secret à créer ou fichier secret existant.

### PostgreSQL local ou remote

Champs à collecter :

```text
DB_ENGINE="postgresql"
DB_MODE="local" ou "remote"
DB_HOST="localhost"
DB_PORT="5432"
DB_USER="app_user"
DB_DATABASES=("appdb")
DB_DUMP_GLOBALS="true"
DB_SECRET_FILE="/etc/server-backup/secrets/db/<profile>/<name>.env"
```

Le fichier secret peut contenir :

```bash
PGPASSWORD="secret"
```

Le script doit utiliser `PGPASSWORD` en environnement ou recommander `.pgpass` root-only.

### PostgreSQL dans Docker

Champs à collecter :

```text
DB_ENGINE="postgresql"
DB_MODE="docker"
DB_CONTAINER="postgres"
DB_USER="app_user"
DB_DATABASES=("appdb")
DB_DUMP_GLOBALS="true"
DB_SECRET_FILE="/etc/server-backup/secrets/db/<profile>/<name>.env"
```

Le fichier secret peut contenir :

```bash
PGPASSWORD="secret"
```

### MariaDB/MySQL local ou Docker

Champs à collecter :

```text
DB_ENGINE="mysql"
DB_MODE="local" ou "docker" ou "remote"
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="app_user"
DB_DATABASES=("appdb")
DB_ALL_DATABASES="false"
DB_SECRET_FILE="/etc/server-backup/secrets/db/<profile>/<name>.env"
```

Le fichier secret peut contenir :

```bash
MYSQL_PWD="secret"
```

ou pointer vers un fichier client root-only.

---

## 5. Format de configuration attendu

Le format historique `POSTGRES_DATABASES` reste supporté pour les cas simples.

Pour les cas robustes, ajouter une configuration DB explicite :

```bash
DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=postgres;user=cis_user;databases=cis;globals=true;secret=/etc/server-backup/secrets/db/cis/postgres.env"
)
```

Exemples :

```bash
DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=postgres;user=cis_user;databases=cis;globals=true;secret=/etc/server-backup/secrets/db/cis/postgres.env"
  "name=app-mysql;engine=mysql;mode=local;host=localhost;port=3306;user=app_user;databases=appdb;all=false;secret=/etc/server-backup/secrets/db/app/mysql.env"
)
```

Le système doit masquer les valeurs de `secret` et ne jamais afficher le contenu des fichiers secrets.

---

## 6. Tests obligatoires proposés par le wizard

Après configuration d'une DB, le wizard doit proposer :

```bash
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

`db test` valide la connexion.

`db dump-test` crée un dump temporaire, vérifie que le fichier est non vide, puis le supprime sauf demande contraire.

---

## 7. Ce que le backup DB ne fait pas

Le backup DB ne doit pas être présenté comme une sauvegarde de l'instance complète si seul `pg_dump` d'une base est configuré.

Cas non couverts sans option explicite :

- autres bases du même serveur ;
- rôles PostgreSQL sans `pg_dumpall --globals-only` ;
- fichiers de configuration PostgreSQL du conteneur si non montés et non inclus ;
- WAL/archive logs ;
- réplication ;
- état exact transactionnel de tout un cluster multi-bases à un instant commun ;
- secrets applicatifs hors fichiers explicitement sauvegardés.

---

## 8. Réponse attendue à la question "sauve-t-on tout dans la DB ?"

Par défaut, pour une application critique :

```text
Oui, on sauvegarde tout le contenu logique de chaque base déclarée : structure + données + objets DB internes.
```

Mais :

```text
Non, on ne sauvegarde pas automatiquement toutes les bases du serveur ni les objets globaux PostgreSQL sauf si les options correspondantes sont activées.
```

Configuration recommandée :

```text
- pg_dump de chaque base applicative critique
- pg_dumpall --globals-only pour les rôles et objets globaux PostgreSQL
- inventaire Docker pour savoir quel conteneur et quelle image utilisaient la DB
- sauvegarde des volumes/configs en complément, mais restauration officielle depuis dump logique
```

---

## 9. Rapport email

Le rapport email doit indiquer :

- liste des dumps DB configurés ;
- base unique ou all-databases ;
- globals PostgreSQL inclus ou non ;
- taille de chaque dump ;
- durée de chaque dump ;
- résultat connexion ;
- résultat dump ;
- warning si application critique sans dump DB ;
- warning si PostgreSQL sans dump globals.

Aucun mot de passe, token ou secret ne doit apparaître.

---

## 10. PR supplémentaire

### PR25 — Database connection wizard and DB dump scope

- Étendre le wizard pour collecter les informations de connexion DB.
- Supporter PostgreSQL local, Docker et remote.
- Supporter MariaDB/MySQL local, Docker et remote.
- Créer des fichiers secrets root-only.
- Ajouter `server-backup db test`.
- Ajouter `server-backup db dump-test`.
- Supporter dump par base, all-databases et PostgreSQL globals.
- Ajouter warnings dans le rapport email si couverture DB incomplète.
