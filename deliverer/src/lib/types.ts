/** Shapes from docs/design/architecture.md §6. Keep in step with dawnmaker/app.py. */
export type Source = 'pixiv' | 'twitter';

export interface Watch {
  slug: string;
  label: string;
  pixiv_tags: string[];
  match_terms: string[];
  min_bookmarks: number;
  include_r18: boolean;
  /** which sources this character is crawled from; both by default */
  sources: Source[];
  post_count?: number;
  latest_posted_at?: string | null;
  cover_sha?: string | null;
  reopened?: number;
}

export type JobState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';

export interface Job {
  id: string;
  type: string;
  params: Record<string, unknown>;
  state: JobState;
  stage: string | null;
  done: number;
  total: number | null;
  counters: Record<string, number>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  log?: LogLine[];
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
}

export interface GalleryPage {
  items: GalleryItem[];
  next_cursor: string | null;
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
  media: {
    idx: number;
    sha256: string | null;
    state: string;
    width: number;
    height: number;
    bytes: number | null;
  }[];
  tags: { tag_raw: string; tag_norm: string; translated: string | null }[];
  linked: {
    source: string;
    external_id: string;
    permalink: string;
    posted_at: string | null;
    reason: string;
  }[];
}

/** POST /api/pixiv/probe — the character form's live validation. */
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

/** GET /api/sources/status — secrets never appear here, only their state. */
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
  schema_version: number;
  idle: boolean;
  last_event_id: number;
}
