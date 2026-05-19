# Configuration NAS OMV + VPN WireGuard pour server-backup

Ce document décrit la procédure utilisée pour préparer un NAS OMV comme destination de backup `restic` via SFTP, accessible depuis un VPS OVH à travers un tunnel WireGuard.

Objectif final :

```text
VPS OVH mes-fragrances
  └── WireGuard client
       └── SSH/SFTP vers NAS OMV via IP WireGuard
            └── dépôt restic distant
```

Valeurs utilisées dans notre installation :

```text
NAS OMV IP LAN             : 192.168.1.3
NAS OMV IP WireGuard       : 10.192.1.254
VPS WireGuard client       : 10.192.1.10
Tunnel WireGuard OMV       : wgnet1
Réseau WireGuard           : 10.192.1.0/24
Utilisateur backup NAS     : backup_mesfragrances
Target server-backup       : nas-steph
Chemin dépôt restic NAS    : /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
```

---

## 1. Principe réseau

Le NAS n'est pas exposé directement sur Internet en SSH.

L'accès se fait via WireGuard :

```text
VPS OVH
  wg0 : 10.192.1.10/32
        |
        | WireGuard via DDNS maison
        |
NAS OMV
  wgnet1 : 10.192.1.254/24
  LAN    : 192.168.1.3
```

Nginx Proxy Manager n'est pas utilisé pour le backup. Il sert aux flux HTTP/HTTPS. Ici `restic` utilise SFTP :

```text
restic → SSH/SFTP → NAS
```

Le hostname à donner à `server-backup target add` est donc l'IP WireGuard du NAS :

```text
10.192.1.254
```

---

## 2. Préparation du NAS OMV

### 2.1 Créer l'utilisateur dédié

Créer l'utilisateur dans OMV :

```text
Users > Users > Create
```

Valeur utilisée :

```text
username      : backup_mesfragrances
primary group : users
```

Vérification côté shell OMV :

```bash
id backup_mesfragrances
getent passwd backup_mesfragrances
```

Résultat attendu :

```text
uid=1002(backup_mesfragrances) gid=100(users) groupes=100(users)
backup_mesfragrances:x:1002:100::/home/backup_mesfragrances:/usr/bin/sh
```

### 2.2 Autoriser SSH pour l'utilisateur

Sur OMV, l'utilisateur doit appartenir au groupe autorisé à utiliser SSH. Dans notre cas, il fallait ajouter l'utilisateur au groupe :

```text
_ssh
```

Sinon SSH répond mais refuse la session.

Vérification :

```bash
groups backup_mesfragrances
```

Le groupe `_ssh` doit apparaître.

### 2.3 Créer le home utilisateur

Le login SSH indiquait initialement :

```text
Could not chdir to home directory /home/backup_mesfragrances: No such file or directory
```

Correction :

```bash
sudo mkdir -p /home/backup_mesfragrances
sudo chown backup_mesfragrances:users /home/backup_mesfragrances
sudo chmod 700 /home/backup_mesfragrances
```

Préparer aussi `.ssh` :

```bash
sudo mkdir -p /home/backup_mesfragrances/.ssh
sudo chown -R backup_mesfragrances:users /home/backup_mesfragrances/.ssh
sudo chmod 700 /home/backup_mesfragrances/.ssh
```

---

## 3. Préparation du dossier de backup sur OMV

Créer le dossier qui recevra le dépôt `restic` :

```bash
sudo mkdir -p /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
```

Donner les droits au compte backup :

```bash
sudo chown -R backup_mesfragrances:users /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances
sudo chmod -R u+rwX,g-rwx,o-rwx /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances
```

Vérifier que l'utilisateur peut écrire :

```bash
sudo -u backup_mesfragrances test -w /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic && echo OK
```

Test plus explicite :

```bash
sudo -u backup_mesfragrances bash -c 'touch /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic/test-write && rm /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic/test-write && echo OK'
```

Résultat attendu :

```text
OK
```

---

## 4. Configuration WireGuard côté OMV

### 4.1 Identifier l'IP WireGuard du NAS

Commande :

```bash
ip -4 -br addr | grep -E 'wg|10\.192'
```

Résultat obtenu :

```text
wgnet1           UNKNOWN        10.192.1.254/24
wgnet2           UNKNOWN        10.192.2.254/24
```

La bonne IP WireGuard du NAS pour le tunnel `wgnet1` est :

```text
10.192.1.254
```

Commande :

```bash
sudo wg show
```

Résultat significatif :

```text
interface: wgnet1
  listening port: 51820

peer: ...
  allowed ips: 10.192.1.10/32
```

Le client VPS `VPS_mesfragrances` utilise donc l'IP WireGuard :

```text
10.192.1.10
```

### 4.2 Créer le client WireGuard dans OMV

Dans OMV :

```text
Services > Wireguard > Clients > Create
```

Valeurs utilisées :

```text
Enable                : yes
Client number         : 10
Tunnel number         : 1 - WG_eyrenard
Name                  : VPS_mesfragrances
Persistent keepalive  : 25
DNS Servers           : disable
```

Restrictions recommandées :

```text
Restrict              : coché
VPN                   : coché
Local IP              : décoché, sauf besoin d'accès au LAN 192.168.1.0/24
Additional subnets    : vide
```

Avec cette configuration, le VPS accède au NAS via l'IP VPN :

```text
10.192.1.254
```

Il n'est pas nécessaire d'accéder à `192.168.1.3` pour le backup.

### 4.3 Exporter la configuration client

Depuis OMV, exporter ou télécharger la configuration du client `VPS_mesfragrances`.

Elle doit contenir une structure du type :

```ini
[Interface]
PrivateKey = <private-key-client-vps>
Address = 10.192.1.10/32

[Peer]
PublicKey = <public-key-wireguard-omv>
PresharedKey = <preshared-key-si-présente>
Endpoint = <ddns-maison>:51820
AllowedIPs = 10.192.1.0/24
PersistentKeepalive = 25
```

Le DDNS sert uniquement à établir le tunnel WireGuard. Il n'est pas utilisé directement par `server-backup`.

---

## 5. Configuration WireGuard côté VPS OVH

### 5.1 Installer WireGuard

Sur le VPS :

```bash
sudo apt update
sudo apt install -y wireguard wireguard-tools
```

Vérifier :

```bash
which wg
which wg-quick
```

### 5.2 Installer la configuration client

Créer le dossier :

```bash
sudo mkdir -p /etc/wireguard
```

Créer le fichier :

```bash
sudo nano /etc/wireguard/wg0.conf
```

Coller la configuration exportée depuis OMV.

Protéger le fichier :

```bash
sudo chmod 600 /etc/wireguard/wg0.conf
sudo chown root:root /etc/wireguard/wg0.conf
```

### 5.3 Activer le tunnel

```bash
sudo systemctl enable --now wg-quick@wg0
```

Vérifier :

```bash
sudo wg
ip -4 -br addr | grep wg
ip route | grep 10.192
```

Le VPS doit avoir une interface WireGuard avec une IP du type :

```text
10.192.1.10/32
```

---

## 6. Tests réseau depuis le VPS

### 6.1 Ping du NAS via WireGuard

Depuis le VPS :

```bash
ping 10.192.1.254
```

Résultat attendu :

```text
64 bytes from 10.192.1.254: icmp_seq=1 ttl=64 time=21.0 ms
```

### 6.2 Test SSH manuel

Depuis le VPS :

```bash
ssh backup_mesfragrances@10.192.1.254
```

Lors de la première connexion, accepter la clé host SSH :

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
```

Fingerprint ED25519 observée :

```text
SHA256:lF4jAKXZSZ/oG77MIcytXbJZKd7OSEDRY9sfDEQAylU
```

### 6.3 Test SFTP manuel

Depuis le VPS :

```bash
sftp backup_mesfragrances@10.192.1.254
```

Dans SFTP :

```text
cd /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
pwd
mkdir test-write
rmdir test-write
exit
```

Si `mkdir` puis `rmdir` fonctionnent, le dossier distant est prêt.

---

## 7. Configuration server-backup target SFTP

Sur le VPS, lancer :

```bash
sudo server-backup target add
```

Réponses utilisées :

```text
Target name                  : nas-steph
Target type                  : sftp
SFTP hostname or IP          : 10.192.1.254
SSH port                     : 22
Remote SSH user              : backup_mesfragrances
Remote restic repository path: /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
Generate dedicated SSH key   : yes
Fetch NAS host key           : yes
Test SFTP now                : no
```

Le wizard récupère les clés host du NAS et demande confirmation :

```text
Add this host key to /etc/server-backup/ssh/known_hosts [Y/n]: Y
```

Fingerprints observées :

```text
ECDSA   SHA256:qEna2etmOGyKwEbJCxHtLHjPRQYuWSludYQ6u295xoo
ED25519 SHA256:lF4jAKXZSZ/oG77MIcytXbJZKd7OSEDRY9sfDEQAylU
RSA     SHA256:8+7RpCLhnt/v1USyfLxikv6wryBJkht+k3E08sP5/K0
```

Le wizard affiche ensuite une clé publique dédiée, par exemple :

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBck6f4gkj2fCA64PBpJZfNXXxlywyIeW3+2zS4Qg/bY server-backup:nas-steph
```

---

## 8. Installer la clé publique server-backup côté NAS

Sur OMV :

```bash
sudo nano /home/backup_mesfragrances/.ssh/authorized_keys
```

Coller la clé publique affichée par le wizard.

Puis :

```bash
sudo chown backup_mesfragrances:users /home/backup_mesfragrances/.ssh/authorized_keys
sudo chmod 600 /home/backup_mesfragrances/.ssh/authorized_keys
```

### Option sécurité recommandée

Une fois le test validé, on peut restreindre la clé à l'IP WireGuard du VPS :

```text
from="10.192.1.10",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty ssh-ed25519 AAAAC3... server-backup:nas-steph
```

Ne pas appliquer cette restriction tant que l'IP WireGuard du VPS n'est pas confirmée.

---

## 9. Test final server-backup target

Sur le VPS :

```bash
sudo server-backup target test nas-steph
```

Résultat obtenu :

```text
Validation: OK

SSH batch test: OK for server-backup-nas-steph
SFTP batch test: OK for server-backup-nas-steph
  sftp> pwd
  Remote working directory: /home/backup_mesfragrances
  sftp> ls
```

Vérifier l'état :

```bash
sudo server-backup status
sudo server-backup config validate
```

Résultat attendu :

```text
Targets:
  configured: 1
  - nas-steph | type=sftp | validation=OK
    alias=server-backup-nas-steph host=10.192.1.254 port=22 user=backup_mesfragrances
    repository=sftp:server-backup-nas-steph:/srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic | ssh_key=yes | known_hosts=yes
```

Le warning suivant est normal tant qu'aucun profile n'a été créé :

```text
No profiles are configured.
```

---

## 10. Valeurs finales à conserver dans le restore kit

```text
Target name                  : nas-steph
NAS WireGuard IP             : 10.192.1.254
VPS WireGuard IP             : 10.192.1.10
SSH port                     : 22
SSH user                     : backup_mesfragrances
Remote restic repository path: /srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
WireGuard tunnel OMV         : wgnet1
WireGuard network            : 10.192.1.0/24
OMV LAN IP                   : 192.168.1.3
```

Fichiers importants côté VPS :

```text
/etc/wireguard/wg0.conf
/etc/server-backup/targets.d/nas-steph.env
/etc/server-backup/ssh/ssh_config
/etc/server-backup/ssh/known_hosts
/etc/server-backup/ssh/id_ed25519_nas-steph
/etc/server-backup/ssh/id_ed25519_nas-steph.pub
```

Fichiers importants côté NAS :

```text
/home/backup_mesfragrances/.ssh/authorized_keys
/srv/dev-disk-by-uuid-e92e1b0d-2270-4952-82d7-b8c2314ad51c/backup_mesfragrances/restic
```

---

## 11. Étapes suivantes

Après validation de la target SFTP :

1. Créer les profiles de backup :

```bash
sudo server-backup profile add
```

Profiles recommandés pour un serveur Docker/CIS :

```text
system-filesystem
docker-host
cis-site
```

2. Déployer PR7 pour initialiser et vérifier le dépôt restic :

```bash
sudo server-backup repo init nas-steph
sudo server-backup repo check nas-steph
sudo server-backup repo snapshots nas-steph
```

Ne pas lancer ces commandes tant que PR7 n'est pas installée.

---

## 12. Dépannage rapide

### `wg: command not found`

Installer WireGuard :

```bash
sudo apt update
sudo apt install -y wireguard wireguard-tools
```

### `wg-quick@wg0.service does not exist`

WireGuard n'est pas installé ou `wireguard-tools` manque.

### `ping 10.192.1.254` ne répond pas

Vérifier :

```bash
sudo wg
ip route | grep 10.192
sudo systemctl status wg-quick@wg0 --no-pager
sudo journalctl -u wg-quick@wg0 -n 100 --no-pager
```

### SSH refuse la connexion

Vérifier côté OMV :

```bash
id backup_mesfragrances
getent passwd backup_mesfragrances
groups backup_mesfragrances
```

L'utilisateur doit appartenir au groupe `_ssh`.

### Message `Could not chdir to home directory`

Créer le home :

```bash
sudo mkdir -p /home/backup_mesfragrances
sudo chown backup_mesfragrances:users /home/backup_mesfragrances
sudo chmod 700 /home/backup_mesfragrances
```

### `server-backup target test` échoue en SFTP

Vérifier :

```bash
sudo server-backup status
sudo server-backup config validate
sudo cat /etc/server-backup/targets.d/nas-steph.env
sudo ls -l /etc/server-backup/ssh/
```

Puis tester manuellement :

```bash
sftp backup_mesfragrances@10.192.1.254
```
