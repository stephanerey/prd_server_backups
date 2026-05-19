# Prompt Codex — Hotfix PR8 gestion propre des interruptions

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR8 est implémentée avec server-backup backup run, rapports locaux backup et verrou restic local.

Problème réel observé :
Lors d'un Ctrl+C pendant :

sudo server-backup backup run --dry-run --target nas-steph

le programme a affiché une stacktrace Python complète avec KeyboardInterrupt.

Objectif du hotfix :
- gérer KeyboardInterrupt proprement ;
- ne plus afficher de stacktrace utilisateur ;
- libérer proprement le lock restic ;
- retourner un code non nul standard, idéalement 130 ;
- afficher un message clair :
  Operation interrupted by user. No report may have been completed.
- si un rapport partiel peut être écrit, le marquer :
  status="interrupted"
  interrupted=true
- ne pas envoyer d'email automatique pour un run interrompu ;
- ajouter un message de progression avant les commandes longues.

Commandes concernées :
- server-backup backup run
- server-backup repo init
- server-backup repo check
- server-backup repo snapshots
- server-backup repo prune
- server-backup restore test

Contraintes :
- pas de dépendance externe ;
- ne jamais afficher de secret ;
- ne pas masquer les erreurs normales ;
- ne pas modifier les dépôts restic en dehors de l'opération déjà en cours ;
- conserver le verrou via context manager/finally.

Amélioration UX attendue :
Avant restic backup, afficher par exemple :

Running restic backup dry-run for target <target>, profile <profile>. This may take several minutes...

Ajouter des messages équivalents si pertinent pour :
- repo check ;
- repo snapshots ;
- repo prune ;
- restore test.

Tests attendus :
- python3 -m unittest discover -s tests
- sudo ./scripts/install.sh
- test manuel réel :
  sudo server-backup backup run --dry-run --target nas-steph
  puis Ctrl+C

Critères d'acceptation :
- Ctrl+C ne produit plus de stacktrace ;
- code retour observé : 130 ;
- lock restic relâché ;
- un rapport partiel est écrit si possible ;
- le JSON contient status="interrupted" et interrupted=true ;
- status affiche le dernier run comme interrupted si c'est le dernier état ;
- aucun email automatique n'est envoyé pour une interruption.
```
