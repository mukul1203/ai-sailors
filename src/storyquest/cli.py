"""The `storyquest` command."""

import argparse
import dataclasses
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from storyquest import __version__
from storyquest.agent.context import AgentError, load_context
from storyquest.agent.modes import get_mode
from storyquest.agent.render import render_turn
from storyquest.agent.turn import run_turn
from storyquest.catalog.importer import CatalogError, import_books
from storyquest.config import Settings, load_settings
from storyquest.domain.position import Position
from storyquest.evaluation.html_report import render_html
from storyquest.evaluation.items import GoldItem, load_items
from storyquest.evaluation.report import compare, summarize
from storyquest.evaluation.runner import (
    judge_rows,
    load_run,
    make_config,
    run_eval,
    save_run,
    write_run,
)
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.inspect import render_book, render_hits
from storyquest.ingestion.pipeline import load_cleaned, run_deterministic
from storyquest.models.build import build_llm
from storyquest.models.llm import LLMError, Message
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.db import connect, migrate, migrations_dir
from storyquest.stores.search import search_chunks


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
    hits = search_chunks(conn, args.book, args.query, position, limit=args.limit)
    print(f"Child at chapter {position.chapter_idx}, beat B{position.beat_idx + 1}")
    print(render_hits(load_cleaned(settings.data_dir, book), hits))
    return 0


def _ask(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    try:
        llm = build_llm(settings, use_cache=not args.no_cache)
        ctx = load_context(conn, llm, settings, args.book)
        mode = get_mode(args.mode)
    except (LLMError, AgentError, ValueError) as e:
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
        llm = build_llm(settings, use_cache=not args.no_cache)
        ctx = load_context(conn, llm, settings, args.book)
        mode = get_mode(args.mode)
    except (LLMError, AgentError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rows = run_eval(ctx, items, mode, log=print)
    config = make_config(ctx, mode, args.split, golden, rows)
    if args.judge:
        rows = judge_rows(ctx, {i.id: i for i in items}, rows, log=print)
        config.update(judged=True, judge_model=settings.llm_model)
    summary = summarize(config, rows)
    run_dir = write_run(settings.root / "eval" / "runs", config, rows, summary)
    print("\n" + summary + f"\n\nSaved to {run_dir.relative_to(settings.root)}")
    return 0


def _eval_judge(args: argparse.Namespace) -> int:
    settings, conn = _open_content()
    run_dir = Path(args.run)
    config, rows = load_run(run_dir)
    golden = Path(config.get("golden_path") or settings.root / "eval" / "golden_v1.jsonl")
    items = {i.id: i for i in load_items(golden)}
    try:
        llm = build_llm(settings, use_cache=not args.no_cache)
        ctx = load_context(conn, llm, settings, config["book"])
    except (LLMError, AgentError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rows = judge_rows(ctx, items, rows, log=print)
    config.update(judged=True, judge_model=settings.llm_model)
    summary = summarize(config, rows)
    save_run(run_dir, config, rows, summary)
    print("\n" + summary)
    return 0


def _eval_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    config, rows = load_run(run_dir)
    baseline = load_run(Path(args.against)) if args.against else None
    page = run_dir / "report.html"
    page.write_text(render_html(config, rows, baseline))
    print(f"Wrote {page}")
    print(f"Open it in a browser, e.g. on macOS: open {page}")
    return 0


def _eval_compare(args: argparse.Namespace) -> int:
    print(compare(load_run(Path(args.run_a)), load_run(Path(args.run_b))))
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

    ask_agent = sub.add_parser("ask", help="Ask the story agent a question as a child")
    ask_agent.add_argument("book", type=int)
    ask_agent.add_argument("question")
    ask_agent.add_argument("--chapter", type=int, default=0, help="child's chapter (zero-based)")
    ask_agent.add_argument("--beat", type=int, default=0, help="child's beat (zero-based)")
    ask_agent.add_argument("--mode", default="M1", help="M0 plain model, M1 with retrieval")
    ask_agent.add_argument("--verbose", action="store_true", help="show the exact prompts")
    ask_agent.add_argument("--no-cache", action="store_true")

    ev = sub.add_parser("eval", help="Evaluate the agent on the golden set").add_subparsers(
        dest="eval_command", required=True
    )
    run = ev.add_parser("run", help="Run the golden set through the agent")
    run.add_argument("--mode", default="M1")
    run.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    run.add_argument("--category", help="only this category, e.g. SPO")
    run.add_argument("--ids", help="comma-separated item ids")
    run.add_argument("--limit", type=int, help="only the first N matching items")
    run.add_argument("--book", type=int, default=236)
    run.add_argument("--golden", help="path to a golden-set file")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument("--judge", action="store_true", help="also run the LLM judge")
    jdg = ev.add_parser("judge", help="Add LLM judge verdicts to a saved run")
    jdg.add_argument("run")
    jdg.add_argument("--no-cache", action="store_true")
    rep = ev.add_parser("report", help="Write report.html for a saved run")
    rep.add_argument("run")
    rep.add_argument("--against", help="another run to compare with")
    cmp = ev.add_parser("compare", help="Compare two saved runs")
    cmp.add_argument("run_a")
    cmp.add_argument("run_b")

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
    if args.command == "ask":
        return _ask(args)
    if args.command == "eval":
        return {
            "run": _eval_run,
            "judge": _eval_judge,
            "report": _eval_report,
            "compare": _eval_compare,
        }[args.eval_command](args)
    return 2
