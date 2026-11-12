"""The `storyquest` command."""

import argparse
import dataclasses
import re
import sqlite3
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from storyquest import __version__
from storyquest.agent.context import AgentError, load_context
from storyquest.agent.modes import Mode, get_mode
from storyquest.agent.render import render_turn
from storyquest.agent.turn import run_turn
from storyquest.catalog.importer import CatalogError, import_books
from storyquest.config import Settings, load_settings
from storyquest.domain.position import Position
from storyquest.evaluation.html_report import render_report
from storyquest.evaluation.items import GoldItem, load_items
from storyquest.evaluation.report import summarize
from storyquest.evaluation.runner import (
    judge_rows,
    load_batch,
    make_config,
    new_batch_dir,
    run_eval,
    write_run,
)
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.inspect import render_book, render_hits
from storyquest.ingestion.pipeline import load_cleaned, run_deterministic
from storyquest.models.build import build_embedder, build_llm
from storyquest.models.embedder import Embedder, EmbeddingError
from storyquest.models.llm import LLMError, Message
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.db import connect, migrate, migrations_dir
from storyquest.stores.search import hybrid_search, search_chunks
from storyquest.stores.vector import chunks_without_vectors, store_vectors


def _show_config() -> int:
    settings = load_settings()
    for f in dataclasses.fields(settings):
        if f.repr:
            print(f"{f.name} = {getattr(settings, f.name)}")
        else:
            print(f"{f.name} set: {bool(getattr(settings, f.name))}")
    return 0


def _llm_ask(args: argparse.Namespace) -> int:
    messages: list[Message] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})
    try:
        client = build_llm(load_settings(), use_cache=not args.no_cache)
        result = client.chat(messages, max_tokens=args.max_tokens, temperature=args.temperature)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(result.text)
    print(
        f"[{result.model} | {result.prompt_tokens}+{result.completion_tokens} tokens | "
        f"{result.latency_s:.1f}s | cached={result.cached} | finish={result.finish_reason}]",
        file=sys.stderr,
    )
    return 0


def _db_migrate() -> int:
    settings = load_settings()
    conn = connect(settings.data_dir / "content.db")
    applied = migrate(conn, migrations_dir("content"))
    print(f"content.db: applied {applied}" if applied else "content.db: up to date")
    return 0


def _open_content() -> tuple[Settings, sqlite3.Connection]:
    settings = load_settings()
    conn = connect(settings.data_dir / "content.db")
    migrate(conn, migrations_dir("content"))
    return settings, conn


def _catalog_import(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    books = import_books(conn, settings.data_dir, Path(args.source))
    for b in books:
        print(f"imported {b.id}: {b.title} ({b.author})")
    return 0


def _ingest(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    spine = Path(args.spine) if args.spine else None
    run_deterministic(conn, settings, args.book, spine_path=spine, log=print)
    return 0


def _inspect(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    print(render_book(conn, settings.data_dir, args.book, args.chapter))
    return 0


def _search(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    book = ContentRepo(conn).get_book(args.book)
    if book is None:
        raise IngestionError(f"Book {args.book} is not in the catalog")
    position = Position(args.chapter, args.beat)
    if args.hybrid:
        try:
            embedder = build_embedder(settings, use_cache=not args.no_cache)
            vector = embedder.embed([args.query], query=True)[0]
        except EmbeddingError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        hits = hybrid_search(
            conn,
            args.book,
            args.query,
            vector,
            embedder.model_id,
            position,
            limit=args.limit,
            candidates=settings.retrieval_candidates,
            rrf_k=settings.rrf_k,
        )
    else:
        hits = search_chunks(conn, args.book, args.query, position, limit=args.limit)
    print(f"Child at chapter {position.chapter_idx}, beat B{position.beat_idx + 1}")
    print(render_hits(load_cleaned(settings.data_dir, book), hits))
    return 0


def _embedder_for(settings: Settings, modes: list[Mode], *, no_cache: bool) -> Embedder | None:
    """An embedder only when a selected mode searches by meaning."""
    if not any(m.hybrid for m in modes):
        return None
    return build_embedder(settings, use_cache=not no_cache)


def _embed(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    try:
        embedder = build_embedder(settings, use_cache=not args.no_cache)
        todo = chunks_without_vectors(conn, args.book, embedder.model_id)
        if not todo:
            print(f"Book {args.book}: every chunk already has a {embedder.model_id} vector")
            return 0
        vectors = embedder.embed([text for _, text in todo], query=False)
    except EmbeddingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    store_vectors(
        conn,
        embedder.model_id,
        embedder.dim,
        [(cid, v) for (cid, _), v in zip(todo, vectors, strict=True)],
    )
    print(f"Book {args.book}: embedded {len(todo)} chunks with {embedder.model_id}")
    return 0


def _ask(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    try:
        llm = build_llm(settings, use_cache=not args.no_cache)
        mode = get_mode(args.mode)
        embedder = _embedder_for(settings, [mode], no_cache=args.no_cache)
        ctx = load_context(conn, llm, settings, args.book, embedder)
    except (LLMError, AgentError, EmbeddingError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    position = Position(args.chapter, args.beat)
    result = run_turn(ctx, args.question, position, mode=mode)
    print(render_turn(ctx, position, args.question, result, verbose=args.verbose))
    return 0


def _select_items(args: argparse.Namespace, items: list[GoldItem]) -> list[GoldItem]:
    if args.split != "all":
        items = [i for i in items if i.split == args.split]
    if args.category:
        items = [i for i in items if i.category == args.category.upper()]
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i.id in wanted]
    return items[: args.limit] if args.limit else items


def _parse_modes(text: str) -> list[Mode]:
    names = dict.fromkeys(n.upper() for n in re.split(r"[,\s]+", text) if n)
    return [get_mode(n) for n in names]


def _publish(page: Path, html: str, *, open_it: bool) -> None:
    page.write_text(html)
    print(f"\nReport: {page}")
    if open_it:
        webbrowser.open(page.resolve().as_uri())


def _eval_run(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    golden = Path(args.golden) if args.golden else settings.root / "eval" / "golden_v1.jsonl"
    items = _select_items(args, load_items(golden))
    if not items:
        print("error: no items match those filters", file=sys.stderr)
        return 1
    if args.split in ("test", "all"):
        print("note: the test split is for reporting; do not tune against it")
    try:
        modes = _parse_modes(args.modes)
        llm = build_llm(settings, use_cache=not args.no_cache)
        embedder = _embedder_for(settings, modes, no_cache=args.no_cache)
        ctx = load_context(conn, llm, settings, args.book, embedder)
    except (LLMError, AgentError, EmbeddingError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    batch = new_batch_dir(settings.root / "eval" / "runs")
    runs = []
    for mode in modes:
        print(f"\n=== Mode {mode.name}: {mode.title} ===")
        rows = run_eval(ctx, items, mode, log=print)
        config = make_config(ctx, mode, args.split, golden, rows)
        if not args.no_judge:
            rows = judge_rows(ctx, {i.id: i for i in items}, rows, log=print)
            config.update(judged=True, judge_model=settings.llm_model)
        summary = summarize(config, rows)
        write_run(batch, config, rows, summary)
        print("\n" + summary)
        runs.append((config, rows))
    _publish(batch / "report.html", render_report(runs), open_it=not args.no_open)
    return 0


def _eval_report(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    try:
        runs = load_batch(folder)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _publish(folder / "report.html", render_report(runs), open_it=not args.no_open)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storyquest")
    parser.add_argument("--version", action="version", version=f"storyquest {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="Show the effective settings (secrets are not printed)")

    llm = sub.add_parser("llm", help="Talk to the configured model").add_subparsers(
        dest="llm_command", required=True
    )
    ask = llm.add_parser("ask", help="Send one prompt")
    ask.add_argument("prompt")
    ask.add_argument("--system", default="")
    ask.add_argument("--max-tokens", type=int, default=256)
    ask.add_argument("--temperature", type=float, default=0.0)
    ask.add_argument("--no-cache", action="store_true")

    db = sub.add_parser("db", help="Database tasks").add_subparsers(
        dest="db_command", required=True
    )
    db.add_parser("migrate", help="Create or upgrade the databases")

    catalog = sub.add_parser("catalog", help="Book catalog").add_subparsers(
        dest="catalog_command", required=True
    )
    imp = catalog.add_parser("import", help="Register books from a folder of book folders")
    imp.add_argument("source")

    ing = sub.add_parser("ingest", help="Run the deterministic ingestion stages for a book")
    ing.add_argument("book", type=int)
    ing.add_argument("--spine", help="Hand-written spine JSON to load as beats")

    insp = sub.add_parser("inspect", help="Show chapters, beats and chunks for a book")
    insp.add_argument("book", type=int)
    insp.add_argument("--chapter", type=int)

    srch = sub.add_parser("search", help="Search a book's chunks as a child at a position")
    srch.add_argument("book", type=int)
    srch.add_argument("query")
    srch.add_argument("--chapter", type=int, default=999, help="child's chapter (default: all)")
    srch.add_argument("--beat", type=int, default=999, help="child's beat, zero-based")
    srch.add_argument("--limit", type=int, default=5)
    srch.add_argument("--hybrid", action="store_true", help="keywords plus meaning (embeddings)")
    srch.add_argument("--no-cache", action="store_true")

    emb = sub.add_parser("embed", help="Compute embedding vectors for a book's chunks")
    emb.add_argument("book", type=int)
    emb.add_argument("--no-cache", action="store_true")

    ask_agent = sub.add_parser("ask", help="Ask the story agent a question as a child")
    ask_agent.add_argument("book", type=int)
    ask_agent.add_argument("question")
    ask_agent.add_argument("--chapter", type=int, default=0, help="child's chapter (zero-based)")
    ask_agent.add_argument("--beat", type=int, default=0, help="child's beat (zero-based)")
    ask_agent.add_argument(
        "--mode",
        default="M1",
        help="M0 plain, M1 retrieval, M1S +evidence sentences, M2 hybrid, M2S hybrid +evidence",
    )
    ask_agent.add_argument("--verbose", action="store_true", help="show the exact prompts")
    ask_agent.add_argument("--no-cache", action="store_true")

    ev = sub.add_parser("eval", help="Evaluate the agent on the golden set").add_subparsers(
        dest="eval_command", required=True
    )
    run = ev.add_parser("run", help="Run the golden set, judge it, write one report and open it")
    run.add_argument("--modes", default="M1", help="modes to compare, e.g. 'M0 M1 M1S'")
    run.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    run.add_argument("--category", help="only this category, e.g. SPO")
    run.add_argument("--ids", help="comma-separated item ids")
    run.add_argument("--limit", type=int, help="only the first N matching items")
    run.add_argument("--book", type=int, default=236)
    run.add_argument("--golden", help="path to a golden-set file")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument("--no-judge", action="store_true", help="skip the LLM judge (faster)")
    run.add_argument("--no-open", action="store_true", help="do not open the report")
    rep = ev.add_parser("report", help="Rebuild and open the report for a saved run folder")
    rep.add_argument("folder")
    rep.add_argument("--no-open", action="store_true")

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (IngestionError, CatalogError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "config":
        return _show_config()
    if args.command == "llm":
        return _llm_ask(args)
    if args.command == "db":
        return _db_migrate()
    if args.command == "catalog":
        return _catalog_import(args)
    if args.command == "ingest":
        return _ingest(args)
    if args.command == "inspect":
        return _inspect(args)
    if args.command == "search":
        return _search(args)
    if args.command == "embed":
        return _embed(args)
    if args.command == "ask":
        return _ask(args)
    if args.command == "eval":
        return {"run": _eval_run, "report": _eval_report}[args.eval_command](args)
    return 2
