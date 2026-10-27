"""How an image was made: by hand, or by AI.

Three signals, trusted in this order, and the first that speaks decides:

1. **Declared.** pixiv has made artists flag AI work since October 2022:
   `aiType` on every artwork (2 = AI-generated; 1 = not; 0 = never said).
   It is already in `source_meta.ai_type` (sources/specs.py).
2. **Tags.** On X there is no flag, but AI posters tag their work so the
   AI crowd finds it: #AIイラスト, #AIart, #NovelAI, #stablediffusion ...
   The post's tags are matched against AI_TAGS after the same folding
   `tag_norm` gets, plus the fillers and variation selectors people pad
   hashtags with (`AIart️️` with twenty U+FE0F is still #AIart).
3. **The model.** `deepghs/anime_ai_check` (MIT), the distilled
   mobilenetv3: 95.65% on its own test set, 17 MB, ~0.03 s per image on CPU,
   the same 384 px encoding as kinds.py. Measured 2026-10-27 on this
   archive's X crawl: 74% of the 266 images whose post carried an AI tag
   score p(ai) >= 0.5, and the undeclared ones split 42% / 58% with a deep
   valley in the middle - which, by eye, is the archive's real share of
   undeclared diffusion art. Its author says it is for reference only; the
   label is shown with how it was reached, and the score is stored so the
   threshold can move without re-running it.

Nothing is removed: the origin only labels, like a character's name
(identify.py). A declared verdict never goes stale; a model verdict does
when DETECTOR_ID changes, and the `label` job re-judges it. Optional like
every classifier: without numpy + onnxruntime only declared and tagged
images get a label; the rest stay pending, which the gallery shows.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .kinds import (
    ModelFile,
    encode,
    ensure_models,
    model_fetcher,
    model_path,
    runtime_available,
)
from .models import norm_tag

if TYPE_CHECKING:
    from .config import Config

ORIGINS = ("ai", "human")
PENDING = "pending"  # no verdict yet, or one from an older model
STATES = (*ORIGINS, PENDING)  # the gallery's `origin` filter
BY = ("declared", "tags", "model")
PIXIV_AI = 2  # aiType: 0 unknown, 1 not AI, 2 AI-generated
AI_THRESHOLD = 0.5  # p(ai) at or above this is `ai`; the model's own cut

MODEL = ModelFile(
    "deepghs/anime_ai_check",
    "901cf37b1fd69c94634b2aa0f83822c174afd6c2",
    "mobilenetv3_sce_dist/model.onnx",
    "0215a215470145a676d7496d138cac3129d93067893573f0c57a7c9ecf7d0dee",
    ("ai", "human"),
)
# stored beside every model verdict; a different value here re-judges the backlog
DETECTOR_ID = "anime_ai_check/mobilenetv3_sce_dist"

# hashtags AI posters use, after fold(): NFKC, casefold, no fillers or separators
AI_TAGS = frozenset(
    {
        "aiイラスト",
        "ai生成",
        "ai生成イラスト",
        "ai生成画像",
        "aiアート",
        "ai画像",
        "ai绘画",
        "ai绘图",
        "ai繪圖",
        "ai繪",
        "ai詠唱",
        "ai美女",
        "aiグラビア",
        "aiart",
        "aiartwork",
        "aiartcommunity",
        "aiillustration",
        "aigenerated",
        "aigenerateart",
        "aigirl",
        "aianime",
        "aiwaifu",
        "sfwaiart",
        "nsfwaiart",
        "novelai",
        "stablediffusion",
        "midjourney",
        "nijijourney",
        "pixai",
    }
)


@dataclass(frozen=True)
class Origin:
    state: str  # ai | human
    by: str  # declared | tags | model
    score: float | None = None  # p(ai) when the model ran
    model: str = ""  # DETECTOR_ID for a model verdict; '' when declared or tagged


class Detects(Protocol):
    """What the pipeline needs; tests pass a fake with the same shape."""

    model: str

    def score(self, data: bytes) -> float:
        """p(ai) in [0, 1]."""
        ...


def fold(tag: str) -> str:
    """`tag_norm`'s folding, then every filler people pad hashtags with
    removed: variation selectors and other marks, format characters, the
    Hangul filler, and `_ - .` and spaces (stable_diffusion = stablediffusion)."""
    out = []
    for ch in norm_tag(tag):
        if ch in "_-. ㅤᅟᅠ⠀":
            continue
        if unicodedata.category(ch) in ("Mn", "Cf"):
            continue
        out.append(ch)
    return "".join(out)


def declared(source_meta: dict[str, Any] | None, tags: Iterable[str]) -> Origin | None:
    """What the post itself says: pixiv's flag first, then an AI hashtag.
    None = the post says nothing, so the model has to decide."""
    try:
        if int((source_meta or {}).get("ai_type") or 0) == PIXIV_AI:
            return Origin("ai", "declared")
    except (TypeError, ValueError):
        pass
    if any(fold(t) in AI_TAGS for t in tags):
        return Origin("ai", "tags")
    return None


def judge(said: Origin | None, score: float | None, model: str = DETECTOR_ID) -> Origin | None:
    """The verdict: what the post declared wins; else the model's score;
    else None (pending)."""
    if said is not None:
        return said
    if score is None:
        return None
    return Origin("ai" if score >= AI_THRESHOLD else "human", "model", round(score, 4), model)


def models_present(home: Path) -> bool:
    return model_path(home, MODEL).exists()


class Detector:
    """The ONNX session, loaded on the first `score()` (which downloads the
    model if needed). Lives on the worker thread with the other adapters."""

    model = DETECTOR_ID

    def __init__(
        self,
        home: Path,
        fetch: Callable[[str], bytes],
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.home = Path(home)
        self._fetch = fetch
        self.log = log
        self._session: Any = None

    def _load(self) -> Any:
        if self._session is None:
            import onnxruntime as ort

            ensure_models(self.home, self._fetch, self.log, models=(MODEL,))
            self._session = ort.InferenceSession(
                str(model_path(self.home, MODEL)), providers=["CPUExecutionProvider"]
            )
        return self._session

    def score(self, data: bytes) -> float:
        session = self._load()
        probs = session.run(["output"], {"input": encode(data)})[0][0]
        by_label = dict(zip(MODEL.labels, (float(p) for p in probs), strict=True))
        return by_label["ai"]


def make_detector(cfg: Config, log: Callable[[str], None] | None = None) -> Detector | None:
    """The configured detector, or None when numpy/onnxruntime are absent."""
    if not runtime_available():
        return None
    return Detector(cfg.home, model_fetcher(cfg), log)
