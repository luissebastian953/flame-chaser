import type {
  GalleryArtist,
  GalleryCharacters,
  GalleryKinds,
  GalleryOrigins,
  GalleryPage,
  GridOrder,
  ImageLabel,
  KindFilter,
  PostDetail,
  Source,
  TagStat,
  Watch,
} from '@/lib/types';

/** Every kind a grid can show. */
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

/** PUT / DELETE /api/images/{sha256}/label */
interface LabelResult {
  sha256: string;
  label: ImageLabel | null;
  label_source: 'auto' | 'manual';
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
    kinds: null as GalleryKinds | null,
    characters: null as GalleryCharacters | null,
    origins: null as GalleryOrigins | null,
    /** one label the grid is narrowed to (this gallery only), or null for any */
    label: null as ImageLabel | null,
    /** one source the grid is narrowed to (this gallery only), or null for every source */
    source: null as Source | null,
    /** one artist (`source:artist_id`, lib/artists.ts) the grid is narrowed to (this gallery only), or null for all */
    artist: null as string | null,
    /** this gallery's artists, most images first - the filter row's chips and By tag's selector */
    artists: [] as GalleryArtist[],
    /** newest or oldest first; kept while the app runs */
    order: 'newest' as GridOrder,
  }),
  getters: {
    /** Rail count: sum of what each watch has kept. */
    totalPosts: (s) => s.watches.reduce((n, w) => n + (w.post_count ?? 0), 0),
    /** The kinds a character's grid can hold: all of them with its filter off. */
    kindsFor: (s) => (slug: string) =>
      s.watches.find((w) => w.slug === slug)?.kind_filter === false ? ALL_KIND_FILTERS : KIND_FILTERS,
    /**
     * The grid's filters as query parameters (kinds, label, source, artist) -- what
     * every page of the grid sends, and what a selection list
     * (stores/deletion.ts) sends so it never picks an image the grid is not
     * showing.
     */
    gridQuery(): (slug: string) => URLSearchParams {
      return (slug: string) => {
        const q = new URLSearchParams();
        q.set('kinds', this.kindsFor(slug).join(','));
        if (this.label) q.set('label', this.label);
        if (this.source) q.set('source', this.source);
        if (this.artist) q.set('artist', this.artist);
        return q;
      };
    },
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
     * more" sentinel into view while the reset's own page is still in flight -
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
        for (const [k, v] of this.gridQuery(slug)) q.set(k, v);
        if (this.order !== 'newest') q.set('order', this.order);
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
    async loadCharacters(slug: string) {
      this.characters = await api.get<GalleryCharacters>(`/api/gallery/${slug}/characters`);
    },
    async loadOrigins(slug: string) {
      this.origins = await api.get<GalleryOrigins>(`/api/gallery/${slug}/origins`);
    },
    /** The gallery's artists with their image counts; 300 covers any character the archive has seen. */
    async loadArtists(slug: string) {
      this.artists = await api.get<GalleryArtist[]>(`/api/gallery/${slug}/artists?limit=300`);
    },
    /** Narrow the grid to one label (null = any); not remembered across galleries, the grid starts over. */
    async setLabel(slug: string, label: ImageLabel | null) {
      this.label = label;
      await this.loadGrid(slug, true);
    },
    /**
     * Set an image's label by hand (null = no badge). The daemon keeps it over
     * any later re-classification. Every loaded copy of the image follows -
     * the grid's tiles and the open post's media rows - and a filtered grid
     * starts over so the change shows; the aside stays on its post.
     */
    async setImageLabel(sha: string, label: ImageLabel | null) {
      const r = await api.put<LabelResult>(`/api/images/${sha}/label`, { label });
      for (const it of this.grid.items) {
        if (it.sha256 === sha) {
          it.label = r.label;
          it.label_source = r.label_source;
        }
      }
      for (const m of this.detail?.media ?? []) {
        if (m.sha256 === sha) {
          m.label = r.label;
          m.label_source = r.label_source;
        }
      }
      if (this.label && this.grid.slug) await this.loadGrid(this.grid.slug, true);
    },
    /** Narrow the grid to one source (null = every source); the grid starts over. */
    async setSource(slug: string, source: Source | null) {
      this.source = source;
      await this.loadGrid(slug, true);
    },
    /** Narrow the grid to one artist by its `source:artist_id` key (null = all); the grid starts over. */
    async setArtist(slug: string, key: string | null) {
      this.artist = key;
      await this.loadGrid(slug, true);
    },
    /** Newest or oldest first; a cursor only continues its own order, so the grid starts over. */
    async setOrder(slug: string, order: GridOrder) {
      this.order = order;
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
