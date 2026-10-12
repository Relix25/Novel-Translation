# Novel — Translation workspace

[![CI](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml/badge.svg)](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml)

A local workspace for importing series, translating with Codex, comparing texts,
editing drafts and approving exact versions. Python uses only the standard
library; the interface uses React, Mantine and Tabler. [MIT license](LICENSE).

Novel uses the Codex CLI ChatGPT session through App Server, without API keys.
Libraries, manuscripts, translations and credentials stay in local locations
excluded from Git. The included demonstration is entirely synthetic.

## Start with Docker

Install Docker Desktop, then run from PowerShell in this repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -EmptyLibrary
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Login
```

Open [Novel](http://127.0.0.1:8791), then select **Connect Codex**. `-EmptyLibrary`
creates a library only if absent. The execution policy applies only to that
process. See [DOCKER.md](DOCKER.md) for backups, updates and rollback.

## Start without Docker

Install Python 3.11+, Node.js 22 and the Codex CLI:

```powershell
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python app.py
```

On Linux use `npm` and `cd`. `launch.cmd` is the Windows launcher.
`frontend/dist` is generated locally and excluded from Git. The browser opens
at [localhost:8788](http://127.0.0.1:8788). Keep the process running; Ctrl+C stops
it. Options include `--root`, `--port` and `--no-browser`. The default library
is `appdata`.

## Import, translate and review

1. Load the synthetic demo or create a series in **Library**. Import EPUBs or
   UTF-8 TXT/MD chapters. Docker sources appear at `/imports`; a native Windows
   folder picker is unavailable inside the container.
2. Check the preview before importing. Sources and identifiers remain stable.
   Original EPUBs are archived by fingerprint. New volumes do not replace
   chapters. Keep EPUBs and text files in separate folders.
3. Choose target languages and review glossary forms. Concepts link language
   forms to first appearances. Translations, summaries and observations are
   separated by language pair.
4. Select chapters, ranges or volumes. **Prepare batch** shows exact selection,
   profile and estimates. The real catalogue must provide Luna High for
   translation, Sol High for review, and Luna Low for summaries and entity
   proposals. Unavailability blocks the operation without silent substitution.
5. Compare source and draft in **Workspace**, save edits and approve the exact
   version fingerprint with a review reason. Later edits retire translation and
   summary approvals.

Long chapters use bounded paragraph batches. Novel checks identifiers, order,
fingerprints and completeness before saving a full draft. AI review performs at
most two passes; only corrected or uncertain batches get the second. AI checking
remains separate from final human approval and summary approval.

The [literary policy](prompts/literary_translation.md) prioritizes meaning,
completeness, literary effect, scoped terminology, idiomatic form and then simple
wording. It adapts the user-supplied Astra prompt to Novel's JSON contract while
preserving ambiguity, voices, cultural setting, pacing and knowledge boundaries.

**Editorial notes — not for publication** separates actionable uncertainty and
terminology proposals from translated segments. Notes quote exact source passages
and stay linked to translation/context fingerprints. They never modify glossary,
memory or approval automatically and never enter the reader.
See [the integration guide](docs/TRANSLATION_PROMPT.md).

Image-based characters in EPUBs require inspection and transcription before
generation. Missing text or unresolved readings block the call; no chapter is invented.

## Memory, jobs and quota

**Entities & memory** groups characters, places, organizations, items and cited
observations. The chapter cutoff hides future names and facts in reading order.
Each fact needs an exact quotation and separate approval. Proposed names are
not approved terminology. Only approved, earlier observations still consistent
with the source enter translation context.

**Jobs** shows phase, model, batches, passes, progress and known usage. Pause
after the current call saves its usable result and awaits explicit resume.
Immediate stop interrupts the call without refunding tokens used. Errors,
unknown usage and limits pause processing. Restart never resumes generation
automatically. Valid batches are reusable only when prompt, context and profile match.

Limits bound calls, tokens, duration and inactivity. A call can exceed a token
limit before reporting usage. Credit estimates are not a percentage of included
quota. Account quota displays actual Codex windows and their freshness; missing
information remains unavailable.

## Backups and privacy

Backups require no active work and produce `COMPLETE.json`, catalogue and
language-pair databases, referenced EPUBs and review reports. Import checks SQLite,
archive presence and fingerprints. Codex authentication is never in a library backup.

`appdata/`, `docker-data/`, imports, backups, SQLite files, EPUBs, private screenshots,
logs and `.env` files are excluded from Git. Docker uses a public-source allowlist.
Inspect diffs and run `python tools/check_public_files.py --history` before
publishing. Imported texts and multilingual fixtures retain their own languages;
translating the software never rewrites manuscripts.

Do not edit the historical library and its migrated copy concurrently.
Reassociate source folders after restoring elsewhere. The migration source and
backups remain local for rollback.

## Development

```powershell
test.cmd
python tools/check_public_files.py --history
```

CI checks Python on Windows/Linux, production frontend dependencies and an
isolated Docker installation. Tests use synthetic responses and no real inference.

Work on `dev`; `main` requires a PR and all six up-to-date CI checks, resolved
conversations and linear history. Force push and deletion are blocked even for
admins. Extra reviewer approval is optional for this single-maintainer repository.
See [CONTRIBUTING.md](CONTRIBUTING.md), [VERIFICATION.md](VERIFICATION.md),
[ROADMAP.md](ROADMAP.md) and [SECURITY.md](SECURITY.md).
