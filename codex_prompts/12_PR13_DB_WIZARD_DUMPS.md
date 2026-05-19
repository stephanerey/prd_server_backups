# Prompt Codex — PR13 DB wizard and dump support

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte : PR1 à PR12 sont terminées. Le système sait installer le socle, configurer backup.conf, targets SFTP, profiles, restic repo, backup run, prune, restore test, email reports et coverage audit minimal.

Objectif : implémenter uniquement PR13 — DB wizard and dump support.

But :
- implémenter server-backup db add, db list, db test <name>, db dump-test <name> ;
- supporter PostgreSQL local/Docker/remote ;
- supporter MariaDB/MySQL local/Docker/remote si raisonnable ;
- stocker les secrets DB en root-only ;
- générer DATABASE_DUMPS dans les profiles ;
- tester connexion DB et dump temporaire ;
- intégrer les dumps DB dans backup run avant restic backup ;
- mettre à jour les rapports backup et coverage audit ;
- ne jamais exposer les mots de passe ;
- ne pas restaurer de DB dans cette PR.

Ne pas implémenter : restauration DB, disaster restore, correction automatique des profiles Docker, docker compose up, scan Docker profond.

Contraintes :
- pas de dépendance Python externe ;
- secrets jamais affichés ni committés ;
- ne jamais afficher PGPASSWORD, MYSQL_PWD, PASSWORD, SECRET, TOKEN, KEY ;
- secrets en 0600 root:root, dossiers secrets en 0700 root:root ;
- système host-level, pas Docker ;
- subprocess.run avec shell=False ;
- ne jamais mettre de mot de passe DB dans les arguments ;
- passer les secrets via env ou fichier protégé.

Important coverage audit : les volumes Docker associés à une DB doivent être considérés couverts principalement par un dump logique DB. Un volume DB brut peut rester optionnel. Ne coder en dur aucun nom de conteneur, volume ou application.

Commandes à implémenter :

sudo server-backup db add
sudo server-backup db add --profile <profile>
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db test --all
sudo server-backup db dump-test <name>
sudo server-backup db dump-test --all
sudo server-backup db dump-test <name> --keep-output

Format profile cible :

DATABASE_DUMPS=(
  "name=<name>;engine=postgresql;mode=docker;container=<container>;user=<db_user>;databases=<db_name>;globals=true;secret=/etc/server-backup/secrets/db/<profile>/<name>.env"
)

Exemples génériques :

PostgreSQL Docker :
DATABASE_DUMPS=(
  "name=app-postgres;engine=postgresql;mode=docker;container=postgres;user=app_user;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/app/postgres.env"
)

PostgreSQL local :
DATABASE_DUMPS=(
  "name=app-postgres-local;engine=postgresql;mode=local;host=localhost;port=5432;user=app_user;databases=appdb;globals=true;secret=/etc/server-backup/secrets/db/app/postgres-local.env"
)

MariaDB/MySQL local :
DATABASE_DUMPS=(
  "name=app-mysql;engine=mysql;mode=local;host=localhost;port=3306;user=app_user;databases=appdb;all=false;secret=/etc/server-backup/secrets/db/app/mysql.env"
)

Livrables code :

1. Ajouter server_backup/db.py avec notamment :
- parse_database_dump_spec
- render_database_dump_spec
- load_database_dumps_from_profiles
- select_database_dump
- list_database_dumps
- write_db_secret_file
- read_db_secret_file
- redact_db_config
- build_postgres_test_command
- build_postgres_dump_command
- build_postgres_globals_command
- build_mysql_test_command
- build_mysql_dump_command
- run_db_command
- test_database_connection
- run_dump_test
- run_database_dump
- update_profile_database_dumps
- discover_db_tools

2. Wizard db add : demander nom, profile, engine, mode, container/host/port, databases/all-databases, user, secret à créer/existant, test connexion, dump-test, ajout profile.

3. Secrets DB :
- chemin /etc/server-backup/secrets/db/<profile>/<name>.env ;
- PostgreSQL : PGPASSWORD="..." ;
- MySQL : MYSQL_PWD="..." ;
- créer en 0600 root:root sans écraser sans confirmation.

4. PostgreSQL Docker :
- test : docker exec -e PGPASSWORD="$PGPASSWORD" <container> psql --username=<user> --dbname=<database> --command="SELECT 1;"
- dump : docker exec -e PGPASSWORD="$PGPASSWORD" <container> pg_dump --username=<user> --format=custom --compress=0 <database> > <dump_file>
- globals : docker exec -e PGPASSWORD="$PGPASSWORD" <container> pg_dumpall --globals-only --username=<user> > <globals_file>

5. PostgreSQL local/remote : pg_dump/pg_dumpall avec PGPASSWORD via env.

6. MariaDB/MySQL : mariadb-dump avec --single-transaction --routines --triggers --events, fallback mysqldump. En Docker, utiliser docker exec -e MYSQL_PWD.

7. db list : lister dumps configurés sans afficher secrets.

8. db test : tester connexion, SELECT 1, code non nul si échec.

9. db dump-test : créer /var/tmp/server-backup/db-dump-test-*, produire dump non vide, pg_restore --list si possible, nettoyer sauf --keep-output.

10. Intégrer backup run : avant restic backup, exécuter DATABASE_DUMPS du profile, ajouter dossier temporaire de dumps aux chemins restic, nettoyer toujours, marquer failure si dump critique échoue, mentionner les dumps dans le rapport backup.

11. update_profile_database_dumps doit ajouter DATABASE_DUMPS sans casser BACKUP_PATHS/EXCLUDES/CONTENT_CLASSIFICATION et faire backup horodaté du profile.

12. Coverage audit : cis-site avec DATABASE_DUMPS ne doit plus warning DB dump absent. Si volume/conteneur DB détecté et dump logique présent, indiquer que le dump logique est la couverture principale et le volume brut optionnel.

13. Volumes applicatifs non-DB : ne pas les corriger en PR13 ; ils relèvent de PR14.

Tests unitaires : ajouter tests/test_db_helpers.py, tests/test_db_cli.py, tests/test_db_dump_integration.py avec unittest.mock. Tester parse/render DATABASE_DUMPS, permissions secrets, commandes sans password en args, update profile, db test inconnu, dump-test mock succès, dump failure empêche restic backup, rapport backup inclut dumps, secrets redacted, coverage audit avec/sans dump.

Tests manuels :
- python3 -m unittest discover -s tests
- python3 -m server_backup.cli db --help
- python3 -m server_backup.cli db add --help
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup db add
- sudo server-backup db list
- sudo server-backup db test <name>
- sudo server-backup db dump-test <name>
- sudo server-backup coverage audit

Si DB configurée :
- sudo server-backup backup run --dry-run --target nas-steph
- sudo server-backup backup run --target nas-steph --profile <profile-with-db>
- sudo server-backup repo snapshots nas-steph
- sudo server-backup repo check nas-steph

Docs à mettre à jour :
- docs/SERVER_INSTALL.md : db add après profiles, db test, dump-test, dump logique prioritaire sur volume DB brut.
- docs/CONFIG_REFERENCE.md : DATABASE_DUMPS, secrets DB, champs engine/mode/container/user/databases/globals/secret.
- docs/BACKUP_RUN.md : dumps avant restic, nettoyage temporaire, échec dump.
- docs/COVERAGE_AUDIT.md : volume DB vs dump logique.
- ajouter docs/DATABASE_DUMPS.md.

Critères d’acceptation :
- tests unitaires OK ;
- server-backup db --help fonctionne ;
- db add fonctionne ;
- secret DB créé en 0600 root:root ;
- DATABASE_DUMPS ajouté au profile ;
- db list fonctionne ;
- db test fonctionne si credentials corrects ;
- db dump-test produit un fichier non vide ;
- backup run intègre les dumps dans restic ;
- rapport backup mentionne les dumps ;
- coverage audit ne signale plus cis-site sans DB dump si DATABASE_DUMPS est configuré ;
- aucun mot de passe affiché ou présent dans les arguments ;
- aucun secret commité ;
- dumps temporaires nettoyés.

À la fin, fournir résumé, tests, DATABASE_DUMPS créé sans secret, db list, db test, dump-test, backup run avec dump, coverage audit après DB dump, limites restantes, prochaine PR recommandée.

Prochaine PR recommandée :

PR14 — Docker profile coverage refinements
- améliorer la couverture Docker ;
- aider à ajouter les volumes non couverts à un profile ;
- améliorer la détection Compose ;
- traiter les volumes applicatifs non-DB ;
- ne pas modifier automatiquement sans confirmation.
```
