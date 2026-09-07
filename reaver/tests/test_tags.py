"""Observed-tag ranking. A three-character corpus where the franchise tag is on
everything, each character has its own exact tag, and one has an alt-costume
tag -- the ranking has to put the right one on top for the right reason."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coreflame import tags
from coreflame.db import Store
from coreflame.models import IllustRecord, Watch


def corpus(store: Store) -> None:
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    store.upsert_watch(Watch(slug="nahida", pixiv_tags=["ナヒーダ"]))
    store.upsert_watch(Watch(slug="shenhe", pixiv_tags=["申鶴"]))
    n = 0

    def post(slug, *tag_lists):
        nonlocal n
        for tl in tag_lists:
            n += 1
            store.upsert_post(
                IllustRecord(source="pixiv", external_id=str(n), artist_id="a", tags=list(tl)), slug
            )

    # ganyu: 10 posts. 原神 on all; 甘雨 on all; 甘雨(原神) on 6; 甘雨(飛花逐月) on 3; ガンユー on 1
    post(
        "ganyu",
        *[["原神", "甘雨", "甘雨(原神)"]] * 6,
        *[["原神", "甘雨", "甘雨(飛花逐月)"]] * 3,
        ["原神", "甘雨", "ガンユー"],
    )
    post("nahida", *[["原神", "ナヒーダ", "ナヒーダ(原神)"]] * 5)
    post("shenhe", *[["原神", "申鶴", "申鶴(原神)"]] * 4, ["原神", "申鶴", "申鶴（原神）"])


def test_ranking(tmp: Path) -> None:
    store = Store(tmp / "t.db")
    corpus(store)
    assert tags.rebuild(store) > 0
    rows = tags.observed(store, "ganyu")
    by = {r.tag_norm: r for r in rows}
    assert by["甘雨"].state == "watched"
    suggested = [r for r in rows if r.state == "suggested"]
    order = [r.tag_raw for r in suggested]
    # the exact character tag ranks first; the franchise tag ranks LAST
    # despite 100% share, because it is on every character
    assert order[0] == "甘雨(原神)", order
    assert order[-1] == "原神", order
    assert by["原神"].share == 1.0 and by["原神"].characters == 3
    assert by["甘雨(原神)"].score > by["甘雨(飛花逐月)"].score > by["原神"].score
    print(f"  ranking:              ok  {order}")
    print(
        f"  franchise demoted:    ok  原神 share={by['原神'].share:.0%} score={by['原神'].score:.2f} "
        f"vs 甘雨(原神) score={by['甘雨(原神)'].score:.2f}"
    )


def test_fullwidth_groups_under_one_norm(tmp: Path) -> None:
    store = Store(tmp / "f.db")
    corpus(store)
    tags.rebuild(store)
    by = {r.tag_norm: r for r in tags.observed(store, "shenhe")}
    assert by["申鶴(原神)"].posts == 5  # 4 halfwidth + 1 fullwidth
    assert by["申鶴(原神)"].tag_raw == "申鶴(原神)"  # most common raw spelling kept
    print("  fullwidth grouping:   ok (5 posts under one norm; halfwidth raw chosen)")


def test_watch_and_ignore_close_the_loop(tmp: Path) -> None:
    store = Store(tmp / "w.db")
    corpus(store)
    tags.rebuild(store)
    w = tags.set_state(store, "ganyu", "甘雨(原神)", tags.WATCHED)
    assert "甘雨(原神)" in w.pixiv_tags
    assert {x.slug: x for x in store.watches()}["ganyu"].pixiv_tags == ["甘雨", "甘雨(原神)"]
    tags.set_state(store, "ganyu", "原神", tags.IGNORED)
    tags.rebuild(store)  # ignored survives a rebuild
    by = {r.tag_norm: r for r in tags.observed(store, "ganyu")}
    assert by["甘雨(原神)"].state == "watched" and by["原神"].state == "ignored"
    print("  watch/ignore:         ok (written to watches.pixiv_tags; ignored persists)")


def test_single_character_degrades_to_share(tmp: Path) -> None:
    store = Store(tmp / "s.db")
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    for i, tl in enumerate([["原神", "甘雨", "甘雨(原神)"]] * 3 + [["原神", "甘雨"]]):
        store.upsert_post(
            IllustRecord(source="pixiv", external_id=str(i), artist_id="a", tags=tl), "ganyu"
        )
    tags.rebuild(store)
    rows = [r for r in tags.observed(store, "ganyu") if r.state == "suggested"]
    assert all(r.score > 0 for r in rows)  # not log(1)=0 everywhere
    assert rows[0].tag_raw == "原神"  # share-only; honest, can't know better
    print("  one character:        ok (scores nonzero; ranks by share, as documented)")


def test_suggest_for_new_character(tmp: Path) -> None:
    store = Store(tmp / "n.db")
    corpus(store)
    tags.rebuild(store)
    listing = [{"tags": ["原神", "刻晴", "刻晴(原神)"]}] * 7 + [
        {"tags": ["原神", "刻晴", "刻晴(霓裾翩跹)"]}
    ] * 3
    out = tags.suggest_from_listing(store, listing, exclude=["刻晴"])
    order = [t.tag_raw for t in out]
    assert order[0] == "刻晴(原神)" and order[-1] == "原神", order
    print(f"  new-character suggest: ok  {order}  (原神 demoted by corpus rarity)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("observed tags")
        test_ranking(tmp)
        test_fullwidth_groups_under_one_norm(tmp)
        test_watch_and_ignore_close_the_loop(tmp)
        test_single_character_degrades_to_share(tmp)
        test_suggest_for_new_character(tmp)
    print("\nall passed")
