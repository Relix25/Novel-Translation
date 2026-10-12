# Contributing

Use Python 3.11+ and Node.js 22. The backend is standard-library-only.
Run `npm ci` in `frontend` and preserve its lockfile.

```powershell
test.cmd
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python tools/check_public_files.py --history
git diff --check
```

Launcher tests use harmless Docker stubs and a process-only PowerShell execution
policy. Tests never generate real translations. Preserve IDs, fingerprint
approval, ephemeral sessions and explicit resume. Simulations prove neither
model access nor literary quality. Record real trials and tokens privately.

Use synthetic fixtures and fictitious paths. No manuscripts, account readings,
databases, private screenshots or credentials. Multilingual fixture content
remains in its declared language; software prose and documentation use English.

Work on `dev` and open a PR to `main`. All six CI checks must pass against an
up-to-date base, conversations must be resolved and history must be linear.
Force push and deletion are disabled for everyone. An extra reviewer is optional
so the sole maintainer can merge their own checked PR. The policy is in
`.github/branch-protection.json` and must also be applied through GitHub administration.

Automatic head-branch deletion is disabled so the long-lived `dev` branch survives
release PRs. Remove completed temporary branches explicitly when appropriate.

Dependabot targets `dev`. Major runtime/build updates need compatibility review;
a successful build does not prove live Codex compatibility. Preserve the requested
model profile. Prompt changes must test blocked responses, cited notes, batch
boundaries and exact segment IDs.
