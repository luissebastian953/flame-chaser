"""The daemon's HTTP surface, in-process via TestClient. Offline."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from test_jobs import make_runner
from test_smoke import _img, fake_pixiv

from coreflame.db import Store
from coreflame.jobs import JobRunner
from coreflame.models import IllustRecord, Watch
from coreflame.thumbs import ThumbStore
from dawnmaker.app import Heartbeat, State, create_app
from dawnmaker.events import EventHub

TOKEN = "t0k3n"
PORT = 5555


def boot(tmp: Path) -> tuple[TestClient, Store, State]:
    runner, cfg = make_runner(tmp)
    hub = EventHub()
    runner.subscribers.append(hub.from_job_event)
    state = State(cfg, runner, hub, TOKEN, PORT)
    app = create_app(state)
    client = TestClient(
        app, base_url=f"http://127.0.0.1:{PORT}", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    return client, Store(cfg.db_path), state


def test_auth_layers(tmp: Path) -> None:
    client, _, _ = boot(tmp / "a")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 421
    assert client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 403
    r = client.get("/api/health", headers={"Origin": "tauri://localhost"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "tauri://localhost"
    # free space on the library disk, answered before the blob folder exists
    assert isinstance(r.json()["library_free_bytes"], int) and r.json()["library_free_bytes"] > 0
    # preflight: no token yet, must still be answered -- but only for an allowed origin
    pre = client.options(
        "/api/health",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert pre.status_code == 204
    assert "authorization" in pre.headers["access-control-allow-headers"].lower()
    assert (
        client.options("/api/health", headers={"Origin": "http://evil.example"}).status_code == 403
    )
    # vite's origin is only an origin in --dev
    assert client.get("/api/health", headers={"Origin": "http://localhost:5173"}).status_code == 403
    # EventSource can't set headers: token as a query param, on /events ONLY
    anon = TestClient(client.app, base_url=f"http://127.0.0.1:{PORT}")
    assert anon.get(f"/api/health?token={TOKEN}").status_code == 401
    assert anon.get(f"/api/events?live=false&token={TOKEN}").status_code == 200
    assert (
        anon.get(f"/api/media/{'0' * 64}/thumb?token={TOKEN}").status_code == 404
    )  # authed, no such thumb
    assert anon.get(f"/api/media/{'0' * 64}/thumb").status_code == 401
    print("  auth layers:          ok (token / host / origin; ?token= only on /events + /media)")


def test_watches_and_jobs_api(tmp: Path) -> None:
    client, store, state = boot(tmp / "b")
    r = client.post(
        "/api/watches", json={"slug": "ganyu", "pixiv_tags": ["甘雨"], "min_bookmarks": 500}
    )
    assert r.status_code == 201 and r.json()["reopened"] == 0
    r = client.patch(
        "/api/watches/ganyu", json={"slug": "ganyu", "pixiv_tags": ["甘雨"], "min_bookmarks": 100}
    )
    assert r.status_code == 200
    assert client.post("/api/jobs", json={"type": "nope"}).status_code == 400
    r = client.post(
        "/api/jobs", json={"type": "poll", "params": {"media": False, "twitter": False}}
    )
    assert r.status_code == 202
    jid = r.json()["job_id"]
    state.runner.run_pending(store)  # drain synchronously
    j = client.get(f"/api/jobs/{jid}").json()
    # min_bookmarks=100 from the PATCH: 1002 (900 bookmarks) kept, 1001 (10) skipped
    assert j["state"] == "succeeded", j["error"]
    assert j["counters"]["new_posts"] == 1 and j["counters"]["skipped"] == 1
    assert len(j["log"]) > 5
    assert client.get("/api/jobs").json()[0]["id"] == jid
    assert client.get("/api/health").json()["idle"] is True
    # a crawl becomes one job per source per character
    assert r.json()["job_ids"] == [jid] and j["lane"] == "pixiv" and j["worker"] == "pixiv"
    assert j["req_per_min"] == 0 and j["paused"] is False
    print("  watches + jobs API:   ok (PATCH applied: 1 kept, 1 skipped; job log via API)")


def test_pipeline_controls(tmp: Path) -> None:
    client, _, _ = boot(tmp / "pipe")
    client.post("/api/watches", json={"slug": "ganyu", "pixiv_tags": ["甘雨"]})
    client.post("/api/watches", json={"slug": "kafka", "pixiv_tags": ["カフカ"]})
    r = client.post("/api/jobs", json={"type": "poll", "params": {"media": False}})
    ids = r.json()["job_ids"]
    jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
    lanes = [jobs[i]["lane"] for i in ids]
    assert lanes == ["pixiv", "pixiv", "twitter", "twitter", "twitter"], lanes
    assert jobs[ids[-1]]["type"] == "timelines"
    bad = client.post("/api/jobs", json={"type": "poll", "params": {"watches": ["nobody"]}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "nothing_to_run"
    p = client.get("/api/pipeline").json()
    assert p["paused"] is False and [w["lane"] for w in p["workers"]] == ["pixiv", "twitter"]
    assert all(w["job_id"] is None for w in p["workers"])  # nothing started in this test
    keys = [b["key"] for b in p["budgets"]]
    assert keys[:3] == ["pixiv.search", "pixiv", "pixiv.pximg"] and "gallery-dl" in keys
    assert isinstance(p["req_per_min"], int)
    assert p["pause_reason"] is None and p["online"] is True
    r = client.post("/api/pipeline/pause", json={"paused": True})
    assert r.json() == {"paused": True, "pause_reason": "user"}
    p = client.get("/api/pipeline").json()
    assert p["paused"] is True and p["pause_reason"] == "user"
    client.post("/api/pipeline/pause", json={"paused": False})
    assert client.get("/api/pipeline").json()["pause_reason"] is None
    # the hold changing hands is an event (the page and the mini window
    # learn it at once); an offline hold is reported the same way
    frames = client.get("/api/events?live=false").text
    assert frames.count("event: pipeline.paused") == 2
    assert '"paused": true, "reason": "user"' in frames
    assert '"paused": false, "reason": null' in frames
    # reorder + run now
    order = client.post("/api/jobs/reorder", json={"ids": [ids[3], ids[0]]}).json()["order"]
    assert order[:2] == [ids[3], ids[0]] and sorted(order) == sorted(ids)
    assert client.post(f"/api/jobs/{ids[4]}/run-now").status_code == 202
    queued = sorted(
        (j for j in client.get("/api/jobs").json() if j["state"] == "queued"),
        key=lambda j: j["position"],
    )
    assert queued[0]["id"] == ids[4]
    assert client.post("/api/jobs/nope/run-now").status_code == 409
    # pause applies to a running job only
    r = client.post(f"/api/jobs/{ids[0]}/pause", json={"paused": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_running"
    # retry: a finished job again, as a fresh queued copy; a live one 409s
    r = client.post(f"/api/jobs/{ids[1]}/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_finished"
    assert client.post(f"/api/jobs/{ids[1]}/cancel").status_code == 202
    r = client.post(f"/api/jobs/{ids[1]}/retry")
    assert r.status_code == 202
    copy = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert copy["state"] == "queued" and copy["params"] == jobs[ids[1]]["params"]
    assert copy["lane"] == jobs[ids[1]]["lane"] and copy["id"] != ids[1]
    print(
        "  pipeline controls:    ok (5 jobs on 2 workers; pause queue; reorder; run now; retry; 409s)"
    )


def test_sse_replay_and_live(tmp: Path) -> None:
    client, store, state = boot(tmp / "c")
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    JobRunner.submit(store, "poll", {"media": False, "twitter": False, "link": False})
    state.runner.run_pending(store)
    last = state.hub.last_id
    assert last > 5
    # replay everything after event 3 -- reconnect semantics. live=false ends
    # the stream after the replay; a real EventSource stays open.
    r = client.get("/api/events?live=false", headers={"Last-Event-ID": "3"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got, ids = [], []
    for line in r.text.splitlines():
        if line.startswith("id: "):
            ids.append(int(line[4:]))
        elif line.startswith("event: "):
            got.append(line[7:])
    assert ids[0] == 4 and ids[-1] == last and ids == list(range(4, last + 1))
    # and the live path: a subscriber registered while streaming gets a fresh publish
    frames = state.hub.stream(last_id=last, live=True, keepalive=0.2)
    state.hub.publish("job.log", {"message": "live"})
    assert "event: job.log" in next(frames)
    frames.close()
    assert got[0] in ("job.stage", "job.log", "job.item", "job.progress")
    assert "job.finished" in got
    print(
        f"  SSE replay:           ok (Last-Event-ID 3 -> ids {ids[0]}..{ids[-1]}; types {sorted(set(got))})"
    )


def test_gallery_keyset_and_media(tmp: Path) -> None:
    client, store, state = boot(tmp / "d")
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    thumbs = ThumbStore(state.cfg.blob_root.parent / "thumbs")
    # 7 posts, 2 sharing a posted_at (the keyset tie case), each with a stored image
    for i in range(7):
        sha = f"{i:064x}"
        data = _img(i, (300, 400))
        rec = IllustRecord(
            source="pixiv",
            external_id=str(100 + i),
            artist_id="a",
            posted_at=f"2026-08-{20 + (i // 2):02d}T10:00:00+00:00",
            media=[{"index": 0, "url": f"https://x/{i}.png"}],
        )
        store.upsert_post(rec, "ganyu")
        state.blobs.put(data, "png")
        import hashlib

        real_sha = hashlib.sha256(data).hexdigest()
        store.mark_media(
            "pixiv", str(100 + i), 0, state="stored", sha=real_sha, nbytes=len(data), ext="png"
        )
        thumbs.make(real_sha, data)
    page1 = client.get("/api/gallery/ganyu?limit=3").json()
    assert len(page1["items"]) == 3 and page1["next_cursor"]
    page2 = client.get(f"/api/gallery/ganyu?limit=3&cursor={page1['next_cursor']}").json()
    page3 = client.get(f"/api/gallery/ganyu?limit=3&cursor={page2['next_cursor']}").json()
    ids = [it["external_id"] for it in page1["items"] + page2["items"] + page3["items"]]
    assert ids == ["106", "105", "104", "103", "102", "101", "100"] and page3["next_cursor"] is None
    assert len(set(ids)) == 7  # no dupes, no skips across the tie
    # oldest first: the same keyset walked the other way, ties included
    old1 = client.get("/api/gallery/ganyu?limit=3&order=oldest").json()
    old2 = client.get(
        f"/api/gallery/ganyu?limit=3&order=oldest&cursor={old1['next_cursor']}"
    ).json()
    old3 = client.get(
        f"/api/gallery/ganyu?limit=3&order=oldest&cursor={old2['next_cursor']}"
    ).json()
    old = [it["external_id"] for it in old1["items"] + old2["items"] + old3["items"]]
    assert old == ids[::-1] and old3["next_cursor"] is None
    bad = client.get("/api/gallery/ganyu?order=sideways")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_order"
    sha = page1["items"][0]["sha256"]
    t = client.get(f"/api/media/{sha}/thumb")
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"
    assert "immutable" in t.headers["cache-control"]
    f = client.get(f"/api/media/{sha}/full")
    assert f.status_code == 200 and len(f.content) > 100
    cards = client.get("/api/gallery").json()
    assert (
        cards[0]["slug"] == "ganyu" and cards[0]["post_count"] == 7 and cards[0]["cover_sha"] == sha
    )
    print(
        "  gallery keyset:       ok (7 rows / 3 pages, tie on posted_at handled; thumb+full+cover)"
    )


def test_gallery_kinds_filter(tmp: Path) -> None:
    """Labels hide, never delete: the filter narrows the grid, the counts feed
    the chips, and the cover skips a newer photo for an illustration."""
    import hashlib

    client, store, state = boot(tmp / "k")
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    shas: dict[str, str] = {}
    for i, kind in [(1, None), (2, "illustration"), (3, "photo")]:  # 203 is the newest
        data = _img(40 + i, (300, 400))
        store.upsert_post(
            IllustRecord(
                source="pixiv",
                external_id=str(200 + i),
                artist_id="a",
                posted_at=f"2026-09-0{i}T10:00:00+00:00",
                media=[{"index": 0, "url": f"https://x/k{i}.png"}],
            ),
            "ganyu",
        )
        state.blobs.put(data, "png")
        sha = hashlib.sha256(data).hexdigest()
        store.mark_media(
            "pixiv", str(200 + i), 0, state="stored", sha=sha, nbytes=len(data), ext="png"
        )
        if kind:
            store.set_kind(sha, kind, {"real": 0.9 if kind == "photo" else 0.1}, "m1")
        shas[str(200 + i)] = sha

    def ids(q: str) -> list[str]:
        r = client.get(f"/api/gallery/ganyu{q}")
        assert r.status_code == 200, r.text
        return [it["external_id"] for it in r.json()["items"]]

    assert ids("") == ["203", "202", "201"]  # no filter = everything, as before
    assert ids("?kinds=illustration,unlabeled") == ["202", "201"]
    assert ids("?kinds=photo") == ["203"]
    kinds_ = [it["kind"] for it in client.get("/api/gallery/ganyu").json()["items"]]
    assert kinds_ == ["photo", "illustration", None]
    for bad in ("?kinds=bogus", "?kinds=", "?kinds=photo,nope"):
        r = client.get(f"/api/gallery/ganyu{bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_kind", bad
    k = client.get("/api/gallery/ganyu/kinds").json()
    assert k["counts"] == {
        "illustration": 1,
        "photo": 1,
        "render": 0,
        "screencap": 0,
        "other": 0,
        "unlabeled": 1,
    }
    assert isinstance(k["labeler"]["available"], bool) and k["labeler"]["models"] is False
    cards = client.get("/api/gallery").json()
    assert cards[0]["cover_sha"] == shas["202"]  # newest illustration, not the newer photo
    assert cards[0]["post_count"] == 3
    assert cards[0]["artist_count"] >= 1  # distinct (source, artist) over the live posts
    # 203's only image thrown away (kinds.KEEP): the post is no longer counted or listed
    store.mark_media("pixiv", "203", 0, state="rejected", error="photo")
    assert client.get("/api/gallery").json()[0]["post_count"] == 2
    assert ids("") == ["202", "201"]
    print("  gallery kinds:        ok (filter, counts, bad_kind 400, cover, rejected not counted)")


def test_gallery_identity_filter(tmp: Path) -> None:
    """Names label, never delete: `ident` and `character` narrow the grid, the
    counts feed the chips, and post detail shows who each image is."""
    import hashlib

    from coreflame import identify
    from coreflame.identify import Hit, Identity

    client, store, state = boot(tmp / "id")
    store.upsert_watch(Watch(slug="mei", pixiv_tags=["雷電芽衣"]))
    named = {
        "301": [Hit("raiden_mei", "raiden_mei_(herrscher_of_thunder)", 0.95, "both")],
        "302": [],  # unidentified
        "303": None,  # not identified yet
        "304": [
            Hit("raiden_mei", "raiden_mei", 0.9, "wd"),
            Hit("kiana_kaslana", "kiana_kaslana", 0.8, "camie"),
        ],
    }
    for i, (eid, hits) in enumerate(named.items(), 1):
        data = _img(60 + i, (300, 400))
        store.upsert_post(
            IllustRecord(
                source="pixiv",
                external_id=eid,
                artist_id="a",
                posted_at=f"2026-09-0{i}T10:00:00+00:00",
                media=[{"index": 0, "url": f"https://x/id{i}.png"}],
            ),
            "mei",
        )
        state.blobs.put(data, "png")
        sha = hashlib.sha256(data).hexdigest()
        store.mark_media("pixiv", eid, 0, state="stored", sha=sha, nbytes=len(data), ext="png")
        if hits is not None:
            store.set_identity(sha, Identity(hits, {"wd": [], "camie": []}, identify.IDENTIFIER_ID))

    def ids(q: str) -> list[str]:
        r = client.get(f"/api/gallery/mei{q}")
        assert r.status_code == 200, r.text
        return [it["external_id"] for it in r.json()["items"]]

    assert ids("") == ["304", "303", "302", "301"]
    assert ids("?ident=identified") == ["304", "301"]
    assert ids("?ident=unidentified,pending") == ["303", "302"]
    assert ids("?character=kiana_kaslana") == ["304"]
    assert ids("?character=raiden_mei&ident=identified") == ["304", "301"]
    states = [it["identity"] for it in client.get("/api/gallery/mei").json()["items"]]
    assert states == ["identified", "pending", "unidentified", "identified"]
    for bad in ("?ident=bogus", "?ident=", "?ident=identified,nope"):
        r = client.get(f"/api/gallery/mei{bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_ident", bad

    c = client.get("/api/gallery/mei/characters").json()
    assert c["counts"] == {"identified": 2, "unidentified": 1, "pending": 1}
    assert c["characters"] == [
        {"name": "raiden_mei", "label": "Raiden Mei", "count": 2},
        {"name": "kiana_kaslana", "label": "Kiana Kaslana", "count": 1},
    ]
    assert c["identifier"]["enabled"] is True and "models" in c["identifier"]

    d = client.get("/api/posts/pixiv/301").json()
    who = d["media"][0]["identity"]
    assert who["state"] == "identified" and who["characters"][0]["label"] == "Raiden Mei"
    assert who["characters"][0]["tag"] == "raiden_mei_(herrscher_of_thunder)"
    assert client.get("/api/posts/pixiv/303").json()["media"][0]["identity"] is None

    # the Settings switch round-trips through /api/config
    r = client.put("/api/config", json={"identify_characters": False})
    assert r.status_code == 200 and r.json()["identify_characters"] is False
    assert client.get("/api/gallery/mei/characters").json()["identifier"]["enabled"] is False
    print("  gallery identity:     ok (ident + character filters, counts, detail, switch)")


def test_gallery_origin_filter(tmp: Path) -> None:
    """AI-made or by hand (coreflame/origin.py) labels, never deletes:
    `origin` narrows the grid, the counts feed the chips, By tag selects
    with `sel_origin`, and post detail says how each image was made."""
    import hashlib

    from coreflame import origin
    from coreflame.origin import Origin

    client, store, state = boot(tmp / "origin")
    store.upsert_watch(Watch(slug="ff", pixiv_tags=["ホタル"]))
    made = {
        "401": Origin("ai", "declared"),
        "402": Origin("human", "model", 0.03, origin.DETECTOR_ID),
        "403": None,  # not judged yet
        "404": Origin("ai", "model", 0.98, "older-model"),  # stale: reads as pending
    }
    for i, (eid, o) in enumerate(made.items(), 1):
        data = _img(80 + i, (300, 400))
        store.upsert_post(
            IllustRecord(
                source="pixiv",
                external_id=eid,
                artist_id="a",
                posted_at=f"2026-09-1{i}T10:00:00+00:00",
                media=[{"index": 0, "url": f"https://x/og{i}.png"}],
            ),
            "ff",
        )
        state.blobs.put(data, "png")
        sha = hashlib.sha256(data).hexdigest()
        store.mark_media("pixiv", eid, 0, state="stored", sha=sha, nbytes=len(data), ext="png")
        if o is not None:
            store.set_origin(sha, o)

    def ids(q: str) -> list[str]:
        r = client.get(f"/api/gallery/ff{q}")
        assert r.status_code == 200, r.text
        return [it["external_id"] for it in r.json()["items"]]

    assert ids("") == ["404", "403", "402", "401"]
    assert ids("?origin=ai") == ["401"]
    assert ids("?origin=human,pending") == ["404", "403", "402"]
    assert ids("?origin=pending&ident=pending") == ["404", "403"]
    items = client.get("/api/gallery/ff").json()["items"]
    assert [it["origin"] for it in items] == ["pending", "pending", "human", "ai"]
    assert [it["origin_by"] for it in items] == [None, None, "model", "declared"]
    for bad in ("?origin=bogus", "?origin=", "?origin=ai,nope"):
        r = client.get(f"/api/gallery/ff{bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_origin", bad

    c = client.get("/api/gallery/ff/origins").json()
    assert c["counts"] == {"ai": 1, "human": 1, "pending": 2}
    assert set(c["detector"]) == {"available", "models"}

    sel = client.get("/api/gallery/ff/images?sel_origin=pending").json()
    assert len(sel["shas"]) == 2
    assert len(client.get("/api/gallery/ff/images?origin=ai&sel_origin=ai").json()["shas"]) == 1
    assert client.get("/api/gallery/ff/images?sel_origin=nope").status_code == 400

    d = client.get("/api/posts/pixiv/401").json()
    assert d["media"][0]["origin"] == {"state": "ai", "by": "declared", "score": None}
    assert client.get("/api/posts/pixiv/402").json()["media"][0]["origin"]["score"] == 0.03
    assert client.get("/api/posts/pixiv/403").json()["media"][0]["origin"] is None
    assert client.get("/api/posts/pixiv/404").json()["media"][0]["origin"] is None  # stale
    print("  gallery origin:       ok (filter, counts, By tag term, detail)")


def test_watch_target_and_kind_filter(tmp: Path) -> None:
    client, _, _ = boot(tmp / "w")
    body = {"slug": "mei", "match_terms": ["raiden mei"], "sources": ["twitter"]}
    w = client.post("/api/watches", json=body).json()
    assert (w["target"], w["kind_filter"]) == (100, True)  # defaults
    w = client.patch("/api/watches/mei", json={**body, "target": 300, "kind_filter": False}).json()
    assert (w["target"], w["kind_filter"]) == (300, False)
    listed = client.get("/api/watches").json()[0]
    assert (listed["target"], listed["kind_filter"]) == (300, False)
    for bad in (0, 1001):
        assert client.patch("/api/watches/mei", json={**body, "target": bad}).status_code == 422
    print("  watch target/filter:  ok (defaults 100/on, round-trip, 1..1000 enforced)")


def test_post_detail_links_cross_source(tmp: Path) -> None:
    client, store, st = boot(tmp / "e")

    def state_of(_c: TestClient) -> State:
        return st

    store.upsert_post(
        IllustRecord(
            source="pixiv",
            external_id="1",
            artist_id="a",
            artist_handle="h",
            permalink="https://www.pixiv.net/artworks/1",
            media=[{"index": 0, "url": "https://x/a.png"}],
        )
    )
    store.mark_media("pixiv", "1", 0, state="stored", sha="ab" * 32, nbytes=10, ext="png")
    store.upsert_post(
        IllustRecord(
            source="twitter",
            external_id="9",
            artist_id="9",
            artist_handle="h",
            permalink="https://x.com/h/status/9",
            media=[{"index": 0, "url": "https://pbs/b.jpg"}],
        )
    )
    store.mark_media(
        "twitter", "9", 0, state="dupe", sha="cd" * 32, dupe_of="ab" * 32, error="phash d=2"
    )
    # a second X image in the same tweet, stored on its own
    store.conn.execute(
        """INSERT INTO media(source,external_id,idx,url,state,sha256,ext,bytes,width,height)
           VALUES('twitter','9',1,'https://pbs/c.jpg?name=orig','stored',?, 'jpg',5,10,20)""",
        ("ef" * 32,),
    )
    store.conn.commit()
    d = client.get("/api/posts/twitter/9").json()
    assert (
        d["linked"]
        and d["linked"][0]["source"] == "pixiv"
        and d["linked"][0]["reason"] == "phash d=2"
    )
    # the linked post comes with its own images, handle and permalink
    lk = d["linked"][0]
    assert lk["artist_handle"] == "h" and lk["permalink"].endswith("/artworks/1")
    assert [m["idx"] for m in lk["media"]] == [0] and lk["media"][0]["sha256"] == "ab" * 32
    # the dupe row has no blob (path None) and says whose it is; variants are derived
    assert d["media"][0]["path"] is None and d["media"][0]["dupe_of"] == "ab" * 32
    assert d["media"][1]["source_variant"] == "orig" and d["media"][1]["path"] is None
    d2 = client.get("/api/posts/pixiv/1").json()
    assert d2["linked"] and d2["linked"][0]["source"] == "twitter"
    assert [m["state"] for m in d2["linked"][0]["media"]] == ["dupe", "stored"]
    assert len(d2["linked"]) == 1  # one entry per post, not per image
    # a stored blob on disk is revealed by its absolute path
    blob = state_of(client).blobs.path_for("ab" * 32, "png")
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"x")
    d2 = client.get("/api/posts/pixiv/1").json()
    assert d2["media"][0]["path"] == str(blob)
    print("  post detail links:    ok (X dupe -> pixiv original, and back; linked media, paths)")


def test_delete_and_trash_api(tmp: Path) -> None:
    """The gallery's deletion routes: selection lists by term, the Smart
    criteria, preview, delete to trash (all needs the name typed), undo,
    the trash summary and purge, the crawl-time rule in config."""
    import hashlib

    from coreflame.identify import IDENTIFIER_ID, Hit, Identity
    from coreflame.phash import dhash

    client, store, state = boot(tmp / "t")
    store.upsert_watch(Watch(slug="firefly", label="Firefly", pixiv_tags=["流螢"]))
    thumbs = ThumbStore(state.cfg.blob_root.parent / "thumbs")
    shas = []
    for i in range(4):
        data = _img(10 + i, (300, 400))
        sha = hashlib.sha256(data).hexdigest()
        rec = IllustRecord(
            source="pixiv" if i < 3 else "twitter",
            external_id=str(200 + i),
            artist_id="a" if i < 2 else "b",
            artist_name="Alpha" if i < 2 else "Beta",
            posted_at=f"2026-08-{20 + i:02d}T10:00:00+00:00",
            tags=["firefly", "fanart"] if i % 2 == 0 else ["firefly"],
            media=[{"index": 0, "url": f"https://x/{i}.png"}],
        )
        store.upsert_post(rec, "firefly")
        state.blobs.put(data, "png")
        store.mark_media(
            rec.source,
            rec.external_id,
            0,
            state="stored",
            sha=sha,
            phash=dhash(data),
            nbytes=len(data),
            ext="png",
        )
        thumbs.make(sha, data)
        shas.append(sha)
    fire = "firefly_(honkai:_star_rail)"
    store.set_identity(shas[0], Identity([Hit(fire, fire, 0.9, "camie")], model=IDENTIFIER_ID))
    store.set_identity(shas[1], Identity([Hit(fire, fire, 0.3, "camie")], model=IDENTIFIER_ID))
    store.set_identity(shas[2], Identity([Hit("sam", "sam", 0.8, "camie")], model=IDENTIFIER_ID))

    # selection lists: by tag, by artist, by character, everything
    listed = client.get("/api/gallery/firefly/images").json()
    every = listed["shas"]
    assert every == shas[::-1]
    assert listed["sources"][shas[3]] == "twitter" and listed["sources"][shas[0]] == "pixiv"
    assert client.get("/api/gallery/firefly/images?tag=fanart").json()["shas"] == [shas[2], shas[0]]
    assert client.get("/api/gallery/firefly/images?artist=pixiv:a").json()["shas"] == [
        shas[1],
        shas[0],
    ]
    assert client.get("/api/gallery/firefly/images?sel_character=sam").json()["shas"] == [shas[2]]
    assert client.get("/api/gallery/firefly/images?source=twitter").json()["shas"] == [shas[3]]
    assert client.get("/api/gallery/firefly/images?sel_kind=nope").status_code == 400
    artists = client.get("/api/gallery/firefly/artists").json()
    # one row per (source, artist): Beta posts on both sites
    assert [(a["name"], a["count"]) for a in artists] == [("Alpha", 2), ("Beta", 1), ("Beta", 1)]
    assert artists[0]["source"] == "pixiv" and artists[0]["artist_id"] == "a"

    # smart criteria and the review card
    smart = client.post("/api/gallery/firefly/smart", json={"min_score": 0.5}).json()
    assert smart["primary"] == fire and smart["cutoff"] == 0.5 and smart["rule"] is None
    kinds = {m["sha256"]: m["reasons"][0]["kind"] for m in smart["matches"]}
    assert kinds == {shas[1]: "score", shas[2]: "other"}
    assert smart["counts"]["score"] == 1 and smart["characters"][0]["name"] == "sam"
    review = client.get("/api/gallery/review").json()
    assert review["total"] == 2 and review["characters"][0]["slug"] == "firefly"

    # preview, then delete two to trash
    pv = client.post("/api/gallery/firefly/delete/preview", json={"shas": shas[:2]}).json()
    assert pv["images"] == 2 and pv["posts"]["forget"] == 2 and pv["whole"] is False
    assert pv["trash"]["count"] == 0
    r = client.post("/api/gallery/firefly/delete", json={"shas": shas[:2], "mode": "image"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["images"] == 2 and got["forgotten"] == 2 and got["batch_id"]
    assert len(client.get("/api/gallery/firefly").json()["items"]) == 2
    assert client.get("/api/gallery").json()[0]["post_count"] == 2
    assert client.get(f"/api/media/{shas[0]}/full").status_code == 404
    assert client.get(f"/api/media/{shas[0]}/thumb").status_code == 200  # kept for undo
    tr = client.get("/api/trash").json()
    assert tr["count"] == 2 and tr["bytes"] > 0 and tr["days"] == 30
    assert client.post("/api/gallery/firefly/delete", json={"shas": []}).status_code == 400

    # undo
    back = client.post(f"/api/trash/{got['batch_id']}/restore").json()
    assert back["images"] == 2 and back["posts"] == 2
    assert len(client.get("/api/gallery/firefly").json()["items"]) == 4
    assert client.get(f"/api/media/{shas[0]}/full").status_code == 200
    assert client.post("/api/trash/nope/restore").status_code == 404

    # all: the name must be typed back; images only, the character stays
    bad = client.post(
        "/api/gallery/firefly/delete", json={"shas": every, "mode": "all", "confirm": "Fire"}
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "confirm_mismatch"
    ok = client.post(
        "/api/gallery/firefly/delete",
        json={"shas": every, "mode": "all", "confirm": "Firefly", "forget": False},
    ).json()
    assert ok["images"] == 4 and ok["forgotten"] == 0
    assert client.get("/api/gallery/firefly").json()["items"] == []
    assert client.get("/api/watches").json()[0]["slug"] == "firefly"
    assert client.post("/api/trash/purge", json={"everything": True}).json()["images"] == 4
    assert client.get("/api/trash").json()["count"] == 0

    # the crawl-time rule lives in config, off by default, cleared with active=false
    assert client.get("/api/config").json()["cleanup_rule"] is None
    c = client.put(
        "/api/config", json={"cleanup_rule": {"min_score": 0.42, "other_character": True}}
    ).json()
    assert c["cleanup_rule"] == {"min_score": 0.42, "other_character": True}
    assert client.post("/api/gallery/firefly/smart", json={}).json()["rule"]["min_score"] == 0.42
    c = client.put("/api/config", json={"cleanup_rule": {"active": False}}).json()
    assert c["cleanup_rule"] is None
    print(
        "  delete + trash:       ok (terms, smart, preview, trash, undo, all+confirm, purge, rule)"
    )


def test_bundle_api(tmp: Path) -> None:
    """Export is a job on the `any` lane; inspect names the conflicts; import
    needs the queue paused and empty, merges, and hands the ui state back."""
    import hashlib

    from coreflame.phash import dhash

    client, store, state = boot(tmp / "bundle")
    store.upsert_watch(Watch(slug="firefly", label="Firefly", pixiv_tags=["流螢"]))
    thumbs = ThumbStore(state.cfg.blob_root.parent / "thumbs")
    for i in range(2):
        data = _img(30 + i, (200, 260))
        sha = hashlib.sha256(data).hexdigest()
        rec = IllustRecord(
            source="pixiv",
            external_id=str(300 + i),
            artist_id="a",
            artist_name="A",
            posted_at="2026-09-01T00:00:00+00:00",
            media=[{"index": 0, "url": f"https://x/{i}.png"}],
        )
        store.upsert_post(rec, "firefly")
        state.blobs.put(data, "png")
        thumbs.make(sha, data)
        store.mark_media(
            "pixiv", str(300 + i), 0, state="stored", sha=sha, phash=dhash(data), ext="png"
        )

    # export: the path gets the format's extension; the ui blob rides along
    out = tmp / "bundle" / "out" / "mine"
    out.parent.mkdir(parents=True)
    r = client.post(
        "/api/bundle/export",
        json={"path": str(out), "ui": {"curio.theme.v3": {"preset": "graphite"}}},
    )
    assert r.status_code == 202, r.text
    jid, path = r.json()["job_id"], r.json()["path"]
    assert path.endswith("mine.curio")
    job = client.get(f"/api/jobs/{jid}").json()
    assert job["type"] == "export" and job["lane"] == "any"
    assert state.runner.run_pending(store) == 1
    job = client.get(f"/api/jobs/{jid}").json()
    assert job["state"] == "succeeded", job["error"]
    assert job["counters"]["images"] == 2 and Path(path).exists()
    assert job["counters"]["entries"] == 8 and job["counters"]["posts"] == 2
    # Settings › Storage: the trees, the db and the disk
    u = client.get("/api/storage").json()
    assert u["blobs"]["files"] == 2 and u["thumbs"]["files"] == 2 and u["db_bytes"] > 0
    assert (
        u["disk"]["total"] > u["disk"]["free"] > 0
        and u["disk"]["library"] == u["blobs"]["bytes"] + u["thumbs"]["bytes"]
    )
    assert u["schema_version"] >= 12
    assert "verify" in [e["message"] for e in job["log"] if e["kind"] == "stage"]
    # a folder that does not exist is refused up front, not by a failed job
    bad = client.post("/api/bundle/export", json={"path": str(tmp / "nope" / "x")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "no_folder"
    # no path (browser mode): under ~/.reaver/exports
    r = client.post("/api/bundle/export", json={"format": "zip", "images": False})
    assert r.json()["path"].startswith(str(state.cfg.home / "exports")) and r.json()[
        "path"
    ].endswith(".zip")
    state.runner.run_pending(store)

    # inspect: the same character on both sides, their config differs
    client2, store2, _ = boot(tmp / "bundle2")
    store2.upsert_watch(Watch(slug="firefly", label="Firefly", pixiv_tags=["流螢", "ホタル"]))
    r = client2.post("/api/bundle/inspect", json={"path": path})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["counts"]["images"] == 2 and info["characters"][0]["new"] is False
    assert [c["slug"] for c in info["conflicts"]] == ["firefly"]
    assert (
        client2.post("/api/bundle/inspect", json={"path": str(tmp / "nope.curio")}).status_code
        == 400
    )
    assert (
        client2.post("/api/bundle/inspect", json={"path": str(tmp / "nope.curio")}).json()["error"][
            "code"
        ]
        == "no_file"
    )

    # import: refused while the queue runs; then merge with the ui state handed back
    body = {"path": path, "settings": "take", "characters": {"firefly": "merge"}}
    r = client2.post("/api/bundle/import", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
    client2.post("/api/pipeline/pause", json={"paused": True})
    r = client2.post("/api/bundle/import", json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["mode"] == "merge" and res["placed"] == 2 and res["damaged"] == []
    assert res["ui"] == {"curio.theme.v3": {"preset": "graphite"}}
    w = client2.get("/api/watches").json()[0]
    assert w["pixiv_tags"] == ["流螢", "ホタル"]
    assert client2.get("/api/gallery").json()[0]["post_count"] == 2
    # the same file again changes nothing
    res = client2.post("/api/bundle/import", json=body).json()
    assert res["placed"] == 0 and res["posts"] == 0
    print("  bundle api:           ok (export job, inspect conflicts, import gated + merged)")


def test_serving_when_the_handshake_arrives(tmp: Path) -> None:
    """The shell asks for /api/health the moment it reads the handshake; the port
    must already be listening then, or the UI shows "daemon unreachable"."""
    import json
    import os
    import subprocess
    import urllib.request

    home = tmp / "spawn"
    home.mkdir(parents=True)
    env = {**os.environ, "REAVER_HOME": str(home)}
    root = Path(__file__).resolve().parents[1]
    p = subprocess.Popen(
        [sys.executable, "-m", "dawnmaker", "--no-heartbeat"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        line = p.stdout.readline() if p.stdout else ""
        assert line.startswith("DAWNMAKER_READY "), line
        hs = json.loads(line.split(" ", 1)[1])
        req = urllib.request.Request(
            f"http://127.0.0.1:{hs['port']}/api/health",
            headers={"Authorization": f"Bearer {hs['token']}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # no retry, no sleep
            assert r.status == 200 and json.loads(r.read())["ok"] is True
    finally:
        p.terminate()
        p.wait(timeout=20)
    print("  handshake → serving:  ok (health answers the instant the port is announced)")


def test_hub_close_ends_live_streams() -> None:
    hub = EventHub()
    frames = hub.stream(live=True, keepalive=5.0)
    hub.publish("job.log", {"message": "one"})
    assert "one" in next(frames)
    t0 = time.monotonic()
    hub.close()
    assert list(frames) == []  # ends at once, not after a keepalive
    assert time.monotonic() - t0 < 1.0
    assert list(hub.stream(last_id=hub.last_id, live=True)) == []  # opened after close: ends too
    print("  hub close: ok (a live stream ends the instant the daemon decides to exit)")


def test_heartbeat_grace() -> None:
    hb = Heartbeat(timeout=30)
    hb.last = time.monotonic() - 31
    assert not hb.expired()  # first silence: a sleep or a throttled shell -> one grace period
    assert not hb.expired()  # still inside it (15 s)
    hb.last = time.monotonic() - 31  # the grace passed in silence
    assert hb.expired()  # dead
    hb.beat()  # a beat resets the grant
    hb.last = time.monotonic() - 3600
    assert not hb.expired()  # an hour asleep is still one grace period, not a death
    hb.beat()
    assert not hb.expired()
    print("  heartbeat grace: ok (first silence is graced, a second one exits, a beat resets)")


def test_config_rejects_sync_folder(tmp: Path) -> None:
    client, _, _ = boot(tmp / "f")
    r = client.put("/api/config", json={"library_root": "/Users/x/Dropbox/art"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "sync_folder"
    assert client.get("/api/config").json()["pixiv_session"] is False  # redacted to bool
    print("  config guard:         ok (sync folder refused; secrets redacted)")


def test_probe_and_preview(tmp: Path) -> None:
    """The character form's validation: one search page per tag, cached;
    preview thumbs only for ids a probe returned; fullwidth never spends."""
    from dawnmaker.probe import Prober

    runner, cfg = make_runner(tmp)
    fake = fake_pixiv()
    calls: list[str] = []
    real_get_json = fake.client.get_json

    def counting(url, **kw):
        calls.append(url)
        return real_get_json(url, **kw)

    fake.client.get_json = counting  # type: ignore[assignment]
    fake.fetch_media = lambda url, referer=None: _img(7, (250, 250))  # type: ignore[method-assign]
    hub = EventHub()
    state = State(cfg, runner, hub, TOKEN, PORT, prober=Prober(cfg, pixiv=fake))
    client = TestClient(
        create_app(state),
        base_url=f"http://127.0.0.1:{PORT}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    r = client.post("/api/pixiv/probe", json={"tags": ["甘雨", "甘雨（原神）"]}).json()
    good, bad = r["tags"]
    assert good["ok"] and good["total"] == 2 and good["warning"] is None
    assert not bad["ok"] and "fullwidth" in bad["warning"]
    assert len(calls) == 1, "fullwidth tag must not spend a request"
    assert [p["illust_id"] for p in r["preview"]] == ["1002", "1001"]
    assert r["estimate"]["artworks"] == 2 and r["estimate"]["seconds"] >= 0
    assert all(s["tag_norm"] != "甘雨" for s in r["suggestions"]), "the probed tag is excluded"

    # cached: a second probe of the same tag is free
    client.post("/api/pixiv/probe", json={"tags": ["甘雨"]})
    assert len(calls) == 1

    # preview thumbs: probed id ok (and ?token= works for <img>), unknown id 404
    anon = TestClient(client.app, base_url=f"http://127.0.0.1:{PORT}")
    t = anon.get(f"/api/preview/1002/thumb?token={TOKEN}")
    assert t.status_code == 200 and t.headers["content-type"].startswith("image/")
    assert anon.get(f"/api/preview/999999/thumb?token={TOKEN}").status_code == 404
    assert anon.get("/api/preview/1002/thumb").status_code == 401
    print("  probe + preview:      ok (1 request / tag, cached, fullwidth free, thumbs gated)")


def test_auth_sessions(tmp: Path) -> None:
    """Sessions: a pixiv cookie is verified by one search before it is kept,
    stored 0600 outside config.json, never echoed; X cookies become a
    gallery-dl cookies.txt; the crawl refuses to start unauthenticated."""
    import json
    import stat

    import httpx

    from dawnmaker import auth as authmod

    class FakePx:
        def __init__(self, sessid):
            self.sessid = sessid

        def probe_tag(self, tag, include_r18=False):
            if self.sessid != "77_goodtoken00000000000000":
                req = httpx.Request("GET", "https://www.pixiv.net/ajax/search/artworks/x")
                raise httpx.HTTPStatusError(
                    "401", request=req, response=httpx.Response(401, request=req)
                )
            return 1, []

        def close(self):
            pass

    authmod.make_pixiv = lambda cfg, sink=None: FakePx(cfg.pixiv_php_sessid)  # type: ignore[assignment]
    client, _store, state = boot(tmp)
    assert client.get("/api/sources/status").json()["pixiv"]["authed"] is False

    # bad shape -> 400, rejected by pixiv -> 401, nothing stored either way
    assert client.post("/api/auth/pixiv", json={"php_sessid": "nope"}).status_code == 400
    r = client.post("/api/auth/pixiv", json={"php_sessid": "77_badtoken000000000000000"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_rejected"
    assert not (state.cfg.home / "secrets.json").exists()

    r = client.post("/api/auth/pixiv", json={"php_sessid": "PHPSESSID=77_goodtoken00000000000000"})
    assert r.status_code == 200
    px = r.json()["pixiv"]
    assert px == {**px, "authed": True, "user_id": "77", "verified": True}
    sp = state.cfg.home / "secrets.json"
    assert stat.S_IMODE(sp.stat().st_mode) == 0o600
    assert "goodtoken" in sp.read_text()
    assert "goodtoken" not in json.dumps(client.get("/api/config").json())
    state.cfg.save()
    assert "goodtoken" not in (state.cfg.home / "config.json").read_text()

    # X: cookies.txt written for gallery-dl, 0600, config points at it
    r = client.post("/api/auth/twitter", json={"auth_token": "a" * 40, "ct0": "b" * 32})
    assert r.status_code == 200 and r.json()["twitter"]["authed"] is True
    ck = state.cfg.home / "twitter-cookies.txt"
    assert stat.S_IMODE(ck.stat().st_mode) == 0o600 and ".x.com\tTRUE" in ck.read_text()
    assert client.delete("/api/auth/twitter").status_code == 204 and not ck.exists()

    assert client.delete("/api/auth/pixiv").status_code == 204
    assert client.get("/api/sources/status").json()["pixiv"]["authed"] is False
    print(
        "  auth sessions:        ok (verify-before-store, 0600 secrets, never echoed, X cookies.txt)"
    )


def test_net_speed(tmp: Path) -> None:
    """The rail's signal: GET is the last answer without a request, POST measures
    (full = with upload), a network-settings save makes the next probe use the new
    path."""
    import httpx
    from test_speed import Tick, fake_transport

    from coreflame import speed
    from dawnmaker.speed import SpeedMeter

    runner, cfg = make_runner(tmp)
    transport, calls = fake_transport()
    meter = SpeedMeter(
        cfg,
        client=httpx.Client(transport=transport),
        connection=lambda: speed.Connection("wifi", "Curio-5G"),
        clock=Tick(0.25),
    )
    state = State(cfg, runner, EventHub(), TOKEN, PORT, speed=meter)
    client = TestClient(
        create_app(state),
        base_url=f"http://127.0.0.1:{PORT}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    r = client.get("/api/net/speed").json()
    assert r["measured_at"] is None and r["online"] is False and calls == []
    assert r["connection"]["ssid"] == "Curio-5G" and r["samples"] == {"download": [], "upload": []}

    r = client.post("/api/net/speed", json={"full": True}).json()
    assert r["online"] and r["download_mbps"] > 0 and r["upload_mbps"] > 0 and r["latency_ms"] > 0
    assert r["server"]["location"] == "Singapore" and r["connection"]["asn"] == "AS4761"
    assert r["samples"]["download"] and r["samples"]["upload"] and r["testing"] is False
    assert client.get("/api/net/speed").json()["measured_at"] == r["measured_at"]

    assert client.put("/api/config", json={"resolver": "system"}).status_code == 200
    assert meter._client is None  # a fresh client on the next probe
    print("  net speed:            ok (GET = last answer, POST measures, settings save resets)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("dawnmaker")
        test_auth_layers(tmp)
        test_watches_and_jobs_api(tmp)
        test_pipeline_controls(tmp)
        test_sse_replay_and_live(tmp)
        test_gallery_keyset_and_media(tmp)
        test_gallery_kinds_filter(tmp)
        test_gallery_identity_filter(tmp)
        test_gallery_origin_filter(tmp)
        test_watch_target_and_kind_filter(tmp)
        test_post_detail_links_cross_source(tmp)
        test_delete_and_trash_api(tmp)
        test_bundle_api(tmp)
        test_serving_when_the_handshake_arrives(tmp)
        test_hub_close_ends_live_streams()
        test_heartbeat_grace()
        test_config_rejects_sync_folder(tmp)
        test_probe_and_preview(tmp / "probe")
        test_auth_sessions(tmp / "auth")
        test_net_speed(tmp / "speed")
    print("\nall passed")
