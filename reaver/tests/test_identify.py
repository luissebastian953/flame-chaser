"""Naming the character in a picture: the two-tagger rule, folding a
costume/form tag to its character, identification at download (labels only,
never rejects), the label job's backlog, and the WD read shared with the
gender filter. Offline: a fake identifier answers fixed candidates instead of
the 1.25 GB of models."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from test_jobs import FakeAdapters
from test_kinds import FakeLabeler, media_by_state, run

from coreflame import identify
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import build_handlers
from coreflame.identify import Hit, Identity, decide, fold, label_of
from coreflame.jobs import SUCCEEDED, JobRunner
from coreflame.models import Watch
from coreflame.people import People

CHARS = {
    "raiden_mei",
    "raiden_mei_(herrscher_of_thunder)",
    "firefly_(honkai:_star_rail)",
    "firefly_(jepella_rebellion)_(honkai:_star_rail)",
    "iris_(mega_man)",
    "raiden_shogun",
    "kiana_kaslana",
}
COPYRIGHTS = {"honkai:_star_rail"}


def base(tag: str) -> str:
    return fold(tag, CHARS, COPYRIGHTS)


class FakeIdentifier:
    """Same shape as identify.Identifier; answers `answers` in call order
    (cycling): each answer is (wd candidates, camie candidates)."""

    model = "fake-ident"

    def __init__(self, answers: list[tuple[list, list]], model: str = "fake-ident") -> None:
        self.answers, self.calls, self.model = answers, 0, model
        self.people_seen: list[People | None] = []

    def identify(self, data: bytes, people: People | None = None) -> Identity:
        wd, camie = self.answers[self.calls % len(self.answers)]
        self.calls += 1
        self.people_seen.append(people)
        made = None if people is not None else People(1, 0, False, {"1girl": 0.9}, {}, "fake-wd")
        return Identity(decide(wd, camie, base), {"wd": wd, "camie": camie}, self.model, made)


def runner_with_identifier(tmp: Path, identifier, tagger=None) -> tuple[JobRunner, Config]:
    cfg = Config(home=tmp / "home")

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx):
        a = FakeAdapters(cfg, ctx.store)
        a.labeler = FakeLabeler(sequence=("illustration",))
        a.tagger = tagger
        a.identifier = identifier
        return a

    return JobRunner(factory, build_handlers(make)), cfg


def test_fold_and_labels() -> None:
    table = [
        ("raiden_mei_(herrscher_of_thunder)", "raiden_mei"),  # a form -> its character
        ("firefly_(jepella_rebellion)_(honkai:_star_rail)", "firefly_(honkai:_star_rail)"),
        ("firefly_(honkai:_star_rail)", "firefly_(honkai:_star_rail)"),  # franchise stays
        ("iris_(mega_man)", "iris_(mega_man)"),  # no bare `iris` character to fold to
        ("unknown_(costume)", "unknown_(costume)"),
    ]
    for tag, want in table:
        assert base(tag) == want, (tag, base(tag))
    assert label_of("firefly_(honkai:_star_rail)") == "Firefly (Honkai: Star Rail)"
    assert label_of("kiana_kaslana") == "Kiana Kaslana"
    print(f"  fold + labels:        ok ({len(table)} tags; franchise kept, form folded)")


def test_the_rule() -> None:
    def names(wd: list, camie: list) -> list[tuple[str, str]]:
        return [(h.name, h.by) for h in decide(wd, camie, base)]

    # one tagger alone, when sure
    assert names([["raiden_mei", 0.9]], []) == [("raiden_mei", "wd")]
    assert names([], [["firefly_(honkai:_star_rail)", 0.97]]) == [
        ("firefly_(honkai:_star_rail)", "camie")
    ]
    # under the sure cuts both must agree -- on the character, not the exact tag
    assert names([["raiden_mei", 0.4]], [["raiden_mei_(herrscher_of_thunder)", 0.3]]) == [
        ("raiden_mei", "both")
    ]
    # unsure and disagreeing: unidentified (Camie's Raiden Shogun lookalike case)
    assert names([["raiden_mei", 0.6]], [["raiden_shogun", 0.45]]) == []
    # one unsure vote is not enough
    assert names([["raiden_mei", 0.3]], []) == []
    # a sure name wins; the other tagger's unsure different name does not add one
    assert names([["raiden_mei", 0.95]], [["raiden_shogun", 0.3]]) == [("raiden_mei", "wd")]
    # two sure, different characters (a two-character picture): both named
    got = decide([["kiana_kaslana", 0.9]], [["raiden_mei", 0.8]], base)
    assert {h.name for h in got} == {"kiana_kaslana", "raiden_mei"}
    # the most specific tag and the higher score are kept for the character
    hit = decide([["raiden_mei", 0.9]], [["raiden_mei_(herrscher_of_thunder)", 0.95]], base)[0]
    assert hit == Hit("raiden_mei", "raiden_mei_(herrscher_of_thunder)", 0.95, "both")
    print("  rule:                 ok (sure alone, agree below, lookalike stays unidentified)")


def test_encode_matches_camie_input() -> None:
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("  encode:               skipped (numpy not installed -- reaver[classify])")
        return
    wide = Image.new("RGB", (200, 100), (255, 0, 0))
    buf = io.BytesIO()
    wide.save(buf, "PNG")
    x = identify.encode(buf.getvalue())
    assert x.shape == (1, 3, 512, 512) and str(x.dtype) == "float32"
    red = (1.0 - 0.485) / 0.229
    assert abs(float(x[0, 0, 256, 256]) - red) < 1e-4  # RGB, ImageNet-normalised
    pad = (124 / 255 - 0.485) / 0.229
    assert abs(float(x[0, 0, 10, 256]) - pad) < 1e-2  # letterboxed with the mean colour
    print("  encode:               ok (1x3x512x512, aspect kept, padded with the mean)")


def test_identified_at_download(tmp: Path) -> None:
    answers = [
        ([["raiden_mei", 0.95]], []),  # identified
        ([["raiden_mei", 0.5]], [["raiden_shogun", 0.4]]),  # unidentified
    ]
    ident = FakeIdentifier(answers)
    runner, cfg = runner_with_identifier(tmp / "a", ident)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"]))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED, j.error
    stored = media_by_state(store, "stored")
    assert stored and not media_by_state(store, "rejected")  # naming never rejects
    rows = store.conn.execute("SELECT state, model FROM image_identity").fetchall()
    assert len(rows) == ident.calls == len({r["sha256"] for r in stored})
    states = {r["state"] for r in rows}
    assert states == {"identified", "unidentified"} and {r["model"] for r in rows} == {"fake-ident"}
    named = store.conn.execute("SELECT DISTINCT name FROM image_characters").fetchall()
    assert [r["name"] for r in named] == ["raiden_mei"]
    # the WD read the identifier made is kept, so a gender filter later needs no re-tag
    assert store.conn.execute("SELECT count(*) FROM image_people").fetchone()[0] == ident.calls
    assert j.counters["identified"] == ident.calls
    print(f"  at download:          ok ({ident.calls} named or unidentified, none rejected)")


def test_crawl_rule_rejects(tmp: Path) -> None:
    """Settings › Duplicates' crawl-time rule (coreflame/trash.py): once the
    gallery knows its character, an image named as someone else is thrown
    away at download like a kind the archive does not keep."""
    answers = [([["raiden_mei", 0.95]], []), ([["raiden_shogun", 0.95]], [])]
    ident = FakeIdentifier(answers)
    runner, cfg = runner_with_identifier(tmp / "r", ident)
    cfg.cleanup_rule = {"min_score": 0.5, "other_character": True}
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"]))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED, j.error
    rejected = media_by_state(store, "rejected")
    assert rejected and all(r["error"].startswith("identity:other=raiden_shogun") for r in rejected)
    assert media_by_state(store, "stored")
    assert j.counters["rejected"] == len(rejected)
    assert len(rejected) + len(media_by_state(store, "stored")) == ident.calls
    print(f"  crawl-time rule:      ok ({len(rejected)} named as someone else, thrown away)")


def test_off_costs_nothing(tmp: Path) -> None:
    runner, cfg = runner_with_identifier(tmp / "b", None)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    assert store.conn.execute("SELECT count(*) FROM image_identity").fetchone()[0] == 0
    assert identify.make_identifier(Config(home=tmp / "c", identify_characters=False), None) is None
    print("  off:                  ok (no identifier, no rows; the Settings switch turns it off)")


def test_backlog_and_new_model(tmp: Path) -> None:
    runner, cfg = runner_with_identifier(tmp / "d", None)  # stored before identification
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    n = len({r["sha256"] for r in media_by_state(store, "stored")})
    assert n >= 2 and len(store.unidentified_media("fake-ident")) == n

    ident = FakeIdentifier([([["raiden_mei", 0.9]], [])])
    runner2, _ = runner_with_identifier(tmp / "d", ident)
    j = run(runner2, store, "label", {})
    assert j.state == SUCCEEDED, j.error
    assert j.counters["identified"] == n and not store.unidentified_media("fake-ident")
    got = store.identity_counts("mei", "fake-ident")
    assert got["counts"]["identified"] >= n and got["characters"] == [
        ("raiden_mei", got["counts"]["identified"])
    ]
    # nothing left: a second run identifies nothing
    assert run(runner2, store, "label", {}).counters["identified"] == 0
    # a newer model re-identifies everything, replacing the names
    newer = FakeIdentifier([([], [["kiana_kaslana", 0.8]])], model="fake-ident-2")
    runner3, _ = runner_with_identifier(tmp / "d", newer)
    assert run(runner3, store, "label", {}).counters["identified"] == n
    names = {r["name"] for r in store.conn.execute("SELECT name FROM image_characters")}
    assert names == {"kiana_kaslana"}
    pending = store.identity_counts("mei", "fake-ident")["counts"]["pending"]
    assert pending >= n  # counted against the old model, everything is pending again
    print(f"  backlog + new model:  ok ({n} identified from disk; a new model redoes them)")


def test_shares_the_gender_read(tmp: Path) -> None:
    """With a gender filter on, the WD read made for it is handed over -- one
    WD run per image, not two."""
    from test_people import FakeTagger

    ident = FakeIdentifier([([["raiden_mei", 0.9]], [])])
    runner, cfg = runner_with_identifier(tmp / "e", ident, tagger=FakeTagger([(1, 0)]))
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"], gender="female"))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    assert ident.calls and all(p is not None for p in ident.people_seen)
    print("  shared WD read:       ok (the gender filter's read is reused)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("identify")
        test_fold_and_labels()
        test_the_rule()
        test_encode_matches_camie_input()
        test_identified_at_download(tmp)
        test_crawl_rule_rejects(tmp)
        test_off_costs_nothing(tmp)
        test_backlog_and_new_model(tmp)
        test_shares_the_gender_read(tmp)
    print("\nall passed")
