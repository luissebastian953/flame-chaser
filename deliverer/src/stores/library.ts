import type { GalleryKinds, GalleryPage, KindFilter, PostDetail, TagStat, Watch } from '@/lib/types';

/** Every kind a grid can show, in chip order. */
export const ALL_KIND_FILTERS: KindFilter[] = [
  'illustration',
  'screencap',
  'photo',
  'render',
  'other',
  'unlabeled',
];

/**
 * What a character with the image-kind filter ON holds: coreflame/kinds.py
 * KEEP plus images not judged yet. The daemon throws the rest away, so its
 * grid never asks for them -- not even before a cleanup has run.
 */
export const KIND_FILTERS: KindFilter[] = ['illustration', 'screencap', 'unlabeled'];

/** Everything selected; each character's grid narrows it to what it can hold. */
export const DEFAULT_KIND_FILTER: KindFilter[] = [...ALL_KIND_FILTERS];

const SHOW_KEY = 'curio.gallery.show';

/** Per-viewer convenience, like the theme: localStorage, never the daemon. */
function loadShow(): KindFilter[] {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(SHOW_KEY) ?? 'null');
    if (Array.isArray(v) && v.length && v.every((k) => ALL_KIND_FILTERS.includes(k as KindFilter))) {
      return v as KindFilter[];
    }
  } catch {
    /* private mode / blocked storage / bad JSON: defaults */
  }

  return [...DEFAULT_KIND_FILTER];
}

export const useLibrary = defineStore('library', {
  state: () => ({
    watches: [] as Watch[],
    grid: {
      slug: '',
      items: [] as GalleryPage['items'],
      cursor: null as string | null,
      done: false,
      loading: false,
    },
    tags: [] as TagStat[],
    detail: null as PostDetail | null,
    show: loadShow(),
    kinds: null as GalleryKinds | null,
  }),
  getters: {
    /** Rail count: sum of what each watch has kept. */
    totalPosts: (s) => s.watches.reduce((n, w) => n + (w.post_count ?? 0), 0),
    /** The kinds a character's grid can hold: all of them with its filter off. */
    kindsFor: (s) => (slug: string) =>
      s.watches.find((w) => w.slug === slug)?.kind_filter === false ? ALL_KIND_FILTERS : KIND_FILTERS,
  },
  actions: {
    async loadWatches() {
      this.watches = await api.get<Watch[]>('/api/watches');
    },
    async saveWatch(w: Watch, isNew: boolean) {
      const r = isNew
        ? await api.post<Watch>('/api/watches', w)
        : await api.patch<Watch>(`/api/watches/${w.slug}`, w);

      await this.loadWatches();
      return r;
    },
    async deleteWatch(slug: string) {
      await api.del(`/api/watches/${slug}`);
      await this.loadWatches();
    },
    /**
     * Keyset pages; `reset` starts over for a new slug or filter. One request
     * per grid at a time: a reset empties the grid, which brings the "load
     * more" sentinel into view while the reset's own page is still in flight —
     * without the guard both land and every image shows twice. A reset also
     * orphans any older request, whose page is then dropped.
     */
    async loadGrid(slug: string, reset = false) {
      if (reset || this.grid.slug !== slug) {
        this.grid = { slug, items: [], cursor: null, done: false, loading: false };
      }

      const grid = this.grid;
      if (grid.done || grid.loading) return;
      grid.loading = true;
      try {
        const q = new URLSearchParams({ limit: '120' });
        const can = this.kindsFor(slug);
        const kinds = this.show.filter((k) => can.includes(k));
        q.set('kinds', (kinds.length ? kinds : can).join(','));
        if (grid.cursor) q.set('cursor', grid.cursor);
        const page = await api.get<GalleryPage>(`/api/gallery/${slug}?${q}`);
        if (this.grid !== grid) return; // reset meanwhile: that load owns the grid now
        grid.items.push(...page.items);
        grid.cursor = page.next_cursor;
        grid.done = page.next_cursor === null;
      } finally {
        grid.loading = false;
      }
    },
    async loadKinds(slug: string) {
      this.kinds = await api.get<GalleryKinds>(`/api/gallery/${slug}/kinds`);
    },
    /** Change which kinds the grid shows; remembered, and the grid starts over. */
    async setShow(slug: string, show: KindFilter[]) {
      this.show = ALL_KIND_FILTERS.filter((k) => show.includes(k));
      try {
        localStorage.setItem(SHOW_KEY, JSON.stringify(this.show));
      } catch {
        /* best effort */
      }

      await this.loadGrid(slug, true);
    },
    async loadTags(slug: string) {
      this.tags = await api.get<TagStat[]>(`/api/gallery/${slug}/tags`);
    },
    async tagAction(slug: string, tag: string, action: 'watch' | 'ignore') {
      await api.post(`/api/watches/${slug}/tags`, { tag, action });
      await Promise.all([this.loadTags(slug), this.loadWatches()]);
    },
    async openDetail(source: string, id: string) {
      this.detail = await api.get<PostDetail>(`/api/posts/${source}/${id}`);
    },
    closeDetail() {
      this.detail = null;
    },
  },
});
