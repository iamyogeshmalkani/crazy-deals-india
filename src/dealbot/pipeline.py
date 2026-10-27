"""One bot cycle: review callbacks -> collect -> publish -> expire.

Designed to be stateless between runs (state lives in the database) so it can be
driven by a GitHub Actions cron. Phase 1 flow: every candidate goes to a private
review chat first; only deals a reviewer approves reach the public channel.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from dealbot.collectors.base import Collector
from dealbot.composer import buy_label, compose
from dealbot.config import Config
from dealbot.db import (STATUS_APPROVED, STATUS_EXPIRED, STATUS_PENDING, STATUS_POSTED,
                        STATUS_REJECTED, Repo)
from dealbot.india import ist_day_start, is_quiet_hours
from dealbot.links import UntaggedLinkError, is_tagged, tag_url
from dealbot.models import RawDeal, Verdict
from dealbot.scorer import compute_stats, evaluate
from dealbot.telegram import Telegram, TelegramError

log = logging.getLogger("dealbot")

OFFSET_KEY = "tg_update_offset"


@dataclass
class Candidate:
    raw: RawDeal
    product_id: int
    link: str
    verdict: Verdict


class Pipeline:
    def __init__(self, cfg: Config, repo: Repo, tg: Telegram,
                 collectors: Sequence[Collector],
                 clock: Callable[[], int] = lambda: int(time.time())):
        self.cfg, self.repo, self.tg, self.collectors, self.clock = cfg, repo, tg, collectors, clock

    # --- full cycle --------------------------------------------------------

    def run(self) -> Dict[str, int]:
        stats: Dict[str, int] = {}
        stats["reviewed"] = self.process_review_callbacks()
        stats["stale"] = self.repo.mark_stale(self.clock() - self.cfg.review_ttl_hours * 3600)
        stats["queued"] = self.collect_and_enqueue()
        stats["posted"] = self.publish_approved()
        stats["expired"] = self.expire_posted()
        return stats

    # --- 1. reviewer decisions --------------------------------------------

    def process_review_callbacks(self) -> int:
        if not self.cfg.review_chat_id:
            return 0
        offset = int(self.repo.get_kv(OFFSET_KEY) or 0)
        handled = 0
        for update in self.tg.get_updates(offset):
            offset = max(offset, update["update_id"] + 1)
            query = update.get("callback_query")
            if not query:
                continue
            handled += self._handle_callback(query)
        self.repo.set_kv(OFFSET_KEY, str(offset))
        return handled

    def _handle_callback(self, query: Dict) -> int:
        cb_id, data = query["id"], query.get("data", "")
        if query["from"]["id"] not in self.cfg.reviewer_ids:
            self.tg.answer_callback(cb_id, "Not allowed")
            return 0
        action, _, raw_id = data.partition(":")
        if action not in ("ap", "rj") or not raw_id.isdigit():
            self.tg.answer_callback(cb_id, "")
            return 0
        deal = self.repo.get_deal(int(raw_id))
        if deal is None or deal["status"] != STATUS_PENDING:
            self.tg.answer_callback(cb_id, "Already handled")
            return 0

        approved = action == "ap"
        self.repo.update_deal(deal["id"], status=STATUS_APPROVED if approved else STATUS_REJECTED)
        self.tg.answer_callback(cb_id, "Approved ✅" if approved else "Rejected ❌")
        if deal["review_chat_msg_id"]:
            label = "✅ Approved" if approved else "❌ Rejected"
            self.tg.set_keyboard(self.cfg.review_chat_id, int(deal["review_chat_msg_id"]),
                                 [[{"text": label, "callback_data": "noop"}]])
        return 1

    # --- 2. collect, score, queue for review ------------------------------

    def gather(self) -> List[RawDeal]:
        seen, raws = set(), []
        for collector in self.collectors:
            try:
                fetched = collector.fetch()
            except Exception as exc:  # one broken source must not stop the run
                log.warning("collector %s failed: %s", getattr(collector, "name", collector), exc)
                continue
            for raw in fetched:
                key = (raw.store, raw.store_product_id)
                if key not in seen:
                    seen.add(key)
                    raws.append(raw)
        return raws

    def evaluate_all(self, raws: Sequence[RawDeal], now: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        for raw in raws:
            try:
                link = tag_url(raw.store, raw.url, self.cfg)
            except UntaggedLinkError as exc:
                log.info("skip %s: %s", raw.title[:40], exc)
                continue
            product_id = self.repo.upsert_product(raw, now)
            # Stats come from history *before* this observation so it can't vouch for itself.
            stats = compute_stats(self.repo.price_history(product_id, now), now)
            if raw.price:
                self.repo.record_price(product_id, raw.price, raw.mrp, now)
            if self.repo.has_open_deal(product_id):
                continue
            last_posted = self.repo.last_posted(product_id, now, self.cfg.repost_cooldown_days)
            verdict = evaluate(raw, stats, last_posted, self.cfg, now)
            if verdict.ok and verdict.score >= self.cfg.min_score:
                candidates.append(Candidate(raw, product_id, link, verdict))
        candidates.sort(key=lambda c: c.verdict.score, reverse=True)
        return candidates

    def collect_and_enqueue(self) -> int:
        now = self.clock()
        candidates = self.evaluate_all(self.gather(), now)
        queued = 0
        for cand in candidates[: self.cfg.max_review_cards_per_run]:
            composed = compose(cand.raw, cand.verdict, cand.link, self.cfg.lang, now)
            auto = cand.verdict.score >= self.cfg.auto_approve_score
            deal_id = self.repo.create_deal(
                cand.product_id, cand.raw,
                status=STATUS_APPROVED if auto else STATUS_PENDING,
                score=cand.verdict.score, verified=cand.verdict.verified, link=cand.link,
                channel_text=composed.channel_text, review_text=composed.review_text,
                expired_text=composed.expired_text, signals=cand.verdict.signals, now=now)
            if not auto:
                self._send_review_card(deal_id, composed.review_text, cand)
            queued += 1
        return queued

    def _send_review_card(self, deal_id: int, text: str, cand: Candidate) -> None:
        if not self.cfg.review_chat_id:
            log.warning("TELEGRAM_REVIEW_CHAT_ID not set; deal %s will wait unreviewed", deal_id)
            return
        keyboard = [
            [{"text": "✅ Approve", "callback_data": f"ap:{deal_id}"},
             {"text": "❌ Reject", "callback_data": f"rj:{deal_id}"}],
            [{"text": "🔗 Open link", "url": cand.link}],
        ]
        sent = self.tg.send(self.cfg.review_chat_id, text, cand.raw.image, keyboard)
        self.repo.update_deal(deal_id, review_chat_msg_id=sent.message_id,
                              review_msg_kind=sent.kind)

    # --- 3. publish approved deals ----------------------------------------

    def publish_approved(self) -> int:
        now = self.clock()
        if is_quiet_hours(now, self.cfg.quiet_start_hour, self.cfg.quiet_end_hour):
            return 0
        room_today = self.cfg.max_posts_per_day - self.repo.posted_count_since(ist_day_start(now))
        budget = min(self.cfg.max_posts_per_run, room_today)
        posted = 0
        for deal in self.repo.deals_by_status(STATUS_APPROVED):
            if posted >= budget:
                break
            if deal["expires_at"] and int(deal["expires_at"]) <= now:
                self.repo.update_deal(deal["id"], status=STATUS_EXPIRED)
                continue
            if not is_tagged(deal["link"], self.cfg):  # never publish an untagged link
                log.error("deal %s has an untagged link; not posting", deal["id"])
                self.repo.update_deal(deal["id"], status=STATUS_REJECTED)
                continue
            keyboard = [[{"text": buy_label(self.cfg.lang), "url": deal["link"]}]]
            try:
                sent = self.tg.send(self.cfg.channel_id, deal["channel_text"], deal["image"],
                                    keyboard)
            except TelegramError as exc:
                log.error("posting deal %s failed: %s", deal["id"], exc)
                continue
            self.repo.update_deal(deal["id"], status=STATUS_POSTED, posted_at=now,
                                  channel_msg_id=sent.message_id, channel_msg_kind=sent.kind)
            posted += 1
        return posted

    # --- 4. mark ended deals ----------------------------------------------

    def expire_posted(self) -> int:
        now = self.clock()
        ended = 0
        for deal in self.repo.deals_by_status(STATUS_POSTED):
            if not deal["expires_at"] or int(deal["expires_at"]) > now:
                continue
            try:
                self.tg.edit(self.cfg.channel_id, int(deal["channel_msg_id"]),
                             deal["channel_msg_kind"], deal["expired_text"])
            except TelegramError as exc:
                log.warning("could not edit expired deal %s: %s", deal["id"], exc)
            self.repo.update_deal(deal["id"], status=STATUS_EXPIRED)
            ended += 1
        return ended
