# Prompt Codex — PR16 production hardening and scheduling

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR15 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- configurer backup.conf ;
- configurer une target SFTP ;
- initialiser/checker un dépôt restic ;
- créer des profiles ;
- configurer des dumps DB ;
- lancer des backups réels ;
- appliquer la rétention/prune ;
- faire un restore test non destructif ;
- envoyer des rapports email ;
- faire un coverage audit ;
- produire des runbooks complets d’installation/exploitation.

État réel validé :
- target nas-steph OK ;
- WireGuard + SFTP OK ;
- repo restic OK ;
- backup réel OK ;
- DB dump PostgreSQL Docker OK ;
- prune OK ;
- restore test OK ;
- email reports OK ;
- coverage audit SUCCESS ;
- runbooks PR15 ajoutés.

Objectif de cette PR :

Implémenter uniquement :

PR16 — production hardening and scheduling

Objectif :
- finaliser l’exploitation récurrente ;
- fiabiliser le timer systemd ;
- ajouter une commande health check locale ;
- ajouter une commande d’état synthétique exploitation ;
- améliorer la robustesse systemd ;
- ajouter logrotate si pertinent ;
- documenter la politique de planning ;
- ne pas changer la logique backup/restic existante ;
- ne pas modifier les secrets ;
- ne pas lancer de backup automatiquement pendant l’installation.

Ne pas implémenter :
- nouveau backend cloud ;
- restauration destructive ;
- orchestration disaster recovery ;
- UI web ;
- monitoring externe lourd ;
- modification automatique de NAS/VPN/SMTP.

Contraintes générales :
- pas de dépendance Python externe ;
- host-level uniquement, pas Docker ;
- compatible Debian/Ubuntu ;
- ne jamais afficher de secrets ;
- ne jamais lancer de backup automatiquement sans confirmation ;
- garder les fichiers de configuration éditables à la main ;
- conserver le comportement idempotent de install.sh.

Livrables attendus :

1. Améliorer systemd/server-backup.service

Le service doit rester Type=oneshot.

Ajouter si pertinent :
- Nice=10
- IOSchedulingClass=best-effort
- IOSchedulingPriority=7
- TimeoutStartSec=12h
- KillSignal=SIGINT
- User=root
- Group=root

Ajouter des protections systemd compatibles avec le besoin root/restic/docker sans casser le fonctionnement.

Éviter les protections trop restrictives qui bloqueraient :
- /etc/server-backup
- /var/lib/server-backup
- /var/cache/restic
- /var/tmp/server-backup
- /srv
- /opt
- /home
- /var/lib/docker/volumes
- docker CLI
- sendmail/postfix

Documenter clairement tout choix.

2. Améliorer systemd/server-backup.timer

Garder un timer quotidien par défaut.

Valeurs recommandées :
- OnCalendar=*-*-* 02:30:00
- Persistent=true
- RandomizedDelaySec=10m

Le wizard setup sait déjà modifier l’heure. Ne pas casser cette capacité.

Ajouter documentation pour :
- activer le timer ;
- désactiver le timer ;
- voir le prochain run ;
- lancer manuellement le service.

3. Ajouter commande server-backup health

Implémenter :

sudo server-backup health

Objectif : faire un check local rapide sans lancer de backup réel.

Checks attendus :
- backup.conf présent et valide ;
- au moins une target ;
- au moins un profile ;
- restic disponible ;
- docker disponible si profile docker/cis-site ;
- sendmail/mail disponible si EMAIL_REPORT_ENABLED=true ;
- RESTIC_PASSWORD_FILE présent ;
- dernier backup run présent ;
- dernier backup pas trop ancien ;
- dernier restore test présent ;
- dernier restore test pas trop ancien ;
- dernier coverage audit présent ;
- dernier coverage audit pas trop ancien ;
- dernier prune run présent ou warning ;
- timer systemd installé ;
- timer activé ou warning ;
- repo snapshots/check non exécutés automatiquement dans health.

Important :
- health ne doit pas contacter le NAS ;
- health ne doit pas lancer restic ;
- health ne doit pas lancer de backup ;
- health ne doit pas lancer Docker inspect profond ;
- health reste local et rapide.

Configuration seuils par défaut :
- BACKUP_MAX_AGE_HOURS=30
- RESTORE_TEST_MAX_AGE_DAYS=30
- COVERAGE_AUDIT_MAX_AGE_DAYS=7
- PRUNE_MAX_AGE_DAYS=14

Ces valeurs peuvent être codées par défaut et documentées. Option future possible dans backup.conf, mais ne pas imposer.

Sortie :
- SUCCESS / WARNING / FAILURE
- liste checks OK/WARNING/FAILURE
- recommandations concrètes.

Code retour :
- 0 si SUCCESS ou WARNING seulement ;
- non zéro si FAILURE.

4. Ajouter commande server-backup operations status

Implémenter :

sudo server-backup operations status

ou si plus simple :

sudo server-backup status --operations

Cette commande doit afficher une vue synthétique :
- timer enabled yes/no ;
- next timer run si disponible ;
- last backup date/status/report ;
- last prune date/status/report ;
- last restore test date/status/report ;
- last coverage audit date/status/report ;
- last email status ;
- target count ;
- profile count ;
- DB dumps count ;
- principaux warnings.

Ne pas contacter le NAS.

5. Ajouter logrotate

Ajouter un fichier exemple ou installé :
- systemd/logrotate-server-backup
- ou packaging/logrotate/server-backup

Pour les logs locaux :

/var/log/server-backup.log

Politique recommandée :
- weekly
- rotate 8
- compress
- missingok
- notifempty

Si /var/log/server-backup.log n’est pas encore activement utilisé, documenter que les logs principaux sont aussi dans journalctl.

install.sh peut installer /etc/logrotate.d/server-backup si logrotate est disponible. Ne pas échouer si logrotate absent.

6. Mettre à jour install.sh

install.sh doit :
- préserver les units existantes si modifiées par setup ;
- ne pas écraser timer personnalisé sans confirmation ;
- installer les nouvelles commandes Python ;
- installer logrotate si possible ;
- faire systemctl daemon-reload ;
- ne pas activer le timer automatiquement.

Afficher à la fin :
- sudo server-backup health
- sudo systemctl enable --now server-backup.timer
- sudo systemctl list-timers | grep server-backup

7. Mettre à jour status

server-backup status peut inclure un rappel si :
- timer disabled ;
- aucun restore test récent ;
- aucun coverage audit récent ;
- aucun backup récent.

Mais status doit rester lisible et ne pas devenir trop verbeux.

8. Tests unitaires

Ajouter :
- tests/test_health.py
- tests/test_operations_status.py

Tester avec mocks :
- health sans backup.conf ;
- health sans target ;
- health sans profile ;
- health avec vieux last-backup-run ;
- health avec vieux last-restore-test ;
- health avec timer disabled ;
- health avec EMAIL_REPORT_ENABLED=true mais sendmail absent ;
- operations status lit les fichiers state sans réseau ;
- pas de secret affiché.

9. Tests manuels

Exécuter :
- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli health --help
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup health
- sudo server-backup operations status
- systemctl cat server-backup.service
- systemctl cat server-backup.timer
- systemctl status server-backup.timer --no-pager
- systemctl list-timers | grep server-backup

Si timer non activé :
- health doit produire un warning, pas une failure.

Ne pas lancer de backup réel automatiquement.

10. Documentation

Mettre à jour :

docs/OPERATIONS_RUNBOOK.md
- ajouter server-backup health ;
- ajouter operations status ;
- ajouter routine quotidienne/hebdo/mensuelle ;
- ajouter commandes systemd timer.

docs/DEPLOYMENT_RUNBOOK.md
- ajouter phase finale d’activation timer ;
- expliquer quand activer le timer ;
- expliquer les vérifications avant activation.

docs/SERVER_INSTALL.md
- ajouter health check après install ;
- ajouter activation timer manuelle.

docs/CONFIG_REFERENCE.md
- documenter seuils health si ajoutés ;
- documenter last state files utilisés.

docs/TROUBLESHOOTING.md
- timer disabled ;
- health warning backup ancien ;
- restore test ancien ;
- logrotate absent ;
- journalctl.

Ajouter si pertinent :

docs/SCHEDULING_POLICY.md

Contenu :
- backup quotidien ;
- heure recommandée ;
- RandomizedDelaySec ;
- restore test mensuel ;
- coverage audit hebdomadaire ou après changement ;
- prune après backup ou manuel ;
- repo check fréquence recommandée ;
- email reports.

11. Critères d’acceptation

- tests unitaires OK ;
- server-backup health fonctionne ;
- health ne contacte pas le NAS ;
- health ne lance pas restic ;
- health ne lance pas de backup ;
- operations status fonctionne ;
- timer reste désactivé sauf activation explicite ;
- install.sh reste idempotent ;
- systemd units valides ;
- logrotate installé si possible sans casser si absent ;
- documentation mise à jour ;
- aucun secret affiché ;
- aucun nouveau comportement destructif.

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- commandes de test exécutées ;
- résultats des tests ;
- sortie résumée de server-backup health ;
- état timer ;
- limites restantes ;
- prochaine PR recommandée.

Prochaine PR recommandée :

PR17 — final production validation and release checklist

Objectif :
- faire une validation end-to-end complète ;
- vérifier timer, backup, prune, restore, email, coverage ;
- produire une checklist de release v1.0 ;
- tagger une première version stable si souhaité.
```
