"""Names a character goes by, from sources outside pixiv and X.

The character form's suggestions came only from pixiv (tags that co-occur in a
search), so without a pixiv session there were none. Two public sources know
characters by name, in several languages, and need no login:

* Danbooru -- the anime-art site's character tags. `autocomplete` resolves a
  name typed in any language to the tag (キアナ -> kiana_kaslana), the tag's
  wiki lists its "other names" (琪亚娜·卡斯兰娜, キアナ・カスラナ, ...), and
  its form/costume tags come ranked by post count
  (raiden_mei_(herrscher_of_thunder) 1,648). Documented limit: 10 req/s in
  bursts, "around 1 request per second" sustained.
* Wikidata -- labels per language (en, ja, ko, zh-hans, zh-hant) plus aliases,
  CC0. Fills what Danbooru leaves out, Korean especially.

Only names are read: never images or posts. A source that fails is reported
in `errors` and left out; the other still answers. Fetchers are injected, so
tests run on fixture payloads.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

if TYPE_CHECKING:
    from .config import Config

DANBOORU = "https://danbooru.donmai.us"
WIKIDATA = "https://www.wikidata.org/w/api.php"
CHARACTER = 4  # Danbooru tag category
FORMS_N = 6  # form/costume tags listed
FORM_WIKIS_N = 3  # of those, the ones whose other names are fetched too
QUERIES_N = 8
LANG_ORDER = ("en", "ja", "zh-hans", "zh-hant", "ko")
WIKIDATA_LANGS = ("en", "ja", "ko", "zh", "zh-hans", "zh-hant")


def _wd_lang(code: str) -> str:
    """Wikidata's language codes folded to the ones the UI names: plain `zh`
    (and the mainland / Singapore variants) are Simplified, Taiwan / Hong Kong /
    Macau are Traditional, regional English is English. Labels and aliases
    alike -- an unfolded alias code reaches the form as an unknown language."""
    if code in ("zh", "zh-cn", "zh-sg", "zh-my", "zh-hans"):
        return "zh-hans"
    if code in ("zh-tw", "zh-hk", "zh-mo", "zh-hant", "yue"):
        return "zh-hant"
    return code.split("-", maxsplit=1)[0] if code.startswith(("en-", "ja-", "ko-")) else code


Fetch = Callable[[str], Any]


class NotFound(Exception):
    """The source has no such page (a 404): an answer, not a failure."""


@dataclass
class NameSuggestion:
    text: str  # exactly what would be added as a pixiv tag or an X term
    kind: str  # "name" | "form"
    lang: str | None  # en ja ko zh-hans zh-hant, "cjk" for Han-only, None unknown
    sources: list[str]
    posts: int | None = None  # Danbooru post count: how much art carries it
    form: str | None = None  # the form's English name, e.g. "herrscher of thunder"
    risky: bool = False  # short or generic: matches other things as an X term


@dataclass
class CharacterNames:
    danbooru_tag: str | None = None
    wikidata_id: str | None = None
    label: str | None = None
    suggestions: list[NameSuggestion] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


# -- text -----------------------------------------------------------------
def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


_KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_HAN = re.compile(r"[㐀-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def lang_of(text: str) -> str | None:
    """By script -- a guess only where no source says. Han without kana could
    be Chinese or Japanese, so it is just "cjk"."""
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _HAN.search(text):
        return "cjk"
    if _LATIN.search(text):
        return "en"
    return None


def is_risky(text: str) -> bool:
    """One short word: `Kiana`, `芽衣`, `메이`. Fine to know, loose as an X
    search term -- `kiana` matched a soccer player and a pet cat."""
    tokens = [t for t in re.split(r"[\s_·・.\-]+", text.strip()) if t]
    if len(tokens) != 1:
        return False
    t = tokens[0]
    if _LATIN.search(t) and not (_KANA.search(t) or _HAN.search(t) or _HANGUL.search(t)):
        return len(t) <= 7
    return len(t) <= 2


_SMALL = {"of", "the", "a", "an", "and", "in", "on", "to", "for", "at", "by", "de", "no"}


def title(tag: str) -> str:
    """kiana_kaslana -> Kiana Kaslana; herrscher_of_the_void -> Herrscher of the Void"""
    words = [w for w in tag.split("_") if w]
    return " ".join(w if i and w in _SMALL else w[:1].upper() + w[1:] for i, w in enumerate(words))


# -- Danbooru -------------------------------------------------------------
def _wiki_names(fetch: Fetch, tag: str) -> list[str]:
    try:
        page = fetch(f"{DANBOORU}/wiki_pages/{quote(tag)}.json")
    except NotFound:
        return []
    return [n for n in (page or {}).get("other_names") or [] if isinstance(n, str) and n.strip()]


def danbooru_resolve(fetch: Fetch, queries: list[str]) -> tuple[str, int] | None:
    """The character tag for the first query Danbooru knows. Autocomplete
    matches "other names" in any language; spaces are tag separators there,
    so a Latin name is sent with underscores. When the hits are a character
    and its forms, the base tag is the one the others extend."""
    for q in queries:
        rows = fetch(
            f"{DANBOORU}/autocomplete.json?"
            + urlencode(
                {
                    "search[query]": q.strip().replace(" ", "_"),
                    "search[type]": "tag_query",
                    "limit": 10,
                }
            )
        )
        chars = [r for r in rows or [] if r.get("category") == CHARACTER and r.get("value")]
        if not chars:
            continue
        shortest = min(chars, key=lambda r: len(r["value"]))
        base = (
            shortest if all(r["value"].startswith(shortest["value"]) for r in chars) else chars[0]
        )
        return str(base["value"]), int(base.get("post_count") or 0)
    return None


def danbooru_names(fetch: Fetch, tag: str, posts: int) -> list[NameSuggestion]:
    src = ["danbooru"]
    out = [NameSuggestion(title(tag), "name", "en", src, posts)]
    out += [NameSuggestion(n, "name", lang_of(n), src) for n in _wiki_names(fetch, tag)]
    forms = fetch(
        f"{DANBOORU}/tags.json?"
        + urlencode(
            {
                "search[name_matches]": f"{tag}_(*",
                "search[category]": CHARACTER,
                "search[order]": "count",
                "limit": FORMS_N,
            }
        )
    )
    for i, t in enumerate(forms or []):
        name = str(t.get("name") or "")
        if not (name.startswith(f"{tag}_(") and name.endswith(")")):
            continue
        form = name[len(tag) + 2 : -1].replace("_", " ")
        n_posts = int(t.get("post_count") or 0)
        out.append(NameSuggestion(title(form.replace(" ", "_")), "form", "en", src, n_posts, form))
        if i < FORM_WIKIS_N:
            out += [
                NameSuggestion(n, "form", lang_of(n), src, n_posts, form)
                for n in _wiki_names(fetch, name)
            ]
    return out


# -- Wikidata -------------------------------------------------------------
def wikidata_names(
    fetch: Fetch, queries: list[str], known: list[str]
) -> tuple[str | None, list[NameSuggestion]]:
    """The item whose label or alias IS one of the queries -- and, when
    Danbooru already named the character, one that shares a name with it, so
    a same-named person or place never slips in."""
    known_n = {norm(k) for k in known}
    qid = None
    for q in queries:
        res = fetch(
            WIKIDATA
            + "?"
            + urlencode(
                {
                    "action": "wbsearchentities",
                    "search": q,
                    "language": "en",
                    "type": "item",
                    "limit": 5,
                    "format": "json",
                }
            )
        )
        for hit in (res or {}).get("search") or []:
            if norm((hit.get("match") or {}).get("text") or hit.get("label") or "") == norm(q):
                qid = str(hit["id"])
                break
        if qid:
            break
    if not qid:
        return None, []
    ent = fetch(
        WIKIDATA
        + "?"
        + urlencode(
            {
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels|aliases",
                "languages": "|".join(WIKIDATA_LANGS),
                "format": "json",
            }
        )
    )
    e = ((ent or {}).get("entities") or {}).get(qid) or {}
    src = ["wikidata"]
    out: list[NameSuggestion] = []
    for lang, v in (e.get("labels") or {}).items():
        out.append(NameSuggestion(v["value"], "name", _wd_lang(lang), src))
    for lang, vs in (e.get("aliases") or {}).items():
        out += [NameSuggestion(a["value"], "name", _wd_lang(lang), src) for a in vs]
    if known_n and not any(norm(s.text) in known_n for s in out):
        return None, []  # a different entity with the same name
    return qid, out


# -- merge ----------------------------------------------------------------
def merge(*groups: list[NameSuggestion]) -> list[NameSuggestion]:
    """One row per text (NFKC, case-insensitive): sources united, the
    explicit language of a source kept over a script guess. Different
    spellings stay separate -- ・ and · are different pixiv tags."""
    by: dict[str, NameSuggestion] = {}
    for group in groups:
        for s in group:
            k = norm(s.text)
            if not k:
                continue
            have = by.get(k)
            if have is None:
                by[k] = NameSuggestion(
                    s.text, s.kind, s.lang, list(s.sources), s.posts, s.form, is_risky(s.text)
                )
                continue
            have.sources += [x for x in s.sources if x not in have.sources]
            if have.lang in (None, "cjk") and s.lang not in (None, "cjk"):
                have.lang = s.lang
            if s.posts and (have.posts or 0) < s.posts:
                have.posts = s.posts
    rows = list(by.values())
    names = [s for s in rows if s.kind == "name"]
    forms = [s for s in rows if s.kind == "form"]
    names.sort(
        key=lambda s: (
            LANG_ORDER.index(s.lang) if s.lang in LANG_ORDER else len(LANG_ORDER),
            s.risky,
        )
    )
    forms.sort(key=lambda s: -(s.posts or 0))
    return names + forms


def lookup(queries: list[str], danbooru: Fetch | None, wikidata: Fetch | None) -> CharacterNames:
    """What the form calls: the character's names and forms from whatever
    sources answer. `queries` = the display name, then its tags and terms."""
    out = CharacterNames()
    qs = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))[:QUERIES_N]
    if not qs:
        return out
    dnames: list[NameSuggestion] = []
    if danbooru is not None:
        try:
            hit = danbooru_resolve(danbooru, qs)
            if hit:
                out.danbooru_tag, posts = hit
                out.label = title(out.danbooru_tag)
                dnames = danbooru_names(danbooru, out.danbooru_tag, posts)
        except Exception as e:
            out.errors["danbooru"] = f"{type(e).__name__}: {str(e)[:120]}"
    wnames: list[NameSuggestion] = []
    if wikidata is not None:
        try:
            wq = list(dict.fromkeys([*([out.label] if out.label else []), *qs]))[:3]
            out.wikidata_id, wnames = wikidata_names(wikidata, wq, [s.text for s in dnames])
        except Exception as e:
            out.errors["wikidata"] = f"{type(e).__name__}: {str(e)[:120]}"
    out.label = out.label or next((s.text for s in wnames if s.lang == "en"), None)
    out.suggestions = merge(dnames, wnames)
    return out


def make_fetchers(cfg: Config, user_agent: str) -> tuple[Fetch, Fetch]:
    """One rate-limited client per source (1 req/s, burst 3, two tries), with
    the configured resolver and proxy. 404 becomes NotFound."""
    import httpx

    from .http import SourceClient

    resolver = None
    if cfg.resolver == "doh":
        from .net import DEFAULT_DOH, DohResolver

        resolver = DohResolver(cfg.doh_endpoints or DEFAULT_DOH)

    def client() -> SourceClient:
        return SourceClient(
            {"User-Agent": user_agent, "Accept": "application/json"},
            rate=1.0,
            burst=3.0,
            timeout=20.0,
            max_retries=2,
            resolver=resolver,
            proxy=cfg.proxy_url,
        )

    def fetcher(c: SourceClient) -> Fetch:
        def fetch(url: str) -> Any:
            try:
                return c.get_json(url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise NotFound(url) from e
                raise

        return fetch

    return fetcher(client()), fetcher(client())
