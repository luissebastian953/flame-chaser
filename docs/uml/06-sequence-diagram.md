# 6. Sequence diagrams

Messages between the four parties that exist at runtime: the Tauri shell
(Rust), the webview (Vue), the daemon (`dawnmaker` over `coreflame`) and the
sites. Six flows live in [`../flows.md`](../flows.md) already and are not
repeated: process lifecycle (§b), sign-in (§e), the character-form probe
(§f), deleting images (§m), the mini window (§n), and the daemon's request
security as a decision chart (§i). The six here fill the gaps.

## 6.1 Boot: handshake, token, first paint

```mermaid
sequenceDiagram
  autonumber
  participant S as Tauri shell (sidecar.rs)
  participant D as dawnmaker
  participant W as Webview (App.vue)
  S->>D: spawn, stdout piped (dev python -m dawnmaker, release resources/sidecar/dawnmaker)
  D->>D: Config.load, bind 127.0.0.1:0 and listen, take dawnmaker.lock
  D->>D: Store(): migrations.apply (backup, forward-only, min_app_version)
  D->>D: JobRunner(): mark running jobs interrupted, or requeue if the queue was held
  D-->>S: DAWNMAKER_READY {port, token, pid}  (the only line on stdout)
  S->>S: Sidecar.endpoint = Endpoint, start heartbeat thread
  S->>W: window shown, Vite bundle loads
  W->>W: useTheme().apply() before first paint
  W->>S: invoke daemon_endpoint
  S-->>W: {port, token, pid}
  W->>D: GET /api/health  Authorization Bearer
  D-->>W: {ok, version, idle, library_root, schema_version, ...}
  W->>D: GET /api/sources/status
  D-->>W: pixiv {authed, verified null}, twitter {...}
  alt pixiv not authed and gate not dismissed
    W->>W: AuthGate
  else
    W->>W: router → /gallery
  end
  W->>D: GET /api/events?token=  (EventSource)
  D-->>W: replay after Last-Event-ID, then live, keepalive every 15 s
  loop every 5 s
    S->>D: POST /api/heartbeat
  end
```

The token never touches a file or argv; the stdout pipe is private to the
parent. The webview is a different origin from the daemon, so every call is
CORS and the daemon reflects only an allowed origin.

## 6.2 A crawl, as the Pipeline page sees it

```mermaid
sequenceDiagram
  autonumber
  participant W as Webview (jobs store)
  participant A as dawnmaker (app.py)
  participant R as JobRunner
  participant P as pixiv worker thread
  participant X as X worker thread
  participant H as EventHub
  participant PX as pixiv.net
  participant GD as gallery-dl → x.com

  W->>A: POST /api/jobs {type poll, params {watches [ganyu]}}
  A->>A: handlers.plan → [(poll pixiv), (poll twitter target 100), (timelines)]
  A->>R: submit × 3 (rows queued, position)
  A-->>W: 202 {job_id, job_ids}
  R->>R: kick()
  par pixiv lane
    P->>P: _take: conditional UPDATE queued → running
    P->>H: job.started {job_id, type, worker pixiv}
    loop each tag, each listing page
      P->>PX: GET ajax/search/artworks/<tag> s_tag_full
      PX-->>P: ids, newest first
      P->>P: watermark check, seen.should_fetch (no request for gated ids)
      loop each unseen id
        P->>PX: GET ajax/illust/<id>, then /pages
        PX-->>P: detail json
        P->>P: put_raw, extract, IllustRecord, upsert_post, seen indexed
        P->>H: job.item {external_id, action new}
        P->>P: ctx.check()  (cancel / pause / offline land here)
      end
      P->>H: job.progress {done, total null}
    end
    P->>P: tags rebuild, link (profile → X handle), download pending pixiv media
    P->>H: library.media {sha256, slug} per stored image
    P->>H: job.finished {state succeeded, counters, seconds}
  and X lane
    X->>X: _take the twitter poll
    X->>H: job.started
    loop until N kept, 10×N listed, or history ends
      X->>GD: search <term> filter:images since/until cursor
      GD-->>X: entries json
      X->>X: seen gate, match terms, upsert_post, download, dedupe (artist-scoped dHash)
      X->>H: job.progress {done, total N}
    end
    X->>H: job.finished
    X->>X: _take the timelines job, same shape over followed handles
  end
  H-->>W: SSE frames id/event/data
  W->>W: jobs store: apply events, poll GET /api/pipeline every 3 s for req/min
  W->>A: GET /api/jobs/{id}
  A-->>W: job + last 200 log lines
```

## 6.3 A thumbnail reaches the grid

```mermaid
sequenceDiagram
  participant G as Gallery grid (GalleryTile)
  participant W as lib/api.ts
  participant D as dawnmaker
  participant FS as library folder
  G->>W: mediaUrl(sha, thumb)
  W-->>G: http://127.0.0.1:port/api/media/sha/thumb?token=...
  G->>D: GET /api/media/{sha}/thumb?token=   (an img src, no headers possible)
  D->>D: LoopbackAuth: Host ok, Origin ok, ?token= allowed on /api/media/*, constant-time compare
  D->>FS: thumbs/aa/bb/sha.webp
  alt thumbnail exists
    D-->>G: 200 image/webp, Cache-Control public, max-age 31536000, immutable
  else missing thumb, blob present
    D->>FS: blobs/aa/bb/sha.ext
    D->>D: ThumbStore.make (400 px WebP), write
    D-->>G: 200 image/webp
  else neither
    D-->>G: 404
  end
  Note over G,D: never file:// or asset:, the webview has no filesystem (LB)
```

## 6.4 Update install, gated on an idle queue

```mermaid
sequenceDiagram
  participant T as timer / Settings › Updates
  participant U as updater store
  participant P as tauri-plugin-updater
  participant GH as GitHub Releases
  participant D as dawnmaker
  participant S as Tauri shell
  T->>U: schedule(): last check older than a day, or Check now
  U->>P: check()
  P->>GH: GET releases/latest/download/latest.json
  GH-->>P: {version, platforms {url, signature}}
  P-->>U: update available?  → phase available, banner in the rail
  U->>P: download()
  P->>GH: GET bundle
  P->>P: verify minisign against compiled-in pubkey
  P-->>U: phase ready
  U->>D: GET /api/health
  D-->>U: {idle false}
  U->>U: phase waiting
  loop every 5 s
    U->>D: GET /api/health
    D-->>U: {idle true}
  end
  U->>P: install()
  P->>S: relaunch
  S->>D: kill child (layer 1)
  Note over D: a crawl is never cut between a blob write and its media row
  S->>S: new version starts, sidecar in resources/ is the new daemon
  U->>D: GET /api/health → version must equal __APP_VERSION__ (daemonMismatch)
```

## 6.5 The internet goes away mid-crawl, and comes back

```mermaid
sequenceDiagram
  participant P as worker thread
  participant C as SourceClient
  participant N as NetWatch (online.py)
  participant R as JobRunner
  participant H as EventHub
  participant W as Pipeline page / mini window
  P->>C: get(url)
  C--xC: transport error (DNS, connect, TLS, timeout)
  C->>N: failed()
  N->>N: TCP connect to 1.1.1.1 / 8.8.8.8 / 9.9.9.9 : 443, any one answers = online
  alt reachable
    N-->>C: online
    C->>C: ordinary retry with backoff (429 / 5xx policy)
  else unreachable
    N-->>C: offline
    C-->>P: raise Offline
    P->>R: _run_one catches Offline
    R->>R: hold(True, offline), requeue_one → front of the queue, state queued
    R->>H: pipeline.paused {paused true, reason offline}
    H-->>W: "paused · no internet"
    loop every 5 s while offline
      N->>N: probe
    end
    N->>R: _on_connectivity(online)
    alt reason still offline
      R->>R: hold(False), wake workers
      R->>H: pipeline.paused {paused false, reason null}
      P->>P: _take the same job again, the visited gate makes it a resume
    else user paused meanwhile
      Note over R: the hold is the user's now, only they lift it
    end
  end
```

## 6.6 Backup: export as a job, import as a request

```mermaid
sequenceDiagram
  participant W as BackupPanel
  participant A as dawnmaker
  participant R as JobRunner (any lane)
  participant B as bundle.py
  participant FS as disk
  W->>A: POST /api/bundle/export {format curio, images, thumbs, secrets, ui}
  A->>R: submit export job (lane any: no remote request)
  A-->>W: 202 {job_id, path}
  R->>B: export(store, blobs, thumbs, opts, progress, check)
  B->>FS: sqlite backup API → consistent snapshot (never a file copy: WAL)
  B->>FS: write <path>.part: manifest, db, settings, ui blob, blobs, thumbs, index
  B->>B: progress per stage: snapshot · images · thumbs · verify
  B->>FS: re-read and verify .part, then rename to <path>
  R-->>W: job.finished via SSE
  Note over W,A: Import: see the activity diagram §5.3. It runs inside the request,<br/>refused with 409 busy unless the queue is paused and empty.
```
