"""Command line entry point: python -m dealbot <command>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from dealbot.collectors import build_collectors
from dealbot.collectors.manual import parse_items
from dealbot.config import Config, load_dotenv
from dealbot.db import Db, Repo
from dealbot.india import IST
from dealbot.pipeline import Pipeline
from dealbot.telegram import Telegram

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "sample_deals.json"


def _open(cfg: Config) -> Repo:
    repo = Repo(Db(cfg.database_url))
    repo.init()
    return repo


def cmd_run(cfg: Config) -> int:
    missing = [name for name, val in (("TELEGRAM_BOT_TOKEN", cfg.bot_token),
                                      ("TELEGRAM_CHANNEL_ID", cfg.channel_id)) if not val]
    if missing and not cfg.dry_run:
        print(f"Missing required settings: {', '.join(missing)}", file=sys.stderr)
        return 2
    collectors = build_collectors(cfg)
    if not collectors:
        print("No collectors configured (set FLIPKART_*, RSS_FEEDS or MANUAL_DEALS_FILE).",
              file=sys.stderr)
    tg = Telegram(cfg.bot_token, dry_run=cfg.dry_run)
    stats = Pipeline(cfg, _open(cfg), tg, collectors).run()
    print(json.dumps(stats))
    if cfg.dry_run:
        _print_outbox(tg)
    return 0


def cmd_init_db(cfg: Config) -> int:
    _open(cfg)
    print("Database ready.")
    return 0


def cmd_check(cfg: Config) -> int:
    rows = [
        ("Database", cfg.database_url.split("@")[-1] if cfg.database_url else "SQLite (dealbot.db)"),
        ("Telegram bot token", "set" if cfg.bot_token else "MISSING"),
        ("Channel", cfg.channel_id or "MISSING"),
        ("Review chat", cfg.review_chat_id or "MISSING (deals cannot be reviewed)"),
        ("Reviewers", ", ".join(map(str, cfg.reviewer_ids)) or "MISSING (nobody can approve)"),
        ("Amazon tag", cfg.amazon_tag or "not set (Amazon deals will be skipped)"),
        ("Flipkart affid/token", "set" if cfg.flipkart_affid and cfg.flipkart_token
         else "not set (Flipkart offers collector off)"),
        ("Network wrappers", ", ".join(cfg.wrap_templates) or "none"),
        ("RSS feeds", str(len(cfg.rss_feeds))),
        ("Manual deals file", cfg.manual_deals_file or "none"),
    ]
    for label, value in rows:
        print(f"{label:<22} {value}")
    return 0


def _print_outbox(tg: Telegram) -> None:
    for msg in tg.outbox:
        if msg["method"] in ("sendMessage", "sendPhoto"):
            body = msg.get("caption") or msg.get("text", "")
            target = msg["chat_id"]
            print(f"\n┌── {msg['method']} → {target}\n{body}")
            buttons = [b.get("text") for row in msg.get("reply_markup", {}).get("inline_keyboard", [])
                       for b in row]
            if buttons:
                print("   buttons: " + "  |  ".join(buttons))
            print("└──")


def cmd_demo(_: Config) -> int:
    """End-to-end dry run on a throwaway database with sample data. Needs no credentials."""
    now = int(datetime.now(IST).replace(hour=14, minute=0, second=0, microsecond=0).timestamp())
    cfg = Config(amazon_tag="demo-21", flipkart_affid="demoaff", channel_id="@demo_channel",
                 review_chat_id="1", reviewer_ids=[1], dry_run=True, lang="hi")
    repo = Repo(Db(":memory:"))
    repo.init()
    tg = Telegram("", dry_run=True, min_interval=0)

    items = json.loads(SAMPLE_FILE.read_text())
    for item in items:
        if "expires_in_hours" in item:
            item["expires_at"] = now + int(item["expires_in_hours"] * 3600)
    raws = parse_items(items, "demo")

    # Seed price history for items that declare one, spread over past days.
    for item, raw in zip(items, raws):
        hist = item.get("demo_history")
        if not hist:
            continue
        pid = repo.upsert_product(raw, now - hist["days"] * 86400)
        prices, days = hist["prices"], hist["days"]
        for i, price in enumerate(prices):
            ts = now - 25 * 3600 - int((len(prices) - 1 - i) * ((days * 86400 - 25 * 3600) / max(len(prices) - 1, 1)))
            repo.record_price(pid, price, raw.mrp, ts)

    class Fixed:
        name = "demo"

        def fetch(self) -> List:
            return raws

    pipe = Pipeline(cfg, repo, tg, [Fixed()], clock=lambda: now)
    print("Run 1: collect + queue for review", json.dumps(pipe.run()))
    pending = [m for m in tg.outbox if m["method"] in ("sendMessage", "sendPhoto")]
    print(f"\n{len(pending)} review card(s) sent to the private review chat.")

    # Simulate the reviewer tapping Approve on every card.
    tg.queued_updates = [
        {"update_id": 500 + i, "callback_query": {"id": f"cb{i}", "from": {"id": 1},
                                                  "data": m["reply_markup"]["inline_keyboard"][0][0]["callback_data"]}}
        for i, m in enumerate(pending)
    ]
    tg.outbox.clear()
    print("Run 2: reviewer approved everything ->", json.dumps(pipe.run()))
    print("\n===== What subscribers would see in the channel =====")
    _print_outbox(tg)
    return 0


COMMANDS = {"run": cmd_run, "init-db": cmd_init_db, "check": cmd_check, "demo": cmd_demo}


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="dealbot", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    return COMMANDS[args.command](Config.from_env())
