# Release Checklist

Checklist v1.0 :

- [ ] `config validate` OK
- [ ] `health` OK ou warnings acceptés
- [ ] `target test` OK
- [ ] `repo check` OK
- [ ] `db test` OK
- [ ] `db dump-test` OK
- [ ] `coverage audit` SUCCESS
- [ ] `backup run --dry-run` OK
- [ ] `backup run` réel OK
- [ ] `repo snapshots` montre le snapshot
- [ ] `repo check` après backup OK
- [ ] `repo prune --dry-run` OK
- [ ] `restore test` OK
- [ ] `email test` reçu
- [ ] timer activé
- [ ] restore kit stocké hors serveur
- [ ] mot de passe `restic` stocké hors serveur
- [ ] accès NAS documenté
- [ ] accès WireGuard documenté
- [ ] secrets DB documentés hors Git
- [ ] runbooks présents
- [ ] aucun secret dans le repo
