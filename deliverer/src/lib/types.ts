/** Shapes from docs/design/architecture.md §6. Keep in step with dawnmaker/app.py. */
export type Source = 'pixiv' | 'twitter';

export type Gender = 'any' | 'female' | 'male';

export type GenderMode = 'full' | 'partial';

export interface Watch {
  slug: string;
  label: string;
  pixiv_tags: string[];
  match_terms: string[];
  min_bookmarks: number;
  include_r18: boolean;
  /** which sources this character is crawled from; both by default */
  sources: Source[];
  /** posts per run: new KEPT posts one crawl collects (1..1000) */
  target: number;
  /** the image-kind filter: keep only illustrations + anime screencaps */
  kind_filter: boolean;
  /** who may be in the picture (coreflame/people.py) */
  gender: Gender;
  /** full = only that gender; partial = the other one as a minority */
  gender_mode: GenderMode;
  post_count?: number;
  /** distinct artists over the character's live posts */
  artist_count?: number;
  latest_posted_at?: string | null;
  cover_sha?: string | null;
  reopened?: number;
}

export type JobState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';

/** one worker per source (coreflame/jobs.py): each site sees one request stream */
export type Lane = 'pixiv' | 'twitter';

export interface Job {
  id: string;
  type: string;
  params: Record<string, unknown>;
  state: JobState;
  stage: string | null;
  done: number;
  total: number | null;
  /** running tallies mid-run (posts, new, stored, listed, gated, …); final counts after */
  counters: Record<string, number>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** the worker that may take it; `any` = no remote request, either one */
  lane: Lane | 'any';
  /** the worker that ran it; null until it starts */
  worker: Lane | null;
  /** queue order (reorder / run now); lower runs first */
  position: number;
  /** held at its next record boundary, keeping its worker */
  paused: boolean;
  /** requests this job sent in the last minute */
  req_per_min: number;
  log?: LogLine[];
}

export interface WorkerSlot {
  lane: Lane;
  job_id: string | null;
}

/** a rate budget and what it actually sent in the last minute */
export interface RateBudget {
  key: string;
  label: string;
  /** requests per second; null = paced by something else (gallery-dl) */
  rate: number | null;
  per_min: number;
}

/** why the queue is held: Pause queue, or the internet went away (it resumes on its own) */
export type PauseReason = 'user' | 'offline';

export interface PipelineState {
  paused: boolean;
  pause_reason: PauseReason | null;
  /** the daemon's own probe: false while the queue waits for the connection */
  online: boolean;
  workers: WorkerSlot[];
  budgets: RateBudget[];
  req_per_min: number;
}

export interface LogLine {
  seq: number;
  at: string;
  level: string;
  kind: string;
  message: string;
  data: Record<string, unknown>;
}

export interface GalleryItem {
  sha256: string;
  source: string;
  external_id: string;
  idx: number;
  width: number;
  height: number;
  posted_at: string | null;
  artist_name: string;
  title: string;
  thumb_url: string;
  /** what the image IS (coreflame/kinds.py); null = not labeled yet */
  kind: ImageKind | null;
  /** whether its character is named (coreflame/identify.py) */
  identity: IdentState;
  /** how it was made (coreflame/origin.py): AI-made, hand-drawn, or not judged yet */
  origin: OriginState;
  /** who said so; null while pending */
  origin_by: OriginBy | null;
  /** the one badge the daemon picked when several apply; null = a normal illustration */
  label: ImageLabel | null;
  label_source: LabelSource;
}

/**
 * ai = AI-generated illustration; non_illust = not an illustration (photo,
 * screencap, render, other); unidentified = the character could not be named
 */
export type ImageLabel = 'ai' | 'non_illust' | 'unidentified';

/** auto = the classifiers' verdict; manual = set in the aside, survives re-classification */
export type LabelSource = 'auto' | 'manual';

/** which end of the timeline a gallery grid starts from */
export type GridOrder = 'newest' | 'oldest';

export interface GalleryPage {
  items: GalleryItem[];
  next_cursor: string | null;
}

export type ImageKind = 'illustration' | 'photo' | 'render' | 'screencap' | 'other';

/** a gallery filter value: an image kind, or `unlabeled` for images with no label yet */
export type KindFilter = ImageKind | 'unlabeled';

/** identified = a character is named; unidentified = judged, nobody named; pending = not judged yet */
export type IdentState = 'identified' | 'unidentified' | 'pending';

/** GET /api/gallery/{slug}/characters */
export interface GalleryCharacters {
  counts: Record<IdentState, number>;
  /** every character named in this gallery, most images first; `name` is the Danbooru tag */
  characters: { name: string; label: string; count: number }[];
  /** enabled = Settings switch; available = classifier deps installed; models = files on disk */
  identifier: { enabled: boolean; available: boolean; models: boolean };
}

/** One character named in an image; `tag` is the exact form or costume, `name` the character. */
export interface CharacterHit {
  name: string;
  label: string;
  tag: string;
  score: number;
  by: 'wd' | 'camie' | 'both';
}

/** ai = AI-made; human = hand-drawn; pending = not judged yet */
export type OriginState = 'ai' | 'human' | 'pending';

/**
 * declared = the artist flagged it on pixiv; tags = the post carries an AI tag
 * such as #AIイラスト; model = the detector decided
 */
export type OriginBy = 'declared' | 'tags' | 'model';

/** GET /api/gallery/{slug}/origins */
export interface GalleryOrigins {
  counts: Record<OriginState, number>;
  /** available = classifier deps installed; models = the detector file is on disk */
  detector: { available: boolean; models: boolean };
}

/** GET /api/gallery/{slug}/kinds */
export interface GalleryKinds {
  counts: Record<KindFilter, number>;
  labeler: { available: boolean; models: boolean };
  /** images the character's gender filter has not judged yet */
  people?: { pending: number };
}

export interface TagStat {
  slug: string;
  tag_norm: string;
  tag_raw: string;
  translated: string | null;
  posts: number;
  share: number;
  characters: number;
  score: number;
  state: 'watched' | 'suggested' | 'ignored';
}

export interface PostDetail {
  source: string;
  external_id: string;
  artist_id: string;
  artist_name: string;
  artist_handle: string;
  title: string;
  caption: string;
  posted_at: string | null;
  permalink: string;
  bookmark_count: number;
  state: 'live' | 'gone';
  source_meta: string;
  media: PostMedia[];
  tags: { tag_raw: string; tag_norm: string; translated: string | null }[];
  /** the other source's post holding the same image (dedupe), with all of its images */
  linked: LinkedPost[];
}

/** One image row of a post (dawnmaker `_media_rows`). */
export interface PostMedia {
  idx: number;
  sha256: string | null;
  /** stored | dupe (recorded, blob is `dupe_of`'s) | rejected | failed | pending */
  state: string;
  /** the stored image this one duplicates, when state is dupe */
  dupe_of: string | null;
  width: number;
  height: number;
  bytes: number | null;
  ext: string;
  /** absolute path of the blob on the daemon's disk, when stored (Reveal) */
  path: string | null;
  /** the size the source handed over: original · orig · 4096x4096 · '' unknown */
  source_variant: string;
  /** null = not identified yet; absent on a linked post's media */
  identity?: { state: 'identified' | 'unidentified'; characters: CharacterHit[] } | null;
  /** how it was made; `score` = p(ai) when the detector ran, else null. null = not judged yet; absent on a linked post's media */
  origin?: { state: 'ai' | 'human'; by: OriginBy; score: number | null } | null;
  /** the image's badge; null = none; absent on a linked post's media */
  label?: ImageLabel | null;
  label_source?: LabelSource;
}

export interface LinkedPost {
  source: string;
  external_id: string;
  artist_handle: string;
  artist_name: string;
  title: string;
  permalink: string;
  posted_at: string | null;
  /** why dedupe linked them, e.g. "phash d=2" */
  reason: string | null;
  media: PostMedia[];
}

/** POST /api/pixiv/probe - the character form's live validation. */
/** POST /api/names - coreflame/names.py */
export interface NameSuggestion {
  text: string;
  kind: 'name' | 'form';
  lang: string | null; // en ja ko zh-hans zh-hant, "cjk" for Han-only
  sources: ('danbooru' | 'wikidata')[];
  posts: number | null; // Danbooru post count
  form: string | null; // the form's English name
  risky: boolean; // one short word: loose as an X search term
}

export interface CharacterNames {
  danbooru_tag: string | null;
  wikidata_id: string | null;
  label: string | null;
  suggestions: NameSuggestion[];
  errors: Partial<Record<'danbooru' | 'wikidata', string>>;
}

export interface ProbeResult {
  tags: { tag: string; total: number; ok: boolean; warning: string | null; error: string | null }[];
  preview: { illust_id: string; title: string; artist_name: string; thumb: string | null }[];
  suggestions: {
    tag_raw: string;
    tag_norm: string;
    posts: number;
    share: number;
    characters: number;
    score: number;
  }[];
  estimate: { artworks: number; seconds: number }; // upper bound: overlap + visited set unknown until crawl
}

/** GET /api/sources/status - secrets never appear here, only their state. */
export interface SourcesStatus {
  pixiv: {
    authed: boolean;
    user_id: string | null;
    verified: boolean | null;
    checked_at: number | null;
    error: string | null;
  };
  twitter: { authed: boolean; gallery_dl: boolean; cookies_file: boolean; from_browser: string | null };
  network: { resolver: string; proxy: boolean };
}

export interface Health {
  ok: boolean;
  version: string;
  library_root: string;
  db_path: string;
  /** free space on the disk holding the library */
  library_free_bytes: number;
  schema_version: number;
  idle: boolean;
  last_event_id: number;
}

// ---------------------------------------------------------------- deletion (coreflame/trash.py)
/** how the images to delete are chosen */
export type DeleteMode = 'image' | 'tag' | 'smart' | 'all';

/** a chip By tag selects with: what it is and which images carry it */
export type TermKind = 'tag' | 'artist' | 'label';

/** GET /api/gallery/{slug}/artists */
export interface GalleryArtist {
  source: string;
  artist_id: string;
  name: string;
  handle: string;
  count: number;
}

/** why Smart flagged an image; `score` is the watched character's (score) or the other one's (other) */
export type SmartReason =
  | { kind: 'score'; score: number }
  | { kind: 'other'; name: string; label: string; score: number }
  | { kind: 'dupe'; distance: number; keep: string }
  | { kind: 'unidentified' }
  /** not an illustration: the kind classifier's label (photo / render / other) */
  | { kind: 'kind'; label: 'photo' | 'render' | 'other' };

export interface SmartMatch {
  sha256: string;
  reasons: SmartReason[];
}

/** POST /api/gallery/{slug}/smart */
export interface SmartResult {
  matches: SmartMatch[];
  counts: Record<'score' | 'other' | 'dupe' | 'unidentified' | 'kind', number>;
  /** the character as the identifier names it (the gallery's most-named character), or null */
  primary: string | null;
  primary_label: string | null;
  /** the other characters found among the matches, most first */
  characters: { name: string; label: string; count: number }[];
  total: number;
  /** the crawl's "sure" score: what the slider's default sits under */
  cutoff: number;
  rule: CleanupRule | null;
  identifier: { enabled: boolean };
}

/** Settings › Duplicates: the Smart criteria applied at crawl time */
export interface CleanupRule {
  min_score: number | null;
  other_character: boolean;
}

/** GET /api/gallery/review */
export interface ReviewSummary {
  min_score: number;
  total: number;
  characters: { slug: string; label: string; count: number }[];
}

/** POST /api/gallery/{slug}/delete/preview */
export interface DeletePreview {
  images: number;
  bytes: number;
  by_source: Record<string, number>;
  posts: { touched: number; keep_other: number; forget: number };
  /** images that are also in another character's gallery: the same file, gone there too */
  shared: number;
  /** the set is every image the character has */
  whole: boolean;
  /** too many or too large to delete permanently: trash is forced */
  forced_trash: boolean;
  trash: TrashSummary;
}

/** POST /api/gallery/{slug}/delete */
export interface DeleteResult {
  batch_id: string | null;
  images: number;
  bytes: number;
  forgotten: number;
  permanent: boolean;
}

/** GET /api/trash */
export interface TrashSummary {
  count: number;
  bytes: number;
  oldest: string | null;
  days: number;
}

/** GET/POST /api/net/speed - the rail's signal card and its detail modal (dawnmaker/speed.py). */
export interface NetworkSpeed {
  measured_at: number | null; // unix seconds; null before the first probe
  online: boolean;
  testing: boolean; // a probe is running right now
  latency_ms: number | null;
  download_mbps: number | null;
  upload_mbps: number | null; // the last long probe's figure; a short probe keeps it
  /** ~1 s each, oldest first, at most 30 per direction */
  samples: { download: number[]; upload: number[] };
  server: { colo: string | null; location: string | null; ip_version: 'IPv4' | 'IPv6' | null };
  connection: {
    interface: 'wifi' | 'ethernet' | 'other' | null;
    ssid: string | null;
    isp: string | null;
    asn: string | null;
  };
  error: string | null;
}

// ---------------------------------------------------------------- backup (coreflame/bundle.py)
export type BundleFormat = 'curio' | 'zip';

export type WatchPolicy = 'keep' | 'take' | 'merge';

/** POST /api/bundle/export */
export interface BundleExportBody {
  /** where the save dialog pointed; omitted in browser mode (the daemon picks ~/.reaver/exports) */
  path?: string;
  format: BundleFormat;
  images: boolean;
  thumbs: boolean;
  secrets: boolean;
  /** the webview's localStorage, opaque to the daemon, handed back on import */
  ui: Record<string, unknown>;
}

/** one character the bundle names that collides with ours */
export interface BundleConflict {
  slug: string;
  label: string;
  mine: Watch;
  theirs: Watch;
  /** same slug, or another slug whose pixiv tags overlap ours (`suggest` names ours) */
  kind: 'same_slug' | 'same_tags';
  suggest: string | null;
}

/** POST /api/bundle/inspect */
export interface BundleInspect {
  path: string;
  format: BundleFormat;
  app_version: string;
  schema_version: number;
  created_at: string;
  counts: { characters: number; posts: number; images: number; thumbs: number };
  has: { images: boolean; thumbs: boolean; secrets: boolean; ui: boolean };
  characters: (Watch & { posts: number; new: boolean })[];
  conflicts: BundleConflict[];
}

/** POST /api/bundle/import */
export interface BundleImportBody {
  path: string;
  mode: 'merge' | 'restore';
  settings: 'keep' | 'take';
  secrets: boolean;
  characters: Record<string, WatchPolicy>;
  salvage: boolean;
}

export interface BundleImportResult {
  mode: 'merge' | 'restore';
  /** entry names that did not verify and were skipped (salvage) */
  damaged: string[];
  /** the bundle's webview state, when settings were taken */
  ui: Record<string, unknown> | null;
  characters: number;
  posts: number;
  placed: number;
  dupes: number;
  /** images whose bytes were missing or damaged: back to pending, the next crawl re-downloads */
  refetch: number;
}

/** GET /api/storage - Settings › Storage (coreflame/library.py usage) */
export interface StorageUsage {
  library_root: string;
  db_path: string;
  /** the db file plus its WAL and shm */
  db_bytes: number;
  schema_version: number;
  disk: {
    total: number;
    free: number;
    used: number;
    /** blobs + thumbs + trash */
    library: number;
    /** used minus the library */
    other: number;
    /** the mount point the library sits on */
    mount: string;
  };
  blobs: { files: number; bytes: number };
  thumbs: { files: number; bytes: number };
  by_character: { characters: number };
}
