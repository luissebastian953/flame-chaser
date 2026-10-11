"""X search to a target: a crawl keeps exactly N new posts, the next crawl
continues further back, new posts are caught up first, and it stops when
history runs out or the terms stop paying. Offline: a fake X with a fixed,
deep history that answers max_id like X does (inclusive, plus the post just
above), and a labeler that keeps even ids and throws odd ones away."""

from __future__ import annotations

import io
import random
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from test_jobs import FakeAdapters

from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import build_handlers
from coreflame.jobs import SUCCEEDED, JobRunner
from coreflame.kinds import Label
from coreflame.models import Watch
from coreflame.sources.twitter import TwitterAdapter

SLUG = "raiden-mei"
TERM = "raiden mei"


def post_image(i: int) -> bytes:
    """Noise seeded by the id (no near-dupes), corner pixel red for odd ids."""
    rnd = random.Random(i)
    im = Image.new("RGB", (40, 50))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(2000)])
    im.putpixel((0, 0), (255, 0, 0) if i % 2 else (0, 0, 255))
    im = im.resize((120, 150), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class ParityLabeler:
    """Odd ids (red corner) are photos -> thrown away; even ids are kept."""

    model = "parity-v1"

    def label(self, data: bytes) -> Label:
        r, _, b = Image.open(io.BytesIO(data)).convert("RGB").getpixel((0, 0))
        return Label("photo" if r > 200 and b < 50 else "illustration", {}, self.model)


class DeepX(TwitterAdapter):
    """X search over a fixed history of ids, newest first, one image each."""

    def __init__(self, store: Store, ids: list[int]) -> None:
        super().__init__(binary="definitely-not-installed")
        self.sink = store
        self.ids = sorted(ids, reverse=True)
        self.pages: list[tuple[str, int | None]] = []
        self.fetch_media = lambda url, referer=None: post_image(int(url.rsplit("/", 1)[1][:-4]))

    def available(self) -> bool:
        return True

    def _run(self, url: str, limit: int, by_post: bool = False) -> list[dict]:
        assert by_post, "target search must count posts, not images"
        q = parse_qs(urlparse(url).query)["q"][0]
        m = re.search(r"max_id:(\d+)", q)
        max_id = int(m.group(1)) if m else None
        self.pages.append((q.split(" filter:")[0], max_id))
        rows = self.ids
        if max_id is not None:  # X: at or below max_id, plus the one just above
            rows = [i for i in rows if i > max_id][-1:] + [i for i in rows if i <= max_id]
        out = []
        for i in rows[:limit]:
            meta = {
                "tweet_id": i,
                "content": f"{TERM} fanart #{i}",
                "date": "2026-08-21 03:00:00",
                "hashtags": [],
                "author": {"id": i, "name": f"artist{i}", "nick": f"artist{i}"},
                "width": 120,
                "height": 150,
                "num": 1,
            }
            out.append([3, f"https://pbs.twimg.com/media/{i}.png", meta])
        return self._flatten(out)


def setup(tmp: Path, ids: list[int], target: int = 100):
    cfg = Config(home=tmp / "home")
    store = Store(cfg.db_path)
    store.upsert_watch(
        Watch(slug=SLUG, label="Raiden Mei", match_terms=[TERM], sources=["twitter"], target=target)
    )
    x = DeepX(store, ids)

    def make(ctx):
        a = FakeAdapters(cfg, ctx.store)
        a.twitter = x
        a.labeler = ParityLabeler()
        return a

    def factory() -> Store:
        return Store(cfg.db_path)

    return JobRunner(factory, build_handlers(make)), store, x


def crawl(runner: JobRunner, store: Store, target: int | None):
    params: dict = {"watches": [SLUG], "link": False}
    if target is not None:
        params["target"] = target
    jid = JobRunner.submit(store, "poll", params)
    runner.run_pending(store)
    j = JobRunner.get(store, jid)
    assert j.state == SUCCEEDED, j.error
    return j


def kept_ids(store: Store) -> list[int]:
    return sorted(
        int(r[0])
        for r in store.conn.execute(
            """SELECT DISTINCT m.external_id FROM media m
               JOIN post_watches pw ON pw.source=m.source AND pw.external_id=m.external_id
               WHERE pw.slug=? AND m.state='stored'""",
            (SLUG,),
        )
    )


def cursors(store: Store) -> tuple[str | None, str | None]:
    return store.watermark("twitter", f"search:{TERM}"), store.watermark(
        "twitter", f"search-lo:{TERM}"
    )


def log_lines(store: Store, jid: str) -> list[str]:
    return [r[0] for r in store.conn.execute("SELECT message FROM job_log WHERE job_id=?", (jid,))]


def test_exact_target_then_further_back(tmp: Path) -> None:
    runner, store, _x = setup(tmp / "a", list(range(1000, 1200)))

    j = crawl(runner, store, 7)
    # newest first: 1199 photo, 1198 kept, ... the 7th keeper is 1186
    assert kept_ids(store) == list(range(1186, 1199, 2))
    prog = [
        m
        for (m,) in store.conn.execute(
            "SELECT message FROM job_log WHERE job_id=? AND kind='progress'", (j.id,)
        )
    ]
    assert "0/7" in prog and "7/7" in prog and "8/7" not in prog  # kept / target, exact
    assert j.counters["listed"] == 14 and j.counters["rejected"] == 7
    assert cursors(store) == ("1199", "1186")  # the rest of the page waits, unskipped

    j = crawl(runner, store, 7)  # continues below 1186, re-lists nothing
    assert kept_ids(store) == list(range(1172, 1199, 2))
    assert j.counters["listed"] == 14 and j.counters["gated"] == 0
    assert cursors(store) == ("1199", "1172")
    print(
        "  exact target:         ok (7 kept of 14 listed, twice; second crawl starts below the first)"
    )


def test_new_posts_first(tmp: Path) -> None:
    runner, store, x = setup(tmp / "b", list(range(1000, 1200)))
    crawl(runner, store, 5)  # covers 1199..1190
    x.ids = sorted([*x.ids, 1200, 1201, 1202, 1203], reverse=True)  # four new posts
    crawl(runner, store, 3)
    # the two new keepers first (1202, 1200), then back below the old stretch
    assert {1200, 1202, 1188} <= set(kept_ids(store)) and 1186 not in kept_ids(store)
    assert cursors(store) == ("1203", "1188")
    print("  new posts first:      ok (caught up 1200-1203 before walking back)")


def test_history_runs_out(tmp: Path) -> None:
    runner, store, x = setup(tmp / "c", list(range(1, 21)))
    j = crawl(runner, store, 100)
    assert kept_ids(store) == list(range(2, 21, 2))
    assert j.counters["downloaded"] == 10
    assert cursors(store)[1] == "0"
    assert any("history complete" in m for m in log_lines(store, j.id))
    before = len(x.pages)
    j = crawl(runner, store, 100)  # nothing older left: one catch-up page, no walk back
    assert j.counters["listed"] == 0 and len(x.pages) - before == 1
    print(f"  history runs out:     ok (10 kept of 20; next crawl = {len(x.pages) - before} page)")


def test_safety_stop(tmp: Path) -> None:
    runner, store, _x = setup(tmp / "d", list(range(1, 2000, 2)))  # odd ids: all photos
    j = crawl(runner, store, 5)
    assert j.counters["downloaded"] == 0 and j.counters["listed"] == 50  # 10 x target
    assert any("matches mostly other things" in m for m in log_lines(store, j.id))
    print("  safety stop:          ok (0 kept -> stopped after listing 10 x target)")


def test_term_searched_the_old_way(tmp: Path) -> None:
    """A term with only the old newest-N watermark: catch up above it first,
    then walk back from it; nothing in between is skipped."""
    runner, store, _x = setup(tmp / "e", list(range(1000, 1200)))
    store.set_watermark("twitter", f"search:{TERM}", "1100")
    j = crawl(runner, store, 60)
    got = kept_ids(store)
    assert len(got) == 60 and j.counters["downloaded"] == 60
    assert all(i > 1100 for i in got[-49:])  # 49 keepers above 1100 came first
    assert got[:11] == list(range(1078, 1099, 2))  # then below 1100, no gap
    print("  old watermark:        ok (caught up above 1100, then walked back from it)")


def test_each_character_uses_its_own_posts_per_run(tmp: Path) -> None:
    """Run / Run all send no number: each character's saved posts-per-run applies."""
    runner, store, _x = setup(tmp / "f", list(range(1000, 1200)), target=4)
    crawl(runner, store, None)
    assert kept_ids(store) == [1192, 1194, 1196, 1198]
    crawl(runner, store, 2)  # an explicit number still overrides it
    assert len(kept_ids(store)) == 6
    print("  per character:        ok (saved posts-per-run 4 -> 4 kept; params override)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("target")
        test_exact_target_then_further_back(tmp)
        test_new_posts_first(tmp)
        test_history_runs_out(tmp)
        test_safety_stop(tmp)
        test_term_searched_the_old_way(tmp)
        test_each_character_uses_its_own_posts_per_run(tmp)
    print("\nall passed")
