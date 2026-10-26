# 1. Use case diagram

One human actor, two external systems the crawler talks to *as that human*,
and a handful of things the system does on its own clock. Mermaid has no
use-case shape, so: rectangles are actors, stadiums are use cases, the
`Curio` subgraph is the system boundary, and `include` / `extend` are written
on the edges.

Sources: `deliverer/src/pages/*.vue` (what the user can click),
`reaver/dawnmaker/app.py` (what the daemon offers), `reaver/coreflame/cli.py`
(the same engine from a terminal), `reaver/coreflame/jobs.py` and
`reaver/dawnmaker/__main__.py` (what runs unprompted).

```mermaid
flowchart LR
  owner["Owner<br/>(the one person using it)"]
  pixiv["pixiv.net<br/>i.pximg.net"]
  x["x.com<br/>(via gallery-dl)"]
  gh["GitHub Releases<br/>latest.json"]
  clock["Timer / OS"]

  subgraph curio["Curio"]
    direction TB
    subgraph setup["Accounts and settings"]
      signin(["Sign in to a source<br/>pixiv required, X optional"])
      pick(["Choose the library folder"])
      tune(["Tune rates, resolver, proxy,<br/>duplicates, cleanup rule"])
      diag(["Diagnose the network path"])
    end
    subgraph crawl["Crawl"]
      addc(["Add or edit a character<br/>tags, terms, sources, target,<br/>kind and gender filters"])
      probe(["Validate tags live<br/>counts, preview, names"])
      run(["Run a crawl now"])
      queue(["Pause, reorder, cancel,<br/>retry, run-now a job"])
      watch(["Watch the pipeline<br/>stages, progress, log, req/min"])
      bg(["Follow progress from<br/>mini window or tray"])
    end
    subgraph gallery["Gallery"]
      browse(["Browse a character's images<br/>filters: source, kind, who, character"])
      detail(["Open a post<br/>pages, related, reveal, fullscreen"])
      tags(["Watch or ignore an observed tag"])
      del(["Delete images<br/>by image, by tag, Smart, all"])
      undo(["Undo a deletion / empty trash"])
    end
    subgraph store["Storage"]
      export(["Export the archive<br/>.curio or .zip"])
      import(["Inspect and import a bundle<br/>merge or restore"])
      usage(["See disk usage and versions"])
    end
    subgraph auto["System-initiated"]
      poll(["Crawl pixiv: discover, link, download"])
      xsearch(["Search and follow X<br/>to the character's target"])
      classify(["Label kind, people, character"])
      dedupe(["Dedupe sha256 + artist dHash"])
      thumbs(["Make a 400 px thumbnail"])
      hold(["Hold the queue while offline,<br/>resume by itself"])
      heartbeat(["Exit when the shell is gone"])
      update(["Check for an update daily,<br/>install when idle"])
      migrate(["Migrate the database at boot"])
    end
  end

  owner --> signin & pick & tune & diag
  owner --> addc & run & queue & watch & bg
  owner --> browse & detail & tags & del & undo
  owner --> export & import & usage

  addc -. "include" .-> probe
  run -. "include" .-> poll
  run -. "include" .-> xsearch
  poll -. "include" .-> dedupe
  xsearch -. "include" .-> dedupe
  dedupe -. "include" .-> thumbs
  thumbs -. "include" .-> classify
  del -. "extend" .-> undo
  import -. "include" .-> migrate
  watch -. "extend" .-> bg

  signin --> pixiv
  signin --> x
  probe --> pixiv
  poll --> pixiv
  xsearch --> x
  update --> gh
  clock --> hold & heartbeat & update
  update -. "precondition: queue idle" .-> run
```

## Actors

| Actor | Role | Notes |
|---|---|---|
| Owner | the single user; configures, runs, browses, deletes, backs up | There is no second role. The CLI (`coreflame ...`) is the same actor through another door; it shares the database and the job table, so a cancel from the terminal is honoured by the daemon. |
| pixiv.net | discovery source: tag search and artwork detail over the ajax endpoints; `i.pximg.net` serves the bytes and needs `Referer` (**LB**) | Curio acts with the owner's own session cookie, verified once before it is stored. |
| x.com | follow source: artists' timelines and a careful, target-driven search, only through `gallery-dl` as a subprocess (**LB**) | Optional. No character metadata exists there, so X never discovers; it follows what pixiv found. |
| GitHub Releases | the update channel: a signed `latest.json` and the installers | Read-only from the app's side. |
| Timer / OS | the heartbeat clock, the daily update check, the online probe, the 30-day trash sweep | What makes the "system-initiated" cases fire. |

## Use cases that carry a rule

- **Run a crawl** always plans per source: one pixiv job and one X job per
  character plus one X `timelines` sweep (`handlers.plan`). An unticked
  source is never requested.
- **Install an update** has a precondition: the job queue is idle. With a
  worker busy the updater waits and says so (architecture §8b.3).
- **Import a bundle** refuses unless the queue is paused and empty
  (409 `busy`), because it merges in one transaction over the live tables.
- **Delete images** goes to a trash folder first; permanent deletion is a
  separate, held confirmation and is refused above 500 images or 1 GB.
- **Sign in** never shows Curio a password: the site's own page opens in a
  window with no IPC, and only the session cookie travels to the daemon.
