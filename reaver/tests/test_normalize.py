"""Layered normalization: retain raw -> extract -> validate -> persist;
quarantine on failure; re-normalize from raw after a spec fix; drift alarm."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from test_smoke import DETAIL, fake_pixiv

from coreflame.db import Store
from coreflame.models import DiscoverStats, IllustRecord, Watch
from coreflame.sources.specs import PIXIV_DETAIL, extract, null_rate


def test_raw_retained_and_addressable(tmp: Path) -> None:
    store = Store(tmp / "r.db")
    a = fake_pixiv()
    a.sink = store
    recs = list(a.discover(Watch(slug="ganyu", pixiv_tags=["甘雨"]), None, stats=DiscoverStats()))
    assert all(r.raw_sha for r in recs)
    for r in recs:
        store.upsert_post(r, "ganyu")
    st = store.stats()
    assert st["raw_payloads"] == 3  # 2 details + 1 pages
    body = store.get_raw(recs[0].raw_sha)
    assert body["illustId"] == recs[0].external_id
    # idempotent: same payload, same sha, no second row
    again = store.put_raw("pixiv", "pixiv_detail", body, recs[0].external_id)
    assert again == recs[0].raw_sha and store.stats()["raw_payloads"] == 3
    print(f"  raw retained:         ok ({st['raw_payloads']} payloads, {st['raw_bytes']} B zlib'd)")


def test_two_form_tags_persisted(tmp: Path) -> None:
    store = Store(tmp / "t.db")
    r = IllustRecord(
        source="pixiv",
        external_id="1",
        artist_id="7",
        tags=["申鶴（原神）", "申鶴(原神)", "Shenhe"],
    )
    assert len(r.tags) == 2  # fullwidth dupe collapsed at the edge
    store.upsert_post(r, "shenhe")
    rows = store.conn.execute(
        "SELECT tag_raw, tag_norm FROM post_tags WHERE external_id='1' ORDER BY tag_norm"
    ).fetchall()
    assert [tuple(x) for x in rows] == [("Shenhe", "shenhe"), ("申鶴（原神）", "申鶴(原神)")]
    print("  tag_raw + tag_norm:   ok (raw keeps fullwidth for search; norm folds it)")


def test_quarantine_then_recover(tmp: Path) -> None:
    store = Store(tmp / "q.db")
    a = fake_pixiv()
    a.sink = store
    # a payload with no userId: extraction leaves artist_id out, validation fails
    broken = {k: dict(v) for k, v in DETAIL.items()}
    broken["1002"] = {"error": False, "body": {**DETAIL["1002"]["body"]}}
    broken["1002"]["body"].pop("userId")
    inner = a.client.get_json

    def get_json(url, **kw):
        if "/ajax/illust/1002?" in url:
            return broken["1002"]
        return inner(url, **kw)

    a.client.get_json = get_json

    ds = DiscoverStats()
    recs = list(a.discover(Watch(slug="ganyu", pixiv_tags=["甘雨"]), None, stats=ds))
    assert [r.external_id for r in recs] == ["1001"] and ds.failed == 1
    for r in recs:
        store.upsert_post(r, "ganyu")
    q = store.conn.execute("SELECT * FROM quarantine").fetchall()
    assert len(q) == 1 and q[0]["external_id"] == "1002" and "artist_id" in q[0]["error"]
    assert q[0]["raw_sha"] is not None
    print("  quarantine on fail:   ok (raw retained, error recorded, crawl continued)")

    # re-normalize from raw after a "spec fix" -- here the fix is a fallback
    # that supplies the missing field -- with ZERO network requests
    fixed = 0
    for sha, eid, body in store.raws_for("pixiv", "pixiv_detail"):
        if eid != "1002":
            continue
        fields = extract(PIXIV_DETAIL, body)
        fields.setdefault("artist_id", "unknown")
        rec = IllustRecord(**fields, raw_sha=sha, media=[{"index": 0, "url": "https://x/p.png"}])
        store.upsert_post(rec, "ganyu")
        fixed += 1
    assert fixed == 1
    assert store.stats()["quarantined"] == 0  # released on successful upsert
    assert store.stats()["posts"] == 2
    print("  re-normalize from raw: ok (recovered without a fetch; quarantine released)")


def test_drift_alarm(tmp: Path) -> None:
    store = Store(tmp / "d.db")
    fields = ["title", "tags", "posted_at"]
    good = [extract(PIXIV_DETAIL, DETAIL["1002"]["body"])] * 50
    store.record_extraction("run-1", "pixiv", "pixiv_detail", null_rate(good, fields), 50)
    assert store.extraction_drift("pixiv", "pixiv_detail") == []
    broken_body = {**DETAIL["1002"]["body"]}
    broken_body.pop("illustTitle")
    bad = [extract(PIXIV_DETAIL, broken_body)] * 48 + good[:2]
    store.record_extraction("run-2", "pixiv", "pixiv_detail", null_rate(bad, fields), 50)
    drift = store.extraction_drift("pixiv", "pixiv_detail")
    assert drift and drift[0][0] == "title" and drift[0][2] > 0.9
    print(f"  drift alarm:          ok (title null rate {drift[0][1]:.0%} -> {drift[0][2]:.0%})")


def test_model_invariants() -> None:
    r = IllustRecord(
        source="twitter",
        external_id=1958871220337,
        artist_id=9,
        posted_at="2026-08-21 03:00:00",
        source_meta={"favorite_count": 12},
    )
    assert r.external_id == "1958871220337" and isinstance(r.external_id, str)
    assert r.posted_at.isoformat() == "2026-08-21T03:00:00+00:00"
    for bad in [
        dict(source="lofter", external_id="1", artist_id="1"),
        dict(source="pixiv", external_id="", artist_id="1"),
        dict(source="pixiv", external_id="1", artist_id="1", likes=1),
    ]:
        try:
            IllustRecord(**bad)
            raise AssertionError(bad)
        except ValidationError:
            pass
    print("  model invariants:     ok (str ids, timezone.utc, closed source enum, no extras)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("normalization")
        test_model_invariants()
        test_raw_retained_and_addressable(tmp)
        test_two_form_tags_persisted(tmp)
        test_quarantine_then_recover(tmp)
        test_drift_alarm(tmp)
    print("\nall passed")
