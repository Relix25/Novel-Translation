# Verification

## Migration baseline — 12 October 2026

- 99 synthetic tests passed locally through `test.cmd`.
- GitHub CI passed Python 3.11/3.13 on Windows/Linux, frontend and isolated Docker.
- Production dependency audit reported zero vulnerabilities.
- Libraries were copied after controlled shutdown. File hashes, SQLite integrity
  and all existing database rows were compared after startup.
- The container is healthy, with its library mounted from this repository,
  sources read-only and the existing Codex volume retained.
- ChatGPT login, the Luna/Sol catalogue and quota were verified without inference.

## English interface and prompt integration

104 synthetic tests passed locally through `test.cmd` after the English and
literary prompt changes. Five new regressions exercise the editorial contract.

Interface, diagnostics, launchers and public documentation use English.
Imported texts and multilingual fixtures keep their declared languages; user
sources and identifiers are never rewritten.

The user-supplied Astra specification becomes one literary policy for CLI
preparation and every translation batch. Regressions cover scoped inputs,
current-batch schema IDs, blocked responses, exact quotations, atomic notes,
legacy responses and exclusion from the reader.

Detailed reports, account data, paths and fingerprints stay in ignored locations.
No private manuscript, database, EPUB or credential is in Git or the Docker image.

## GitHub

CI runs for main/dev pushes, PRs and manual dispatch, with pinned Actions and
read-only permissions. Main requires six up-to-date checks, PRs and resolved
conversations; force push and deletion are blocked for admins too.

Dependabot follows npm, Actions and Docker on dev. The initial four PRs predated
the Windows temporary-path test fix; their Windows failures alone do not prove
dependency incompatibility. See [the review](docs/DEPENDENCY_REVIEW.md).

Current results are in [Actions](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml).
Configuration alone is not a passing result; inspect the delivered commit's run.

## Limits

Tests and catalogue access prove neither every model's generation availability
nor literary quality. Bilingual human review remains necessary. Private texts
and real trials are never public fixtures.
