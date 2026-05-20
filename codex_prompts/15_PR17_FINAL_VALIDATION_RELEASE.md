# Prompt Codex — PR17 final production validation and release checklist

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR16 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- configurer backup.conf ;
- configurer une target SFTP ;
- initialiser/checker un dépôt restic ;
- créer des profiles ;
- configurer des dumps DB ;
- lancer des backups réels ;
- appliquer la rétention/prune ;
- faire un restore test non destructif ;
- envoyer des rapports email ;
- faire un coverage audit ;
- produire des runbooks complets ;
- fournir un health check local ;
- fournir un operations status ;
- utiliser un timer systemd durci ;
- installer logrotate si disponible.

État réel validé :
- target nas-steph OK ;
- WireGuard + SFTP OK ;
- repo restic OK ;
- backup réel OK ;
- DB dump PostgreSQL Docker OK ;
- prune OK ;
- restore test OK ;
- email reports OK ;
- coverage audit SUCCESS ;
- health OK avec un seul warning attendu : timer disabled ;
- operations status OK ;
- systemd unit validée ;
- logrotate installé.

Objectif de cette PR :

Implémenter uniquement :

PR17 — final production validation and release checklist

Objectif :
- ajouter une procédure de validation finale v1.0 ;
- ajouter une checklist release ;
- ajouter une commande optionnelle de validation end-to-end non destructive ;
- documenter l’activation finale du timer ;
- préparer une première release stable ;
- ne pas ajouter de nouvelle fonctionnalité risquée ;
- ne pas lancer automatiquement de backup pendant install.

Ne pas implémenter :
- nouveau backend ;
- restore destructif ;
- auto-remédiation ;
- monitoring externe ;
- UI web ;
- orchestration disaster recovery.

Livrables attendus :

1. Ajouter docs/FINAL_VALIDATION.md

Ce document doit contenir une procédure complète de validation finale :

- vérifier config :
  sudo server-backup config validate

- vérifier health :
  sudo server-backup health

- vérifier operations status :
  sudo server-backup operations status

- vérifier target :
  sudo server-backup target test <target>

- vérifier repo :
  sudo server-backup repo snapshots <target>
  sudo server-backup repo check <target>

- vérifier DB :
  sudo server-backup db list
  sudo server-backup db test <name>
  sudo server-backup db dump-test <name>

- vérifier coverage :
  sudo server-backup coverage audit
  sudo server-backup docker coverage

- vérifier backup :
  sudo server-backup backup run --dry-run --target <target> --profile <profile>
  sudo server-backup backup run --target <target> --profile <profile>

- vérifier prune :
  sudo server-backup repo prune <target> --dry-run

- vérifier restore :
  sudo server-backup restore test --target <target> --keep-output

- vérifier email :
  sudo server-backup email test

- vérifier timer :
  systemctl status server-backup.timer
  systemctl list-timers | grep server-backup

- activer timer :
  sudo systemctl enable --now server-backup.timer

2. Ajouter docs/RELEASE_CHECKLIST.md

Checklist v1.0 :

- [ ] config validate OK
- [ ] health OK ou warnings acceptés
- [ ] target test OK
- [ ] repo check OK
- [ ] DB test OK
- [ ] DB dump-test OK
- [ ] coverage audit SUCCESS
- [ ] backup dry-run OK
- [ ] backup réel OK
- [ ] repo snapshots montre le snapshot
- [ ] repo check après backup OK
- [ ] prune dry-run OK
- [ ] restore test OK
- [ ] email test reçu
- [ ] timer activé
- [ ] restore kit stocké hors serveur
- [ ] mot de passe restic stocké hors serveur
- [ ] accès NAS documenté
- [ ] accès WireGuard documenté
- [ ] secrets DB documentés hors Git
- [ ] runbooks présents
- [ ] aucun secret dans le repo

3. Ajouter commande optionnelle :

sudo server-backup validate production

Cette commande doit rester non destructive par défaut.

Elle peut exécuter uniquement des checks non destructifs :

- config validate
- health
- operations status
- coverage audit
- repo snapshots
- repo check
- db list
- db test si disponible
- email test seulement avec option explicite --email-test
- restore test seulement avec option explicite --restore-test
- backup dry-run seulement avec option explicite --backup-dry-run

Options :

sudo server-backup validate production
sudo server-backup validate production --target <target>
sudo server-backup validate production --profile <profile>
sudo server-backup validate production --email-test
sudo server-backup validate production --restore-test
sudo server-backup validate production --backup-dry-run

Ne pas lancer de backup réel.
Ne pas lancer prune réel.
Ne pas activer le timer.
Ne pas modifier la configuration.

La commande doit produire un résumé SUCCESS/WARNING/FAILURE.

4. Ajouter server_backup/validation.py

Fonctions possibles :

- run_production_validation(...)
- check_config_validate()
- check_health()
- check_operations_status()
- check_repo_snapshots()
- check_repo_check()
- check_db_list()
- check_db_tests()
- check_coverage_audit()
- maybe_email_test()
- maybe_restore_test()
- maybe_backup_dry_run()
- render_validation_report_text()
- render_validation_report_json()
- write_validation_report()

Rapports :

/var/lib/server-backup/reports/production-validation-YYYYMMDD-HHMMSS.txt
/var/lib/server-backup/reports/production-validation-YYYYMMDD-HHMMSS.json

State :

/var/lib/server-backup/state/last-production-validation.json

5. Status

server-backup status doit afficher si présent :

- last production validation date
- last production validation status
- report path

Ne pas lancer validation automatiquement.

6. Tests unitaires

Ajouter :

tests/test_validation.py
tests/test_validation_cli.py

Tester avec mocks :
- validation sans options ne lance pas email/restore/backup
- validation avec --email-test appelle email test
- validation avec --restore-test appelle restore test
- validation avec --backup-dry-run appelle backup dry-run
- rapport texte/json écrit
- status lit last-production-validation
- aucun secret affiché

7. Documentation

Mettre à jour :

docs/DEPLOYMENT_RUNBOOK.md
- ajouter PR17 validation finale ;
- ajouter quand lancer validate production ;
- ajouter activation timer après validation.

docs/OPERATIONS_RUNBOOK.md
- ajouter validate production ;
- ajouter routine de release.

docs/SCHEDULING_POLICY.md
- ajouter activation finale du timer.

README.md
- ajouter lien vers FINAL_VALIDATION.md et RELEASE_CHECKLIST.md.

8. Critères d’acceptation

- tests unitaires OK ;
- server-backup validate production --help fonctionne ;
- validate production fonctionne sans action destructive ;
- rapport validation généré ;
- last-production-validation.json généré ;
- status affiche la dernière validation ;
- aucune commande destructive n’est lancée ;
- aucun backup réel n’est lancé ;
- aucun prune réel n’est lancé ;
- timer non activé automatiquement ;
- docs finales présentes ;
- checklist v1.0 présente.

Tests à exécuter :

python3 -m unittest discover -s tests
python3 -m server_backup.cli validate --help
python3 -m server_backup.cli validate production --help
sudo ./scripts/install.sh
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis --backup-dry-run
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis --restore-test
sudo server-backup status

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- commandes de test exécutées ;
- résultats des tests ;
- rapport de validation généré ;
- statut final ;
- actions manuelles restantes avant v1.0 ;
- recommandation sur activation timer.

Prochaine étape après PR17 :
- activer le timer systemd ;
- tagger une version v1.0 si tout est validé.
```
