# Novel with Docker

The service is local at `http://127.0.0.1:8791`. The image includes Codex CLI
`0.162.0-alpha.17.2` for App Server compatibility. Test CLI upgrades explicitly.

| Resource | Location | Purpose |
| --- | --- | --- |
| Library | `docker-data/library` → `/data/library` | Catalogue, sources, drafts, decisions, memory and backups |
| Sources | `NOVEL_SOURCES_DIR` → `/imports` | Read-only source mount |
| Codex session | `novel_codex-home` → `/home/node/.codex` | Authentication owned only by Codex |
| Source selection | `docker-data/settings.json` or `.env` | Private local configuration |

The Compose project stays `novel`. The explicit session volume name survives
checkout moves. `NOVEL_CODEX_VOLUME` selects another existing volume. Never use
`docker compose down --volumes`, erase `docker-data` or delete that volume for updates.

## First installation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -EmptyLibrary
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Login
```

Add `-SourcesPath 'C:\Books\My series'` to `Up` to mount a folder. The launcher
remembers this private path. Import from `/imports`. For direct Compose use,
copy `.env.example` to `.env` and set paths locally.

Initial sign-in uses `codex login --device-auth`, followed by **Connect Codex**.
Enter the CLI's code in the browser; no API key is required. See
[official authentication documentation](https://learn.chatgpt.com/docs/auth).
An existing session survives container replacement; do not Login on every update.

## Import a complete backup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -BackupPath 'C:\Backups\Novel\complete-backup'
```

The destination library must be absent. Import requires `COMPLETE.json` and checks
SQLite, referenced EPUBs and hashes. Links and credentials are rejected.
An existing library is never overwritten. `-EmptyLibrary` and `-BackupPath`
are mutually exclusive. Without either option, first startup attempts backup
from the historical local instance on port 8790; if closed, provide a backup
or explicitly choose an empty library.

## Update, restart and stop

Use launcher actions `Status`, `Up`, `Restart`, `Stop` and `Logs`.
`Up` checks jobs before and after building; active work prevents replacement.
A running but unreachable API also blocks update or stop. `Restart` uses the
existing image instead of rebuilding code. Pause in Novel and wait for the
active call before restarting or stopping.

Docker restart preserves data. Novel pauses incomplete work and requires explicit
resume. Inspect logs before sharing; they may contain private information.

## Migration and rollback

1. Confirm no active work and create a complete backup.
2. Build from the new checkout while the old service runs. Keep its image ID.
3. Stop it, copy the entire library and compare file hashes and SQLite integrity.
   Copy any local-mode library only while its instance is stopped.
4. Keep the project name, session volume and read-only source mount. Store
   personal paths only in local configuration.
5. Run `docker compose up --detach --no-build --wait`. Check health, drafts,
   approvals, memory and login status; connect the bridge without inference.

Keep the old checkout and backup until verification. New edits are absent from
the old copy, so back up again before rollback. Stop the new service before
reactivating the old Compose file. Only one active installation should use the
session volume.

The image uses a non-root user, bounded logs, health checks and a thirty-second
stop grace period. Its context includes the prompt policy but no user data.
