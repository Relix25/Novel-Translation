# Novel

[![CI](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml/badge.svg)](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml)

A local workspace for importing series, translating through Codex, comparing
texts and approving exact versions. Python uses the standard library; the
interface uses React and Mantine. [MIT license](LICENSE).

Generation uses the Codex-owned ChatGPT session, confirmed ephemeral sessions
and no API key. Sources, libraries, credentials and real account/trial evidence
stay in ignored local storage. The demonstration is synthetic.

## Start with Docker

Install Docker Desktop, then run from this repository in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -EmptyLibrary
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Login
```

Open [Novel](http://127.0.0.1:8791), then select **Connect Codex**. An existing
library and Codex session survive updates; `-EmptyLibrary` creates a library
only when absent. Do not sign in again on every update. See [DOCKER.md](DOCKER.md)
for source mounts, backup import, safe updates and rollback.

## Start without Docker

Use Python 3.11+, Node.js 22.12+ and a signed-in Codex CLI:

```powershell
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python app.py
```

On Linux use `npm` and `cd`. `launch.cmd` wraps the Python command on Windows.
Open [localhost:8788](http://127.0.0.1:8788); Ctrl+C stops the server. Options
include `--root`, `--port`, `--no-browser` and `--public-origin` for a Docker
port mapping. The default library is `appdata`; generated frontend files are
excluded from Git.

## Translate and review

1. Load the synthetic demo or import EPUB/UTF-8 chapters into a series.
2. Verify source text, language pairs, scoped glossary forms and glyph readings.
3. Connect Codex and prepare an exact chapter selection with explicit safeguards.
4. Generate drafts, compare them with the source and inspect cited AI findings.
5. Approve only after reading, using the exact fingerprint and a review reason.
   Summaries and story facts have separate approvals.

The production profile is Luna High translation, Luna Low summaries/entity
proposals and Sol High review with at most two passes per batch. An unavailable
profile or unconfirmed ephemeral session blocks generation. Errors pause work;
restart does not resume it. Imported text and identifiers are never rewritten.

## Documentation

- [User guide](docs/USER_GUIDE.md): imports, Workspace, terminology, jobs, memory,
  quota, backups, troubleshooting and manual CLI.
- [Docker operations](DOCKER.md): persistent storage, installation, updates and rollback.
- [Architecture and LLM maintenance contracts](docs/ARCHITECTURE.md),
  [AGENTS.md](AGENTS.md) and [contributing checks](CONTRIBUTING.md).
- [Literary prompt contract](docs/TRANSLATION_PROMPT.md) and its
  [policy asset](prompts/literary_translation.md).
- [Benchmark protocol](benchmarks/PROTOCOL.md): isolated experiments and offline
  reports. Running an experiment requires a separate explicit request and budget.
- [Verification](VERIFICATION.md), [roadmap](ROADMAP.md),
  [dependency review](docs/DEPENDENCY_REVIEW.md) and [security](SECURITY.md).

## Development and publication

```powershell
test.cmd
python tools/check_public_files.py --history --worktree
```

See CONTRIBUTING for formatting, lint, frontend tests and isolated Docker checks.
Keep private material in `local-*`, library, import or backup directories. Inspect
all staged diffs; automated checks cannot identify every private sentence.

Work on `dev` or a temporary `codex/` branch and open a PR to protected `main`.
Six current CI checks, resolved conversations and linear history are required;
force push and deletion are blocked, including for admins. Extra reviewer
approval is optional for this single-maintainer repository. Dev is long-lived.
