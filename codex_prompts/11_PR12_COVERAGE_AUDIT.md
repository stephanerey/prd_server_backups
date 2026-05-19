# Prompt Codex — PR12 coverage audit minimal

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR11 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- générer backup.conf ;
- générer une target SFTP ;
- tester SSH/SFTP ;
- générer des profiles ;
- initialiser/checker un dépôt restic ;
- créer un vrai snapshot restic via backup run ;
- appliquer la rétention avec repo prune ;
- faire un restore test non destructif ;
- envoyer des rapports email via sendmail/mail ;
- générer des rapports locaux backup/prune/restore/email ;
- utiliser un lock local partagé entre repo, backup, prune et restore.

État réel validé :
- target : nas-steph
- target test : OK
- repo init : OK
- repo check : OK
- snapshot réel existant : df472f9c
- backup run : OK
- prune : OK
- restore test : OK avec warning attendu
- email test --to root@localhost : OK
- rapports locaux : OK
- lock restic local : OK

Objectif de cette PR :

Implémenter uniquement :

PR12 — coverage audit minimal

Objectif :
- détecter les problèmes évidents de couverture backup ;
- générer un rapport local coverage audit texte et JSON ;
- détecter targets/profiles incomplets ;
- détecter profiles sans chemins valides ;
- détecter chemins BACKUP_PATHS absents ;
- détecter fichiers .env non couverts dans les projets Docker ;
- détecter volumes Docker ou bind mounts non couverts, si Docker est disponible ;
- détecter cis-site sans DATABASE_DUMPS configuré ;
- détecter cis-site sans CONTENT_CLASSIFICATION ;
- détecter cis-site sans frontend/backend/migrations couverts ;
- ne pas modifier la configuration ;
- ne pas faire de correction automatique ;
- ne pas lancer de backup ;
- ne pas contacter le NAS ;
- ne pas exécuter restic.

Ne pas implémenter encore :
- correction automatique des profiles ;
- modification des fichiers .conf ;
- scan Docker avancé profond ;
- DB dump réel ;
- test de connexion DB ;
- restore DB ;
- disaster restore.

Contraintes générales :
- pas de dépendance Python externe ;
- ne jamais afficher de secrets ;
- ne jamais afficher le contenu de fichiers .env ;
- ne jamais afficher RESTIC_PASSWORD_FILE ;
- ne jamais afficher les clés SSH ;
- ne pas contacter le NAS ;
- ne pas lancer restic ;
- ne pas lancer docker compose ;
- ne pas modifier la production ;
- comportement clair et idempotent ;
- compatible Debian/Ubuntu.

Commandes à implémenter :

sudo server-backup coverage audit
sudo server-backup coverage audit --json
sudo server-backup coverage audit --profile <profile>
sudo server-backup coverage audit --output-dir <path>

Comportement :
- charger backup.conf ;
- charger targets ;
- charger profiles ;
- inspecter localement les fichiers et chemins ;
- si Docker est disponible, inspecter localement docker ps / docker volume ls / docker inspect ;
- générer un rapport texte et JSON sous /var/lib/server-backup/reports ;
- mettre à jour /var/lib/server-backup/state/last-coverage-audit.json ;
- retourner code 0 si success ou warning seulement ;
- retourner code non nul si failure critique.

Livrables attendus :

1. Ajouter server_backup/coverage.py

Fonctions attendues :
- run_coverage_audit(profile_name=None, output_dir=None)
- collect_targets_coverage(global_config, targets)
- collect_profiles_coverage(global_config, profiles)
- check_backup_paths(profile)
- check_profile_excludes(profile)
- check_docker_availability()
- collect_docker_inventory_light()
- collect_docker_mounts()
- check_docker_mount_coverage(profiles, docker_mounts)
- discover_compose_files(search_paths)
- check_env_files_coverage(profiles, compose_files)
- check_cis_site_coverage(profile)
- classify_finding(severity, code, message, details=None)
- render_coverage_report_text(report)
- render_coverage_report_json(report)
- write_coverage_report(report, report_dir)
- update_last_coverage_audit(report)

2. Sévérités

Utiliser trois niveaux :
- SUCCESS
- WARNING
- FAILURE

Exemples FAILURE :
- aucune target configurée ;
- aucun profile configuré ;
- profile sans BACKUP_PATHS ;
- profile dont aucun BACKUP_PATH n’existe ;
- target invalide selon validate_target_config.

Exemples WARNING :
- chemin BACKUP_PATH absent ;
- Docker installé mais certains volumes/bind mounts ne sont pas couverts ;
- fichier .env détecté mais pas couvert ;
- cis-site sans CONTENT_CLASSIFICATION ;
- cis-site sans frontend/backend détecté ;
- restore test jamais exécuté ;
- backup run jamais exécuté ;
- email automatique désactivé.

3. Checks génériques

Vérifier :
- backup.conf existe ;
- au moins une target ;
- au moins un profile ;
- RESTIC_PASSWORD_FILE existe ;
- RESTIC_CACHE_DIR existe ;
- chaque target est valide localement ;
- chaque profile est valide localement ;
- chaque BACKUP_PATH existe ou warning ;
- au moins un BACKUP_PATH existant par profile.

Ne pas contacter le NAS.
Ne pas lancer restic.
Ne pas exécuter target test.

4. Checks Docker minimaux

Si docker est disponible :
- docker ps --format json si supporté, sinon format texte stable ;
- docker volume ls ;
- docker inspect pour conteneurs actifs.

Si docker absent :
- warning informatif seulement si un profile docker-host/docker-app/cis-site existe ;
- pas de failure.

Collecter :
- conteneurs actifs ;
- noms ;
- mounts ;
- bind mounts ;
- volumes nommés.

Comparer mounts avec BACKUP_PATHS existants.

Warning si :
- bind mount détecté mais non inclus dans aucun BACKUP_PATH ;
- volume Docker détecté mais chemin /var/lib/docker/volumes/<name>/_data non inclus ;
- conteneur actif sans chemin Compose retrouvé.

Ne pas lancer docker compose.
Ne pas modifier Docker.

5. Checks Compose et .env

Rechercher compose files dans les chemins des profiles :
- compose.yml
- compose.yaml
- docker-compose.yml
- docker-compose.yaml
- docker-compose.override.yml

Pour chaque compose file trouvé :
- vérifier si le répertoire parent est couvert ;
- rechercher .env dans le même répertoire ;
- si .env existe et n’est pas dans un BACKUP_PATH couvert, warning ;
- ne jamais afficher le contenu du .env.

6. Checks cis-site

Pour profile avec :
- PROFILE_TYPE="cis-site"
- ou APP_KIND="cis-site"
- ou WEB_CONTENT_CRITICAL="true"

Vérifier :
- WEB_CONTENT_CRITICAL présent ;
- CONTENT_CLASSIFICATION présent ;
- DATABASE_DUMPS présent ou warning ;
- BACKUP_PATHS contient un chemin frontend probable ;
- BACKUP_PATHS contient un chemin backend probable ;
- chemin migrations probable couvert : alembic ou migrations ;
- chemins media/uploads/assets classifiés ou warning ;
- table site_pages ou autre table de pages mentionnée dans CONTENT_CLASSIFICATION si possible.

Ne pas se connecter à PostgreSQL.
Ne pas vérifier réellement la table en DB dans cette PR.

7. Rapport local

Créer :

/var/lib/server-backup/reports/coverage-audit-YYYYMMDD-HHMMSS.txt
/var/lib/server-backup/reports/coverage-audit-YYYYMMDD-HHMMSS.json

Mettre à jour :

/var/lib/server-backup/state/last-coverage-audit.json

Contenu rapport :
- hostname ;
- BACKUP_NAME ;
- start time ;
- end time ;
- duration ;
- global status ;
- nombre targets ;
- nombre profiles ;
- findings par severity ;
- findings par profile ;
- findings Docker ;
- findings CIS ;
- recommandations ;
- chemins des rapports.

Ne jamais inclure :
- contenu .env ;
- mots de passe ;
- clés SSH ;
- tokens ;
- secrets.

8. Status

server-backup status doit afficher si présent :
- last coverage audit date ;
- last coverage audit status ;
- last coverage audit report path.

Ne pas lancer l’audit depuis status.

9. CLI

Mettre à jour server_backup/cli.py :

Ajouter :

server-backup coverage audit

Options :
- --json : affiche aussi le JSON ou chemin JSON ;
- --profile <profile> : limite à un profile ;
- --output-dir <path> : répertoire de rapport alternatif.

Si --output-dir est fourni :
- créer si absent ;
- refuser chemins dangereux type /, /etc, /srv, /opt, /var/lib/docker ;
- conserver permissions prudentes.

10. Tests unitaires

Ajouter :
- tests/test_coverage_helpers.py
- tests/test_coverage_cli.py

Utiliser unittest.mock.
Ne pas dépendre de Docker réel.

Tester :
- profile sans BACKUP_PATHS => failure ;
- profile avec chemin absent => warning ;
- profile avec tous chemins absents => failure ;
- target absente => failure ;
- cis-site sans DATABASE_DUMPS => warning ;
- cis-site sans CONTENT_CLASSIFICATION => warning ;
- docker mount non couvert => warning ;
- .env détecté non couvert => warning ;
- rapport texte/json généré ;
- last-coverage-audit.json généré ;
- secrets redacted ;
- status lit last-coverage-audit sans lancer audit.

11. Tests manuels

Exécuter :
- python3 -m unittest discover -s tests
- python3 -m server_backup.cli coverage --help
- python3 -m server_backup.cli coverage audit --help
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup coverage audit
- sudo server-backup status

Si Docker est disponible sur le VPS :
- vérifier que l’audit détecte les conteneurs/mounts ;
- ne pas modifier Docker ;
- ne pas lancer docker compose.

12. Documentation

Mettre à jour docs/SERVER_INSTALL.md :
- lancer coverage audit après création des profiles ;
- lire les warnings ;
- corriger les profiles manuellement.

Mettre à jour docs/CONFIG_REFERENCE.md :
- last-coverage-audit.json ;
- coverage-audit-*.txt/json.

Ajouter docs/COVERAGE_AUDIT.md :
- objectif ;
- commandes ;
- niveaux SUCCESS/WARNING/FAILURE ;
- checks génériques ;
- checks Docker ;
- checks CIS ;
- limites ;
- pas de modification automatique ;
- pas de contact NAS ;
- pas de secret affiché.

Mettre à jour README.md avec une courte section coverage audit.

13. Critères d’acceptation

- tests unitaires OK ;
- server-backup coverage audit fonctionne ;
- rapport texte généré ;
- rapport JSON généré ;
- last-coverage-audit.json généré ;
- status affiche le dernier coverage audit ;
- aucune valeur sensible affichée ;
- aucun fichier .env lu ou affiché ;
- aucun restic lancé ;
- aucun NAS contacté ;
- aucun docker compose lancé ;
- aucun fichier de configuration modifié ;
- warnings pertinents si profile incomplet ;
- warnings pertinents si cis-site sans DB dump.

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- commandes de test exécutées ;
- résultats des tests ;
- statut global du coverage audit réel ;
- principaux warnings détectés ;
- rapports générés ;
- limites restantes ;
- prochaine PR recommandée.

Prochaine PR recommandée après celle-ci :

PR13 — DB wizard and dump support

Objectif PR13 :
- implémenter server-backup db add ;
- configurer PostgreSQL local/Docker/remote ;
- configurer secrets DB root-only ;
- générer DATABASE_DUMPS ;
- exécuter dumps logiques pendant backup run ;
- ne jamais exposer les mots de passe.
```
