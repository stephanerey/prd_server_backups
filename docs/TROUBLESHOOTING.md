# Troubleshooting

## Objectif

Ce document recense les incidents déjà rencontrés et les vérifications à faire
en priorité.

## SSH user OMV pas dans le groupe _ssh

Symptômes :

- `ping` WireGuard OK
- SSH ou SFTP refusé

Vérifications :

```bash
id <user>
getent group _ssh
```

Correction :

- ajouter l'utilisateur au groupe SSH autorisé par OMV
- reconnecter le service si nécessaire

## Home utilisateur NAS absent

Symptômes :

- authentification SSH partielle
- erreurs SFTP sur `.ssh` ou sur le répertoire distant

Vérifications :

```bash
ls -ld /home/<user>
ls -ld /home/<user>/.ssh
```

Correction :

- créer le home
- corriger propriétaire et permissions

## SFTP fonctionne mais mauvais chemin remote

Symptômes :

- `target test` OK
- `repo init` ou `backup run` échoue sur le chemin distant

Vérifications :

- chemin `RESTIC_REPOSITORY`
- droits sur le dossier distant
- espace disque NAS

## WireGuard installé mais wg absent

Symptômes :

- paquet installé partiellement
- commande `wg` absente

Vérification :

```bash
which wg
which wg-quick
```

Correction :

- installer les paquets complets WireGuard

## wg-quick service absent

Symptômes :

- configuration présente
- impossible de lancer `wg-quick@<iface>`

Vérification :

```bash
systemctl status wg-quick@wg0 --no-pager
```

Correction :

- vérifier les paquets et le nom d'interface

## Ping VPN OK mais SSH KO

Symptômes :

- tunnel opérationnel
- port 22 non joignable

Causes fréquentes :

- firewall du NAS
- service SSH désactivé
- utilisateur non autorisé
- route retour incomplète

## Repo restic corrompu après init concurrent

Symptômes :

- erreur type `config or key is damaged`

Cause déjà observée :

- deux `repo init` lancés en parallèle

État actuel :

- `server-backup` protège désormais ces opérations avec un lock local

## Lock server-backup

Message attendu :

```text
Another server-backup restic operation is already running. Lock file: /run/server-backup-repo.lock
```

Action :

- attendre la fin de l'opération en cours
- vérifier qu'aucune commande suspendue n'est restée active

## Gmail rejette car Postfix envoie directement

Symptômes :

- `sendmail` semble fonctionner localement
- Gmail rejette ensuite le message

Cause :

- émission directe sans relay SMTP
- SPF/DKIM non valides

Correction :

- configurer Postfix avec un relay SMTP, par exemple OVH

Voir :
[POSTFIX_OVH_RELAY.md](POSTFIX_OVH_RELAY.md)

## Postfix relayhost OVH

Vérifier dans `/etc/postfix/main.cf` :

```text
relayhost = [smtp.mail.ovh.net]:465
smtp_sasl_auth_enable = yes
smtp_tls_wrappermode = yes
```

Puis vérifier les logs :

- `relay=smtp.mail.ovh.net`
- `status=sent`

## Warning /var/spool/postfix/etc/resolv.conf not owned by root

Symptômes :

- warning Postfix dans les logs

Action :

- vérifier le propriétaire et les permissions de `resolv.conf`
- vérifier la configuration chroot Postfix

Ce warning n'est pas spécifique à `server-backup`, mais il peut polluer le
diagnostic mail.

## backup run Ctrl+C

Comportement attendu :

- pas de stacktrace Python
- message propre :
  `Operation interrupted by user. No report may have been completed.`
- rapport partiel éventuellement marqué `interrupted`

## Timer disabled

Symptômes :

- `server-backup.timer` installé mais non actif
- `server-backup health` renvoie un warning

Vérifications :

```bash
systemctl status server-backup.timer --no-pager
systemctl list-timers | grep server-backup
```

Correction :

```bash
sudo systemctl enable --now server-backup.timer
```

## Health warning backup ancien

Symptômes :

- `server-backup health` signale un backup trop ancien

Vérifications :

```bash
sudo server-backup operations status
sudo server-backup status
```

Actions :

- vérifier le timer
- relancer un `backup run`
- relire le dernier rapport

## Health warning restore test ancien

Symptômes :

- dernier `restore test` trop ancien dans `health`

Action :

```bash
sudo server-backup restore test --target <target>
```

## logrotate absent

Symptômes :

- pas de `/etc/logrotate.d/server-backup`

Explication :

- `logrotate` peut être absent sur l'hôte
- ce n'est pas bloquant pour `server-backup`

Référence :

- les logs principaux restent disponibles via `journalctl -u server-backup.service`

## journalctl

Commande de base :

```bash
journalctl -u server-backup.service
```

Utiliser `journalctl` comme source principale si `/var/log/server-backup.log`
n'est pas utilisé dans le déploiement courant.

## coverage audit warning volumes Docker

Symptômes :

- volumes ou bind mounts non couverts

Commandes utiles :

```bash
sudo server-backup docker coverage
sudo server-backup docker suggest-profile-updates
sudo server-backup docker add-missing-paths --profile <profile> --dry-run
```

## DB volume brut vs dump logique

Règle opérateur :

- le dump logique est la couverture principale
- le volume brut DB reste optionnel

Si un volume DB n'est pas sauvegardé mais qu'un `DATABASE_DUMPS` fonctionne,
l'audit doit le traiter comme couverture logique principale.

## restore test warning car snapshot incomplet

Symptômes :

- `restore test` en `WARNING`
- certains chemins du profile sont absents

Explication :

- le snapshot testé peut ne contenir qu'un sous-ensemble volontaire des chemins
- le restore reste correct si les fichiers réellement sauvegardés sont lisibles

Vérifier :

- le profile testé
- le snapshot réellement restauré
- les chemins présents dans le rapport
