"""The visited gate. Offline: fake pixiv responses, real SQLite."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from test_smoke import fake_pixiv

from coreflame.db import Store
from coreflame.models import DiscoverStats, Watch
from coreflame.seen import Seen, SeenState, SkipReason
from coreflame.sources.pixiv import PixivAdapter


def _adapter_with_404(gone_id: str) -> PixivAdapter:
    a = fake_pixiv()
    inner = a.client.get_json

    def get_json(url, **kw):
        if f"/ajax/illust/{gone_id}?" in url:
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "404", request=req, response=httpx.Response(404, request=req)
            )
        return inner(url, **kw)

    a.client.get_json = get_json  # type: ignore[assignment]
    a.calls = 0
    return a


def test_gate_states(tmp: Path) -> None:
    seen = Seen(Store(tmp / "s.db").conn)
    assert seen.should_fetch("pixiv", "1")  # unknown
    seen.mark("pixiv", "1", SeenState.INDEXED)
    assert not seen.should_fetch("pixiv", "1")  # indexed: never
    seen.mark("pixiv", "2", SeenState.GONE, reason="http_404")
    assert not seen.should_fetch("pixiv", "2")  # gone: never
    seen.mark(
        "pixiv", "3", SeenState.SKIPPED, reason=SkipReason.BELOW_MIN_BOOKMARKS.value, threshold=500
    )
    assert not seen.should_fetch("pixiv", "3")  # skipped: not now
    ra = seen.mark_failed("pixiv", "4", "ReadTimeout")
    assert not seen.should_fetch("pixiv", "4")  # failed: backoff
    assert datetime.fromisoformat(ra) > datetime.now(timezone.utc)
    print("  four states gate:     ok")

    # failed escalates, and a later success clears the failure count
    seen.mark_failed("pixiv", "4", "ReadTimeout")
    assert seen.get("pixiv", "4").failures == 2
    seen.mark("pixiv", "4", SeenState.INDEXED)
    assert seen.get("pixiv", "4").failures == 0
    print("  backoff escalates:    ok (2 failures -> cleared on success)")


def test_threshold_invalidation(tmp: Path) -> None:
    seen = Seen(Store(tmp / "t.db").conn)
    seen.mark(
        "pixiv", "a", SeenState.SKIPPED, reason=SkipReason.BELOW_MIN_BOOKMARKS.value, threshold=500
    )
    seen.mark(
        "pixiv", "b", SeenState.SKIPPED, reason=SkipReason.BELOW_MIN_BOOKMARKS.value, threshold=100
    )
    seen.mark("pixiv", "c", SeenState.SKIPPED, reason=SkipReason.UGOIRA.value)
    # raising the threshold reopens nothing
    assert seen.reopen_skipped("pixiv", SkipReason.BELOW_MIN_BOOKMARKS, 800) == 0
    # lowering to 200 reopens only the one skipped at 500
    assert seen.reopen_skipped("pixiv", SkipReason.BELOW_MIN_BOOKMARKS, 200) == 1
    assert seen.should_fetch("pixiv", "a") and not seen.should_fetch("pixiv", "b")
    assert not seen.should_fetch("pixiv", "c")  # ugoira untouched
    print("  threshold reopen:     ok (500 reopened at 200; 100 and ugoira kept)")


def test_gate_prevents_detail_requests(tmp: Path) -> None:
    store = Store(tmp / "g.db")
    a = fake_pixiv()
    inner = a.client.get_json
    detail_calls = []

    def counting(url, **kw):
        if "/ajax/illust/" in url and not url.endswith("/pages?lang=en"):
            detail_calls.append(url)
        return inner(url, **kw)

    a.client.get_json = counting  # type: ignore[assignment]

    w = Watch(slug="ganyu", pixiv_tags=["甘雨"])
    ds = DiscoverStats()
    recs = list(a.discover(w, None, seen=store.seen, stats=ds))
    for r in recs:
        store.seen.mark("pixiv", r.external_id, SeenState.INDEXED)
    first = len(detail_calls)
    assert first == 2 and ds.listed == 2 and ds.gated == 0

    # second tag returning the same ids: zero detail requests
    ds2 = DiscoverStats()
    recs2 = list(
        a.discover(Watch(slug="ganyu", pixiv_tags=["甘雨(原神)"]), None, seen=store.seen, stats=ds2)
    )
    assert recs2 == [] and len(detail_calls) == first
    assert ds2.gated == 2 and ds2.highest_id == 1002
    print(
        f"  cross-tag gate:       ok ({first} detail requests, then 0; "
        f"watermark still advanced to {ds2.highest_id})"
    )


def test_404_marked_gone_once(tmp: Path) -> None:
    store = Store(tmp / "n.db")
    a = _adapter_with_404("1001")
    w = Watch(slug="ganyu", pixiv_tags=["甘雨"])
    ds = DiscoverStats()
    recs = list(a.discover(w, None, seen=store.seen, stats=ds))
    assert [r.external_id for r in recs] == ["1002"]
    assert ds.gone == 1
    row = store.seen.get("pixiv", "1001")
    assert row and row.state is SeenState.GONE and row.reason == "http_404"
    # next poll: 1001 is gated, not re-fetched
    ds2 = DiscoverStats()
    list(a.discover(w, None, seen=store.seen, stats=ds2))
    assert ds2.gone == 0 and ds2.gated >= 1
    print("  404 -> gone, once:    ok (not refetched on the next poll)")


def test_min_bookmarks_skip_recorded(tmp: Path) -> None:
    store = Store(tmp / "m.db")
    a = fake_pixiv()
    w = Watch(slug="ganyu", pixiv_tags=["甘雨"], min_bookmarks=500)
    ds = DiscoverStats()
    recs = list(a.discover(w, None, seen=store.seen, stats=ds))
    assert [r.external_id for r in recs] == ["1002"] and ds.skipped == 1
    row = store.seen.get("pixiv", "1001")
    assert row.state is SeenState.SKIPPED and row.threshold == 500
    # user lowers the bar on save -> reopened, and the next poll fetches it
    store.upsert_watch(w)  # first save
    w2 = Watch(slug="ganyu", pixiv_tags=["甘雨"], min_bookmarks=5)
    assert store.upsert_watch(w2) == 1
    assert store.seen.should_fetch("pixiv", "1001")
    print("  skip stores threshold: ok (lowering 500 -> 5 reopened 1)")


def test_gone_propagates_to_posts(tmp: Path) -> None:
    store = Store(tmp / "p.db")
    from coreflame.models import IllustRecord

    store.upsert_post(IllustRecord(source="pixiv", external_id="9", artist_id="1"))
    assert store.mark_post_gone("pixiv", "9")
    assert not store.mark_post_gone("pixiv", "9")  # idempotent
    assert store.stats()["posts_gone"] == 1
    print("  gone -> posts.state:  ok")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("visited gate")
        test_gate_states(tmp)
        test_threshold_invalidation(tmp)
        test_gate_prevents_detail_requests(tmp)
        test_404_marked_gone_once(tmp)
        test_min_bookmarks_skip_recorded(tmp)
        test_gone_propagates_to_posts(tmp)
    print("\nall passed")
