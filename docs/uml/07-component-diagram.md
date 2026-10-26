# 7. Component diagram

Three processes on one machine plus the sites they reach. Each box is a
component with the interface it *provides* written on the edge that leads to
it. The one rule the picture must keep: dependencies point from `deliverer`
to `dawnmaker` to `coreflame`, never back (**LB**). That is what lets the
CLI drive the engine while the UI is mid-refactor.

```mermaid
flowchart TB
  subgraph shell["deliverer · Tauri v2 shell (Rust)"]
    lib["lib.rs<br/>plugins · commands · window events"]
    side["sidecar.rs<br/>spawn · handshake · heartbeat thread · shutdown"]
    authr["auth.rs<br/>source_login: site login window,<br/>cookies_for_url poll"]
    pipr["pip.rs<br/>mini window: open · snap · resize"]
    trayr["tray.rs<br/>tray icon · menu · tooltip"]
    caps["capabilities/<br/>default.json (main) · pip.json (pip)"]
  end

  subgraph web["deliverer · webview (Vue 3 + Pinia + Vite)"]
    pages["pages/<br/>Gallery · CharacterDetail · Config · PipelineList · PipelineDetail · Settings"]
    comps["components/<br/>WatchForm · GalleryTile · DetailAside · ImageViewer · RunToasts · BackupPanel · ..."]
    stores["stores/<br/>endpoint · sources · jobs · library · deletion · background · updater · theme · ..."]
    apits["lib/api.ts + lib/types.ts<br/>discover · fetch with Bearer · EventSource · mediaUrl"]
    bgts["lib/background.ts<br/>PipTick builder, tray labels"]
    i18n["i18n.ts + locales/<lang>/*.json"]
    styl["styles.css · stores/theme.ts<br/>Tailwind v4 @theme, runtime re-hue"]
    pipw["src/pip/<br/>mini window page: render · protocol (no Vue, no token)"]
  end

  subgraph daemon["dawnmaker · FastAPI + uvicorn (Python)"]
    main["__main__.py<br/>bind :0 · lockfile · handshake · watchdog"]
    app["app.py<br/>54 routes · *In models · State · Heartbeat"]
    sec["security.py<br/>LoopbackAuth: Host · Origin · Bearer / ?token= · CORS"]
    hub["events.py<br/>EventHub: ring 500 · Last-Event-ID · keepalive"]
    authd["auth.py<br/>pixiv cookie verify-then-store · X cookies file"]
    probe["probe.py<br/>tag probe · preview proxy"]
    names["names.py · speed.py<br/>NameFinder · SpeedMeter"]
  end

  subgraph engine["coreflame · engine (Python, no daemon deps)"]
    models["models.py<br/>Watch · IllustRecord · MediaRef · Tag"]
    db["db.py + migrations.py + seen.py<br/>Store · forward-only schema · visited gate"]
    jobs["jobs.py + handlers.py<br/>JobRunner · lanes · JobContext · plan"]
    pipe["pipeline.py<br/>poll · link · search_to_target · download · label · identify"]
    http["http.py + net.py + online.py<br/>SourceClient · token buckets · METER · DoH · NetWatch"]
    srcs["sources/<br/>Adapter protocol · pixiv.py · twitter.py · specs.py (glom)"]
    media["blobs.py · thumbs.py · library.py · dedupe.py · phash.py"]
    cls["kinds.py · people.py · identify.py<br/>optional [classify]: numpy + onnxruntime"]
    extra["tags.py · trash.py · bundle.py · names.py · speed.py"]
    cli["cli.py<br/>coreflame watch · poll · jobs · bundle · net · doctor"]
  end

  subgraph fs["local state"]
    dbf[("~/.reaver/reaver.db<br/>config.json · secrets.json · twitter-cookies.txt · dawnmaker.lock · models/")]
    libf[("library folder<br/>blobs/ · thumbs/ · by-character/ · trash/")]
  end

  subgraph remote["remote"]
    pixiv["www.pixiv.net ajax · i.pximg.net"]
    xcom["x.com (via gallery-dl)"]
    hf["huggingface.co (models)"]
    misc["danbooru · wikidata · speed.cloudflare.com · ipinfo"]
    gh["GitHub Releases · latest.json"]
  end

  %% shell ↔ daemon
  side -- "spawn · stdout DAWNMAKER_READY · SIGTERM" --> main
  side -- "POST /api/heartbeat every 5 s" --> sec
  %% shell ↔ webview
  apits -- "invoke daemon_endpoint" --> side
  stores -- "invoke source_login" --> authr
  bgts -- "invoke pip_* · tray_update · emit pipeline:tick" --> pipr
  bgts --> trayr
  pipr -- "window pip" --> pipw
  pipw -- "emit pip:*" --> bgts
  caps -. "IPC allowlist per window" .- lib
  lib --> side & authr & pipr & trayr
  stores -- "tauri-plugin-updater" --> gh
  %% webview ↔ daemon
  apits -- "HTTP /api/* Authorization Bearer<br/>SSE /api/events?token=<br/>img /api/media/*?token=" --> sec
  sec --> app
  pages --> comps --> stores --> apits
  comps --> i18n
  comps --> styl
  %% daemon internals
  main --> app
  app --> hub
  app --> authd & probe & names
  app -- "Depends(store): one Store per request" --> db
  app -- "submit · cancel · pause · hold" --> jobs
  jobs -- "subscribers → from_job_event" --> hub
  probe --> srcs
  %% engine internals
  jobs --> pipe
  pipe --> srcs & media & cls & db & extra
  srcs --> http
  srcs --> models
  pipe --> models
  cli --> jobs & db & extra
  %% engine ↔ state and remote
  db --> dbf
  media --> libf
  extra --> libf
  cls -- "first use downloads" --> hf
  http --> pixiv
  srcs -- "subprocess: python -m gallery_dl, or the frozen exe --gallery-dl" --> xcom
  extra --> misc
  names --> misc
```

## Provided and required interfaces

| Interface | Provider | Consumers | Shape |
|---|---|---|---|
| `DAWNMAKER_READY` line | `dawnmaker/__main__.py` | `sidecar.rs`, `docker/entrypoint.sh` | one JSON line on stdout: `{port, token, pid}`; everything else logs to stderr |
| REST `/api/*` | `dawnmaker/app.py` behind `LoopbackAuth` | `lib/api.ts`, the heartbeat thread, `curl` in dev | JSON; `Authorization: Bearer`; errors `{"error": {code, message}}`; contract in architecture §6 |
| SSE `/api/events` | `EventHub` | `lib/api.ts subscribe` | `id/event/data` frames, `Last-Event-ID` replay from a 500-event ring, keepalive comments |
| Image routes `/api/media/*`, `/api/preview/*` | `app.py` | `<img src>` in the grid and the form | `?token=` allowed here only; thumbs immutable-cached |
| Tauri commands | `src-tauri/src/*.rs` | stores, `background.ts`, `src/pip` | `invoke(name, args)`; allowlisted per window by `capabilities/*.json`; the `source-login` window has none |
| Window events | main webview and `pip` window | each other | `pipeline:tick` down, `pip:*` up; `tray:*` from Rust |
| `Adapter` protocol | `sources/base.py` | `pipeline.py`, `probe.py` | `discover(watch, since, stats)`, `fetch_media(url, referer)`; records are `IllustRecord` at the edge |
| `Handler` | `handlers.build_handlers` | `JobRunner` | `(JobContext) -> counters`, keyed by job type |
| `Labels` / `Tags` / `Identifies` | `kinds.py` / `people.py` / `identify.py` | `pipeline.py` | `None` when the `classify` extra is missing; the engine must import without it |
| SQLite file | `Store` over `migrations.py` | daemon threads (one connection each), the CLI | WAL; natural-key upserts; `jobs.cancel_requested` is the cross-process cancel |
| gallery-dl | the `gallery_dl` module run as a subprocess | `TwitterAdapter` | JSON output; cookies file and proxy passed through; owns the X protocol layer |

## What is deliberately not a component

- No background service, agent or server: the daemon lives exactly as long
  as the shell beats (Docker's `--no-heartbeat` is the dev exception).
- No image proxy: `/api/preview/*` serves only ids a probe returned.
- No second update channel: the sidecar is a bundle *resource*, so the shell
  and the daemon are one artifact and cannot skew.
