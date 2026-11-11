"""The `storyquest` command."""

import argparse
import dataclasses
import sys
from collections.abc import Sequence

from storyquest import __version__
from storyquest.config import load_settings
from storyquest.models.build import build_llm
from storyquest.models.llm import LLMError, Message
from storyquest.stores.db import connect, migrate, migrations_dir


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

    args = parser.parse_args(argv)
    if args.command == "config":
        return _show_config()
    if args.command == "llm":
        return _llm_ask(args)
    if args.command == "db":
        return _db_migrate()
    return 2
