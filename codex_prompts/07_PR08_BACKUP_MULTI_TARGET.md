# Prompt Codex — PR8 backup multi-target

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

PR6 est terminée :
- server-backup profile add
- génération profiles.d/<profile>.conf
- profiles generic, system-filesystem, docker-host, docker-app, cis-site
- status affiche les profiles
- config validate prend les profiles en compte
- docs PROFILES.md

PR7 est terminée et hotfixée :
- server-backup repo init <target>
- server-backup repo check <target>
- server-backup repo snapshots <target>
- support --all
- module server_backup/restic.py
- verrou local avec fcntl.flock
- lock file /run/server-backup-repo.lock avec fallback /tmp/server-backup-repo.lock
- les commandes repo ne peuvent plus tourner en parallèle

État réel de la target NAS validée :
- target name : nas-steph
- NAS WireGuard IP : 10.192.1.254
- SSH user : backup_mesfragrances
- SFTP test : OK
- restic repo init : OK
- restic repo check : OK
- restic snapshots : No snapshots found
- repository path : /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic

Objectif de cette PR :

Implémenter uniquement :

PR8 — backup multi-target

Objectif :
- implémenter server-backup backup run
- charger backup.conf
- charger targets
- charger profiles
- construire les commandes restic backup
- lancer restic backup vers chaque target configurée
- supporter plusieurs profiles
- supporter plusieurs targets
- collecter les résultats
- écrire un rapport local texte et JSON
- utiliser le verrou restic local existant
- ne pas encore gérer les dumps DB complets
- ne pas encore gérer le coverage audit avancé
- ne pas encore gérer prune/forget
- ne pas encore envoyer d’email réel
- ne pas encore faire de restore test

Ne pas implémenter encore :
- db add réel
- dump PostgreSQL/MariaDB/MySQL réel
- docker scan avancé
- coverage audit réel
- prune/forget réel
- restore test réel
- email réel

Ces fonctionnalités viendront dans les PR suivantes.

Contraintes générales :
- pas de dépendance Python externe
- ne jamais stocker de secrets dans Git
- ne jamais afficher de secrets dans les logs
- ne jamais afficher le contenu du RESTIC_PASSWORD_FILE
- ne jamais afficher de clé privée SSH
- comportement idempotent
- erreurs claires
- compatible Debian/Ubuntu
- le système tourne sur l’hôte Linux, pas dans Docker
- backend MVP : SFTP uniquement
- fichiers de config éditables à la main
- utiliser subprocess.run avec shell=False
- ne pas contacter le NAS depuis status ou config validate

Important :
- backup run est la première commande qui crée de vrais snapshots restic.
- Ajouter un mode --dry-run pour tester sans écrire de snapshot.
- Par défaut, backup run doit sauvegarder vers toutes les targets configurées.
- Une target qui échoue ne doit pas empêcher les autres targets d’être tentées.
- Le code retour global doit être non nul si au moins une target ou un profile échoue.
- Le verrou restic local doit être pris avant toute commande restic backup.
- Le verrou doit couvrir toute l’opération backup run.

Livrables attendus :

1. Ajouter server_backup/backup.py

Créer un module dédié backup.

Fonctions attendues :

- load_backup_context()
- collect_profiles()
- collect_targets()
- normalize_backup_paths(profile)
- normalize_excludes(profile)
- validate_backup_paths(profile)
- build_backup_tags(global_config, profile)
- build_restic_backup_args(global_config, profile, dry_run=False)
- run_backup_for_target(global_config, target, profiles, dry_run=False)
- run_backup_all_targets(global_config, targets, profiles, dry_run=False)
- write_backup_report(report, report_dir)
- render_backup_report_text(report)
- render_backup_report_json(report)
- run_backup(dry_run=False, target_name=None, profile_name=None)

Utiliser les helpers existants dans :
- server_backup/config.py
- server_backup/validators.py
- server_backup/restic.py

Réutiliser :
- validate_restic_preflight()
- build_restic_env()
- build_sftp_command()
- run_restic_command()
- restic_repo_lock()

2. Commande CLI

Implémenter :

sudo server-backup backup run

Options :

sudo server-backup backup run --dry-run
sudo server-backup backup run --target nas-steph
sudo server-backup backup run --profile <profile>
sudo server-backup backup run --target nas-steph --profile <profile>
sudo server-backup backup run --dry-run --target nas-steph --profile <profile>

Comportement :
- sans --target : toutes les targets
- sans --profile : tous les profiles
- avec --dry-run : ajouter --dry-run à la commande restic backup
- avec --target : ne traiter que cette target
- avec --profile : ne traiter que ce profile

Si aucune target :
- message clair
- code non nul

Si aucun profile :
- message clair
- code non nul
- recommander : sudo server-backup profile add

3. Construction restic backup

Pour chaque couple target/profile, construire une commande du type :

restic backup <paths> --tag <BACKUP_NAME> --tag <profile_name> --tag server-backup --exclude <pattern> ...

Tags recommandés :
- server-backup
- BACKUP_NAME
- PROFILE_NAME
- PROFILE_TYPE
- chaque tag de BACKUP_TAGS si présent

Exemple :
BACKUP_TAGS="pyparfums prod docker"

doit produire :
--tag pyparfums
--tag prod
--tag docker

Ne pas inclure de tag vide.

Inclure les excludes du profile :
EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
)

Chaque entrée doit devenir :
--exclude <entry>

Ne pas encore ajouter :
- --one-file-system
- --exclude-file
- --files-from
sauf si déjà prévu proprement.

4. Gestion des chemins

Pour BACKUP_PATHS :
- si un chemin existe : l’inclure
- si un chemin n’existe pas : warning
- si tous les chemins d’un profile sont absents : failure pour ce profile
- ne pas supprimer/modifier les chemins
- ne pas créer les chemins applicatifs

Un profile avec chemins partiellement absents peut continuer avec les chemins existants.

Exemple :
BACKUP_PATHS=(
  "/etc"
  "/srv/app"
)

Si /etc existe et /srv/app manque :
- warning sur /srv/app
- backup de /etc continue

Si aucun chemin n’existe :
- ne pas lancer restic backup pour ce profile
- résultat profile = failure

5. Verrouillage

Utiliser le verrou PR7 :

/run/server-backup-repo.lock
fallback /tmp/server-backup-repo.lock

Le verrou doit couvrir toute l’opération backup run.

Si une autre opération restic tourne :
- afficher message clair
- code non nul
- ne pas lancer backup

6. Rapport local

À chaque backup run, générer un rapport local sous :

/var/lib/server-backup/reports

Fichiers :

backup-run-YYYYMMDD-HHMMSS.txt
backup-run-YYYYMMDD-HHMMSS.json

Le rapport doit contenir :

- hostname
- BACKUP_NAME
- start time
- end time
- duration
- dry_run true/false
- global status : success/warning/failure
- targets traitées
- profiles traités
- résultat par target
- résultat par profile
- chemins sauvegardés
- chemins manquants
- excludes utilisés
- commandes restic résumées sans secrets
- stdout/stderr filtrés
- warnings
- errors
- chemin du rapport texte
- chemin du rapport JSON

Ne jamais inclure :
- contenu du RESTIC_PASSWORD_FILE
- clé privée SSH
- tokens
- secrets
- mots de passe

Créer ou mettre à jour aussi :

/var/lib/server-backup/state/last-backup-run.json

avec un résumé du dernier run.

7. Affichage CLI

À la fin de server-backup backup run, afficher un résumé clair :

Exemple :

server-backup backup run

Targets: 1
Profiles: 2
Dry-run: no

Target nas-steph:
  profile system-filesystem: OK
  profile docker-host: WARNING
    missing path: /srv/nonexistent

Overall: WARNING

Reports:
  /var/lib/server-backup/reports/backup-run-20260519-xxxxxx.txt
  /var/lib/server-backup/reports/backup-run-20260519-xxxxxx.json

8. Mise à jour status

server-backup status doit rester rapide et local.

Ajouter si présent :
- last backup run date
- last backup status
- last backup report path

Lire uniquement :
/var/lib/server-backup/state/last-backup-run.json

Ne pas contacter le NAS.

9. Gestion des erreurs

Cas à gérer proprement :
- aucune target
- aucun profile
- target inconnue
- profile inconnu
- restic absent
- repository non initialisé
- mauvais mot de passe restic
- SFTP inaccessible
- chemin profile inexistant
- tous les chemins d’un profile absents
- lock déjà pris
- permission denied sur un chemin local
- permission denied sur RESTIC_PASSWORD_FILE

Le backup doit tenter les autres targets/profiles quand possible.

10. Tests unitaires

Ajouter ou compléter :

- tests/test_backup_helpers.py
- tests/test_backup_cli.py

Ne pas faire de vrai réseau dans les tests unitaires.
Ne pas lancer de vrai restic dans les tests unitaires.
Utiliser unittest.mock.

Tester au minimum :

- normalize_backup_paths
- normalize_excludes
- build_backup_tags
- build_restic_backup_args
- dry-run ajoute --dry-run
- excludes deviennent --exclude
- tags BACKUP_TAGS sont splittés correctement
- profile sans chemin existant produit failure
- profile avec chemins partiellement absents produit warning
- target inconnue produit erreur
- profile inconnu produit erreur
- write_backup_report écrit txt/json
- secrets redacted dans rapport
- last-backup-run.json est généré
- lock utilisé autour de run_backup

11. Tests manuels attendus

Avec la vraie target nas-steph disponible, exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli backup --help
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup target test nas-steph
- sudo server-backup repo check nas-steph
- sudo server-backup backup run --dry-run --target nas-steph

Si un profile sûr existe, exécuter aussi un vrai backup limité :

- sudo server-backup backup run --target nas-steph --profile <safe-profile>

Si aucun profile n’existe :
- ne pas inventer de succès
- créer un profile de test minimal si nécessaire, par exemple avec /var/lib/server-backup/state
- indiquer clairement s’il a été supprimé ensuite ou conservé

Après un vrai backup, vérifier :

- sudo server-backup repo snapshots nas-steph
- sudo server-backup repo check nas-steph

12. Documentation

Mettre à jour docs/SERVER_INSTALL.md :

Ajouter section :

Premier backup :

sudo server-backup backup run --dry-run
sudo server-backup backup run

Expliquer :
- repo init doit être fait avant
- au moins un profile doit exister
- dry-run ne crée pas de snapshot
- backup réel crée un snapshot restic
- rapports locaux dans /var/lib/server-backup/reports

Mettre à jour docs/CONFIG_REFERENCE.md :

Documenter :
- BACKUP_TAGS
- BACKUP_PATHS
- EXCLUDES
- last-backup-run.json
- reports backup-run-*.txt/json

Ajouter ou mettre à jour :

docs/BACKUP_RUN.md

Ce document doit expliquer :
- dry-run
- backup réel
- multi-target
- multi-profile
- warnings chemins absents
- rapports
- codes retour
- erreurs fréquentes
- différence avec repo check/init
- pas encore de DB dumps dans PR8

Mettre à jour docs/RESTIC_REPOSITORIES.md :

Ajouter :
- repo init/check/snapshots prépare le dépôt
- backup run crée les snapshots
- snapshots permet de vérifier la création du premier snapshot

13. Critères d’acceptation

- python3 -m unittest discover -s tests passe
- python3 -m server_backup.cli backup --help fonctionne
- sudo server-backup backup run affiche une erreur claire si aucun profile
- sudo server-backup backup run --dry-run --target nas-steph fonctionne si profile valide
- sudo server-backup backup run --target nas-steph --profile <safe-profile> crée un snapshot si profile valide
- sudo server-backup repo snapshots nas-steph affiche ensuite au moins un snapshot après backup réel
- rapport texte généré
- rapport JSON généré
- last-backup-run.json généré
- aucune valeur sensible n’est affichée
- status affiche le dernier backup run sans contacter le NAS
- config validate reste local
- le lock empêche une commande backup et une commande repo de tourner en parallèle
- aucun prune n’est lancé
- aucun dump DB réel n’est lancé
- aucun email réel n’est envoyé

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- si un vrai snapshot a été créé, donner son ID restic
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR9 — rétention et prune

Objectif PR9 :
- implémenter server-backup repo prune ou backup prune intégré
- restic forget --keep-daily --keep-weekly --keep-monthly --prune
- appliquer par target
- ne pas supprimer sans affichage clair
```
