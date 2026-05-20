# Prompt Codex — PR18 repository cleanup and v1 preparation

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR17 sont terminées et le système `server-backup` est fonctionnel en production sur le VPS de référence.

État réel validé :
- installation host-level OK ;
- target SFTP via WireGuard OK ;
- repo restic OK ;
- backup réel OK ;
- PostgreSQL dump Docker OK ;
- prune OK ;
- restore test OK ;
- rapports email OK ;
- coverage audit SUCCESS ;
- health SUCCESS ;
- production validation OK, à l’exception éventuelle du warning timer tant qu’il n’est pas activé ;
- timer systemd activé et planifié en production.

Objectif de cette PR :

Implémenter uniquement :

PR18 — repository cleanup and v1 preparation

Objectif :
- nettoyer le dépôt pour préparer une v1.0.0 ;
- transformer le README en README produit, plus en README de PRD ;
- corriger les liens absolus locaux ;
- remplir le .gitignore ;
- organiser les documents PRD historiques ;
- ajouter CHANGELOG / RELEASE_NOTES ;
- ajuster la version du package ;
- vérifier qu’aucun secret n’est versionné ;
- ne pas changer la logique fonctionnelle du backup sauf micro-corrections sûres.

Ne pas implémenter :
- nouvelle feature backup ;
- nouveau backend ;
- refonte CLI ;
- migration de config ;
- changements destructifs ;
- modifications de secrets ou fichiers runtime.

Contraintes générales :
- aucun secret dans Git ;
- pas de dépendance externe ;
- tests unitaires toujours OK ;
- ne pas casser `sudo ./scripts/install.sh` ;
- ne pas casser les chemins des docs référencées ;
- ne pas déplacer les fichiers sans corriger tous les liens.

Tâches attendues :

1. Remplir `.gitignore`

Le fichier `.gitignore` ne doit pas être vide.

Inclure au minimum :

```gitignore
# Python
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/

# Local / runtime
.env
*.env.local
*.log

# Secrets
secrets/
*.key
*.pem
id_ed25519*
restic-password
sasl_passwd
wg0.conf

# Installed/runtime paths should never be committed
etc/server-backup/
var/lib/server-backup/
var/cache/restic/

# OS / editor
.DS_Store
.idea/
.vscode/
```

2. Corriger README.md

README.md doit devenir un README produit.

Supprimer ou remplacer toute phrase indiquant que :
- le dépôt est uniquement un PRD ;
- il ne contient pas encore l’implémentation finale ;
- Codex doit implémenter tout le projet depuis zéro.

Le README doit contenir :
- présentation courte ;
- statut v1 ;
- fonctionnalités principales ;
- architecture ;
- installation rapide ;
- configuration rapide ;
- commandes principales ;
- sécurité / secrets ;
- documentation utile ;
- section “Documents historiques PRD” si les PRD restent dans le repo.

3. Corriger tous les liens absolus locaux

Rechercher et remplacer les liens de type :

```text
/home/eva/prd_server_backups/docs/...
```

par des liens relatifs :

```markdown
[DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md)
```

ou, depuis un fichier dans `docs/` :

```markdown
[NAS_OMV_WIREGUARD_RUNBOOK.md](NAS_OMV_WIREGUARD_RUNBOOK.md)
```

Commandes de recherche à utiliser :

```bash
grep -R "/home/eva/prd_server_backups" -n . || true
grep -R "vps-51ab13bd\|10.192.1.254\|nas-steph\|backup_mesfragrances" -n README.md docs manuel_utilisateur.md || true
```

Les valeurs réelles peuvent rester uniquement dans des sections explicitement nommées “exemple réel validé” ou “exemple”, jamais comme valeurs par défaut génériques.

4. Organiser les PRD historiques

Option recommandée : créer un dossier `prd/` et déplacer les documents PRD historiques dedans :

- PRD.md
- PRD_*_ADDENDUM.md

Mettre à jour les liens du README vers `prd/`.

Si tu choisis de ne pas les déplacer, ajoute une section claire dans README :

```text
Historical design documents
```

et explique qu’ils sont conservés pour traçabilité.

5. Conserver `codex_prompts/` comme historique développeur

Ne pas supprimer `codex_prompts/`.

Mettre à jour `codex_prompts/README.md` si nécessaire pour dire :
- ces prompts sont conservés pour historique et maintenance ;
- ils ne sont pas nécessaires à une installation normale ;
- un nouvel utilisateur doit suivre les docs et installer le code, pas relancer Codex.

6. Ajouter CHANGELOG.md

Créer `CHANGELOG.md` avec au moins :

```markdown
# Changelog

## v1.0.0 - YYYY-MM-DD

### Added
- Host-level server-backup installer.
- Restic SFTP targets with isolated SSH config.
- Profiles for generic, system-filesystem, docker-host, docker-app, cis-site.
- Backup run with multi-target and multi-profile support.
- PostgreSQL/MariaDB/MySQL dump support.
- Docker coverage and inventory helpers.
- Coverage audit.
- Restore test.
- Retention/prune.
- Email reports via sendmail/mail.
- Health and operations status.
- Production validation command.
- Deployment and operations runbooks.
```

Utiliser la date du jour si possible.

7. Ajouter RELEASE_NOTES.md

Créer `RELEASE_NOTES.md` pour la v1.0.0.

Inclure :
- résumé ;
- fonctionnalités validées ;
- limites connues ;
- prérequis ;
- procédure courte d’installation ;
- procédure courte de validation ;
- note sécurité sur secrets/restic password ;
- recommandation de faire un restore test.

8. Mettre à jour la version

Dans `server_backup/__init__.py`, passer :

```python
__version__ = "1.0.0"
```

si l’état v1 est considéré prêt.

Sinon, utiliser :

```python
__version__ = "0.9.0"
```

et expliquer dans RELEASE_NOTES que c’est une release candidate.

Pour cette PR, utiliser v1.0.0 sauf découverte d’un blocage.

9. Revoir `scripts/install.sh`

Point à évaluer : actuellement, l’installateur peut copier `backup.conf.example` vers `/etc/server-backup/backup.conf` si absent.

Comportement recommandé pour v1 :
- installer `/etc/server-backup/backup.conf.example` ;
- ne pas créer un vrai `/etc/server-backup/backup.conf` depuis l’exemple sauf option explicite ;
- recommander `sudo server-backup setup` pour créer la vraie configuration ;
- préserver la compatibilité si le comportement actuel est nécessaire aux tests, mais documenter clairement.

Si tu modifies ce comportement, mettre à jour les tests et docs.

10. Mettre à jour manuel_utilisateur.md

Améliorer si nécessaire :
- ajouter une table des matières ;
- séparer installation, exploitation quotidienne, dépannage ;
- indiquer clairement les commandes destructives ou potentiellement destructives ;
- mettre les valeurs spécifiques au serveur de référence dans une section exemple ;
- conserver les commandes génériques comme priorité.

11. Vérifier absence de secrets

Exécuter :

```bash
git grep -nE "(PGPASSWORD|MYSQL_PWD|SMTP_PASSWORD|RESTIC_PASSWORD|PRIVATE KEY|BEGIN OPENSSH|BEGIN WIREGUARD|sasl_passwd|id_ed25519|wg0.conf)" || true
```

Les seules occurrences acceptables doivent être :
- exemples redacted ;
- documentation qui mentionne des noms de variables ;
- `.gitignore`.

Aucun secret réel ne doit apparaître.

12. Tests

Exécuter :

```bash
python3 -m unittest discover -s tests
python3 -m py_compile server_backup/*.py
```

Vérifier aussi :

```bash
bash -n scripts/install.sh
grep -R "/home/eva/prd_server_backups" -n . || true
git status --short
```

13. Critères d’acceptation

- `.gitignore` rempli ;
- README ne dit plus que le dépôt est seulement un PRD ;
- liens absolus locaux corrigés ;
- PRD historiques organisés ou clairement identifiés ;
- CHANGELOG.md ajouté ;
- RELEASE_NOTES.md ajouté ;
- version mise à jour ;
- manuel utilisateur cohérent ;
- tests OK ;
- aucun secret réel dans le repo ;
- install.sh toujours idempotent ;
- documentation d’installation pointe vers les bons runbooks.

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- tests exécutés ;
- résultat de la recherche de secrets ;
- décision version retenue ;
- actions restantes avant tag ;
- commande de tag recommandée.

Après cette PR, si tout est OK :

```bash
git tag v1.0.0
git push origin v1.0.0
```
```
