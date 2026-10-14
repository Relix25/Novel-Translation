# Verification

Public verification records reproducible checks, versions and limitations.
Real manuscripts, trial outputs, per-call tokens, account readings and execution
logs remain in ignored local evidence. This cleanup started no real generation.

## Cleanup — 14 October 2026

The existing suite passed 185 tests before cleanup. Added regressions cover a
global backup without a series, active-work backup refusal, malformed JSON/media
types, private artifact detection, binary Git object auditing, escaped report
citations, unavailable values and absence of unrecorded historical costs.

The final local cleanup suite passed **195 Python tests** through `test.cmd`.
Ruff lint/format, frontend lint/format, all four frontend tests and the production
build passed. The full npm dependency audit reported no vulnerabilities; existing
locked runtime versions were preserved.

An isolated browser check loaded the synthetic demo, opened Workspace, edited a
paragraph and observed autosave, approval retirement and retained version history.
No Codex connection or inference was started; browser artifacts stay ignored.

Four frontend transport tests cover same-origin paths, CSRF, Unicode, server
errors, interrupted mutations without retry and unexpected non-JSON responses.
Python and frontend formatting/linting use pinned development tools. CI enforces
them alongside the structural tests, frontend build/audit and isolated Docker smoke.

Run the exact checks in [CONTRIBUTING.md](CONTRIBUTING.md). The final checked
commit's CI result is authoritative; configuration alone is not a passing result.
[GitHub Actions](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml)
shows Python 3.11/3.13 on Windows/Linux, frontend and Docker.

## Migration and earlier foundation

The initial migration passed 99 synthetic tests; English interface and literary
prompt integration passed 104. Migration compared copied files, SQLite integrity
and existing database rows after controlled shutdown. Docker keeps the catalogue
mount, read-only sources and the existing Codex-owned session volume. Health,
login/catalogue/quota checks are distinct from generation and literary validation.

Editorial regressions cover scoped inputs, current-batch IDs, blocked responses,
exact quotations, atomic notes, legacy responses and reader exclusion. Original
texts, multilingual fixtures and stable serialized markers keep their identities.

## Privacy and release checks

`tools/check_public_files.py --history --worktree` inspects staged/history blobs
and publishable working files. It reports filenames/categories only, checks
private local directories and uses Git's binary-safe batch protocol. `.gitignore`
protects private libraries, imports, backups, credentials and local evidence;
Docker uses a public-source allowlist. Manual diff inspection remains required:
no pattern scanner can identify every private sentence in otherwise public code.

Local Docker Desktop was unavailable during cleanup. The user explicitly deferred
deployment; no library/session volume was replaced. Docker image compatibility is
checked by the isolated CI job, and live replacement still requires the guarded
backup/row-comparison procedure in DOCKER.md when deployment is requested.

Main requires a PR, six current CI contexts, resolved conversations and linear
history; force push/deletion are blocked for admins too. Dev is preserved.
Dependabot targets dev; historical dependency findings are in
[DEPENDENCY_REVIEW.md](docs/DEPENDENCY_REVIEW.md).

## Limits

FakeBridge tests and synthetic stdio peers validate structure and behavior. They
prove neither access to every real model/effort nor translation quality. Real
benchmark trials and their tokens are documented separately and privately.
Exact citations demonstrate evidence attachment, not a correct bilingual verdict.
AI findings never replace final chapter, summary or memory approval.
