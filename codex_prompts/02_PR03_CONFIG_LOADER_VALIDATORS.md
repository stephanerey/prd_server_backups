# Prompt Codex — PR3 Configuration loader et validateurs

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

La PR1/PR2/PR27 partiel est terminée. Le socle est en place :
- arborescence projet
- install.sh idempotent
- CLI minimale
- stubs de commandes
- systemd service/timer
- exemples de configuration
- documentation courte

Objectif de cette PR :

Implémenter uniquement :

PR3 — Configuration loader et validateurs

Ne pas implémenter encore :
- wizard
- backup restic réel
- target test réel
- repo init/check réel
- DB dump réel
- Docker scan réel
- coverage audit réel
- restore test réel
- email report réel

Contexte architecture :

- Le système tourne sur l’hôte Linux, pas dans Docker.
- Les fichiers de configuration sont sous /etc/server-backup.
- Les fichiers doivent rester éditables à la main.
- Les secrets ne doivent jamais être affichés.
- Pas de dépendance Python externe.
- Code simple, robuste, testable.

Fichiers de configuration à charger :

- /etc/server-backup/backup.conf
- /etc/server-backup/targets.d/*.env
- /etc/server-backup/profiles.d/*.conf

Fichiers d’exemples à supporter :

- examples/backup.conf.example
- examples/targets/sftp.env.example
- examples/profiles/docker-host.conf.example
- examples/profiles/cis-site.conf.example
- examples/profiles/system-filesystem.conf.example

Important sécurité :

Ne pas exécuter les fichiers de configuration comme du code Python.
Ne pas afficher les secrets.
Ne pas afficher les valeurs des variables dont le nom contient :
- PASSWORD
- SECRET
- TOKEN
- KEY
- PGPASSWORD
- MYSQL_PWD
- PASS
- PWD

Pour cette PR, implémenter un parser simple qui supporte uniquement le format attendu dans nos fichiers :
- KEY="value"
- KEY='value'
- KEY=value
- tableaux Bash simples :
  ARRAY_NAME=(
    "value1"
    "value2"
  )
- lignes vides
- commentaires commençant par #

Le parser peut ignorer ou signaler en warning les lignes non supportées.
Il ne doit pas exécuter de shell.

Livrables attendus :

1. Ajouter server_backup/config.py

Fonctions attendues :

- load_global_config(path="/etc/server-backup/backup.conf")
- load_targets(path="/etc/server-backup/targets.d")
- load_profiles(path="/etc/server-backup/profiles.d")
- parse_config_file(path)
- redact_config(config)
- list_config_files(directory, suffixes)
- config_file_exists(path)

Le loader doit retourner des objets Python simples :
- dict pour backup.conf
- list[dict] pour targets
- list[dict] pour profiles

Chaque dict doit inclure au minimum :
- __file__ : chemin source du fichier
- __kind__ : global / target / profile

2. Ajouter server_backup/validators.py

Fonctions attendues :

- validate_global_config(config)
- validate_target_config(target)
- validate_profile_config(profile)
- validate_all(global_config, targets, profiles)

Chaque fonction doit retourner une structure claire, par exemple :

ValidationResult:
- ok: bool
- errors: list[str]
- warnings: list[str]

Une dataclass standard library est acceptée.

3. Champs obligatoires backup.conf

Valider au minimum :

- CONFIG_VERSION
- BACKUP_NAME
- RETENTION_DAILY
- RETENTION_WEEKLY
- RETENTION_MONTHLY
- LOCAL_DUMP_DIR
- LOG_FILE
- STATE_DIR
- REPORT_DIR
- RESTIC_CACHE_DIR
- RESTIC_PASSWORD_FILE
- RUN_RESTIC_CHECK
- RUN_PRUNE

Champs email optionnels mais validés si EMAIL_REPORT_ENABLED="true" :

- EMAIL_REPORT_TO
- EMAIL_REPORT_FROM
- EMAIL_REPORT_COMMAND

Valeurs acceptées pour EMAIL_REPORT_COMMAND :

- sendmail
- mail

Valider que les rétentions sont des entiers positifs.

4. Champs obligatoires target

Pour toute target :

- CONFIG_VERSION
- TARGET_NAME
- TARGET_TYPE
- RESTIC_REPOSITORY
- RESTIC_PASSWORD_FILE
- RESTIC_CACHE_DIR

Pour TARGET_TYPE="sftp", valider aussi :

- SSH_HOST_ALIAS
- SSH_HOSTNAME
- SSH_PORT
- SSH_USER
- SSH_IDENTITY_FILE

Valider que SSH_PORT est un entier entre 1 et 65535.

Pour cette PR, TARGET_TYPE accepté :

- sftp

Les autres types futurs doivent produire un warning clair :

"Target type '<type>' is recognized as future backend but not implemented in MVP."

Types futurs connus : rest-server, s3, rclone.

5. Champs obligatoires profile

Pour tout profile :

- CONFIG_VERSION
- PROFILE_NAME
- PROFILE_TYPE
- BACKUP_PATHS

EXCLUDES est optionnel.

PROFILE_TYPE acceptés pour cette PR :

- generic
- docker-host
- docker-app
- cis-site
- system-filesystem

Si PROFILE_TYPE="cis-site", valider :

- WEB_CONTENT_CRITICAL="true" recommandé
- DATABASE_DUMPS présent recommandé
- CONTENT_CLASSIFICATION présent recommandé

Ces manques doivent être des warnings, pas des errors dans cette PR.

Si PROFILE_TYPE="docker-host" ou "docker-app", valider :

- DOCKER_INVENTORY recommandé

Warning si absent.

6. Validation des chemins

Pour cette PR :

- vérifier que les chemins critiques système existent si possible :
  - /etc/server-backup
  - /etc/server-backup/targets.d
  - /etc/server-backup/profiles.d
  - /var/cache/restic
  - /var/lib/server-backup
- Pour BACKUP_PATHS :
  - warning si un chemin n’existe pas
  - pas d’erreur fatale

Ne pas vérifier encore les chemins distants SFTP.

7. Mise à jour CLI

Mettre à jour server_backup/cli.py.

La commande :

server-backup status

doit utiliser le loader et les validateurs.

Elle doit afficher :

- état global de /etc/server-backup
- backup.conf trouvé ou absent
- CONFIG_VERSION si présent
- BACKUP_NAME si présent
- nombre de targets
- liste des targets avec TARGET_NAME, TARGET_TYPE, RESTIC_REPOSITORY redacted si nécessaire, statut validation OK/WARNING/ERROR
- nombre de profiles
- liste des profiles avec PROFILE_NAME, PROFILE_TYPE, nombre de BACKUP_PATHS, statut validation OK/WARNING/ERROR
- erreurs
- warnings
- prochaine action recommandée

Ajouter une commande :

server-backup config validate

Elle doit charger global config, targets, profiles, afficher les erreurs/warnings, retourner code 0 si tout est OK ou warnings seulement, et retourner code non nul si errors.

Ajouter une commande :

server-backup config show

Elle doit afficher une vue redacted de la configuration et ne jamais afficher de secrets.

8. Gestion des permissions

Si la CLI est lancée en non-root et ne peut pas lire certains fichiers root-only :

- ne pas crasher
- afficher un message clair :
  "Permission denied. Run with sudo to inspect root-only configuration."
- status doit rester utilisable autant que possible

9. Tests à ajouter

Sans dépendance externe.

Ajouter si possible des tests simples avec unittest standard library :

- tests/test_config_parser.py
- tests/test_validators.py

Tester au minimum :

- parsing KEY="value"
- parsing KEY=value
- parsing tableaux Bash simples
- commentaires ignorés
- redaction des secrets
- validation backup.conf minimal
- validation target sftp minimal
- validation profile minimal
- warning sur champ manquant

Commande :

python3 -m unittest discover -s tests

10. Documentation

Mettre à jour docs/CONFIG_REFERENCE.md pour documenter :

- champs backup.conf
- champs target SFTP
- champs profile
- valeurs sensibles redacted
- commande server-backup config validate
- commande server-backup config show

Mettre à jour docs/SERVER_INSTALL.md si nécessaire pour indiquer :

- après install.sh, lancer :
  sudo server-backup status
  sudo server-backup config validate

Critères d’acceptation :

- python3 -m server_backup.cli --help fonctionne
- python3 -m server_backup.cli status fonctionne
- python3 -m server_backup.cli config validate fonctionne
- python3 -m server_backup.cli config show fonctionne
- server-backup status fonctionne
- sudo server-backup status fonctionne
- sudo server-backup config validate fonctionne
- sudo server-backup config show fonctionne
- aucune valeur sensible n’est affichée
- les fichiers absents donnent des messages clairs
- les permissions insuffisantes ne provoquent pas de stacktrace brutale
- les tests unitaires passent
- aucun wizard n’est implémenté
- aucun backup restic réel n’est implémenté
- aucun secret réel n’est ajouté au repo

Tests à exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli status
- python3 -m server_backup.cli config validate
- python3 -m server_backup.cli config show
- sudo ./scripts/install.sh
- server-backup status
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup config show

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR4 — CLI et wizard global setup.
```
