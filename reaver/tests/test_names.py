"""Character names from Danbooru and Wikidata: resolving, merging, flagging,
and the daemon's cache. Offline: trimmed copies of real answers (2026-09-29)
served by a fake fetcher that records every URL it was asked for."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from test_jobs import make_runner

from coreflame.names import NotFound, is_risky, lang_of, lookup, title
from dawnmaker.app import State, create_app
from dawnmaker.events import EventHub
from dawnmaker.names import USER_AGENT, NameFinder

DANBOORU = {
    "autocomplete.json": [
        # a form ranked first on purpose: the base is the tag the others extend
        {"category": 4, "value": "raiden_mei_(herrscher_of_thunder)", "post_count": 1648},
        {"category": 4, "value": "raiden_mei", "post_count": 5833},
        {"category": 3, "value": "honkai_impact_3rd", "post_count": 40000},
    ],
    "wiki_pages/raiden_mei.json": {"other_names": ["雷电芽衣", "芽衣", "雷電芽衣", "RaidenMei"]},
    "tags.json": [
        {"name": "raiden_mei_(herrscher_of_thunder)", "post_count": 1648},
        {"name": "raiden_mei_(apho)", "post_count": 733},
    ],
    "wiki_pages/raiden_mei_%28herrscher_of_thunder%29.json": {
        "other_names": ["雷の律者", "雷之律者", "雷電芽衣(雷の律者)"]
    },
    # apho has no wiki page: a 404, i.e. NotFound -- an answer, not a failure
}
WIKIDATA = {
    "wbsearchentities": {
        "search": [
            {
                "id": "Q136681265",
                "label": "Raiden Mei",
                "match": {"type": "label", "language": "en", "text": "Raiden Mei"},
            }
        ]
    },
    "wbgetentities": {
        "entities": {
            "Q136681265": {
                "labels": {
                    "en": {"value": "Raiden Mei"},
                    "ja": {"value": "雷電芽衣"},
                    "ko": {"value": "라이덴 메이"},
                    "zh-hans": {"value": "雷电芽衣"},
                    "zh-hant": {"value": "雷電芽衣"},
                },
                "aliases": {},
            }
        }
    },
}


class Fake:
    def __init__(self, answers: dict, fail: Exception | None = None) -> None:
        self.answers, self.fail, self.urls = answers, fail, []

    def __call__(self, url: str):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        for key, payload in self.answers.items():
            if key in url:
                return payload
        raise NotFound(url)


def by_text(r) -> dict:
    return {s.text: s for s in r.suggestions}


def test_user_agent_is_wikimedia_acceptable() -> None:
    # Wikidata answers 403 to a User-Agent whose contact info is not a real URL
    assert USER_AGENT.startswith("Curio/") and "https://" in USER_AGENT
    print("  user agent:           ok (contact URL with scheme, per Wikimedia's robot policy)")


def test_text_helpers() -> None:
    assert [lang_of(t) for t in ("キアナ", "라이덴 메이", "雷電芽衣", "Kiana", "123")] == [
        "ja",
        "ko",
        "cjk",
        "en",
        None,
    ]
    assert [
        is_risky(t) for t in ("Kiana", "芽衣", "메이", "RaidenMei", "キアナ", "raiden mei")
    ] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert title("herrscher_of_the_void") == "Herrscher of the Void"
    print("  text helpers:         ok (script -> language; one short word is risky)")


def test_lookup_merges_both_sources() -> None:
    d, w = Fake(DANBOORU), Fake(WIKIDATA)
    r = lookup(["Raiden Mei"], d, w)
    assert (r.danbooru_tag, r.wikidata_id, r.label) == ("raiden_mei", "Q136681265", "Raiden Mei")
    assert "search%5Bquery%5D=Raiden_Mei" in d.urls[0]  # spaces separate tags on Danbooru
    s = by_text(r)
    assert s["雷電芽衣"].sources == ["danbooru", "wikidata"] and s["雷電芽衣"].lang == "ja"
    assert s["라이덴 메이"].lang == "ko" and s["라이덴 메이"].sources == ["wikidata"]
    assert s["芽衣"].risky and not s["雷電芽衣"].risky
    assert s["Raiden Mei"].posts == 5833
    forms = [x for x in r.suggestions if x.kind == "form"]
    assert [f.text for f in forms][:2] == ["Herrscher of Thunder", "雷の律者"]
    assert forms[-1].text == "Apho" and forms[-1].posts == 733  # ranked by post count
    assert r.errors == {}
    print(
        f"  merge:                ok ({len(r.suggestions)} suggestions; ko from Wikidata, forms by posts)"
    )


def test_same_name_different_entity_is_rejected() -> None:
    """A Wikidata item that shares no name with the Danbooru character is
    someone else with the same label -- dropped, not merged."""
    other = {
        "wbsearchentities": WIKIDATA["wbsearchentities"],
        "wbgetentities": {
            "entities": {"Q136681265": {"labels": {"en": {"value": "Raiden"}}, "aliases": {}}}
        },
    }
    r = lookup(["Raiden Mei"], Fake(DANBOORU), Fake(other))
    assert r.wikidata_id is None and all("wikidata" not in s.sources for s in r.suggestions)
    print("  entity check:         ok (a same-named item with no shared name is dropped)")


def test_a_failing_source_is_reported_not_fatal() -> None:
    r = lookup(["Raiden Mei"], Fake({}, fail=OSError("blocked by ISP")), Fake(WIKIDATA))
    assert "danbooru" in r.errors and "blocked" in r.errors["danbooru"]
    assert r.wikidata_id == "Q136681265" and "라이덴 메이" in by_text(r)
    print("  one source down:      ok (Danbooru error reported, Wikidata still answers)")


def test_daemon_caches_good_answers_only(tmp: Path) -> None:
    runner, cfg = make_runner(tmp / "n")
    d, w = Fake(DANBOORU), Fake(WIKIDATA)
    state = State(cfg, runner, EventHub(), "t", 5555, names=NameFinder(cfg, fetchers=(d, w)))
    client = TestClient(
        create_app(state), base_url="http://127.0.0.1:5555", headers={"Authorization": "Bearer t"}
    )
    r = client.post("/api/names", json={"queries": ["Raiden Mei", "雷電芽衣"]}).json()
    assert r["danbooru_tag"] == "raiden_mei" and any(s["lang"] == "ko" for s in r["suggestions"])
    asked = len(d.urls) + len(w.urls)
    client.post("/api/names", json={"queries": ["raiden mei ", "雷電芽衣"]})  # same, normalised
    assert len(d.urls) + len(w.urls) == asked  # served from the cache
    assert client.post("/api/names", json={"queries": ["x"] * 9}).status_code == 422

    d.fail = OSError("down")
    for _ in range(2):  # an answer with an error is not cached: each call retries
        r = client.post("/api/names", json={"queries": ["Kiana"]}).json()
    assert "danbooru" in r["errors"] and d.urls.count(d.urls[-1]) == 2
    print("  daemon /api/names:    ok (cached per queries; errors retried; max 8 queries)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("names")
        test_user_agent_is_wikimedia_acceptable()
        test_text_helpers()
        test_lookup_merges_both_sources()
        test_same_name_different_entity_is_rejected()
        test_a_failing_source_is_reported_not_fatal()
        test_daemon_caches_good_answers_only(tmp)
    print("\nall passed")
