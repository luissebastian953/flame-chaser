from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from ..models import DiscoverStats, IllustRecord, Watch
from ..seen import Seen


class Adapter(Protocol):
    name: str
    #: whether this source can answer "find posts of character X" at all
    supports_discovery: bool

    def discover(
        self,
        watch: Watch,
        since: str | None,
        seen: Seen | None = None,
        stats: DiscoverStats | None = None,
    ) -> Iterator[IllustRecord]: ...

    def fetch_media(self, url: str, referer: str | None) -> bytes: ...
