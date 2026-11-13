"""Catalog import: register books from folders of raw.txt plus book.yaml."""

import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from storyquest.domain.book import Book
from storyquest.stores.content_repo import ContentRepo


class CatalogError(Exception):
    pass


def import_book(repo: ContentRepo, data_dir: Path, folder: Path) -> Book:
    """Verify one book folder (raw.txt and book.yaml), copy its text under data_dir, and upsert
    its record. `sha256` in book.yaml is optional: if given, raw.txt must match it."""
    meta: dict[str, Any] = yaml.safe_load((folder / "book.yaml").read_text()) or {}
    raw = folder / "raw.txt"
    if not raw.is_file():
        raise CatalogError(f"{folder.name}: raw.txt is missing")
    missing = [k for k in ("gutenberg_id", "title", "author") if not meta.get(k)]
    if missing:
        raise CatalogError(f"{folder.name}: book.yaml needs {', '.join(missing)}")
    data = raw.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if meta.get("sha256") and sha != meta["sha256"]:
        raise CatalogError(f"{folder.name}: raw.txt does not match the sha256 in book.yaml")

    book_id = int(meta["gutenberg_id"])
    relative = f"books/{book_id}/raw.txt"
    dest = data_dir / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.read_bytes() != data:
        shutil.copyfile(raw, dest)

    book = Book(
        id=book_id,
        title=str(meta["title"]),
        author=str(meta["author"]),
        raw_path=relative,
        content_sha256=sha,
        language=str(meta.get("language", "en")),
        age_band=str(meta.get("age_band", "")),
        summary=str(meta.get("summary", "")),
        content_notes=str(meta.get("content_notes", "")),
        visibility=str(meta.get("visibility", "listed")),
    )
    repo.upsert_book(book)
    return book


def _folders(source: Path) -> list[Path]:
    return sorted(p for p in source.iterdir() if (p / "book.yaml").is_file())


def import_books(conn: sqlite3.Connection, data_dir: Path, source: Path) -> list[Book]:
    """Import every book folder in `source`; the first bad folder raises CatalogError."""
    repo = ContentRepo(conn)
    return [import_book(repo, data_dir, folder) for folder in _folders(source)]


def scan_books(
    conn: sqlite3.Connection, data_dir: Path, source: Path
) -> tuple[list[Book], list[str]]:
    """Like import_books, but a bad folder is reported and skipped, so one broken book does not
    hide the others. Returns (books imported, error messages)."""
    repo = ContentRepo(conn)
    books: list[Book] = []
    errors: list[str] = []
    if not source.is_dir():
        return books, errors
    for folder in _folders(source):
        try:
            books.append(import_book(repo, data_dir, folder))
        except (CatalogError, ValueError, OSError, yaml.YAMLError) as e:
            errors.append(f"{folder.name}: {e}")
    return books, errors
