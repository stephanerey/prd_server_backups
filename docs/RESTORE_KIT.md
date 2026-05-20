# Restore Kit

## Objectif

Le restore kit est l'ensemble minimal d'informations à conserver hors du
serveur protégé pour pouvoir reconstruire l'accès aux sauvegardes et lancer une
restauration.

Sans restore kit, des backups valides peuvent devenir inutilisables.

## À conserver hors serveur

- mot de passe `restic`
- `TARGET_NAME`
- `RESTIC_REPOSITORY`
- hostname ou IP WireGuard du NAS
- chemin exact du dépôt `restic`
- accès WireGuard
- compte SSH du NAS
- procédure de récupération de la clé SSH ou procédure de régénération
- host key NAS ou procédure de revalidation
- secrets DB
- credentials SMTP si nécessaires hors serveur
- liste des profiles
- chemins critiques par profile
- chemins volontairement exclus
- pour un `cis-site` :
  - frontend
  - backend
  - migrations
  - media/uploads/assets
- dernier coverage audit
- dernier restore test
- procédure de restauration

## Checklist restore kit

À conserver explicitement dans le kit :

- [ ] mot de passe `restic`
- [ ] `TARGET_NAME`
- [ ] `RESTIC_REPOSITORY`
- [ ] hostname/IP WireGuard NAS
- [ ] chemin dépôt restic
- [ ] accès WireGuard
- [ ] compte SSH NAS
- [ ] procédure de récupération clé SSH ou nouvelle clé
- [ ] secrets DB
- [ ] credentials SMTP si nécessaires
- [ ] liste des profiles
- [ ] dernier coverage audit
- [ ] dernier restore test
- [ ] procédure de restauration

## Règles obligatoires

- ne jamais stocker le mot de passe `restic` dans le dépôt qu'il protège
- ne jamais committer de secret dans Git
- ne jamais dépendre uniquement du serveur source pour les informations de
  récupération
- si `server-backup setup` a généré le mot de passe `restic`, le copier
  immédiatement dans le restore kit
- sans mot de passe `restic`, les sauvegardes chiffrées sont inutilisables
- ne jamais stocker le mot de passe `restic` ou une clé privée SSH dans Git

## Emplacements pratiques

Le restore kit doit exister dans au moins un emplacement externe, par exemple :

- gestionnaire de mots de passe
- document chiffré hors ligne
- runbook opérateur protégé
- second poste d'administration sécurisé

## Références utiles

- [DEPLOYMENT_RUNBOOK.md](/home/eva/prd_server_backups/docs/DEPLOYMENT_RUNBOOK.md)
- [OPERATIONS_RUNBOOK.md](/home/eva/prd_server_backups/docs/OPERATIONS_RUNBOOK.md)
- [RESTORE_TEST.md](/home/eva/prd_server_backups/docs/RESTORE_TEST.md)
