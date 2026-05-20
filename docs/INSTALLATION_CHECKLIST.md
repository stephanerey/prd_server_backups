# Installation Checklist

Checklist concise à cocher pour un nouveau serveur :

- [ ] VPS prêt
- [ ] OS Debian/Ubuntu supporté
- [ ] dépôt cloné
- [ ] `sudo ./scripts/install.sh` exécuté
- [ ] `sudo server-backup setup` exécuté
- [ ] `backup.conf` vérifié
- [ ] mot de passe `restic` copié dans le restore kit
- [ ] WireGuard OK si nécessaire
- [ ] NAS SFTP OK
- [ ] clé publique SSH installée côté NAS
- [ ] `sudo server-backup target test <target>` OK
- [ ] `sudo server-backup repo init <target>` OK
- [ ] `sudo server-backup repo check <target>` OK
- [ ] au moins un profile créé
- [ ] dump DB configuré si base critique
- [ ] `sudo server-backup db test <name>` OK
- [ ] `sudo server-backup db dump-test <name>` OK
- [ ] `sudo server-backup coverage audit` acceptable
- [ ] `sudo server-backup backup run --dry-run --target <target>` OK
- [ ] `sudo server-backup backup run --target <target> --profile <profile>` OK
- [ ] `sudo server-backup repo snapshots <target>` affiche un snapshot
- [ ] `sudo server-backup repo prune <target> --dry-run` OK
- [ ] `sudo server-backup restore test --target <target>` OK
- [ ] `sudo server-backup email test` OK
- [ ] timer systemd activé
