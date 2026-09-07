import type { GalleryPage, PostDetail, TagStat, Watch } from '@/lib/types';

export const useLibrary = defineStore('library', {
  state: () => ({
    watches: [] as Watch[],
    grid: { slug: '', items: [] as GalleryPage['items'], cursor: null as string | null, done: false },
    tags: [] as TagStat[],
    detail: null as PostDetail | null,
  }),
  getters: {
    /** Rail count: sum of what each watch has kept. */
    totalPosts: (s) => s.watches.reduce((n, w) => n + (w.post_count ?? 0), 0),
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
    /** Keyset pages; `reset` starts over for a new slug or filter. */
    async loadGrid(slug: string, reset = false) {
      if (reset || this.grid.slug !== slug) {
        this.grid = { slug, items: [], cursor: null, done: false };
      }
      if (this.grid.done) return;
      const q = new URLSearchParams({ limit: '120' });
      if (this.grid.cursor) q.set('cursor', this.grid.cursor);
      const page = await api.get<GalleryPage>(`/api/gallery/${slug}?${q}`);
      this.grid.items.push(...page.items);
      this.grid.cursor = page.next_cursor;
      this.grid.done = page.next_cursor === null;
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
