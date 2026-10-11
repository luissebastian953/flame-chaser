"""The per-character gender filter: counting tags -> girls/boys, the full and
partial rules, judging at download, the backlog cleanup, and loosening a
filter bringing its rejections back. Offline: a fake tagger answers a fixed
sequence of (girls, boys) instead of the 467 MB model."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from test_jobs import FakeAdapters
from test_kinds import FakeLabeler, blob_exists, media_by_state, run, runner_with

from coreflame import people
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import build_handlers
from coreflame.jobs import SUCCEEDED, JobRunner
from coreflame.models import IllustRecord, Watch
from coreflame.people import People, accepts, counts


class FakeTagger:
    """Same shape as people.Tagger; answers `seq` in call order (cycling)."""

    model = "fake-tagger"

    def __init__(self, seq: list[tuple[int, int]]) -> None:
        self.seq, self.calls = seq, 0

    def people(self, data: bytes) -> People:
        g, b = self.seq[self.calls % len(self.seq)]
        self.calls += 1
        return People(g, b, False, {"1girl": 0.9} if g else {}, {}, self.model)


def runner_with_tagger(tmp: Path, tagger, labeler=None) -> tuple[JobRunner, Config]:
    """runner_with() from test_kinds, plus a tagger on the fake adapters."""
    cfg = Config(home=tmp / "home")

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx):
        a = FakeAdapters(cfg, ctx.store)
        a.labeler = labeler or FakeLabeler(sequence=("illustration",))
        a.tagger = tagger
        return a

    return JobRunner(factory, build_handlers(make)), cfg


def test_counts_and_rules() -> None:
    assert counts({"1girl": 0.9, "1boy": 0.4, "male_focus": 0.1}) == (1, 1, False)
    assert counts({"6+girls": 0.8, "multiple_boys": 0.5}) == (6, 2, False)
    assert counts({"1girl": 0.9, "1boy": 0.27}) == (1, 0, False)  # under the 0.35 cut
    table = [
        # girls, boys, focus, gender, mode, kept?
        (1, 0, False, "female", "full", True),
        (2, 1, False, "female", "full", False),
        (2, 1, False, "female", "partial", True),  # the boy is the minority
        (1, 1, False, "female", "partial", False),  # a tie is not a minority
        (2, 1, True, "female", "partial", False),  # male_focus: the picture is about him
        (0, 0, False, "female", "full", False),  # nobody: not this character
        (0, 2, False, "male", "full", True),
        (1, 2, False, "male", "partial", True),
        (1, 1, False, "any", "full", True),
        (0, 0, False, "any", "full", True),
    ]
    for g, b, f, gender, mode, want in table:
        assert accepts(g, b, f, gender, mode) is want, (g, b, f, gender, mode)
    print(f"  rules:                ok ({len(table)} cases: full, partial minority, focus, nobody)")


def test_encode_matches_the_tagger_input() -> None:
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("  encode:               skipped (numpy not installed -- reaver[classify])")
        return
    wide = Image.new("RGB", (200, 100), (255, 0, 0))  # red, wider than tall
    buf = io.BytesIO()
    wide.save(buf, "PNG")
    x = people.encode(buf.getvalue())
    assert x.shape == (1, 448, 448, 3) and str(x.dtype) == "float32"
    assert tuple(x[0, 224, 224]) == (0.0, 0.0, 255.0)  # BGR: red is the LAST channel
    assert tuple(x[0, 5, 224]) == (255.0, 255.0, 255.0)  # padded top: white
    print("  encode:               ok (1x448x448x3 BGR 0..255, padded white to a square)")


def test_judged_at_download(tmp: Path) -> None:
    tagger = FakeTagger([(1, 0), (1, 1), (0, 2)])  # girl / girl+boy / two boys
    runner, cfg = runner_with_tagger(tmp / "a", tagger)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"], gender="female"))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED, j.error
    stored, gone = media_by_state(store, "stored"), media_by_state(store, "rejected")
    assert stored and gone and tagger.calls == len(stored) + len(gone)
    assert all(r["error"].startswith("gender:") for r in gone)
    assert all(not blob_exists(cfg, r["sha256"]) for r in gone)
    tagged = store.conn.execute("SELECT count(*) FROM image_people").fetchone()[0]
    assert tagged == tagger.calls
    print(f"  at download:          ok ({len(stored)} kept, {len(gone)} rejected before storage)")


def test_no_filter_costs_nothing(tmp: Path) -> None:
    tagger = FakeTagger([(0, 1)])
    runner, cfg = runner_with_tagger(tmp / "b", tagger)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))  # gender any
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    assert tagger.calls == 0 and not media_by_state(store, "rejected")
    print("  no filter:            ok (the tagger is never called)")


def test_any_character_that_accepts_keeps_it(tmp: Path) -> None:
    store = Store(tmp / "c.db")
    store.upsert_watch(Watch(slug="kiana", gender="female"))
    store.upsert_watch(Watch(slug="kevin", gender="male"))
    store.upsert_post(
        IllustRecord(
            source="twitter",
            external_id="1",
            artist_id="a",
            posted_at="2026-09-01T00:00:00+00:00",
            media=[{"index": 0, "url": "https://x/1.jpg"}],
        ),
        "kiana",
    )
    from coreflame.pipeline import _passes_gender

    assert not _passes_gender(store, "twitter", "1", 0, 1, False)  # kiana alone: no
    store.conn.execute("INSERT INTO post_watches VALUES('twitter','1','kevin')")
    assert _passes_gender(store, "twitter", "1", 0, 1, False)  # kevin's post too: yes
    print("  shared post:          ok (kept when any of its characters accepts it)")


def test_backlog_and_loosening(tmp: Path) -> None:
    # stored with no filter, then the filter is switched on: the label job judges them
    runner, cfg = runner_with(tmp / "d", None)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    before = len(media_by_state(store, "stored"))
    assert before >= 2

    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"], gender="female"))
    assert store.people_pending("ganyu", "fake-tagger") == before
    tagger = FakeTagger([(1, 0), (1, 1)])
    runner2, _ = runner_with_tagger(tmp / "d", tagger)
    j = run(runner2, store, "label", {})
    assert j.state == SUCCEEDED, j.error
    removed = j.counters["removed_gender"]
    assert j.counters["tagged"] == before and removed >= 1
    assert len(media_by_state(store, "stored")) == before - removed
    assert store.people_pending("ganyu", "fake-tagger") == 0

    # a kind rejection on the same character, to show the two reopen separately
    store.conn.execute(
        "UPDATE media SET state='rejected', error='photo' WHERE state='stored' AND rowid="
        "(SELECT min(rowid) FROM media WHERE state='stored')"
    )
    # full -> partial is looser: the gender rejections come back, the photo does not
    reopened = store.upsert_watch(
        Watch(slug="ganyu", pixiv_tags=["甘雨"], gender="female", gender_mode="partial")
    )
    assert reopened == removed
    assert [r["error"] for r in media_by_state(store, "rejected")] == ["photo"]
    # stricter (partial -> full) reopens nothing
    assert store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"], gender="female")) == 0
    print(f"  backlog + loosen:     ok ({removed} removed; loosening reopened them, not the photo)")


def test_watch_gender_round_trip(tmp: Path) -> None:
    store = Store(tmp / "e.db")
    store.upsert_watch(Watch(slug="mei", gender="female", gender_mode="partial"))
    w = store.watches()[0]
    assert (w.gender, w.gender_mode) == ("female", "partial")  # through the v7 columns
    for bad in ({"gender": "girls"}, {"gender_mode": "half"}):
        try:
            Watch(slug="x", **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} must be rejected")
    print("  watch fields:         ok (round-trip; unknown values refused)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("people")
        test_counts_and_rules()
        test_encode_matches_the_tagger_input()
        test_judged_at_download(tmp)
        test_no_filter_costs_nothing(tmp)
        test_any_character_that_accepts_keeps_it(tmp)
        test_backlog_and_loosening(tmp)
        test_watch_gender_round_trip(tmp)
    print("\nall passed")
