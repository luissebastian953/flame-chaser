"""The job runner. Offline: fake adapters, real SQLite, real threads where the
claim is about threads."""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_smoke import _img, fake_pixiv

from coreflame.blobs import BlobStore
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import Adapters, build_handlers
from coreflame.jobs import CANCELLED, INTERRUPTED, SUCCEEDED, JobRunner
from coreflame.models import IllustRecord, Watch
from coreflame.sources.twitter import TwitterAdapter


class FakeTwitter(TwitterAdapter):
    """gallery-dl replaced by a canned search answer: one two-image post that
    names the character. `available()` is true so the handler runs the X pass."""

    def __init__(self, store: Store) -> None:
        super().__init__(binary="definitely-not-installed")
        self.sink = store
        self.queries: list[str] = []

    def available(self) -> bool:
        return True

    def _run(self, url: str, limit: int, by_post: bool = False) -> list[dict]:
        self.queries.append(url)
        if "/search?" not in url:
            return []
        entry = {
            "tweet_id": 777,
            "content": "甘雨 sketch #原神",
            "date": "2026-08-21 03:00:00",
            "hashtags": ["原神"],
            "author": {"id": 9, "name": "Artist", "nick": "artist_x"},
            "width": 1200,
            "height": 1600,
        }
        return self._flatten(
            [
                [3, "https://pbs.twimg.com/media/AAA.jpg", {**entry, "num": 1}],
                [3, "https://pbs.twimg.com/media/BBB.jpg", {**entry, "num": 2}],
            ]
        )


class FakeAdapters(Adapters):
    """Real Adapters shape, fake pixiv, fake X search (see FakeTwitter)."""

    def __init__(self, cfg: Config, store: Store, pixiv=None) -> None:
        self.cfg = cfg
        self.pixiv = pixiv or fake_pixiv()
        self.pixiv.sink = store
        # bytes, not a network round-trip: each url gets a distinct image
        self.pixiv.fetch_media = lambda url, referer=None: _img(hash(url) % 1000, (120, 160))
        self.twitter = FakeTwitter(store)
        self.twitter.fetch_media = lambda url, referer=None: _img(hash(url) % 1000, (120, 160))
        self.blobs = BlobStore(cfg.blob_root)

    def close(self) -> None:
        pass


def make_runner(tmp: Path, pixiv_factory=None) -> tuple[JobRunner, Config]:
    cfg = Config(home=tmp / "home")

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx):
        return FakeAdapters(cfg, ctx.store, pixiv_factory() if pixiv_factory else None)

    return JobRunner(factory, build_handlers(make)), cfg


def test_poll_job_end_to_end(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "a")
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    events = []
    runner.subscribers.append(events.append)
    jid = JobRunner.submit(store, "poll", {"media": False})
    assert runner.run_pending(store) == 1
    j = JobRunner.get(store, jid)
    assert j.state == SUCCEEDED, j.error
    # 2 pixiv artworks; the X search for the slug lists 1 post that names
    # the character in Japanese only, so it is a NO_MATCH skip, not a post
    assert j.counters["new_posts"] == 2 and j.counters["listed"] == 3
    assert j.counters["skipped"] == 1
    stages = [e["message"] for e in events if e["kind"] == "stage"]
    assert stages[0] == "started" and "discover" in stages and stages[-1] == "finished"
    assert JobRunner.tail(store, jid)[-1]["data"]["state"] == "succeeded"
    assert store.stats()["posts"] == 2
    print(f"  poll job:             ok (stages {stages}; {len(events)} events persisted)")


def test_cancel_lands_on_a_record_boundary(tmp: Path) -> None:
    """A slow adapter yields records one at a time; cancel after the first
    lands. The job ends CANCELLED and the db holds exactly the records that
    were fully written -- never a torn one."""
    gate = threading.Event()
    first_written = threading.Event()

    def slow_pixiv():
        a = fake_pixiv()
        inner = a.discover

        def discover(*args, **kw):
            for i, rec in enumerate(inner(*args, **kw)):
                if i == 1:
                    first_written.set()
                    gate.wait(5)  # hold here until the test cancels
                yield rec

        a.discover = discover
        return a

    runner, cfg = make_runner(tmp / "b", slow_pixiv)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    jid = JobRunner.submit(store, "poll", {"media": False, "link": False, "twitter": False})
    runner.start()
    assert first_written.wait(5)
    assert runner.cancel(store, jid)  # running -> flag + in-memory event
    gate.set()
    j = JobRunner.get(store, jid)
    for _ in range(100):
        j = JobRunner.get(store, jid)
        if j.state != "running":
            break
        time.sleep(0.05)
    runner.stop()
    assert j.state == CANCELLED, j.state
    posts = store.conn.execute("SELECT external_id FROM posts ORDER BY external_id").fetchall()
    assert [r[0] for r in posts] == ["1002"]  # exactly one full record
    tags = store.conn.execute("SELECT count(*) FROM post_tags WHERE external_id='1002'").fetchone()[
        0
    ]
    assert tags > 0  # ...and it is complete
    print("  cancel:               ok (cancelled at record boundary; 1 complete post, 0 torn)")


def test_cancel_queued(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "c")
    store = Store(cfg.db_path)
    jid = JobRunner.submit(store, "tags")
    assert runner.cancel(store, jid) and JobRunner.get(store, jid).state == CANCELLED
    assert not runner.cancel(store, jid)  # terminal: nothing to do
    print("  cancel queued:        ok (immediate; terminal jobs refuse a second cancel)")


def test_cancel_from_other_process(tmp: Path) -> None:
    """No in-memory event -- only the db flag, as `coreflame jobs cancel` from
    a second process would set it. check() must notice within check_every."""
    gate = threading.Event()

    def slow_pixiv():
        a = fake_pixiv()
        inner = a.discover

        def discover(*args, **kw):
            for rec in inner(*args, **kw):
                gate.wait(5)
                yield rec

        a.discover = discover
        return a

    runner, cfg = make_runner(tmp / "g", slow_pixiv)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    jid = JobRunner.submit(store, "poll", {"media": False, "link": False, "twitter": False})
    store.conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (jid,))
    runner.start()
    gate.set()
    for _ in range(100):
        j = JobRunner.get(store, jid)
        if j.state not in ("queued", "running"):
            break
        time.sleep(0.05)
    runner.stop()
    assert j.state == CANCELLED, j.state
    print("  cancel via db flag:   ok (another process's cancel is honoured)")


def test_interrupted_at_boot(tmp: Path) -> None:
    cfg = Config(home=tmp / "d" / "home")
    store = Store(cfg.db_path)
    jid = JobRunner.submit(store, "poll")
    store.conn.execute("UPDATE jobs SET state='running', started_at='x' WHERE id=?", (jid,))
    store.close()
    runner, _ = make_runner(tmp / "d")  # same home -> same db
    assert runner.interrupted == 1
    j = JobRunner.get(Store(cfg.db_path), jid)
    assert j.state == INTERRUPTED and "exited" in (j.error or "")
    print("  interrupted at boot:  ok (running row -> interrupted with reason)")


def test_honest_denominators(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "e")
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    events = []
    runner.subscribers.append(events.append)
    JobRunner.submit(store, "poll", {"media": False, "link": False, "twitter": False})
    runner.run_pending(store)
    disc = [e for e in events if e["kind"] == "progress"]
    assert disc and all(e["data"]["total"] is None for e in disc)  # discover: no honest total
    store.upsert_post(
        IllustRecord(
            source="pixiv",
            external_id="9",
            artist_id="1",
            media=[{"index": 0, "url": "https://i.pximg.net/x.png"}],
        )
    )
    pending = store.stats()["media_pending"]  # the poll queued 3, plus this one
    assert pending == 4
    events.clear()
    JobRunner.submit(store, "media")
    runner.run_pending(store)
    prog = [e for e in events if e["kind"] == "progress"]
    assert prog and prog[0]["data"]["total"] == prog[-1]["data"]["total"] == pending
    assert prog[-1]["data"]["done"] == pending
    assert store.stats()["media_stored"] == pending  # bytes really landed in blobs/
    # ...and each stored file has a readable second name under by-character/<slug>/
    view = cfg.blob_root.parent / "by-character" / "ganyu"
    placed = sorted(p.name for p in view.iterdir()) if view.exists() else []
    assert placed and all(n.endswith((".png", ".jpg")) for n in placed), placed
    assert any("1002" in n for n in placed)
    print(f"  honest denominators:  ok (discover total=None; media total={pending}=pending count)")


def test_watch_sources_gate_each_stage(tmp: Path) -> None:
    """A watch crawls only the sources it has ticked. pixiv-off means no
    search request and -- the part that matters for the unauthenticated case
    -- no 'not signed in' failure either; X-off drops the watch from the
    timeline matcher. Both off is rejected at the model."""
    try:
        Watch(slug="none", sources=[])
    except ValueError:
        pass
    else:
        raise AssertionError("a watch with no source must be rejected")
    assert Watch(slug="d").sources == ["pixiv", "twitter"]  # default: both
    assert Watch(slug="x", sources=["twitter", "twitter"]).sources == ["twitter"]

    runner, cfg = make_runner(tmp / "s")
    store = Store(cfg.db_path)
    store.upsert_watch(
        Watch(slug="ganyu", pixiv_tags=["甘雨"], match_terms=["甘雨"], sources=["twitter"])
    )
    assert store.watches()[0].sources == ["twitter"]  # round-trips through v4 column
    jid = JobRunner.submit(store, "poll", {"media": False, "link": False})
    runner.run_pending(store)
    j = JobRunner.get(store, jid)
    assert j.state == SUCCEEDED, j.error
    # X-only: no pixiv request (it would have failed -- the fake is authed but
    # the point is no pixiv rows), one X search hit archived under the watch
    rows = store.conn.execute("SELECT source, external_id FROM posts").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("twitter", "777")]
    assert store.conn.execute("SELECT slug FROM post_watches").fetchone()[0] == "ganyu"
    assert store.watermark("twitter", "search:甘雨") == "777"
    log = " ".join(e["message"] for e in JobRunner.tail(store, jid))
    assert "'甘雨' · older page" in log and "no linked X artists yet" in log
    # every job says how old the running engine is -- stale-process detection
    assert "engine up" in log

    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"], sources=["pixiv"]))
    jid = JobRunner.submit(store, "poll", {"media": False, "link": False})
    runner.run_pending(store)
    j = JobRunner.get(store, jid)
    assert j.state == SUCCEEDED, j.error
    assert store.stats()["posts"] == 3  # + the two pixiv artworks
    print("  watch sources:        ok (X-only -> 1 search hit, no pixiv; pixiv-only -> +2)")


def test_failure_is_data(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "f")
    store = Store(cfg.db_path)
    jid = JobRunner.submit(store, "no-such-type")
    runner.run_pending(store)
    j = JobRunner.get(store, jid)
    assert j.state == "failed" and "no handler" in j.error
    print("  failure recorded:     ok (bad job type -> failed with error, runner survives)")


class _FlakyConn:
    """A connection whose queue query fails once with the error Docker's file
    sharing produced when the host wrote to the db under a running container."""

    def __init__(self, real) -> None:
        self.real, self.failed = real, False

    def execute(self, sql, *args):
        if not self.failed and "WHERE state='queued'" in sql:
            self.failed = True
            raise sqlite3.OperationalError("disk I/O error")
        return self.real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self.real, name)


def test_worker_survives_an_error_outside_a_job(tmp: Path) -> None:
    """The worker thread used to die on any error around a job, leaving every
    later job queued forever while the API said "idle"."""
    cfg = Config(home=tmp / "worker")
    made: list[Store] = []

    def factory() -> Store:
        s = Store(cfg.db_path)
        if threading.current_thread().name == "coreflame-worker":
            if not made:  # only the worker's first connection is broken
                s.conn = _FlakyConn(s.conn)  # type: ignore[assignment]
            made.append(s)
        return s

    ran = threading.Event()

    def noop(ctx) -> dict:
        ran.set()
        return {"ok": 1}

    runner = JobRunner(factory, {"noop": noop})
    store = Store(cfg.db_path)
    jid = JobRunner.submit(store, "noop", {})
    runner.start()
    try:
        assert ran.wait(15), "the worker died instead of retrying"
        deadline = time.time() + 5
        while JobRunner.get(store, jid).state != SUCCEEDED and time.time() < deadline:
            time.sleep(0.05)
    finally:
        runner.stop()
    assert JobRunner.get(store, jid).state == SUCCEEDED
    assert len(made) >= 2  # the worker reopened its connection
    print("  worker survives:      ok (queue query failed once; reconnected and ran the job)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("jobs")
        test_poll_job_end_to_end(tmp)
        test_cancel_lands_on_a_record_boundary(tmp)
        test_cancel_queued(tmp)
        test_cancel_from_other_process(tmp)
        test_interrupted_at_boot(tmp)
        test_honest_denominators(tmp)
        test_watch_sources_gate_each_stage(tmp)
        test_failure_is_data(tmp)
        test_worker_survives_an_error_outside_a_job(tmp)
    print("\nall passed")
