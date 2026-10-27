from __future__ import annotations

from typing import List

from dealbot.collectors.base import Collector
from dealbot.collectors.flipkart import FlipkartOffersCollector
from dealbot.collectors.manual import ManualCollector
from dealbot.collectors.rss import RssCollector
from dealbot.config import Config

__all__ = ["Collector", "FlipkartOffersCollector", "ManualCollector", "RssCollector",
           "build_collectors"]


def build_collectors(cfg: Config) -> List[Collector]:
    """Instantiate every collector that has the credentials/config it needs."""
    collectors: List[Collector] = []
    if cfg.flipkart_affid and cfg.flipkart_token:
        collectors.append(FlipkartOffersCollector(cfg.flipkart_affid, cfg.flipkart_token))
    for feed in cfg.rss_feeds:
        collectors.append(RssCollector(feed))
    if cfg.manual_deals_file:
        collectors.append(ManualCollector(cfg.manual_deals_file))
    return collectors
