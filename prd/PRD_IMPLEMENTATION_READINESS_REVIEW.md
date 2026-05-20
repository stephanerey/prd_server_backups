# PRD Addendum — Revue finale de couverture et readiness Codex

Ce document complète le PRD avec une revue de couverture fonctionnelle, les points encore à préciser et les décisions d'architecture nécessaires avant implémentation.

## 1. Verdict global

Le PRD contient suffisamment d'informations pour que Codex démarre l'implémentation PR par PR.

Le périmètre fonctionnel principal est clair :

- moteur `restic` ;
- configuration par wizard ;
- destinations SFTP/NAS multi-cibles ;
- profiles applicatifs ;
- support Docker ;
- support DB ;
- support sites web critiques, dont CIS ;
- audit de couverture ;
- rapports email ;
- restore test non destructif ;
- documentation NAS et restauration.

Il reste quelques décisions et détails d'implémentation à verrouiller pour éviter les ambiguïtés.

---

## 2. Décision d'architecture : host-level service, pas Docker par défaut

Le système `server-backup` doit tourner directement sur l'hôte Linux, via scripts installés et `systemd timer`.

Il ne doit pas tourner dans un conteneur Docker séparé par défaut.

Raisons :

- accès nécessaire à `/etc`, `/srv`, `/opt`, `/root`, `/home` ;
- accès nécessaire aux volumes Docker sous `/var/lib/docker/volumes/...` ;
- accès nécessaire au socket Docker ou à `docker inspect` ;
- besoin de `systemd timer` et logs `journalctl` ;
- besoin d'exécuter `pg_dump`, `mariadb-dump`, `restic`, `ssh`, `sendmail` ;
- gestion plus simple des permissions root-only et secrets.

Une version conteneurisée pourra être étudiée plus tard, mais elle serait plus complexe car elle nécessiterait au minimum :

```text
montage read-only/read-write de nombreux chemins host
accès au docker.sock
montage des secrets
montage de /etc/server-backup
montage de /var/lib/server-backup
montage de /var/cache/restic
capabilities/permissions élevées
risque de sécurité accru
```

Décision MVP :

```text
server-backup = agent host-level installé par install.sh + systemd timer
Docker = cible à inspecter/sauvegarder, pas runtime du backup
```

---

## 3. Features couvertes par le PRD

### Backup core

- Backup quotidien automatique.
- Rétention configurable : daily, weekly, monthly.
- Multi-target indépendant.
- Dépôts restic chiffrés.
- Init/check/prune/restore-test.
- Logs locaux.
- Rapport email.

### NAS distant

- Backend minimal SFTP.
- NAS agnostique : OMV, Synology, QNAP, TrueNAS, Linux dédié.
- Clé SSH dédiée.
- Utilisateur distant dédié.
- Chemin restic configurable.
- Préparation NAS documentée.

### Docker

- Scan Compose.
- Inventaire Docker.
- Volumes Docker persistants.
- Bind mounts.
- Exclusion des layers Docker reconstructibles.
- Warnings si volumes/mounts non couverts.

### Bases de données

- PostgreSQL local, Docker, remote.
- MariaDB/MySQL local, Docker, remote.
- Dump logique.
- Mode single database, multiple databases, all databases.
- PostgreSQL globals avec `pg_dumpall --globals-only`.
- Secrets DB root-only.
- Tests de connexion et dump-test.

### CIS et sites web critiques

- Profil `cis-site`.
- Contenu builder/CMS en PostgreSQL.
- Blocs JSON/JSONB.
- Backend/frontend/migrations.
- Pages codées en dur possibles.
- Médias/uploads/assets.
- Coverage audit spécifique.

### Restauration

- Restore test non destructif dans `/tmp`.
- Vérification basique des dumps DB.
- Vérification Docker/CIS.
- Tracking du dernier test réussi.
- Plan future disaster restore.

---

## 4. Points à préciser avant ou pendant implémentation

### 4.1 Format de configuration et versioning

Ajouter un champ de version dans `backup.conf` :

```bash
CONFIG_VERSION="1"
```

Chaque fichier `.env` ou `.conf` généré devrait contenir :

```bash
GENERATED_BY="server-backup"
GENERATED_AT="YYYY-MM-DDTHH:MM:SSZ"
```

Objectif : faciliter migrations futures et debug.

### 4.2 Politique secrets et restore kit

Le PRD exclut les secrets par défaut, ce qui est sain. Mais une restauration complète nécessite certains secrets hors dépôt restic :

- mot de passe restic ;
- clés SSH privées vers NAS ;
- secrets DB ;
- secrets applicatifs `.env` si exclus ;
- informations SMTP ;
- URL/host du NAS.

Ajouter une documentation `docs/RESTORE_KIT.md`.

Elle doit expliquer que l'opérateur doit conserver hors serveur :

```text
mot de passe restic
clé SSH de backup ou moyen d'en générer une nouvelle
liste des targets
chemins des dépôts restic
procédure NAS
secrets DB si non sauvegardés
```

Important : le mot de passe restic ne doit jamais être sauvegardé dans le dépôt qu'il protège.

### 4.3 Hooks pre/post backup

Ajouter un mécanisme de hooks optionnels :

```text
/etc/server-backup/hooks.d/pre-backup.d/*.sh
/etc/server-backup/hooks.d/post-backup.d/*.sh
/etc/server-backup/hooks.d/pre-profile.d/*.sh
/etc/server-backup/hooks.d/post-profile.d/*.sh
```

Usage :

- flush applicatif ;
- mise en maintenance ;
- export custom ;
- notification externe ;
- snapshot applicatif.

Les hooks doivent être désactivés par défaut et exécutés comme root, avec logs et timeout.

### 4.4 Concurrence et locks

Le backup ne doit jamais avoir deux exécutions simultanées.

Ajouter :

- lock local via `flock` ;
- gestion restic lock ;
- option documentée pour `restic unlock`, jamais automatique sans prudence.

Configuration proposée :

```bash
LOCAL_LOCK_FILE="/run/server-backup.lock"
BACKUP_MAX_RUNTIME_SECONDS=21600
```

### 4.5 Retries et timeouts réseau

Ajouter retries par target :

```bash
TARGET_RETRY_COUNT=2
TARGET_RETRY_DELAY_SECONDS=60
RESTIC_REPOSITORY_TIMEOUT_SECONDS=3600
```

Objectif : éviter un échec complet pour une micro-coupure réseau.

### 4.6 Ressources système

Définir limites :

```bash
BACKUP_NICE=10
BACKUP_IONICE_CLASS="best-effort"
BACKUP_IONICE_PRIORITY=7
RESTIC_LIMIT_UPLOAD_KBPS=""
```

Laisser `RESTIC_LIMIT_UPLOAD_KBPS` vide par défaut.

### 4.7 Politique email en cas d'échec d'envoi

Préciser :

- si le backup réussit mais l'email échoue : statut global `WARNING` ;
- si le backup échoue et l'email échoue : code retour backup reste failure ;
- toujours écrire le rapport localement avant tentative email.

### 4.8 Fréquence des checks restic

`restic check` complet peut être coûteux.

Ajouter une politique :

```bash
RUN_RESTIC_CHECK="true"
RESTIC_CHECK_MODE="read-data-subset"
RESTIC_CHECK_SUBSET="5%"
RESTIC_FULL_CHECK_DAY="sun"
```

MVP possible : simple `restic check`, puis optimisation future.

### 4.9 Nettoyage local

Préciser que les dumps temporaires doivent être supprimés même en cas d'erreur.

Ajouter :

- trap Bash `EXIT` ;
- cleanup des vieux dossiers `/var/tmp/server-backup/*` ;
- rapport si nettoyage impossible.

### 4.10 Gestion des `.env` applicatifs

Les `.env` applicatifs sont nécessaires à la restauration, mais peuvent contenir des secrets.

Le wizard doit proposer trois choix :

```text
include-encrypted-restic : inclure dans le backup restic
exclude-manual-restore-kit : exclure et documenter dans restore kit
split : inclure .env.example et garder secrets hors backup
```

Le choix doit être explicite.

### 4.11 Test de restauration DB réel optionnel

Le restore test standard ne restaure pas les bases.

Ajouter une future option :

```bash
sudo server-backup restore db-test --target nas-home --database cis-postgres --temporary-container postgres:XX
```

Cette option restaure dans une instance temporaire, jamais en production.

### 4.12 Documentation QNAP/TrueNAS

Le README couvre OMV et Synology. Le PRD mentionne QNAP/TrueNAS.

Ajouter plus tard :

```text
docs/NAS_QNAP_EXAMPLE.md
docs/NAS_TRUENAS_EXAMPLE.md
docs/NAS_LINUX_SERVER_EXAMPLE.md
```

### 4.13 Backends non-SFTP

Le PRD mentionne rest-server, S3, rclone.

Pour éviter l'ambiguïté, préciser :

```text
MVP : SFTP uniquement
Architecture : extensible vers rest-server/S3/rclone
Implémentation future : plugins target
```

---

## 5. Documentation supplémentaire recommandée

À ajouter dans le projet final :

```text
docs/RESTORE_KIT.md
  Liste des secrets et informations à conserver hors serveur.

docs/OPERATIONS_RUNBOOK.md
  Commandes d'exploitation quotidienne, diagnostic et incidents.

docs/DISASTER_RECOVERY_DRILL.md
  Procédure trimestrielle sur VM/VPS temporaire.

docs/CONFIG_REFERENCE.md
  Référence exhaustive des variables de configuration.

docs/HOOKS.md
  Format, ordre et sécurité des hooks pre/post.

docs/TROUBLESHOOTING.md
  SSH, restic locks, DB dumps, Docker volumes, email.

docs/NAS_QNAP_EXAMPLE.md
  Préparation QNAP.

docs/NAS_TRUENAS_EXAMPLE.md
  Préparation TrueNAS.
```

---

## 6. PR supplémentaires recommandées

### PR27 — Runtime architecture and config versioning

- Documenter explicitement que le runtime MVP est host-level systemd, pas Docker.
- Ajouter `CONFIG_VERSION`.
- Ajouter métadonnées de génération dans les fichiers wizard.
- Ajouter `docs/CONFIG_REFERENCE.md`.

### PR28 — Restore kit documentation

- Ajouter `docs/RESTORE_KIT.md`.
- Documenter les secrets et informations à conserver hors serveur.
- Documenter comment repartir d'un serveur vierge avec uniquement le restore kit et le NAS.

### PR29 — Hooks pre/post backup

- Ajouter structure hooks.
- Ajouter timeouts et logs.
- Documenter ordre d'exécution.

### PR30 — Locks, retries and resource limits

- Ajouter `flock` local.
- Ajouter retries target.
- Ajouter nice/ionice.
- Ajouter timeout global.

### PR31 — Operations runbook and troubleshooting

- Ajouter `docs/OPERATIONS_RUNBOOK.md`.
- Ajouter `docs/TROUBLESHOOTING.md`.
- Couvrir SSH, restic, DB, Docker, email, locks, NAS plein.

### PR32 — Optional DB restore test to temporary instance

- Ajouter une commande optionnelle de test DB dans instance temporaire.
- Ne jamais toucher à la production.

---

## 7. Readiness Codex

Codex peut implémenter dès maintenant si on lui donne comme consigne :

```text
Implémenter le MVP host-level avec backend SFTP uniquement.
Respecter l'ordre des PR.
Ne pas implémenter Docker runtime pour server-backup.
Garder les fichiers de configuration éditables à la main.
Ne jamais stocker de secrets dans Git.
Ne jamais faire de restauration destructive sans confirmation.
```

Le MVP suffisant pour premier déploiement est :

```text
PR1 à PR15
+ PR16 Docker inventory
+ PR18 Dumps PostgreSQL Docker
+ PR21 Coverage audit minimal
+ PR25 DB wizard
+ PR26 CIS generic profile si site CIS présent
+ PR27 runtime host-level/config versioning
+ PR28 restore kit
+ PR30 locks/retries/resource limits
```

Le reste peut être livré ensuite.
