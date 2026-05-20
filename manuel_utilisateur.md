# Manuel utilisateur — server-backup

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Installation initiale](#2-installation-initiale)
3. [Configuration globale](#3-configuration-globale)
4. [Target SFTP et dépôt restic](#4-target-sftp-et-dépôt-restic)
5. [Profiles, Docker et dumps DB](#5-profiles-docker-et-dumps-db)
6. [Backups, prune et restore test](#6-backups-prune-et-restore-test)
7. [Exploitation quotidienne](#7-exploitation-quotidienne)
8. [Commandes potentiellement destructives](#8-commandes-potentiellement-destructives)
9. [Exemple réel validé](#9-exemple-réel-validé)
10. [Documentation associée](#10-documentation-associée)

## 1. Vue d'ensemble

`server-backup` fonctionne directement sur l'hôte Linux. Il orchestre les
configurations locales, les targets SFTP, les dépôts `restic`, les dumps DB
logiques, les rapports locaux/email et les vérifications opérateur.

Emplacements importants :

```text
/etc/server-backup/backup.conf
/etc/server-backup/targets.d/*.env
/etc/server-backup/profiles.d/*.conf
/etc/server-backup/secrets/
/etc/server-backup/ssh/
/var/lib/server-backup/state/
/var/lib/server-backup/reports/
/var/cache/restic/
```

Ne jamais commiter les fichiers sensibles présents sous `/etc/server-backup`.

## 2. Installation initiale

Depuis le dépôt :

```bash
cd prd_server_backups
sudo ./scripts/install.sh
```

Après installation :

```bash
server-backup --help
sudo server-backup status
sudo server-backup health
sudo server-backup config validate
```

Important pour la v1 :

- `install.sh` installe `/etc/server-backup/backup.conf.example`
- il ne crée plus automatiquement `/etc/server-backup/backup.conf`
- la vraie configuration globale doit être générée via `sudo server-backup setup`

## 3. Configuration globale

Commande interactive :

```bash
sudo server-backup setup
```

Cette commande configure notamment :

- `BACKUP_NAME`
- `BACKUP_TAGS`
- `RETENTION_DAILY`, `RETENTION_WEEKLY`, `RETENTION_MONTHLY`
- `RESTIC_PASSWORD_FILE`
- `RESTIC_CACHE_DIR`
- `RUN_RESTIC_CHECK`, `RUN_PRUNE`, `RUN_COVERAGE_AUDIT`
- la planification du timer systemd
- les rapports email

Vérifications recommandées :

```bash
sudo server-backup config validate
sudo server-backup status
sudo server-backup operations status
```

## 4. Target SFTP et dépôt restic

Créer la target :

```bash
sudo server-backup target add
```

Tester la connectivité :

```bash
sudo server-backup target test <target>
```

Initialiser et vérifier le dépôt :

```bash
sudo server-backup repo init <target>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

Le dépôt `restic` doit être prêt avant le premier vrai backup.

## 5. Profiles, Docker et dumps DB

Créer un profile :

```bash
sudo server-backup profile add
```

Configurer un dump logique DB si nécessaire :

```bash
sudo server-backup db add
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

Vérifier la couverture :

```bash
sudo server-backup coverage audit
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
```

Ajouter manuellement des chemins Docker proposés :

```bash
sudo server-backup docker add-missing-paths --profile <profile> --dry-run
sudo server-backup docker add-missing-paths --profile <profile>
```

## 6. Backups, prune et restore test

Premier backup dry-run :

```bash
sudo server-backup backup run --dry-run --target <target>
```

Premier backup réel ciblé :

```bash
sudo server-backup backup run --target <target> --profile <profile>
```

Rétention :

```bash
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune <target> --yes
```

Restore test non destructif :

```bash
sudo server-backup restore test --target <target>
sudo server-backup restore test --target <target> --keep-output
```

## 7. Exploitation quotidienne

Commandes courantes :

```bash
sudo server-backup status
sudo server-backup health
sudo server-backup operations status
sudo server-backup validate production --target <target> --profile <profile>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
sudo server-backup coverage audit
```

Emails et timer :

```bash
sudo server-backup email test
sudo systemctl enable --now server-backup.timer
sudo systemctl list-timers | grep server-backup
systemctl status server-backup.timer --no-pager
```

## 8. Commandes potentiellement destructives

Les commandes suivantes doivent être relues avant exécution :

- `sudo server-backup repo prune <target> --yes`
- `sudo systemctl enable --now server-backup.timer`
- toute modification manuelle des profiles ou targets en production

Règles opérateur :

- toujours commencer par `prune --dry-run`
- ne jamais restaurer en production depuis `restore test`
- ne jamais lancer plusieurs opérations `restic` en parallèle
- ne jamais exposer le mot de passe `restic`, les clés SSH, les secrets DB ou SMTP

## 9. Exemple réel validé

Les valeurs ci-dessous proviennent d'un déploiement validé. Elles sont données
comme exemple opérateur, pas comme valeurs par défaut génériques.

```text
Target name                  : nas-steph
SFTP hostname or IP          : 10.192.1.254
Remote SSH user              : backup_mesfragrances
Remote restic repository path: /srv/dev-disk-by-uuid-.../backup_mesfragrances/restic
Profile applicatif           : mes-fragrances-cis
```

Exemples de commandes validées :

```bash
sudo server-backup target test nas-steph
sudo server-backup repo check nas-steph
sudo server-backup backup run --dry-run --target nas-steph
sudo server-backup backup run --target nas-steph --profile mes-fragrances-cis
sudo server-backup restore test --target nas-steph --keep-output
sudo server-backup validate production --target nas-steph --profile mes-fragrances-cis
```

## 10. Documentation associée

- [README.md](README.md)
- [Server install](docs/SERVER_INSTALL.md)
- [Deployment runbook](docs/DEPLOYMENT_RUNBOOK.md)
- [Operations runbook](docs/OPERATIONS_RUNBOOK.md)
- [Restore kit](docs/RESTORE_KIT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Final validation](docs/FINAL_VALIDATION.md)
