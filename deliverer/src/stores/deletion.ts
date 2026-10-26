import type {
  DeleteMode,
  DeletePreview,
  DeleteResult,
  SmartMatch,
  SmartReason,
  SmartResult,
  TermKind,
} from '@/lib/types';

/**
 * Deleting images from one character's gallery (coreflame/trash.py).
 *
 * Four ways to choose them, one selection: *By image* marks tiles by hand;
 * *By tag* marks every image a chip stands for (a tag, a kind, an
 * identification state, a character, an artist), any or all of them; *Smart*
 * marks what the identifier's criteria flag; *All* marks everything. In the
 * last three the user drops single tiles back out (`dropped`, the amber
 * "kept" ring). `effective` is what the confirm sheet and the daemon get.
 *
 * Selection lists come from the daemon per term, filtered exactly like the
 * grid, so nothing hidden is ever selected. Smart counts refresh 150 ms after
 * the last criteria change.
 */

export interface Term {
  key: string; // `${kind}:${value}`
  kind: TermKind;
  value: string;
  label: string;
  shas: string[];
}

export interface SmartCriteria {
  minScore: number | null; // null = the "low score" criterion off
  other: boolean;
  dupes: boolean;
  distance: number;
  unidentified: boolean;
  /** photos (cosplay, people, figures), 3D renders, screenshots: the recognition filter after the fact */
  kinds: boolean;
}

export type SmartSort = 'score' | 'reason' | 'newest';

export const DEFAULT_DISTANCE = 6;

/** the slider starts a little under the crawl's "sure" score */
export const SCORE_UNDER_CUTOFF = 0.08;

export const SMART_DEBOUNCE = 150;

/** GET /api/gallery/{slug}/images */
interface ImageList {
  shas: string[];
  sources?: Record<string, string>;
}

const TERM_PARAM: Record<TermKind, string> = {
  tag: 'tag',
  kind: 'sel_kind',
  ident: 'sel_ident',
  character: 'sel_character',
  artist: 'artist',
};

let smartTimer: ReturnType<typeof setTimeout> | null = null;

/** the reason worth a badge: another character or a low score first, then a dupe */
export function mainReason(reasons: SmartReason[]): SmartReason | null {
  return (
    reasons.find((r) => r.kind === 'kind') ??
    reasons.find((r) => r.kind === 'other') ??
    reasons.find((r) => r.kind === 'score') ??
    reasons.find((r) => r.kind === 'dupe') ??
    reasons[0] ??
    null
  );
}

/** badge colour per reason: rose = wrong or very unsure, amber = unsure, cyan = duplicate */
export function reasonTone(r: SmartReason | null): 'rose' | 'amber' | 'cyan' | 'dim' {
  if (!r) return 'dim';
  if (r.kind === 'dupe') return 'cyan';
  if (r.kind === 'other' || r.kind === 'unidentified' || r.kind === 'kind') return 'rose';
  return r.score < 0.5 ? 'rose' : 'amber';
}

export const useDeletion = defineStore('deletion', {
  state: () => ({
    slug: '',
    mode: null as DeleteMode | null,
    /** By image: the marked tiles, in the order they were marked */
    picked: [] as string[],
    /** By tag / Smart / All: tiles the user took back out ("kept") */
    dropped: [] as string[],
    terms: [] as Term[],
    match: 'any' as 'any' | 'all',
    /** By tag: a chip that stands for the whole gallery was clicked */
    everythingPrompt: null as string | null,
    smart: {
      minScore: 0.42,
      other: true,
      dupes: true,
      distance: DEFAULT_DISTANCE,
      unidentified: false,
      kinds: useCharacterDefaults().kind_filter,
    } as SmartCriteria,
    smartResult: null as SmartResult | null,
    smartLoading: false,
    smartSort: 'score' as SmartSort,
    reviewOnly: false,
    /** All: every image the grid can show */
    everything: [] as string[],
    /** which source each listed sha is from (the bar's pixiv / X split) */
    sourceOf: {} as Record<string, string>,
    /** the hint line under the bar collapses after the first change */
    hintSeen: false,
    sheet: false,
    preview: null as DeletePreview | null,
    busy: false,
    /** the last batch, until Undo or the next deletion */
    lastBatch: null as string | null,
  }),
  getters: {
    active: (s) => s.mode !== null,
    /** the candidate set before manual drops */
    base(): string[] {
      switch (this.mode) {
        case 'image':
          return this.picked;
        case 'tag':
          return combine(this.terms, this.match);
        case 'smart':
          return (this.smartResult?.matches ?? []).map((m) => m.sha256);
        case 'all':
          return this.everything;
        default:
          return [];
      }
    },
    effective(): string[] {
      if (this.mode === 'image') return this.picked;
      const out = new Set(this.dropped);
      return this.base.filter((sha) => !out.has(sha));
    },
    selected(): Set<string> {
      return new Set(this.effective);
    },
    count(): number {
      return this.effective.length;
    },
    baseSet(): Set<string> {
      return new Set(this.base);
    },
    droppedSet: (s) => new Set(s.dropped),
    /** By tag: images two or more terms share */
    overlap(): number {
      const seen = new Map<string, number>();
      for (const term of this.terms) for (const sha of term.shas) seen.set(sha, (seen.get(sha) ?? 0) + 1);
      let n = 0;
      for (const c of seen.values()) if (c > 1) n++;
      return n;
    },
    /** By tag: the chip(s) that pulled an image in */
    termsOf(): (sha: string) => Term[] {
      return (sha) => this.terms.filter((term) => term.shas.includes(sha));
    },
    smartBySha(): Map<string, SmartMatch> {
      return new Map((this.smartResult?.matches ?? []).map((m) => [m.sha256, m]));
    },
    isTerm: (s) => (kind: TermKind, value: string) => s.terms.some((term) => term.key === `${kind}:${value}`),
  },
  actions: {
    enter(slug: string, mode: DeleteMode) {
      if (this.slug !== slug || !this.mode) this.reset();
      this.slug = slug;
      this.mode = mode;
      this.hintSeen = false;
      this.sheet = false;
    },
    /** switch modes without losing what By image picked */
    switchTo(mode: DeleteMode) {
      this.mode = mode;
      this.dropped = [];
      this.hintSeen = false;
    },
    exit() {
      this.reset();
    },
    reset() {
      if (smartTimer) clearTimeout(smartTimer);
      smartTimer = null;
      this.mode = null;
      this.picked = [];
      this.dropped = [];
      this.terms = [];
      this.match = 'any';
      this.everythingPrompt = null;
      this.smartResult = null;
      this.smartLoading = false;
      this.reviewOnly = false;
      this.everything = [];
      this.sourceOf = {};
      this.hintSeen = false;
      this.sheet = false;
      this.preview = null;
      this.busy = false;
    },
    /** By image: mark or unmark; elsewhere: drop out or take back in */
    toggle(sha: string) {
      this.hintSeen = true;
      if (this.mode === 'image') {
        this.picked = this.picked.includes(sha)
          ? this.picked.filter((x) => x !== sha)
          : [...this.picked, sha];

        return;
      }
      if (!this.baseSet.has(sha)) return; // not a candidate: nothing to keep or drop

      this.dropped = this.dropped.includes(sha)
        ? this.dropped.filter((x) => x !== sha)
        : [...this.dropped, sha];
    },
    /** By image: mark everything between the last pick and `sha` in visual order */
    range(visible: string[], sha: string) {
      const anchor = this.picked[this.picked.length - 1];
      const a = anchor ? visible.indexOf(anchor) : -1;
      const b = visible.indexOf(sha);
      if (a < 0 || b < 0) return this.toggle(sha);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      this.hintSeen = true;
      const add = visible.slice(lo, hi + 1).filter((x) => !this.picked.includes(x));
      this.picked = [...this.picked, ...add];
    },
    /** By image: mark every tile in `visible` (or the ones a marquee covered) */
    mark(shas: string[]) {
      this.hintSeen = true;
      const add = shas.filter((x) => !this.picked.includes(x));
      this.picked = [...this.picked, ...add];
    },
    clear() {
      this.hintSeen = true;
      if (this.mode === 'image') this.picked = [];
      else if (this.mode === 'tag') {
        this.terms = [];
        this.dropped = [];
      } else this.dropped = [...this.base];
    },
    /** By tag: a chip on or off; `query` = the grid's filters, so the list matches the grid */
    async toggleTerm(kind: TermKind, value: string, label: string, query: URLSearchParams, total = 0) {
      this.hintSeen = true;
      const key = `${kind}:${value}`;
      if (this.terms.some((term) => term.key === key)) {
        this.terms = this.terms.filter((term) => term.key !== key);
        if (this.everythingPrompt === key) this.everythingPrompt = null;
        return;
      }
      const q = new URLSearchParams(query);
      q.set(TERM_PARAM[kind], value);
      let r: ImageList;
      try {
        r = await api.get<ImageList>(`/api/gallery/${this.slug}/images?${q}`);
      } catch (e) {
        this.failed(e); // an old daemon has no such route: say so instead of a dead chip
        return;
      }
      if (this.mode !== 'tag') return; // left meanwhile
      Object.assign(this.sourceOf, r.sources ?? {});
      this.terms = [...this.terms, { key, kind, value, label, shas: r.shas }];
      // a chip that stands for the whole gallery is what All is for
      this.everythingPrompt = total > 0 && r.shas.length >= total ? key : null;
    },
    setMatch(match: 'any' | 'all') {
      this.hintSeen = true;
      this.match = match;
    },
    /** Smart: change a criterion; the daemon recounts 150 ms after the last change */
    setSmart(patch: Partial<SmartCriteria>) {
      Object.assign(this.smart, patch);
      this.hintSeen = true;
      if (smartTimer) clearTimeout(smartTimer);
      smartTimer = setTimeout(() => void this.loadSmart(), SMART_DEBOUNCE);
    },
    /** a request the daemon refused: an error toast, since the chip or panel would otherwise stay dead */
    failed(e: unknown) {
      const toasts = useToasts();
      const code = e instanceof ApiError ? e.code : 'unreachable';

      toasts.error({
        slug: this.slug,
        label: this.slug,
        sources: [],
        terms: 0,
        code,
        message: e instanceof Error ? e.message : String(e),
        retry: async () => {},
      });
    },
    async loadSmart() {
      if (smartTimer) clearTimeout(smartTimer);
      smartTimer = null;
      const slug = this.slug;
      this.smartLoading = true;
      try {
        const r = await api.post<SmartResult>(`/api/gallery/${slug}/smart`, {
          min_score: this.smart.minScore,
          other_character: this.smart.other,
          dupes: this.smart.dupes,
          distance: this.smart.distance,
          unidentified: this.smart.unidentified,
          kinds: this.smart.kinds,
        });

        if (this.slug !== slug || this.mode !== 'smart') return;
        this.smartResult = r;
        // a kept override only means something while its image is still a match
        const matches = new Set(r.matches.map((m) => m.sha256));
        this.dropped = this.dropped.filter((sha) => matches.has(sha));
      } catch (e) {
        this.failed(e);
      } finally {
        this.smartLoading = false;
      }
    },
    /** All: every image the grid can show */
    async loadEverything(query: URLSearchParams) {
      const slug = this.slug;
      let r: ImageList;
      try {
        r = await api.get<ImageList>(`/api/gallery/${slug}/images?${query}`);
      } catch (e) {
        this.failed(e);
        return;
      }
      if (this.slug !== slug || this.mode !== 'all') return;
      Object.assign(this.sourceOf, r.sources ?? {});
      this.everything = r.shas;
    },
    async openSheet() {
      this.busy = true;
      try {
        this.preview = await api.post<DeletePreview>(`/api/gallery/${this.slug}/delete/preview`, {
          shas: this.effective,
        });

        this.sheet = true;
      } finally {
        this.busy = false;
      }
    },
    closeSheet() {
      this.sheet = false;
    },
    /** the deletion itself; the caller shows the toast and redraws */
    async commit(opts: { trash: boolean; forget: boolean; confirm?: string }): Promise<DeleteResult> {
      this.busy = true;
      try {
        const r = await api.post<DeleteResult>(`/api/gallery/${this.slug}/delete`, {
          shas: this.effective,
          mode: this.mode,
          trash: opts.trash,
          forget: opts.forget,
          confirm: opts.confirm,
        });

        this.lastBatch = r.batch_id;
        return r;
      } finally {
        this.busy = false;
      }
    },
    /** put the last batch back: images, forgotten posts and their visited state */
    async undo(batchId: string) {
      await api.post(`/api/trash/${batchId}/restore`);
      if (this.lastBatch === batchId) this.lastBatch = null;
    },
  },
});

/** any = union, all = intersection, in the first term's order */
export function combine(terms: Term[], match: 'any' | 'all'): string[] {
  if (!terms.length) return [];
  if (match === 'any') {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const term of terms)
      for (const sha of term.shas) {
        if (seen.has(sha)) continue;
        seen.add(sha);
        out.push(sha);
      }
    return out;
  }
  const rest = terms.slice(1).map((term) => new Set(term.shas));
  return terms[0]!.shas.filter((sha) => rest.every((s) => s.has(sha)));
}
