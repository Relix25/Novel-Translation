# Novel benchmark protocol

Benchmarks are isolated experiments through the production translation workflow.
They do not modify the production library, approve drafts or change the production
Luna High / Luna Low / Sol High profile. A new experiment, recovery, parallelism
or removed ceiling requires a corresponding explicit user request. Cleanup and
structural testing authorize no inference.

## Corpus and common conditions

The fixed fixture is the complete UDHR preamble in English, Simplified Chinese,
Korean and Japanese, with French/English references. Archived files attribute
translations to OHCHR and are distributed with Unicode ICU notices. The exact
upstream commit, provenance limitations, extraction lines and SHA-256 values are
in `corpus/manifest.json`; keep the corpus bytes and licences unchanged. Current
OHCHR PDFs were not byte-verified. This familiar institutional prose is not a
user-supplied novel and may have been memorized by a model.

Normalization trims indentation and joins selected nonempty lines with one
space. A complete preamble forms one segment; differing editions are not falsely
presented as sentence-aligned. Git attributes preserve archived bytes across
Windows/Linux clones.

Comparable cells share title, style, source, prompt and schema. No glossary,
summary, narrative history, memory, correction or target reference is supplied
to the translator. References stay outside generation context. Each trial uses
a fresh library and passes through queue_job, prepare, bounded batches and submit.
Its validated output remains unapproved; previous trials cannot populate its
local batch cache.

Codex owns ChatGPT authentication. Generation requires confirmed ephemeral
threads, tools refused, service tier default and the exact supported model/effort.
A rerouted model invalidates a trial. Record the announced model and acknowledged
per-turn request; do not claim an independent server echo of the effort actually
executed. The real catalogue advertises capabilities; only a completed real call
proves access. No automatic retry or silent substitution after failure.

## Pilot and full matrix

The default pilot has nine matched Japanese-to-French cells:

| Model | Requested efforts |
| --- | --- |
| gpt-6-luna | low, high, max |
| gpt-6.1-sol | low, high, ultra |
| gpt-6-astra | low, high, ultra |

A recorded fixed seed randomizes these cells. Seven Luna High coverage calls
then cover English-to-French, Chinese-to-French/English, Korean-to-French/English,
Japanese-to-English and return English from the actually generated French of the
English-to-French leg. That return is dependent, not a direct independent test.
Compare matched pilot configurations only on Japanese-to-French; coverage totals
across different routes are not comparable. One observation cannot establish a
statistical ranking.

Default ceilings are 16 calls, 200,000 known tokens, three observed account quota
percentage points and a five-percent remaining reserve. Checks occur between
calls, so an in-progress call or delayed counter can exceed a ceiling. The runner
also refuses another call when remaining budget is below the smallest input
context already observed.

`plan --mode full` records all supported efforts among low/medium/high/xhigh/max/ultra
for the three named models, without aliases. The recorded catalogue had 17
configurations: eight routes times three repetitions gave 408 planned positions.
Future catalogues can differ. Direct routes are randomized per repetition;
dependent returns follow their outgoing leg. Set explicit ceilings before running.

## Measurement and interpretation

Retain exact sources/prompts/schemas/outputs and fingerprints, model/effort,
ephemeral confirmation, job/session IDs, raw responses, final state, errors,
latency and every available usage counter. Failed attempts remain in the journal
and costs. Interrupted counters are known incomplete values, not final measurements.
Cached input is part of input; reasoning is part of output. Do not add either twice.
Missing measurements stay absent, never zero.

Read account quota before/after calls and at experiment boundaries, in percentage
points per bucket/window. Keep reset identities separate; never add incomparable
windows or deltas across a reset. Shared activity, rounding, telemetry delay and
concurrent overlapping intervals prevent exact per-configuration attribution.
A displayed zero can mean use below counter resolution, not a free call. Tokens
and API prices cannot be converted into included subscription quota percentages.

Record sequential/concurrent measurement mode and phase. Mixed load describes
observed execution, not intrinsic model speed. Distinct planned-slot keys govern
coverage; retries add costs/attempt records, not independent repetitions. Median
and min-max range describe available repetitions; they are not confidence intervals.
Generalization needs multiple authorized literary passages, independent repeats,
counterbalanced order and separate multi-batch/context scenarios.

## Separate quality assessment

Check structure, completeness, target language and refusals first. Blind and
shuffle candidates; keep model/effort identity in a separate key. Human bilingual
readers cite exact source/output passages and adjudicate disagreements. Report
critical, major, minor and uncertain findings separately. Lexical similarity to
one reference does not prove fidelity; institutional variants can differ.

Optional AI review uses Sol High, at most two passes per bounded batch. The second
is restricted to corrected/uncertain material or a specifically authorized final
attempt after a proven first-pass failure. It never edits benchmark originals,
approves a chapter or fabricates a human quality score. Exact source/candidate
pairs may share a cited judgment with explicit hashed provenance; reuse is not
another independent vote or another billable call.

Full review batches have at most 12 candidates and 60,000 data characters. Exact
citations are validated character by character. The return leg is judged against
its actual French input. A separate chain case compares initial and final English.
Keep step and chain findings distinct: errors can propagate, overlap or compensate,
so their counts are not added together. One AI judge has possible interpretation,
reference-memory and family biases; a bilingual reader must validate findings.

## Commands and private outputs

Run from the repository root with Codex signed in. Planning reads the real
catalogue but performs no translation. Generation commands require explicit
authorization; use new output directories under an ignored `local-*` location.

```powershell
python benchmark.py plan --mode full --output local-benchmark-plan
python benchmark.py run --output local-benchmark-pilot
python tools/benchmark_report.py local-benchmark-pilot
```

The runner retains results.json/results.csv, catalogue.json, plan.json, provenance,
trial libraries, exact prompts and raw responses. Account snapshots, outputs,
tokens and execution verification remain private. Reports are local HTML plus
CSV/JSON; optional charts require Matplotlib and export PNG/SVG/PDF. The software
report labels are English; sources, translations and cited evidence retain their
own languages. Reporting commands never call a model.

For a separately authorized full campaign:

```powershell
python benchmark.py run --help
python tools/benchmark_quality_full.py --help
python tools/benchmark_global.py local-benchmark-full --quality local-benchmark-quality/quality.json
python tools/benchmark_conclusions.py local-benchmark-full local-benchmark-quality/quality.json
```

Choose explicit token and percentage-point ceilings before using run/review.
Full review's ceilings include the campaign's existing usage and original quota
baseline; they are not a fresh allowance. `--all-cells` continues independent
preregistered cells after a refusal while skipping later repetitions of that
rejected cell. Missing outgoing legs block their dependent returns.

## Manual recovery and documented adaptations

Ordinary failures stop work without retry. A new explicit continuation can use
`--continue-from` with a new output folder, preserving earlier attempts, hashes
and dependencies. The combine tool joins finished evidence blocks without editing
originals. New-block and cumulative usage are labelled separately.

A manually invoked recovery can select previously failed/unprocessed positions;
it retains original errors and does not automatically retry a new failure. A
content refusal is not a reason to bypass safeguards. Frozen partitions remain
finite; removing aggregate ceilings or using parallel workers is a separate
explicit choice. Operational watchdogs, profile checks, ephemeral sessions and
maximum review passes remain active. A quota reset does not erase earlier costs;
unobserved time before the reset remains unknown.

Quota reads allow 30 seconds; one independent fresh read transport can recover an
unavailable reading, with its failure/recovery recorded. This never retries an
inference. Small deadline jitter is tolerated only for the administrative guard
under the recorded identity/duration/future-time/nondecreasing-counter constraints;
strict scientific deltas become unavailable when reset identity changes.

`--reuse-server` can retain the review transport, but every pass still creates a
fresh confirmed ephemeral thread with a unique ID, never thread/resume. Generation
errors close the real transport without restart. At most three bounded read-only
connection checks can address the specific routing failure before generation.
`--continue-unstarted` requires evidence that prior connection setup failed before
any inference: empty trial directory and no inference entry. Finished verdicts and
actual failed calls are not silently retried.

A specifically authorized final second pass after an interrupted real first pass
must verify exact cases and traces. If a finished first pass contains invalid
citations, preserve strictly valid verdicts and mark only invalid cases uncertain.
Only those cases can enter pass two. Never repair quotations artificially, reread
an already valid case, discard earlier tokens or add a third pass. Final failure
remains unavailable. Later adaptations must remain labelled; do not present an
incident-driven campaign as fully preregistered before the first call.

The corrected-draft tool can clone trial libraries and apply uniquely anchored,
source-cited editorial edits through prepare/submit without inference. It preserves
original measurements and leaves revised drafts unapproved and unassessed. Never
assign an original verdict or cost measurement to a changed translation.

Consult code docstrings, command help and the private recorded provenance for the
exact run. Public reproducible checks are in [VERIFICATION.md](../VERIFICATION.md);
real execution/account records are excluded from Git. Historical experiment
permissions do not authorize new generation in an unrelated maintenance task.
