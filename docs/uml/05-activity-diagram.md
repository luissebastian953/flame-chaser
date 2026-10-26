# 5. Activity diagrams

Swimlanes are `subgraph`s; diamonds are decisions; the thick bars are
forks and joins. The full crawl pipeline with every gate is drawn in
[`../flows.md`](../flows.md) §c; here the view is the *activity* across
actors, plus two activities flows.md does not have.

## 5.1 Run a crawl

From the owner's click to a thumbnail in the grid. The two lanes run in
parallel because they hit different hosts; a job never crosses lanes.

```mermaid
flowchart TD
  subgraph owner["Owner"]
    a0(["Crawl page: Run now"])
  end
  subgraph web["Webview"]
    a1["POST /api/jobs {type poll, watches}"]
    a2["route to /pipeline, EventSource open"]
    a9["grid inserts thumb on library.media"]
  end
  subgraph daemon["dawnmaker"]
    b1["handlers.plan: per character<br/>pixiv poll + X poll, then X timelines"]
    b2["JobRunner.submit × n, 202 {job_ids}"]
    fork1{{"fork: one worker per lane"}}
    join1{{"join: lanes idle"}}
    b8["EventHub publishes job.* and library.media"]
  end
  subgraph px["pixiv worker"]
    c1["take queued pixiv/any job"]
    c2["stage discover: each tag listing,<br/>watermark then seen gate, detail, upsert"]
    c3["stage tags: rebuild tag_stats"]
    c4["stage link: pixiv profile → X handle"]
    c5["stage download: pending pixiv media"]
    c6["succeeded / failed / cancelled"]
  end
  subgraph xw["X worker"]
    d1["take queued twitter/any job"]
    d2{"X ready?<br/>gallery-dl + cookies"}
    d3["search_to_target: newest-first per term,<br/>then further back, stop at N kept"]
    d4["timelines: followed handles since watermark"]
    d5["stage download: pending X media"]
    d6["succeeded / failed / cancelled"]
    d7["skipped, log says why"]
  end

  a0 --> a1 --> b1 --> b2 --> fork1
  a1 --> a2
  fork1 --> c1 --> c2 --> c3 --> c4 --> c5 --> c6 --> join1
  fork1 --> d1 --> d2
  d2 -- no --> d7 --> join1
  d2 -- yes --> d3 --> d5 --> d6 --> join1
  d1 -. "timelines job, after the polls" .-> d4 --> d5
  c2 & c5 & d3 & d5 -. "stage · progress · item · log" .-> b8
  b8 -. "SSE" .-> a2
  c5 & d5 -. "library.media" .-> b8 --> a9
  join1 --> e(["/api/health idle = true"])
```

Between any two records a worker calls `ctx.check()`: that is where a
cancel, a pause (hold in place, lane kept) or an `Offline` (job back at the
front, queue held) lands. Never inside a write.

## 5.2 Ingest one image (`pipeline.download_pending`)

The activity behind every `pending` media row. Order matters: the cheap
checks come first, the classifier (if installed) only runs on bytes that
would otherwise be kept, and nothing is written to the library before the
dedupe verdict.

```mermaid
flowchart TD
  s(["pending media row"]) --> f["fetch bytes<br/>pixiv: SourceClient with Referer<br/>X: gallery-dl client, orig then 4096x4096"]
  f -- "transport failure, internet gone" --> off(["raise Offline: job to the front, queue held"])
  f -- "other error" --> fail["state = failed, error kept, url kept"]
  f -- ok --> h["sha256"]
  h --> e{"sha exists<br/>as stored?"}
  e -- yes --> dupe["state = dupe, dupe_of = sha"]
  e -- no --> ph["dHash"]
  ph --> near{"Hamming ≤ threshold<br/>vs this artist's hashes?"}
  near -- yes --> dupe
  near -- no --> kind{"kind filter on<br/>and labeler present?"}
  kind -- "photo · render · other" --> rej["state = rejected, error = kind"]
  kind -- "illustration · screencap · off" --> gen{"gender rule set<br/>and tagger present?"}
  gen -- "rule says no" --> rej2["state = rejected, error = gender:…"]
  gen -- "ok · any" --> put["BlobStore.put → blobs/aa/bb/sha.ext"]
  put --> th["ThumbStore.make → thumbs/…/sha.webp 400 px"]
  th --> row["mark_media stored: sha, phash, bytes, w×h, variant"]
  row --> place["LibraryView.place → by-character/slug/… hardlink,<br/>for every watch the post belongs to"]
  place --> ident{"identify_characters on?"}
  ident -- yes --> id["Identifier: WD + Camie vouch → image_identity, image_characters"]
  ident -- no --> ev
  id --> rule{"cleanup rule active and<br/>verdict says discard?"}
  rule -- yes --> disc["discard: row rejected, blob to trash"]
  rule -- no --> ev["emit item stored, library.media"]
  dupe --> ev2(["next row"])
  rej --> ev2
  rej2 --> ev2
  fail --> ev2
  disc --> ev2
  ev --> ev2
```

A `rejected` row keeps its url. Loosening the rule that rejected it
(`Store.upsert_watch` compares old and new) puts it back to `pending`, and
the next download judges it again.

## 5.3 Import a bundle (`bundle.import_`, `POST /api/bundle/import`)

Verification gates before anything touches the live archive; one
transaction for the merge; bytes move only after the commit.

```mermaid
flowchart TD
  s(["Settings › Storage › Backup › Import"]) --> insp["POST /api/bundle/inspect {path}"]
  insp --> fmt{"codec?"}
  fmt -- "neither zip nor .curio" --> e1(["400 not_a_bundle"])
  fmt -- ok --> man["read manifest: app_version, schema_version, counts"]
  man --> newer{"schema newer than this daemon?"}
  newer -- yes --> e2(["400 bundle_too_new"])
  newer -- no --> conf["conflicts: same slug, or another slug with overlapping pixiv tags"]
  conf --> ui["UI shows characters with keep / take / merge per collision"]
  ui --> go["POST /api/bundle/import {mode, policies, salvage}"]
  go --> busy{"queue paused and empty?"}
  busy -- no --> e3(["409 busy"])
  busy -- yes --> ver["verify every entry: crc32 chunks + sha256"]
  ver -- "damaged entry, salvage off" --> e4(["400 damaged, names the entries"])
  ver -- "damaged entry, salvage on" --> note["note it; a hurt image goes back to pending"]
  ver -- ok --> stage["stage under ~/.reaver/import/stamp/"]
  note --> stage
  stage --> dbchk["integrity_check + migrate the STAGED db copy"]
  dbchk -- fails --> e5(["400 damaged database, nothing changed"])
  dbchk -- ok --> tx["ATTACH staged db, ONE transaction"]
  tx --> mode{"mode"}
  mode -- merge --> merge["watches by policy · posts newer fetched_at wins ·<br/>media ours wins · seen gone/skipped free, indexed with post, failed never"]
  mode -- restore --> rest["replace the merge tables wholesale"]
  merge --> commit["COMMIT"]
  rest --> commit
  commit --> blobs["move bytes into blobs/ and thumbs/,<br/>new images get the artist-scoped dHash check"]
  blobs --> cfg["apply portable settings (keep / take), secrets if opted in"]
  cfg --> done(["{characters, posts, placed, dupes, refetch, damaged}"])
```
