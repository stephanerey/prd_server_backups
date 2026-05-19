# PRD Addendum — Restore test non destructif

Ce document complète `PRD.md`, `PRD_DOCKER_ADDENDUM.md` et `PRD_COVERAGE_AND_RESTORE_STRATEGY_ADDENDUM.md`.

Objectif : définir précisément ce que fait le test de restauration, ce qu'il valide et ce qu'il ne valide pas.

## 1. Principe

Le test de restauration doit être non destructif.

Il ne doit jamais restaurer directement dans les chemins de production.

Il ne doit jamais écraser :

```text
/etc
/srv
/opt
/var/lib/docker
bases de données de production
volumes Docker de production
```

Il restaure toujours dans un répertoire temporaire ou dans un répertoire explicitement fourni par l'opérateur.

Exemple :

```text
/tmp/server-backup-restore-test-YYYYMMDD-HHMMSS
```

---

## 2. Commandes attendues

Commande minimale :

```bash
sudo server-backup restore test --target nas-home
```

Options attendues :

```bash
sudo server-backup restore test --target nas-home --snapshot latest
sudo server-backup restore test --target nas-home --profile docker-host
sudo server-backup restore test --target nas-home --include /srv/cis
sudo server-backup restore test --target nas-home --keep-output
sudo server-backup restore test --target nas-home --output-dir /tmp/restore-test
```

Par défaut :

- utiliser le snapshot `latest` ;
- restaurer dans `/tmp/server-backup-restore-test-*` ;
- ne pas écraser de fichiers existants ;
- conserver un rapport de test dans `/var/lib/server-backup/state` ;
- nettoyer ou conserver les fichiers restaurés selon configuration ou option `--keep-output`.

---

## 3. Étapes du restore test

Le test doit effectuer les étapes suivantes :

1. charger `backup.conf` ;
2. charger la target demandée ;
3. vérifier que le dépôt restic est joignable ;
4. vérifier que le mot de passe restic fonctionne ;
5. lister les snapshots ;
6. sélectionner le snapshot demandé ou `latest` ;
7. créer un répertoire temporaire de restauration ;
8. restaurer le snapshot ou les chemins demandés avec `restic restore` ;
9. vérifier que des fichiers ont réellement été restaurés ;
10. vérifier la présence des fichiers critiques selon les profiles ;
11. vérifier les dumps DB restaurés ;
12. vérifier les fichiers Docker/CIS critiques si applicable ;
13. produire un rapport lisible ;
14. enregistrer la date du dernier test réussi ;
15. retourner un code non nul si le test échoue.

---

## 4. Vérifications minimales

Le test doit vérifier :

```text
accès au dépôt restic
mot de passe restic valide
snapshot présent
restauration possible dans un répertoire temporaire
fichiers restaurés non vides
présence des chemins critiques attendus
présence des dumps DB attendus
```

---

## 5. Vérifications Docker

Pour un profil Docker, le test doit vérifier si présents :

```text
compose.yml ou docker-compose.yml
.env déclarés ou explicitement exclus
répertoires /srv ou /opt attendus
inventaire Docker restauré
volumes/bind mounts sauvegardés selon configuration
```

Le test ne doit pas lancer `docker compose up -d` par défaut.

Le démarrage réel des conteneurs appartient à un test de restauration complet ou à une future commande `disaster restore` avec confirmation explicite.

---

## 6. Vérifications DB

Pour PostgreSQL avec dump custom format, le test doit exécuter si possible :

```bash
pg_restore --list <dump_file>
```

Pour PostgreSQL dump SQL ou `pg_dumpall`, le test doit vérifier :

- fichier non vide ;
- présence d'éléments SQL attendus ;
- taille cohérente.

Pour MariaDB/MySQL, le test doit vérifier :

- fichier non vide ;
- présence de statements SQL attendus ;
- taille cohérente.

Le test ne doit pas restaurer le dump dans la base de production.

Une restauration DB réelle doit se faire dans :

```text
base temporaire
conteneur temporaire
serveur de staging
```

ou via procédure manuelle documentée.

---

## 7. Vérifications CIS

Pour un profil `APP_KIND="cis-site"`, le test doit vérifier :

```text
backend présent
frontend présent
migrations présentes, ex. alembic ou migrations
compose.yml/docker-compose.yml présent
.env présent ou explicitement exclu
media/uploads/assets classifiés
Dump PostgreSQL présent
table de pages attendue déclarée dans le rapport
```

Si le dump PostgreSQL est au format custom, `pg_restore --list` doit permettre de vérifier la présence probable de tables critiques, par exemple `site_pages` si configurée.

Le test ne doit pas démarrer le frontend/backend ni appeler l'API en production.

Ces vérifications appartiennent à un test de restauration complet sur staging.

---

## 8. Rapport de restore test

Le test doit générer un rapport sous :

```text
/var/lib/server-backup/state/restore-test-YYYYMMDD-HHMMSS.json
/var/lib/server-backup/state/restore-test-YYYYMMDD-HHMMSS.txt
```

Contenu minimal :

```text
hostname
backup name
target
snapshot id
date du snapshot
répertoire temporaire de restauration
profiles testés
chemins restaurés
nombre de fichiers restaurés
taille restaurée
checks DB
checks Docker
checks CIS
warnings
errors
statut global
```

Le dernier test réussi doit être enregistré dans :

```text
/var/lib/server-backup/state/last-restore-test.json
```

---

## 9. Ce que le restore test ne prouve pas

Le restore test standard ne prouve pas à lui seul :

```text
qu'un serveur vierge peut redémarrer tous les services
que Docker Compose relance correctement toutes les stacks
que PostgreSQL restaure correctement dans une instance neuve
que les DNS, certificats et reverse proxy fonctionnent
que les pages web sont visuellement correctes
que les secrets externes sont disponibles
```

Pour valider cela, il faut un test de restauration complet sur serveur de staging ou VM temporaire.

---

## 10. Niveaux de test recommandés

### Niveau 1 — Restore smoke test quotidien ou hebdomadaire

- accès restic ;
- restore partiel ;
- présence de fichiers critiques ;
- vérification basique des dumps.

### Niveau 2 — Restore test mensuel

- restauration plus large dans `/tmp` ;
- vérification Docker/CIS ;
- vérification `pg_restore --list` ;
- rapport enregistré.

### Niveau 3 — Disaster restore rehearsal trimestriel

- serveur vierge ou VM temporaire ;
- réinstallation Docker ;
- restauration fichiers ;
- restauration DB dans une instance neuve ;
- lancement `docker compose up -d` ;
- tests HTTP/API ;
- vérification du site.

Le niveau 3 est le seul qui valide réellement la capacité à reconstruire complètement le service.

---

## 11. Intégration email

Le rapport email quotidien doit mentionner :

```text
dernier restore test réussi
âge du dernier restore test
warning si > 30 jours
failure optionnelle si > 90 jours selon configuration future
```

---

## 12. Critères d'acceptation

- `server-backup restore test` restaure dans un répertoire temporaire.
- Aucun fichier de production n'est écrasé.
- Le test échoue si aucun snapshot n'est disponible.
- Le test échoue si restic ne peut pas restaurer.
- Le test vérifie les dumps DB restaurés.
- Le test vérifie les fichiers Docker/CIS critiques si configurés.
- Le test enregistre `last-restore-test.json` en cas de succès.
- Le rapport email indique l'âge du dernier test.
