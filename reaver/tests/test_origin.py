"""AI-made or by hand (coreflame/origin.py): the hashtag fold, what a post
declares (pixiv's flag, an AI tag), the model's cut, the verdict at download
(labels only, never rejects), the label job's backlog with and without the
detector, and a newer model re-judging only its own verdicts. Offline: a
fake detector answers fixed scores instead of the 17 MB model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_jobs import FakeAdapters
from test_kinds import FakeLabeler, media_by_state, run
from test_smoke import DETAIL

from coreflame import origin
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import build_handlers
from coreflame.jobs import SUCCEEDED, JobRunner
from coreflame.kinds import ModelError
from coreflame.models import Watch
from coreflame.origin import Origin, declared, fold, judge


class FakeDetector:
    """Same shape as origin.Detector; answers `scores` in call order (cycling)."""

    def __init__(
        self,
        scores: tuple[float, ...] = (0.97, 0.02),
        model: str = "fake-ai",
        raise_for: type[Exception] | None = None,
    ) -> None:
        self.scores, self.calls, self.model, self.raise_for = scores, 0, model, raise_for

    def score(self, data: bytes) -> float:
        self.calls += 1
        if self.raise_for is not None:
            raise self.raise_for("boom")
        return self.scores[(self.calls - 1) % len(self.scores)]


def runner_with_detector(tmp: Path, detector) -> tuple[JobRunner, Config]:
    cfg = Config(home=tmp / "home")

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx):
        a = FakeAdapters(cfg, ctx.store)
        a.labeler = FakeLabeler(sequence=("illustration",))
        a.tagger = None
        a.identifier = None
        a.detector = detector
        return a

    return JobRunner(factory, build_handlers(make)), cfg


def rows(store: Store) -> list:
    return store.conn.execute("SELECT * FROM image_origin ORDER BY sha256").fetchall()


def test_fold_and_declared() -> None:
    # the fold: NFKC + casefold, then fillers, variation selectors and separators go
    assert fold("AIart️️️") == "aiart"
    assert fold("AIイラストㅤㅤ") == "aiイラスト"
    assert fold("Stable_Diffusion") == fold("stablediffusion") == "stablediffusion"
    assert fold("ＡＩアート") == "aiアート"
    for t in ("AIイラスト", "#aiart", "NovelAI", "AI生成", "pixai"):
        assert fold(t.lstrip("#")) in origin.AI_TAGS, t
    assert fold("KizunaAi") not in origin.AI_TAGS and fold("waifu") not in origin.AI_TAGS
    # what the post says
    assert declared({"ai_type": 2}, []) == Origin("ai", "declared")
    assert declared({"ai_type": "2"}, []) == Origin("ai", "declared")
    assert declared({"ai_type": 1}, ["HonkaiStarRail"]) is None  # "not AI" is not a human verdict
    assert declared({}, ["ホタル", "AIart️"]) == Origin("ai", "tags")
    assert declared(None, ["ホタル"]) is None
    assert declared({"ai_type": "x"}, ["AIイラスト"]) == Origin("ai", "tags")  # junk flag, tag wins
    # the verdict: declared wins, else the model's cut, else pending
    assert judge(Origin("ai", "tags"), 0.01) == Origin("ai", "tags")
    assert judge(None, 0.5, "m") == Origin("ai", "model", 0.5, "m")
    assert judge(None, 0.4999, "m") == Origin("human", "model", 0.4999, "m")
    assert judge(None, 0.123456, "m").score == 0.1235
    assert judge(None, None) is None
    assert origin.MODEL.labels == ("ai", "human") and origin.DETECTOR_ID.startswith(
        "anime_ai_check"
    )
    print("  fold + declared:      ok (fillers stripped, pixiv flag, AI tags, the cut)")


def test_judged_at_download(tmp: Path) -> None:
    """Post 1001 arrives tagged #AIイラスト (padded the way X posters pad it):
    its tag decides and the model is not asked. Post 1002 says nothing: the
    model scores each of its two pages."""
    det = FakeDetector((0.97, 0.02))
    runner, cfg = runner_with_detector(tmp / "a", det)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    tags = DETAIL["1001"]["body"]["tags"]["tags"]
    tags.append({"tag": "AIイラスト️️"})
    try:
        j = run(runner, store, "poll", {})
    finally:
        tags.pop()
    assert j.state == SUCCEEDED, j.error
    stored = media_by_state(store, "stored")
    shas = {r["sha256"] for r in stored}
    assert shas and not media_by_state(store, "rejected")  # the origin never rejects
    by_post = {r["sha256"]: r["external_id"] for r in stored}
    got = {r["sha256"]: r for r in rows(store)}
    assert set(got) == shas and j.counters["judged"] == len(shas)
    tagged = [o for sha, o in got.items() if by_post[sha] == "1001"]
    scored = [o for sha, o in got.items() if by_post[sha] == "1002"]
    assert len(tagged) == 1 and tagged[0]["by"] == "tags" and tagged[0]["state"] == "ai"
    assert tagged[0]["score"] is None and tagged[0]["model"] == ""
    assert len(scored) == det.calls == 2
    assert {o["by"] for o in scored} == {"model"} and {o["model"] for o in scored} == {"fake-ai"}
    assert {(o["state"], o["score"]) for o in scored} == {("ai", 0.97), ("human", 0.02)}
    assert store.origin_counts("ganyu", "fake-ai") == {"ai": 2, "human": 1, "pending": 0}
    # model verdicts read as pending against another model; the tagged one stands
    assert store.origin_counts("ganyu", "fake-ai-2") == {"ai": 1, "human": 0, "pending": 2}
    print("  at download:          ok (1 by its tag, 2 scored by the model, none rejected)")


def test_detector_off_keeps_crawling(tmp: Path) -> None:
    broken = FakeDetector(raise_for=ModelError)
    runner, cfg = runner_with_detector(tmp / "b", broken)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED, j.error
    assert media_by_state(store, "stored") and not rows(store)
    assert broken.calls == 1  # unusable once: not asked again this run
    print("  detector unusable:    ok (crawl went on, images stay pending)")


def test_backlog_declared_then_model(tmp: Path) -> None:
    runner, cfg = runner_with_detector(tmp / "c", None)  # no deps: nothing judged
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    stored = media_by_state(store, "stored")
    shas = {r["sha256"] for r in stored}
    assert len(shas) == 3 and not rows(store)
    assert len(store.unjudged_media("")) == 3

    # post 1002 (two pages) is flagged AI-generated on pixiv; 1001 says nothing
    store.conn.execute(
        "UPDATE posts SET source_meta=? WHERE source='pixiv' AND external_id='1002'",
        (json.dumps({"ai_type": 2}),),
    )
    store.conn.commit()
    said = {r["sha256"] for r in stored if r["external_id"] == "1002"}  # every page
    assert len(said) == 2
    flagged = next(iter(said))
    j = run(runner, store, "label", {})  # still no detector
    assert j.state == SUCCEEDED, j.error
    assert j.counters["judged"] == 2 == j.counters["ai"]
    assert {r["sha256"] for r in rows(store)} == said
    assert all(
        r["by"] == "declared" and r["score"] is None and r["model"] == "" for r in rows(store)
    )
    assert store.origin_counts("ganyu", "fake-ai")["pending"] == 1

    # the detector arrives: only what nothing said about is scored
    det = FakeDetector((0.1,))
    runner2, _ = runner_with_detector(tmp / "c", det)
    j = run(runner2, store, "label", {})
    assert j.state == SUCCEEDED, j.error
    assert det.calls == j.counters["judged"] == j.counters["human"] == 1
    assert not store.unjudged_media("fake-ai")
    assert run(runner2, store, "label", {}).counters["judged"] == 0  # nothing left
    assert store.origin_counts("ganyu", "fake-ai") == {"ai": 2, "human": 1, "pending": 0}

    # a newer model re-judges its own verdicts; the declared ones stand
    newer = FakeDetector((0.9,), model="fake-ai-2")
    runner3, _ = runner_with_detector(tmp / "c", newer)
    assert run(runner3, store, "label", {}).counters["judged"] == newer.calls == 1
    by = {r["sha256"]: (r["by"], r["model"]) for r in rows(store)}
    assert all(by[sha] == ("declared", "") for sha in said)
    assert store.origin_counts("ganyu", "fake-ai-2") == {"ai": 3, "human": 0, "pending": 0}
    got = store.origins(list(shas), "fake-ai-2")
    assert got[flagged] == {"state": "ai", "by": "declared", "score": None}
    assert [o["by"] for sha, o in got.items() if sha not in said] == ["model"]
    print("  backlog + new model:  ok (2 declared without a model; 1 scored; the model's redone)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("origin")
        test_fold_and_declared()
        test_judged_at_download(tmp)
        test_detector_off_keeps_crawling(tmp)
        test_backlog_declared_then_model(tmp)
    print("\nall passed")
