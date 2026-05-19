# Prompt Codex — PR11 rapports email réels

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1 à PR10 sont terminées.

Le système sait maintenant :
- installer le socle host-level ;
- générer backup.conf ;
- générer une target SFTP ;
- tester SSH/SFTP ;
- générer des profiles ;
- initialiser/checker un dépôt restic ;
- créer un vrai snapshot restic via backup run ;
- appliquer la rétention avec repo prune ;
- faire un restore test non destructif ;
- générer des rapports locaux backup/prune/restore ;
- utiliser un lock local partagé entre repo, backup, prune et restore.

État réel validé :
- target : nas-steph
- target test : OK
- repo init : OK
- repo check : OK
- snapshot réel existant : df472f9c
- backup run : OK
- prune : OK
- restore test : OK avec warning attendu
- rapports locaux : OK
- lock restic local : OK
- SMTP/MTA local : opérationnel ; un email de rapport d’audit de sécurité a déjà été envoyé avec succès depuis ce VPS.

Objectif de cette PR :

Implémenter uniquement :

PR11 — rapports email réels

Objectif :
- envoyer les rapports backup/prune/restore par email ;
- implémenter server-backup email test réel ;
- utiliser sendmail ou mail selon backup.conf ;
- ne jamais envoyer de secrets ;
- conserver une copie locale des rapports ;
- intégrer l’envoi email en fin de backup run, repo prune et restore test ;
- ne pas encore implémenter SMTP complet ;
- ne pas configurer Postfix/SMTP dans ce projet.

Contrainte importante :
La configuration SMTP/MTA est un prérequis externe. Ce projet doit seulement utiliser un mécanisme local déjà fonctionnel :
- /usr/sbin/sendmail -t
- ou mail / mailx

Ne pas implémenter :
- configuration SMTP ;
- authentification SMTP ;
- DKIM/SPF/DMARC ;
- serveur mail ;
- relais SMTP ;
- UI de configuration email.

Contraintes générales :
- pas de dépendance Python externe ;
- ne jamais afficher de secrets ;
- ne jamais envoyer de secrets ;
- ne jamais inclure RESTIC_PASSWORD_FILE ;
- ne jamais inclure le contenu de clés SSH ;
- ne jamais inclure PGPASSWORD, MYSQL_PWD, TOKEN, SECRET, PASSWORD, KEY ;
- utiliser subprocess.run avec shell=False ;
- comportement clair et testable ;
- compatible Debian/Ubuntu.

Configuration existante dans backup.conf :

EMAIL_REPORT_ENABLED="true|false"
EMAIL_REPORT_TO="admin@example.net"
EMAIL_REPORT_FROM="server-backup@example.net"
EMAIL_REPORT_SUBJECT_PREFIX="[server-backup]"
EMAIL_REPORT_SEND_ON_SUCCESS="true"
EMAIL_REPORT_SEND_ON_FAILURE="true"
EMAIL_REPORT_COMMAND="sendmail|mail"

Livrables attendus :

1. Ajouter server_backup/email_report.py

Fonctions attendues :

- load_email_config(global_config)
- should_send_email(status, email_config)
- sanitize_email_body(text)
- sanitize_email_subject(text)
- build_email_subject(kind, status, backup_name, hostname)
- build_email_message(to_addr, from_addr, subject, body)
- send_with_sendmail(message)
- send_with_mail(to_addr, from_addr, subject, body)
- send_email_report(kind, status, report_text, global_config)
- send_test_email(global_config, to_override=None)
- redact_sensitive_lines(text)

Types de rapports :
- backup
- prune
- restore-test
- test

2. Redaction obligatoire

Avant tout envoi email, filtrer le contenu.

Masquer toute ligne contenant des clés sensibles :

- PASSWORD
- SECRET
- TOKEN
- KEY
- PGPASSWORD
- MYSQL_PWD
- RESTIC_PASSWORD
- RESTIC_PASSWORD_FILE
- SSH_IDENTITY_FILE
- PRIVATE
- PASSPHRASE

Remplacer la valeur ou la ligne par :

<redacted>

Ne jamais supprimer les informations utiles comme nom de target, nom de profile, statut, chemins de rapport, mais masquer les secrets.

3. Sujet email

Format attendu :

[server-backup] SUCCESS backup vps-51ab13bd on hostname
[server-backup] WARNING prune vps-51ab13bd on hostname
[server-backup] FAILURE restore-test vps-51ab13bd on hostname
[server-backup] TEST vps-51ab13bd on hostname

Le préfixe vient de :

EMAIL_REPORT_SUBJECT_PREFIX

4. Commande server-backup email test

Implémenter :

sudo server-backup email test

Options :

sudo server-backup email test --to adresse@example.net

Comportement :
- charger backup.conf ;
- vérifier EMAIL_REPORT_COMMAND ;
- construire un email de test ;
- envoyer via sendmail ou mail ;
- afficher succès/échec ;
- ne pas envoyer de secrets ;
- retourner code non nul si échec.

Si EMAIL_REPORT_ENABLED=false :
- email test doit quand même pouvoir fonctionner, mais afficher :
  "Email reports are disabled for automatic reports, but sending test email anyway."
- sauf si tu préfères ajouter option --force ; dans ce cas documenter.

5. Intégration avec backup run

À la fin de server-backup backup run :
- récupérer le rapport texte généré ;
- si EMAIL_REPORT_ENABLED=true :
  - envoyer si status success et EMAIL_REPORT_SEND_ON_SUCCESS=true ;
  - envoyer si status warning/failure et EMAIL_REPORT_SEND_ON_FAILURE=true ;
- si email échoue :
  - ne pas masquer l’échec ;
  - afficher warning clair ;
  - ajouter warning dans last-backup-run.json si possible ;
  - ne pas transformer un backup failure en success ;
  - si backup success mais email failure, statut CLI final peut devenir WARNING.

6. Intégration avec repo prune

À la fin de server-backup repo prune :
- même logique que backup ;
- utiliser kind="prune" ;
- envoyer le rapport prune texte.

7. Intégration avec restore test

À la fin de server-backup restore test :
- même logique ;
- utiliser kind="restore-test" ;
- envoyer le rapport restore texte.

8. Gestion des commandes email

sendmail :
- utiliser /usr/sbin/sendmail si présent ;
- fallback vers sendmail dans PATH si pertinent ;
- commande :
  /usr/sbin/sendmail -t
- message complet avec headers To, From, Subject.

mail :
- utiliser mail ou mailx ;
- commande indicative :
  mail -s <subject> -r <from> <to>
- gérer le cas où -r n’est pas supporté en fallback documenté si nécessaire.

Ne jamais utiliser shell=True.

9. Validation config email

Mettre à jour validators.py si nécessaire :

Si EMAIL_REPORT_ENABLED=true :
- EMAIL_REPORT_TO obligatoire ;
- EMAIL_REPORT_FROM obligatoire ;
- EMAIL_REPORT_COMMAND obligatoire ;
- EMAIL_REPORT_COMMAND ∈ sendmail, mail.

Si EMAIL_REPORT_ENABLED=false :
- champs email peuvent être vides ;
- config validate ne doit pas échouer.

10. Status

server-backup status peut afficher :
- email enabled yes/no ;
- command sendmail/mail ;
- recipient si configuré ;
- last email send status si stocké dans state.

Ne pas envoyer d’email depuis status.

11. État local email

Créer si pertinent :

/var/lib/server-backup/state/last-email-report.json

Contenu :
- kind
- status
- to
- from
- subject
- sent_at
- command
- success true/false
- error si échec

Ne pas inclure le corps complet si cela risque de dupliquer des informations sensibles, ou alors stocker uniquement une version redacted.

12. Tests unitaires

Ajouter :

- tests/test_email_report.py

Tester :
- build_email_subject
- build_email_message
- sanitize_email_body
- redaction de RESTIC_PASSWORD_FILE
- redaction de PGPASSWORD
- redaction de SECRET/TOKEN/KEY
- should_send_email success/failure
- sendmail appelé avec shell=False via mock
- mail appelé avec shell=False via mock
- email disabled mais email test possible si prévu
- config invalide si enabled=true et destinataire manquant
- aucun secret dans le message final

Ne pas envoyer de vrai email dans les tests unitaires.

13. Tests manuels

Exécuter :

python3 -m unittest discover -s tests
python3 -m server_backup.cli email --help
python3 -m server_backup.cli email test --help
sudo ./scripts/install.sh
sudo server-backup status
sudo server-backup config validate
sudo server-backup email test

La config SMTP/MTA est censée être opérationnelle sur ce VPS.
Donc si server-backup email test échoue :
- ne pas inventer de succès ;
- fournir l’erreur exacte ;
- indiquer si l’échec vient de la commande sendmail/mail ou de la configuration backup.conf.

Si MTA local fonctionne :
- confirmer l’envoi du mail ;
- indiquer le destinataire et le sujet.

Tester aussi avec un rapport existant si possible :
- sudo server-backup backup run --dry-run --target nas-steph
- vérifier si email automatique est déclenché uniquement si EMAIL_REPORT_ENABLED=true.

14. Documentation

Mettre à jour :

docs/SERVER_INSTALL.md

Ajouter :
- prérequis email ;
- test sendmail/mail ;
- server-backup email test ;
- activation EMAIL_REPORT_ENABLED.

Mettre à jour :

docs/CONFIG_REFERENCE.md

Documenter :
- EMAIL_REPORT_ENABLED
- EMAIL_REPORT_TO
- EMAIL_REPORT_FROM
- EMAIL_REPORT_SUBJECT_PREFIX
- EMAIL_REPORT_SEND_ON_SUCCESS
- EMAIL_REPORT_SEND_ON_FAILURE
- EMAIL_REPORT_COMMAND
- last-email-report.json

Ajouter ou mettre à jour :

docs/EMAIL_REPORTS.md

Ce document doit expliquer :
- fonctionnement ;
- sendmail ;
- mail/mailx ;
- test ;
- redaction ;
- quand les emails sont envoyés ;
- quoi faire si Postfix/mailutils n’est pas configuré ;
- ce qui est hors scope : SMTP/DKIM/SPF/DMARC.

Mettre à jour README.md si nécessaire avec un paragraphe court sur les rapports email.

15. Critères d’acceptation

- tests unitaires OK ;
- server-backup email test fonctionne ou échoue proprement selon MTA ;
- aucun secret n’est envoyé ;
- sendmail/mail utilisés sans shell=True ;
- backup run peut envoyer un rapport si activé ;
- prune peut envoyer un rapport si activé ;
- restore test peut envoyer un rapport si activé ;
- si EMAIL_REPORT_ENABLED=false, aucun email automatique n’est envoyé ;
- si EMAIL_REPORT_SEND_ON_SUCCESS=false, les succès ne déclenchent pas d’email ;
- si EMAIL_REPORT_SEND_ON_FAILURE=true, warning/failure déclenchent un email ;
- status n’envoie jamais d’email ;
- config validate vérifie les champs email uniquement si enabled=true.

À la fin, fournir :
- résumé des fichiers créés/modifiés ;
- commandes de test exécutées ;
- résultats des tests ;
- résultat de server-backup email test ;
- si email réel envoyé, destinataire et sujet ;
- limites restantes ;
- prochaine PR recommandée.

Prochaine PR recommandée après celle-ci :

PR12 — coverage audit minimal

Objectif PR12 :
- détecter targets/profiles incomplets ;
- détecter volumes Docker/bind mounts non couverts ;
- détecter cis-site sans DB dump configuré ;
- générer rapport coverage audit local ;
- ne pas encore faire de corrections automatiques.
```
