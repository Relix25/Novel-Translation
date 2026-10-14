# Novel

This repository is the local foundation for translating long-running series with Codex.

- Generate translations and summaries through Codex using the ChatGPT account. Do not add an API key or external generation service.
- Preserve original sources and segment identifiers. Never invent text to replace a missing chapter.
- Prepare context with `prepare` and submit JSON with `submit`. Read before approving an exact fingerprint with `review`.
- Apply the approved glossary within its scope. Document exceptions in the review reason. A glossary change requires new approval of affected chapters.
- Summaries must cite chapter segments and be reviewed and approved separately. Do not introduce facts revealed after the reader's chapter.
- The demonstration is synthetic. It is not a translation of a novel supplied by the user.
- Run `test.cmd` after changing the foundation. Structural tests do not replace bilingual reading of real texts.
- Do not publish the reader or schedule recurring processing without a corresponding user request.
- The standalone application starts through launch.cmd/app.py; library.py manages series and multilingual concepts. Preserve existing databases.
- Use Codex App Server with the ChatGPT session owned by Codex. Never copy or display credentials.
- Automatic Novel jobs use ephemeral Codex sessions. If Codex does not confirm this mode, refuse generation; never silently fall back to a persistent chat.
- User-requested profile: Luna High for translation and Luna Low for summaries. Automatic review uses Sol High with at most two passes per batch; the second checks only corrected or uncertain batches. Preserve versions and cited decisions. No additional pass, silent model change or automatic restart after an error. AI review remains separate from final approval and summary approval.
- FakeBridge tests are structural and do not prove access to a real model. Document real Codex trials and their tokens separately.

## Maintenance map

- Read `docs/ARCHITECTURE.md` for storage, concurrency and fingerprint contracts; `docs/USER_GUIDE.md` describes actual user flows. Keep docstrings next to non-obvious invariants. Follow `CONTRIBUTING.md` for checks.
- Tests live in `tests/`. Run `test.cmd` (or `python -m unittest discover -s tests -p 'test_*.py' -v` on Linux), Ruff checks, frontend lint/format/tests/build and the staged/history/worktree privacy audit after relevant changes.
- Keep real account readings, trial tokens and outputs in ignored local evidence. Public verification describes synthetic/reproducible checks, not private records. Never run a benchmark or real generation merely to validate a cleanup.
- Historical benchmark recovery, parallelism and budget exceptions are evidence of earlier explicit requests, not authorization for a new task. They do not alter the application's production profile or approval rules.
- The Docker context is an explicit allowlist. A new runtime module needs a corresponding entry; tests, tools, developer environments and libraries stay outside the image. Preserve the Compose project, library and existing Codex volume.
- Use English software prose. Preserve original manuscripts, multilingual fixtures, exact evidence, stable serialized compatibility markers and license notices.
