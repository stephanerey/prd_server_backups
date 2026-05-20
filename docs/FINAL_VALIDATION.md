# Final Validation

## Objectif

Ce document décrit la validation finale v1.0 avant activation du timer et
passage en exploitation récurrente.

## 1. Vérifier la configuration

```bash
sudo server-backup config validate
```

## 2. Vérifier la santé locale

```bash
sudo server-backup health
sudo server-backup operations status
```

## 3. Vérifier la target

```bash
sudo server-backup target test <target>
```

## 4. Vérifier le dépôt restic

```bash
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```

## 5. Vérifier les bases

```bash
sudo server-backup db list
sudo server-backup db test <name>
sudo server-backup db dump-test <name>
```

## 6. Vérifier la couverture

```bash
sudo server-backup coverage audit
sudo server-backup docker coverage
```

## 7. Vérifier le backup

Dry-run :

```bash
sudo server-backup backup run --dry-run --target <target> --profile <profile>
```

Backup réel :

```bash
sudo server-backup backup run --target <target> --profile <profile>
```

## 8. Vérifier le prune

```bash
sudo server-backup repo prune <target> --dry-run
```

## 9. Vérifier le restore test

```bash
sudo server-backup restore test --target <target> --keep-output
```

## 10. Vérifier l'email

```bash
sudo server-backup email test
```

## 11. Vérifier le timer

```bash
systemctl status server-backup.timer
systemctl list-timers | grep server-backup
```

## 12. Activer le timer

Une fois toute la validation terminée :

```bash
sudo systemctl enable --now server-backup.timer
```

## Commande synthétique non destructive

La commande suivante regroupe les checks de production non destructifs :

```bash
sudo server-backup validate production
sudo server-backup validate production --target <target>
sudo server-backup validate production --target <target> --profile <profile>
sudo server-backup validate production --target <target> --profile <profile> --backup-dry-run
sudo server-backup validate production --target <target> --restore-test
sudo server-backup validate production --target <target> --email-test
```

Par défaut, cette commande :

- ne lance pas de backup réel
- ne lance pas de prune réel
- n'active pas le timer
- ne modifie pas la configuration

## Critère final avant v1.0

Avant d'activer le timer :

- `config validate` OK
- `health` sans `FAILURE`
- target test OK
- repo check OK
- dumps DB validés si DB critique
- coverage audit acceptable
- backup réel validé
- prune dry-run validé
- restore test validé
- email test validé si emails activés
- restore kit stocké hors serveur
