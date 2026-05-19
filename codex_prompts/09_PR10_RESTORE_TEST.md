# Prompt Codex — PR10 restore test non destructif

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR9 sont terminées.

Le système sait maintenant :
- installer le socle host-level
- générer backup.conf
- générer une target SFTP
- tester SSH/SFTP
- générer des profiles
- initialiser/checker un dépôt restic
- créer un vrai snapshot restic via backup run
- générer des rapports locaux backup
- appliquer la rétention avec repo prune
- générer des rapports locaux prune
- utiliser un lock local partagé entre repo, backup et prune

État réel validé :
- target : nas-steph
- target test : OK
- repo init : OK
- repo check : OK
- snapshot réel existant : df472f9c
- repo snapshots : 1 snapshot
- backup run : OK
- prune dry-run : OK
- prune réel : OK
- repo check après prune : OK
- rapports locaux : OK
- lock restic local : OK

Objectif de cette PR :

Implémenter uniquement :

PR10 — restore test non destructif

Objectif :
- implémenter server-backup restore test
- restaurer un snapshot restic dans un dossier temporaire
- ne jamais restaurer dans les chemins de production
- vérifier que des fichiers ont été restaurés
- vérifier les fichiers critiques selon les profiles
- générer un rapport restore-test texte et JSON
- mettre à jour last-restore-test.json
- utiliser le lock restic local existant
- ne pas encore restaurer de DB dans une instance réelle
- ne pas encore lancer Docker Compose
- ne pas encore faire de disaster restore
- ne pas encore envoyer d’email réel

Ne pas implémenter encore :
- restauration destructive
- restore DB réel
- restore Docker réel
- docker compose up
- appel HTTP/API
- coverage audit réel
- email réel

Contraintes générales :
- pas de dépendance Python externe
- ne jamais afficher de secrets
- ne jamais afficher le contenu RESTIC_PASSWORD_FILE
- ne jamais afficher de clé privée SSH
- utiliser subprocess.run avec shell=False
- utiliser le lock local restic existant
- ne pas contacter le NAS depuis status ou config validate
- comportement clair et idempotent
- compatible Debian/Ubuntu
- restauration toujours non destructive par défaut

Commandes à implémenter :

sudo server-backup restore test --target <target>
sudo server-backup restore test --target <target> --snapshot latest
sudo server-backup restore test --target <target> --snapshot <snapshot-id>
sudo server-backup restore test --target <target> --profile <profile>
sudo server-backup restore test --target <target> --include <path>
sudo server-backup restore test --target <target> --output-dir <path>
sudo server-backup restore test --target <target> --keep-output

Comportement par défaut :
- target obligatoire pour cette PR
- snapshot = latest par défaut
- output dir = /tmp/server-backup-restore-test-YYYYMMDD-HHMMSS
- ne jamais écraser un dossier output existant
- supprimer le dossier restauré à la fin sauf si --keep-output est fourni
- générer un rapport local même si le dossier temporaire est supprimé

Livrables attendus :

1. Ajouter server_backup/restore.py

Créer un module dédié restore.

Fonctions attendues :

- build_restore_output_dir(base_dir="/tmp")
- build_restic_restore_args(snapshot, output_dir, includes=None)
- run_restore_test(target, snapshot="latest", profile_name=None, includes=None, output_dir=None, keep_output=False)
- validate_restore_preflight(global_config, target)
- collect_restore_checks(output_dir, profiles, profile_name=None)
- check_restored_files(output_dir)
- check_profile_expected_paths(output_dir, profile)
- check_db_dump_files_if_present(output_dir)
- check_cis_files_if_present(output_dir, profile)
- write_restore_report(report, report_dir)
- render_restore_report_text(report)
- render_restore_report_json(report)
- update_last_restore_test(report)

Réutiliser :
- config.py
- validators.py
- restic.py
- validate_restic_preflight()
- build_restic_env()
- run_restic_command()
- restic_repo_lock()

2. Commande restic restore

Construire une commande du type :

restic restore <snapshot> --target <output_dir>

Avec include optionnel :

restic restore <snapshot> --target <output_dir> --include <path>

Si plusieurs includes :

restic restore <snapshot> --target <output_dir> --include <path1> --include <path2>

Ne pas utiliser shell=True.

3. Sécurité restauration

Interdictions :
- ne jamais restaurer directement dans /
- ne jamais restaurer directement dans /etc
- ne jamais restaurer directement dans /srv
- ne jamais restaurer directement dans /opt
- ne jamais restaurer directement dans /var/lib/docker
- ne jamais restaurer dans un dossier existant
- ne jamais supprimer un dossier qui n’est pas sous /tmp/server-backup-restore-test-* sauf si explicitement fourni et validé comme sûr

Si --output-dir est fourni :
- refuser si le dossier existe déjà
- refuser si le chemin est /, /etc, /srv, /opt, /var, /var/lib, /var/lib/docker, /home, /root
- accepter uniquement un chemin absent ou un chemin sous /tmp par défaut

4. Vérifications minimales après restore

Après restauration, vérifier :
- le dossier output existe
- il contient au moins un fichier ou dossier
- nombre approximatif de fichiers restaurés
- taille restaurée approximative
- présence des chemins attendus selon les profiles si possible

Pour chaque profile :
- prendre BACKUP_PATHS
- convertir les chemins absolus en chemins restaurés sous output_dir
  exemple :
  /var/lib/server-backup/state
  devient :
  <output_dir>/var/lib/server-backup/state
- warning si un chemin attendu n’est pas retrouvé
- OK si au moins un chemin du profile est retrouvé

Si --profile est fourni :
- vérifier seulement ce profile

Si --include est fourni :
- vérifier seulement les includes restaurés

5. Vérifications DB basiques

Ne pas restaurer de DB réelle.

Mais si des fichiers dump sont présents dans l’arborescence restaurée, détecter les extensions :
- .dump
- .sql
- .sql.gz
- .backup

Pour PostgreSQL custom dump si pg_restore est disponible :
- exécuter pg_restore --list <dump_file>
- ne jamais restaurer dans une DB
- seulement vérifier que le dump est lisible

Si pg_restore absent :
- warning non bloquant

Pour fichiers SQL :
- vérifier fichier non vide
- éventuellement chercher des mots-clés SQL simples :
  CREATE
  INSERT
  COPY

6. Vérifications CIS basiques

Pour un profile avec :
APP_KIND="cis-site"
ou
PROFILE_TYPE="cis-site"

Vérifier dans le restore output si possible :
- frontend présent
- backend présent
- migrations présentes, ex. alembic ou migrations
- compose.yml ou docker-compose.yml présent si déclaré dans BACKUP_PATHS ou détectable
- CONTENT_CLASSIFICATION présente dans le profile
- table de pages déclarée dans CONTENT_CLASSIFICATION, ex. site_pages

Ne pas lancer backend/frontend.
Ne pas appeler d’API.
Ne pas lancer docker compose.

7. Rapports locaux

Créer des rapports sous :

/var/lib/server-backup/reports

Fichiers :

restore-test-YYYYMMDD-HHMMSS.txt
restore-test-YYYYMMDD-HHMMSS.json

Contenu :
- hostname
- BACKUP_NAME
- start time
- end time
- duration
- target
- snapshot demandé
- snapshot restauré si identifiable
- output_dir
- keep_output true/false
- profile testé si applicable
- includes si applicable
- nombre de fichiers restaurés
- taille restaurée approximative
- checks fichiers
- checks profiles
- checks DB basiques
- checks CIS basiques
- warnings
- errors
- status success/warning/failure

Mettre à jour :

/var/lib/server-backup/state/last-restore-test.json

Seulement si le restore test est success ou warning.
Si failure, générer le rapport mais ne pas marquer comme dernier test réussi.

8. Status

server-backup status doit afficher si présent :
- last restore test date
- last restore test status
- last restore test report path

Ne pas contacter le NAS.

9. Lock

Utiliser le lock restic local existant.

Le lock doit couvrir toute l’opération restore test.

Si lock déjà pris :
- message clair
- code non nul
- ne pas lancer restic restore

10. Gestion des erreurs

Cas à gérer proprement :
- target absente
- target inconnue
- dépôt non initialisé
- snapshot introuvable
- mauvais mot de passe restic
- SFTP inaccessible
- output-dir dangereux
- output-dir déjà existant
- aucun fichier restauré
- permission denied pendant restore
- lock déjà pris

11. Tests unitaires

Ajouter ou compléter :

- tests/test_restore_helpers.py
- tests/test_restore_cli.py

Ne pas faire de vrai réseau dans les tests unitaires.
Ne pas lancer de vrai restic dans les tests unitaires.
Utiliser unittest.mock.

Tester :
- build_restore_output_dir
- build_restic_restore_args latest
- build_restic_restore_args avec include
- refus output-dir dangereux
- refus output-dir existant
- conversion BACKUP_PATHS vers chemins restaurés
- détection fichiers restaurés
- rapport restore texte/json
- last-restore-test.json
- keep-output true/false
- lock utilisé
- target obligatoire
- snapshot par défaut latest

12. Tests manuels

Avec la vraie target nas-steph disponible et au moins un snapshot existant :

Exécuter :

python3 -m unittest discover -s tests
python3 -m server_backup.cli restore --help
python3 -m server_backup.cli restore test --help
sudo ./scripts/install.sh
sudo server-backup status
sudo server-backup config validate
sudo server-backup repo snapshots nas-steph
sudo server-backup restore test --target nas-steph --keep-output
sudo server-backup restore test --target nas-steph
sudo server-backup status

Vérifier :
- un dossier /tmp/server-backup-restore-test-* est créé
- si --keep-output est utilisé, le dossier reste présent
- sans --keep-output, le dossier est nettoyé
- le rapport texte est généré
- le rapport JSON est généré
- last-restore-test.json est généré
- status affiche le dernier restore test
- aucun fichier de production n’est modifié

13. Documentation

Mettre à jour docs/SERVER_INSTALL.md :

Ajouter section :

Test de restauration non destructif :

sudo server-backup restore test --target <target>
sudo server-backup restore test --target <target> --keep-output

Expliquer :
- restaure dans /tmp
- ne touche pas la production
- vérifie les fichiers restaurés
- génère un rapport local
- doit être lancé régulièrement

Mettre à jour docs/RESTIC_REPOSITORIES.md :

Ajouter :
- différence repo snapshots et restore test
- restore test utilise un snapshot existant
- restore test ne restaure pas en production

Mettre à jour docs/CONFIG_REFERENCE.md :

Documenter :
- last-restore-test.json
- restore-test-*.txt/json

Ajouter ou mettre à jour :

docs/RESTORE_TEST.md

Ce document doit expliquer :
- objectif du restore test
- commandes
- --keep-output
- --include
- --profile
- sécurité
- limites
- différence avec disaster restore réel

14. Critères d’acceptation

- tests unitaires OK
- server-backup restore --help fonctionne
- server-backup restore test --help fonctionne
- restore test fonctionne sur nas-steph
- restore test restaure dans /tmp
- restore test ne modifie pas /etc, /srv, /opt, /var/lib/docker
- restore test génère rapport texte/json
- last-restore-test.json généré
- status affiche le dernier restore test
- --keep-output conserve le dossier
- sans --keep-output, le dossier est supprimé après rapport
- output-dir dangereux refusé
- aucun secret affiché
- aucun dump DB restauré dans une DB réelle
- aucun docker compose lancé
- aucun email réel envoyé

À la fin, fournir :
- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- chemin du dossier restauré avec --keep-output
- rapports générés
- statut final restore test
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR11 — rapports email réels

Objectif PR11 :
- envoyer les rapports backup/prune/restore via sendmail ou mail
- implémenter server-backup email test réel
- ne jamais envoyer de secrets
```
