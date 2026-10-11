"""What kind of image is this: an illustration, a photo, a 3D render, a
screencap, or something else (UI screenshots, text, graphics).

X search hands back whatever mentions a name -- soccer results, cosplay,
figure unboxings, leaderboard screenshots -- and no search term can tell a
drawing from a photo. Two small ONNX classifiers from deepghs on Hugging Face
can: `anime_real_cls` (anime vs real photo) and `anime_classification`
(illustration / comic / 3d / bangumi / not_painting). On a hand-labelled set
of 213 X posts the pair kept 71/84 illustrations and 6/129 of everything
else, at ~0.1 s per image on CPU.

The archive keeps only KEEP (illustrations and anime screencaps). Anything
else is thrown away at ingest: no blob, no thumbnail, no by-character name.
The media row stays, state `rejected` with its kind in `error` and its url,
so the call is auditable and reversible by re-downloading.

Optional: needs `numpy` + `onnxruntime` (`pip install 'reaver[classify]'`).
Without them `runtime_available()` is False and images stay unlabeled, which
the gallery shows. The model files (17 MB each) are fetched on first use from
a pinned revision and refused unless they hash to the pinned sha256.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PIL import Image

if TYPE_CHECKING:
    from .config import Config

KINDS = ("illustration", "photo", "render", "screencap", "other")
# what the archive keeps: drawings, and the character as the studio drew her.
# Photos (incl. cosplay), 3D renders and figures, screenshots/other are dropped.
KEEP = ("illustration", "screencap")
UNLABELED = "unlabeled"  # no image_kinds row yet -- kept, since nothing judged it
REAL_THRESHOLD = 0.5  # p(real) at or above this is a photo, whatever it depicts
INPUT_PX = 384

# anime_classification's labels -> ours. A comic page is still a drawing.
_STYLE_TO_KIND = {
    "illustration": "illustration",
    "comic": "illustration",
    "3d": "render",
    "bangumi": "screencap",
    "not_painting": "other",
}


@dataclass(frozen=True)
class ModelFile:
    repo: str
    revision: str  # a commit, never a branch: the bytes must not move under us
    path: str
    sha256: str
    labels: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.path}"


REAL = ModelFile(
    "deepghs/anime_real_cls",
    "097a6c1e9e62866a435810c883a45a7cb2c7077d",
    "mobilenetv3_v1.4_dist/model.onnx",
    "c02d68cc7f56dbcbcd4f41a10df190385c1f963f22c4eefb8d162869800ed3b0",
    ("anime", "real"),
)
STYLE = ModelFile(
    "deepghs/anime_classification",
    "5ee62e06f5f4cd68a1c2f3bc5dc9805e827d37df",
    "mobilenetv3_v1.5_dist/model.onnx",
    "ea8f4497b0e3ee86f43b6a6fd38884e25f960979a1debb5c4e1ee6a22e80d111",
    ("3d", "bangumi", "comic", "illustration", "not_painting"),
)
MODELS = (REAL, STYLE)
# stored beside every label; a different value here re-labels the backlog
MODEL_ID = "anime_real_cls/mobilenetv3_v1.4_dist+anime_classification/mobilenetv3_v1.5_dist"


class LabelError(RuntimeError):
    """This image could not be labelled (undecodable bytes). It stays unlabeled."""


class ModelError(RuntimeError):
    """The classifier itself is unusable: download failed or bytes did not verify."""


@dataclass(frozen=True)
class Label:
    kind: str
    scores: dict[str, float] = field(default_factory=dict)
    model: str = MODEL_ID


class Labels(Protocol):
    """What the pipeline needs; tests pass a fake with the same shape."""

    model: str

    def label(self, data: bytes) -> Label: ...


def kept(kind: str) -> bool:
    return kind in KEEP


def runtime_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def kind_from_scores(real: dict[str, float], style: dict[str, float]) -> str:
    """Photo wins first: a cosplay shoot or a soccer graphic is `real` whatever
    anime_classification thinks of its composition."""
    if real.get("real", 0.0) >= REAL_THRESHOLD:
        return "photo"
    top = max(style, key=style.__getitem__)
    return _STYLE_TO_KIND[top]


def model_path(home: Path, m: ModelFile) -> Path:
    return Path(home) / "models" / m.repo.replace("/", "--") / m.revision[:12] / m.path


def models_present(home: Path) -> bool:
    return all(model_path(home, m).exists() for m in MODELS)


def ensure_models(
    home: Path,
    fetch: Callable[[str], bytes],
    log: Callable[[str], None] | None = None,
    models: tuple[ModelFile, ...] = MODELS,
) -> None:
    """Download any missing model file, verify it, write it atomically. A file
    on disk was verified when written, so presence is enough afterwards."""
    for m in models:
        dest = model_path(home, m)
        if dest.exists():
            continue
        if log:
            log(f"downloading {m.repo}/{m.path} (first use; verified before it is used)")
        try:
            data = fetch(m.url)
        except Exception as e:
            raise ModelError(f"{m.repo}: download failed: {e}") from e
        got = hashlib.sha256(data).hexdigest()
        if got != m.sha256:
            raise ModelError(
                f"{m.repo}/{m.path}: sha256 {got[:12]}… does not match the pinned "
                f"{m.sha256[:12]}… -- refusing it"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".onnx.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)


def encode(data: bytes) -> Any:
    """Bytes -> the (1, 3, 384, 384) float32 tensor both models take: alpha
    over white, RGB, bilinear resize, [-1, 1]. Mirrors deepghs' imgutils
    (checked to 5e-7 against it); change it and the benchmark no longer holds."""
    import numpy as np

    try:
        img: Image.Image = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise LabelError(f"not an image Pillow can read: {e}") from e
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        img = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img.alpha_composite(rgba)
    img = img.convert("RGB").resize((INPUT_PX, INPUT_PX), Image.Resampling.BILINEAR)
    x = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
    return ((x - 0.5) / 0.5)[None].astype(np.float32)


class Labeler:
    """Both ONNX sessions, loaded on the first `label()` (which downloads the
    models if needed). Lives on the worker thread with the other adapters."""

    model = MODEL_ID

    def __init__(
        self,
        home: Path,
        fetch: Callable[[str], bytes],
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.home = Path(home)
        self._fetch = fetch
        self.log = log  # the job binds its own log so a first-use download is visible
        self._sessions: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._sessions is None:
            import onnxruntime as ort

            ensure_models(self.home, self._fetch, self.log)
            self._sessions = {
                m.repo: ort.InferenceSession(
                    str(model_path(self.home, m)), providers=["CPUExecutionProvider"]
                )
                for m in MODELS
            }
        return self._sessions

    def label(self, data: bytes) -> Label:
        sessions = self._load()
        x = encode(data)
        out: dict[str, dict[str, float]] = {}
        for m in MODELS:
            probs = sessions[m.repo].run(["output"], {"input": x})[0][0]
            out[m.repo] = {name: float(p) for name, p in zip(m.labels, probs, strict=True)}
        real, style = out[REAL.repo], out[STYLE.repo]
        scores = {"real": round(real["real"], 4), **{k: round(v, 4) for k, v in style.items()}}
        return Label(kind_from_scores(real, style), scores, MODEL_ID)


def model_fetcher(cfg: Config) -> Callable[[str], bytes]:
    """Downloads a model file with the configured resolver and proxy -- the
    same path every other request takes."""
    from .http import SourceClient

    resolver = None
    if cfg.resolver == "doh":
        from .net import DEFAULT_DOH, DohResolver

        resolver = DohResolver(cfg.doh_endpoints or DEFAULT_DOH)

    def fetch(url: str) -> bytes:
        with SourceClient(
            {}, rate=1.0, burst=2.0, timeout=300.0, resolver=resolver, proxy=cfg.proxy_url
        ) as client:
            return client.get(url).content

    return fetch


def make_labeler(cfg: Config, log: Callable[[str], None] | None = None) -> Labeler | None:
    """The configured labeler, or None when numpy/onnxruntime are absent."""
    if not runtime_available():
        return None
    return Labeler(cfg.home, model_fetcher(cfg), log)
