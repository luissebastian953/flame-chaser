"""The job runner. Offline: fake adapters, real SQLite, real threads where the
claim is about threads."""

from __future__ import annotations

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


class FakeAdapters(Adapters):
    """Real Adapters shape, fake pixiv, gallery-dl reported absent."""

    def __init__(self, cfg: Config, store: Store, pixiv=None) -> None:
        self.cfg = cfg
        self.pixiv = pixiv or fake_pixiv()
        self.pixiv.sink = store
        # bytes, not a network round-trip: each url gets a distinct image
        self.pixiv.fetch_media = lambda url, referer=None: _img(hash(url) % 1000, (120, 160))
        self.twitter = TwitterAdapter(binary="definitely-not-installed")
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
    assert j.counters["new_posts"] == 2 and j.counters["listed"] == 2
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


def test_failure_is_data(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "f")
    store = Store(cfg.db_path)
    jid = JobRunner.submit(store, "no-such-type")
    runner.run_pending(store)
    j = JobRunner.get(store, jid)
    assert j.state == "failed" and "no handler" in j.error
    print("  failure recorded:     ok (bad job type -> failed with error, runner survives)")


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
        test_failure_is_data(tmp)
    print("\nall passed")
