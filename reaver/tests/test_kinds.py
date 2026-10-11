"""Image kinds: score mapping, model download + verification, labelling at
ingest and for the backlog. Offline: a fake labeler stands in for the ONNX
models, and the download is a local function returning bytes."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from test_jobs import FakeAdapters
from test_smoke import _img

from coreflame import kinds
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import build_handlers
from coreflame.jobs import FAILED, SUCCEEDED, JobRunner
from coreflame.kinds import Label, LabelError, ModelError, ModelFile
from coreflame.models import IllustRecord, Watch


class FakeLabeler:
    """Same shape as kinds.Labeler. Answers `sequence` in call order (cycling),
    so every run has both kinds that are kept and kinds that are thrown away."""

    def __init__(
        self,
        model: str = "fake-v1",
        raise_for: type[Exception] | None = None,
        sequence: tuple[str, ...] = ("photo", "illustration", "screencap"),
    ) -> None:
        self.model = model
        self.calls = 0
        self.raise_for = raise_for
        self.sequence = sequence

    def label(self, data: bytes) -> Label:
        self.calls += 1
        if self.raise_for is not None:
            raise self.raise_for("boom")
        k = self.sequence[(self.calls - 1) % len(self.sequence)]
        return Label(k, {"real": 0.9 if k == "photo" else 0.1}, self.model)


def runner_with(tmp: Path, labeler) -> tuple[JobRunner, Config]:
    cfg = Config(home=tmp / "home")

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx):
        a = FakeAdapters(cfg, ctx.store)
        a.labeler = labeler
        return a

    return JobRunner(factory, build_handlers(make)), cfg


def run(runner: JobRunner, store: Store, type_: str, params: dict):
    jid = JobRunner.submit(store, type_, params)
    runner.run_pending(store)
    return JobRunner.get(store, jid)


def stored_shas(store: Store) -> set[str]:
    return {
        r["sha256"] for r in store.conn.execute("SELECT sha256 FROM media WHERE state='stored'")
    }


def test_kind_from_scores() -> None:
    style = {"3d": 0.1, "bangumi": 0.1, "comic": 0.1, "illustration": 0.6, "not_painting": 0.1}
    assert kinds.kind_from_scores({"anime": 0.9, "real": 0.1}, style) == "illustration"
    # a real photo is a photo whatever its composition looks like
    assert kinds.kind_from_scores({"anime": 0.4, "real": 0.6}, style) == "photo"
    for top, want in [
        ("comic", "illustration"),
        ("3d", "render"),
        ("bangumi", "screencap"),
        ("not_painting", "other"),
    ]:
        s = {**{k: 0.05 for k in style}, top: 0.8}
        assert kinds.kind_from_scores({"real": 0.0}, s) == want, top
    assert set(kinds._STYLE_TO_KIND.values()) | {"photo"} == set(kinds.KINDS)
    print("  kind mapping:         ok (photo wins; comic=illustration; 3d/bangumi/other)")


def test_models_download_and_verify(tmp: Path) -> None:
    good = b"onnx-bytes"
    m = ModelFile(
        "org/repo", "abc123def456", "v1/model.onnx", hashlib.sha256(good).hexdigest(), ("a",)
    )
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return good

    kinds.ensure_models(tmp / "h", fetch, models=(m,))
    p = kinds.model_path(tmp / "h", m)
    assert p.read_bytes() == good and fetched == [m.url]
    assert "/resolve/abc123def456/" in m.url  # pinned revision, never a branch
    kinds.ensure_models(tmp / "h", fetch, models=(m,))
    assert len(fetched) == 1  # present = verified when written; no second download

    bad = ModelFile("org/other", "abc123def456", "v1/model.onnx", "0" * 64, ("a",))
    try:
        kinds.ensure_models(tmp / "h", fetch, models=(bad,))
    except ModelError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("bytes that do not match the pinned sha256 must be refused")
    assert not kinds.model_path(tmp / "h", bad).exists()  # nothing half-trusted left behind

    def offline(url: str) -> bytes:
        raise OSError("no route to host")

    try:
        kinds.ensure_models(tmp / "h2", offline, models=(m,))
    except ModelError as e:
        assert "download failed" in str(e)
    else:
        raise AssertionError("a failed download is a ModelError")
    print("  model files:          ok (pinned revision; sha256 verified; mismatch refused)")


def test_encode_matches_model_input() -> None:
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("  encode:               skipped (numpy not installed -- reaver[classify])")
        return
    x = kinds.encode(_img(1, (500, 300)))
    assert x.shape == (1, 3, 384, 384) and str(x.dtype) == "float32"
    assert float(x.min()) >= -1.0 and float(x.max()) <= 1.0
    # transparency is composited on WHITE, as the models were trained
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(buf, "PNG")
    assert float(kinds.encode(buf.getvalue()).min()) == 1.0
    try:
        kinds.encode(b"not an image")
    except LabelError:
        pass
    else:
        raise AssertionError("undecodable bytes are a LabelError, not a crash")
    print("  encode:               ok (1x3x384x384 in [-1,1]; alpha over white)")


def media_by_state(store: Store, state: str) -> list:
    return store.conn.execute("SELECT * FROM media WHERE state=?", (state,)).fetchall()


def view_files(cfg: Config) -> list[Path]:
    return sorted(p for p in (cfg.home / "by-character").rglob("*") if p.is_file())


def blob_exists(cfg: Config, sha: str) -> bool:
    return any((cfg.blob_root / sha[:2] / sha[2:4]).glob(f"{sha}*"))


def thumb_exists(cfg: Config, sha: str) -> bool:
    return (cfg.home / "thumbs" / sha[:2] / sha[2:4] / f"{sha}.webp").exists()


def test_ingest_keeps_only_illustrations_and_screencaps(tmp: Path) -> None:
    """Judged before a byte is written: a photo never becomes a blob, a
    thumbnail or a by-character name. Its row stays, rejected, url intact."""
    runner, cfg = runner_with(tmp / "i", FakeLabeler())
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED, j.error
    kept_rows, rejected = media_by_state(store, "stored"), media_by_state(store, "rejected")
    assert rejected and kept_rows
    assert j.counters["rejected"] == len(rejected) and j.counters["downloaded"] == len(kept_rows)
    assert j.counters["labeled"] == len(rejected) + len(kept_rows)
    for r in rejected:
        assert r["error"] == "photo" and r["url"] and r["sha256"]  # auditable, re-downloadable
        assert not blob_exists(cfg, r["sha256"]) and not thumb_exists(cfg, r["sha256"])
    for r in kept_rows:
        assert blob_exists(cfg, r["sha256"]) and thumb_exists(cfg, r["sha256"])
    assert len(view_files(cfg)) == len(kept_rows)
    assert set(store.kind_counts("ganyu")) <= set(kinds.KEEP)
    assert store.stats()["media_rejected"] == len(rejected)
    print(
        f"  ingest filter:        ok ({len(kept_rows)} kept, {len(rejected)} thrown away before storage)"
    )


def test_backlog_labels_then_discards(tmp: Path) -> None:
    # 1. stored before labels existed: everything kept, nothing judged
    runner, cfg = runner_with(tmp / "a", None)
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    shas = stored_shas(store)
    assert shas and store.kind_counts("ganyu") == {"unlabeled": len(shas)}
    assert len(view_files(cfg)) == len(shas)

    # 2. the label job without numpy/onnxruntime fails and says how to fix it
    j = run(runner, store, "label", {})
    assert j.state == FAILED and "reaver[classify]" in (j.error or ""), j.error

    # 3. label the backlog from disk, then throw away what the archive does not keep
    fake = FakeLabeler("fake-v1", sequence=("photo", "illustration", "render"))
    runner2, _ = runner_with(tmp / "a", fake)
    j = run(runner2, store, "label", {})
    assert j.state == SUCCEEDED, j.error
    assert j.counters["labeled"] == len(shas) == fake.calls
    gone = media_by_state(store, "rejected")
    assert gone and j.counters["removed"] == len(gone)
    assert {r["error"] for r in gone} <= {"photo", "render"}
    for r in gone:
        assert not blob_exists(cfg, r["sha256"]) and not thumb_exists(cfg, r["sha256"])
    left = stored_shas(store)
    assert left and left | {r["sha256"] for r in gone} == shas
    assert len(view_files(cfg)) == len(left)  # hardlinks outlive blobs: removed explicitly
    assert set(store.kind_counts("ganyu")) == {"illustration"}
    again = run(runner2, store, "label", {})
    assert again.counters["labeled"] == 0 and again.counters["removed"] == 0

    # 4. a label that already exists is enough to discard -- no classifier call
    sha = next(iter(left))
    store.set_kind(sha, "other", {"real": 0.1}, "fake-v1")
    calls = fake.calls
    j = run(runner2, store, "label", {})
    assert j.counters["removed"] == 1 and fake.calls == calls and not blob_exists(cfg, sha)

    # 5. a new model re-labels what is still stored, never what was thrown away
    fake2 = FakeLabeler("fake-v2", sequence=("illustration",))
    runner3, _ = runner_with(tmp / "a", fake2)
    assert run(runner3, store, "label", {}).counters["labeled"] == len(stored_shas(store))
    print(
        f"  label backlog:        ok ({len(shas)} blobs; {len(gone)} discarded with thumbs + names; "
        "no-deps job fails with the fix)"
    )


def test_kind_filter_per_character(tmp: Path) -> None:
    """Switched off for a character: what it threw away comes back (the rows
    kept their url), nothing of its is rejected again, and a cleanup skips it."""
    runner, cfg = runner_with(tmp / "k", FakeLabeler())
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    assert run(runner, store, "poll", {}).state == SUCCEEDED
    rejected = media_by_state(store, "rejected")
    stored_before = len(media_by_state(store, "stored"))
    assert rejected

    reopened = store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"], kind_filter=False))
    assert reopened == len(rejected) and not media_by_state(store, "rejected")
    assert store.watches()[0].kind_filter is False  # round-trips through the v6 column

    j = run(runner, store, "media", {})
    assert j.state == SUCCEEDED, j.error
    assert j.counters["rejected"] == 0 and j.counters["downloaded"] == len(rejected)
    assert all(blob_exists(cfg, r["sha256"]) for r in rejected)
    assert run(runner, store, "label", {}).counters["removed"] == 0
    assert len(media_by_state(store, "stored")) == stored_before + len(rejected)
    print(
        f"  per-character filter: ok (off -> {len(rejected)} re-downloaded and kept; cleanup skips it)"
    )


def test_label_failures(tmp: Path) -> None:
    # undecodable image: that image stays unlabeled, the rest carry on
    runner, cfg = runner_with(tmp / "b", FakeLabeler(raise_for=LabelError))
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    j = run(runner, store, "poll", {})
    assert j.state == SUCCEEDED and j.counters["downloaded"] > 0 and j.counters["labeled"] == 0

    # unusable classifier (download/verify failed): downloads still succeed, labelling
    # stops after the first try instead of failing every image the same way
    broken = FakeLabeler(raise_for=ModelError)
    runner2, cfg2 = runner_with(tmp / "c", broken)
    store2 = Store(cfg2.db_path)
    store2.upsert_watch(Watch(slug="ganyu", pixiv_tags=["甘雨"]))
    j = run(runner2, store2, "poll", {})
    assert j.state == SUCCEEDED, j.error
    assert j.counters["downloaded"] > 1 and broken.calls == 1
    warned = store2.conn.execute(
        "SELECT count(*) FROM job_log WHERE job_id=? AND message LIKE 'image labels off%'", (j.id,)
    ).fetchone()[0]
    assert warned == 1
    # the backlog job cannot do anything without the model, so there it IS a failure
    assert run(runner2, store2, "label", {}).state == FAILED
    print(
        "  label failures:       ok (bad image skipped; broken model: 1 warning, downloads go on)"
    )


def test_reposts_are_labelled_once(tmp: Path) -> None:
    store = Store(tmp / "r.db")
    data = _img(7, (120, 160))
    sha = hashlib.sha256(data).hexdigest()
    for eid in ("1", "2"):  # same bytes posted twice
        store.upsert_post(
            IllustRecord(
                source="twitter",
                external_id=eid,
                artist_id=f"a{eid}",
                posted_at="2026-09-01T00:00:00+00:00",
                media=[{"index": 0, "url": f"https://x/{eid}.jpg"}],
            )
        )
        store.mark_media("twitter", eid, 0, state="stored", sha=sha, nbytes=len(data), ext="jpg")
    assert [r["sha256"] for r in store.unlabeled_media("m1")] == [sha]
    store.set_kind(sha, "photo", {"real": 0.9}, "m1")
    assert store.unlabeled_media("m1") == [] and len(store.unlabeled_media("m2")) == 1
    print("  reposts:              ok (one label per sha; model change re-queues it)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("kinds")
        test_kind_from_scores()
        test_models_download_and_verify(tmp)
        test_encode_matches_model_input()
        test_ingest_keeps_only_illustrations_and_screencaps(tmp)
        test_backlog_labels_then_discards(tmp)
        test_kind_filter_per_character(tmp)
        test_label_failures(tmp)
        test_reposts_are_labelled_once(tmp)
    print("\nall passed")
