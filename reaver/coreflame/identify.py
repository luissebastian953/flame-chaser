"""Who the character in a picture is, by name: any anime, game, manga,
light-novel or visual-novel character the taggers learned from Danbooru --
or `unidentified`.

Two taggers vouch for each other:
- WD tagger v3 (people.py's model, Apache-2.0): 2,751 characters, data to
  Feb 2024, strong on older characters (it knows Raiden Mei from Genshin's
  Raiden Shogun).
- Camie tagger v2 (Camais03, GPL-3.0): 26,968 characters, 2024 data, 789 MB.
A character is named when WD >= 0.85 or Camie >= 0.5 says so alone;
otherwise only when both name the same character at >= 0.2. Nothing else
counts: the picture is `unidentified`. Measured 2026-10-10 on 264
hand-labelled crawled images (Kiana, Raiden Mei, Firefly): 96.9% right,
2.6% a wrong name, 0.5% unidentified -- against WD alone 41.9% (it has no
Firefly) and Camie alone 92.7%.

Names are Danbooru character tags folded to the character (`base`): a
costume or form tag (raiden_mei_(herrscher_of_thunder)) groups under its
character (raiden_mei); a franchise qualifier stays part of the name
(firefly_(honkai:_star_rail)). The top candidates of both models are stored
per image, so the rule can move without re-running either model.

Identification only labels -- it never removes an image. Needs numpy +
onnxruntime like kinds.py; Camie's files are fetched on first use from a
pinned revision and refused unless they hash to the pinned sha256.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PIL import Image

from .kinds import (
    LabelError,
    ModelFile,
    ensure_models,
    model_fetcher,
    model_path,
    runtime_available,
)
from .names import title
from .people import People, Tagger

if TYPE_CHECKING:
    from .config import Config

WD_SURE = 0.85  # WD alone names a character from here (its demo's character cut)
CAMIE_SURE = 0.5  # Camie alone names a character from here
BOTH = 0.2  # under those, both must name the same character at least this sure
KEEP_SCORE = 0.05  # candidates stored from here, so the rule can move later
TOP = 5  # candidates stored per model
INPUT_PX = 512
PAD = (124, 116, 104)  # ImageNet's mean, what Camie pads to a square with
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)

CAMIE_REPO, CAMIE_REVISION = "Camais03/camie-tagger-v2", "7d40c1b85b86ab4f607b2caf26b1b50c99db743e"
CAMIE = ModelFile(
    CAMIE_REPO,
    CAMIE_REVISION,
    "camie-tagger-v2.onnx",
    "ab0aaf253e3d546090001bec9bebc776c354ab6800f442ab9167af87b4a953ac",
    (),
)
CAMIE_META = ModelFile(
    CAMIE_REPO,
    CAMIE_REVISION,
    "camie-tagger-v2-metadata.json",
    "de9f962eb0fd86b7e30d0af4e8c7990205200d70e955d8ecae60f87d14eae66b",
    (),
)
# stored beside every identity; a different value here re-identifies the backlog
IDENTIFIER_ID = f"wd-swinv2-tagger-v3+camie-tagger-v2@{CAMIE_REVISION[:8]}"

_GROUP = re.compile(r"_\(([^()]*)\)")


@dataclass(frozen=True)
class Hit:
    name: str  # the character (base tag): what the gallery groups and filters by
    tag: str  # the most specific tag named for it -- a costume, a form
    score: float
    by: str  # wd | camie | both


@dataclass
class Identity:
    hits: list[Hit]
    candidates: dict[str, list[list[Any]]] = field(default_factory=dict)  # model -> [[tag, p]]
    model: str = IDENTIFIER_ID
    people: People | None = None  # the WD read this call made, stored as image_people too

    @property
    def state(self) -> str:
        return "identified" if self.hits else "unidentified"


class Identifies(Protocol):
    """What the pipeline needs; tests pass a fake with the same shape."""

    model: str

    def identify(self, data: bytes, people: People | None = None) -> Identity: ...


def fold(tag: str, characters: AbstractSet[str], copyrights: AbstractSet[str]) -> str:
    """A costume/form tag -> its character: drop one parenthesised group that
    is not a franchise when what is left is itself a character tag; repeat.
    raiden_mei_(herrscher_of_thunder) -> raiden_mei;
    firefly_(jepella_rebellion)_(honkai:_star_rail) -> firefly_(honkai:_star_rail);
    iris_(mega_man) stays (no bare `iris` character)."""
    cur = tag
    while True:
        for m in reversed(list(_GROUP.finditer(cur))):
            if m.group(1) in copyrights:
                continue  # a franchise qualifier is part of the name
            shorter = cur[: m.start()] + cur[m.end() :]
            if shorter in characters:
                cur = shorter
                break
        else:
            return cur


def label_of(tag: str) -> str:
    """firefly_(honkai:_star_rail) -> Firefly (Honkai: Star Rail)"""
    return re.sub(r"\((\w)", lambda m: "(" + m.group(1).upper(), title(tag))


def decide(wd: list[list[Any]], camie: list[list[Any]], base: Callable[[str], str]) -> list[Hit]:
    """The rule (module docstring) over both models' candidates [[tag, p], ...]."""
    best: dict[str, Hit] = {}

    def offer(tag: str, p: float, by: str) -> None:
        name = base(tag)
        h = best.get(name)
        if h is None:
            best[name] = Hit(name, tag, p, by)
        else:  # both models named it, or one named it twice (base and form)
            both = "both" if h.by != by else h.by
            top = (tag, p) if p > h.score else (h.tag, h.score)
            best[name] = Hit(name, top[0], top[1], both)

    for tag, p in wd:
        if p >= WD_SURE:
            offer(tag, p, "wd")
    for tag, p in camie:
        if p >= CAMIE_SURE:
            offer(tag, p, "camie")
    if not best:  # neither is sure: only a character both name counts
        agreed = {base(t) for t, p in wd if p >= BOTH} & {base(t) for t, p in camie if p >= BOTH}
        for by, cands in (("wd", wd), ("camie", camie)):
            for tag, p in cands:
                if p >= BOTH and base(tag) in agreed:
                    offer(tag, p, by)
    return sorted(best.values(), key=lambda h: -h.score)


def encode(data: bytes) -> Any:
    """Bytes -> the (1, 3, 512, 512) float32 tensor Camie takes: alpha over
    white, fitted inside 512 keeping the aspect (Lanczos), padded with
    ImageNet's mean, ImageNet-normalised. As Camie's onnx_inference.py, with
    the white composite the benchmark used."""
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
    img = img.convert("RGB")
    w, h = img.size
    nw, nh = (INPUT_PX, int(INPUT_PX * h / w)) if w > h else (int(INPUT_PX * w / h), INPUT_PX)
    img = img.resize((max(nw, 1), max(nh, 1)), Image.Resampling.LANCZOS)
    square = Image.new("RGB", (INPUT_PX, INPUT_PX), PAD)
    square.paste(img, ((INPUT_PX - img.width) // 2, (INPUT_PX - img.height) // 2))
    x = (np.asarray(square, dtype=np.float32) / 255.0 - np.array(MEAN, np.float32)) / np.array(
        STD, np.float32
    )
    return np.ascontiguousarray(x.transpose(2, 0, 1))[None]


def _top(scores: list[tuple[str, float]]) -> list[list[Any]]:
    keep = sorted((s for s in scores if s[1] >= KEEP_SCORE), key=lambda s: -s[1])[:TOP]
    return [[t, round(float(p), 4)] for t, p in keep]


class Identifier:
    """Camie's session and vocabulary, loaded on first use (which downloads
    789 MB if needed), plus the WD tagger it shares with the gender filter.
    Lives on the worker thread."""

    model = IDENTIFIER_ID

    def __init__(
        self,
        home: Path,
        fetch: Callable[[str], bytes],
        tagger: Tagger,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.home = Path(home)
        self._fetch = fetch
        self.tagger = tagger
        self.log = log
        self._session: Any = None
        self._chars: Any = None  # numpy index array of Camie's character tags
        self._names: list[str] = []
        self.base: Callable[[str], str] = lambda t: t

    def _load(self) -> Any:
        if self._session is None:
            import numpy as np
            import onnxruntime as ort

            ensure_models(self.home, self._fetch, self.log, models=(CAMIE, CAMIE_META))
            with open(model_path(self.home, CAMIE_META), encoding="utf-8") as f:
                mapping = json.load(f)["dataset_info"]["tag_mapping"]
            cats: dict[str, str] = mapping["tag_to_category"]
            idx = sorted(
                int(i) for i, t in mapping["idx_to_tag"].items() if cats.get(t) == "character"
            )
            self._chars = np.array(idx)
            self._names = [mapping["idx_to_tag"][str(i)] for i in idx]
            characters = frozenset(self._names) | frozenset(n for _, n in self.tagger.characters())
            copyrights = frozenset(t for t, c in cats.items() if c == "copyright")
            self.base = lru_cache(maxsize=65536)(lambda t: fold(t, characters, copyrights))
            self._session = ort.InferenceSession(
                str(model_path(self.home, CAMIE)), providers=["CPUExecutionProvider"]
            )
        return self._session

    def identify(self, data: bytes, people: People | None = None) -> Identity:
        """`people` = the WD read the caller already made for this image (the
        gender filter's); without one this makes it."""
        import numpy as np

        session = self._load()
        wd_read = people if people is not None else self.tagger.people(data)
        out = session.run(None, {session.get_inputs()[0].name: encode(data)})
        logits = out[1] if len(out) >= 2 else out[0]  # the refined predictions
        probs = 1.0 / (1.0 + np.exp(-logits[0, self._chars]))
        camie = _top(list(zip(self._names, probs.tolist(), strict=True)))
        wd = _top(list(wd_read.characters.items()))
        return Identity(
            decide(wd, camie, self.base),
            {"wd": wd, "camie": camie},
            IDENTIFIER_ID,
            None if people is not None else wd_read,
        )


def models_present(home: Path) -> bool:
    """Both taggers' files on disk -- otherwise the first use downloads them."""
    from .people import MODEL as WD_MODEL
    from .people import TAGS as WD_TAGS

    return all(model_path(home, m).exists() for m in (CAMIE, CAMIE_META, WD_MODEL, WD_TAGS))


def make_identifier(
    cfg: Config, tagger: Tagger | None, log: Callable[[str], None] | None = None
) -> Identifier | None:
    """The configured identifier, or None when switched off in Settings or
    numpy/onnxruntime are absent."""
    if not cfg.identify_characters or tagger is None or not runtime_available():
        return None
    return Identifier(cfg.home, model_fetcher(cfg), tagger, log)
