# Postfix OVH Relay

## Objectif

Ce document décrit la configuration validée pour faire partir les rapports
`server-backup` via Postfix en relay SMTP OVH.

Ce document concerne le MTA local du serveur. La configuration SMTP elle-même
reste hors périmètre du code `server-backup`.

## Problème observé

Cas réel rencontré :

- `sendmail` local acceptait le message ;
- Postfix essayait ensuite de livrer directement vers Gmail ;
- l'envelope sender initial partait en `root@<hostname>` ;
- Gmail rejetait la livraison pour absence de SPF/DKIM valides ;
- `relayhost` était vide dans Postfix.

Même après correction de `server-backup` pour utiliser `sendmail -f
<EMAIL_REPORT_FROM>`, un MTA local peut encore accepter le message puis être
rejeté plus loin par le serveur distant.

## Solution validée

Configurer Postfix pour relayer via OVH :

```text
relayhost = [smtp.mail.ovh.net]:465
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
smtp_tls_wrappermode = yes
smtp_tls_security_level = encrypt
```

Puis recharger Postfix :

```bash
sudo systemctl restart postfix
```

## Fichier /etc/postfix/sasl_passwd

Créer :

```text
/etc/postfix/sasl_passwd
```

Format :

```text
[smtp.mail.ovh.net]:465 admin@example.tld:SMTP_PASSWORD
```

Ne jamais committer ce fichier.

Permissions :

```bash
sudo chown root:root /etc/postfix/sasl_passwd
sudo chmod 600 /etc/postfix/sasl_passwd
sudo postmap /etc/postfix/sasl_passwd
sudo chmod 600 /etc/postfix/sasl_passwd.db
```

## Generic map si utilisée

Si le système doit réécrire les expéditeurs locaux, une `generic map` peut être
ajoutée, mais elle reste optionnelle selon l'environnement.

Exemple :

```text
/etc/postfix/generic
root@hostname.example admin@example.tld
```

Puis :

```bash
sudo postmap /etc/postfix/generic
```

Et dans `main.cf` :

```text
smtp_generic_maps = hash:/etc/postfix/generic
```

## Test avec sendmail

Exemple de test local :

```bash
printf 'To: you@example.tld\nFrom: admin@example.tld\nSubject: Test relay\n\nHello\n' | \
sudo /usr/sbin/sendmail -t -f admin@example.tld
```

Avec `server-backup` :

```bash
sudo server-backup email test --to you@example.tld
```

## Vérification des logs

Dans `/var/log/mail.log`, vérifier :

- `relay=smtp.mail.ovh.net`
- `status=sent`

Exemple de lignes attendues :

```text
postfix/smtp[...] relay=smtp.mail.ovh.net[...]:465, ...
postfix/smtp[...] status=sent
```

## Points de vigilance

- `sendmail` peut accepter localement un message qui sera rejeté ensuite
- un relay SMTP résout l'émission sortante, mais SPF/DKIM/DMARC du domaine
  restent un sujet distinct
- `server-backup` n'administre pas Postfix
- ne pas stocker les credentials SMTP dans le dépôt Git

## Lien avec server-backup

Dans `backup.conf`, vérifier :

```text
EMAIL_REPORT_ENABLED="true"
EMAIL_REPORT_TO="ops@example.tld"
EMAIL_REPORT_FROM="admin@example.tld"
EMAIL_REPORT_COMMAND="sendmail"
```

`server-backup` utilise alors :

```text
/usr/sbin/sendmail -t -f <EMAIL_REPORT_FROM>
```

Les headers `From:`, `To:` et `Subject:` restent présents dans le message.

## Hors scope

Ce document ne couvre pas :

- la configuration DKIM/SPF/DMARC complète
- un relais SMTP authentifié autre qu'OVH
- l'administration complète de Postfix
- la supervision mail avancée
