# Prompt Codex — PR7 init/check repositories

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

État réel de la target NAS validée :
- target name : nas-steph
- NAS WireGuard IP : 10.192.1.254
- SSH user : backup_mesfragrances
- SFTP test : OK
- repository path : /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic

Objectif de cette PR :

Implémenter uniquement :

PR7 — init/check repositories

Objectif :
- implémenter server-backup repo init <target>
- implémenter server-backup repo check <target>
- implémenter server-backup repo snapshots <target>
- utiliser restic avec les targets SFTP configurées
- vérifier que les credentials restic sont présents
- vérifier que la target est valide
- ne pas encore faire de backup réel
- ne pas encore faire de prune
- ne pas encore faire de restore test

Ne pas implémenter encore :
- backup restic réel
- prune/forget réel
- db add réel
- dump DB réel
- docker scan avancé
- coverage audit réel
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

Point important restic + SSH config isolée :
Les targets SFTP utilisent une configuration SSH dédiée :
- /etc/server-backup/ssh/ssh_config
- /etc/server-backup/ssh/known_hosts

Ne pas dépendre de /root/.ssh/config.

Pour que restic utilise cette configuration SSH dédiée, construire la commande restic avec une option SFTP explicite.

Approche attendue :

RESTIC_REPOSITORY="sftp:<SSH_HOST_ALIAS>:<remote_path>"

et passer à restic une option équivalente à :

-o sftp.command="ssh -F /etc/server-backup/ssh/ssh_config <SSH_HOST_ALIAS> -s sftp"

Le code doit construire cette option automatiquement depuis :
- SSH_CONFIG_FILE
- SSH_HOST_ALIAS

Ne pas utiliser StrictHostKeyChecking=no.

Livrables attendus :

1. Ajouter server_backup/restic.py

Créer un module dédié restic.

Fonctions attendues :

- build_restic_env(global_config, target)
- build_sftp_command(target)
- build_restic_base_command(target)
- run_restic_command(args, env, timeout=None)
- repo_is_initialized(target, global_config)
- init_repository(target, global_config)
- check_repository(target, global_config)
- list_snapshots(target, global_config)
- select_target(name, targets)
- require_restic_available()
- validate_restic_preflight(global_config, target)

Utiliser subprocess.run avec shell=False.

Ne jamais logger :
- contenu du fichier RESTIC_PASSWORD_FILE
- clés privées SSH
- variables sensibles

2. Préflight restic

Avant toute commande restic, vérifier :

- restic est disponible dans PATH
- target existe
- target est valide via validate_target_config()
- TARGET_TYPE="sftp"
- RESTIC_REPOSITORY existe
- RESTIC_PASSWORD_FILE existe
- RESTIC_PASSWORD_FILE est lisible par root
- RESTIC_CACHE_DIR existe ou peut être créé
- SSH_CONFIG_FILE existe
- SSH_IDENTITY_FILE existe
- SSH_KNOWN_HOSTS_FILE existe
- SSH_HOST_ALIAS existe
- SSH_PORT valide

Si un prérequis manque :
- afficher une erreur claire
- retourner code non nul
- ne pas lancer restic

3. Implémenter server-backup repo init <target>

Commande :

sudo server-backup repo init nas-steph

Elle doit :

- charger backup.conf
- charger targets
- sélectionner la target par TARGET_NAME
- faire les validations préflight
- vérifier si le dépôt semble déjà initialisé
- si déjà initialisé :
  - afficher "Repository already initialized"
  - retourner 0
- sinon :
  - exécuter restic init
  - afficher un résultat clair
  - ne jamais afficher le mot de passe

Détection dépôt déjà initialisé :
- essayer une commande non destructive du type restic snapshots ou restic cat config
- si elle réussit, considérer le dépôt initialisé
- si elle échoue avec une erreur compatible "repository not initialized", permettre restic init
- si elle échoue pour réseau/authentification, ne pas lancer init et afficher l’erreur

Si restic init échoue :
- afficher stdout/stderr de manière filtrée
- retourner code non nul

4. Implémenter server-backup repo check <target>

Commande :

sudo server-backup repo check nas-steph

Elle doit :

- charger config et target
- vérifier préflight
- exécuter restic check
- afficher résultat clair
- retourner code 0 si OK
- retourner code non nul si échec

Pour cette PR, utiliser un check simple :

restic check

Ne pas encore implémenter read-data-subset ou full-check scheduling. Cela viendra plus tard.

5. Implémenter server-backup repo snapshots <target>

Commande :

sudo server-backup repo snapshots nas-steph

Elle doit :

- charger config et target
- vérifier préflight
- exécuter restic snapshots
- afficher la sortie restic
- retourner code non nul si erreur

Cette commande est utile pour valider qu’un dépôt est initialisé.

6. Support option --all

Ajouter le support optionnel :

sudo server-backup repo init --all
sudo server-backup repo check --all
sudo server-backup repo snapshots --all

Comportement :
- parcourir toutes les targets
- tenter chaque target même si une échoue
- afficher résultat par target
- code retour global non nul si au moins une target échoue

Si aucune target :
- message clair
- code non nul

7. Mise à jour CLI

Mettre à jour server_backup/cli.py.

Commandes attendues :

- server-backup repo init <target>
- server-backup repo init --all
- server-backup repo check <target>
- server-backup repo check --all
- server-backup repo snapshots <target>
- server-backup repo snapshots --all

Les anciens stubs repo init/check doivent être remplacés par l’implémentation réelle.

8. Mise à jour status

server-backup status doit rester rapide.

Ne pas lancer restic automatiquement dans status.

Mais status peut afficher pour chaque target :

- TARGET_NAME
- TARGET_TYPE
- RESTIC_REPOSITORY redacted si nécessaire
- RESTIC_PASSWORD_FILE exists yes/no, sans afficher le contenu
- SSH_CONFIG_FILE exists yes/no
- SSH_IDENTITY_FILE exists yes/no
- SSH_KNOWN_HOSTS_FILE exists yes/no

Ne pas faire de test réseau dans status.

9. Mise à jour config validate

server-backup config validate doit rester local.

Il doit vérifier :
- existence RESTIC_PASSWORD_FILE
- permissions RESTIC_PASSWORD_FILE si possible
- existence RESTIC_CACHE_DIR
- existence SSH_CONFIG_FILE
- existence SSH_IDENTITY_FILE
- existence SSH_KNOWN_HOSTS_FILE

Ne pas lancer restic.
Ne pas faire de réseau.
Ne pas contacter le NAS.

10. Gestion des erreurs restic

Créer une fonction de filtrage des logs ou sorties.

But :
- afficher les erreurs utiles
- ne pas afficher de secrets
- éviter les stacktraces non gérées

Cas à gérer clairement :
- restic absent
- RESTIC_PASSWORD_FILE absent
- permission denied sur RESTIC_PASSWORD_FILE
- repository not initialized
- repository already initialized
- SSH host key missing
- SSH authentication failed
- DNS failure
- SFTP failure
- NAS unreachable
- bad password

11. Tests unitaires

Ajouter ou compléter :

- tests/test_restic_helpers.py
- tests/test_repo_cli.py si pertinent

Ne pas faire de vrai réseau.
Ne pas lancer de vrai restic si possible dans les tests unitaires.

Tester au minimum :

- build_sftp_command génère ssh -F <config> <alias> -s sftp
- build_restic_env contient RESTIC_REPOSITORY
- build_restic_env contient RESTIC_PASSWORD_FILE mais le contenu n’est jamais lu
- build_restic_env contient RESTIC_CACHE_DIR
- select_target trouve une target par TARGET_NAME
- select_target échoue proprement si target absente
- validate_restic_preflight détecte restic password absent
- validate_restic_preflight détecte SSH config absent
- les commandes sont construites avec shell=False
- redaction ne montre pas de secret

Pour tester run_restic_command, utiliser mocking standard library unittest.mock.

12. Documentation

Mettre à jour docs/SERVER_INSTALL.md :

Ajouter section :

Initialisation du dépôt restic :

sudo server-backup repo init <target>
sudo server-backup repo check <target>
sudo server-backup repo snapshots <target>

Expliquer :
- target add doit être fait avant repo init
- la clé publique doit être installée côté NAS avant repo init
- target test doit réussir avant repo init
- restic-password doit exister
- repo init ne lance aucun backup

Mettre à jour docs/CONFIG_REFERENCE.md :

Documenter :
- champs utilisés par restic
- RESTIC_REPOSITORY
- RESTIC_PASSWORD_FILE
- RESTIC_CACHE_DIR
- SSH_CONFIG_FILE
- SSH_HOST_ALIAS
- option interne sftp.command

Mettre à jour docs/NAS_SFTP_TARGET.md :

Ajouter :
- après installation clé publique côté NAS :
  sudo server-backup target test <target>
  sudo server-backup repo init <target>
  sudo server-backup repo check <target>

Mettre à jour docs/RESTORE_KIT.md :

Ajouter :
- le restore kit doit contenir les informations nécessaires pour retrouver le dépôt restic
- target name
- RESTIC_REPOSITORY
- hostname NAS
- remote path
- restic password
- méthode SSH

Ajouter si pertinent :

docs/RESTIC_REPOSITORIES.md

Ce document doit expliquer :
- init
- check
- snapshots
- --all
- erreurs fréquentes
- sécurité du mot de passe restic
- le fait que repo init ne fait pas de backup

13. Critères d’acceptation

- python3 -m unittest discover -s tests passe
- python3 -m server_backup.cli --help fonctionne
- python3 -m server_backup.cli repo --help fonctionne
- sudo server-backup repo init nas-steph fonctionne si NAS disponible
- sudo server-backup repo check nas-steph fonctionne si dépôt initialisé
- sudo server-backup repo snapshots nas-steph fonctionne si dépôt initialisé
- --all fonctionne pour init/check/snapshots
- si aucune target existe, message clair et code non nul
- si RESTIC_PASSWORD_FILE absent, message clair et code non nul
- si SSH config absent, message clair et code non nul
- aucune commande restic ne révèle de secret
- status ne contacte pas le NAS
- config validate ne contacte pas le NAS
- aucun backup réel n’est lancé
- aucun prune n’est lancé
- aucun fichier de production n’est modifié hors config attendue

Tests à exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli repo --help
- python3 -m server_backup.cli status
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup repo snapshots --all
- sudo server-backup repo check --all

Comme une vraie target NAS est disponible, exécuter aussi :

- sudo server-backup target test nas-steph
- sudo server-backup repo init nas-steph
- sudo server-backup repo snapshots nas-steph
- sudo server-backup repo check nas-steph

Ne pas inventer de succès réseau : si une commande échoue, fournir la sortie et l’analyse.

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR8 — backup.sh multi-target

Objectif PR8 :
- charger backup.conf
- charger profiles
- créer la liste des fichiers à sauvegarder
- lancer restic backup vers chaque target
- collecter résultats
- ne pas encore gérer DB dumps complets ni coverage audit avancé
```
