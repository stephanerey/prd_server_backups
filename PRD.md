# PRD — Template de sauvegarde serveur avec restic

## 1. Objectif

Créer un projet générique permettant de déployer rapidement une stratégie de sauvegarde applicative sur plusieurs serveurs Linux.

Le système doit :

- utiliser `restic` comme moteur de sauvegarde ;
- supporter plusieurs destinations indépendantes ;
- rester agnostique du stockage distant : OMV, Synology, QNAP, TrueNAS, serveur Linux dédié, storage SFTP, rest-server, S3 ou rclone ;
- proposer un wizard CLI pour générer les fichiers de configuration ;
- conserver des fichiers de configuration simples, lisibles et modifiables à la main ;
- utiliser `systemd timer` plutôt que cron ;
- produire un rapport email à la fin de chaque backup ;
- permettre l'initialisation, la vérification, la rotation, le test de restauration et le diagnostic.

Le projet final doit être exploitable directement sur un serveur cible après clone Git.

---

## 2. Contexte

Un serveur peut disposer d'une sauvegarde provider, par exemple OVH Premium Backup 7 jours glissants. Cette sauvegarde est utile pour restaurer rapidement une image serveur, mais elle ne remplace pas une sauvegarde applicative indépendante, chiffrée et externalisée.

La solution applicative cible est :

```text
Serveur Linux
 ├── backup provider éventuel, ex. OVH Premium Backup 7j
 └── restic applicatif quotidien
      ├── destination 1 : NAS maison
      ├── destination 2 : NAS distant
      └── destination future : S3/rest-server/rclone
```

Chaque destination doit avoir son propre dépôt restic indépendant.

---

## 3. Périmètre fonctionnel

### Inclus

- installation des dépendances système ;
- génération de configuration par wizard ;
- configuration manuelle possible sans wizard ;
- backup de chemins fichiers ;
- exclusions configurables ;
- dumps PostgreSQL ;
- dumps MariaDB/MySQL ;
- support multi-profils ;
- support multi-destinations ;
- initialisation des dépôts restic ;
- backup quotidien par systemd timer ;
- rétention configurable ;
- prune optionnel ;
- restic check ;
- restore test ;
- logs locaux ;
- rapport email de fin de backup ;
- documentation NAS générique et exemples OMV/Synology/QNAP/Linux.

### Exclu pour la première version

- interface web ;
- orchestration Terraform ;
- rôle Ansible complet ;
- serveur restic append-only obligatoire ;
- gestion centralisée de secrets type Vault ;
- configuration SMTP système détaillée.

La configuration SMTP du serveur est considérée comme un prérequis externe. Le projet doit seulement utiliser un mécanisme local d'envoi d'email compatible avec un MTA déjà configuré.

---

## 4. Hypothèses serveur

Serveur cible :

- Linux Debian/Ubuntu en priorité ;
- accès root ou sudo ;
- systemd disponible ;
- shell Bash disponible ;
- Python 3 standard library disponible pour le wizard ;
- outbound SSH autorisé vers les destinations SFTP ;
- un MTA local ou équivalent sera configuré séparément pour l'envoi d'emails.

Paquets nécessaires :

- `restic` ;
- `openssh-client` ;
- `python3` ;
- `postgresql-client`, si dump PostgreSQL ;
- `mariadb-client` ou `mysql-client`, si dump MariaDB/MySQL ;
- `mailutils` ou commande compatible `sendmail`, si rapports email.

---

## 5. Hypothèses destination distante

Une destination distante minimale doit fournir :

- un accès réseau depuis le serveur source ;
- un backend compatible restic ;
- pour SFTP : SSH/SFTP activé ;
- un utilisateur dédié ;
- authentification par clé SSH ;
- un dossier dédié au dépôt restic ;
- droits lecture/écriture uniquement sur ce dossier ;
- espace disque suffisant ;
- idéalement snapshots locaux côté NAS.

Le code ne doit contenir aucune dépendance spécifique à OMV, Synology ou QNAP. Ces systèmes sont uniquement documentés comme exemples de préparation d'une cible SFTP.

---

## 6. Politique de rétention par défaut

Valeurs par défaut :

```text
journaliers   : 14
hebdomadaires : 8
mensuels      : 12
```

Ces valeurs doivent être configurables dans `/etc/server-backup/backup.conf` et via wizard.

---

## 7. Architecture cible du dépôt

```text
server-backup-template/
├── README.md
├── PRD.md
├── docs/
│   ├── NAS_GENERIC_PREREQUISITES.md
│   ├── NAS_OMV_EXAMPLE.md
│   ├── NAS_SYNOLOGY_EXAMPLE.md
│   ├── NAS_QNAP_EXAMPLE.md
│   ├── NAS_LINUX_SERVER_EXAMPLE.md
│   ├── SERVER_INSTALL.md
│   ├── RESTORE.md
│   ├── EMAIL_REPORTS.md
│   └── SECURITY_MODEL.md
├── examples/
│   ├── backup.conf.example
│   ├── targets/
│   │   ├── sftp.env.example
│   │   ├── rest-server.env.example
│   │   ├── s3.env.example
│   │   └── rclone.env.example
│   └── profiles/
│       ├── generic-web.conf.example
│       ├── pyparfums.conf.example
│       ├── docker-compose.conf.example
│       └── homeassistant.conf.example
├── scripts/
│   ├── install.sh
│   ├── backup.sh
│   ├── init-repositories.sh
│   ├── check-repositories.sh
│   ├── prune.sh
│   └── restore-test.sh
├── server_backup/
│   ├── __init__.py
│   ├── cli.py
│   ├── wizard.py
│   ├── config.py
│   ├── ssh.py
│   ├── restic.py
│   ├── email_report.py
│   └── validators.py
└── systemd/
    ├── server-backup.service
    └── server-backup.timer
```

---

## 8. Architecture cible installée

Sur chaque serveur :

```text
/etc/server-backup/
├── backup.conf
├── secrets/
│   └── restic-password
├── ssh/
│   ├── id_ed25519_nas_home
│   └── id_ed25519_nas_eva
├── targets.d/
│   ├── nas-home.env
│   └── nas-eva.env
└── profiles.d/
    ├── pyparfums.conf
    └── nginx.conf

/var/cache/restic/
/var/log/server-backup.log
/var/lib/server-backup/
├── reports/
└── state/
```

Droits attendus :

```text
/etc/server-backup                  0700 root:root
/etc/server-backup/secrets          0700 root:root
/etc/server-backup/secrets/*        0600 root:root
/etc/server-backup/ssh              0700 root:root
/etc/server-backup/ssh/id_*         0600 root:root
/etc/server-backup/targets.d/*.env  0600 root:root
/etc/server-backup/profiles.d/*.conf 0600 root:root
/var/cache/restic                   0700 root:root
/var/lib/server-backup              0700 root:root
```

---

## 9. Configuration globale

Exemple `/etc/server-backup/backup.conf` :

```bash
BACKUP_NAME="pyparfums-prod"
BACKUP_TAGS="pyparfums prod ovh"

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

EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="admin@example.net"
EMAIL_REPORT_FROM="server-backup@example.net"
EMAIL_REPORT_SUBJECT_PREFIX="[server-backup]"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
EMAIL_REPORT_COMMAND="sendmail"
```

Le champ `EMAIL_REPORT_COMMAND` doit supporter au minimum :

- `sendmail` : utilisation de `/usr/sbin/sendmail -t` ;
- `mail` : utilisation de la commande `mail` ou `mailx`.

La configuration SMTP détaillée n'est pas dans le périmètre. Le serveur devra être préparé dans un autre chantier pour que `sendmail` ou `mail` fonctionne.

---

## 10. Configuration target

Exemple SFTP `/etc/server-backup/targets.d/nas-home.env` :

```bash
TARGET_NAME="nas-home"
TARGET_TYPE="sftp"

SSH_HOST_ALIAS="server-backup-nas-home"
SSH_HOSTNAME="backup.example.net"
SSH_PORT="2222"
SSH_USER="backup-pyparfums"
SSH_IDENTITY_FILE="/etc/server-backup/ssh/id_ed25519_nas_home"

RESTIC_REPOSITORY="sftp:server-backup-nas-home:/backups/pyparfums-prod/restic"
RESTIC_PASSWORD_FILE="/etc/server-backup/secrets/restic-password"
RESTIC_CACHE_DIR="/var/cache/restic"
```

Règles :

- un fichier `.env` par destination ;
- un dépôt restic indépendant par destination ;
- ne jamais partager un dépôt entre plusieurs serveurs ;
- les scripts parcourent automatiquement `/etc/server-backup/targets.d/*.env` ;
- si une destination échoue, les autres doivent quand même être tentées ;
- le code retour global doit être non nul si au moins une destination échoue.

---

## 11. Configuration profile

Exemple `/etc/server-backup/profiles.d/pyparfums.conf` :

```bash
PROFILE_NAME="pyparfums"

BACKUP_PATHS=(
  "/srv/pyparfums"
  "/etc/nginx"
  "/etc/letsencrypt"
  "/etc/systemd/system"
)

EXCLUDES=(
  "**/__pycache__"
  "**/.venv"
  "**/venv"
  "**/node_modules"
  "**/.cache"
  "/srv/pyparfums/tmp"
  "/srv/pyparfums/cache"
)

POSTGRES_DATABASES=(
  "pyparfums"
)

MYSQL_DATABASES=()
```

Règles :

- plusieurs profiles peuvent être présents ;
- un backup charge tous les fichiers `/etc/server-backup/profiles.d/*.conf` ;
- les chemins inexistants doivent générer un warning, pas forcément un échec fatal ;
- les erreurs de dump DB doivent être fatales pour le profile concerné, sauf option explicite future ;
- les dumps DB doivent être placés temporairement sous `LOCAL_DUMP_DIR` puis inclus dans restic ;
- les dumps temporaires doivent être supprimés en fin d'exécution.

---

## 12. Dumps bases de données

### PostgreSQL

Pour chaque base dans `POSTGRES_DATABASES`, le script doit générer un dump.

Format par défaut :

```bash
pg_dump --format=custom --compress=0 --file="$dump_file" "$database"
```

Justification : éviter la compression préalable pour favoriser la déduplication restic.

### MariaDB/MySQL

Pour chaque base dans `MYSQL_DATABASES`, le script doit générer un dump SQL non compressé.

Commande indicative :

```bash
mariadb-dump --single-transaction --routines --triggers --events "$database" > "$dump_file"
```

Si `mariadb-dump` n'existe pas, tenter `mysqldump`.

Les credentials DB ne doivent pas être stockés en clair dans le repo. Utiliser les mécanismes standards :

- `.pgpass` root ;
- variables d'environnement système ;
- fichier client MariaDB/MySQL protégé ;
- socket local si applicable.

---

## 13. Rapport email

Le système doit générer un rapport à la fin de chaque exécution.

### Contenu minimal

- nom du serveur backup ;
- hostname système ;
- date de début ;
- date de fin ;
- durée ;
- statut global : success, warning, failure ;
- liste des profiles traités ;
- liste des targets ;
- résultat par target ;
- taille approximative des données envoyées si disponible ;
- nombre de fichiers traités si disponible ;
- statut prune ;
- statut check ;
- erreurs et warnings ;
- chemin du log local ;
- commandes utiles pour diagnostic.

### Sujet email

Format :

```text
[server-backup] SUCCESS pyparfums-prod on hostname
[server-backup] FAILURE pyparfums-prod on hostname
[server-backup] WARNING pyparfums-prod on hostname
```

### Envoi

Le module `server_backup/email_report.py` doit permettre :

- génération du corps texte ;
- envoi via `/usr/sbin/sendmail -t` ;
- fallback via `mail` si configuré ;
- désactivation complète par `EMAIL_REPORT_ENABLED=false` ;
- envoi seulement sur échec si `EMAIL_REPORT_SEND_ON_SUCCESS=false`.

### Important

La configuration SMTP, SPF/DKIM, relais SMTP, authentification SMTP ou MTA local sera traitée séparément. Le projet doit seulement supposer que le serveur sait déjà envoyer un email localement via `sendmail` ou `mail`.

---

## 14. Wizard CLI

Commande principale :

```bash
sudo server-backup setup
```

Sous-commandes attendues :

```bash
sudo server-backup setup
sudo server-backup target add
sudo server-backup target test <target>
sudo server-backup repo init [target]
sudo server-backup repo check [target]
sudo server-backup profile add
sudo server-backup backup run
sudo server-backup restore test
sudo server-backup email test
sudo server-backup status
```

### Wizard global

Questions :

- nom logique du backup ;
- tags ;
- rétention daily/weekly/monthly ;
- heure du timer systemd ;
- activer prune ;
- activer restic check ;
- activer rapports email ;
- adresse email destinataire ;
- adresse email expéditeur ;
- envoyer aussi en cas de succès ;
- méthode email : sendmail ou mail.

Le wizard doit générer `/etc/server-backup/backup.conf` sans écraser les fichiers existants sans confirmation.

### Wizard target SFTP

Questions :

- nom logique de destination ;
- type de destination ;
- hostname ou IP ;
- port SSH ;
- utilisateur SSH ;
- chemin distant dépôt restic ;
- créer une nouvelle clé SSH dédiée ;
- chemin de clé ;
- générer alias SSH ;
- tester la connexion ;
- initialiser le dépôt.

Le wizard doit afficher clairement la clé publique à copier côté NAS.

### Wizard profile

Questions :

- nom du profile ;
- type : generic, web, docker-compose, postgresql, mariadb, custom ;
- chemins à sauvegarder ;
- exclusions ;
- bases PostgreSQL ;
- bases MySQL/MariaDB.

---

## 15. systemd

Service :

```ini
[Unit]
Description=Server backup using restic
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/server-backup-run
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

Timer par défaut :

```ini
[Unit]
Description=Run server backup daily

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
```

Le wizard doit pouvoir modifier l'heure de lancement.

---

## 16. Sécurité

Principes :

- secrets hors Git ;
- droits stricts root-only ;
- clé SSH dédiée par target ;
- utilisateur distant dédié ;
- accès distant limité au dossier backup ;
- pas de login root distant ;
- authentification par clé ;
- idéalement restriction par IP côté NAS ;
- snapshots locaux côté NAS recommandés ;
- documentation claire du risque : si le serveur source est compromis, un attaquant peut potentiellement supprimer les backups accessibles en écriture.

La documentation doit recommander :

- snapshots Btrfs/ZFS côté NAS si possible ;
- dépôt append-only restic-server comme amélioration future ;
- second NAS distant pour redondance géographique.

---

## 17. Critères d'acceptation globaux

Le projet est considéré utilisable si :

1. un serveur vierge Debian/Ubuntu peut installer le template avec `sudo ./scripts/install.sh` ;
2. le wizard peut générer `backup.conf`, au moins une target SFTP et un profile ;
3. `server-backup target test <target>` valide la connexion ;
4. `server-backup repo init <target>` initialise restic ;
5. `server-backup backup run` exécute un backup complet ;
6. la rétention est appliquée selon la configuration ;
7. `server-backup restore test` restaure un snapshot dans un répertoire temporaire ;
8. un rapport email est généré et envoyé si activé ;
9. les logs sont disponibles dans `/var/log/server-backup.log` et via journalctl ;
10. l'ajout d'une deuxième target se fait uniquement en ajoutant un fichier `.env` ou via wizard.

---

# Plan de réalisation par PR pour Codex

## PR1 — Structure repo et documentation de base

Créer l'arborescence cible.

Livrables :

- `README.md` ;
- `PRD.md` ;
- `docs/NAS_GENERIC_PREREQUISITES.md` ;
- `docs/SERVER_INSTALL.md` ;
- `docs/SECURITY_MODEL.md` ;
- `examples/backup.conf.example` ;
- exemples targets/profiles.

Critères :

- les docs expliquent que le NAS est générique ;
- SFTP est le backend minimal ;
- OMV/Synology/QNAP ne sont que des exemples.

## PR2 — install.sh idempotent

Créer `scripts/install.sh`.

Fonctions :

- vérifier root ;
- détecter apt ;
- installer dépendances disponibles ;
- créer `/etc/server-backup` ;
- créer `/var/cache/restic` ;
- créer `/var/lib/server-backup` ;
- installer wrappers dans `/usr/local/sbin` ;
- installer CLI `server-backup` dans `/usr/local/bin` ;
- installer units systemd ;
- ne jamais écraser secrets/config sans confirmation.

Critères :

- relancer install.sh ne casse pas une installation existante ;
- permissions correctes ;
- systemd daemon-reload exécuté.

## PR3 — Configuration loader et validateurs

Créer `server_backup/config.py` et `server_backup/validators.py`.

Fonctions :

- lire backup.conf ;
- lister targets ;
- lister profiles ;
- valider les champs obligatoires ;
- signaler warnings lisibles ;
- ne pas afficher les secrets.

Critères :

- erreurs explicites ;
- tests simples possibles via CLI status.

## PR4 — CLI et wizard global

Créer `server_backup/cli.py` et `server_backup/wizard.py`.

Commandes :

- `server-backup setup` ;
- `server-backup status`.

Critères :

- génération de backup.conf ;
- support configuration email de rapport ;
- aucune écriture destructrice sans confirmation.

## PR5 — Wizard target SFTP et SSH

Créer `server_backup/ssh.py`.

Commandes :

- `server-backup target add` ;
- `server-backup target test <target>`.

Fonctions :

- créer clé ed25519 dédiée ;
- afficher clé publique ;
- générer target env ;
- générer ou documenter alias SSH ;
- tester SSH/SFTP.

Critères :

- compatible OMV/Synology/QNAP/Linux si SSH/SFTP disponible ;
- aucun détail spécifique NAS codé en dur.

## PR6 — Wizard profile

Commande :

- `server-backup profile add`.

Fonctions :

- créer profile conf ;
- chemins multiples ;
- exclusions ;
- bases PostgreSQL ;
- bases MariaDB/MySQL.

Critères :

- profile lisible en Bash ;
- chemins inexistants signalés.

## PR7 — init/check repositories

Créer :

- `scripts/init-repositories.sh` ;
- `scripts/check-repositories.sh` ;
- couche CLI `repo init`, `repo check`.

Critères :

- fonctionne pour une target ou toutes ;
- code retour non nul si une target échoue ;
- logs clairs.

## PR8 — backup.sh multi-target

Créer `scripts/backup.sh`.

Fonctions :

- charger backup.conf ;
- charger profiles ;
- créer dumps DB ;
- construire options restic ;
- exécuter backup vers chaque target ;
- tenter toutes les targets même si une échoue ;
- collecter résultats ;
- nettoyer dumps temporaires ;
- retourner non zéro si échec.

Critères :

- backup manuel possible ;
- logs exploitables ;
- pas de compression préalable des dumps DB par défaut.

## PR9 — rétention et prune

Créer `scripts/prune.sh` et intégrer dans backup si `RUN_PRUNE=true`.

Commande restic attendue :

```bash
restic forget --keep-daily "$RETENTION_DAILY" --keep-weekly "$RETENTION_WEEKLY" --keep-monthly "$RETENTION_MONTHLY" --prune
```

Critères :

- exécuté par target ;
- erreurs remontées ;
- peut être lancé séparément.

## PR10 — restore test

Créer `scripts/restore-test.sh` et CLI `restore test`.

Fonctions :

- restaurer latest dans `/tmp/server-backup-restore-test-*` ;
- option target ;
- option include ;
- afficher chemins restaurés ;
- ne rien écraser.

Critères :

- test de restauration simple et documenté ;
- code retour clair.

## PR11 — rapports email

Créer `server_backup/email_report.py` et intégrer l'envoi en fin de `backup.sh` ou via wrapper Python.

Fonctions :

- collecter résultats d'exécution ;
- produire rapport texte ;
- sauvegarder copie dans `/var/lib/server-backup/reports` ;
- envoyer via sendmail ;
- fallback via mail si configuré ;
- respecter `EMAIL_REPORT_ENABLED` ;
- respecter `EMAIL_REPORT_SEND_ON_SUCCESS` et `EMAIL_REPORT_SEND_ON_FAILURE` ;
- fournir commande `server-backup email test`.

Critères :

- aucun secret dans l'email ;
- email envoyé en success/failure selon config ;
- si email échoue, le backup ne doit pas être considéré comme réussi silencieusement : générer warning ou failure selon politique documentée.

## PR12 — systemd timer

Livrables :

- `systemd/server-backup.service` ;
- `systemd/server-backup.timer` ;
- installation dans `/etc/systemd/system` ;
- enable optionnel via wizard.

Critères :

- `systemctl start server-backup.service` fonctionne ;
- `systemctl enable --now server-backup.timer` fonctionne ;
- logs via `journalctl -u server-backup.service`.

## PR13 — documentation NAS spécifiques

Ajouter :

- `docs/NAS_OMV_EXAMPLE.md` ;
- `docs/NAS_SYNOLOGY_EXAMPLE.md` ;
- `docs/NAS_QNAP_EXAMPLE.md` ;
- `docs/NAS_LINUX_SERVER_EXAMPLE.md`.

Critères :

- chaque doc explique utilisateur dédié, dossier, SSH/SFTP, clé publique, droits, snapshots recommandés ;
- aucune doc n'est nécessaire au fonctionnement du code.

## PR14 — documentation restauration et exploitation

Ajouter :

- `docs/RESTORE.md` ;
- `docs/EMAIL_REPORTS.md` ;
- troubleshooting.

Critères :

- un opérateur peut tester une restauration ;
- un opérateur peut diagnostiquer email, SSH, restic, DB dumps.

## PR15 — qualité, shellcheck et tests simples

Ajouter :

- checks shellcheck si possible ;
- tests unitaires Python minimaux ;
- validation syntaxe bash ;
- GitHub Actions optionnel.

Critères :

- CI simple ;
- pas de dépendances lourdes ;
- documentation à jour.

---

## 18. Informations que le wizard doit collecter avant installation complète

Pour que Codex puisse déployer le système sans ambiguïté après implémentation, le wizard doit obtenir toutes les informations suivantes :

### Global

- nom logique du backup ;
- tags ;
- rétention daily/weekly/monthly ;
- heure de lancement ;
- prune oui/non ;
- check oui/non ;
- email report oui/non ;
- destinataire email ;
- expéditeur email ;
- envoyer en succès oui/non ;
- envoyer en échec oui/non ;
- méthode d'envoi : sendmail ou mail.

### Target

- nom target ;
- type target ;
- repository restic complet ou éléments pour le construire ;
- pour SFTP : hostname, port, user, chemin distant ;
- clé SSH à créer ou chemin clé existante ;
- alias SSH ;
- initialiser repository oui/non.

### Profile

- nom profile ;
- chemins fichiers ;
- exclusions ;
- bases PostgreSQL ;
- bases MySQL/MariaDB ;
- comportement en cas de chemin absent.

Après wizard, aucune information fonctionnelle ne doit manquer sauf les prérequis externes :

- SMTP local déjà configuré ;
- accès SSH/SFTP distant déjà préparé ;
- credentials DB disponibles via mécanisme système protégé.
