# Curio - UML

Eight views of one system, each drawn from the code in the repo (file names
are given so you can check). They are deliberately short: the *why* lives in
[`../design/architecture.md`](../design/architecture.md), the runtime *how* in
[`../flows.md`](../flows.md), and the engineering trade-offs in
[`../design/system-design.md`](../design/system-design.md). This folder is
the *what*: who uses it, what the pieces are, how they relate, and where
they run.

| # | Diagram | Answers | File |
|---|---|---|---|
| 1 | Use case | who does what with Curio, and what the system does on its own | [`01-use-case.md`](01-use-case.md) |
| 2 | State machine | the lifecycles that carry policy: a job, a visited post, a media row, the queue hold, the heartbeat, the updater, a session | [`02-state-machine.md`](02-state-machine.md) |
| 3 | Class | the engine's types and their relations; the daemon's objects; the webview's stores | [`03-class-diagram.md`](03-class-diagram.md) |
| 4 | Object | one character, one artwork, two images, as rows at a moment in time | [`04-object-diagram.md`](04-object-diagram.md) |
| 5 | Activity | a crawl from "Run" to a thumbnail on screen; downloading one image; deleting | [`05-activity-diagram.md`](05-activity-diagram.md) |
| 6 | Sequence | the messages between shell, webview, daemon and the sites | [`06-sequence-diagram.md`](06-sequence-diagram.md) |
| 7 | Component | the parts, their interfaces, and the one allowed dependency direction | [`07-component-diagram.md`](07-component-diagram.md) |
| 8 | Deployment and versioning | where each artifact runs, how it is built, and how a version number travels | [`08-deployment-diagram.md`](08-deployment-diagram.md) |

## Reading the diagrams

- Everything is [Mermaid](https://mermaid.js.org/); GitHub, VS Code (with the
  Mermaid preview extension) and most Markdown viewers render it inline.
  Mermaid has no native use-case or object diagram, so those two use the
  flowchart and class syntaxes with the conventional notation written in.
- Vocabulary: **deliverer** is the Tauri shell plus the Vue webview (the app
  you open), **dawnmaker** the FastAPI daemon, **coreflame** the crawl engine
  both the daemon and the CLI drive. "pixiv" and "X" are the two sources;
  the engine still spells X `twitter`, as the code does.
- Load-bearing decisions (root `CLAUDE.md`) are marked **LB** where a
  diagram touches one. Changing what the diagram shows there is a design
  change, not a refactor.

## Keeping them true

A diagram that disagrees with the code is worse than none. When a feature
lands (see the `feature-workflow` skill):

- a new job type, state or retry policy: `02-state-machine.md`
- a new model field, table or store: `03-class-diagram.md` and the ER
  diagram in `system-design.md`
- a new route or event: `06-sequence-diagram.md` if a flow changed, and
  architecture.md §6 always
- a new process, window, binary or CI job: `07-component-diagram.md`,
  `08-deployment-diagram.md`

`scripts/check-dash.sh` applies here too: the plain hyphen-minus, never the
long dash.
