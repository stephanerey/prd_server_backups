# Prompt Codex — PR6 Wizard profile

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1/PR2/PR27 partiel sont terminées :
- structure repo
- install.sh idempotent
- CLI minimale
- systemd service/timer
- exemples
- docs initiales

PR3 est terminée :
- loader config
- validateurs
- config validate
- config show
- redaction secrets

PR4 est terminée :
- server-backup setup
- génération /etc/server-backup/backup.conf
- génération optionnelle /etc/server-backup/secrets/restic-password
- configuration du timer systemd
- status enrichi
- email test stub

PR5 est terminée :
- server-backup target add
- server-backup target test <target>
- génération targets.d/<target>.env
- génération clé SSH ED25519 dédiée
- ssh_config isolé
- known_hosts isolé
- test SFTP
- docs NAS SFTP

Objectif de cette PR :

Implémenter uniquement :

PR6 — Wizard profile

Objectif :
- implémenter server-backup profile add
- générer /etc/server-backup/profiles.d/<profile>.conf
- supporter les types de profiles :
  - generic
  - system-filesystem
  - docker-host
  - docker-app
  - cis-site
- générer des profils éditables à la main
- détecter et proposer des chemins à sauvegarder
- ne pas encore lancer de backup réel
- ne pas encore faire de dump DB réel
- ne pas encore faire de scan Docker réel complet
- ne pas encore faire de coverage audit réel

Ne pas implémenter encore :
- backup restic réel
- repo init réel
- repo check réel
- db add réel
- db dump réel
- docker scan réel avancé
- coverage audit réel
- restore test réel
- email réel

Ces fonctionnalités viendront dans les PR suivantes.

Contraintes générales :
- pas de dépendance Python externe
- ne jamais stocker de secrets dans Git
- ne jamais afficher de secrets dans les logs
- ne jamais écraser une config existante sans confirmation explicite
- comportement idempotent
- erreurs claires
- compatible Debian/Ubuntu
- le système tourne sur l’hôte Linux, pas dans Docker
- backend MVP : SFTP uniquement
- fichiers de config éditables à la main

Livrables attendus :

1. Compléter server_backup/wizard.py

Ajouter les fonctions utiles pour profile add, par exemple :

- run_profile_add()
- prompt_profile_type()
- prompt_profile_name()
- prompt_backup_paths()
- prompt_excludes()
- prompt_profile_generic()
- prompt_profile_system_filesystem()
- prompt_profile_docker_host()
- prompt_profile_docker_app()
- prompt_profile_cis_site()
- sanitize_profile_name()
- render_profile_conf()
- write_profile_file_secure()

Les fonctions de rendu doivent être testables sans interaction.

2. Implémenter server-backup profile add

Commande :

sudo server-backup profile add

Le wizard doit demander :

- nom logique du profile
- type de profile :
  - generic
  - system-filesystem
  - docker-host
  - docker-app
  - cis-site
- chemins à sauvegarder
- exclusions
- comportement en cas de chemin absent :
  - warning
  - ignore
  - future option fail, mais pas actif par défaut

Le fichier généré :

/etc/server-backup/profiles.d/<profile>.conf

Doit être écrit en :

0600 root:root

Si le fichier existe déjà :
- ne pas l’écraser sans confirmation
- si remplacement accepté, créer une sauvegarde horodatée :
  /etc/server-backup/profiles.d/<profile>.conf.bak-YYYYMMDD-HHMMSS

3. Format commun des profiles

Chaque profile généré doit contenir :

CONFIG_VERSION="1"
GENERATED_BY="server-backup"
GENERATED_AT="<timestamp ISO8601>"

PROFILE_NAME="<profile>"
PROFILE_TYPE="<type>"

BACKUP_PATHS=(
  "/path1"
  "/path2"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
)

Les tableaux doivent être compatibles avec le parser existant de PR3.

4. Profile generic

Pour PROFILE_TYPE="generic", le wizard doit demander :

- chemins à sauvegarder, saisie multiple
- exclusions, saisie multiple

Exclusions proposées par défaut :

"**/.cache"
"**/cache"
"**/tmp"
"**/__pycache__"
"**/node_modules"

Exemple généré :

PROFILE_NAME="generic-app"
PROFILE_TYPE="generic"

BACKUP_PATHS=(
  "/srv/my-app"
  "/etc/my-app"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/__pycache__"
  "**/node_modules"
)

5. Profile system-filesystem

Pour PROFILE_TYPE="system-filesystem", proposer par défaut :

BACKUP_PATHS=(
  "/etc"
  "/root"
  "/home"
  "/srv"
  "/opt"
  "/usr/local"
  "/var/spool/cron"
  "/var/lib/server-backup/state"
)

EXCLUDES=(
  "/proc"
  "/sys"
  "/dev"
  "/run"
  "/tmp"
  "/var/tmp"
  "/mnt"
  "/media"
  "/lost+found"
  "/var/cache"
  "/var/log/*.log"
  "/var/lib/docker/overlay2"
  "/var/lib/docker/image"
  "/var/lib/docker/containers/*/*.log"
  "/etc/server-backup/secrets"
  "**/.cache"
  "**/cache"
  "**/tmp"
)

Le wizard doit permettre d’accepter ces valeurs par défaut ou de les modifier.

Ce profile ne remplace pas les dumps DB ni les profiles Docker/CIS.

Afficher clairement :

"system-filesystem is a broad filesystem backup profile. It does not replace logical DB dumps."

6. Profile docker-host

Pour PROFILE_TYPE="docker-host", le wizard doit demander :

- scanner les chemins standards ? défaut yes :
  - /srv
  - /opt
  - /home
- ajouter un chemin custom ?
- inclure /etc ? défaut yes
- inclure /var/lib/server-backup/state ? défaut yes
- activer DOCKER_INVENTORY ? défaut true
- ajouter manuellement des volumes Docker ?
- ajouter manuellement des bind mounts ?
- ajouter des exclusions ?

Dans cette PR, ne pas implémenter encore un vrai docker inspect avancé.
Mais si Docker est présent, une détection simple est autorisée :
- docker ps --format
- docker volume ls
- docker compose files non obligatoire

Si Docker n’est pas installé ou pas accessible :
- ne pas échouer
- afficher un warning clair
- permettre de saisir les chemins manuellement

Exemple généré :

PROFILE_NAME="docker-host"
PROFILE_TYPE="docker-host"
DOCKER_INVENTORY="true"

BACKUP_PATHS=(
  "/etc"
  "/srv"
  "/opt"
  "/var/lib/server-backup/state"
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

7. Profile docker-app

Pour PROFILE_TYPE="docker-app", le wizard doit demander :

- nom logique de l’application
- chemin du projet Compose
- chemin compose.yml ou docker-compose.yml
- inclure fichier .env ? oui/non
- chemins de volumes ou bind mounts à inclure
- exclusions
- l’application contient-elle une DB ? oui/non
- si oui, afficher que la configuration DB détaillée viendra avec PR25 db add

Ne pas configurer encore DATABASE_DUMPS en détail dans cette PR, sauf placeholder commenté.

Exemple généré :

PROFILE_NAME="my-docker-app"
PROFILE_TYPE="docker-app"

BACKUP_PATHS=(
  "/srv/my-docker-app"
  "/var/lib/docker/volumes/my_app_data/_data"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/node_modules"
)

DOCKER_INVENTORY="true"

# DATABASE_DUMPS will be configured by:
# sudo server-backup db add

8. Profile cis-site

Pour PROFILE_TYPE="cis-site", le wizard doit traiter le cas générique CIS.

Questions à poser :

- nom logique du site CIS
- chemin du projet CIS
- chemin du frontend, défaut <project>/frontend si présent
- chemin du backend, défaut <project>/backend si présent
- chemin des migrations, exemples :
  - <project>/backend/alembic
  - <project>/backend/migrations
- chemin compose.yml ou docker-compose.yml
- inclure fichier .env ? oui/non
- les pages builder sont-elles stockées en PostgreSQL ? défaut yes
- table de pages attendue, défaut site_pages
- y a-t-il des médias/uploads locaux ? oui/non
- chemins médias/uploads/assets à inclure
- les médias sont-ils externes ? oui/non
- activer WEB_CONTENT_CRITICAL ? défaut true
- activer DOCKER_INVENTORY ? défaut true
- DB à configurer maintenant ? non dans cette PR, afficher que PR25 le fera

Le profile généré doit inclure :

APP_KIND="cis-site"
WEB_CONTENT_CRITICAL="true"
DOCKER_INVENTORY="true"

CONTENT_CLASSIFICATION=(
  "db:postgresql:<database-placeholder>:site_pages:builder-pages"
  "files:<frontend_path>:frontend-renderer-and-routes"
  "files:<backend_path>:api-models-and-migrations"
)

Si la DB n’est pas encore configurée, ajouter un commentaire :

# DATABASE_DUMPS will be configured by:
# sudo server-backup db add

Exemple généré :

PROFILE_NAME="cis-site"
PROFILE_TYPE="cis-site"
APP_KIND="cis-site"
WEB_CONTENT_CRITICAL="true"
DOCKER_INVENTORY="true"

BACKUP_PATHS=(
  "/srv/cis-project"
  "/srv/cis-project/frontend"
  "/srv/cis-project/backend"
  "/srv/cis-project/backend/alembic"
  "/var/lib/server-backup/state"
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

CONTENT_CLASSIFICATION=(
  "db:postgresql:<database-placeholder>:site_pages:builder-pages"
  "files:/srv/cis-project/frontend:frontend-renderer-and-routes"
  "files:/srv/cis-project/backend:api-models-and-migrations"
)

# DATABASE_DUMPS will be configured by:
# sudo server-backup db add

9. Détection simple des fichiers Compose

Ajouter une fonction simple, sans dépendance externe, qui peut chercher dans un chemin donné :

- compose.yml
- compose.yaml
- docker-compose.yml
- docker-compose.yaml
- docker-compose.override.yml

Le wizard peut proposer les fichiers trouvés.

Ne pas implémenter un scan Docker complet dans cette PR.

10. Validation des chemins

Le wizard doit afficher un warning si un chemin saisi n’existe pas.

Mais il doit permettre de l’ajouter quand même, car certains chemins peuvent être créés plus tard.

11. Mise à jour validators.py

Adapter validate_profile_config si nécessaire pour mieux gérer :

- generic
- system-filesystem
- docker-host
- docker-app
- cis-site

Règles :

- BACKUP_PATHS obligatoire
- PROFILE_NAME obligatoire
- PROFILE_TYPE obligatoire
- EXCLUDES optionnel
- DOCKER_INVENTORY recommandé pour docker-host/docker-app/cis-site
- WEB_CONTENT_CRITICAL recommandé pour cis-site
- CONTENT_CLASSIFICATION recommandé pour cis-site
- DATABASE_DUMPS recommandé pour cis-site mais warning seulement dans cette PR

Ne pas rendre ces warnings bloquants.

12. Mise à jour status

server-backup status doit afficher les profiles avec :

- PROFILE_NAME
- PROFILE_TYPE
- nombre de BACKUP_PATHS
- DOCKER_INVENTORY si présent
- WEB_CONTENT_CRITICAL si présent
- validation OK/WARNING/ERROR

13. Tests unitaires

Ajouter ou compléter :

- tests/test_profile_rendering.py
- tests/test_profile_wizard_helpers.py

Tester au minimum :

- sanitize_profile_name
- render generic profile
- render system-filesystem profile
- render docker-host profile
- render docker-app profile
- render cis-site profile
- parse_config_file peut relire les profiles générés
- validate_profile_config accepte les profiles générés
- cis-site sans DATABASE_DUMPS produit warning, pas error
- chemins avec espaces ou caractères dangereux sont correctement quotés ou refusés proprement

Ne pas utiliser Docker réel dans les tests unitaires.

14. Documentation

Mettre à jour docs/SERVER_INSTALL.md :

Ajouter section :

Création d’un profile :

sudo server-backup profile add

Décrire les types :

- generic
- system-filesystem
- docker-host
- docker-app
- cis-site

Mettre à jour docs/CONFIG_REFERENCE.md :

Documenter :

- profiles.d/<name>.conf
- PROFILE_NAME
- PROFILE_TYPE
- BACKUP_PATHS
- EXCLUDES
- DOCKER_INVENTORY
- WEB_CONTENT_CRITICAL
- APP_KIND
- CONTENT_CLASSIFICATION
- DATABASE_DUMPS placeholder

Mettre à jour docs/RESTORE_KIT.md :

Ajouter que le restore kit doit documenter :

- quels profiles existent
- quels chemins sont critiques
- quels chemins sont volontairement exclus
- pour cis-site : où sont frontend/backend/migrations/media
- quelles DB restent à configurer avec db add

Ajouter si pertinent :

docs/PROFILES.md

Ce document doit expliquer :

- comment choisir un profile
- exemples de profiles
- recommandations Docker
- recommandations CIS
- différence entre system-filesystem et dumps DB

15. Critères d’acceptation

- python3 -m unittest discover -s tests passe
- python3 -m server_backup.cli --help fonctionne
- sudo server-backup profile add fonctionne en interactif
- profile add génère /etc/server-backup/profiles.d/<profile>.conf en 0600 root:root
- profile add ne remplace rien sans confirmation
- profile generic générable
- profile system-filesystem générable
- profile docker-host générable
- profile docker-app générable
- profile cis-site générable
- sudo server-backup status affiche les profiles
- sudo server-backup config validate prend les profiles en compte
- aucun backup réel n’est lancé
- aucun dump DB réel n’est lancé
- aucun scan Docker avancé obligatoire n’est lancé
- aucun secret réel n’est commité
- aucun secret n’est affiché

Tests à exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli status
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup profile add
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup config show

Tester au moins manuellement la création d’un profile :
- system-filesystem
- docker-host
- cis-site

Si tu crées des profiles de démonstration sur la machine de test, indique clairement lesquels ont été créés et s’ils ont été supprimés ensuite.

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR7 — init/check repositories

Objectif PR7 :
- implémenter server-backup repo init <target>
- implémenter server-backup repo check <target>
- utiliser restic avec les targets SFTP configurées
- ne pas encore faire de backup réel
```
