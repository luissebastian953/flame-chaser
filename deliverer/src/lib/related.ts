import type { LinkedPost, PostDetail } from '@/lib/types';

/**
 * The set the image detail panel and the fullscreen viewer walk through: the
 * post's own pages in page order, then every image of the other source's post
 * that dedupe linked (the X thread a pixiv upload was reposted in, or back).
 *
 * A `dupe` row was recorded but never stored -- its bytes are the kept copy's,
 * so its thumb and full image are served from `dupe_of`. Rejected, failed and
 * pending rows have nothing to show and are left out.
 */
export interface ViewerItem {
  /** `${source}:${external_id}:${idx}` -- stable across the panel and the viewer */
  key: string;
  /** the sha whose thumb and full bytes are shown */
  sha: string;
  /** false for a recorded duplicate: the blob shown is the kept copy's */
  stored: boolean;
  source: string;
  external_id: string;
  idx: number;
  /** 1-based page label (p1, p2 …) and how many pages of that post are shown */
  page: number;
  pages: number;
  title: string;
  artist_name: string;
  artist_handle: string;
  permalink: string;
  posted_at: string | null;
  width: number;
  height: number;
  bytes: number | null;
  ext: string;
  /** absolute path of the blob on the daemon's disk, when stored (Reveal) */
  path: string | null;
  /** original · orig · 4096x4096 · '' unknown */
  variant: string;
  /** true when the image belongs to the linked post, not the one the panel opened on */
  linked: boolean;
}

type PostLike = Pick<
  PostDetail,
  'source' | 'external_id' | 'title' | 'artist_name' | 'artist_handle' | 'permalink' | 'posted_at' | 'media'
>;

function itemsOf(post: PostLike | LinkedPost, linked: boolean): ViewerItem[] {
  const shown = post.media.filter(
    (m) => (m.state === 'stored' && m.sha256) || (m.state === 'dupe' && m.dupe_of),
  );

  return shown.map((m) => ({
    key: `${post.source}:${post.external_id}:${m.idx}`,
    sha: (m.state === 'stored' ? m.sha256 : m.dupe_of) as string,
    stored: m.state === 'stored',
    source: post.source,
    external_id: post.external_id,
    idx: m.idx,
    page: m.idx + 1,
    pages: shown.length,
    title: post.title,
    artist_name: post.artist_name,
    artist_handle: post.artist_handle,
    permalink: post.permalink,
    posted_at: post.posted_at,
    width: m.width,
    height: m.height,
    bytes: m.bytes,
    ext: m.ext,
    path: m.path,
    variant: m.source_variant,
    linked,
  }));
}

/** Pages first, then the linked posts' images in the order the daemon listed them. */
export function relatedSet(post: PostDetail): ViewerItem[] {
  return [...itemsOf(post, false), ...post.linked.flatMap((l) => itemsOf(l, true))];
}

/** Index of the first linked item -- where the strip draws its divider; -1 when none. */
export function linkedStart(items: ViewerItem[]): number {
  return items.findIndex((it) => it.linked);
}

/** "8.24" for 8.24 MB; the unit is the caller's string. */
export function megabytes(bytes: number | null | undefined): string {
  return ((bytes ?? 0) / 1048576).toFixed(2);
}
