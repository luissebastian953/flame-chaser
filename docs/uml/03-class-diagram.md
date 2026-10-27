# 3. Class diagrams

Four diagrams, one per layer, in dependency order: the engine's domain, the
engine's runtime, the daemon, the webview. Arrows only ever point *down* this
page: `dawnmaker` imports `coreflame`, `coreflame` never imports `dawnmaker`,
and `deliverer` knows neither beyond the HTTP contract (**LB**).

Type notation follows the code: Python annotations in the first three,
TypeScript in the last. `Optional~T~` stands for `T | None`.

## 3.1 Domain model (`coreflame/models.py`, `seen.py`, `config.py`)

The normalization boundary. Every adapter builds an `IllustRecord` once, at
its edge, with media in hand; nothing downstream sees a source-shaped dict.

```mermaid
classDiagram
  direction LR

  class Watch {
    <<pydantic, extra=forbid>>
    +str slug
    +str label
    +list~str~ pixiv_tags
    +list~str~ match_terms
    +int min_bookmarks
    +bool include_r18
    +list~Source~ sources
    +int target
    +bool kind_filter
    +Literal gender
    +Literal gender_mode
    +wants(source) bool
  }

  class IllustRecord {
    <<pydantic, extra=forbid>>
    +Source source
    +str external_id
    +str artist_id
    +str artist_name
    +str artist_handle
    +str title
    +str caption
    +list~Tag~ tags
    +int page_count
    +Literal illust_type
    +bool is_r18
    +Optional~datetime~ posted_at
    +datetime fetched_at
    +str permalink
    +int bookmark_count
    +list~MediaRef~ media
    +dict source_meta
    +Optional~str~ raw_sha
    +key() tuple
    +tag_raws() list~str~
  }

  class MediaRef {
    <<pydantic>>
    +int index
    +str url
    +int width
    +int height
    +Optional~str~ referer
    +str filename_hint
  }

  class Tag {
    <<pydantic, frozen>>
    +str raw
    +str norm
    +Optional~str~ translated
    +of(raw, translated)$ Tag
  }

  class DiscoverStats {
    <<dataclass>>
    +int listed
    +int gated
    +int fetched
    +int skipped
    +int gone
    +int failed
    +int highest_id
  }

  class SeenState {
    <<enum>>
    indexed
    skipped
    gone
    failed
  }

  class SkipReason {
    <<enum>>
    below_min_bookmarks
    r18_excluded
    ugoira
    no_match
    deleted
  }

  class Config {
    <<dataclass>>
    +Path home
    +Path db_path
    +Path blob_root
    +Optional~str~ pixiv_php_sessid
    +float pixiv_rate
    +Optional~str~ twitter_cookies_file
    +int twitter_timeline_limit
    +int twitter_search_limit
    +int dupe_threshold
    +str resolver
    +Optional~str~ proxy_url
    +bool identify_characters
    +Optional~dict~ cleanup_rule
    +load(path)$ Config
    +save(path) Path
    +save_secrets(path) Path
  }

  IllustRecord "1" *-- "0..*" MediaRef : media, page order
  IllustRecord "1" *-- "0..*" Tag : tags, deduped on norm
  Watch ..> IllustRecord : selects by pixiv_tags / match_terms
  SeenState ..> SkipReason : skipped carries a reason
```

Rules carried by validators: ids are `str` (snowflakes exceed JS safe
integers), datetimes are tz-aware UTC, `page_count` is reconciled with
`len(media)`, tags are deduped on `norm` (NFKC + casefold) while `raw` is kept
for pixiv's exact search.

## 3.2 Engine runtime (`coreflame/`)

```mermaid
classDiagram
  direction TB

  class Adapter {
    <<protocol>>
    +str name
    +bool supports_discovery
    +discover(watch, since, stats) Iterator~IllustRecord~
    +fetch_media(url, referer) bytes
  }

  class RawSink {
    <<protocol>>
    +put_raw(source, kind, payload, external_id) str
    +quarantine(source, external_id, raw_sha, error, extracted)
  }

  class PixivAdapter {
    +discover(watch, since, stats) Iterator~IllustRecord~
    +probe_tag(tag, include_r18) tuple
    +twitter_handle(user_id) Optional~str~
    +fetch_media(url, referer) bytes
    +close()
  }

  class TwitterAdapter {
    +available() bool
    +timeline(handle, since, limit) list
    +search(term, since, limit) list
    +search_page(term, cursor, limit) list
    +matches(rec, watch) bool
    +fetch_media(url, referer) bytes
    +close()
  }

  class SourceClient {
    +get(url, bucket) Response
    +get_json(url, bucket) Any
    +limit_endpoint(name, rate)
    +close()
  }
  class TokenBucket {
    +float rate
    +float capacity
    +take(n)
  }
  class Meter {
    +declare(key, label, rate)
    +bind(job_id)
    +hit(key)
    +snapshot() list
    +per_job() dict
  }
  class DohResolver {
    +resolve(host) str
    +clear()
  }
  class NetWatch {
    +check() bool
    +failed() bool
    +start(active)
    +stop()
    +list listeners
  }

  class Store {
    +Connection conn
    +Seen seen
    +upsert_watch(w) int
    +watches() list~Watch~
    +put_raw(...) str
    +raws_for(source, kind) Iterator
    +quarantine(...)
    +upsert_post(rec, slug) bool
    +mark_post_gone(source, id) bool
    +pending_media(limit, source) list
    +mark_media(source, id, idx, state, ...)
    +set_kind(sha, kind, scores, model)
    +set_people(sha, people)
    +set_identity(sha, identity)
    +phashes_for_artist(artist_id) list
    +sha_exists(sha) bool
    +watermark(source, feed) Optional~str~
    +set_watermark(source, feed, value)
    +record_extraction(...)
    +tx() Connection
    +close()
  }

  class Seen {
    +should_fetch(source, id) bool
    +get(source, id) Optional~SeenRow~
    +mark(source, id, state, reason, threshold)
    +mark_failed(source, id, reason) str
    +reopen_skipped(source, reason, threshold) int
    +stats(source) dict
  }

  class BlobStore {
    +Path root
    +path_for(sha, ext) Path
    +exists(sha, ext) bool
    +put(data, ext) tuple
  }
  class ThumbStore {
    +path_for(sha) Path
    +make(sha, data, px) Optional~Path~
  }
  class LibraryView {
    +LinkMode mode
    +place(blob, slug, filename) Optional~Path~
    +remove(slug, filename)
    +clear()
    +orphans(live) list
  }

  class Job {
    <<dataclass>>
    +str id
    +str type
    +dict params
    +str state
    +Optional~str~ stage
    +int done
    +Optional~int~ total
    +dict counters
    +Optional~str~ error
    +str lane
    +Optional~str~ worker
    +float position
    +bool paused
  }
  class JobContext {
    +Store store
    +Job job
    +dict live
    +check()
    +stage(name)
    +progress(done, total)
    +item(message)
    +tally(key, n)
    +log(message, level)
    +emit(kind, message, level)
  }
  class JobRunner {
    +dict handlers
    +tuple lanes
    +list subscribers
    +list on_hold
    +submit(store, type, params)$ str
    +cancel(store, jid) bool
    +pause(store, jid, on) bool
    +reorder(store, ids)$ list
    +retry(store, jid)$ Optional~str~
    +run_now(store, jid)$ bool
    +hold(on, reason)
    +held() bool
    +held_reason() Optional~str~
    +workers() list
    +start()
    +stop(timeout)
    +run_pending(store) int
  }
  class Adapters {
    +PixivAdapter pixiv
    +TwitterAdapter twitter
    +BlobStore blobs
    +Optional~Labels~ labeler
    +Optional~Tags~ tagger
    +Optional~Identifies~ identifier
    +Optional~Detects~ detector
    +close()
  }
  class pipeline {
    <<module>>
    +poll_pixiv(store, adapter, watch, ctx) RunStats
    +resolve_artist_links(store, adapter, ctx) RunStats
    +poll_twitter(store, adapter, watches, ctx) RunStats
    +search_to_target(store, adapter, watch, target, ctx) RunStats
    +download_pending(store, blobs, pixiv, twitter, threshold, ctx) RunStats
    +label_pending(...) RunStats
    +people_pending(...) RunStats
    +identify_pending(...) RunStats
    +discard_unkept(...) RunStats
  }
  class dedupe {
    <<module>>
    +classify(store, data, sha, artist_id, threshold) DupeVerdict
  }
  class Labels {
    <<protocol>>
    +label(data) Label
  }
  class Tags {
    <<protocol>>
    +people(data) People
  }
  class Identifies {
    <<protocol>>
    +identify(data, people) Identity
  }
  class Detects {
    <<protocol>>
    +score(data) float
  }

  Adapter <|.. PixivAdapter
  Adapter <|.. TwitterAdapter
  RawSink <|.. Store
  PixivAdapter --> SourceClient : ajax + pximg, Referer
  PixivAdapter --> RawSink : put_raw, quarantine
  TwitterAdapter --> RawSink
  TwitterAdapter ..> gallery_dl : subprocess of our interpreter
  SourceClient *-- TokenBucket : global + per endpoint
  SourceClient --> Meter : METER, process-wide
  SourceClient --> DohResolver : resolver = doh
  SourceClient --> NetWatch : transport failure asks failed()
  Store *-- Seen
  JobRunner "1" --> "2" JobContext : one running per lane
  JobRunner ..> Job : rows in jobs
  JobRunner --> NetWatch : hold on offline
  JobContext --> Store : one connection per worker thread
  JobContext --> Meter : bind(job_id)
  Adapters *-- PixivAdapter
  Adapters *-- TwitterAdapter
  Adapters *-- BlobStore
  Adapters o-- Labels
  Adapters o-- Tags
  Adapters o-- Identifies
  Adapters o-- Detects
  pipeline ..> Adapters : built per job (handlers.py)
  pipeline ..> Store
  pipeline ..> dedupe
  pipeline ..> ThumbStore : 400 px WebP at ingest
  pipeline ..> LibraryView : by-character hardlink
  pipeline ..> JobContext : check, stage, progress, tally
  dedupe ..> Store : sha_exists, phashes_for_artist
```

`handlers.build_handlers` maps a job type (`poll`, `timelines`, `link`,
`media`, `tags`, `label`, `export`) to a function `(JobContext) -> counters`;
`handlers.plan` splits one `poll` request into per-source jobs. The classifier
protocols (`Labels`, `Tags`, `Identifies`, `Detects`) have ONNX implementations
behind the optional `classify` extra and are `None` when numpy/onnxruntime are
absent, so the engine stays importable without them (`Detects` is the AI-or-hand
detector of `origin.py`; pixiv's flag and AI hashtags are read without it).

## 3.3 Daemon (`dawnmaker/`)

```mermaid
classDiagram
  direction LR

  class State {
    +Config cfg
    +JobRunner runner
    +EventHub hub
    +str token
    +int port
    +Heartbeat heartbeat
    +Prober prober
    +NameFinder names
    +SpeedMeter speed
    +Auth auth
    +BlobStore blobs
    +ThumbStore thumbs
    +open_store() Store
  }
  class Heartbeat {
    +float timeout
    +bool enabled
    +bool graced
    +beat()
    +expired() bool
  }
  class EventHub {
    +publish(type, data) int
    +close()
    +from_job_event(ev)
    +replay(last_id) list
    +stream(last_id, live, keepalive) Iterator~str~
    +last_id() int
  }
  class LoopbackAuth {
    <<BaseHTTPMiddleware>>
    +str token
    +set hosts
    +bool dev
    +dispatch(request, call_next)
  }
  class Auth {
    +pixiv_status() PixivStatus
    +verify_pixiv() PixivStatus
    +set_pixiv(sessid) PixivStatus
    +clear_pixiv()
    +set_twitter(auth_token, ct0) Path
    +clear_twitter()
    +twitter_status() dict
  }
  class Prober {
    +probe_tag(tag, include_r18) TagProbe
    +probe(store, tags, include_r18) dict
    +thumb(illust_id) Optional~tuple~
    +reset()
  }
  class NameFinder {
    +find(queries, refresh) dict
    +reset()
  }
  class SpeedMeter {
    +run(full) dict
    +snapshot() dict
    +connection() Connection
  }
  class FastAPI_app {
    <<create_app(state, dev)>>
    +54 routes under /api
    +Depends(store) one Store per request
    +HTTPException(code, dict)
  }
  class InModels {
    <<pydantic request bodies>>
    PixivAuthIn
    TwitterAuthIn
    ProbeIn
    WatchIn
    NamesIn
    JobIn
    PauseIn
    ReorderIn
    TagAction
    CleanupRuleIn
    ShasIn
    DeleteIn
    SmartIn
    PurgeIn
    SpeedIn
    BundleExportIn
    BundleImportIn
    ConfigIn
  }

  FastAPI_app --> State : closure
  FastAPI_app --> LoopbackAuth : add_middleware
  FastAPI_app ..> InModels : validates bodies
  State *-- Heartbeat
  State *-- Prober
  State *-- NameFinder
  State *-- SpeedMeter
  State *-- Auth
  State --> EventHub
  State --> JobRunner : coreflame
  State ..> Store : open_store() per request
  EventHub ..> JobRunner : subscriber from_job_event
  JobRunner --> EventHub : on_hold publishes pipeline.paused
  Prober --> PixivAdapter : make_pixiv(cfg), one listing page per tag
  Auth --> Config : save_secrets 0600
```

## 3.4 Webview and shell (`deliverer/`)

Pinia option stores call `lib/api.ts`; `lib/types.ts` mirrors
`dawnmaker/app.py` and is the only contract the webview has. The Rust side is
a handful of commands the webview `invoke`s.

```mermaid
classDiagram
  direction TB

  class api {
    <<lib/api.ts>>
    +discover() Promise~Endpoint~
    +get(path) Promise~T~
    +post(path, body) Promise~T~
    +put(path, body) Promise~T~
    +patch(path, body) Promise~T~
    +del(path) Promise~T~
    +authedUrl(path) string
    +mediaUrl(sha, kind) string
    +subscribe(onEvent, types) unsubscribe
  }
  class types {
    <<lib/types.ts>>
    Watch
    Job
    JobState
    Lane
    PipelineState
    GalleryItem
    GalleryPage
    PostDetail
    PostMedia
    ProbeResult
    SourcesStatus
    Health
    DeletePreview
    SmartResult
    BundleInspect
    StorageUsage
  }
  class useEndpoint {
    +bool ready
    +Health health
    +boot()
    +refresh()
  }
  class useSources {
    +SourcesStatus status
    +load()
    +connectViaWindow(source)
    +submit(source, cookies)
    +verifyPixiv()
    +disconnect(source)
    +dismiss()
  }
  class useJobs {
    +Job[] jobs
    +DaemonEvent[] events
    +PipelineState pipeline
    +running
    +queued
    +runsToday
    +slots
    +offline
    +load()
    +loadPipeline()
    +submit(type, params)
    +submitMany(type, params)
    +cancel(id)
    +cancelAll()
    +pauseJob(id, paused)
    +pauseQueue(paused)
    +retry(id)
    +runNow(id)
    +reorder(ids)
    +listen()
  }
  class useLibrary {
    +Watch[] watches
    +GalleryItem[] items
    +filters per slug
    +loadWatches()
    +saveWatch(w, isNew)
    +deleteWatch(slug)
    +loadGrid(slug, reset)
    +loadKinds(slug)
    +loadCharacters(slug)
    +setShow / setWho / setCharacter / setSource / setOrder
    +loadTags(slug)
    +tagAction(slug, tag, action)
    +openDetail(source, id)
  }
  class useDeletion {
    +DeleteMode mode
    +Set selected
    +enter(slug, mode)
    +toggle(sha)
    +range(visible, sha)
    +mark(shas)
    +toggleTerm(kind, value, label, query)
    +setSmart(patch)
    +loadSmart()
    +loadEverything(query)
    +exit()
  }
  class useBackground {
    +mode mini|notify|none
    +PipPlacement placement
    +supported, reason wayland|browser
    +set(patch)
    +probe()
    +persist()
  }
  class useUpdater {
    +phase
    +schedule()
    +check()
    +download()
    +install()
    +setAuto(v)
    +daemonMismatch
  }
  class useTheme {
    +apply()
  }
  class useToasts
  class useViewer
  class useNetwork
  class useFormats
  class useCharacterDefaults

  class pages {
    <<router.ts>>
    Gallery
    CharacterDetail
    Config
    PipelineList
    PipelineDetail
    Settings
  }
  class background_ts {
    <<lib/background.ts>>
    +PIP_DELAY 1500
    +TICK_MS 500
    +buildTick(...) PipTick
  }
  class pip_window {
    <<src/pip, no Vue, no token>>
    +render(tick)
    +emit pip:ready, pip:pause-all, pip:dismiss, pip:open-lane, pip:placed
  }

  class RustCommands {
    <<src-tauri>>
    +daemon_endpoint() Endpoint
    +source_login(source) cookies
    +shutdown_app()
    +pip_supported() Support
    +pip_open(placement, height) bool
    +pip_close()
    +pip_resize(height)
    +pip_snap(reduced) Placement
    +tray_update(tooltip, paused, labels)
    +show_main()
  }
  class Sidecar {
    <<Rust state>>
    +Mutex~Option~Child~~ child
    +Mutex~Option~Endpoint~~ endpoint
    +spawn(app) Endpoint
    +shutdown(app)
    -heartbeat(app, endpoint) thread
  }
  class Endpoint {
    +u16 port
    +String token
    +u32 pid
  }

  pages --> useLibrary
  pages --> useJobs
  pages --> useDeletion
  pages --> useSources
  pages --> useUpdater
  useEndpoint --> api : discover, /api/health
  useSources --> api
  useSources --> RustCommands : source_login (desktop)
  useJobs --> api : /api/jobs, /api/pipeline, subscribe
  useLibrary --> api : /api/watches, /api/gallery
  useDeletion --> api : /gallery/slug/delete, /trash
  useUpdater --> useEndpoint : install gate reads health.idle
  useUpdater --> RustCommands : tauri-plugin-updater
  background_ts --> useJobs
  background_ts --> useBackground
  background_ts --> RustCommands : pip_open, tray_update
  background_ts --> pip_window : emit pipeline tick
  pip_window --> RustCommands : pip_resize, pip_snap
  api ..> types
  api --> RustCommands : daemon_endpoint (desktop) or VITE_DAEMON_* (browser)
  RustCommands --> Sidecar
  Sidecar *-- Endpoint
```

The mini window has no token and never fetches: everything it shows arrives
in a `PipTick` from the main window, and every click comes back as a `pip:*`
event (`src/pip/protocol.ts`).
