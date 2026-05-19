# Prompts Codex

Ce dossier contient les prompts prêts à copier dans Codex pour implémenter le projet `server-backup` PR par PR.

Ordre recommandé :

```text
01_PR01_PR02_PR27_INITIAL_SETUP.md
02_PR03_CONFIG_LOADER_VALIDATORS.md
03_PR04_GLOBAL_SETUP_WIZARD.md
04_PR05_SFTP_TARGET_WIZARD.md
```

Règles d'utilisation :

- donner un seul prompt à la fois à Codex ;
- ne pas demander plusieurs PR dans une seule passe ;
- relire, tester et merger chaque PR avant de passer à la suivante ;
- conserver le backend MVP en SFTP uniquement ;
- conserver l'architecture host-level : `server-backup` tourne sur l'hôte Linux, pas dans Docker ;
- ne jamais commiter de secrets, clés privées ou mots de passe.

Chaque prompt rappelle le contexte, les contraintes, les livrables, les critères d'acceptation et les tests à exécuter.
