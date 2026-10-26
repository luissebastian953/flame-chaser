# 2. State machine diagrams

The states that carry policy. Each one is a column in SQLite or a field in a
store, so a restart reads the machine back exactly where it was. Collapsing
any of the first two is the bug the root `CLAUDE.md` warns about (**LB**).

## 2.1 Job (`coreflame/jobs.py`, table `jobs`)

Six states. One worker thread per lane (`pixiv`, `twitter`) claims the first
`queued` row of its lane, or an `any` job, with a conditional `UPDATE`.
Cancel and pause are columns (`cancel_requested`, `pause_requested`) read at
`ctx.check()` between records, never inside a write, so another process can
set them too.

```mermaid
stateDiagram-v2
  [*] --> queued : POST /api/jobs, CLI, retry()
  queued --> running : worker claims the row (conditional UPDATE)
  queued --> cancelled : cancel while waiting
  queued --> queued : reorder, run-now (position changes only)
  running --> running : pause_requested, held at next check(), lane kept
  running --> succeeded : handler returned counters
  running --> failed : handler raised, error stored
  running --> cancelled : cancel_requested seen at check() or stage()
  running --> queued : Offline raised, back at the FRONT, queue held
  running --> interrupted : process died, marked at next boot
  running --> queued : process died while the queue was paused, front of the queue
  succeeded --> [*]
  failed --> queued : retry (a fresh copy, visited gate makes it a resume)
  cancelled --> queued : retry (a fresh copy)
  interrupted --> queued : retry (a fresh copy)
```

Invariants: a `running` row at boot means the process died (`mark_interrupted`);
a cancel can only land between complete records because `upsert_post` is one
transaction; `total` is `NULL` when no honest denominator exists.

## 2.2 The queue hold (`JobRunner.hold`, table `queue_state`)

The queue as a whole has its own two-valued state with a *reason*. A user's
pause outranks the connection's: pausing by hand while offline makes the hold
the user's, and only the user lifts it.

```mermaid
stateDiagram-v2
  [*] --> open
  open --> held_user : POST /api/pipeline/pause {paused true}
  open --> held_offline : NetWatch says offline, or a request raised Offline
  held_offline --> open : NetWatch says online again
  held_offline --> held_user : user pauses while offline (reason becomes user)
  held_user --> open : POST /api/pipeline/pause {paused false}
  note right of held_user
    persisted in queue_state;
    a daemon that dies here comes back held,
    the running job back at the front as queued
  end note
  note right of held_offline
    workers take nothing new;
    running jobs hold at their next record boundary;
    the watch probes every 5 s
  end note
```

## 2.3 A visited post (`coreflame/seen.py`, table `seen_posts`) **LB**

Four states, four retry policies. Consulted from the search listing, where
the id is free, *before* a detail request is spent. `posts` is not the gate;
it only holds what was kept.

```mermaid
stateDiagram-v2
  [*] --> unseen
  unseen --> indexed : detail fetched, validated, upsert_post
  unseen --> skipped : rejected by config (min_bookmarks, R-18, ugoira, no_match)
  unseen --> gone : 404 / 410
  unseen --> failed : 5xx, timeout, reset (failures = 1, retry_after = +30 min)
  failed --> failed : backoff 30 min, 6 h, 1 d, 7 d
  failed --> indexed : retry succeeded
  failed --> gone : retry answered 404 / 410
  skipped --> unseen : the config that rejected it loosened (reopen_skipped, threshold compared)
  indexed --> skipped : every image deleted with "forget" (reason deleted, never reopened)
  indexed --> unseen : every image deleted without forget (row dropped, next run re-fetches)
  indexed --> [*] : never revisited
  gone --> [*] : never revisited
```

`should_fetch` is true only for `unseen` and for `failed` past its
`retry_after`. The `threshold` column stores the config value that caused a
skip, so lowering `min_bookmarks` reopens exactly the rows it would now admit.

## 2.4 A media row (`pipeline.download_pending`, table `media`)

One row per image of a post (`idx`). The crawl records the row at discover
time; the download stage moves it.

```mermaid
stateDiagram-v2
  [*] --> pending : upsert_post recorded the MediaRef (url, referer)
  pending --> failed : fetch raised (error kept, url kept)
  pending --> dupe : sha256 exists, or dHash within threshold of the same artist
  pending --> rejected : kind filter (photo, render, other) or gender rule said no
  pending --> stored : blob written, thumb made, by-character placed
  stored --> rejected : backlog relabel, or crawl-time cleanup rule (discard_unkept)
  rejected --> pending : the rule loosened (kind filter off, gender any/partial)
  stored --> trashed : delete to trash (row snapshotted into trash_items)
  trashed --> stored : Undo within 30 days
  trashed --> [*] : purge (30 days, or Empty trash)
  pending --> pending : bundle import found the blob damaged, re-fetch on next crawl
```

`dupe_of` names the stored sha a dupe resolves to; the gallery shows a dupe
row's bytes through its original. `trashed` is not a `state` value but a move
of the row into `trash_items`; it is drawn here because Undo brings the same
row back.

## 2.5 Heartbeat watchdog (`dawnmaker/app.py Heartbeat`, `__main__.watchdog`)

Layer 2 of the sidecar lifecycle. A gap is as often a sleeping laptop as a
dead shell, so the first silence is graced once.

```mermaid
stateDiagram-v2
  [*] --> alive : handshake printed, enabled unless --no-heartbeat
  alive --> alive : POST /api/heartbeat every 5 s from the shell's thread
  alive --> graced : 30 s without a beat (last reset to now - 15 s, graced = true)
  graced --> alive : a beat arrives (graced = false)
  graced --> exiting : another 15 s of silence
  alive --> exiting : SIGTERM from the shell (layer 1)
  exiting --> [*] : should_exit, hub.close() ends every SSE stream, uvicorn stops within 3 s, runner.stop(), lockfile removed
```

## 2.6 Updater (`deliverer/src/stores/updater.ts`)

```mermaid
stateDiagram-v2
  [*] --> unsupported : not inside Tauri (browser mode)
  [*] --> idle : desktop
  idle --> checking : boot after a day, daily timer, Check now
  checking --> idle : no update
  checking --> available : update found (banner in the rail)
  checking --> error : endpoint, pubkey or network failure
  available --> downloading : Download, or auto
  downloading --> ready : bytes verified against the compiled-in pubkey
  downloading --> error
  ready --> waiting : install requested but /api/health is not idle
  waiting --> ready : queue idle (polled every 5 s), install again
  ready --> installing : Restart, or auto
  installing --> [*] : shell kills the sidecar, relaunches
  installing --> error
  error --> checking : Check now
```

## 2.7 A pixiv session (`dawnmaker/auth.py`, `stores/sources.ts`)

```mermaid
stateDiagram-v2
  [*] --> absent : no PHPSESSID in secrets.json or env
  absent --> checking : POST /api/auth/pixiv (cookie from the login window or pasted)
  checking --> verified : one search request answered 200, saved 0600
  checking --> absent : 401 / 403, previous cookie restored, 401 session_rejected
  verified --> checking : daemon start (background thread), Check in Settings
  verified --> expired : the check answered 401 / 403
  verified --> verified : network error, last verdict kept, noted unreachable
  expired --> checking : Sign in again
  verified --> absent : DELETE /api/auth/pixiv
  expired --> absent : DELETE /api/auth/pixiv
```

`poll_pixiv` refuses to start in any state but `verified`, rather than
401-ing once per tag. X cookies have only `absent` and `stored`: they cannot
be verified without a timeline fetch.
