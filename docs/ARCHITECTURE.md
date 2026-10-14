# Architecture and maintenance contracts

Read [AGENTS.md](../AGENTS.md) before editing. It defines the generation,
approval and privacy rules. This guide describes the current implementation;
docstrings describe contracts next to the code. The backend is standard-library
Python 3.11+, with no generation API key or external inference service.

## Module boundaries

| Module | Responsibility |
| --- | --- |
| `app.py` | HTTP adapter, application lifetime, library lock, one worker, serialized mutations and quota polling |
| `library.py` | Catalogue, imports, multilingual concepts, pair synchronization, jobs and complete backups |
| `novel_v1.py` | Canonical JSON/hashes, immutable segments, draft/version/approval/summary lifecycle, reader and single-pair CLI |
| `codex_bridge.py` | Codex App Server stdio RPC, ChatGPT account/catalogue checks, confirmed ephemeral sessions and turn events |
| `batches.py`, `translation_prompt.py`, `prompts/` | Bounded context, literary policy, strict response schema and editorial notes |
| `job_tracking.py`, `bulk_jobs.py` | Durable calls/progress/limits, stop/pause, ordered bulk selection and explicit resume |
| `quality_review.py` | Exact evidence, version-checked corrections and at most two review passes |
| `story_memory.py` | Cited observations, chapter cutoffs, separate decisions and earlier approved context |
| `epubs.py`, `folders.py`, `source_images.py` | Bounded parsing, preview fingerprints, archived sources, ruby and glyph overlays |
| `quota.py`, `consumption.py` | Fresh account windows, measured usage and explicitly labelled estimates |
| `instance_lock.py` | OS-owned exclusive library writer lock |
| `docker_bootstrap.py`, `docker-novel.ps1` | Host-side guarded migration, backups, source selection and container lifecycle |
| `benchmark.py`, `tools/benchmark_*` | Isolated experiments and offline reports; never mutate the production library |

The flat runtime modules keep native execution and the explicit Docker build
allowlist simple. Tests live in `tests/`; tools do not enter the runtime image.
Do not create an abstraction solely to wrap one existing call. Split a component
when it owns a distinct contract or removes duplication.

## Storage and lifecycle

```text
library root/
  library.sqlite                  catalogue, originals, concepts, jobs, calls, memory
  books/<sha256>.epub              immutable referenced archives
  series/<series-id>/<src>--<dst>/  language-pair workspace
    novel.sqlite                  chapters, drafts, versions, approvals, summaries, notes
    packets/                      prepared context/templates and local response artifacts
  reviews/                        bounded AI review evidence
  backups/<id>/                   complete snapshots; COMPLETE.json is written last
```

See `Library.pair()` for the authoritative path construction. These locations are
private regardless of their filenames. Codex authentication belongs outside the
library and is never read, displayed or backed up by Novel.

Schema initialization is additive. Preserve tables, rows, sources, IDs and audit
history; do not replace databases to simplify a migration. SQLite context managers
commit/rollback but do not close connections. `App.library()` and `Library.pair()`
close explicitly, and each request or worker creates its own connection.

The application binds the port before acquiring/recovering the library. A failed
duplicate launch cannot mutate live jobs. The OS lock prevents two app writers;
HTTP mutations use a reentrant lock and inference runs on a single executor.
Completion checks source/context/version fingerprints instead of trusting the
time the request began. Recovery records interruptions and pauses runs; it never
submits another model call. Shutdown interrupts active work and joins the worker.

## Fingerprints and approval

`novel_v1.encode()` is canonical sorted compact JSON; `digest()` is SHA-256 over
UTF-8. Paragraph IDs include chapter number, paragraph ordinal and original source
hash prefix. Never regenerate IDs for a UI rename or split imported paragraphs
in place. French legacy EPUB markers remain serialized source evidence; display
overlays can use English without rewriting that evidence.

A packet hash binds the source, scoped terminology, prior approved summaries,
source-image readings and earlier approved memory. Catalogue reading position,
not numeric chapter ID, governs scope after out-of-order volume imports.

`prepare` produces context, template and policy. `submit` validates all segments
before saving an unapproved draft. Edits/restores retain history and require current
fingerprints. `review` grants approval only after explicit reading and a reason.
Translation/context changes retire approvals; summaries have separate evidence,
translation hashes and approvals. AI review never replaces that final decision.

Editorial notes are separate rows keyed by chapter, translation hash and packet
hash. They cite exact supplied segments and never enter translated prose, the
reader, approved terminology or memory automatically. Full prompt hashes also
bind batch cache reuse; a changed policy invalidates older cache entries even if
the chapter's source hash is unchanged. See [the prompt contract](TRANSLATION_PROMPT.md).

## Generation and jobs

App Server owns ChatGPT authentication. Novel validates the real catalogue and
selected effort, requires `thread/start` to confirm `ephemeral: true`, then sends
the manuscript. An unconfirmed/persistent session receives no manuscript.
Tools are refused, generation is read-only, and no inference failure triggers an
automatic retry, profile substitution or persistent-thread fallback.

Production defaults are Luna High translation, Luna Low summary/entity proposal
and Sol High review. Review has at most two passes per batch; the second inspects
only corrected/uncertain material. Versions and cited decisions survive errors.
Historical benchmark recovery authorizations are evidence of earlier experiments,
not permission to generate, parallelize or disable limits in a new task.

Jobs persist state, calls, progress, errors and known usage. Pause after call and
immediate stop differ. Unknown counters are explicit; token limits are checked
between calls and cannot guarantee that the current call stays below its ceiling.
Cached input and reasoning output are subsets of input and output. Quota windows
have identity/reset/freshness constraints and represent the shared account.

## HTTP and frontend

The app is local, single-owner software. Native mode binds `127.0.0.1`; Docker
binds internally while publishing only `127.0.0.1:8791`. Every request checks the
configured Host. Mutation requests also require the exact Origin, a random
process CSRF token, JSON media type and a bounded body. Static assets must resolve
inside the build assets directory. CSV titles are neutralized for spreadsheet
formula injection. This service is not an Internet/multitenant deployment.

| Route | Contract |
| --- | --- |
| `/health` | Status and backend version; no inference |
| `/api/state` | Catalogue and lightweight job metadata, CSRF token, connection, capabilities and quota |
| `/api/activity`, `/api/quota` | Poll progress/account cache without sending manuscript bodies |
| `/api/pair`, `/api/chapter`, `/api/version` | Pair state, exact chapter/context data and immutable version inspection |
| `/api/memory`, `/api/quality`, `/api/glyph` | Scoped evidence, current/stale review reports and archived glyph images |
| `/api/usage`, `/api/usage.csv` | Recorded usage and export; missing counters stay unavailable |
| `/api/action` | Serialized POST dispatcher; malformed objects produce a JSON error |
| `/reader` | Guarded local export; requires valid chapter approvals |

`frontend/src/api.js` owns same-origin JSON transport and timeouts. It never retries
mutations: a timeout can follow a committed write. Refresh and inspect fingerprints
before retrying. The React shell coordinates routes and selections; ChapterList,
Workshop, WorkPanels, StoryMemory and the smaller panels own their respective UI.
Effects cancel stale reads, while effect events read current selections without
resetting work on every polling render. Workshop refs serialize in-flight saves
and preserve newer typed edits. Browser draft storage is private, scoped state.

React Compiler is not enabled. Oxlint enforces correctness, Hook order/dependencies,
imports and accessibility; its Compiler-only purity/ref/effect constraints are
explicitly disabled. Do not disable a rule merely to hide a real race or unused
value. Prettier and Ruff supply repeatable formatting without runtime dependencies.

## Tests, release and private evidence

Use [CONTRIBUTING.md](../CONTRIBUTING.md) for exact checks. FakeBridge and synthetic
stdio peers test contracts, not real model access or literary quality. Test changed
concurrency, malformed responses, stale fingerprints, privacy and migration paths.
Do not generate real manuscripts as a routine cleanup check.

The Docker allowlist must include every new runtime module/policy and exclude
libraries, credentials, developer environments, tests and reports. Keep the Compose
project and Codex session volume stable. Before replacement: no active work,
complete backup, SQLite integrity/row comparison, health and connection checks.
Keep actual paths, account snapshots, trial outputs and tokens in ignored local
evidence directories. Public verification documents reproducible checks and their
limits, without those private records.

Main requires a PR, all six current CI contexts, resolved conversations and linear
history. Dev is long-lived. CI has read-only permissions and pinned Actions; the
repository also applies the versioned branch-protection policy on GitHub.
