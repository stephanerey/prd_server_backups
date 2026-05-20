# Operations Runbook

## Objectif

Ce document décrit l'exploitation courante d'un serveur déjà déployé avec
`server-backup`.

## Commandes quotidiennes

Vérifications rapides :

```bash
sudo server-backup status
sudo server-backup health
sudo server-backup operations status
sudo server-backup validate production --target <target> --profile <profile>
sudo server-backup config validate
```

Tests opérateur non destructifs :

```bash
sudo server-backup backup run --dry-run
sudo server-backup coverage audit
```

Contrôles dépôt :

```bash
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

Test périodique de restauration :

```bash
sudo server-backup restore test --target <target>
```

## Commandes de diagnostic

Service systemd :

```bash
journalctl -u server-backup.service
systemctl start server-backup.service
systemctl status server-backup.timer --no-pager
systemctl list-timers | grep server-backup
systemctl enable --now server-backup.timer
systemctl disable --now server-backup.timer
```

Mail :

```bash
tail -n 100 /var/log/mail.log
mailq
```

WireGuard :

```bash
sudo wg
ip addr show
ip route
```

Connectivité target :

```bash
sudo server-backup target test <target>
```

Base de données :

```bash
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

Docker :

```bash
sudo server-backup docker scan
sudo server-backup docker coverage
sudo server-backup docker inventory
```

## Routine mensuelle

Au minimum une fois par mois :

- lancer `restore test`
- lancer `repo check`
- lancer `coverage audit`
- lancer `repo prune --dry-run`
- vérifier les emails de rapport
- vérifier l'espace libre du NAS
- vérifier l'état WireGuard
- vérifier les dumps DB

Exemple :

```bash
sudo server-backup restore test --target <target>
sudo server-backup repo check <target>
sudo server-backup coverage audit
sudo server-backup repo prune <target> --dry-run
sudo server-backup db dump-test <name>
```

## Routine de release

Avant une mise en production finale ou une validation majeure :

```bash
sudo server-backup validate production --target <target> --profile <profile>
sudo server-backup validate production --target <target> --profile <profile> --backup-dry-run
```

Si nécessaire :

```bash
sudo server-backup validate production --target <target> --restore-test
sudo server-backup validate production --target <target> --email-test
```

## Routine hebdomadaire

Au minimum une fois par semaine :

- lancer `server-backup health`
- relire `operations status`
- vérifier `coverage audit`
- vérifier l'état du timer systemd

Exemple :

```bash
sudo server-backup health
sudo server-backup operations status
sudo server-backup coverage audit
systemctl list-timers | grep server-backup
```

## Routine après changement applicatif

Relancer les contrôles après :

- ajout d'un nouveau conteneur
- nouveau volume Docker
- nouveau `.env`
- nouvelle DB
- modification du chemin du projet
- changement d'IP WireGuard

Commandes utiles :

```bash
sudo server-backup docker coverage
sudo server-backup coverage audit
sudo server-backup backup run --dry-run --target <target>
```

## Fichiers de suivi

Consulter régulièrement :

- `/var/lib/server-backup/state/last-backup-run.json`
- `/var/lib/server-backup/state/last-prune-run.json`
- `/var/lib/server-backup/state/last-restore-test.json`
- `/var/lib/server-backup/state/last-coverage-audit.json`
- `/var/lib/server-backup/state/last-email-report.json`

Et les rapports correspondants dans :

```text
/var/lib/server-backup/reports
```

## Rappels opérationnels

- ne pas lancer deux opérations `restic` en parallèle
- toujours faire un `prune --dry-run` avant un prune réel
- un `restore test` warning n'est pas forcément un échec ; relire les chemins
  réellement présents dans le snapshot
- privilégier les dumps DB logiques pour les bases
- ne pas dépendre uniquement des emails ; lire aussi les rapports locaux
- `server-backup health` reste local et rapide ; il ne contacte pas le NAS
- si `server-backup.timer` est désactivé, le réactiver explicitement après
  validation opérateur

Politique recommandée :
[SCHEDULING_POLICY.md](SCHEDULING_POLICY.md)
