"""Independent library, multilingual concepts and language-pair workflows."""

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from novel_v1 import Novel, atomic_write, digest, encode, positive, require
from source_images import render_source, require_readable


def language(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", value),
        "Use a language code: en, fr, zh, ja, pt-br…",
    )
    return value


class Pair(Novel):
    """A language pair with context scoped by the catalogue's actual reading order.

    Segment IDs are inherited unchanged. Glossary, approved prior summaries,
    source-image readings and earlier approved facts contribute to packet_hash.
    """

    def __init__(self, root, library, series, source, target):
        self.library, self.series, self.source_language, self.target_language = (
            library,
            series,
            source,
            target,
        )
        super().__init__(root)

    def reading_position(self, number):
        return self.library.reading_position(self.series, self.source_language, number)

    def status(self):
        return sorted(super().status(), key=lambda c: self.reading_position(c["number"]))

    def packet(self, number):
        packet = super().packet(number)
        packet.pop("packet_hash")
        packet["glossary"] = self.library.pair_terms(
            self.series,
            self.source_language,
            self.target_language,
            number,
            self.chapter(number)["source"],
        )
        # Reading order is distinct from stable IDs when an earlier volume arrives later.
        position = self.reading_position(number)
        previous = [
            dict(r)
            for r in self.db.execute(
                "SELECT number,title,translation_hash,summary FROM chapters "
                "WHERE state='approved' AND summary_state='approved'"
            )
            if self.reading_position(r["number"]) < position
        ]
        previous.sort(key=lambda r: self.reading_position(r["number"]))
        packet["previous_summaries"] = [
            {**r, "summary": json.loads(r["summary"])["text"]} for r in previous[-3:]
        ]
        origin = self.library.db.execute(
            "SELECT metadata FROM origins WHERE series=? AND language=? AND number=?",
            (self.series, self.source_language, number),
        ).fetchone()
        if origin:
            metadata = json.loads(origin["metadata"])
            packet["source_metadata"] = {
                k: metadata[k] for k in ("volume", "volume_title", "kind", "file", "book_hash")
            }
            # Pronunciation evidence from the EPUB, not approved terminology or character facts.
            packet["ruby_readings"] = [
                {
                    "id": packet["segments"][r["paragraph"]]["id"],
                    "base": r["base"],
                    "reading": r["reading"],
                }
                for r in metadata.get("readings", [])
            ]
            if metadata.get("source_images"):
                packet["segments"], packet["source_image_readings"] = render_source(
                    packet["segments"],
                    metadata["source_images"],
                    self.library.glyph_readings(self.series),
                )
        from story_memory import past_context

        memory = past_context(
            self.library,
            self.series,
            self.source_language,
            self.target_language,
            number,
            "\n".join(s["source"] for s in packet["segments"]),
        )
        if memory:
            packet["story_memory"] = memory
        packet["packet_hash"] = digest(encode(packet))
        return packet

    def validate_translation(self, packet, response):
        require_readable(packet)
        return super().validate_translation(packet, response)

    def prepare_summary(self, number):
        packet = self.packet(number)
        require_readable(packet)
        prepared = super().prepare_summary(number)
        file = Path(prepared["folder"]) / "context.json"
        context = json.loads(file.read_text(encoding="utf-8"))
        context["source_segments"] = packet["segments"]
        if packet.get("story_memory"):
            context["story_memory"] = packet["story_memory"]
        if "source_image_readings" in packet:
            context["source_image_readings"] = packet["source_image_readings"]
        atomic_write(file, json.dumps(context, ensure_ascii=False, indent=2))
        return prepared


class Library:
    """Catalogue owner, import coordinator and durable job journal.

    A Library instance owns a thread-local SQLite connection and must be closed.
    Pair databases retain their own translation/version/approval history. Schema
    initialization is additive; existing databases are never replaced.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite", timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS series(id TEXT PRIMARY KEY, title TEXT NOT NULL,
                source_language TEXT NOT NULL, target_languages TEXT NOT NULL, style TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(series TEXT REFERENCES series(id), language TEXT,
                number INTEGER CHECK(number>0), title TEXT, source TEXT, hash TEXT,
                PRIMARY KEY(series,language,number));
            CREATE TABLE IF NOT EXISTS concepts(series TEXT REFERENCES series(id), id TEXT,
                note TEXT NOT NULL, PRIMARY KEY(series,id));
            CREATE TABLE IF NOT EXISTS forms(series TEXT, concept TEXT, language TEXT,
                text TEXT NOT NULL, first_chapter INTEGER CHECK(first_chapter>0),
                PRIMARY KEY(series,concept,language), UNIQUE(series,language,text),
                FOREIGN KEY(series,concept) REFERENCES concepts(series,id));
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, series TEXT, source TEXT, target TEXT,
                number INTEGER, kind TEXT, model TEXT, effort TEXT, state TEXT,
                result TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(series,source,target,number,kind)
                WHERE state IN ('queued','running');
            CREATE TABLE IF NOT EXISTS folders(series TEXT REFERENCES series(id), language TEXT,
                path TEXT NOT NULL, fingerprint TEXT NOT NULL, imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(series,language));
            CREATE TABLE IF NOT EXISTS origins(series TEXT, language TEXT, number INTEGER,
                source_key TEXT NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY(series,language,number), UNIQUE(series,language,source_key),
                FOREIGN KEY(series,language,number) REFERENCES sources(series,language,number));
            CREATE TABLE IF NOT EXISTS translation_batches(prompt_hash TEXT, model TEXT, effort TEXT,
                result TEXT NOT NULL, job TEXT REFERENCES jobs(id), PRIMARY KEY(prompt_hash,model,effort));
            CREATE TABLE IF NOT EXISTS glyph_readings(series TEXT REFERENCES series(id), image_hash TEXT,
                text TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(series,image_hash));
        """)
        if "options" not in {
            column["name"] for column in self.db.execute("PRAGMA table_info(jobs)")
        }:
            with self.db:
                self.db.execute("ALTER TABLE jobs ADD COLUMN options TEXT")
        from job_tracking import schema

        schema(self.db)
        from story_memory import schema as memory_schema

        memory_schema(self.db)

    def close(self):
        self.db.close()

    def create(self, title, source_language, targets, style):
        source_language = language(source_language)
        require(isinstance(targets, list) and targets, "Choose at least one target language.")
        targets = sorted(set(language(t) for t in targets))
        require(source_language not in targets, "The target language must differ from the source.")
        require(title.strip() and style.strip(), "Title and style are required.")
        series_id = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO series VALUES(?,?,?,?,?)",
                (series_id, title.strip(), source_language, encode(targets), style.strip()),
            )
        return series_id

    def series(self, series_id):
        row = self.db.execute("SELECT * FROM series WHERE id=?", (series_id,)).fetchone()
        require(row is not None, "Unknown series.")
        value = dict(row)
        value["target_languages"] = json.loads(value["target_languages"])
        return value

    def add_target(self, series_id, target):
        series = self.series(series_id)
        target = language(target)
        require(
            target != series["source_language"], "Choose a language other than the primary source."
        )
        with self.db:
            self.db.execute(
                "UPDATE series SET target_languages=? WHERE id=?",
                (encode(sorted(set(series["target_languages"] + [target]))), series_id),
            )

    def import_source(self, series_id, source_language, number, title, source):
        self.series(series_id)
        language(source_language)
        positive(number)
        require(
            isinstance(source, str) and source.strip() and title.strip(),
            "Chapter number and title are required.",
        )
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute(
                "SELECT * FROM sources WHERE series=? AND language=? AND number=?",
                (series_id, source_language, number),
            ).fetchone()
            if old:
                require(
                    old["hash"] == digest(source) and old["title"] == title,
                    "This chapter already exists with different content; the original is preserved.",
                )
                return {"unchanged": True}
            self.db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?)",
                (series_id, source_language, number, title, source, digest(source)),
            )
        return {"imported": True}

    def source(self, series_id, source_language, number):
        positive(number)
        row = self.db.execute(
            "SELECT * FROM sources WHERE series=? AND language=? AND number=?",
            (series_id, source_language, number),
        ).fetchone()
        require(row is not None, "The source chapter is missing in this language.")
        return dict(row)

    def origins(self, series_id, source_language):
        return {
            r["number"]: {k: v for k, v in json.loads(r["metadata"]).items() if k != "readings"}
            for r in self.db.execute(
                "SELECT number,metadata FROM origins WHERE series=? AND language=?",
                (series_id, source_language),
            )
        }

    def glyph_readings(self, series_id):
        return {
            r["image_hash"]: dict(r)
            for r in self.db.execute(
                "SELECT image_hash,text,reason FROM glyph_readings WHERE series=?", (series_id,)
            )
        }

    def glyphs(self, series_id):
        known = self.glyph_readings(series_id)
        grouped = {}
        for row in self.db.execute(
            "SELECT language,number,metadata FROM origins WHERE series=? ORDER BY language,number",
            (series_id,),
        ):
            metadata = json.loads(row["metadata"])
            for image in metadata.get("source_images", []):
                key = image["image_hash"]
                if key not in grouped:
                    alt = image.get("alt", "").strip()
                    grouped[key] = {
                        "image_hash": key,
                        "text": known[key]["text"]
                        if key in known
                        else alt
                        if alt and len(alt) <= 20
                        else None,
                        "reason": known[key]["reason"] if key in known else "",
                        "occurrences": [],
                    }
                grouped[key]["occurrences"].append(
                    {
                        "language": row["language"],
                        "number": row["number"],
                        "paragraph": image["paragraph"] + 1,
                    }
                )
        return list(grouped.values())

    def glyph_image(self, series_id, image_hash):
        import zipfile

        require(
            isinstance(image_hash, str) and re.fullmatch("[a-f0-9]{64}", image_hash),
            "Invalid image hash.",
        )
        self.series(series_id)
        for row in self.db.execute("SELECT metadata FROM origins WHERE series=?", (series_id,)):
            metadata = json.loads(row["metadata"])
            image = next(
                (i for i in metadata.get("source_images", []) if i["image_hash"] == image_hash),
                None,
            )
            if image:
                with zipfile.ZipFile(
                    self.root / "books" / (metadata["book_hash"] + ".epub")
                ) as archive:
                    info = archive.getinfo(image["image_resource"])
                    require(info.file_size <= 1_000_000, "Image is too large.")
                    raw = archive.read(info)
                require(
                    hashlib.sha256(raw).hexdigest() == image_hash, "The archived image has changed."
                )
                mime = (
                    "image/png"
                    if raw.startswith(b"\x89PNG\r\n\x1a\n")
                    else "image/jpeg"
                    if raw.startswith(b"\xff\xd8\xff")
                    else "image/gif"
                    if raw.startswith((b"GIF87a", b"GIF89a"))
                    else "image/webp"
                    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
                    else None
                )
                require(mime is not None, "Image format is not supported for preview.")
                return raw, mime
        raise ValueError("Unknown source image in this series.")

    def set_glyph(self, series_id, image_hash, text, reason):
        require(
            any(g["image_hash"] == image_hash for g in self.glyphs(series_id)),
            "Unknown source image.",
        )
        require(
            isinstance(text, str) and len(text) <= 20 and not any(ord(c) < 32 for c in text),
            "Transcribe at most 20 characters; leave blank only for a decorative image.",
        )
        require(isinstance(reason, str) and reason.strip(), "A review reason is required.")
        with self.db:
            self.db.execute(
                "INSERT INTO glyph_readings VALUES(?,?,?,?) ON CONFLICT(series,image_hash) DO UPDATE SET text=excluded.text,reason=excluded.reason",
                (series_id, image_hash, text, reason.strip()),
            )
        self.reconcile(series_id)
        return {"saved": image_hash}

    def refresh_source_images(self, series_id):
        from epubs import read_epub

        self.series(series_id)
        require(
            not self.db.execute(
                "SELECT 1 FROM jobs WHERE series=? AND state IN ('queued','running')", (series_id,)
            ).fetchone(),
            "Wait for all jobs to finish before checking EPUBs.",
        )
        books, updates, occurrences = {}, [], 0
        for row in self.db.execute(
            "SELECT language,number,metadata FROM origins WHERE series=?", (series_id,)
        ):
            metadata = json.loads(row["metadata"])
            book_hash = metadata["book_hash"]
            if book_hash not in books:
                book = read_epub(self.root / "books" / (book_hash + ".epub"))
                require(book["hash"] == book_hash, "The EPUB archive has changed.")
                books[book_hash] = {c["locator"]: c for c in book["chapters"]}
            chapter = books[book_hash][metadata["locator"]]
            original = self.source(series_id, row["language"], row["number"])
            require(
                chapter["hash"] == original["hash"] and chapter["source"] == original["source"],
                "The new extraction differs from the immutable source; manual migration is required.",
            )
            metadata["source_images"] = chapter["source_images"]
            occurrences += len(chapter["source_images"])
            updates.append((encode(metadata), series_id, row["language"], row["number"]))
        with self.db:
            self.db.executemany(
                "UPDATE origins SET metadata=? WHERE series=? AND language=? AND number=?", updates
            )
        self.reconcile(series_id)
        return {
            "books_checked": len(books),
            "images_located": occurrences,
            "glyphs": len(self.glyphs(series_id)),
        }

    def reading_position(self, series_id, source_language, number):
        row = self.db.execute(
            "SELECT metadata FROM origins WHERE series=? AND language=? AND number=?",
            (series_id, source_language, number),
        ).fetchone()
        if row:
            metadata = json.loads(row["metadata"])
            return (metadata["volume"], metadata["section"])
        exists = self.db.execute(
            "SELECT 1 FROM sources WHERE series=? AND language=? AND number=?",
            (series_id, source_language, number),
        ).fetchone()
        if (
            not exists
            and self.db.execute(
                "SELECT 1 FROM origins WHERE series=? AND language=? LIMIT 1",
                (series_id, source_language),
            ).fetchone()
        ):
            # An unpublished/unimported first appearance is future, not volume zero.
            return (float("inf"), number)
        return (0, number)

    def import_folder(
        self, path, fingerprint, source_language, series_id=None, title="", targets=None, style=""
    ):
        from folders import scan_folder

        scanned = scan_folder(path)
        require(
            scanned["fingerprint"] == fingerprint,
            "The folder changed since the preview. Scan it again.",
        )
        source_language = language(source_language)
        require(
            not scanned.get("detected_language")
            or scanned["detected_language"].split("-")[0] == source_language.split("-")[0],
            "The selected language does not match the language declared in the EPUBs.",
        )
        if series_id:
            self.series(series_id)
        else:
            require(title.strip() and style.strip(), "Title and style are required.")
            require(isinstance(targets, list) and targets, "Choose a target language.")
            targets = sorted(set(language(t) for t in targets))
            require(source_language not in targets, "The target must differ from the source.")
        imported, unchanged = 0, 0
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if not series_id:
                series_id = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO series VALUES(?,?,?,?,?)",
                    (series_id, title.strip(), source_language, encode(targets), style.strip()),
                )
            for chapter in scanned["chapters"]:
                if chapter.get("format") == "epub":
                    origin = self.db.execute(
                        "SELECT number,metadata FROM origins WHERE series=? AND language=? AND source_key=?",
                        (series_id, source_language, chapter["source_key"]),
                    ).fetchone()
                    if origin:
                        chapter["number"] = origin["number"]
                        require(
                            json.loads(origin["metadata"])["book_hash"] == chapter["book_hash"],
                            "An EPUB changed: the original is preserved and the entire import was cancelled.",
                        )
                    else:
                        chapter["number"] = self.db.execute(
                            "SELECT coalesce(max(number),0)+1 FROM sources WHERE series=? AND language=?",
                            (series_id, source_language),
                        ).fetchone()[0]
                old = self.db.execute(
                    "SELECT title,hash FROM sources WHERE series=? AND language=? AND number=?",
                    (series_id, source_language, chapter["number"]),
                ).fetchone()
                if old:
                    require(
                        old["hash"] == chapter["hash"] and old["title"] == chapter["title"],
                        f"Chapter {chapter['number']} changed: the original is preserved and the entire import was cancelled.",
                    )
                    unchanged += 1
                else:
                    self.db.execute(
                        "INSERT INTO sources VALUES(?,?,?,?,?,?)",
                        (
                            series_id,
                            source_language,
                            chapter["number"],
                            chapter["title"],
                            chapter["source"],
                            chapter["hash"],
                        ),
                    )
                    imported += 1
                if chapter.get("source_key"):
                    metadata = {
                        k: v for k, v in chapter.items() if k not in ("source", "hash", "number")
                    }
                    self.db.execute(
                        "INSERT INTO origins VALUES(?,?,?,?,?) ON CONFLICT(series,language,number) DO NOTHING",
                        (
                            series_id,
                            source_language,
                            chapter["number"],
                            chapter["source_key"],
                            encode(metadata),
                        ),
                    )
                    # Enrich legacy imports without changing originals, IDs or reading order.
                    if chapter.get("source_images"):
                        stored = json.loads(
                            self.db.execute(
                                "SELECT metadata FROM origins WHERE series=? AND language=? AND number=?",
                                (series_id, source_language, chapter["number"]),
                            ).fetchone()[0]
                        )
                        stored["source_images"] = chapter["source_images"]
                        self.db.execute(
                            "UPDATE origins SET metadata=? WHERE series=? AND language=? AND number=?",
                            (encode(stored), series_id, source_language, chapter["number"]),
                        )
            for volume in scanned.get("volumes", []):
                original = Path(scanned["path"]) / volume["file"]
                require(
                    not original.is_symlink()
                    and original.resolve().is_relative_to(Path(scanned["path"])),
                    "The EPUB source moved outside the folder; scan again.",
                )
                raw = original.read_bytes()
                require(
                    hashlib.sha256(raw).hexdigest() == volume["hash"],
                    "An EPUB changed during import; scan again.",
                )
                stored = self.root / "books" / (volume["hash"] + ".epub")
                stored.parent.mkdir(exist_ok=True)
                if stored.exists():
                    require(
                        hashlib.sha256(stored.read_bytes()).hexdigest() == volume["hash"],
                        "Local EPUB archive hash mismatch.",
                    )
                else:
                    import os
                    from tempfile import NamedTemporaryFile

                    with NamedTemporaryFile(dir=stored.parent, delete=False) as temporary:
                        temporary.write(raw)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    try:
                        os.link(temporary.name, stored)
                    except FileExistsError:
                        require(
                            hashlib.sha256(stored.read_bytes()).hexdigest() == volume["hash"],
                            "Local EPUB archive hash mismatch.",
                        )
                    finally:
                        Path(temporary.name).unlink()
            self.db.execute(
                "INSERT INTO folders(series,language,path,fingerprint) VALUES(?,?,?,?) "
                "ON CONFLICT(series,language) DO UPDATE SET path=excluded.path, "
                "fingerprint=excluded.fingerprint,imported_at=CURRENT_TIMESTAMP",
                (series_id, source_language, scanned["path"], fingerprint),
            )
        return {"series_id": series_id, "imported": imported, "unchanged": unchanged}

    def concepts(self, series_id):
        result = []
        for row in self.db.execute(
            "SELECT * FROM concepts WHERE series=? ORDER BY id", (series_id,)
        ):
            result.append(
                {
                    **dict(row),
                    "forms": [
                        dict(f)
                        for f in self.db.execute(
                            "SELECT language,text,first_chapter FROM forms WHERE series=? AND concept=? ORDER BY language",
                            (series_id, row["id"]),
                        )
                    ],
                }
            )
        return result

    def set_concept(self, series_id, concept, forms, note="", kind=None):
        self.series(series_id)
        require(
            isinstance(concept, str) and re.fullmatch(r"[\w-]{1,80}", concept),
            "A concept identifier is required.",
        )
        require(isinstance(forms, dict) and len(forms) >= 1, "Add concept forms for each language.")
        if kind is not None:
            from story_memory import KINDS

            require(kind in KINDS, "Invalid entity category.")
        values = []
        for code, form in forms.items():
            language(code)
            require(
                isinstance(form, dict)
                and isinstance(form.get("text"), str)
                and form["text"].strip(),
                "A form must contain text.",
            )
            positive(form.get("first_chapter"))
            values.append((series_id, concept, code, form["text"].strip(), form["first_chapter"]))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "INSERT INTO concepts VALUES(?,?,?) ON CONFLICT(series,id) DO UPDATE SET note=excluded.note",
                (series_id, concept, note),
            )
            for value in values:
                self.db.execute(
                    "INSERT INTO forms VALUES(?,?,?,?,?) ON CONFLICT(series,concept,language) "
                    "DO UPDATE SET text=excluded.text,first_chapter=excluded.first_chapter",
                    value,
                )
            if kind is not None:
                self.db.execute(
                    "INSERT INTO memory_entities VALUES(?,?,?,?,?,?) ON CONFLICT(series,id) DO UPDATE SET kind=excluded.kind",
                    (series_id, concept, kind, None, None, "{}"),
                )
        # Reconcile every existing pair. The packet fingerprint is authoritative:
        # changed glossary or prior memory retires an approval rather than exporting it.
        self.reconcile(series_id)
        return {"saved": concept}

    def pair_terms(self, series_id, source, target, number, text):
        rows = self.db.execute(
            """SELECT a.concept,a.text AS source,b.text AS target,a.first_chapter
            FROM forms a JOIN forms b ON a.series=b.series AND a.concept=b.concept
            WHERE a.series=? AND a.language=? AND b.language=?
            ORDER BY a.text""",
            (series_id, source, target),
        )
        position = self.reading_position(series_id, source, number)
        return [
            dict(row)
            for row in rows
            if row["source"] in text
            and self.reading_position(series_id, source, row["first_chapter"]) <= position
        ]

    @contextmanager
    def pair(self, series_id, source, target):
        """Open a pair, synchronize immutable sources, then close its connection."""
        series = self.series(series_id)
        language(source)
        language(target)
        require(
            target in series["target_languages"] and source != target,
            "Language pair is not enabled.",
        )
        folder = self.root / "series" / series_id / f"{source}--{target}"
        project = Pair(folder, self, series_id, source, target)
        try:
            expected = {
                "title": series["title"],
                "source_language": source,
                "target_language": target,
                "style": series["style"],
            }
            if not project.config():
                project.init(series["title"], source, target, series["style"])
            else:
                require(
                    project.config() == expected, "Language pair configuration is inconsistent."
                )
            existing = {
                r["number"]: r
                for r in project.db.execute("SELECT number,title,source_hash FROM chapters")
            }
            for row in self.db.execute(
                "SELECT * FROM sources WHERE series=? AND language=? ORDER BY number",
                (series_id, source),
            ):
                old = existing.get(row["number"])
                if old:
                    require(
                        old["title"] == row["title"] and old["source_hash"] == row["hash"],
                        "Source differs between the catalogue and the language pair.",
                    )
                else:
                    project.import_chapter(row["number"], row["title"], row["source"])
            self.reconcile_pair(project)
            yield project
        finally:
            project.close()

    def reconcile_pair(self, project):
        # Ascending order propagates retirement of earlier summaries to later contexts.
        with project.db:
            for chapter in project.status():
                row = project.chapter(chapter["number"])
                if (
                    row["state"] == "approved"
                    and row["packet_hash"] != project.packet(row["number"])["packet_hash"]
                ):
                    project.db.execute(
                        "UPDATE chapters SET state='needs_review',summary_state=CASE "
                        "WHEN summary IS NULL THEN 'missing' ELSE 'stale' END WHERE number=?",
                        (row["number"],),
                    )
                    project.log("context_retired", {"number": row["number"]})

    def reconcile(self, series_id):
        base = self.root / "series" / series_id
        for database in base.glob("*--*/novel.sqlite"):
            source, target = database.parent.name.split("--")
            with self.pair(series_id, source, target):
                pass

    def snapshot(self):
        series_list = []
        for row in self.db.execute("SELECT id FROM series ORDER BY rowid"):
            series = self.series(row["id"])
            series["sources"] = [
                dict(s)
                for s in self.db.execute(
                    "SELECT language,number,title FROM sources WHERE series=? ORDER BY language,number",
                    (row["id"],),
                )
            ]
            for code in {s["language"] for s in series["sources"]}:
                origins = self.origins(row["id"], code)
                for chapter in series["sources"]:
                    if chapter["language"] == code:
                        chapter["origin"] = origins.get(chapter["number"])
            series["concepts"] = self.concepts(row["id"])
            series["source_glyphs"] = self.glyphs(row["id"])
            series["folders"] = [
                dict(f)
                for f in self.db.execute(
                    "SELECT language,path,imported_at FROM folders WHERE series=?", (row["id"],)
                )
            ]
            series["progress"] = []
            # Inspect existing pairs only. Do not create every possible language pair on the home screen.
            for database in (self.root / "series" / row["id"]).glob("*--*/novel.sqlite"):
                source, target = database.parent.name.split("--")
                with self.pair(row["id"], source, target) as project:
                    states = project.db.execute(
                        "SELECT state,count(*) AS count FROM chapters GROUP BY state"
                    ).fetchall()
                    series["progress"].append(
                        {
                            "source": source,
                            "target": target,
                            "counts": {s["state"]: s["count"] for s in states},
                        }
                    )
            series_list.append(series)
        return {"series": series_list, **self.activity()}

    def activity(self):
        from job_tracking import enough_usage, spent

        jobs = []
        for row in self.db.execute(
            "SELECT id,series,source,target,number,kind,model,effort,state,error,created_at,result,progress,run_id,stop_requested,started_at,finished_at "
            "FROM jobs WHERE state IN ('queued','running') OR id IN (SELECT id FROM jobs ORDER BY rowid DESC LIMIT 100) ORDER BY rowid DESC"
        ):
            job = dict(row)
            job["progress"] = json.loads(job["progress"] or "{}")
            job["tokens"], job["call_count"] = spent(self.db, job=job["id"])
            readings = self.db.execute(
                "SELECT usage FROM inference_calls WHERE job=?", (job["id"],)
            ).fetchall()
            job["usage_known"] = bool(readings) and all(
                enough_usage(json.loads(r[0] or "{}")) for r in readings
            )
            if job["result"]:
                result = json.loads(job["result"])
                # Activity polling needs progress and usage, not full manuscript output.
                job["result"] = encode(
                    {
                        key: result[key]
                        for key in (
                            "model",
                            "effort",
                            "batches",
                            "batch_total",
                            "token_usage",
                            "saved",
                        )
                        if key in result
                    }
                )
                if result.get("quality"):
                    from quality_review import compact

                    job["result"] = encode(
                        {**json.loads(job["result"]), "quality": compact(result["quality"])}
                    )
            jobs.append(job)
        runs = []
        for row in self.db.execute(
            "SELECT * FROM bulk_runs WHERE state IN ('queued','running','pause_requested','paused') OR id IN (SELECT id FROM bulk_runs ORDER BY rowid DESC LIMIT 20) ORDER BY rowid DESC"
        ):
            run = dict(row)
            run["options"] = json.loads(run["options"])
            run["items"] = [
                dict(i)
                for i in self.db.execute(
                    "SELECT * FROM bulk_items WHERE run=? ORDER BY position", (run["id"],)
                )
            ]
            run["tokens"], run["call_count"] = spent(self.db, run=run["id"])
            runs.append(run)
        return {"jobs": jobs, "runs": runs}

    def recover_jobs(self):
        """Record an interrupted process; leave every affected run explicitly paused."""
        with self.db:
            for row in self.db.execute(
                "SELECT id,result FROM jobs WHERE state IN ('queued','running') AND result IS NOT NULL"
            ).fetchall():
                result = json.loads(row["result"])
                if result.get("quality"):
                    report = result["quality"]
                    report.update(
                        status="interrupted",
                        token_usage_complete=False,
                        error="Application interrupted; explicitly restart the review.",
                    )
                    destination = (self.root / report["audit_file"]).resolve()
                    require(
                        destination.is_relative_to((self.root / "reviews").resolve()),
                        "Invalid report path.",
                    )
                    atomic_write(destination, encode(report))
                    self.db.execute(
                        "UPDATE jobs SET result=? WHERE id=?", (encode(result), row["id"])
                    )
            self.db.execute(
                "UPDATE jobs SET state='interrupted',error='Application interrupted; no automatic retry.' "
                "WHERE state IN ('queued','running')"
            )
            self.db.execute(
                "UPDATE inference_calls SET state='interrupted',error='Application interrupted; usage may be partial.' WHERE state='running'"
            )
            self.db.execute(
                "UPDATE bulk_runs SET state='paused',error='Application interrupted; explicit resume is required.' WHERE state IN ('queued','running','pause_requested')"
            )

    def backup(self):
        """Copy a quiescent library with SQLite backup and validated source archives.

        COMPLETE.json is written last. A directory without that marker is an
        incomplete diagnostic artifact and must never be accepted for restore.
        Codex authentication is outside this library and is never copied.
        """
        require(
            not self.db.execute(
                "SELECT 1 FROM jobs WHERE state IN ('queued','running')"
            ).fetchone(),
            "Wait for all jobs to finish before backing up the library.",
        )
        require(
            not self.db.execute(
                "SELECT 1 FROM bulk_runs WHERE state IN ('queued','running','pause_requested')"
            ).fetchone(),
            "Pause the batch run before backing up the library.",
        )
        folder = self.root / "backups" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            with sqlite3.connect(folder / "library.sqlite") as destination:
                self.db.backup(destination)
                require(
                    destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    "Invalid backup.",
                )
            destination.close()
            hashes = {
                json.loads(r["metadata"])["book_hash"]
                for r in self.db.execute("SELECT metadata FROM origins")
            }
            for book_hash in hashes:
                require(re.fullmatch(r"[a-f0-9]{64}", book_hash), "Invalid EPUB hash.")
                original = self.root / "books" / (book_hash + ".epub")
                require(
                    hashlib.sha256(original.read_bytes()).hexdigest() == book_hash,
                    "Local EPUB archive hash mismatch.",
                )
                target = folder / "books" / original.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(original, target)
            for database in (self.root / "series").glob("*/*/novel.sqlite"):
                relative = database.relative_to(self.root)
                original = sqlite3.connect(database)
                target = folder / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                copied = sqlite3.connect(target)
                try:
                    original.backup(copied)
                    require(
                        copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                        "Invalid series backup.",
                    )
                finally:
                    copied.close()
                    original.close()
            if (self.root / "reviews").is_dir():
                shutil.copytree(self.root / "reviews", folder / "reviews")
            (folder / "COMPLETE.json").write_text(
                encode({"format": "novel-library-v1", "complete": True}), encoding="utf-8"
            )
        except Exception:
            # Preserve the incomplete directory for diagnostics; it has no COMPLETE marker.
            raise
        return {"database_backup": str(folder)}

    def queue_job(
        self,
        series_id,
        source,
        target,
        number,
        kind,
        model,
        effort,
        review=None,
        limits_config=None,
        run_id=None,
        position=None,
    ):
        from job_tracking import limits
        from quality_review import policy

        require(kind in ("translation", "summary", "quality_review", "memory"), "Unknown job type.")
        review = policy(review)
        require(kind != "summary" or review is None, "Summaries require separate approval.")
        require(
            kind != "memory" or review is None, "Entity observations require separate approval."
        )
        if kind == "memory":
            require(
                effort == "low" and "luna" in model.lower(),
                "Entity analysis uses Luna Low; no automatic model substitution.",
            )
        if kind == "quality_review":
            review = policy(review or {"model": model, "effort": effort, "max_passes": 2})
            model, effort = review["model"], review["effort"]
        self.source(series_id, source, number)
        with self.pair(series_id, source, target) as project:
            packet = project.packet(number)
            require_readable(packet)
            chapter = project.chapter(number)
            options = {
                "review": review,
                "expected_hash": chapter["translation_hash"],
                "packet_hash": packet["packet_hash"],
            }
            options["limits"] = limits(limits_config)
            if kind == "quality_review":
                require(chapter["translation"], "Translate the chapter before reviewing it.")
            if kind == "summary":
                require(
                    chapter["state"] == "approved",
                    "Review and approve the translation before creating its summary.",
                )
            if kind == "memory":
                from story_memory import analysis_context

                _, options["memory_key"] = analysis_context(self, series_id, source, target, number)
                require(
                    not self.db.execute(
                        "SELECT 1 FROM memory_scans WHERE key=?", (options["memory_key"],)
                    ).fetchone(),
                    "Chapter already analysed; no additional call is needed.",
                )
        require(
            isinstance(model, str) and model and isinstance(effort, str) and effort,
            "Model and reasoning effort are required.",
        )
        job = uuid.uuid4().hex
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            require(
                not self.db.execute(
                    "SELECT 1 FROM jobs WHERE series=? AND source=? AND target=? AND number=? "
                    "AND state IN ('queued','running')",
                    (series_id, source, target, number),
                ).fetchone(),
                "This chapter already has an active job.",
            )
            require(
                run_id
                or not self.db.execute(
                    "SELECT 1 FROM bulk_runs r JOIN bulk_items i ON i.run=r.id WHERE r.series=? AND r.source=? AND r.target=? AND i.number=? AND i.state!='done' AND r.state IN ('queued','running','pause_requested','paused')",
                    (series_id, source, target, number),
                ).fetchone(),
                "This chapter already belongs to a batch run; resume or cancel that run.",
            )
            self.db.execute(
                "INSERT INTO jobs(id,series,source,target,number,kind,model,effort,state,options,run_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job,
                    series_id,
                    source,
                    target,
                    number,
                    kind,
                    model,
                    effort,
                    "queued",
                    encode(options),
                    run_id,
                ),
            )
            if run_id:
                self.db.execute(
                    "UPDATE bulk_items SET state='running',job=?,error=NULL WHERE run=? AND position=?",
                    (job, run_id, position),
                )
        return job

    def run_job(self, job, bridge):
        from job_tracking import JobStopped, check, invoke, limits, now, progress

        row = dict(self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())
        with self.db:
            self.db.execute("UPDATE jobs SET state='running',started_at=? WHERE id=?", (now(), job))
        generated = None
        options = json.loads(row["options"] or "{}")

        def checkpoint(result):
            with self.db:
                self.db.execute(
                    "UPDATE jobs SET result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (encode(result), job),
                )

        try:
            check(self, row, limits(options.get("limits")))
            progress(self, job, phase="preparing")
            if row["kind"] == "memory":
                from story_memory import run

                generated = run(self, row, bridge)
                with self.db:
                    self.db.execute(
                        "UPDATE jobs SET state='draft',result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (encode(generated), job),
                    )
                return
            with self.pair(row["series"], row["source"], row["target"]) as project:
                require(
                    not options.get("packet_hash")
                    or options["packet_hash"] == project.packet(row["number"])["packet_hash"],
                    "Context changed after queuing; explicitly restart the job.",
                )
                require(
                    "expected_hash" not in options
                    or options["expected_hash"]
                    == project.chapter(row["number"])["translation_hash"],
                    "Translation changed after queuing; explicitly restart the job.",
                )
                if row["kind"] in ("translation", "quality_review"):
                    prepared = project.prepare(row["number"])
                else:
                    prepared = project.prepare_summary(row["number"])
                folder = Path(prepared["folder"])
                context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
                require_readable(context)
                template = json.loads(
                    (folder / "response.template.json").read_text(encoding="utf-8")
                )
                instructions = (folder / "INSTRUCTIONS.txt").read_text(encoding="utf-8")
                if row["kind"] == "translation":
                    from batches import batch_prompt, split_segments

                    batches = split_segments(context["segments"])
                    translated, records, usage, editorial_notes = [], [], {}, []
                    for index, batch in enumerate(batches, 1):
                        check(self, row, limits(options.get("limits")))
                        require(
                            "expected_hash" not in options
                            or options["expected_hash"]
                            == project.chapter(row["number"])["translation_hash"],
                            "Translation changed; stopping before the next batch.",
                        )
                        require(
                            project.packet(row["number"])["packet_hash"] == context["packet_hash"],
                            "Context changed; stopping before the next batch.",
                        )
                        prompt, local_context = batch_prompt(
                            context, template, instructions, batch, index, len(batches), translated
                        )
                        key = digest(prompt)
                        cached = self.db.execute(
                            "SELECT b.result FROM translation_batches b JOIN jobs j ON j.id=b.job "
                            "WHERE prompt_hash=? AND b.model=? AND b.effort=? AND j.state IN ('failed','interrupted')",
                            (key, row["model"], row["effort"]),
                        ).fetchone()
                        result = (
                            json.loads(cached["result"])
                            if cached
                            else invoke(
                                self,
                                row,
                                bridge,
                                prompt,
                                response_schema("translation", local_context),
                                row["model"],
                                row["effort"],
                                folder,
                                phase="translation",
                                batch=index,
                                total=len(batches),
                                start=len(translated) + 1,
                                end=len(translated) + len(batch),
                                completed=len(translated),
                                paragraphs=len(context["segments"]),
                            )
                        )
                        if not cached:
                            for name, count in (
                                (result.get("token_usage") or {}).get("last", {}).items()
                            ):
                                if type(count) is int:
                                    usage[name] = usage.get(name, 0) + count
                        try:
                            normalized, _ = project.validate_translation(
                                local_context, result["response"]
                            )
                        except ValueError as error:
                            generated = {
                                "response": {**template, "segments": translated},
                                "model": row["model"],
                                "effort": row["effort"],
                                "batches": records,
                                "batch_total": len(batches),
                                "token_usage": {"last": usage} if usage else None,
                                "failed_batch": {
                                    "index": index,
                                    "result": result,
                                    "expected_ids": [segment["id"] for segment in batch],
                                },
                            }
                            raise ValueError(f"Batch {index}/{len(batches)}: {error}") from error
                        with self.db:
                            self.db.execute(
                                "INSERT OR REPLACE INTO translation_batches VALUES(?,?,?,?,?)",
                                (key, row["model"], row["effort"], encode(result), job),
                            )
                        translated.extend(normalized)
                        editorial_notes.extend(result["response"].get("editorial_notes", []))
                        progress(
                            self,
                            job,
                            phase="translation",
                            batch=index,
                            batch_total=len(batches),
                            paragraphs_done=len(translated),
                            paragraphs_total=len(context["segments"]),
                            activity="cached" if cached else "validated",
                        )
                        records.append(
                            {
                                "index": index,
                                "cached": bool(cached),
                                "segments": len(batch),
                                "token_usage": result.get("token_usage"),
                            }
                        )
                        generated = {
                            "response": {
                                **template,
                                "segments": translated,
                                "editorial_notes": editorial_notes,
                            },
                            "model": row["model"],
                            "effort": row["effort"],
                            "batches": records,
                            "batch_total": len(batches),
                            "token_usage": {"last": usage} if usage else None,
                        }
                        with self.db:
                            self.db.execute(
                                "UPDATE jobs SET result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (encode(generated), job),
                            )
                elif row["kind"] == "quality_review":
                    require(
                        project.chapter(row["number"])["translation_hash"]
                        == options["expected_hash"],
                        "Translation changed after queuing.",
                    )
                    generated = {
                        "response": {
                            **template,
                            "segments": json.loads(project.chapter(row["number"])["translation"]),
                        },
                        "model": row["model"],
                        "effort": row["effort"],
                    }
                else:
                    prompt, local_context = summary_prompt(
                        context,
                        template,
                        instructions,
                        row["target"],
                        project.packet(row["number"])["glossary"],
                    )
                    require(len(prompt) <= 120000, "Summary context is too large.")
                    generated = invoke(
                        self,
                        row,
                        bridge,
                        prompt,
                        response_schema(row["kind"], local_context),
                        row["model"],
                        row["effort"],
                        folder,
                        phase="summary",
                        paragraphs=len(context["source_segments"]),
                    )
            # Fresh reads after generation detect glossary changes made while the job ran.
            with self.pair(row["series"], row["source"], row["target"]) as project:
                saved = (
                    project.summary(row["number"], generated["response"])
                    if row["kind"] == "summary"
                    else project.submit(
                        row["number"],
                        generated["response"],
                        expected_hash=options.get("expected_hash", Ellipsis),
                    )
                )
            generated["saved"] = saved
            if options.get("review"):
                from quality_review import run

                checkpoint(generated)
                generated = run(self, row, bridge, context, generated, checkpoint)
            with self.db:
                self.db.execute(
                    "UPDATE jobs SET state='draft',result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (encode(generated), job),
                )
        except Exception as error:
            with self.db:
                self.db.execute(
                    "UPDATE jobs SET state=?,error=?,result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        "draft"
                        if generated and generated.get("saved")
                        else "interrupted"
                        if isinstance(error, JobStopped)
                        else "failed",
                        str(error),
                        encode(generated) if generated else None,
                        job,
                    ),
                )
        finally:
            with self.db:
                self.db.execute("UPDATE jobs SET finished_at=? WHERE id=?", (now(), job))


def summary_prompt(context, template, instructions, target, glossary):
    # Keep the full bilingual review packet on disk, but send each source once.
    compact = {
        key: context[key] for key in ("chapter", "title", "translation_hash", "source_segments")
    }
    compact["glossary"] = glossary
    if context.get("story_memory"):
        compact["story_memory"] = context["story_memory"]
    prompt = (
        instructions
        + "\nUse the source text for facts and the glossary for target-language names. "
        "story_memory is reviewed earlier context, not evidence of new events. Cite only current source_segments IDs. "
        "Write 250–450 words. Cite source segment IDs beside each main factual claim and "
        "list those same IDs in evidence. Do not infer romantic relationships or motives "
        "beyond what this chapter establishes.\nTarget language: "
        + target
        + "\nContext: "
        + encode(compact)
        + "\nResponse template: "
        + encode(template)
    )
    return prompt, compact


def response_schema(kind, context=None):
    properties = {"chapter": {"type": "integer"}}
    if kind == "translation":
        properties.update(
            source_hash={"type": "string"},
            packet_hash={"type": "string"},
            segments={
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["id", "text"],
                },
            },
        )
        from translation_prompt import note_schema

        properties["editorial_notes"] = note_schema(
            [s["id"] for s in context["segments"]] if context else None
        )
        properties["blocked_reason"] = {"type": "string"}
        if context is not None:
            # Constrain copying at generation time; Python still checks order and completeness.
            properties["chapter"]["enum"] = [context["chapter"]]
            properties["source_hash"]["enum"] = [context["source_hash"]]
            properties["packet_hash"]["enum"] = [context["packet_hash"]]
            properties["segments"]["items"]["properties"]["id"]["enum"] = [
                s["id"] for s in context["segments"]
            ]
    else:
        properties.update(
            translation_hash={"type": "string"},
            text={"type": "string"},
            evidence={"type": "array", "items": {"type": "string"}},
        )
        if context is not None:
            properties["chapter"]["enum"] = [context["chapter"]]
            properties["translation_hash"]["enum"] = [context["translation_hash"]]
            properties["evidence"]["items"]["enum"] = [s["id"] for s in context["source_segments"]]
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
