# Dependency review

## Cleanup check — 14 October 2026

The original four Dependabot PRs remain open and now target dev. The cleanup
preserves locked runtime versions and the production profile; it does not merge
the major Node/Vite changes. Development-only Ruff, Prettier and Oxlint enforce
the new checks, with pip added to Dependabot's dev targets. The full local npm
audit reports no vulnerabilities. Main retains the same six required CI contexts.

## Initial review — 12 October 2026

Four initial PRs target main and predate the Windows backup test correction.
Their frontend, Linux and Docker jobs passed; both Windows jobs failed on the
inherited temporary-path alias. Refresh the base before judging final CI.

| PR | Change | Review |
| --- | --- | --- |
| [#1](https://github.com/Relix25/Novel-Translation/pull/1) | setup-node 6.5.0 → 7.1.0 | Action-only, SHA retained; refreshed CI required. |
| [#2](https://github.com/Relix25/Novel-Translation/pull/2) | setup-python 6.3.0 → 7.0.0 | Action-only, SHA retained; refreshed CI required. |
| [#3](https://github.com/Relix25/Novel-Translation/pull/3) | Node image 22 → 26 | Major runtime upgrade; build success is not live Codex compatibility. Keep Node 22 pending review. |
| [#4](https://github.com/Relix25/Novel-Translation/pull/4) | Vite 7.3.7 → 8.3.4 | Major build-system upgrade introduces Rolldown/Lightning CSS. Initial frontend/Docker builds passed; inspect configuration and Windows compatibility. |

No dependency PR was automatically merged. Future npm, Actions and Docker
updates target dev, then reach main through a checked PR.
