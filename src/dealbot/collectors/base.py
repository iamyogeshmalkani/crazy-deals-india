from __future__ import annotations

from typing import List, Protocol

from dealbot.models import RawDeal


class Collector(Protocol):
    """A deal source. `fetch` must not raise for a single bad item; the pipeline
    isolates whole-collector failures so one broken source never stops the run."""

    name: str

    def fetch(self) -> List[RawDeal]: ...
