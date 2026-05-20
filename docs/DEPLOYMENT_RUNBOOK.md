# Deployment Runbook

## Vue d'ensemble

Ce document est le guide principal pour déployer `server-backup` sur un nouveau
serveur Linux.

Objectif :

- installer le socle host-level ;
- préparer la connectivité NAS et VPN ;
- configurer la target SFTP ;
- initialiser le dépôt `restic` ;
- créer les profiles ;
- configurer les dumps DB logiques ;
- vérifier la couverture ;
- exécuter un premier backup, un prune et un restore test ;
- activer ensuite l'exploitation récurrente.

Le flux décrit ici correspond à la procédure validée sur le VPS
`mes-fragrances`, sans inclure de secret réel.

## Prérequis

- Debian ou Ubuntu supporté
- accès `root` ou `sudo`
- `git`, `python3`, `systemd`
- accès réseau au NAS cible, directement ou via WireGuard
- MTA local prêt si les rapports email doivent partir du serveur
- espace libre local pour :
  - `/var/cache/restic`
  - `/var/lib/server-backup`
  - `/var/tmp/server-backup`

## Architecture cible

```text
Serveur source
├── /etc/server-backup
├── /var/lib/server-backup
├── /var/cache/restic
└── server-backup
     ├── target SFTP -> NAS
     ├── profiles fichiers/applications
     ├── dumps DB logiques
     ├── backup/prune/restore test
     └── rapports locaux + email

NAS / cible distante
└── dépôt restic via SFTP
```

## Ordre des PR / fonctionnalités

Ordre fonctionnel déjà validé :

- PR1-PR4 : socle local, setup global, timer, config
- PR5 : target SFTP + SSH dédiée
- PR6 : profiles
- PR7 : repo `init/check/snapshots`
- PR8 : `backup run`
- PR9 : rétention `forget/prune`
- PR10 : `restore test`
- PR11 : rapports email via MTA local
- PR12 : `coverage audit`
- PR13 : dumps DB logiques
- PR14 : couverture Docker assistée
- PR15 : présent runbook opérateur
- PR16 : hardening, health, operations status, scheduling
- PR17 : validation finale v1.0

## Préparation NAS

Préparer le NAS avant toute création de target :

- créer un utilisateur dédié au backup
- créer le dossier du dépôt `restic`
- limiter les droits au strict nécessaire
- activer SSH/SFTP
- préparer `authorized_keys`
- vérifier que l'utilisateur peut atteindre le chemin du dépôt

Pour OMV + WireGuard, suivre aussi
[NAS_OMV_WIREGUARD_RUNBOOK.md](NAS_OMV_WIREGUARD_RUNBOOK.md).

## Préparation VPN WireGuard

Si le NAS n'est pas exposé publiquement :

- installer WireGuard sur le NAS et sur le VPS
- créer les peers
- vérifier les routes
- noter l'IP WireGuard du NAS
- utiliser cette IP comme `SSH_HOSTNAME` de la target `server-backup`

Vérifications minimales :

```bash
ping -c 3 <wireguard-nas-ip>
ssh <user>@<wireguard-nas-ip>
sftp <user>@<wireguard-nas-ip>
```

## Installation serveur source

### Phase A — socle local

Installer le dépôt et le socle jusqu'au setup global :

```bash
git clone <repo-url>
cd prd_server_backups
sudo ./scripts/install.sh
sudo server-backup setup
```

Après `setup`, vérifier :

- `/etc/server-backup/backup.conf`
- `/etc/server-backup/secrets/restic-password` si généré
- `server-backup.timer` installé mais désactivé par défaut

Commandes utiles :

```bash
sudo server-backup status
sudo server-backup health
sudo server-backup config validate
systemctl cat server-backup.timer
systemctl status server-backup.timer --no-pager
```

## Configuration globale

Le wizard `setup` configure notamment :

- `BACKUP_NAME`
- `BACKUP_TAGS`
- rétention `daily/weekly/monthly`
- `RESTIC_PASSWORD_FILE`
- `RESTIC_CACHE_DIR`
- `LOCAL_DUMP_DIR`
- options `RUN_RESTIC_CHECK`, `RUN_PRUNE`, `RUN_COVERAGE_AUDIT`
- email reports
- heure du timer systemd

Conserver le mot de passe `restic` hors serveur dès cette étape.

## Configuration target SFTP

### Phase B — réseau et NAS

Interrompre le flux ici si le NAS ou WireGuard ne sont pas prêts.

Checklist minimale :

- NAS accessible
- utilisateur SSH/SFTP prêt
- dossier dépôt prêt
- clé publique prête à être installée
- WireGuard fonctionnel si utilisé

### Phase C — target

Créer ensuite la target :

```bash
sudo server-backup target add
sudo server-backup target test <target>
```

Étapes opérateur :

- copier la clé publique dans `authorized_keys` côté NAS
- vérifier `ssh_config` dédié
- vérifier `known_hosts`
- confirmer que `target test` renvoie `OK`

## Initialisation repo restic

### Phase D — repo restic

Quand `target test` est `OK` :

```bash
sudo server-backup repo init <target>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

Résultat attendu pour un dépôt vide :

- `repo init` : succès
- `repo snapshots` : `No snapshots found`
- `repo check` : succès

## Création profiles

### Phase E — profiles

Créer au minimum :

- un profile `system-filesystem`
- ou un profile applicatif
- ou un profile `cis-site` si le serveur héberge une application CIS

Commandes :

```bash
sudo server-backup profile add
sudo server-backup config validate
sudo server-backup status
```

Pour Docker, préférer ensuite :

```bash
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
```

## Configuration dumps DB

### Phase F — DB

Configurer ensuite les dumps logiques :

```bash
sudo server-backup db add
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

Ordre recommandé :

1. créer le secret DB root-only
2. ajouter `DATABASE_DUMPS` au bon profile
3. tester la connexion
4. tester un dump temporaire

Le dump logique est la couverture principale d'une DB. Le volume Docker brut
reste optionnel.

## Coverage audit

### Phase G — coverage

Vérifier ensuite la couverture réelle :

```bash
sudo server-backup coverage audit
sudo server-backup docker coverage
```

Corriger les warnings avant le premier vrai backup :

- chemins `BACKUP_PATHS` absents
- `.env` non couverts
- volumes applicatifs Docker non couverts
- `cis-site` sans `CONTENT_CLASSIFICATION`
- `cis-site` sans `DATABASE_DUMPS`

## Premier backup dry-run

### Phase H — premier backup

Faire d'abord un test sans créer de snapshot :

```bash
sudo server-backup backup run --dry-run --target <target>
```

Puis faire un premier backup réel, de préférence limité à un profile :

```bash
sudo server-backup backup run --target <target> --profile <profile>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

Résultat attendu :

- un nouveau snapshot visible
- `repo check` toujours `OK`
- rapport local `backup-run-*.txt` et `backup-run-*.json`

## Premier backup réel

Le premier backup réel doit être lancé seulement après :

- target test validé
- repo init/check validés
- coverage audit acceptable
- dump DB testé si base critique

Ne pas activer le timer avant ce premier backup réel validé.

## Prune / rétention

### Phase I — prune

> `repo prune --yes` est une opération destructive.

Toujours commencer par un dry-run :

```bash
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune <target> --yes
```

Puis revérifier :

```bash
sudo server-backup repo check <target>
sudo server-backup repo snapshots <target>
```

## Restore test

### Phase J — restore test

Le restore test est non destructif et restaure sous `/tmp`.

```bash
sudo server-backup restore test --target <target> --keep-output
sudo server-backup restore test --target <target>
```

Vérifier :

- le rapport `restore-test-*`
- le statut final
- la présence des chemins critiques restaurés

Un warning peut être normal si le snapshot ne contient qu'un sous-ensemble
volontaire des chemins d'un profile.

## Email reports

### Phase K — email

Préparer d'abord un MTA local fonctionnel :

- Postfix avec relay SMTP
- ou `mail` / `mailx`

Ensuite :

```bash
sudo server-backup email test
```

Puis activer dans `backup.conf` :

- `EMAIL_REPORT_ENABLED="true"`
- `EMAIL_REPORT_TO`
- `EMAIL_REPORT_FROM`
- `EMAIL_REPORT_COMMAND`

Enfin, refaire un dry-run :

```bash
sudo server-backup backup run --dry-run --target <target>
```

Pour un relais Postfix via OVH, voir
[POSTFIX_OVH_RELAY.md](POSTFIX_OVH_RELAY.md).

## Activation timer systemd

### Phase L — timer

Le timer ne doit être activé qu'après validation complète :

```bash
sudo server-backup health
sudo server-backup operations status
sudo systemctl enable --now server-backup.timer
sudo systemctl list-timers | grep server-backup
sudo systemctl status server-backup.timer --no-pager
```

Vérifications minimales avant activation :

- `health` sans `FAILURE`
- dernier backup récent
- dernier restore test présent
- dernier coverage audit récent
- email reports validés si activés
- `repo check` OK

Avant l'activation finale, il est recommandé d'exécuter aussi :

```bash
sudo server-backup validate production --target <target> --profile <profile>
```

## Exploitation quotidienne

Routine minimale :

```bash
sudo server-backup status
sudo server-backup health
sudo server-backup operations status
sudo server-backup config validate
sudo server-backup coverage audit
sudo server-backup restore test --target <target>
```

Pour l'exploitation détaillée, voir
[OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md).

## Dépannage

Incidents fréquents documentés dans
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) :

- SSH/SFTP NAS
- WireGuard
- dépôt `restic`
- lock local `server-backup`
- Postfix / Gmail
- coverage Docker
- restore test

## Checklist finale

Avant mise en production récurrente :

- `target test` OK
- `repo init/check` OK
- au moins un profile valide
- dumps DB validés si DB critique
- `coverage audit` acceptable
- premier backup réel réussi
- `repo snapshots` affiche le snapshot
- `repo prune --dry-run` validé
- `restore test` exécuté
- `email test` validé si emails activés
- timer activé seulement après tout le reste

Checklist concise :
[INSTALLATION_CHECKLIST.md](INSTALLATION_CHECKLIST.md)

Validation finale v1.0 :
[FINAL_VALIDATION.md](FINAL_VALIDATION.md)
