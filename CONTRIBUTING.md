# Contributing

Read [AGENTS.md](AGENTS.md) and [architecture/contracts](docs/ARCHITECTURE.md)
before changing source, storage, prompts or generation. Use English software
prose and synthetic fixtures. Imported sources, quoted evidence and multilingual
fixture translations retain their own languages.

## Setup

Use Python 3.11+ and Node.js 22.12+. Runtime Python has no third-party dependencies.
Development checks use the pinned Ruff version; frontend tools are dev-only and
locked in package-lock.json:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Push-Location frontend
npm.cmd ci --no-audit --no-fund
Pop-Location
```

On Linux activate `.venv` or use `.venv/bin/python`; use `npm` instead of `npm.cmd`.
To work against an isolated synthetic library, run `python app.py --root
local-dev-library --port 8792 --no-browser`. In another terminal, run `npm run dev`
in `frontend`: this watches the production build. Refresh the app after edits;
there is no separate API proxy or Hot Module Replacement server. Docker users
can keep their production library running separately.

## Required checks

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
test.cmd
Push-Location frontend
npm.cmd run lint
npm.cmd run format:check
npm.cmd test
npm.cmd run build
npm.cmd audit --omit=dev --audit-level=high
Pop-Location
python tools/check_public_files.py --history --worktree
git diff --check
```

Use `ruff format .` and `npm run format` to apply formatting. Ruff excludes private
libraries, local evidence and frontend dependencies. Oxlint checks correctness,
Hook order/dependencies, imports and accessibility. React Compiler is not used;
its Compiler-specific constraints are disabled deliberately, as documented in
the architecture guide. Do not silence a finding to hide a race.

`test.cmd` selects the bundled Codex Python when present and works from outside
the checkout. On Linux use `python -m unittest discover -s tests -p 'test_*.py' -v`.
Tests use fake bridges, local synthetic stdio peers and harmless Docker stubs;
no real inference. Structural tests do not prove model access or bilingual quality.

For a Docker change, follow CI in `.github/workflows/ci.yml`: build a separate
image, start an isolated empty library on a free loopback port and run the smoke
checker. `tools/smoke_http.py` accepts the test service's base URL. Never run it
against your real library: it checks emptiness and adds the synthetic demo.
Keep the Docker build allowlist complete for runtime modules and policies.

## Review and release

Test the contract changed: immutable source IDs, exact fingerprints, stale writes,
bounded responses, separate approvals, interruption/resume, private-data boundaries
and backup/restore. Add regressions for meaningful behavior; avoid tests that just
repeat a function's implementation. Prompt changes must cover blocked responses,
exact notes, segment IDs and current-batch boundaries.

Work on `dev` or a temporary `codex/` branch. Main requires a PR, six up-to-date
CI contexts, resolved conversations and linear history. Force push/deletion are
blocked for admins too. Extra reviewer approval is optional for the sole maintainer.
The policy is in `.github/branch-protection.json` and must also be applied on GitHub.
Automatic branch deletion is disabled to preserve dev. Synchronize dev with a
release without rewriting other people's commits.

Use descriptive commits. When Codex contributes under the owner's identity,
include `Co-authored-by: Codex <codex@openai.com>`. Inspect the exact staged files
and run the privacy audit again after staging. It checks indexed blobs/history;
`--worktree` also checks publishable unstaged files. Do not stage with a blanket
command before reviewing private exclusions.

Dependabot targets dev for frontend, Actions, Docker and Python dev tooling.
Major runtime/build upgrades need explicit compatibility review; a green build
alone does not prove live Codex compatibility. Preserve the production profile.

## Evidence and documentation

Keep user steps in docs/USER_GUIDE.md, engineering contracts in
AGENTS.md/docs/ARCHITECTURE.md and local invariants in docstrings. README is the
entry point, not a duplicate manual. Update the relevant guide when a route,
action, CLI flag, storage contract or UI label changes. Preserve license notices.

Real trials, per-call tokens, account readings, manuscripts, databases, source
EPUBs, personal paths and private screenshots belong in ignored local evidence.
Public VERIFICATION records reproducible checks and their limits. Historical
benchmark authorizations do not authorize new inference or a changed profile.
Optional offline benchmark charts require Matplotlib; install it in a separate
local development environment, not the runtime image.
