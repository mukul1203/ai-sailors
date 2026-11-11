import shutil
import sqlite3
from pathlib import Path

import pytest

from storyquest.catalog.importer import CatalogError, import_books
from storyquest.stores.content_repo import ContentRepo

pytestmark = pytest.mark.integration


def test_import_registers_the_book_and_copies_its_text(
    conn: sqlite3.Connection, tmp_path: Path, eval_dir: Path
) -> None:
    books = import_books(conn, tmp_path, eval_dir / "books")
    assert [b.id for b in books] == [236]
    book = ContentRepo(conn).get_book(236)
    assert book is not None
    assert (book.title, book.status, book.raw_path) == (
        "The Jungle Book",
        "allowlisted",
        "books/236/raw.txt",
    )
    assert (tmp_path / book.raw_path).is_file()


def test_reimport_is_idempotent_and_keeps_status(
    conn: sqlite3.Connection, tmp_path: Path, eval_dir: Path
) -> None:
    import_books(conn, tmp_path, eval_dir / "books")
    ContentRepo(conn).set_book_status(236, "ready")
    import_books(conn, tmp_path, eval_dir / "books")
    assert len(ContentRepo(conn).list_books()) == 1
    book = ContentRepo(conn).get_book(236)
    assert book is not None and book.status == "ready"


def copy_book(eval_dir: Path, tmp_path: Path) -> Path:
    source = tmp_path / "source"
    shutil.copytree(eval_dir / "books", source)
    return source


def test_a_text_that_does_not_match_its_hash_is_refused(
    conn: sqlite3.Connection, tmp_path: Path, eval_dir: Path
) -> None:
    source = copy_book(eval_dir, tmp_path)
    (source / "236-the-jungle-book" / "raw.txt").write_text("changed")
    with pytest.raises(CatalogError, match="sha256"):
        import_books(conn, tmp_path / "data", source)


def test_a_missing_text_file_is_refused(
    conn: sqlite3.Connection, tmp_path: Path, eval_dir: Path
) -> None:
    source = copy_book(eval_dir, tmp_path)
    (source / "236-the-jungle-book" / "raw.txt").unlink()
    with pytest.raises(CatalogError, match="missing"):
        import_books(conn, tmp_path / "data", source)
