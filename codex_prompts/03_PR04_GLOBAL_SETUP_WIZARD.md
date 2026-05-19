# Prompt Codex — PR4 Wizard global setup

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

Objectif de cette PR :

Implémenter uniquement :

PR4 — CLI et wizard global setup

Objectif :
- implémenter server-backup setup
- générer /etc/server-backup/backup.conf
- poser les questions globales
- configurer rétention, timer, email, prune, check, coverage audit
- créer le mot de passe restic si demandé
- ne pas encore configurer target NAS
- ne pas encore configurer profiles applicatifs
- ne pas encore faire de backup restic réel

Ne pas implémenter encore :
- target add réel
- target test réel
- repo init/check réel
- profile add réel
- db add réel
- docker scan réel
- coverage audit réel
- restore test réel
- backup run réel
- email report réel

Contraintes générales :
- pas de dépendance Python externe
- ne jamais stocker de secrets dans Git
- ne jamais afficher de secrets dans les logs
- ne jamais écraser une config existante sans confirmation explicite
- fichiers éditables à la main
- comportement idempotent
- erreurs claires
- compatible Debian/Ubuntu
- le système tourne sur l’hôte Linux, pas dans Docker

Livrables attendus :

1. Ajouter ou compléter server_backup/wizard.py

Créer des fonctions simples et testables, par exemple :

- prompt_string()
- prompt_bool()
- prompt_int()
- prompt_choice()
- confirm_overwrite()
- generate_restic_password()
- write_file_secure()
- render_backup_conf()
- run_global_setup()

Le wizard doit fonctionner en mode interactif terminal.
Il doit aussi supporter un mode non-interactif minimal pour tests si raisonnable, par exemple en permettant d’injecter des réponses ou en séparant rendu/écriture.

2. Implémenter server-backup setup

Commande :

sudo server-backup setup

Elle doit poser les questions globales :

- BACKUP_NAME
- BACKUP_TAGS
- RETENTION_DAILY
- RETENTION_WEEKLY
- RETENTION_MONTHLY
- heure du timer systemd au format HH:MM
- RUN_RESTIC_CHECK true/false
- RUN_PRUNE true/false
- RUN_COVERAGE_AUDIT true/false
- COVERAGE_AUDIT_FAIL_ON_FAILURE true/false
- COVERAGE_AUDIT_FAIL_ON_WARNING true/false
- EMAIL_REPORT_ENABLED true/false
- si email activé : EMAIL_REPORT_TO, EMAIL_REPORT_FROM, EMAIL_REPORT_SUBJECT_PREFIX, EMAIL_REPORT_SEND_ON_SUCCESS, EMAIL_REPORT_SEND_ON_FAILURE, EMAIL_REPORT_COMMAND choix sendmail/mail
- RESTIC_PASSWORD_FILE
- générer un mot de passe restic maintenant ? true/false
- si oui, créer le fichier secret avec permissions 0600 root:root
- si non, vérifier ou indiquer que le fichier devra être créé avant restic init

Valeurs par défaut recommandées :

- BACKUP_NAME = hostname système
- BACKUP_TAGS = hostname
- RETENTION_DAILY = 14
- RETENTION_WEEKLY = 8
- RETENTION_MONTHLY = 12
- timer = 02:30
- RUN_RESTIC_CHECK = true
- RUN_PRUNE = true
- RUN_COVERAGE_AUDIT = true
- COVERAGE_AUDIT_FAIL_ON_FAILURE = true
- COVERAGE_AUDIT_FAIL_ON_WARNING = false
- EMAIL_REPORT_ENABLED = false
- EMAIL_REPORT_SUBJECT_PREFIX = [server-backup]
- EMAIL_REPORT_SEND_ON_SUCCESS = true
- EMAIL_REPORT_SEND_ON_FAILURE = true
- EMAIL_REPORT_COMMAND = sendmail
- LOCAL_DUMP_DIR = /var/tmp/server-backup
- LOG_FILE = /var/log/server-backup.log
- STATE_DIR = /var/lib/server-backup/state
- REPORT_DIR = /var/lib/server-backup/reports
- RESTIC_CACHE_DIR = /var/cache/restic
- RESTIC_PASSWORD_FILE = /etc/server-backup/secrets/restic-password

3. Générer /etc/server-backup/backup.conf

Le fichier généré doit contenir au minimum :

CONFIG_VERSION="1"
GENERATED_BY="server-backup"
GENERATED_AT="<timestamp ISO8601>"

BACKUP_NAME="..."
BACKUP_TAGS="..."

RETENTION_DAILY=14
RETENTION_WEEKLY=8
RETENTION_MONTHLY=12

LOCAL_DUMP_DIR="/var/tmp/server-backup"
LOG_FILE="/var/log/server-backup.log"
STATE_DIR="/var/lib/server-backup/state"
REPORT_DIR="/var/lib/server-backup/reports"

RESTIC_CACHE_DIR="/var/cache/restic"
RESTIC_PASSWORD_FILE="/etc/server-backup/secrets/restic-password"

RUN_RESTIC_CHECK="true"
RUN_PRUNE="true"
RUN_COVERAGE_AUDIT="true"
COVERAGE_AUDIT_FAIL_ON_FAILURE="true"
COVERAGE_AUDIT_FAIL_ON_WARNING="false"

EMAIL_REPORT_ENABLED="false"
EMAIL_REPORT_TO=""
EMAIL_REPORT_FROM=""
EMAIL_REPORT_SUBJECT_PREFIX="[server-backup]"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
EMAIL_REPORT_COMMAND="sendmail"

Le fichier doit être écrit avec permissions 0600 root:root.

Si /etc/server-backup/backup.conf existe déjà :
- ne pas l’écraser par défaut
- demander confirmation interactive
- si refus, laisser le fichier intact
- si acceptation, faire une sauvegarde horodatée avant remplacement : /etc/server-backup/backup.conf.bak-YYYYMMDD-HHMMSS

4. Mot de passe restic

Si l’utilisateur choisit de générer le mot de passe restic :

- créer /etc/server-backup/secrets/restic-password
- permissions 0600 root:root
- ne jamais afficher le mot de passe
- générer au moins 32 caractères aléatoires avec secrets standard library
- si le fichier existe déjà, ne pas l’écraser par défaut ; demander confirmation ; si remplacement, faire backup horodaté

Important :
- rappeler à l’utilisateur qu’il doit stocker ce mot de passe hors serveur dans son restore kit
- ne jamais écrire ce mot de passe dans les logs ou rapports

5. Timer systemd

Le setup doit pouvoir mettre à jour l’heure du timer.

Le fichier systemd installé est :

/etc/systemd/system/server-backup.timer

Le wizard doit :
- demander l’heure quotidienne HH:MM
- mettre à jour OnCalendar=*-*-* HH:MM:00 dans le timer installé
- faire systemctl daemon-reload
- demander si l’utilisateur veut activer le timer maintenant
- si oui : systemctl enable --now server-backup.timer
- si non : afficher la commande à lancer plus tard

Ne pas activer automatiquement sans confirmation.

Si le timer n’existe pas encore :
- afficher une erreur claire conseillant de lancer sudo ./scripts/install.sh

6. Validation après setup

À la fin de server-backup setup :

- relire /etc/server-backup/backup.conf via config.py
- exécuter validate_global_config
- afficher warnings/errors
- afficher prochaine étape recommandée : sudo server-backup target add

Mais ne pas implémenter target add réel dans cette PR.

7. Mise à jour server-backup status

status doit maintenant détecter si backup.conf existe et afficher :

- BACKUP_NAME
- rétention
- email enabled yes/no
- coverage audit enabled yes/no
- prune enabled yes/no
- check enabled yes/no
- restic password file exists yes/no, sans contenu
- timer enabled yes/no si possible
- timer next run si possible via systemctl list-timers ou message simple

Si systemctl n’est pas disponible, ne pas crasher.

8. Ajouter commande server-backup email test en stub amélioré

Ne pas envoyer encore d’email réel.

Mais si EMAIL_REPORT_ENABLED=true, afficher EMAIL_REPORT_TO, EMAIL_REPORT_FROM, EMAIL_REPORT_COMMAND et le message “Email sending will be implemented in PR11.”

Si email disabled : afficher “Email reports are disabled in backup.conf.”

9. Tests unitaires

Ajouter tests sans dépendance externe :

- tests/test_wizard_rendering.py

Tester au minimum :

- render_backup_conf génère CONFIG_VERSION
- render_backup_conf inclut BACKUP_NAME
- render_backup_conf inclut EMAIL_REPORT_ENABLED
- render_backup_conf quote correctement les strings
- generate_restic_password retourne une longueur suffisante
- aucune valeur générée n’est vide quand obligatoire
- backup.conf rendu est parsable par parse_config_file

10. Documentation

Mettre à jour docs/SERVER_INSTALL.md :
- exécuter sudo server-backup setup
- choix posés par le wizard
- création backup.conf
- création optionnelle restic-password
- activation optionnelle timer
- prochaine étape target add

Mettre à jour docs/CONFIG_REFERENCE.md :
- détails des champs globaux

Mettre à jour docs/RESTORE_KIT.md :
- le mot de passe restic généré par setup doit être copié dans le restore kit
- sans ce mot de passe, les backups sont inutilisables
- ne jamais le stocker dans Git

Critères d’acceptation :

- python3 -m unittest discover -s tests passe
- python3 -m server_backup.cli --help fonctionne
- python3 -m server_backup.cli status fonctionne
- sudo server-backup setup fonctionne en interactif
- setup crée /etc/server-backup/backup.conf en 0600 root:root
- setup ne remplace pas backup.conf sans confirmation
- setup peut générer /etc/server-backup/secrets/restic-password en 0600 root:root
- setup ne remplace pas restic-password sans confirmation
- setup peut modifier l’heure OnCalendar du timer
- setup n’active pas le timer sans confirmation
- sudo server-backup status affiche les infos globales
- sudo server-backup config validate fonctionne après setup
- aucun secret n’est affiché
- aucune target NAS n’est créée
- aucun profile applicatif n’est créé
- aucun backup réel n’est lancé

Tests à exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli status
- sudo ./scripts/install.sh
- sudo server-backup setup
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup config show
- systemctl cat server-backup.timer
- systemctl status server-backup.timer --no-pager

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR5 — Wizard target SFTP et SSH.
```
