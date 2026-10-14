# Literary prompt integration

The user-supplied Astra specification asks for natural wording without making
the original simpler, more explicit or more ornate. Novel adapts it to segmented JSON.

`translation_prompt.instructions()` loads `prompts/literary_translation.md`.
CLI preparation and automatic batches share this policy. A policy change alters
the full prompt hash, preventing reuse of differently prompted cached batches.

Actual packet fields supply languages, style, scoped approved terminology,
earlier summaries, approved observations and source segments. At most two prior
translated paragraphs supply continuity; they are never translated again.
No unsupplied chapter or example is implicitly available.

The shared policy takes supplied JSON inputs, not an instruction to read files
inside a tool-refusing generation turn. CLI operators read the prepared context
and template before providing them; automatic batches embed their scoped JSON
directly. A wording change in this wrapper also changes the prompt cache key.

The priorities are completeness/meaning, literary effect, scoped continuity,
idiomatic form and simple wording. Ambiguity, voices, viewpoint, pacing,
intensity and cultural setting survive. Missing text is never invented.

## Structured editorial mode

The prose-only output options become JSON with unchanged chapter and
source/context fingerprints. Every current-batch ID appears once, in order,
with its complete translation.

`editorial_notes` objects contain `id`, `category`, `source_quote`, `rendering`
and `detail`. Categories are ambiguity, source error, continuity conflict,
wordplay loss and proposed terminology. Quotes must exactly match the cited
source segment. The schema constrains IDs and Python validates before caching
or saving any draft.

Notes are stored under translation/context hashes in `translation_notes` and
shown separately. They never enter translated text, the reader, approved glossary
or approved memory. New translation hashes leave earlier notes attached to their
old version.

`blocked_reason` is empty on success. Missing, unreadable or contradictory input
sets an explanation and empty translation/notes arrays. Novel rejects the result,
preserves earlier work and requires explicit action. Legacy responses without
these fields remain supported.

The internal bilingual check adds no model call. Luna High, Sol High (at most
two passes) and Luna Low summaries remain unchanged. Synthetic tests require no
real generation.
