# Prompt Codex — PR14 Docker profile coverage refinements

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR13 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- générer backup.conf ;
- générer une target SFTP ;
- tester SSH/SFTP ;
- générer des profiles ;
- initialiser/checker un dépôt restic ;
- créer de vrais snapshots restic via backup run ;
- appliquer la rétention avec repo prune ;
- faire un restore test non destructif ;
- envoyer des rapports email via sendmail/mail ;
- faire un coverage audit minimal ;
- configurer des dumps DB logiques ;
- exécuter les dumps DB avant restic backup ;
- intégrer les dumps DB dans les rapports backup ;
- reconnaître qu’un volume DB est couvert principalement par un dump logique ;
- utiliser un lock local partagé entre repo, backup, prune, restore et DB dumps.

État réel validé :
- target : nas-steph
- target test : OK
- repo check : OK
- snapshots existants : df472f9c, febc4230, c6598564 ;
- DB dump PostgreSQL Docker : OK ;
- db test pilot-postgres : OK ;
- db dump-test pilot-postgres : OK ;
- backup run avec dump DB : OK ;
- coverage audit après correction profile : SUCCESS ;
- volumes Caddy ajoutés manuellement au profile mes-fragrances-cis ;
- dump PostgreSQL logique configuré dans DATABASE_DUMPS ;
- repo check après backup : OK.

Objectif de cette PR :

Implémenter uniquement :

PR14 — Docker profile coverage refinements

Objectif :
- améliorer la couverture Docker ;
- aider l’opérateur à détecter les volumes Docker et bind mounts non couverts ;
- aider l’opérateur à ajouter les volumes/bind mounts manquants dans des profiles ;
- améliorer la détection Compose ;
- améliorer la détection .env sans jamais lire leur contenu ;
- améliorer les recommandations de coverage audit ;
- proposer des corrections sans les appliquer automatiquement par défaut ;
- permettre une commande interactive pour ajouter des chemins Docker manquants à un profile ;
- ne pas faire de correction silencieuse ;
- ne pas lancer de backup réel ;
- ne pas modifier Docker ;
- ne pas lancer docker compose ;
- ne pas restaurer de données.

Ne pas implémenter encore :
- correction automatique sans confirmation ;
- restore Docker ;
- docker compose up ;
- migration de volumes ;
- suppression de volumes ;
- modification de conteneurs ;
- modification de compose.yml ;
- orchestration disaster restore.

Contraintes générales :
- pas de dépendance Python externe ;
- ne jamais afficher de secrets ;
- ne jamais lire ou afficher le contenu des fichiers .env ;
- ne jamais modifier Docker ;
- ne jamais lancer docker compose ;
- ne jamais modifier les profiles sans confirmation explicite ;
- faire un backup horodaté de tout profile modifié ;
- fichiers profiles en 0600 root:root ;
- comportement idempotent ;
- compatible Debian/Ubuntu ;
- système host-level, pas Docker ;
- utiliser subprocess.run avec shell=False.

Commandes à implémenter ou améliorer :

sudo server-backup docker scan
sudo server-backup docker inventory
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
sudo server-backup docker add-missing-paths --profile <profile>
sudo server-backup docker add-missing-paths --profile <profile> --dry-run
sudo server-backup docker add-missing-paths --profile <profile> --volume <volume-name>
sudo server-backup docker add-missing-paths --profile <profile> --all-volumes

Si certaines commandes existent déjà en stub, les remplacer par une implémentation réelle minimale.

1. Ajouter ou compléter server_backup/docker.py

Créer un module dédié Docker si absent.

Fonctions attendues :
- docker_available()
- run_docker_command(args, timeout=None)
- list_containers()
- inspect_container(container_id_or_name)
- list_volumes()
- inspect_volume(volume_name)
- collect_container_mounts()
- collect_named_volumes()
- collect_bind_mounts()
- discover_compose_files(search_paths)
- discover_env_files_near_compose(compose_files)
- classify_docker_mount(mount)
- docker_volume_data_path(volume_name)
- compare_mounts_to_backup_paths(mounts, profiles)
- suggest_missing_docker_paths(profiles, mounts)
- render_docker_inventory_text(inventory)
- render_docker_inventory_json(inventory)
- write_docker_inventory(inventory, state_dir)
- update_profile_backup_paths(profile_path, paths_to_add)
- backup_profile_file(profile_path)

Utiliser uniquement standard library et commande docker CLI.

2. Docker scan

Commande :

sudo server-backup docker scan

Elle doit :
- vérifier si Docker est disponible ;
- lister les conteneurs actifs ;
- lister les volumes ;
- lister les bind mounts ;
- chercher les fichiers Compose dans les chemins connus des profiles : /srv, /opt, /home, BACKUP_PATHS existants ;
- afficher un résumé sans secret ;
- ne pas lire les fichiers .env ;
- ne rien modifier.

3. Docker inventory

Commande :

sudo server-backup docker inventory

Elle doit générer un inventaire local sous /var/lib/server-backup/state :
- docker-inventory-YYYYMMDD-HHMMSS.txt
- docker-inventory-YYYYMMDD-HHMMSS.json

Inclure date, hostname, version Docker, conteneurs, images, volumes, networks, mounts, ports, labels Compose, chemins Compose détectés et chemins .env détectés sans contenu.

Ne jamais inclure variables d’environnement sensibles, contenu .env, secrets, tokens, passwords.

4. Docker coverage

Commande :

sudo server-backup docker coverage

Elle doit comparer les mounts Docker détectés avec les BACKUP_PATHS des profiles et afficher volumes/bind mounts/Compose/.env couverts ou non couverts. Ne rien modifier.

5. Suggestions de correction

Commande :

sudo server-backup docker suggest-profile-updates

Elle doit analyser les volumes/bind mounts manquants, proposer à quel profile les ajouter, ne rien modifier et afficher des commandes suggérées.

Critères de suggestion :
- volumes liés à reverse proxy/caddy/nginx/traefik → profile docker-host ou cis-site selon contexte ;
- volumes liés à DB → ne pas ajouter automatiquement ; rappeler qu’un dump logique DB est prioritaire ;
- bind mounts sous /srv/<app> ou /home/<user>/<app> → profile docker-app ou cis-site si présent ;
- volumes inconnus → proposer profile docker-host par défaut, mais demander confirmation.

6. Add missing paths

Commande :

sudo server-backup docker add-missing-paths --profile <profile>

Elle doit afficher les chemins candidats, demander confirmation chemin par chemin, ajouter les chemins confirmés à BACKUP_PATHS, faire un backup horodaté du profile, préserver BACKUP_PATHS, EXCLUDES, DATABASE_DUMPS, CONTENT_CLASSIFICATION, éviter les doublons, écrire en 0600 root:root et relancer validation locale.

Options :
- --dry-run : afficher sans modifier ;
- --volume <volume-name> : proposer uniquement ce volume ;
- --all-volumes : proposer tous les volumes non couverts, mais demander confirmation.

Ne pas ajouter automatiquement les volumes DB si un dump logique existe. Afficher :
"This looks like a database volume. A logical DATABASE_DUMPS entry is preferred. Raw volume backup is optional."

7. Mise à jour coverage audit

Améliorer server_backup/coverage.py pour réutiliser les helpers Docker, afficher des recommandations plus précises et distinguer :
- volume DB non couvert sans dump logique : warning fort ;
- volume DB non couvert avec dump logique : warning faible ou info ;
- volume applicatif non-DB non couvert : warning ;
- volume reverse proxy non couvert : warning.

Ne jamais coder en dur des noms de projet spécifiques.

Heuristiques DB : nom contenant postgres, postgresql, pgdata, mysql, mariadb, db, database ; mount path contenant /var/lib/postgresql, /var/lib/mysql, /var/lib/mariadb ; image contenant postgres, mysql, mariadb.

Heuristiques reverse proxy : nom/image contenant caddy, nginx, traefik ; mount path contenant /data, /config, /etc/caddy, /etc/nginx.

8. Cas réel à valider sans coder en dur

Le coverage audit réel a déjà détecté des volumes applicatifs non-DB non couverts, puis ils ont été ajoutés manuellement au profile mes-fragrances-cis.

PR14 doit rendre cette opération assistée et reproductible pour les prochains serveurs, sans coder les noms spécifiques dans le code.

Après PR14, l’opérateur doit pouvoir faire :

sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
sudo server-backup docker add-missing-paths --profile <profile>
sudo server-backup coverage audit

et vérifier que les warnings volumes applicatifs non-DB disparaissent si les chemins ont été ajoutés.

9. Tests unitaires

Ajouter :
- tests/test_docker_helpers.py
- tests/test_docker_cli.py
- tests/test_docker_profile_updates.py

Utiliser unittest.mock. Ne pas dépendre de Docker réel.

Tester docker_volume_data_path, classification volume DB/reverse proxy/bind mount, comparaison mounts vs BACKUP_PATHS, volume couvert/non couvert, update_profile_backup_paths sans doublon et en préservant EXCLUDES/DATABASE_DUMPS/CONTENT_CLASSIFICATION, dry-run, volume DB avec/sans dump logique, .env détecté sans contenu.

10. Tests manuels

Exécuter :
- python3 -m unittest discover -s tests
- python3 -m server_backup.cli docker --help
- python3 -m server_backup.cli docker scan --help
- python3 -m server_backup.cli docker coverage --help
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup docker scan
- sudo server-backup docker inventory
- sudo server-backup docker coverage
- sudo server-backup docker suggest-profile-updates
- sudo server-backup docker add-missing-paths --profile <profile> --dry-run
- sudo server-backup coverage audit

Si possible, tester une vraie correction avec confirmation sur un profile non critique ou après backup du profile. Ne pas lancer de backup réel sauf validation explicite.

11. Documentation

Mettre à jour :
- docs/COVERAGE_AUDIT.md : volumes Docker couverts/non couverts, volume DB vs dump logique, reverse proxy volumes, suggestions.
- docs/PROFILES.md : ajouter volumes Docker à BACKUP_PATHS, bind mounts vs volumes nommés, exemples Caddy/nginx/Traefik, DB volume vs dump logique.
- docs/BACKUP_RUN.md : volumes ajoutés aux profiles sauvegardés par restic.

Ajouter docs/DOCKER_COVERAGE.md expliquant docker scan, inventory, coverage, suggest-profile-updates, add-missing-paths, sécurité, pas de modification automatique, DB volumes, reverse proxy volumes, .env.

12. Critères d’acceptation

- tests unitaires OK ;
- server-backup docker scan fonctionne ;
- server-backup docker inventory fonctionne ;
- server-backup docker coverage fonctionne ;
- server-backup docker suggest-profile-updates fonctionne ;
- server-backup docker add-missing-paths --dry-run ne modifie rien ;
- add-missing-paths avec confirmation modifie uniquement le profile choisi ;
- backup horodaté du profile créé avant modification ;
- chemins déjà présents non dupliqués ;
- DATABASE_DUMPS préservé ;
- EXCLUDES préservé ;
- CONTENT_CLASSIFICATION préservé ;
- aucun secret affiché ;
- aucun contenu .env affiché ;
- Docker n’est jamais modifié ;
- docker compose n’est jamais lancé ;
- coverage audit devient plus précis après correction des profiles ;
- aucun backup réel lancé automatiquement.

À la fin, fournir résumé, tests, résultat docker coverage réel, suggestions générées, éventuels chemins ajoutés à un profile, résultat coverage audit après correction éventuelle, limites restantes, prochaine PR recommandée.

Prochaine PR recommandée :

PR15 — deployment runbook and end-to-end installation procedure

Objectif PR15 :
- écrire une procédure complète PR par PR ;
- expliquer quand préparer NAS/VPN ;
- expliquer quand créer target/profile/db ;
- expliquer quand lancer repo init, backup, prune, restore test ;
- produire un runbook de déploiement reproductible.
```