# Server Backup Template — PRD et procédure d'installation

Ce dépôt décrit le cahier des charges d'un système de sauvegarde serveur générique basé sur `restic`.

Le but est de permettre à Codex d'implémenter un template réutilisable sur plusieurs serveurs Linux, avec :

- sauvegarde applicative quotidienne ;
- stockage distant sur un ou plusieurs NAS ;
- configuration interactive via wizard ;
- support Docker, Docker Compose, PostgreSQL, MariaDB/MySQL ;
- audit de couverture pour éviter les oublis ;
- tests de restauration ;
- rapports email après chaque backup.

> État du dépôt : ce dépôt est le PRD. Il ne contient pas encore l'implémentation finale. Codex doit lire `PRD.md` puis les addendums, et implémenter les PR dans l'ordre.

---

## 1. Documents du PRD

Documents principaux :

```text
PRD.md
PRD_DOCKER_ADDENDUM.md
PRD_SITE_CONTENT_ADDENDUM.md
PRD_COVERAGE_AND_RESTORE_STRATEGY_ADDENDUM.md
PRD_DATABASE_CONNECTION_AND_SCOPE_ADDENDUM.md
```

Rôle des documents :

```text
PRD.md
  Spécification générale du système : restic, targets, profiles, wizard, systemd, email.

PRD_DOCKER_ADDENDUM.md
  Sauvegarde des serveurs Docker : Compose, volumes, bind mounts, inventaire Docker, dumps DB Docker.

PRD_SITE_CONTENT_ADDENDUM.md
  Sauvegarde du contenu réel des sites web, notamment CIS : pages, uploads, médias, contenu DB.

PRD_COVERAGE_AND_RESTORE_STRATEGY_ADDENDUM.md
  Audit de couverture, comparaison avec les snapshots OVH, stratégie de restauration.

PRD_DATABASE_CONNECTION_AND_SCOPE_ADDENDUM.md
  Connexion aux bases, wizard DB, périmètre exact des dumps PostgreSQL/MariaDB/MySQL.
```

---

## 2. Objectif du système final

Le système final doit permettre de reconstruire rapidement un serveur après incident, sans dépendre uniquement d'un backup provider.

Architecture cible :

```text
Serveur Linux
 ├── Backup provider éventuel
 │    └── ex. OVH Premium Backup 7 jours glissants
 │
 └── Backup applicatif restic
      ├── NAS maison via SFTP
      ├── NAS distant secondaire via SFTP
      ├── futur backend rest-server
      ├── futur backend S3
      └── futur backend rclone
```

Chaque destination doit avoir son propre dépôt `restic` indépendant.

Exemple :

```text
/backups/
├── pyparfums-prod/restic
├── homeassistant-prod/restic
├── radio-prod/restic
└── test-server/restic
```

Un serveur = un dépôt restic par destination.

---

## 3. Ce que le système sauvegarde

Le système sauvegarde ce qui est nécessaire pour reconstruire les services applicatifs.

### 3.1 Configuration système utile

Selon le profil choisi :

```text
/etc
/etc/systemd/system
/etc/ssh/sshd_config
/etc/ssh/sshd_config.d
/etc/cron.d
/etc/cron.daily
/etc/crontab
/etc/nginx
/etc/caddy
/etc/letsencrypt
/etc/fail2ban
/etc/ufw
/root
/home
/usr/local
```

Le profil large `system-filesystem` peut inclure :

```text
/etc
/root
/home
/srv
/opt
/usr/local
/var/spool/cron
/var/lib/server-backup/state
```

### 3.2 Applications

Le système sauvegarde les répertoires applicatifs configurés :

```text
/srv
/opt
chemins custom déclarés dans le wizard
```

Il sauvegarde aussi :

```text
scripts de déploiement locaux
fichiers de configuration applicatifs
fichiers .env associés aux projets Compose
configuration reverse proxy
```

### 3.3 Docker et Docker Compose

Pour les serveurs Docker, le système doit sauvegarder :

```text
compose.yml
docker-compose.yml
docker-compose.yaml
docker-compose.override.yml
.env liés aux projets Compose
volumes Docker persistants sélectionnés
bind mounts Docker sélectionnés
inventaire Docker complet
```

L'inventaire Docker doit contenir :

```text
version Docker
version Docker Compose
conteneurs actifs et arrêtés
images
volumes
networks
mounts par conteneur
ports exposés
labels Compose
restart policy
variables non sensibles, avec secrets masqués
```

Commande prévue :

```bash
sudo server-backup docker inventory
```

### 3.4 Bases de données

Le système sauvegarde les bases via dumps logiques.

PostgreSQL :

```text
pg_dump par base applicative critique
pg_dumpall --globals-only optionnel mais recommandé
pg_dump ou pg_dumpall via docker exec si PostgreSQL tourne dans Docker
```

MariaDB/MySQL :

```text
mariadb-dump ou mysqldump
base unique, plusieurs bases ou all-databases
routines, triggers et events inclus
```

### 3.5 Sites web et CIS

Pour CIS et autres services web critiques, le système doit sauvegarder le contenu réel du site :

```text
pages stockées en fichiers
pages stockées en base
uploads
médias
assets
contenu public/static
répertoires content/data/storage/files/pages/www/html/site/cms
volumes ou bind mounts associés
base de données associée
```

Le wizard doit demander explicitement où est stocké le contenu.

Cas possibles :

```text
Pages stockées en PostgreSQL
  → dump PostgreSQL obligatoire.

Pages stockées en fichiers
  → chemins content/uploads/media/etc. ajoutés à BACKUP_PATHS.

Pages stockées en DB + fichiers
  → dump DB + chemins fichiers.
```

### 3.6 Rapports, logs et état

Le système doit conserver :

```text
/var/log/server-backup.log
/var/lib/server-backup/reports
/var/lib/server-backup/state
inventaires Docker
audits de couverture
dernier test de restauration réussi
```

---

## 4. Ce que le système ne sauvegarde pas par défaut

Le système ne fait pas une image disque complète type snapshot provider.

Il ne sauvegarde pas par défaut :

```text
/var/lib/docker en entier
/var/lib/docker/overlay2
/var/lib/docker/image
/var/lib/docker/containers/*/*.log
couches d'images Docker
images Docker téléchargeables depuis registry
caches applicatifs
logs volumineux
/tmp
/var/tmp hors dumps temporaires
/proc
/sys
/dev
/run
/mnt
/media
lost+found
```

Il ne sauvegarde pas automatiquement :

```text
toutes les bases DB du serveur sauf option all-databases
tous les rôles PostgreSQL sauf pg_dumpall --globals-only
les secrets sauf décision explicite
le mot de passe restic lui-même
un clone bit-à-bit du VPS
```

---

## 5. Pourquoi garder OVH Premium Backup en plus

Le backup OVH et le backup restic n'ont pas le même rôle.

```text
OVH Premium Backup 7j
  Usage : rollback rapide du serveur complet.
  Avantage : retour arrière simple, court terme.
  Limite : dépendant OVH, rétention courte, restauration all-or-nothing.

Backup applicatif restic
  Usage : restauration portable, granulaire, long terme.
  Avantage : fichiers, services, DB, volumes, NAS distant.
  Limite : demande une procédure de restauration testée.
```

La stratégie recommandée :

```text
1. OVH Premium Backup
   → bouton rollback rapide.

2. Restic vers NAS
   → reconstruction fiable et portable.

3. Coverage audit
   → vérifie qu'on n'oublie pas un volume, une DB ou un contenu web.

4. Restore test régulier
   → vérifie que la restauration fonctionne vraiment.
```

---

## 6. Audit de couverture

Pour éviter les oublis, le système doit fournir :

```bash
sudo server-backup coverage audit
```

Cette commande doit comparer :

```text
conteneurs Docker actifs
projets Docker Compose détectés
volumes Docker
bind mounts
fichiers .env
conteneurs PostgreSQL/MariaDB/MySQL
bases déclarées
services web critiques comme CIS
chemins content/uploads/media/static/data/storage
reverse proxy Caddy/nginx/Traefik
ports exposés
chemins réellement présents dans BACKUP_PATHS
dumps DB réellement configurés
```

Exemples de warnings attendus :

```text
WARNING: volume cis_data détecté mais non inclus dans le backup
WARNING: bind mount /srv/cis/uploads détecté mais non inclus
WARNING: conteneur postgres détecté mais aucun dump configuré
WARNING: service CIS critique sans contenu fichier ou DB configuré
WARNING: fichier .env détecté mais non inclus
WARNING: reverse proxy détecté mais configuration non incluse
WARNING: aucun test de restauration réussi depuis plus de 30 jours
```

Options prévues :

```bash
RUN_COVERAGE_AUDIT="true"
COVERAGE_AUDIT_FAIL_ON_FAILURE="true"
COVERAGE_AUDIT_FAIL_ON_WARNING="false"
```

---

## 7. Périmètre exact des dumps DB

### 7.1 PostgreSQL avec pg_dump

Un `pg_dump` d'une base déclarée sauvegarde le contenu logique complet de cette base :

```text
schémas
tables
données
index
contraintes
séquences
vues
vues matérialisées
fonctions
triggers
types
extensions référencées
privilèges et ownership liés à la base
```

Mais il ne sauvegarde pas automatiquement :

```text
autres bases du même cluster
rôles/users PostgreSQL
mots de passe des rôles
tablespaces
paramètres globaux PostgreSQL
WAL/archive logs
configuration interne du serveur DB si non montée
```

Configuration recommandée PostgreSQL :

```text
pg_dump de chaque base applicative critique
+
pg_dumpall --globals-only pour les rôles/objets globaux
```

### 7.2 PostgreSQL dans Docker

Exemple attendu :

```bash
docker exec -e PGPASSWORD="$PGPASSWORD" "$container" \
  pg_dump --username="$user" --format=custom --compress=0 "$database" \
  > "$dump_file"
```

Dump des objets globaux :

```bash
docker exec -e PGPASSWORD="$PGPASSWORD" "$container" \
  pg_dumpall --globals-only --username="$user" \
  > "$dump_file"
```

### 7.3 MariaDB/MySQL

Exemple attendu :

```bash
mariadb-dump \
  --single-transaction \
  --routines \
  --triggers \
  --events \
  "$database" > "$dump_file"
```

Pour toutes les bases :

```bash
mariadb-dump \
  --all-databases \
  --single-transaction \
  --routines \
  --triggers \
  --events > "$dump_file"
```

---

## 8. Prérequis côté serveur source

Serveur cible recommandé :

```text
Debian ou Ubuntu
accès root ou sudo
systemd
Bash
Python 3 standard library
accès réseau sortant vers les NAS
Docker si serveur Docker
```

Paquets attendus :

```bash
sudo apt update
sudo apt install -y \
  restic \
  openssh-client \
  python3 \
  postgresql-client \
  mariadb-client \
  mailutils
```

Selon le serveur, `mysql-client` peut remplacer `mariadb-client`.

### 8.1 Prérequis DB

Pour chaque DB critique, il faut connaître :

```text
moteur : PostgreSQL ou MariaDB/MySQL
mode : local, Docker ou remote
host/port si local ou remote
nom du conteneur si Docker
nom de la base
utilisateur DB
mot de passe DB
besoin de dump global PostgreSQL oui/non
```

Les mots de passe DB doivent être stockés côté serveur, jamais dans Git.

Exemple PostgreSQL :

```text
/etc/server-backup/secrets/db/cis/postgres.env
```

Contenu :

```bash
PGPASSWORD="mot_de_passe"
```

Droits :

```bash
sudo chmod 600 /etc/server-backup/secrets/db/cis/postgres.env
sudo chown root:root /etc/server-backup/secrets/db/cis/postgres.env
```

### 8.2 Prérequis SMTP

Le système de backup n'implémente pas la configuration SMTP complète.

Il suppose qu'un des mécanismes suivants fonctionne déjà sur le serveur :

```text
/usr/sbin/sendmail -t
mail
mailx
```

À préparer séparément :

```text
MTA local ou relais SMTP
SPF/DKIM/DMARC si nécessaire
authentification SMTP éventuelle
expéditeur autorisé
```

Test attendu avant activation des rapports :

```bash
printf "Subject: test server-backup\n\nTest email\n" | sendmail -t admin@example.net
```

ou :

```bash
echo "Test email" | mail -s "test server-backup" admin@example.net
```

Le wizard doit seulement demander :

```text
activer rapports email ?
adresse destinataire
adresse expéditeur
envoyer aussi en cas de succès ?
envoyer en cas d'échec ?
commande : sendmail ou mail
```

---

## 9. Prérequis côté NAS distant

Le stockage distant doit être générique. Il peut être :

```text
OMV
Synology
QNAP
TrueNAS
serveur Linux dédié
storage SFTP
rest-server
S3
rclone
```

Backend minimal recommandé :

```text
SFTP via SSH
```

À préparer sur chaque NAS :

```text
utilisateur dédié
accès SSH/SFTP activé
authentification par clé SSH
dossier dédié au dépôt restic
droits lecture/écriture pour l'utilisateur dédié
quota ou espace disque suffisant
snapshots locaux côté NAS si possible
accès réseau depuis le serveur source
```

Recommandation espace disque :

```text
minimum par serveur sauvegardé : 200 Go
confortable : 500 Go
très confortable : 1 To
```

Chemin recommandé par serveur :

```text
/backups/<server-name>/restic
```

Exemple :

```text
/backups/pyparfums-prod/restic
```

Sécurité recommandée :

```text
pas de login root SSH
clé SSH dédiée par serveur source
utilisateur distant non admin
restriction par IP source si possible
pas de shell interactif si SFTP-only possible
snapshots Btrfs/ZFS côté NAS si possible
```

---

## 10. Préparation NAS OMV

### 10.1 Shared folder

Dans OMV :

```text
Storage > Shared Folders > Create
```

Exemple :

```text
Name : backup_pyparfums
Path : backups/pyparfums-prod
```

Chemin réel possible :

```text
/srv/dev-disk-by-uuid-XXXX/backups/pyparfums-prod
```

Le dépôt restic sera par exemple :

```text
/srv/dev-disk-by-uuid-XXXX/backups/pyparfums-prod/restic
```

### 10.2 Utilisateur dédié

Dans OMV :

```text
Users > Users > Create
```

Exemple :

```text
username : backup-pyparfums
```

Droits :

```text
lecture/écriture uniquement sur backup_pyparfums
aucun droit admin
aucun accès aux autres partages
```

### 10.3 SSH/SFTP

Dans OMV :

```text
Services > SSH
```

Activer :

```text
Enable SSH : yes
Permit root login : no
Public key auth : yes
Password authentication : no après validation des clés
```

Pendant le premier test, le mot de passe peut rester activé temporairement. L'objectif final est clé SSH uniquement.

### 10.4 Clé publique

Le wizard côté serveur générera une clé publique à copier dans le compte NAS.

Exemple :

```bash
sudo server-backup target add
```

Puis copier la clé affichée dans `authorized_keys` de l'utilisateur `backup-pyparfums`.

Restriction recommandée dans `authorized_keys` :

```text
from="IP_PUBLIQUE_DU_SERVEUR",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty ssh-ed25519 AAAA...
```

### 10.5 Snapshots locaux OMV

Si le filesystem OMV le permet, activer des snapshots locaux du dossier backup.

But : protéger le dépôt restic contre une suppression malveillante ou accidentelle depuis le serveur source.

---

## 11. Préparation NAS Synology

### 11.1 Dossier partagé

Dans DSM :

```text
Control Panel > Shared Folder > Create
```

Exemple :

```text
Shared folder : backups
Sous-dossier : pyparfums-prod/restic
```

Chemin SFTP typique selon configuration :

```text
/volume1/backups/pyparfums-prod/restic
```

### 11.2 Utilisateur dédié

Dans DSM :

```text
Control Panel > User & Group > Create
```

Exemple :

```text
username : backup-pyparfums
```

Permissions :

```text
Read/Write sur backups
No access sur les autres dossiers
pas de permission admin
```

### 11.3 Activer SSH

Dans DSM :

```text
Control Panel > Terminal & SNMP > Enable SSH service
```

Recommandé :

```text
port SSH dédié ou VPN
clé SSH uniquement si possible
restriction IP via firewall Synology
```

### 11.4 Clé SSH

Copier la clé publique générée par le wizard dans :

```text
/var/services/homes/backup-pyparfums/.ssh/authorized_keys
```

Vérifier les droits :

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

### 11.5 Snapshots Synology

Si le paquet Snapshot Replication est disponible, activer des snapshots du dossier `backups`.

Rétention indicative :

```text
snapshots horaires sur 24 h
snapshots quotidiens sur 14 jours
snapshots hebdomadaires sur 8 semaines
```

À adapter selon espace disponible.

---

## 12. Accès réseau NAS

Deux options.

### Option recommandée : VPN

```text
serveur source ---- VPN ---- NAS
```

Exemples :

```text
WireGuard
Tailscale
ZeroTier
OpenVPN
```

Avantages :

```text
pas de SSH exposé publiquement
migration de NAS plus simple
sécurité supérieure
```

### Option simple : port forwarding SSH

Sur la box Internet du NAS :

```text
Port externe : 2222
IP NAS locale : IP fixe du NAS
Port interne : 22
Protocole : TCP
```

Côté DNS :

```text
DDNS ou IP fixe
```

Recommandations :

```text
limiter le firewall à l'IP publique du serveur source
clé SSH uniquement
désactiver root login
surveiller les logs SSH
```

---

## 13. Installation prévue sur un serveur source

> Cette section décrit la procédure attendue après implémentation par Codex.

Clone du projet final :

```bash
git clone https://github.com/stephanerey/prd_server_backups.git
cd prd_server_backups
```

Installation :

```bash
sudo ./scripts/install.sh
```

Ce script doit :

```text
installer les dépendances
créer /etc/server-backup
créer /var/cache/restic
créer /var/lib/server-backup
installer les scripts sous /usr/local/sbin
installer la CLI server-backup sous /usr/local/bin
installer les units systemd
préserver toute configuration existante
```

Permissions attendues :

```text
/etc/server-backup                   0700 root:root
/etc/server-backup/secrets           0700 root:root
/etc/server-backup/secrets/*         0600 root:root
/etc/server-backup/ssh               0700 root:root
/etc/server-backup/ssh/id_*          0600 root:root
/etc/server-backup/targets.d/*.env   0600 root:root
/etc/server-backup/profiles.d/*.conf 0600 root:root
/var/cache/restic                    0700 root:root
/var/lib/server-backup               0700 root:root
```

---

## 14. Configuration avec le wizard

### 14.1 Configuration globale

Commande :

```bash
sudo server-backup setup
```

Questions attendues :

```text
nom logique du backup
tags
rétention daily/weekly/monthly
heure du timer systemd
activer prune
activer restic check
activer coverage audit
activer rapports email
email destinataire
email expéditeur
envoyer en cas de succès
envoyer en cas d'échec
commande email : sendmail ou mail
```

Exemple de configuration générée :

```bash
BACKUP_NAME="pyparfums-prod"
BACKUP_TAGS="pyparfums prod ovh docker"

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

EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="admin@example.net"
EMAIL_REPORT_FROM="server-backup@example.net"
EMAIL_REPORT_SUBJECT_PREFIX="[server-backup]"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
EMAIL_REPORT_COMMAND="sendmail"
```

### 14.2 Ajout d'une destination NAS

Commande :

```bash
sudo server-backup target add
```

Questions attendues :

```text
nom logique de destination
type : sftp/rest-server/s3/rclone
hostname ou IP
port SSH
utilisateur SSH
chemin distant du dépôt restic
créer une clé SSH dédiée
chemin de la clé
alias SSH
tester la connexion
initialiser le dépôt restic
```

Exemple de target SFTP :

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

Test :

```bash
sudo server-backup target test nas-home
sudo server-backup repo init nas-home
sudo server-backup repo check nas-home
```

### 14.3 Ajout d'un profil Docker host

Commande :

```bash
sudo server-backup profile add --type docker-host
```

Le wizard doit :

```text
scanner /srv, /opt, /home ou chemins custom
trouver les compose.yml et docker-compose.yml
inspecter les conteneurs
lister les volumes Docker
lister les bind mounts
identifier les chemins content/uploads/media/data/static
proposer les chemins à inclure
configurer les dumps DB
classer CIS ou autre site comme web-content-critical si nécessaire
```

Exemple de profil :

```bash
PROFILE_NAME="docker-host"
PROFILE_TYPE="docker-host"

BACKUP_PATHS=(
  "/etc"
  "/srv"
  "/opt"
  "/var/lib/server-backup/state"
  "/var/lib/docker/volumes/caddy_data/_data"
  "/var/lib/docker/volumes/caddy_config/_data"
  "/var/lib/docker/volumes/cis_data/_data"
)

EXCLUDES=(
  "/etc/server-backup/secrets"
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/__pycache__"
  "**/node_modules"
  "/var/lib/docker/overlay2"
  "/var/lib/docker/image"
  "/var/lib/docker/containers/*/*.log"
)

DOCKER_INVENTORY="true"
```

### 14.4 Configuration DB via wizard

Commande prévue :

```bash
sudo server-backup db add
```

ou via :

```bash
sudo server-backup profile add --type docker-host
```

Questions attendues :

```text
moteur : PostgreSQL ou MariaDB/MySQL
mode : local, Docker ou remote
host/port si local ou remote
nom du conteneur si Docker
nom logique du dump
base unique, plusieurs bases ou toutes les bases
utilisateur DB
mot de passe DB ou fichier secret existant
inclure PostgreSQL globals oui/non
tester la connexion maintenant
tester un dump temporaire maintenant
```

Exemple PostgreSQL Docker :

```bash
DATABASE_DUMPS=(
  "name=cis-postgres;engine=postgresql;mode=docker;container=postgres;user=cis_user;databases=cis;globals=true;secret=/etc/server-backup/secrets/db/cis/postgres.env"
)
```

Fichier secret :

```bash
PGPASSWORD="mot_de_passe"
```

Tests :

```bash
sudo server-backup db test cis-postgres
sudo server-backup db dump-test cis-postgres
```

---

## 15. Utilisation quotidienne

### 15.1 Lancer un backup manuel

```bash
sudo server-backup backup run
```

ou directement :

```bash
sudo systemctl start server-backup.service
```

### 15.2 Voir les logs

```bash
sudo journalctl -u server-backup.service -n 200 --no-pager
sudo tail -n 200 /var/log/server-backup.log
```

### 15.3 Vérifier le timer

```bash
sudo systemctl status server-backup.timer
sudo systemctl list-timers | grep server-backup
```

### 15.4 Lancer un audit de couverture

```bash
sudo server-backup coverage audit
```

### 15.5 Vérifier les snapshots restic

```bash
sudo server-backup repo check nas-home
```

ou :

```bash
sudo -i
source /etc/server-backup/targets.d/nas-home.env
restic snapshots
restic check
```

### 15.6 Test de restauration

```bash
sudo server-backup restore test --target nas-home
```

Le test doit restaurer dans un répertoire temporaire :

```text
/tmp/server-backup-restore-test-XXXX
```

Il ne doit rien écraser.

Le système doit enregistrer le dernier test réussi dans :

```text
/var/lib/server-backup/state/last-restore-test.json
```

---

## 16. Rapport email

À la fin de chaque backup, si activé, le système doit envoyer un rapport.

Sujet attendu :

```text
[server-backup] SUCCESS pyparfums-prod on hostname
[server-backup] WARNING pyparfums-prod on hostname
[server-backup] FAILURE pyparfums-prod on hostname
```

Contenu minimal :

```text
nom du backup
hostname
date début / fin
durée
statut global
profiles traités
targets traitées
résultat par target
résultat des dumps DB
résultat prune
résultat restic check
résultat coverage audit
warnings de couverture
chemin du log local
dernier restore test réussi
commandes utiles de diagnostic
```

Le rapport ne doit jamais contenir :

```text
mots de passe DB
mot de passe restic
clés SSH privées
tokens
secrets applicatifs
```

---

## 17. Restauration — principe

La restauration complète d'un serveur Docker doit suivre ce flux :

```text
1. Réinstaller serveur Linux vierge.
2. Réinstaller Docker et Docker Compose.
3. Installer server-backup.
4. Reconfigurer l'accès à la target restic.
5. Restaurer fichiers applicatifs et configs.
6. Restaurer volumes/bind mounts.
7. Restaurer dumps DB.
8. Relancer docker compose up -d.
9. Vérifier Caddy/reverse proxy.
10. Vérifier CIS/pages/uploads/médias.
```

Commande de test non destructive :

```bash
sudo server-backup restore test --target nas-home
```

Commande future de plan :

```bash
sudo server-backup disaster plan --target nas-home --snapshot latest
```

Une restauration destructive ne doit jamais être lancée sans confirmation explicite.

---

## 18. Sécurité

Principes obligatoires :

```text
secrets hors Git
droits root-only
clé SSH dédiée par target
utilisateur distant dédié
pas de login root distant
authentification par clé
restriction IP si possible
snapshots locaux NAS si possible
ne jamais sauvegarder le mot de passe restic dans son propre dépôt
```

Risque important : si le serveur source est compromis, l'attaquant peut potentiellement supprimer les backups accessibles en écriture sur le NAS.

Contremesures recommandées :

```text
snapshots locaux Btrfs/ZFS côté NAS
second NAS distant
rest-server append-only comme évolution future
restriction IP sur SSH
utilisateur SFTP sans shell interactif si possible
```

---

## 19. Roadmap PR pour Codex

Plan principal :

```text
PR1  Structure repo et documentation de base
PR2  install.sh idempotent
PR3  Configuration loader et validateurs
PR4  CLI et wizard global
PR5  Wizard target SFTP et SSH
PR6  Wizard profile
PR7  init/check repositories
PR8  backup.sh multi-target
PR9  rétention et prune
PR10 restore test
PR11 rapports email
PR12 systemd timer
PR13 documentation NAS spécifiques
PR14 documentation restauration et exploitation
PR15 qualité, shellcheck et tests simples
```

Addendums :

```text
PR16 Docker discovery et inventory
PR17 Profil docker-host
PR18 Dumps PostgreSQL Docker
PR19 Documentation restauration Docker
PR20 Web content critical services
PR21 Coverage audit
PR22 Profil system-filesystem
PR23 Restore readiness tracking
PR24 Disaster restore plan
PR25 Database connection wizard and DB dump scope
```

---

## 20. Checklist avant premier déploiement

### Serveur source

```text
[ ] OVH Premium Backup activé si serveur OVH
[ ] Docker fonctionne
[ ] Docker Compose fonctionne
[ ] chemins applicatifs connus : /srv, /opt, etc.
[ ] conteneur PostgreSQL identifié
[ ] identifiants DB récupérés
[ ] SMTP/sendmail/mail testé
[ ] accès réseau vers NAS validé
```

### NAS

```text
[ ] dossier backup créé
[ ] utilisateur dédié créé
[ ] SSH/SFTP activé
[ ] clé publique installée
[ ] accès par mot de passe désactivé après test
[ ] droits limités au dossier backup
[ ] espace disque suffisant
[ ] snapshots NAS configurés si possible
[ ] test SFTP depuis serveur source OK
```

### Configuration backup

```text
[ ] server-backup setup exécuté
[ ] target NAS ajoutée
[ ] restic init OK
[ ] profile docker-host créé
[ ] CIS marqué comme service critique si présent
[ ] volumes Docker critiques inclus
[ ] bind mounts critiques inclus
[ ] dumps DB configurés
[ ] pg_dumpall --globals-only activé si PostgreSQL
[ ] coverage audit sans failure
[ ] premier backup manuel OK
[ ] email de rapport reçu
[ ] restore test OK
```

---

## 21. Commandes attendues du projet final

```bash
sudo server-backup setup
sudo server-backup status

sudo server-backup target add
sudo server-backup target test nas-home

sudo server-backup repo init nas-home
sudo server-backup repo check nas-home

sudo server-backup docker scan
sudo server-backup docker inventory

sudo server-backup profile add --type docker-host
sudo server-backup profile add --type system-filesystem

sudo server-backup db add
sudo server-backup db test cis-postgres
sudo server-backup db dump-test cis-postgres

sudo server-backup coverage audit
sudo server-backup backup run
sudo server-backup restore test --target nas-home
sudo server-backup email test

sudo systemctl enable --now server-backup.timer
sudo systemctl start server-backup.service
sudo journalctl -u server-backup.service -n 200 --no-pager
```

---

## 22. Résumé final

Ce système ne cherche pas à remplacer un snapshot provider comme OVH Premium Backup.

Il ajoute une sauvegarde applicative robuste :

```text
restic chiffré
multi-NAS
configuration par wizard
Docker-aware
DB-aware
site-content-aware
audit de couverture
rapport email
restore test
```

La couverture attendue pour un serveur Docker avec CIS et PostgreSQL est :

```text
OVH Backup 7j
  → rollback rapide.

Restic vers NAS
  → /etc, /srv, /opt, Compose, .env, volumes, bind mounts.

Dumps DB
  → bases applicatives + globals PostgreSQL.

CIS
  → pages en DB ou fichiers, uploads, médias, assets.

Coverage audit
  → signale ce qui manque.

Restore test
  → vérifie que la restauration fonctionne.
```
