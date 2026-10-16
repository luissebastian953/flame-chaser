# reaver — engine + daemon

```
reaver/                 the project (pyproject, tests). Not a package. Python >= 3.10.
├── check.sh          definition of done: ruff check · ruff format --check · mypy · tests · verify=False grep
├── pyproject.toml    deps, ruff rules (each ignore explained), mypy (pydantic plugin)
├── requirements.txt  engine deps only (mirrors pyproject; gallery-dl must stay current)
├── coreflame/        the engine. No FastAPI, no daemon imports.
│   ├── __main__.py   `python -m coreflame` → cli.main
│   ├── config.py     Config dataclass; ~/.reaver (REAVER_HOME); save() vs save_secrets() (0600)
│   ├── models.py     IllustRecord / MediaRef / Tag / Watch — pydantic, the normalization boundary
│   ├── migrations.py forward-only schema migrations (backup before apply, min_app_version)
│   ├── http.py       SourceClient: token buckets (global + per endpoint), 429, retries; METER (req/min per budget and job)
│   ├── net.py        DoH resolver + the blocking diagnostic (`coreflame net <host>`)
│   ├── db.py         SQLite Store; every write an idempotent upsert; raw retention, quarantine
│   ├── seen.py       the visited gate (four states)
│   ├── tags.py       tag_stats rebuild, rarity-weighted ranking, watch/ignore, suggest
│   ├── phash.py      dHash + Hamming + int64 sign-wrap
│   ├── dedupe.py     two-level classify()
│   ├── blobs.py      content-addressed store
│   ├── thumbs.py     400px WebP at ingest, addressed by the original's sha
│   ├── kinds.py      image kinds; KEEP = illustration + screencap, the rest is never stored; optional [classify]
│   ├── names.py      a character's names + forms from Danbooru and Wikidata (form suggestions)
│   ├── people.py     who is in a picture (WD tagger v3): per-character gender filter, full/partial
│   ├── identify.py   the character's name (WD v3 + Camie v2 vouch for each other) or unidentified; labels only
│   ├── library.py    hardlink view, gc, import
│   ├── jobs.py       queue, one worker thread per source lane, JobContext (check/stage/progress/tally), pause, interrupted-at-boot
│   ├── handlers.py   job type -> pipeline function; adapters built per job; plan() splits a crawl per source
│   ├── pipeline.py   poll → link → poll_twitter / search_to_target → download; drift notes
│   ├── cli.py        watch / watches / poll / link / media / status / doctor / tags / suggest / jobs / net
│   └── sources/      one file per source, behind the Adapter protocol
│       ├── base.py   Adapter protocol (name, supports_discovery, discover, fetch_media)
│       ├── pixiv.py  discovery source (ajax search + illust detail)
│       ├── twitter.py follow source via gallery-dl; discover() raises on purpose
│       └── specs.py  glom extraction specs — source-shaped JSON -> flat dict, as DATA
├── dawnmaker/        FastAPI + SSE. Imports coreflame. Never the reverse.
│   ├── __main__.py   bind :0 -> lockfile -> ONE handshake line on stdout -> serve; --dev/--host/--no-heartbeat
│   ├── app.py        the API contract (docs/design/architecture.md §6); *In models; Heartbeat; State
│   ├── auth.py       store / verify / revoke source sessions (pixiv cookie verified before stored)
│   ├── probe.py      character-form live validation: one search page per tag, cached; preview proxy
│   ├── names.py      NameFinder: coreflame.names behind a day's cache (POST /api/names)
│   ├── events.py     EventHub: ring buffer + Last-Event-ID replay + keepalives
│   └── security.py   LoopbackAuth: bearer token + Host/Origin check + CORS reflection
└── tests/            plain python3 files, all offline; each has a __main__ block
    ├── test_smoke.py     fake_pixiv(), inline fixtures, generated images; adapters, dedupe, library
    ├── test_normalize.py raw → extract → validate → quarantine; re-normalize; drift
    ├── test_seen.py      the visited gate
    ├── test_tags.py      observed-tag ranking
    ├── test_jobs.py      make_runner(); queue, cancel, interrupted, lanes, pause, order, plan, meter
    ├── test_kinds.py     score mapping, model verify, reject at ingest, backlog discard (fake labeler)
    ├── test_target.py    X search to N kept posts: exact target, catch-up, history end, 10× stop (DeepX)
    ├── test_names.py     Danbooru/Wikidata names: resolve, merge, entity check, cache (fixtures)
    ├── test_net.py       diagnostic verdicts + the verify=False refusal
    ├── test_people.py    gender rules, tagger input, reject at download, backlog, loosening (fake tagger)
    ├── test_identify.py  naming rule, form folding, at download (never rejects), backlog, new model (fake)
    └── test_dawnmaker.py the HTTP surface via TestClient (auth layers, routes, SSE)
```

Conventions in depth: `.claude/skills/conventions-python` (includes the
adding-an-endpoint checklist).

## Rules specific to this package

- **The worker thread never dies.** A job's failure becomes `failed` in
  `_run_one`; an error around it (the queue query, a lost database) is logged,
  the job it was on is marked failed, the connection reopened, and the loop
  backs off (2 s → 30 s). A dead worker leaves every later job queued while
  the API still says "idle".
- **One worker thread per source, never two on one source.** The constraint
  is the remote rate limit, not local CPU. Two workers on pixiv doubles the ban
  risk and halves each one's budget; pixiv and X are different hosts, so each
  has a lane (`jobs.LANES`) and a worker downloads only its own source's
  media. An `any` job (no remote request) is claimed by whichever is free.
- **Retry 429 and 5xx. Never retry other 4xx.** That is how an IP ban happens.
- **Cancellation is cooperative** — `ctx.check()` between records and at every
  `ctx.stage()`; never inside a write. `upsert_post` is one transaction, so a
  cancel can only ever land between complete records. The flag is a column on
  `jobs`, so a cancel from another process is honoured too.
- **A job left `running` at boot is marked `interrupted`**, not forgotten. That
  row is how you learn a crawl died at 3am.
- **Progress denominators must be honest.** For a pixiv poll the denominator is
  the count of *unvisited* ids, not `illustManga.total` — most of that total is
  gated out and costs nothing. When there is no honest denominator, send
  `total: null` and let the UI show indeterminate.
- **Ugoira is out of scope** (frame zip behind `/ugoira_meta`). Skip and record.
- **`gallery-dl` owns the X protocol layer.** Do not hand-roll a GraphQL client;
  update the dependency instead. Our code owns policy, not protocol.
- Blobs store a hash in the db and bytes on disk. Never bytes in SQLite.

## Normalization is three layers, and they stay separate

```
fetch → store.put_raw()  (zlib'd, content-addressed)     the JSON as fetched
      → specs.extract()  (glom, per source, never raises)  flat dict, nulls on missing
      → IllustRecord(**fields)  (pydantic, shared)         coerce + validate
      → store.upsert_post()  |  ValidationError → store.quarantine()
```

- **Records are built ONCE** at the adapter edge with media in hand. Do not
  construct then mutate.
- **Extraction never raises.** Every spec path is `Coalesce(..., default=)`.
  A missing required field is *validation's* failure — that routes the record
  to quarantine with its raw payload, instead of crashing the poll.
- **Re-normalization is a re-parse, never a re-fetch:** iterate
  `store.raws_for(source, kind)` after a spec fix.
- `pipeline._record_drift` writes per-field null rates each run and emits a
  DRIFT note when one jumps. That is the only signal that catches a silent
  site-shape change.
- Semantic reconciliation across sources is deliberately not done: pixiv
  `bookmark_count` and X `favorite_count` are not the same number. Extras live
  in `source_meta`.

## Daemon

Binds `127.0.0.1:0`, prints exactly one handshake line on stdout before
serving, then requires a bearer token and rejects foreign `Host`/`Origin`.
Exits after ~30s without a heartbeat — with a monotonic sleep guard, or every
laptop lid-close kills a running crawl.

- **stdout is the handshake channel.** Everything else logs to stderr. A
  stray `print()` in the daemon breaks the shell's spawn.
- **Cursors are opaque** (base64url). A raw `+00:00` in a query string decodes
  to a space; that bug was real.
- `/api/events?live=false` returns the replay and ends — for tests and one-shot
  catch-up. A real EventSource omits it and stays open with keepalive comments.
- `?token=` is accepted on `/api/events`, `/api/media/*` and `/api/preview/*`
  only, because EventSource and `<img src>` cannot set headers. Nowhere else
  (`security.py`). CORS reflects an allowed origin, never `*`.
- Dev: `python -m dawnmaker --no-heartbeat --dev` (no self-exit; allows
  `http://localhost:*` origins for Vite).

## Secrets

Session cookies live in `~/.reaver/secrets.json` (0600), written only by
`Config.save_secrets()`; `config.json` never contains them and `/api/config`
never returns them. Env (`PIXIV_PHPSESSID`) still overrides. A pixiv cookie is
verified with one search request *before* it is stored (`dawnmaker/auth.py`)
-- that is the request the crawl needs, so its verdict is the one that matters.
X cookies become `~/.reaver/twitter-cookies.txt` for gallery-dl. `poll_pixiv`
refuses to start unauthenticated rather than 401-ing per tag.

## Definition of done

```
./check.sh          # ruff check + ruff format --check + mypy + every test + the verify=False grep
```

Run it before saying anything is finished (`pnpm check` at the repo root
runs it after the deliverer checks). Individually: `ruff check . --fix`
and `ruff format .` for style (config in `pyproject.toml`, with the reason for
every ignored rule); `mypy --cache-dir /tmp/mypy_cache` for types — the cache
dir must be off the synced folder or mypy dies with a sqlite I/O error.
Python floor is 3.10: `timezone.utc`, not `datetime.UTC`.

All tests are offline and are plain `python3 tests/test_x.py` runs, not
pytest; `check.sh` prints only each file's last line, so re-run a failing one
directly for the traceback. `test_net.py` and `check.sh` both refuse
`verify=False`. To check a real connection, run `python3 -m coreflame net` from a
normal terminal on the host — NOT from a sandboxed shell, whose egress
allowlist produces a false `resolver_blocked`.
