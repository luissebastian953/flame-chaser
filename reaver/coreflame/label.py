"""The one badge an image carries: AI, Non-Illust, Unidentified, or none.

The classifiers each answer their own question - what the image is
(kinds.py), how it was made (origin.py), who is in it (identify.py) - and
each verdict stays in its own table. The gallery shows one word per image,
folded from them in this order, the first that applies:

1. a label the user set by hand (`image_label`; `None` there means "no
   label", set by hand too) - re-running any classifier never touches it;
2. `non_illust` when the kind is anything but `illustration` (a screencap is
   kept, and is still not an illustration);
3. `ai` when the origin is `ai`;
4. `unidentified` when the identifier judged it and named nobody;
5. none: a normal illustration.

The fold is SQL, so the grid filters by it in the same query that lists it;
LABEL_SQL expects the grid's aliases: media m, image_kinds k, image_origin o
(joined on the current detector), image_identity i (joined on the current
identifier), image_label l.
"""

from __future__ import annotations

LABELS = ("ai", "non_illust", "unidentified")
SOURCES = ("auto", "manual")

MANUAL_JOIN = "LEFT JOIN image_label l ON l.sha256=m.sha256"
LABEL_SQL = """CASE
    WHEN l.sha256 IS NOT NULL THEN l.label
    WHEN k.kind IS NOT NULL AND k.kind<>'illustration' THEN 'non_illust'
    WHEN o.state='ai' THEN 'ai'
    WHEN i.state='unidentified' THEN 'unidentified'
END"""
SOURCE_SQL = "CASE WHEN l.sha256 IS NOT NULL THEN 'manual' ELSE 'auto' END"


def fold(
    manual: tuple[bool, str | None],
    kind: str | None,
    origin: str | None,
    identity: str | None,
) -> str | None:
    """The same fold in Python, for callers that already hold the verdicts.
    `manual` is (a row exists, its label)."""
    if manual[0]:
        return manual[1]
    if kind is not None and kind != "illustration":
        return "non_illust"
    if origin == "ai":
        return "ai"
    if identity == "unidentified":
        return "unidentified"
    return None
