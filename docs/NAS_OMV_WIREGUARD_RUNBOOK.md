# NAS OMV + WireGuard Runbook

## Objectif

Ce document reprend la procédure validée pour préparer un NAS OMV ou un NAS
équivalent comme cible SFTP pour `server-backup`, avec WireGuard entre le VPS
source et le NAS.

## Exemple réel validé

Les valeurs ci-dessous proviennent d'un déploiement validé. Elles restent des
exemples opérateur et ne doivent jamais être copiées comme secrets ou valeurs
par défaut.

- utilisateur NAS : `backup_mesfragrances`
- groupe SSH OMV : `_ssh`
- target `server-backup` : `nas-steph`

## 1. Préparer l'utilisateur SFTP côté NAS

Créer un utilisateur dédié :

- login : `backup_mesfragrances`
- shell : selon la politique du NAS
- home directory : obligatoire
- appartenance au groupe SSH autorisé par OMV, souvent `_ssh`

Points à vérifier :

- le home utilisateur existe réellement
- l'utilisateur peut ouvrir une session SSH/SFTP
- les permissions du home sont cohérentes

## 2. Préparer la clé publique

Depuis le serveur source :

```bash
sudo server-backup target add
```

Le wizard génère une clé publique. La copier côté NAS dans :

```text
/home/<user>/.ssh/authorized_keys
```

Permissions recommandées :

```bash
chmod 700 /home/<user>/.ssh
chmod 600 /home/<user>/.ssh/authorized_keys
chown -R <user>:<group> /home/<user>/.ssh
```

Exemple de restriction recommandée dans `authorized_keys` :

```text
from="<source-server-public-ip>",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty ssh-ed25519 AAAA...
```

## 3. Créer le dossier du dépôt restic

Créer un dossier dédié, par exemple :

```text
/srv/dev-disk-by-uuid-<disk-uuid>/backups/<server-name>/restic
```

Vérifier :

- existence du chemin parent
- droits d'écriture pour l'utilisateur de backup
- capacité disque suffisante

## 4. Activer SSH/SFTP

Sur OMV :

- activer le service SSH
- vérifier que l'utilisateur est autorisé
- confirmer que le groupe SSH requis est correct

Erreur fréquente :

- utilisateur créé, mais non membre du groupe `_ssh`
- effet : `ping` WireGuard OK, mais SSH/SFTP refusé

## 5. Préparer WireGuard côté NAS

Installer et configurer WireGuard sur le NAS.

Points à vérifier :

- interface WireGuard active
- peer du VPS autorisé
- route du sous-réseau WireGuard correcte
- firewall autorise le trafic SSH sur l'interface WireGuard

Conserver hors serveur :

- IP WireGuard du NAS
- procédure de régénération des clés
- procédure de redémarrage WireGuard

## 6. Préparer WireGuard côté VPS

Sur le serveur source :

- installer `wireguard` / `wg` / `wg-quick` si nécessaire
- créer la configuration du peer NAS
- démarrer l'interface

Tests utiles :

```bash
sudo wg
ip addr show
ping -c 3 <wireguard-nas-ip>
ssh <user>@<wireguard-nas-ip>
sftp <user>@<wireguard-nas-ip>
```

Incidents fréquents :

- WireGuard installé mais commande `wg` absente
- service `wg-quick@<iface>` absent
- tunnel monté d'un côté seulement

## 7. Utiliser l'IP WireGuard comme hostname de target

Dans `server-backup`, privilégier l'IP WireGuard du NAS comme `SSH_HOSTNAME`.

Exemple :

```text
SSH_HOSTNAME="<wireguard-nas-ip>"
```

Avantages :

- trafic privé
- pas d'exposition publique SSH du NAS
- comportement reproductible entre serveurs

## 8. Tests de validation

Après ajout de la clé et du dossier distant :

```bash
sudo server-backup target test <target>
sudo server-backup repo init <target>
sudo server-backup repo check <target>
```

Résultats attendus :

- SFTP test : `OK`
- dépôt `restic` initialisé
- `repo check` : `OK`

## 9. Ce qu'il ne faut pas faire

- ne pas utiliser Nginx Proxy Manager pour SFTP
- ne pas passer par un reverse proxy HTTP pour SSH/SFTP
- ne pas partager l'utilisateur avec d'autres usages
- ne pas stocker la clé privée SSH dans Git
- ne pas mettre le mot de passe `restic` sur le NAS

## 10. Validation opérateur finale

Avant de passer aux profiles et aux backups :

- utilisateur NAS prêt
- groupe SSH OK
- home utilisateur OK
- `authorized_keys` OK
- dossier `restic` distant OK
- WireGuard OK
- `target test` OK

La suite du flux est dans
[DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md).
