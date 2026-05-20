# NAS SFTP Target

This MVP uses a plain SSH/SFTP target on the NAS. The backup runtime stays on the Linux source host.

## NAS-Side Preparation

Recommended generic steps:

1. Create a dedicated user for backups.
2. Create a dedicated backup directory for the future restic repository.
3. Enable SSH or SFTP access for that user.
4. Add the public key printed by `sudo server-backup target add` into `authorized_keys`.
5. Restrict the key when possible with options such as:

```text
from="<SERVER_PUBLIC_IP>",no-agent-forwarding,no-X11-forwarding,no-port-forwarding,no-pty ssh-ed25519 ...
```

## Permissions and Scope

Recommended:

- give the backup user access only to its own backup directory
- avoid interactive shell privileges when the NAS supports SFTP-only users
- keep the future restic repository outside shared user home directories when possible

## Source-Server Commands

Create the target:

```bash
sudo server-backup target add
```

Test it after the NAS key installation:

```bash
sudo server-backup target test <target>
```

`target test` checks SSH in batch mode when possible, then validates SFTP. If the NAS uses `internal-sftp` and rejects `ssh ... true`, the command still succeeds when SFTP works.

After the key is installed and `target test` succeeds, initialize and inspect the repository:

```bash
sudo server-backup repo init <target>
sudo server-backup repo snapshots <target>
sudo server-backup repo check <target>
```
