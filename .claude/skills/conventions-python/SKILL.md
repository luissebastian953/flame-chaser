---
name: conventions-python
description: Conventions for reaver/ (coreflame engine + dawnmaker daemon) — Python floor, ruff/mypy, offline tests, http/rate limits, models, secrets, and the checklist for adding a daemon endpoint.
---

# Python conventions — `reaver/`

Two packages, one direction: `dawnmaker` imports `coreflame`; `coreflame`
never imports `dawnmaker` or FastAPI. `./check.sh` is the definition of done.

## Toolchain (`reaver/pyproject.toml`)

- **`requires-python = ">=3.10"`.** No `datetime.UTC` (use `timezone.utc`),
  no `StrEnum` (use `(str, Enum)`), no `match` on types you can avoid. ruff
  `target-version = "py310"` with `UP017`/`UP042` ignored for exactly this.
- **ruff** selects `E F I UP B SIM RUF S T20 PL`; every ignore has a comment
  saying why. `S501` (`verify=False`) is deliberately NOT ignored. Format:
  double quotes, 100 cols (`E501` ignored — long SQL is fine).
  `tests/*` may assert freely (`S`, `PL` off); `coreflame/net.py` may name
  `verify=False` only to refuse it.
- **mypy** on `coreflame` + `dawnmaker` with the `pydantic.mypy` plugin,
  `check_untyped_defs`, `warn_return_any`, `warn_unused_ignores`,
  `ignore_missing_imports` (glom, gallery-dl have no stubs). Run with
  `--cache-dir /tmp/mypy_cache` — the cache must be off the synced folder.

```
cd reaver && ./check.sh      # ruff check · ruff format --check · mypy · tests · verify=False grep
ruff format . && ruff check . --fix     # the fixers
```

## Tests are plain files, not pytest

`tests/test_*.py` each have an `if __name__ == "__main__":` block and run with
`python3 tests/test_x.py`; `check.sh` loops over them and prints the last
line. They `sys.path.insert(0, parent)` and import each other
(`from test_smoke import _img, fake_pixiv`). **Every test is offline**:
fake adapters and inline fixture payloads live in `tests/test_smoke.py`;
images are generated with Pillow. Never write a test that hits pixiv or X.
A new `tests/test_*.py` is picked up by `check.sh` automatically; it only
needs its own `__main__` block that calls every test function.

## HTTP — `coreflame/http.py`

- One `SourceClient` per source: owns cookies, headers, the global
  `TokenBucket(rate, burst)` and per-endpoint buckets via
  `limit_endpoint(name, rate)`; call `get(url, bucket="search")`.
- Retry only 429 (honour `Retry-After`) and 5xx. Any other 4xx raises at
  once — retrying it is how an IP ban happens. Rates stay conservative
  (default 1 req/s, burst 3); a new endpoint gets its own, stricter bucket.
- **Never `verify=False`** — as an option, flag or fallback. `check.sh` greps
  for it and fails. A cert failure is evidence of interception; stop.
- `Referer` is mandatory on `i.pximg.net`.

## Normalisation — three layers, kept separate

```
store.put_raw()  → every raw payload retained, zlib'd, content-addressed
specs.extract()  → glom, per source; EVERY path is Coalesce(..., default=None); never raises
IllustRecord()   → pydantic; ValidationError → store.quarantine(raw_hash, error)
```

Models (`coreflame/models.py`): `ConfigDict(extra="forbid")`, ids are `str`
(snowflakes overflow JS ints), datetimes are tz-aware UTC at the adapter
edge, tags keep `tag_raw` + NFKC `tag_norm`. A missing required field is
validation's failure, not extraction's. Re-normalise by re-parsing
`store.raws_for()`, never by re-fetching.

## Engine rules that bite

- `seen_posts` is checked from the listing, **before** any detail fetch;
  four states (`indexed skipped gone failed`) are four retry policies.
- Every write is an idempotent upsert on a natural key; blobs on disk, hash
  in SQLite, never bytes in SQLite.
- Jobs: one worker thread per source lane, never two on one source;
  `ctx.check()` between records and at each
  `ctx.stage()`, never inside a write; `ctx.progress(done, total=None)` when
  there is no honest denominator. A job `running` at boot becomes `interrupted`.

## Daemon rules — `dawnmaker/`

- **stdout is the handshake channel** (`DAWNMAKER_READY {json}`); all logging
  to stderr. A stray `print()` breaks the shell's spawn.
- One `Store` per request: `Depends(store)` yields
  `Store(db_path, check_same_thread=False)` and closes it. No thread-local
  cache — the dependency and the endpoint run on different threads and the
  SSE stream pins one for its lifetime. SQLite access stays sequential.
- Secrets: only `Config.save_secrets()` writes `~/.reaver/secrets.json`
  (chmod 0600). `config.json` never contains a cookie; `GET /api/config`
  never returns one. A pixiv cookie is verified with one search request
  before it is stored (`dawnmaker/auth.py`).
- `?token=` is accepted on `/api/events`, `/api/media/*`, `/api/preview/*`
  only (`security.py`); everywhere else the bearer header. CORS reflects
  only `tauri://`/`tauri.localhost` origins, plus `localhost:*` under `--dev`;
  never `*`. Foreign `Host` → 421, foreign `Origin` → 403.
- Errors are `HTTPException(status, {"code": ..., "message": ...})`; the
  handler wraps them as `{"error": {code, message}}`. The UI switches on `code`.
- Legal posture: private archive, attribution permalink on every post, no
  redistribution, deleted/privated works removed. Do not add sharing features.

## Adding an endpoint — checklist

1. Body model `class XIn(BaseModel)` in `dawnmaker/app.py` (pydantic, no
   `Any` unless it is a job params bag).
2. Route inside `create_app`: `@app.<verb>("/api/...")`, `s: Store =
   Depends(store)`, return plain dicts/lists, raise `HTTPException` with
   `{code, message}`; 201/202/204 where the contract says so.
3. Engine logic lives in `coreflame` (a function that takes a `Store`), not
   in the route.
4. Test in `tests/test_dawnmaker.py` via `boot(tmp)` → `TestClient` with the
   bearer header; seed data through `fake_pixiv()` / `IllustRecord`, never
   the network. Add the call to the file's `__main__` block.
5. Mirror the response shape in `deliverer/src/lib/types.ts` and the route in
   `docs/design/architecture.md` §6 (API contract).
6. `./check.sh` green, then commit as `feat(dawnmaker): ...`.
