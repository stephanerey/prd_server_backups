# Scheduling Policy

## Objectif

Ce document décrit la politique de planning recommandée pour l'exploitation
récurrente de `server-backup`.

## Backup quotidien

Politique recommandée :

- un backup quotidien
- heure recommandée par défaut : `02:30`
- `RandomizedDelaySec=10m` pour éviter les collisions exactes
- timer `Persistent=true` pour rejouer un run manqué après redémarrage

Commandes utiles :

```bash
sudo systemctl enable --now server-backup.timer
sudo systemctl disable --now server-backup.timer
sudo systemctl list-timers | grep server-backup
sudo systemctl start server-backup.service
```

Le timer ne doit être activé qu'après la validation finale v1.0 :

```bash
sudo server-backup validate production --target <target> --profile <profile>
```

## Restore test

Recommandation :

- au minimum mensuel
- aussi après tout changement important de profile, de dump DB ou de target

Commande :

```bash
sudo server-backup restore test --target <target>
```

## Coverage audit

Recommandation :

- au minimum hebdomadaire
- systématiquement après changement Docker, Compose, `.env`, volumes, mounts ou
  DB

Commandes :

```bash
sudo server-backup coverage audit
sudo server-backup docker coverage
```

## Prune / rétention

Recommandation :

- vérifier régulièrement le dry-run
- exécuter le prune réel avec visibilité opérateur claire

Commandes :

```bash
sudo server-backup repo prune <target> --dry-run
sudo server-backup repo prune <target> --yes
```

La politique par défaut reste :

- `RETENTION_DAILY=14`
- `RETENTION_WEEKLY=8`
- `RETENTION_MONTHLY=12`

## Repo check

Recommandation :

- au moins mensuelle
- aussi après incident réseau, corruption suspectée ou prune réel important

Commande :

```bash
sudo server-backup repo check <target>
```

## Emails

Si les rapports email sont activés :

- vérifier le chemin MTA local
- relire aussi les rapports locaux
- ne pas dépendre uniquement des emails pour l'exploitation

## Health check

Recommandation :

- exécuter `health` régulièrement
- l'utiliser comme contrôle local rapide avant activation du timer

Commande :

```bash
sudo server-backup health
sudo server-backup operations status
```

## Principe général

- timer quotidien pour le backup
- coverage audit hebdomadaire ou après changement
- restore test mensuel
- prune avec dry-run avant toute exécution réelle
- repo check mensuel
- emails en complément, pas comme seule source de vérité
