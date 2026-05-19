# Prompt Codex — PR1 / PR2 / PR27 partiel

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Objectif : implémenter le système de backup serveur décrit dans le PRD.

Avant de coder, lis entièrement les documents suivants :

- README.md
- PRD.md
- PRD_DOCKER_ADDENDUM.md
- PRD_SITE_CONTENT_ADDENDUM.md
- PRD_CIS_GENERIC_ADDENDUM.md
- PRD_COVERAGE_AND_RESTORE_STRATEGY_ADDENDUM.md
- PRD_DATABASE_CONNECTION_AND_SCOPE_ADDENDUM.md
- PRD_RESTORE_TEST_ADDENDUM.md
- PRD_IMPLEMENTATION_READINESS_REVIEW.md

Décisions d’architecture importantes :

- Le système server-backup doit tourner directement sur l’hôte Linux.
- Ne pas le faire tourner dans un conteneur Docker pour le MVP.
- Docker est une cible à inspecter/sauvegarder, pas le runtime du backup.
- Le backend MVP est SFTP uniquement.
- Les backends rest-server, S3, rclone/WebDAV sont futurs.
- Utiliser systemd timer, pas cron.
- Les fichiers de configuration doivent rester lisibles et modifiables à la main.

Contraintes générales :

- Ne jamais stocker de secrets dans Git.
- Ne jamais afficher de secrets dans les logs ou rapports.
- Ne jamais faire de restauration destructive sans confirmation explicite.
- Le système doit être idempotent : relancer l’installation ne doit pas casser une configuration existante.
- Respecter les permissions root-only pour secrets, clés SSH et configs sensibles.
- Prévoir des logs clairs.
- Prévoir des erreurs explicites.
- Ne pas ajouter de dépendance Python externe pour le MVP.
- Privilégier du code simple, robuste et maintenable.

Travail demandé pour cette première PR :

Implémenter uniquement le socle initial :

- PR1 — Structure repo et documentation de base
- PR2 — install.sh idempotent
- PR27 partiel — runtime host-level et config versioning

Ne pas implémenter encore :

- backup.sh complet
- wizard complet
- restic backup réel
- dumps DB réels
- coverage audit réel
- restore test réel
- email report complet

Important sur le wizard :

Le système final devra obtenir les informations manquantes via le wizard interactif, mais le wizard complet ne doit pas être implémenté dans cette première PR.

Dans cette première PR, préparer seulement la structure CLI pour accueillir les futures commandes :

- server-backup setup
- server-backup target add
- server-backup target test <target>
- server-backup repo init <target>
- server-backup repo check <target>
- server-backup profile add
- server-backup db add
- server-backup db test <name>
- server-backup db dump-test <name>
- server-backup docker scan
- server-backup docker inventory
- server-backup coverage audit
- server-backup backup run
- server-backup restore test
- server-backup email test
- server-backup status

Pour l’instant, toutes les commandes non implémentées peuvent afficher un message clair :

"Not implemented yet. This command will be implemented in a future PR."

Le wizard complet sera implémenté dans les PR suivantes :

- PR4 : wizard global setup
- PR5 : wizard target SFTP/SSH
- PR6 : wizard profile
- PR25 : wizard DB connection and dump scope
- PR26 : wizard profil cis-site

Livrables attendus :

1. Créer l’arborescence cible :

- docs/
- examples/
- examples/targets/
- examples/profiles/
- scripts/
- server_backup/
- systemd/

2. Ajouter les fichiers d’exemples :

- examples/backup.conf.example
- examples/targets/sftp.env.example
- examples/profiles/docker-host.conf.example
- examples/profiles/cis-site.conf.example
- examples/profiles/system-filesystem.conf.example

Chaque exemple doit contenir :

- CONFIG_VERSION="1"
- GENERATED_BY="server-backup"
- GENERATED_AT="example"

3. Ajouter scripts/install.sh idempotent.

Il doit :

- vérifier que le script tourne en root ;
- détecter Debian/Ubuntu avec apt ;
- installer si nécessaire : restic, openssh-client, python3, postgresql-client, mariadb-client ou mysql-client, mailutils si disponible ;
- créer /etc/server-backup, /etc/server-backup/secrets, /etc/server-backup/secrets/db, /etc/server-backup/ssh, /etc/server-backup/targets.d, /etc/server-backup/profiles.d, /etc/server-backup/hooks.d, /etc/server-backup/hooks.d/pre-backup.d, /etc/server-backup/hooks.d/post-backup.d, /etc/server-backup/hooks.d/pre-profile.d, /etc/server-backup/hooks.d/post-profile.d, /var/cache/restic, /var/lib/server-backup, /var/lib/server-backup/state, /var/lib/server-backup/reports ;
- appliquer les permissions 0700 root:root aux répertoires sensibles ;
- ne jamais écraser backup.conf, secrets, clés SSH, targets ou profiles existants ;
- copier les exemples uniquement s’ils n’existent pas déjà ;
- installer les units systemd depuis systemd/ vers /etc/systemd/system ;
- faire systemctl daemon-reload ;
- ne pas activer automatiquement le timer sans option explicite ;
- afficher clairement les prochaines commandes à lancer.

4. Ajouter les units systemd :

- systemd/server-backup.service
- systemd/server-backup.timer

Service attendu : Type=oneshot, ExecStart=/usr/local/sbin/server-backup-run, Wants=network-online.target, After=network-online.target.

Timer attendu : lancement quotidien par défaut à 02:30, Persistent=true, RandomizedDelaySec=10m, non activé automatiquement par install.sh.

5. Ajouter un wrapper serveur :

- /usr/local/sbin/server-backup-run

Pour cette PR, ce wrapper peut appeler server-backup backup run. Comme backup run n’est pas encore implémenté, il doit échouer proprement avec un message explicite.

6. Ajouter un squelette CLI Python :

- server_backup/__init__.py
- server_backup/cli.py

Commandes minimales fonctionnelles :

- server-backup --help
- server-backup status

Commandes stub : setup, target add, target test, repo init, repo check, profile add, db add, db test, db dump-test, docker scan, docker inventory, coverage audit, backup run, restore test, email test.

Le status doit vérifier au minimum l’existence des répertoires /etc/server-backup, targets.d, profiles.d, /var/cache/restic, /var/lib/server-backup, et la présence ou absence de targets/profiles.

7. Installer la CLI via install.sh :

- créer /usr/local/bin/server-backup
- ce wrapper doit appeler python3 -m server_backup.cli
- s’assurer que le module est installé ou copié dans un chemin accessible.

8. Ajouter la documentation courte :

- docs/SERVER_INSTALL.md
- docs/CONFIG_REFERENCE.md
- docs/RESTORE_KIT.md

Critères d’acceptation :

- sudo ./scripts/install.sh fonctionne sur Debian/Ubuntu.
- Relancer sudo ./scripts/install.sh ne casse rien.
- Les dossiers sont créés avec les bonnes permissions.
- server-backup --help fonctionne.
- server-backup status fonctionne même sans configuration complète.
- Les commandes futures existent en stub et affichent un message explicite.
- systemd/server-backup.service et systemd/server-backup.timer sont installés.
- Le timer n’est pas activé automatiquement.
- Aucun secret réel n’est créé ou commité.
- Aucun fichier de configuration existant n’est écrasé.
- Le code est simple, robuste, lisible, sans dépendance Python externe.

Tests à exécuter :

- bash -n scripts/install.sh
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli status
- sudo ./scripts/install.sh
- server-backup --help
- server-backup status
- systemctl status server-backup.timer
- systemctl cat server-backup.service
- systemctl cat server-backup.timer

À la fin, fournir :

- résumé des fichiers créés/modifiés ;
- commandes de test exécutées ;
- résultats des tests ;
- limites restantes ;
- prochaine PR recommandée.

Prochaine PR recommandée après celle-ci :

PR3 — Configuration loader et validateurs.
```
