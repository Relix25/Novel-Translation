# Reporting vulnerabilities

Use **Report a vulnerability** in the repository Security tab when available.
Do not disclose secrets or private text in public reports.

Libraries, originals, backups, logs and Codex sessions stay local. Codex owns
authentication; Novel uses no API key. Never publish a session volume, export
it into an image or add it to Git.

The local service checks host, origin and CSRF tokens. It is not designed for
direct Internet exposure or mutually untrusted users.

Run `python tools/check_public_files.py --history` before publication and inspect
the diff. The scanner identifies private paths and some credentials without
printing values; it cannot recognize every private passage placed in source code.

Protected main, read-only CI, dependency alerts, secret scanning, push protection
and private reporting are enabled. Main changes require a checked PR.
Editorial proposals never become approved glossary or memory automatically.
