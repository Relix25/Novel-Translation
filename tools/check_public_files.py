"""Reject private artifacts and obvious credentials in the Git index or history.

Print only filenames and finding categories, never matched credential values.
"""

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def git(*args, input=None):
    return subprocess.check_output(
        ["git", "-c", "safe.directory=" + ROOT.as_posix(), "-c", "core.excludesFile=", *args],
        cwd=ROOT,
        input=input,
    )


def findings(name, content):
    path = PurePosixPath(name)
    forbidden = {
        "appdata",
        "docker-data",
        "backups",
        "imports",
        ".codex",
        "node_modules",
        ".npm-cache",
        "dist",
        "demo",
        ".venv",
        "__pycache__",
        ".playwright-cli",
        "playwright",
    }
    if (
        any(part in forbidden or part.startswith("local-") for part in path.parts)
        and name != "imports/.gitkeep"
        or path.name == "auth.json"
        or path.name.startswith(".env")
        and path.name != ".env.example"
        or path.name.startswith("verification-")
        or path.suffix.lower()
        in {".sqlite", ".sqlite3", ".db", ".epub", ".zip", ".png", ".jpg", ".jpeg", ".log"}
        or path.name.endswith(("-wal", "-shm", "-journal"))
    ):
        yield "private artifact"
    patterns = {
        "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "GitHub token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b",
        "OpenAI key": rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b",
        "JWT credential": rb"\beyJ[A-Za-z0-9_-]{25,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b",
        "personal Windows path": rb"C:[/\\]+Users[/\\]+(?!Public\b|Default\b|example\b)[A-Za-z0-9_-]+[/\\]",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, content, re.IGNORECASE):
            yield label


def blobs(shas):
    """Read each unique object once through Git's binary-safe batch protocol."""
    requested = sorted(set(shas))
    if not requested:
        return {}
    stream = io.BytesIO(git("cat-file", "--batch", input=("\n".join(requested) + "\n").encode()))
    found = {}
    for expected in requested:
        header = stream.readline().decode("ascii").strip().split()
        if len(header) != 3 or header[0] != expected:
            raise ValueError("Git object audit could not read an expected object.")
        sha, kind, size = header
        content = stream.read(int(size))
        if len(content) != int(size) or stream.read(1) != b"\n":
            raise ValueError("Git object audit returned incomplete content.")
        if kind == "blob":
            found[sha] = content
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument(
        "--worktree", action="store_true", help="Also inspect publishable unstaged files."
    )
    args = parser.parse_args()
    entries = []
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            mode, sha, _ = metadata.decode().split()
            entries.append((name.decode("utf-8"), sha, mode))
    if args.history:
        for line in git("rev-list", "--objects", "--all").splitlines():
            sha, _, name = line.partition(b" ")
            if name:
                entries.append((name.decode("utf-8"), sha.decode(), "100644"))
    failures = set()
    contents = blobs(sha for _, sha, _ in entries)
    for name, sha, mode in entries:
        if mode == "120000":
            failures.add((name, "symlink"))
        if sha not in contents:
            continue
        for label in findings(name, contents[sha]):
            failures.add((name, label))
    if args.worktree:
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
        for raw in set(names) - {b""}:
            name = raw.decode("utf-8")
            path = ROOT / name
            if path.is_symlink():
                failures.add((name, "symlink"))
            elif path.is_file():
                for label in findings(name, path.read_bytes()):
                    failures.add((name, label))
    for name, label in sorted(failures):
        print(f"{name}: {label}")
    if failures:
        return 1
    print(f"Public file audit passed ({len(entries)} indexed/history entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
