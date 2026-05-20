# PRD Addendum — Couverture de backup et stratégie de restauration

Ce document complète `PRD.md`, `PRD_DOCKER_ADDENDUM.md` et `PRD_SITE_CONTENT_ADDENDUM.md`.

Objectif : éviter les oublis de données critiques et clarifier la différence entre :

- rollback image provider, ex. backup VPS OVH ;
- sauvegarde applicative restic ;
- restauration orchestrée d'un serveur Docker.

## 1. Stratégie recommandée

La stratégie cible est en trois couches :

```text
Couche 1 — Backup provider image/snapshot
Usage : rollback rapide du serveur complet sur quelques jours.
Exemple : OVH Premium Backup 7j.

Couche 2 — Backup applicatif restic
Usage : restauration portable, granulaire, long terme, hors provider.
Contenu : configs, projets Docker, volumes persistants, dumps DB, contenu web, inventaires.

Couche 3 — Procédure de restauration testée
Usage : valider que les backups permettent vraiment de reconstruire le service.
```

Le projet `server-backup` ne remplace pas le backup provider. Il le complète.

---

## 2. Pourquoi ne pas se limiter à un dump image complet

Un dump image complet est utile pour revenir rapidement en arrière, mais il n'est pas suffisant comme unique stratégie.

Limites :

- restauration souvent all-or-nothing ;
- dépendance au provider et au compte client ;
- rétention courte dans les offres provider ;
- restauration peu portable vers un autre hébergeur ;
- difficulté à restaurer seulement un fichier, un volume, une base ou un service ;
- risque de snapshot crash-consistent mais pas forcément application-consistent pour une base active ;
- si l'incident est découvert tard, les snapshots courts peuvent déjà contenir l'erreur ;
- si le serveur est compromis, restaurer une image complète peut aussi restaurer la compromission.

Conclusion :

```text
backup image provider = rollback rapide
backup applicatif restic = reconstruction fiable et portable
```

Les deux doivent coexister.

---

## 3. Mode `system-filesystem` optionnel

Le système peut proposer un profil optionnel `system-filesystem` pour sauvegarder une vue large du filesystem avec restic, sans faire un dump bloc brut.

Exemple :

```bash
PROFILE_NAME="system-filesystem"
PROFILE_TYPE="system-filesystem"

BACKUP_PATHS=(
  "/etc"
  "/root"
  "/home"
  "/srv"
  "/opt"
  "/usr/local"
  "/var/spool/cron"
  "/var/lib/server-backup/state"
)

EXCLUDES=(
  "/proc"
  "/sys"
  "/dev"
  "/run"
  "/tmp"
  "/var/tmp"
  "/mnt"
  "/media"
  "/lost+found"
  "/var/cache"
  "/var/log/*.log"
  "/var/lib/docker/overlay2"
  "/var/lib/docker/image"
  "/var/lib/docker/containers/*/*.log"
  "/etc/server-backup/secrets"
)
```

Ce profil ne remplace pas les dumps DB ni la sauvegarde explicite des volumes Docker persistants.

---

## 4. Couverture : comment être sûr de ne rien oublier

Le système doit fournir une commande :

```bash
sudo server-backup coverage audit
```

Elle doit analyser le serveur et comparer :

- services systemd personnalisés ;
- projets Docker Compose détectés ;
- conteneurs Docker actifs ;
- bind mounts Docker ;
- volumes Docker nommés ;
- bases PostgreSQL/MariaDB/MySQL détectées ou déclarées ;
- chemins candidats de contenu web ;
- reverse proxy Caddy/nginx/Traefik ;
- ports exposés ;
- fichiers `.env` liés aux projets Compose ;
- chemins réellement présents dans `BACKUP_PATHS` ;
- dumps DB réellement configurés.

La commande doit produire un rapport :

```text
/var/lib/server-backup/state/coverage-audit-YYYYMMDD-HHMMSS.txt
```

---

## 5. Règles de warning/failure

La commande `coverage audit` doit signaler au minimum :

### Failure

- service web critique déclaré mais aucun chemin de contenu ni dump DB configuré ;
- conteneur PostgreSQL détecté pour une application critique sans dump configuré ;
- target restic absente ;
- profile absent ;
- chemin critique configuré mais inexistant ;
- secret DB requis mais absent.

### Warning

- volume Docker persistant détecté mais non inclus ;
- bind mount détecté mais non inclus ;
- fichier `.env` détecté mais non inclus ;
- chemin candidat `uploads`, `media`, `content`, `data`, `storage`, `public`, `static`, `www`, `html` non classifié ;
- conteneur actif sans projet Compose retrouvé ;
- reverse proxy détecté mais configuration non incluse ;
- aucun test de restauration enregistré dans les 30 derniers jours.

---

## 6. Intégration au backup quotidien

Le backup quotidien doit pouvoir exécuter `coverage audit` avant sauvegarde.

Configuration :

```bash
RUN_COVERAGE_AUDIT="true"
COVERAGE_AUDIT_FAIL_ON_FAILURE="true"
COVERAGE_AUDIT_FAIL_ON_WARNING="false"
```

Si `COVERAGE_AUDIT_FAIL_ON_FAILURE=true`, un échec critique de couverture doit faire échouer le backup et envoyer un rapport email failure.

Les warnings doivent apparaître dans le rapport email.

---

## 7. Restauration orchestrée

Le projet doit viser une restauration quasi automatisée, mais pas promettre un vrai one-click universel.

Commande cible future :

```bash
sudo server-backup disaster restore --target nas-home --snapshot latest --profile docker-host
```

La commande doit pouvoir :

1. restaurer les fichiers vers un répertoire temporaire ;
2. afficher le plan d'actions ;
3. restaurer les projets Compose ;
4. restaurer les volumes/bind mounts sélectionnés ;
5. restaurer les dumps DB selon documentation ;
6. relancer les stacks Docker si demandé explicitement ;
7. exécuter des checks post-restore.

Par défaut, aucune restauration destructive ne doit être exécutée sans confirmation.

---

## 8. Tests de restauration obligatoires

Le système doit enregistrer la date du dernier test de restauration réussi :

```text
/var/lib/server-backup/state/last-restore-test.json
```

La commande :

```bash
sudo server-backup restore test
```

Doit mettre à jour ce fichier si le test réussit.

Le rapport email doit indiquer :

- dernier test de restauration ;
- âge du dernier test ;
- warning si > 30 jours ;
- failure optionnelle si > 90 jours selon configuration future.

---

## 9. Critères d'acceptation

- Le système documente clairement que le backup provider image et le backup restic ont des rôles différents.
- Le wizard peut créer un profil `system-filesystem` optionnel.
- `coverage audit` détecte les volumes Docker et bind mounts non couverts.
- `coverage audit` détecte les applications web critiques sans contenu sauvegardé.
- `coverage audit` détecte les bases critiques sans dump.
- Le rapport email inclut les warnings de couverture.
- Le test de restauration est daté et reporté dans l'email.

---

## 10. PR supplémentaires

### PR21 — Coverage audit

- Implémenter `server-backup coverage audit`.
- Comparer ressources détectées et configuration backup.
- Générer rapport texte.
- Intégrer les warnings/failures au rapport email.

### PR22 — Profil system-filesystem

- Ajouter wizard pour profil large `/etc`, `/srv`, `/opt`, `/home`, `/root`, `/usr/local`.
- Ajouter exclusions sûres.
- Documenter que ce profil ne remplace pas les dumps DB.

### PR23 — Restore readiness tracking

- Enregistrer le dernier test de restauration réussi.
- Ajouter warning email si test trop ancien.
- Ajouter documentation de routine mensuelle.

### PR24 — Disaster restore plan

- Ajouter commande préparatoire `server-backup disaster plan`.
- Générer un plan de restauration sans action destructive.
- Préparer future commande `disaster restore`.
