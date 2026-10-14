# Using Novel

Novel is a local workspace for importing sources, generating drafts through
your Codex-owned ChatGPT session, comparing texts and approving exact versions.
Start with the [installation commands](../README.md). Docker users should also
read [storage, updates and rollback](../DOCKER.md).

## Learn with the demo

Select **Load synthetic demo** in **Library**. Its short fictional sources and
translations exercise the interface without reading your books or calling a
model. Source and translation languages remain distinct. Loading the same demo
again does not duplicate it, including libraries with its old display name.

## Create a series and import sources

1. Create a series with its source language, target languages and translation
   style, or choose **Import folder** from the library.
2. Choose a folder of EPUBs or UTF-8 TXT/MD chapters. Keep EPUBs and plain-text
   chapters in separate folders. In Docker, enter `/imports`; the container
   cannot display a native Windows folder picker.
3. Check the preview: detected language, volumes, sections, titles and ordering.
   The preview fingerprint must still match when you import.
4. Inspect the imported text. EPUB ruby readings are pronunciation evidence,
   not automatically approved names or story facts. Image-based characters
   need inspection and transcription before generation.

Reimporting an unchanged source is safe. A changed source does not silently
replace an imported chapter. Original EPUBs are archived by hash. Stable chapter
and paragraph identifiers survive later imports; reading order can differ from
the numerical identifiers when an earlier volume arrives later.

Source chapters, drafts, summaries and memory are separated by language pair.
Choose the source and target at the top of a series before working. Imported
texts keep their original language; the software interface uses English.

## Set terminology and Codex preferences

In **Entities & memory**, concepts link language forms and their first appearances.
Check names and forms yourself before saving them as approved terminology. A
future form must not enter an earlier chapter's context. New glossary decisions
can retire affected translation and summary approvals; re-read those chapters.

Use **Connect Codex** after signing into Codex with ChatGPT. For native mode,
install the Codex CLI or set `NOVEL_CODEX_BIN` to its executable. Docker keeps
authentication in its existing named volume. Never put credentials into Novel's
library, source folders, Git or an image.

The requested production profile is Luna High for translation, Luna Low for
summaries and entity proposals, and Sol High for AI review. The actual catalogue
must support the selected model and effort. An unavailable profile blocks the
operation; there is no silent switch to another model. Generation requires
Codex to confirm a fresh ephemeral session.

## Translate a selection

Use **Chapters** to filter and select chapters, ranges or volumes, then choose
**Prepare batch**. Existing drafts and chapters already reserved by active runs
are excluded from new bulk translation. Review an existing draft individually.

Check the exact selection, source/target pair, profile and safeguards. Preparation
and estimates do not generate text. **Start batch** authorizes the selected work.
Long chapters are divided into bounded paragraph batches. Every supplied ID must
appear exactly once and in order before a complete chapter draft can be saved.
An invalid response cannot replace an existing draft with a partial translation.

The literary policy preserves meaning, ambiguity, voice, pacing and cultural
setting while using natural target-language prose. Missing chapters or unreadable
text are never invented. See the [prompt contract](TRANSLATION_PROMPT.md).

## Edit and approve in Workspace

Open a chapter to compare the source and draft. Search and pagination help with
long chapters. Edit the translation paragraphs, keeping each segment's identity.
Autosave waits briefly while you type and refuses stale or empty paragraphs.
Unsaved edits also remain in this browser's local storage, scoped to the series,
language pair and chapter. They are private manuscript data: use your own browser
profile and do not treat browser storage as a library backup.

If another version appeared, inspect it before resuming edits. A timeout can occur
after the server saved a change. Refresh and check the version before trying again;
Novel does not automatically retry a mutation. Version history retains older
drafts. Restoring a version creates an unapproved current draft.

**Editorial notes — not for publication** contains exact source quotations and
actionable uncertainty or terminology proposals. Notes stay attached to their
translation and context fingerprints. They do not enter the reader or approve
glossary forms, memory or chapters automatically.

Read the whole bilingual chapter before approving it. Supply a meaningful review
reason; approval applies to the exact translation and current context fingerprints.
Document any intentional glossary exception. An edit, relevant glossary change or
changed context can retire approval. AI review is a separate process: Sol checks
at most two passes per batch, with the second restricted to corrected or uncertain
batches. Remaining findings still require your decision.

## Summaries and story memory

Summaries require an approved translation, cite source segment IDs and have a
separate approval. Read the summary before approving its exact fingerprint.
Changing the translation retires the summary's approval.

Choose a chapter cutoff in **Entities & memory**. Proposed observations cite exact
source passages and remain unapproved until you decide on each fact with a reason.
Future names and facts stay hidden by actual reading order. Only approved earlier
facts whose evidence still matches the source can enter translation context.
Classifying an entity or proposing a name does not approve all of its facts.

## Jobs, pause and usage

**Jobs** shows the model, phase, batches, review passes, progress and known usage.
**Pause after call** lets the current call finish and saves its usable result.
**Stop now** interrupts it; already used tokens are not refunded. Errors and unknown
usage pause processing. Restarting the application never resumes generation.
Resume explicitly after checking the saved state and remaining limits.

Valid cached batches are reusable only when prompt, context, model and effort
match. Changing the policy or context prevents reuse of a differently prompted
batch. Limits apply to calls, known tokens, duration and inactivity. A current call
can exceed a ceiling before usage is reported.

**Usage** separates input, cached input, output and reasoning. Cached input is
included in input; reasoning is included in output. Do not add them twice.
Credit estimates are illustrative, not a percentage of ChatGPT quota. The quota
panel shows actual account windows and reading freshness; unavailable readings
are not zero. Other account activity can change those observations.

## Reader and backups

The reader exports only chapters with valid current approvals. It remains local;
exporting does not publish a website. Editorial notes do not appear in it.

In **Codex & preferences**, use **Back up library** with no active work. A complete
backup contains the catalogue, pair databases, source EPUBs and review reports;
`COMPLETE.json` is written last. A folder without that marker is incomplete.
Codex authentication is excluded. Back up again before an update or rollback.
Docker restore refuses an existing destination and checks SQLite and EPUB hashes;
see [DOCKER.md](../DOCKER.md). Reassociate source folders after restoring elsewhere.

## Troubleshooting

| Symptom | Check and action |
| --- | --- |
| Blank interface or missing assets | Run the frontend build; keep the Python process running. Docker includes the build. |
| Address or library already in use | Use the existing instance. Stop it before starting another writer on the same library. |
| Codex unavailable | Check CLI installation, ChatGPT sign-in and **Connect Codex**. Do not copy auth files. |
| Model/effort unavailable or ephemeral mode unconfirmed | Stop and inspect the connection. Do not substitute a profile or persistent session. |
| Import preview changed | Preview the current folder again; do not reuse an obsolete fingerprint. |
| Glyph blocks generation | Inspect the archived image and record a justified transcription. |
| Draft or approval is stale | Compare the current source, terminology and context, then review the exact current version. |
| Job stopped or usage is unknown | Inspect the retained error and counters; explicitly decide whether to resume. |
| Docker refuses update/stop | Pause active work and wait for the current call. An unreachable running API also blocks replacement. |

Inspect logs locally before sharing them. Never include manuscripts, credentials,
account readings or personal paths in a public issue.

## Manual single-pair CLI

`novel.cmd` wraps `novel_v1.py` on Windows. This is a separate single-pair workflow;
do not point it at the application's catalogue root or modify a live pair database.
Use an isolated ignored directory such as `local-cli-project`:

```powershell
python novel_v1.py --root local-cli-project init --title "Synthetic series" --source-language en --target-language fr --style "Faithful natural prose"
python novel_v1.py --root local-cli-project import 1 local-source/chapter.txt --title "Chapter one"
python novel_v1.py --root local-cli-project prepare 1
python novel_v1.py --root local-cli-project submit 1 local-response/response.json
python novel_v1.py --root local-cli-project status
```

Read the prepared context and template before supplying them to Codex. Submit
its JSON response, inspect the draft, then use `review 1 --hash EXACT_HASH
--reason "Bilingual review reason"`. Summary operations are `prepare-summary`,
`summary` and `review-summary`. `export` writes the local reader. CLI `backup FILE`
backs up that single pair; it is not the complete catalogue backup used by Docker.
