# Prompt Codex — PR15 deployment runbook and end-to-end installation procedure

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR14 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- générer backup.conf ;
- générer une target SFTP ;
- tester SSH/SFTP ;
- générer des profiles ;
- initialiser/checker un dépôt restic ;
- créer de vrais snapshots restic via backup run ;
- appliquer la rétention avec repo prune ;
- faire un restore test non destructif ;
- envoyer des rapports email via sendmail/mail ;
- faire un coverage audit ;
- configurer des dumps DB logiques ;
- intégrer les dumps DB dans backup run ;
- détecter et aider à couvrir les volumes Docker ;
- produire inventaires Docker ;
- utiliser un lock local partagé entre repo, backup, prune, restore et DB dumps.

État réel validé sur le VPS mes-fragrances :
- target : nas-steph ;
- SFTP via WireGuard : OK ;
- repo restic : OK ;
- backup réel : OK ;
- prune : OK ;
- restore test : OK ;
- email reports : OK ;
- coverage audit : SUCCESS ;
- dump PostgreSQL Docker : OK ;
- volumes Caddy couverts ;
- volume DB couvert par dump logique ;
- repo check après backup : OK.

Objectif de cette PR :

Implémenter uniquement :

PR15 — deployment runbook and end-to-end installation procedure

Objectif :
- écrire une procédure complète de déploiement de server-backup ;
- documenter l’ordre exact des PR et des étapes opérateur ;
- expliquer quand préparer le NAS ;
- expliquer quand préparer le VPN ;
- expliquer quand créer target/profile/db ;
- expliquer quand lancer repo init, backup, prune, restore test ;
- documenter la procédure validée sur le VPS mes-fragrances ;
- produire un runbook reproductible pour d’autres serveurs ;
- ne pas modifier le comportement du code sauf corrections mineures de documentation ou CLI help.

Ne pas implémenter de nouvelle feature majeure dans cette PR.

Livrables attendus :

1. Ajouter docs/DEPLOYMENT_RUNBOOK.md

Ce document doit être le guide principal pour installer server-backup sur un nouveau serveur.

Structure attendue :
- Vue d’ensemble
- Prérequis
- Architecture cible
- Ordre des PR / fonctionnalités
- Préparation NAS
- Préparation VPN WireGuard
- Installation serveur source
- Configuration globale
- Configuration target SFTP
- Initialisation repo restic
- Création profiles
- Configuration dumps DB
- Coverage audit
- Premier backup dry-run
- Premier backup réel
- Prune/rétention
- Restore test
- Email reports
- Activation timer systemd
- Exploitation quotidienne
- Dépannage
- Checklist finale

2. Documenter l’ordre validé

Le runbook doit expliquer clairement :

Phase A — socle local
- installer jusqu’à PR4
- sudo ./scripts/install.sh
- sudo server-backup setup
- vérifier backup.conf
- vérifier restic-password
- vérifier timer désactivé par défaut

Phase B — réseau et NAS
- préparer NAS OMV ou autre NAS SFTP
- préparer utilisateur backup
- préparer dossier restic
- préparer droits
- préparer SSH/SFTP
- préparer WireGuard si le NAS n’est pas exposé publiquement
- vérifier ping/ssh/sftp depuis le VPS

Phase C — target
- sudo server-backup target add
- copier la clé publique dans authorized_keys côté NAS
- sudo server-backup target test <target>

Phase D — repo restic
- sudo server-backup repo init <target>
- sudo server-backup repo snapshots <target>
- sudo server-backup repo check <target>

Phase E — profiles
- sudo server-backup profile add
- créer system-filesystem ou profile applicatif
- créer cis-site si applicable
- vérifier : sudo server-backup config validate

Phase F — DB
- sudo server-backup db add
- sudo server-backup db list
- sudo server-backup db test <name>
- sudo server-backup db dump-test <name>

Phase G — coverage
- sudo server-backup coverage audit
- sudo server-backup docker coverage
- corriger les profiles si warnings

Phase H — premier backup
- sudo server-backup backup run --dry-run --target <target>
- sudo server-backup backup run --target <target> --profile <profile>
- sudo server-backup repo snapshots <target>
- sudo server-backup repo check <target>

Phase I — prune
- sudo server-backup repo prune <target> --dry-run
- sudo server-backup repo prune <target> --yes

Phase J — restore test
- sudo server-backup restore test --target <target> --keep-output
- sudo server-backup restore test --target <target>

Phase K — email
- configurer Postfix/sendmail ou mailx
- sudo server-backup email test
- activer EMAIL_REPORT_ENABLED
- vérifier un backup dry-run avec email

Phase L — timer
- sudo systemctl enable --now server-backup.timer
- sudo systemctl list-timers | grep server-backup

3. Ajouter docs/NAS_OMV_WIREGUARD_RUNBOOK.md

Ce document doit reprendre la procédure validée :
- utilisateur NAS backup_mesfragrances comme exemple générique ;
- groupe SSH OMV, par exemple _ssh ;
- création du home utilisateur ;
- création .ssh/authorized_keys ;
- création du dossier restic ;
- droits sur le dossier ;
- WireGuard OMV ;
- identification de l’IP WireGuard du NAS ;
- configuration WireGuard client côté VPS ;
- tests ping/ssh/sftp ;
- choix de l’IP WireGuard comme hostname server-backup ;
- rappel : ne pas utiliser Nginx Proxy Manager pour SFTP.

Ne pas inclure de secrets réels.

4. Ajouter docs/POSTFIX_OVH_RELAY.md

Documenter la configuration validée pour envoyer les rapports via SMTP OVH avec Postfix/sendmail.

Inclure :
- problème observé : sendmail local envoyait directement à Gmail, Gmail rejetait SPF/DKIM, relayhost vide dans Postfix ;
- solution : relayhost = [smtp.mail.ovh.net]:465, smtp_sasl_auth_enable = yes, smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd, smtp_tls_wrappermode = yes, smtp_tls_security_level = encrypt ;
- fichier /etc/postfix/sasl_passwd ;
- permissions 600 ;
- postmap ;
- generic map si utilisé ;
- test sendmail ;
- vérification logs : relay=smtp.mail.ovh.net, status=sent ;
- rappel que SMTP/DKIM/SPF complet reste hors périmètre server-backup.

Ne pas inclure de mot de passe.

5. Mettre à jour README.md

Ajouter une section courte :
- “Déploiement validé”
- lien vers docs/DEPLOYMENT_RUNBOOK.md
- lien vers docs/NAS_OMV_WIREGUARD_RUNBOOK.md
- lien vers docs/POSTFIX_OVH_RELAY.md
- ordre recommandé des étapes

6. Mettre à jour docs/RESTORE_KIT.md

Ajouter une section checklist restore kit :
À conserver hors serveur :
- mot de passe restic ;
- target name ;
- RESTIC_REPOSITORY ;
- hostname/IP WireGuard NAS ;
- chemin dépôt restic ;
- accès WireGuard ;
- compte SSH NAS ;
- procédure de récupération clé SSH ou nouvelle clé ;
- secrets DB ;
- SMTP credentials si nécessaires ;
- liste profiles ;
- dernier coverage audit ;
- dernier restore test ;
- procédure de restauration.

7. Ajouter docs/OPERATIONS_RUNBOOK.md

Documenter l’exploitation courante :

Commandes quotidiennes :
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup backup run --dry-run
- sudo server-backup backup run
- sudo server-backup repo snapshots <target>
- sudo server-backup repo check <target>
- sudo server-backup coverage audit
- sudo server-backup restore test --target <target>

Commandes diagnostic :
- journalctl -u server-backup.service
- tail logs mail
- mailq
- sudo wg
- sudo server-backup target test <target>
- sudo server-backup db test <name>
- sudo server-backup db dump-test <name>

Routine mensuelle :
- restore test
- repo check
- coverage audit
- prune dry-run
- vérification emails
- vérification espace NAS

8. Ajouter docs/TROUBLESHOOTING.md

Inclure les incidents déjà rencontrés :
- SSH user OMV pas dans groupe _ssh ;
- home utilisateur NAS absent ;
- SFTP fonctionne mais mauvais chemin remote ;
- WireGuard installé mais wg absent ;
- wg-quick service absent ;
- ping VPN OK mais SSH KO ;
- restic repo corrompu après init concurrent ;
- lock server-backup ;
- Gmail rejette car Postfix envoie directement ;
- Postfix relayhost OVH ;
- warning /var/spool/postfix/etc/resolv.conf not owned by root ;
- backup run Ctrl+C ;
- coverage audit warning volumes Docker ;
- DB volume brut vs dump logique ;
- restore test warning car snapshot incomplet.

9. Ajouter docs/INSTALLATION_CHECKLIST.md

Checklist concise à cocher :
- VPS prêt ;
- OS supporté ;
- WireGuard OK ;
- NAS SFTP OK ;
- target test OK ;
- repo init OK ;
- repo check OK ;
- profile créé ;
- DB dump configuré ;
- coverage audit success ;
- backup dry-run success ;
- backup réel success ;
- snapshots visibles ;
- prune dry-run OK ;
- restore test OK ;
- email test OK ;
- timer activé.

10. Aucun secret

Tous les documents doivent utiliser des valeurs d’exemple ou placeholders.

Ne jamais inclure :
- mot de passe SMTP ;
- mot de passe DB ;
- clé privée WireGuard ;
- clé privée SSH ;
- mot de passe restic.

11. Tests

Exécuter :

python3 -m unittest discover -s tests

Vérifier aussi que les nouveaux fichiers Markdown existent :
- docs/DEPLOYMENT_RUNBOOK.md
- docs/NAS_OMV_WIREGUARD_RUNBOOK.md
- docs/POSTFIX_OVH_RELAY.md
- docs/OPERATIONS_RUNBOOK.md
- docs/TROUBLESHOOTING.md
- docs/INSTALLATION_CHECKLIST.md

Si le projet a un linter Markdown, l’exécuter. Sinon, vérifier manuellement les titres et les blocs de code.

12. Critères d’acceptation

- documentation complète ajoutée ;
- aucune nouvelle feature risquée ;
- aucun secret dans la documentation ;
- README pointe vers les nouveaux runbooks ;
- la procédure explique clairement quand interrompre le flux pour préparer NAS/VPN/profile/DB ;
- la procédure permet de reproduire le déploiement sur un autre serveur ;
- les incidents rencontrés sont documentés dans TROUBLESHOOTING.md ;
- les commandes validées réellement sont incluses ;
- les étapes destructives sont clairement marquées avec avertissements.

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- tests exécutés ;
- liste des nouveaux documents ;
- limites restantes ;
- prochaine PR recommandée.

Prochaine PR recommandée :

PR16 — production hardening and scheduling

Objectif :
- finaliser timer systemd ;
- documenter politique de planning ;
- ajouter check de santé périodique ;
- améliorer notifications ;
- préparer exploitation récurrente.
```
