"""Who is in a picture -- how many girls, how many boys -- for the
per-character gender filter.

The WD tagger v3 (SmilingWolf, SwinV2, Apache-2.0) predicts Danbooru's
counting tags (1girl, 2boys, multiple_girls, male_focus, ...), learned from
millions of Danbooru posts. On 144 archived images it got boys-only 5/5,
mixed ~7/9 and girls-only 47/48 right; the one miss scored 1boy 0.27, under
the usual 0.35 cut.

A character's filter is `gender` (any | female | male) and `gender_mode`:
full = only that gender in the picture; partial = the other gender allowed
as a minority (2 girls + 1 boy passes, 1 girl + 1 boy does not). An image
with nobody in it passes neither -- the archive is for the character.

The tag scores are stored per image (image_people), so the rule and its cut
can change without re-tagging. The character tags it predicts are stored too,
for character recognition later (backlogged). Needs numpy + onnxruntime, like
kinds.py; the 467 MB model is fetched on first use, pinned and verified.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from PIL import Image

from .kinds import (
    LabelError,
    ModelFile,
    ensure_models,
    model_fetcher,
    model_path,
    runtime_available,
)

if TYPE_CHECKING:
    from .config import Config

Gender = Literal["any", "female", "male"]
GenderMode = Literal["full", "partial"]
GENDERS: tuple[Gender, ...] = ("any", "female", "male")
MODES: tuple[GenderMode, ...] = ("full", "partial")

THRESHOLD = 0.35  # the tagger's usual cut for general tags
KEEP_SCORE = 0.2  # people tags stored from here, so the cut can move later
CHAR_SCORE = 0.5  # character tags stored from here
INPUT_PX = 448

REPO, REVISION = "SmilingWolf/wd-swinv2-tagger-v3", "627aef95638667ddcaa3ac8ae625e88ea5b02f51"
MODEL = ModelFile(
    REPO,
    REVISION,
    "model.onnx",
    "e6774bff34d43bd49f75a47db4ef217dce701c9847b546523eb85ff6dbba1db1",
    (),
)
TAGS = ModelFile(
    REPO,
    REVISION,
    "selected_tags.csv",
    "298633d94d0031d2081c0893f29c82eab7f0df00b08483ba8f29d1e979441217",
    (),
)
TAGGER_ID = f"wd-swinv2-tagger-v3@{REVISION[:8]}"

_PEOPLE_TAG = re.compile(
    r"^(\d+\+?|multiple_)(girls?|boys?|others?)$|^(male_focus|no_humans|solo)$"
)
_COUNT = re.compile(r"^(\d+)\+?(girl|boy)s?$")


@dataclass
class People:
    girls: int
    boys: int
    male_focus: bool
    scores: dict[str, float] = field(default_factory=dict)  # people tags >= KEEP_SCORE
    characters: dict[str, float] = field(default_factory=dict)  # character tags >= CHAR_SCORE
    model: str = TAGGER_ID


def counts(scores: dict[str, float], cut: float = THRESHOLD) -> tuple[int, int, bool]:
    """Girls, boys and male_focus from the counting tags: 3girls -> 3,
    6+girls -> 6, multiple_boys -> at least 2."""
    girls = boys = 0
    for tag, p in scores.items():
        if p < cut:
            continue
        m = _COUNT.match(tag)
        if m:
            n = int(m.group(1))
            if m.group(2) == "girl":
                girls = max(girls, n)
            else:
                boys = max(boys, n)
        elif tag == "multiple_girls":
            girls = max(girls, 2)
        elif tag == "multiple_boys":
            boys = max(boys, 2)
    return girls, boys, scores.get("male_focus", 0.0) >= cut


def accepts(girls: int, boys: int, male_focus: bool, gender: str, mode: str) -> bool:
    """One character's rule. full: only that gender; partial: the other one
    allowed while strictly fewer. Nobody in the picture passes no filter."""
    if gender == "any":
        return True
    mine, other = (girls, boys) if gender == "female" else (boys, girls)
    if mine == 0:
        return False
    if gender == "female" and male_focus:
        return False
    return other == 0 if mode == "full" else other < mine


def encode(data: bytes) -> Any:
    """Bytes -> the (1, 448, 448, 3) float32 BGR tensor, 0..255, the tagger
    takes: pasted centred on a white square (alpha as the mask), bicubic.
    Mirrors deepghs' imgutils so the benchmark holds."""
    import numpy as np

    try:
        img: Image.Image = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise LabelError(f"not an image Pillow can read: {e}") from e
    w, h = img.size
    side = max(w, h)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    at = ((side - w) // 2, (side - h) // 2)
    try:
        square.paste(img, at, mask=img)
    except ValueError:  # no alpha to mask with
        square.paste(img, at)
    if side != INPUT_PX:
        square = square.resize((INPUT_PX, INPUT_PX), Image.Resampling.BICUBIC)
    x = np.asarray(square, dtype=np.float32)[:, :, ::-1]
    return np.ascontiguousarray(x)[None]


class Tagger:
    """The ONNX session and the tag vocabulary, loaded on first use (which
    downloads them if needed). Lives on the worker thread."""

    model = TAGGER_ID

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
        self._people: list[tuple[int, str]] = []
        self._chars: list[tuple[int, str]] = []

    def _load(self) -> Any:
        if self._session is None:
            import onnxruntime as ort

            ensure_models(self.home, self._fetch, self.log, models=(MODEL, TAGS))
            with open(model_path(self.home, TAGS), encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self._people = [
                (i, r["name"]) for i, r in enumerate(rows) if _PEOPLE_TAG.match(r["name"])
            ]
            self._chars = [(i, r["name"]) for i, r in enumerate(rows) if r["category"] == "4"]
            self._session = ort.InferenceSession(
                str(model_path(self.home, MODEL)), providers=["CPUExecutionProvider"]
            )
        return self._session

    def people(self, data: bytes) -> People:
        session = self._load()
        x = encode(data)
        probs = session.run(None, {session.get_inputs()[0].name: x})[0][0]
        scores = {n: round(float(probs[i]), 4) for i, n in self._people if probs[i] >= KEEP_SCORE}
        chars = {n: round(float(probs[i]), 4) for i, n in self._chars if probs[i] >= CHAR_SCORE}
        girls, boys, focus = counts(scores)
        return People(girls, boys, focus, scores, chars, TAGGER_ID)


class Tags(Protocol):
    """What the pipeline needs; tests pass a fake with the same shape."""

    model: str

    def people(self, data: bytes) -> People: ...


def make_tagger(cfg: Config, log: Callable[[str], None] | None = None) -> Tagger | None:
    """The configured tagger, or None when numpy/onnxruntime are absent."""
    if not runtime_available():
        return None
    return Tagger(cfg.home, model_fetcher(cfg), log)
