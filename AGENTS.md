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
