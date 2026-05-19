# Prompt Codex — PR9 rétention et prune

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR8 sont terminées.

Le système sait maintenant :
- installer le socle host-level
- générer backup.conf
- générer une target SFTP
- tester SSH/SFTP
- générer des profiles
- initialiser/checker un dépôt restic
- créer un vrai snapshot restic via backup run
- générer des rapports locaux
- utiliser un lock local partagé entre repo et backup

État réel validé :
- target : nas-steph
- target test : OK
- repo init : OK
- repo check : OK
- premier snapshot réel créé : df472f9c
- backup run : OK
- rapports locaux : OK
- lock restic local : OK

Objectif de cette PR :

Implémenter uniquement :

PR9 — rétention et prune

Objectif :
- implémenter la rétention restic avec forget/prune
- utiliser les valeurs de backup.conf :
  - RETENTION_DAILY
  - RETENTION_WEEKLY
  - RETENTION_MONTHLY
- appliquer la rétention par target
- supporter une commande dry-run
- afficher clairement ce qui serait supprimé avant toute action destructive
- utiliser le verrou restic local existant
- générer un rapport local prune
- ne pas encore gérer DB dumps
- ne pas encore gérer coverage audit
- ne pas encore gérer restore test
- ne pas encore envoyer d’email réel

Ne pas implémenter encore :
- dumps PostgreSQL/MariaDB/MySQL
- coverage audit réel
- restore test
- email réel
- orchestration disaster restore

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

Commandes à implémenter :

sudo server-backup repo prune <target>
sudo server-backup repo prune --all
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune --all --dry-run

Optionnel si plus cohérent côté CLI :

sudo server-backup backup prune <target>
sudo server-backup backup prune --all

Mais conserver au minimum :

sudo server-backup repo prune

Comportement attendu :

1. En dry-run :
- exécuter restic forget avec --dry-run
- ne rien supprimer
- afficher ce qui serait supprimé
- générer un rapport local

2. En réel :
- exécuter restic forget avec :
  --keep-daily RETENTION_DAILY
  --keep-weekly RETENTION_WEEKLY
  --keep-monthly RETENTION_MONTHLY
  --prune
- afficher clairement que c’est une opération destructive
- demander confirmation interactive sauf option explicite --yes
- générer un rapport local

Commande restic attendue :

restic forget \
  --keep-daily <RETENTION_DAILY> \
  --keep-weekly <RETENTION_WEEKLY> \
  --keep-monthly <RETENTION_MONTHLY> \
  --prune

Dry-run :

restic forget \
  --keep-daily <RETENTION_DAILY> \
  --keep-weekly <RETENTION_WEEKLY> \
  --keep-monthly <RETENTION_MONTHLY> \
  --dry-run

Important :
- ne pas utiliser --prune avec --dry-run si restic ne le supporte pas correctement
- vérifier le comportement réel de restic utilisé dans les tests
- si besoin, documenter la différence entre dry-run et prune réel

Livrables attendus :

1. Compléter server_backup/restic.py

Ajouter fonctions :

- build_forget_args(global_config, dry_run=False)
- prune_repository(target, global_config, dry_run=False, yes=False)
- prune_all_repositories(global_config, targets, dry_run=False, yes=False)
- validate_retention_config(global_config)
- parse_retention_values(global_config)

Réutiliser :
- validate_restic_preflight()
- build_restic_env()
- run_restic_command()
- restic_repo_lock()

2. Mettre à jour server_backup/cli.py

Ajouter commande :

server-backup repo prune

Options :
- target positional optionnel
- --all
- --dry-run
- --yes

Exemples :

sudo server-backup repo prune nas-steph --dry-run
sudo server-backup repo prune nas-steph --yes
sudo server-backup repo prune --all --dry-run
sudo server-backup repo prune --all --yes

Règles :
- target ou --all obligatoire
- si ni target ni --all : afficher aide et code non nul
- si target inconnue : erreur claire
- si aucune target : erreur claire
- --dry-run ne demande pas confirmation
- prune réel sans --yes demande confirmation interactive
- si confirmation refusée : aucune action, code 0 ou code spécifique documenté

3. Validation rétention

Valider :
- RETENTION_DAILY entier positif ou zéro
- RETENTION_WEEKLY entier positif ou zéro
- RETENTION_MONTHLY entier positif ou zéro
- au moins une valeur > 0

Si valeurs invalides :
- erreur claire
- ne pas lancer restic

4. Lock

Le lock restic local doit couvrir toute l’opération prune.

Si lock déjà pris :
- message clair
- code non nul
- ne pas lancer restic

5. Rapports locaux

Créer des rapports sous :

/var/lib/server-backup/reports

Fichiers :

prune-run-YYYYMMDD-HHMMSS.txt
prune-run-YYYYMMDD-HHMMSS.json

Contenu :
- hostname
- BACKUP_NAME
- start time
- end time
- duration
- dry_run true/false
- target(s)
- retention daily/weekly/monthly
- commande restic résumée sans secrets
- stdout/stderr filtrés
- status success/warning/failure
- warnings
- errors

Mettre à jour :

/var/lib/server-backup/state/last-prune-run.json

6. Status

server-backup status doit afficher si présent :
- last prune run date
- last prune status
- last prune report path

Ne pas contacter le NAS.

7. Tests unitaires

Ajouter ou compléter :

- tests/test_prune_helpers.py
- tests/test_prune_cli.py

Tester :
- build_forget_args
- build_forget_args dry-run
- valeurs de rétention valides
- valeurs invalides
- target obligatoire ou --all
- --dry-run ne demande pas confirmation
- prune réel sans --yes demande confirmation
- rapport prune texte/json
- last-prune-run.json
- lock utilisé
- secrets redacted

Ne pas lancer de vrai restic dans les tests unitaires.

Utiliser unittest.mock.

8. Tests manuels

Avec la vraie target nas-steph :

Exécuter :

python3 -m unittest discover -s tests
python3 -m server_backup.cli repo --help
sudo ./scripts/install.sh
sudo server-backup status
sudo server-backup config validate
sudo server-backup repo snapshots nas-steph
sudo server-backup repo prune nas-steph --dry-run
sudo server-backup repo prune nas-steph --yes
sudo server-backup repo check nas-steph
sudo server-backup repo snapshots nas-steph

Important :
- comme il n’y a probablement qu’un snapshot, prune réel ne devrait normalement rien supprimer
- ne pas inventer de suppression
- reporter précisément la sortie restic

9. Documentation

Mettre à jour :

docs/RESTIC_REPOSITORIES.md

Ajouter :
- repo prune
- dry-run
- --yes
- rétention daily/weekly/monthly
- différence forget et prune
- rapport local prune
- sécurité opération destructive

Mettre à jour :

docs/SERVER_INSTALL.md

Ajouter étape après premier backup :
- vérifier snapshots
- lancer prune dry-run
- lancer prune réel si nécessaire

Mettre à jour :

docs/CONFIG_REFERENCE.md

Documenter :
- RETENTION_DAILY
- RETENTION_WEEKLY
- RETENTION_MONTHLY
- last-prune-run.json
- prune-run-*.txt/json

Ajouter si pertinent :

docs/RETENTION_POLICY.md

Décrire :
- politique par défaut 14 daily / 8 weekly / 12 monthly
- impact stockage
- dry-run obligatoire avant premier prune réel
- différence backup provider vs rétention restic

10. Critères d’acceptation

- tests unitaires OK
- server-backup repo prune --help fonctionne
- prune dry-run fonctionne sur nas-steph
- prune réel avec --yes fonctionne sur nas-steph
- prune réel sans --yes demande confirmation
- aucune valeur sensible affichée
- rapports prune texte/json générés
- last-prune-run.json généré
- status affiche le dernier prune run
- lock empêche prune pendant backup/repo et inversement
- repo check OK après prune
- aucun dump DB lancé
- aucun email réel envoyé
- aucun restore test lancé

À la fin, fournir :
- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- résultat du prune dry-run
- résultat du prune réel
- rapport généré
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR10 — restore test non destructif

Objectif PR10 :
- restaurer latest dans /tmp/server-backup-restore-test-*
- vérifier fichiers restaurés
- vérifier dumps DB si présents plus tard
- générer rapport restore-test
- mettre à jour last-restore-test.json
```
