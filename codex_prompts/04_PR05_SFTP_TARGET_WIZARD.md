# Prompt Codex — PR5 Wizard target SFTP et SSH

```text
Tu travailles dans le dépôt :

https://github.com/stephanerey/prd_server_backups

Contexte :
PR1/PR2/PR27 partiel sont terminées :
- structure repo
- install.sh idempotent
- CLI minimale
- systemd service/timer
- exemples
- docs initiales

PR3 est terminée :
- loader config
- validateurs
- config validate
- config show
- redaction secrets

PR4 est terminée :
- server-backup setup
- génération /etc/server-backup/backup.conf
- génération optionnelle /etc/server-backup/secrets/restic-password
- configuration du timer systemd
- status enrichi
- email test stub

Objectif de cette PR :

Implémenter uniquement :

PR5 — Wizard target SFTP et SSH

Objectif :
- implémenter server-backup target add
- implémenter server-backup target test <target>
- générer /etc/server-backup/targets.d/<target>.env
- générer une clé SSH dédiée par target
- générer une configuration SSH isolée
- afficher la clé publique à copier côté NAS
- tester SSH/SFTP
- ne pas encore initialiser le dépôt restic
- ne pas encore faire de backup réel

Ne pas implémenter encore :
- repo init réel
- repo check réel
- backup restic réel
- profile add réel
- db add réel
- docker scan réel
- coverage audit réel
- restore test réel
- email réel

Ces fonctionnalités viendront dans les PR suivantes.

Contraintes générales :
- pas de dépendance Python externe
- ne jamais stocker de secrets dans Git
- ne jamais afficher de secrets dans les logs
- ne jamais écraser une config existante sans confirmation explicite
- comportement idempotent
- erreurs claires
- compatible Debian/Ubuntu
- le système tourne sur l’hôte Linux, pas dans Docker
- backend MVP : SFTP uniquement

Sécurité SSH :
- ne pas désactiver StrictHostKeyChecking globalement
- ne pas utiliser StrictHostKeyChecking=no par défaut
- ne pas écrire dans /root/.ssh/config si possible
- utiliser une configuration SSH dédiée sous /etc/server-backup/ssh/
- isoler le known_hosts dans /etc/server-backup/ssh/known_hosts
- clé SSH dédiée par target
- permissions strictes root-only

Livrables attendus :

1. Compléter server_backup/wizard.py

Ajouter les fonctions utiles pour target add, par exemple :

- run_target_add()
- prompt_target_name()
- prompt_sftp_target()
- sanitize_target_name()
- render_target_env()
- render_ssh_config_entry()
- generate_ssh_key()
- read_public_key()
- ensure_known_host()
- test_sftp_connection()
- write_target_file_secure()

Les fonctions de rendu doivent être testables sans interaction.

2. Ajouter ou compléter server_backup/ssh.py

Créer un module dédié SSH.

Fonctions attendues :

- sanitize_ssh_alias(name)
- generate_ed25519_key(private_key_path, comment)
- get_public_key(public_key_path)
- render_ssh_config_entry(alias, hostname, port, user, identity_file, known_hosts_file)
- write_ssh_config_entry(alias, rendered_entry)
- remove_or_replace_ssh_config_entry(alias, rendered_entry, confirm)
- ensure_known_hosts_file(path)
- fetch_host_key(hostname, port)
- append_known_host(hostname, port, known_hosts_file)
- test_ssh_batch(alias, ssh_config_file)
- test_sftp_batch(alias, ssh_config_file)

Utiliser uniquement standard library + commandes système :
- ssh-keygen
- ssh-keyscan
- ssh
- sftp

Gestion d’erreurs claire si une commande manque.

3. Chemins SSH à utiliser

Utiliser ces chemins :

/etc/server-backup/ssh/
├── id_ed25519_<target>
├── id_ed25519_<target>.pub
├── ssh_config
└── known_hosts

Le fichier /etc/server-backup/ssh/ssh_config doit contenir des blocs Host.

Exemple :

Host server-backup-nas-home
    HostName backup.example.net
    User backup-pyparfums
    Port 2222
    IdentityFile /etc/server-backup/ssh/id_ed25519_nas-home
    IdentitiesOnly yes
    UserKnownHostsFile /etc/server-backup/ssh/known_hosts
    StrictHostKeyChecking yes
    ServerAliveInterval 30
    ServerAliveCountMax 3

Les commandes SSH/SFTP devront utiliser :

ssh -F /etc/server-backup/ssh/ssh_config server-backup-nas-home
sftp -F /etc/server-backup/ssh/ssh_config server-backup-nas-home

Ne pas dépendre de /root/.ssh/config.

4. Implémenter server-backup target add

Commande :

sudo server-backup target add

Questions à poser :

- nom logique de la target, ex. nas-home
- type de target, MVP : sftp uniquement
- hostname ou IP du NAS
- port SSH, défaut 22
- utilisateur SSH distant
- chemin distant du dépôt restic, ex. /backups/pyparfums-prod/restic
- générer une nouvelle clé SSH dédiée ? défaut yes
- chemin de clé si réutilisation d’une clé existante
- récupérer et enregistrer la host key avec ssh-keyscan ? défaut yes
- tester la connexion SFTP maintenant ? défaut yes

Valeurs générées :

- TARGET_NAME
- TARGET_TYPE="sftp"
- SSH_HOST_ALIAS="server-backup-<target>"
- SSH_HOSTNAME
- SSH_PORT
- SSH_USER
- SSH_IDENTITY_FILE
- SSH_CONFIG_FILE="/etc/server-backup/ssh/ssh_config"
- SSH_KNOWN_HOSTS_FILE="/etc/server-backup/ssh/known_hosts"
- RESTIC_REPOSITORY="sftp:<alias>:<remote_path>"
- RESTIC_PASSWORD_FILE depuis backup.conf si disponible, sinon défaut /etc/server-backup/secrets/restic-password
- RESTIC_CACHE_DIR depuis backup.conf si disponible, sinon défaut /var/cache/restic

Le fichier généré :

/etc/server-backup/targets.d/<target>.env

Doit contenir :

CONFIG_VERSION="1"
GENERATED_BY="server-backup"
GENERATED_AT="<timestamp ISO8601>"

TARGET_NAME="nas-home"
TARGET_TYPE="sftp"

SSH_HOST_ALIAS="server-backup-nas-home"
SSH_HOSTNAME="backup.example.net"
SSH_PORT="2222"
SSH_USER="backup-pyparfums"
SSH_IDENTITY_FILE="/etc/server-backup/ssh/id_ed25519_nas-home"
SSH_CONFIG_FILE="/etc/server-backup/ssh/ssh_config"
SSH_KNOWN_HOSTS_FILE="/etc/server-backup/ssh/known_hosts"

RESTIC_REPOSITORY="sftp:server-backup-nas-home:/backups/pyparfums-prod/restic"
RESTIC_PASSWORD_FILE="/etc/server-backup/secrets/restic-password"
RESTIC_CACHE_DIR="/var/cache/restic"

Permissions :

/etc/server-backup/targets.d/<target>.env : 0600 root:root
/etc/server-backup/ssh/id_ed25519_<target> : 0600 root:root
/etc/server-backup/ssh/id_ed25519_<target>.pub : 0644 root:root
/etc/server-backup/ssh/ssh_config : 0600 root:root
/etc/server-backup/ssh/known_hosts : 0600 root:root

Si le fichier target existe déjà :
- ne pas l’écraser sans confirmation
- si remplacement accepté, créer une sauvegarde horodatée :
  /etc/server-backup/targets.d/<target>.env.bak-YYYYMMDD-HHMMSS

Si la clé SSH existe déjà :
- ne pas l’écraser sans confirmation
- proposer de la réutiliser
- si remplacement accepté, backup horodaté de l’ancienne clé et de la .pub

5. Affichage de la clé publique

Après génération ou sélection de clé, afficher clairement :

Copier cette clé publique dans le fichier authorized_keys de l'utilisateur distant :

Puis afficher la clé publique .pub.

Ajouter aussi un rappel sécurité :

Recommandé côté NAS :
from="<IP_PUBLIQUE_SERVEUR>",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty ssh-ed25519 ...

Ne pas insérer automatiquement la clé côté NAS.

6. Host key

Si l’utilisateur accepte la récupération host key :

- exécuter ssh-keyscan -p <port> <hostname>
- afficher l’empreinte si possible avec ssh-keygen -lf -
- demander confirmation avant ajout au known_hosts
- ajouter au fichier /etc/server-backup/ssh/known_hosts
- ne pas ajouter de doublon si déjà présent

Si ssh-keyscan échoue :
- message clair
- ne pas désactiver StrictHostKeyChecking
- indiquer que l’utilisateur devra ajouter la host key manuellement

7. Implémenter server-backup target test <target>

Commande :

sudo server-backup target test nas-home

Elle doit :

- charger /etc/server-backup/targets.d/nas-home.env
- valider la target avec validate_target_config()
- vérifier que TARGET_TYPE="sftp"
- vérifier que SSH_CONFIG_FILE existe
- vérifier que SSH_IDENTITY_FILE existe
- vérifier que SSH_KNOWN_HOSTS_FILE existe
- tester SSH batch si possible :
  ssh -F <ssh_config> -o BatchMode=yes <alias> true
- tester SFTP batch :
  printf "pwd\nls\n" | sftp -F <ssh_config> -b - <alias>
- afficher résultat clair

Important :
- si le NAS force internal-sftp et refuse la commande SSH true, ne pas considérer SSH true comme failure fatale si SFTP fonctionne.
- SFTP fonctionnel doit être le test principal.
- ne pas créer ou modifier le chemin distant du dépôt dans cette PR.
- ne pas lancer restic init dans cette PR.

Codes retour :
- 0 si SFTP OK
- non zéro si target invalide ou SFTP impossible

8. Mise à jour status

server-backup status doit afficher pour chaque target :

- TARGET_NAME
- TARGET_TYPE
- SSH_HOST_ALIAS
- SSH_HOSTNAME
- SSH_PORT
- SSH_USER
- RESTIC_REPOSITORY
- présence clé SSH yes/no
- présence known_hosts yes/no
- validation OK/WARNING/ERROR

Ne jamais afficher de secret.

9. Mise à jour config validate

server-backup config validate doit maintenant valider aussi :

- existence du fichier clé SSH si target active
- permissions du fichier clé SSH si accessible
- existence du SSH_CONFIG_FILE
- existence du SSH_KNOWN_HOSTS_FILE

Warnings, pas forcément errors, si :
- known_hosts absent
- clé SSH absente
- ssh_config absent

Error si :
- target env invalide
- TARGET_TYPE absent
- RESTIC_REPOSITORY absent

10. Tests unitaires

Ajouter ou compléter :

- tests/test_ssh_helpers.py
- tests/test_target_rendering.py

Tester au minimum :

- sanitize target name
- sanitize ssh alias
- render_target_env
- render_ssh_config_entry
- RESTIC_REPOSITORY correctement formé
- parse du target env généré
- validate target sftp minimal
- redaction ne montre pas SSH_IDENTITY_FILE si considéré sensible ou au moins ne montre jamais contenu de clé
- permissions helper si testable sans root

Ne pas faire de vrai SSH réseau dans les tests unitaires.

11. Documentation

Mettre à jour docs/SERVER_INSTALL.md :

Ajouter section :

Ajout d'une target NAS SFTP

sudo server-backup target add
sudo server-backup target test <target>

Mettre à jour docs/CONFIG_REFERENCE.md :

Documenter :

- targets.d/<name>.env
- SSH_CONFIG_FILE
- SSH_KNOWN_HOSTS_FILE
- RESTIC_REPOSITORY SFTP
- permissions attendues

Mettre à jour docs/RESTORE_KIT.md :

Ajouter que le restore kit doit conserver :

- nom de la target
- hostname NAS
- port SSH
- user SSH
- chemin distant du dépôt restic
- méthode de récupération ou régénération de la clé SSH
- host key NAS si nécessaire

Ajouter un document si pertinent :

- docs/NAS_SFTP_TARGET.md

Il doit expliquer côté NAS générique :

- créer utilisateur dédié
- créer dossier backup
- activer SSH/SFTP
- ajouter clé publique dans authorized_keys
- limiter droits
- tester depuis serveur source

12. Critères d’acceptation

- python3 -m unittest discover -s tests passe
- python3 -m server_backup.cli --help fonctionne
- sudo server-backup target add fonctionne en interactif
- target add génère /etc/server-backup/targets.d/<target>.env en 0600 root:root
- target add génère une clé SSH dédiée en 0600 root:root
- target add affiche la clé publique à copier côté NAS
- target add génère ou met à jour /etc/server-backup/ssh/ssh_config
- target add gère known_hosts sans désactiver StrictHostKeyChecking
- target add ne remplace rien sans confirmation
- sudo server-backup target test <target> teste SFTP
- sudo server-backup status affiche la target
- sudo server-backup config validate prend la target en compte
- aucun restic init n’est lancé
- aucun backup réel n’est lancé
- aucun secret réel n’est commité
- aucune clé privée n’est affichée

Tests à exécuter :

- python3 -m unittest discover -s tests
- python3 -m server_backup.cli --help
- python3 -m server_backup.cli status
- sudo ./scripts/install.sh
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup target add
- sudo server-backup status
- sudo server-backup config validate
- sudo server-backup target test <target>

Si aucun NAS réel n’est disponible pour les tests réseau :
- tester jusqu’à génération des fichiers
- documenter que le test SFTP réel n’a pas pu être validé
- montrer les commandes à exécuter quand le NAS est prêt

À la fin, fournir :

- résumé des fichiers créés/modifiés
- commandes de test exécutées
- résultats des tests
- limites restantes
- prochaine PR recommandée

Prochaine PR recommandée après celle-ci :

PR6 — Wizard profile

Objectif PR6 :
- implémenter server-backup profile add
- générer profiles.d/*.conf
- supporter generic, docker-host, docker-app, cis-site, system-filesystem
- ne pas encore exécuter de backup réel
```
