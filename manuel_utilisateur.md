# Manuel utilisateur — server-backup

Ce manuel regroupe les commandes utiles pour configurer, vérifier, exécuter et exploiter `server-backup`.

Le système fonctionne directement sur l'hôte Linux. Il ne tourne pas dans Docker. Docker est uniquement une cible inspectée/sauvegardée.

---

## 1. Vue d'ensemble

`server-backup` s'appuie sur :

```text
restic      : moteur de backup chiffré
SFTP/SSH    : transport vers NAS distant
systemd     : planification automatique
Postfix     : envoi local des rapports email via sendmail
Docker CLI  : inspection locale des conteneurs/volumes
```

Architecture type :

```text
VPS / serveur source
 ├── /etc/server-backup             configuration
 ├── /var/lib/server-backup         état + rapports
 ├── /var/cache/restic              cache restic
 └── WireGuard/SFTP                 accès NAS

NAS distant
 └── dépôt restic chiffré
```

---

## 2. Emplacements importants

### Configuration

```text
/etc/server-backup/backup.conf
/etc/server-backup/targets.d/*.env
/etc/server-backup/profiles.d/*.conf
/etc/server-backup/secrets/
/etc/server-backup/ssh/
```

### État local

```text
/var/lib/server-backup/state/
/var/lib/server-backup/reports/
```

### Logs

```text
journalctl -u server-backup.service
/var/log/server-backup.log si utilisé
/var/log/mail.log pour Postfix
```

### Fichiers sensibles

```text
/etc/server-backup/secrets/restic-password
/etc/server-backup/secrets/db/<profile>/<dump>.env
/etc/server-backup/ssh/id_ed25519_<target>
/etc/wireguard/wg0.conf
/etc/postfix/sasl_passwd
```

Ne jamais commiter ces fichiers dans Git.

---

## 3. Installation initiale

Depuis le dépôt :

```bash
cd prd_server_backups
sudo ./scripts/install.sh
```

Vérifier :

```bash
server-backup --help
sudo server-backup status
sudo server-backup config validate
```

L'installation doit créer les répertoires :

```text
/etc/server-backup
/var/lib/server-backup
/var/cache/restic
```

Le timer n'est pas activé automatiquement.

---

## 4. Configuration globale

Commande interactive :

```bash
sudo server-backup setup
```

Cette commande configure :

```text
BACKUP_NAME
BACKUP_TAGS
RETENTION_DAILY
RETENTION_WEEKLY
RETENTION_MONTHLY
heure du timer systemd
RUN_RESTIC_CHECK
RUN_PRUNE
RUN_COVERAGE_AUDIT
EMAIL_REPORT_ENABLED
EMAIL_REPORT_TO
EMAIL_REPORT_FROM
EMAIL_REPORT_COMMAND
RESTIC_PASSWORD_FILE
```

Vérifier ensuite :

```bash
sudo server-backup config validate
sudo server-backup status
```

Éditer manuellement si nécessaire :

```bash
sudo nano /etc/server-backup/backup.conf
```

Exemple email :

```bash
EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="user1@example.com,user2@example.com"
EMAIL_REPORT_FROM="admin@example.com"
EMAIL_REPORT_COMMAND="sendmail"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
```

---

## 5. Configuration NAS / target SFTP

### Ajouter une target

```bash
sudo server-backup target add
```

Informations demandées :

```text
Target name
SFTP hostname/IP
SSH port
Remote SSH user
Remote restic repository path
Génération clé SSH dédiée
Récupération host key
Test SFTP
```

Exemple :

```text
Target name                  : nas-steph
Target type                  : sftp
SFTP hostname or IP          : 10.192.1.254
SSH port                     : 22
Remote SSH user              : backup_mesfragrances
Remote restic repository path: /srv/dev-disk-by-uuid-.../backup_mesfragrances/restic
```

Le wizard affiche une clé publique à copier côté NAS dans :

```text
/home/<user>/.ssh/authorized_keys
```

### Tester la target

```bash
sudo server-backup target test nas-steph
```

Résultat attendu :

```text
Validation: OK
SSH batch test: OK
SFTP batch test: OK
```

### Voir les targets

```bash
sudo server-backup status
sudo server-backup config show
```

---

## 6. Dépôt restic

### Initialiser le dépôt

```bash
sudo server-backup repo init nas-steph
```

### Lister les snapshots

```bash
sudo server-backup repo snapshots nas-steph
```

### Vérifier le dépôt

```bash
sudo server-backup repo check nas-steph
```

### Appliquer la rétention

Dry-run :

```bash
sudo server-backup repo prune nas-steph --dry-run
```

Prune réel :

```bash
sudo server-backup repo prune nas-steph --yes
```

Valeurs utilisées :

```text
RETENTION_DAILY
RETENTION_WEEKLY
RETENTION_MONTHLY
```

### Déverrouiller un dépôt restic

À utiliser uniquement si aucune opération restic/server-backup ne tourne.

Vérifier d'abord :

```bash
ps aux | grep -E "restic|server-backup" | grep -v grep
sudo fuser /run/server-backup-repo.lock
```

Déverrouiller manuellement :

```bash
sudo -i
source /etc/server-backup/backup.conf
source /etc/server-backup/targets.d/nas-steph.env

restic \
  -r "$RESTIC_REPOSITORY" \
  --password-file "$RESTIC_PASSWORD_FILE" \
  -o "sftp.command=ssh -F ${SSH_CONFIG_FILE} ${SSH_HOST_ALIAS} -s sftp" \
  unlock
```

Puis :

```bash
sudo server-backup repo snapshots nas-steph
sudo server-backup repo check nas-steph
```

---

## 7. Profiles de backup

Un profile définit **quoi sauvegarder**.

Une target définit **où sauvegarder**.

### Créer un profile

```bash
sudo server-backup profile add
```

Types disponibles :

```text
generic
system-filesystem
docker-host
docker-app
cis-site
```

### Exemple profile CIS

Fichier :

```text
/etc/server-backup/profiles.d/mes-fragrances-cis.conf
```

Contenu type :

```bash
PROFILE_NAME="mes-fragrances-cis"
PROFILE_TYPE="cis-site"
APP_KIND="cis-site"
WEB_CONTENT_CRITICAL="true"
DOCKER_INVENTORY="true"

BACKUP_PATHS=(
  "/home/eva/mes-fragrances_CIS"
  "/home/eva/mes-fragrances_CIS/frontend"
  "/home/eva/mes-fragrances_CIS/backend"
  "/home/eva/mes-fragrances_CIS/backend/alembic"
  "/home/eva/mes-fragrances_CIS/frontend/public"
  "/var/lib/docker/volumes/mes-fragrances_cis_caddy_config/_data"
  "/var/lib/docker/volumes/mes-fragrances_cis_caddy_data/_data"
  "/var/lib/server-backup/state"
)

EXCLUDES=(
  "**/.cache"
  "**/cache"
  "**/tmp"
  "**/__pycache__"
  "**/node_modules"
  "**/.next/cache"
  "**/logs/*.log"
  "**/.git"
)
```

### Valider les profiles

```bash
sudo server-backup config validate
sudo server-backup status
```

---

## 8. Dumps de bases de données

### Ajouter une DB

```bash
sudo server-backup db add
```

Options :

```bash
sudo server-backup db add --profile mes-fragrances-cis
```

### Lister les DB configurées

```bash
sudo server-backup db list
```

### Tester la connexion DB

```bash
sudo server-backup db test pilot-postgres
```

### Tester un dump DB

```bash
sudo server-backup db dump-test pilot-postgres
```

Option pour conserver la sortie temporaire :

```bash
sudo server-backup db dump-test pilot-postgres --keep-output
```

### Emplacement secrets DB

```text
/etc/server-backup/secrets/db/<profile>/<dump>.env
```

Exemple PostgreSQL :

```bash
PGPASSWORD="..."
```

Permissions :

```bash
sudo chmod 700 /etc/server-backup/secrets/db/<profile>
sudo chmod 600 /etc/server-backup/secrets/db/<profile>/<dump>.env
```

### Exemple DATABASE_DUMPS

```bash
DATABASE_DUMPS=(
  "name=pilot-postgres;engine=postgresql;mode=docker;container=mes-fragrances_cis-db-1;user=pilot;databases=pilot;globals=true;secret=/etc/server-backup/secrets/db/mes-fragrances-cis/pilot-postgres.env"
)
```

---

## 9. Backup run

### Dry-run

```bash
sudo server-backup backup run --dry-run --target nas-steph
```

Ciblé sur un profile :

```bash
sudo server-backup backup run --dry-run --target nas-steph --profile mes-fragrances-cis
```

### Backup réel

```bash
sudo server-backup backup run --target nas-steph --profile mes-fragrances-cis
```

### Vérifier après backup

```bash
sudo server-backup repo snapshots nas-steph
sudo server-backup repo check nas-steph
```

### Rapports

```text
/var/lib/server-backup/reports/backup-run-*.txt
/var/lib/server-backup/reports/backup-run-*.json
/var/lib/server-backup/state/last-backup-run.json
```

---

## 10. Restore test non destructif

Le restore test restaure dans `/tmp`, jamais dans la production.

### Test standard

```bash
sudo server-backup restore test --target nas-steph
```

### Conserver le dossier restauré

```bash
sudo server-backup restore test --target nas-steph --keep-output
```

### Cibler un profile

```bash
sudo server-backup restore test --target nas-steph --profile mes-fragrances-cis
```

### Cibler un snapshot

```bash
sudo server-backup restore test --target nas-steph --snapshot latest
sudo server-backup restore test --target nas-steph --snapshot <snapshot-id>
```

### Rapports

```text
/var/lib/server-backup/reports/restore-test-*.txt
/var/lib/server-backup/reports/restore-test-*.json
/var/lib/server-backup/state/last-restore-test.json
```

---

## 11. Coverage audit

### Audit global

```bash
sudo server-backup coverage audit
```

### Audit JSON

```bash
sudo server-backup coverage audit --json
```

### Cibler un profile

```bash
sudo server-backup coverage audit --profile mes-fragrances-cis
```

### Rapports

```text
/var/lib/server-backup/reports/coverage-audit-*.txt
/var/lib/server-backup/reports/coverage-audit-*.json
/var/lib/server-backup/state/last-coverage-audit.json
```

---

## 12. Docker coverage

### Scan Docker

```bash
sudo server-backup docker scan
```

### Inventaire Docker

```bash
sudo server-backup docker inventory
```

### Couverture Docker

```bash
sudo server-backup docker coverage
```

### Suggestions de correction

```bash
sudo server-backup docker suggest-profile-updates
```

### Ajouter des chemins manquants à un profile

Dry-run :

```bash
sudo server-backup docker add-missing-paths --profile mes-fragrances-cis --dry-run
```

Correction interactive :

```bash
sudo server-backup docker add-missing-paths --profile mes-fragrances-cis
```

Par volume :

```bash
sudo server-backup docker add-missing-paths --profile mes-fragrances-cis --volume <volume-name>
```

Tous les volumes non couverts :

```bash
sudo server-backup docker add-missing-paths --profile mes-fragrances-cis --all-volumes
```

---

## 13. Rapports email

### Tester l'email

```bash
sudo server-backup email test
```

Avec destinataire forcé :

```bash
sudo server-backup email test --to user@example.com
```

### Configuration dans backup.conf

```bash
EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="user1@example.com,user2@example.com"
EMAIL_REPORT_FROM="admin@example.com"
EMAIL_REPORT_COMMAND="sendmail"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
```

### Vérifier Postfix

```bash
sudo tail -n 50 /var/log/mail.log
mailq
```

Ligne attendue :

```text
relay=smtp.mail.ovh.net
status=sent
```

### Dernier email report

```bash
sudo cat /var/lib/server-backup/state/last-email-report.json
```

---

## 14. Health et operations

### Health check local

```bash
sudo server-backup health
```

Ne contacte pas le NAS et ne lance pas restic.

### Operations status

```bash
sudo server-backup operations status
```

### Status complet

```bash
sudo server-backup status
```

---

## 15. Validation production

### Validation non destructive

```bash
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis
```

### Avec backup dry-run

```bash
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis --backup-dry-run
```

### Avec restore test

```bash
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis --restore-test
```

### Rapports

```text
/var/lib/server-backup/reports/production-validation-*.txt
/var/lib/server-backup/reports/production-validation-*.json
/var/lib/server-backup/state/last-production-validation.json
```

---

## 16. Timer systemd

### Voir le timer

```bash
sudo systemctl status server-backup.timer --no-pager
systemctl list-timers | grep server-backup
systemctl cat server-backup.timer
```

### Activer le timer

```bash
sudo systemctl enable --now server-backup.timer
```

### Désactiver le timer

```bash
sudo systemctl disable --now server-backup.timer
```

### Lancer manuellement le service

```bash
sudo systemctl start server-backup.service
```

### Logs systemd

```bash
sudo journalctl -u server-backup.service -n 200 --no-pager
```

---

## 17. Exploitation quotidienne

### Vérification rapide

```bash
sudo server-backup status
sudo server-backup health
```

### Vérification hebdomadaire

```bash
sudo server-backup config validate
sudo server-backup coverage audit
sudo server-backup repo snapshots nas-steph
sudo server-backup repo check nas-steph
```

### Vérification mensuelle

```bash
sudo server-backup restore test --target nas-steph --keep-output
sudo server-backup repo prune nas-steph --dry-run
sudo server-backup email test
```

---

## 18. Routine après modification

Après modification d'un profile, d'une target, d'un secret DB ou de backup.conf :

```bash
sudo server-backup config validate
sudo server-backup coverage audit
sudo server-backup backup run --dry-run --target nas-steph
sudo server-backup health
```

Si tout est OK :

```bash
sudo server-backup backup run --target nas-steph --profile mes-fragrances-cis
```

---

## 19. Dépannage rapide

### Le timer n'est pas actif

```bash
sudo systemctl status server-backup.timer --no-pager
sudo systemctl enable --now server-backup.timer
```

### Dépôt restic verrouillé

Vérifier qu'aucune opération ne tourne :

```bash
ps aux | grep -E "restic|server-backup" | grep -v grep
sudo fuser /run/server-backup-repo.lock
```

Déverrouiller si nécessaire :

```bash
sudo -i
source /etc/server-backup/backup.conf
source /etc/server-backup/targets.d/nas-steph.env
restic -r "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE" -o "sftp.command=ssh -F ${SSH_CONFIG_FILE} ${SSH_HOST_ALIAS} -s sftp" unlock
```

### Tester SFTP

```bash
sudo server-backup target test nas-steph
```

### Tester DB

```bash
sudo server-backup db test pilot-postgres
sudo server-backup db dump-test pilot-postgres
```

### Tester email

```bash
sudo server-backup email test
sudo tail -n 50 /var/log/mail.log
```

### Voir les rapports récents

```bash
sudo ls -lah /var/lib/server-backup/reports/ | tail
```

---

## 20. Ordre recommandé de mise en service

Pour un nouveau serveur :

```text
1. Installer server-backup
2. server-backup setup
3. Préparer NAS + VPN
4. target add
5. target test
6. repo init
7. repo check
8. profile add
9. db add si nécessaire
10. coverage audit
11. docker coverage si Docker
12. backup dry-run
13. backup réel
14. repo snapshots
15. repo check
16. prune dry-run
17. restore test
18. email test
19. validate production
20. activer timer
```

---

## 21. Commandes principales résumées

```bash
sudo server-backup setup
sudo server-backup status
sudo server-backup health
sudo server-backup config validate

sudo server-backup target add
sudo server-backup target test nas-steph

sudo server-backup repo init nas-steph
sudo server-backup repo snapshots nas-steph
sudo server-backup repo check nas-steph
sudo server-backup repo prune nas-steph --dry-run
sudo server-backup repo prune nas-steph --yes

sudo server-backup profile add
sudo server-backup db add
sudo server-backup db list
sudo server-backup db test pilot-postgres
sudo server-backup db dump-test pilot-postgres

sudo server-backup coverage audit
sudo server-backup docker scan
sudo server-backup docker inventory
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates

sudo server-backup backup run --dry-run --target nas-steph --profile mes-fragrances-cis
sudo server-backup backup run --target nas-steph --profile mes-fragrances-cis

sudo server-backup restore test --target nas-steph --keep-output
sudo server-backup email test
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis

sudo systemctl enable --now server-backup.timer
sudo systemctl status server-backup.timer --no-pager
```

---

## 22. Sécurité

À conserver hors serveur :

```text
mot de passe restic
accès NAS
configuration WireGuard
secrets DB
secrets SMTP
restore kit
```

À ne jamais commiter :

```text
/etc/server-backup/secrets/
/etc/server-backup/ssh/id_ed25519_*
/etc/wireguard/wg0.conf
/etc/postfix/sasl_passwd
.env applicatifs contenant secrets
```

Rappel : sans le mot de passe restic, les backups sont inutilisables.
