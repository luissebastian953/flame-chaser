<script setup lang="ts">
import { pickedFirst } from '@/lib/chips';
import type {
  DeleteMode,
  GalleryArtist,
  GalleryItem,
  GridOrder,
  SmartResult,
  Source,
  TermKind,
} from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const del = useDeletion();
const toasts = useToasts();
const fm = useFormats();
const router = useRouter();
const route = useRoute();
const { t } = useI18n();
const sentinel = ref<HTMLElement | null>(null);
let io: IntersectionObserver | null = null;

const SOURCES: Source[] = ['pixiv', 'twitter'];
const ORDERS: GridOrder[] = ['newest', 'oldest'];
const TAGS_SHOWN = 10; // tag chips before "see all"

const w = computed(() => lib.watches.find((x) => x.slug === props.slug));
const label = computed(() => w.value?.label || props.slug);

/** every image the grid can hold (the kept kinds), null until the counts arrive */
const total = computed(() => {
  const c = lib.kinds?.counts;
  return c ? lib.kindsFor(props.slug).reduce((sum, k) => sum + c[k], 0) : null;
});

// the header count rolls to its new value over 300 ms after a deletion
const shown = ref<number | null>(null);
let roll: number | null = null;

watch(
  total,
  (n, was) => {
    if (n === null || was == null || shown.value === null) {
      shown.value = n;
      return;
    }
    const from = shown.value;
    const t0 = performance.now();
    if (roll) cancelAnimationFrame(roll);

    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / 300);
      shown.value = Math.round(from + (n - from) * k);
      if (k < 1) roll = requestAnimationFrame(tick);
    };

    roll = requestAnimationFrame(tick);
  },
  { immediate: true },
);

/** "1,284 images · 412 posts · 61 artists" */
const stats = computed(() => {
  const n = shown.value;

  const images =
    n === null
      ? lib.grid.done
        ? t('gallery.detail.images', lib.grid.items.length)
        : t('gallery.detail.imagesMore', { n: lib.grid.items.length })
      : t('gallery.detail.images', { n: fm.number(n) }, n);

  const p = w.value?.post_count;
  const a = w.value?.artist_count ?? 0;

  return p === undefined
    ? images
    : t('gallery.detail.stats', {
        images,
        posts: postCount(p),
        artists: t('gallery.detail.artists', { n: fm.number(a) }, a),
      });
});

function postCount(p: number) {
  return t('gallery.gallery.postCount', { n: fm.number(p) }, p);
}

// observed tags: watched first, then the suggestions, then what was ignored
const allTags = ref(false);
const watchedTags = computed(() => lib.tags.filter((x) => x.state === 'watched'));

const orderedTags = computed(() => [
  ...watchedTags.value,
  ...lib.tags.filter((x) => x.state === 'suggested'),
  ...lib.tags.filter((x) => x.state === 'ignored'),
]);

// By tag shows every chip, in place: a folded row hides exactly what the user is looking for
const shownTags = computed(() => {
  if (del.mode === 'tag') return orderedTags.value;
  return allTags.value
    ? orderedTags.value
    : orderedTags.value.slice(0, Math.max(TAGS_SHOWN, watchedTags.value.length));
});

const tagsHint = computed(() => {
  const p = w.value?.post_count;

  return p === undefined ? '' : t('gallery.detail.tagsHint', { posts: postCount(p) });
});

// the grid scrolled under the header and tags: both turn into a frosted plate
const scrolled = ref(false);

function onScroll(e: Event) {
  scrolled.value = (e.target as HTMLElement).scrollTop > 0;
}

const order = computed({
  get: () => lib.order,
  set: (o: GridOrder) => void lib.setOrder(props.slug, o),
});

// the tile the aside was opened from, ringed while the aside is open
const selected = ref<string | null>(null);

function tileKey(it: GalleryItem) {
  return it.sha256 + it.idx;
}

function openTile(it: GalleryItem) {
  selected.value = tileKey(it);
  void lib.openDetail(it.source, it.external_id);
}

watch(
  () => lib.detail,
  (d) => {
    if (!d) selected.value = null;
  },
);

// the fullscreen viewer, on a post with one image: ← → move to the next tile
// in the grid's current order, loading the next page when the end is reached
const viewer = useViewer();

async function stepGrid(dir: 1 | -1) {
  const d = lib.detail;
  if (!d) return;
  const items = lib.grid.items;
  const i = items.findIndex((it) => it.source === d.source && it.external_id === d.external_id);
  if (i < 0) return;
  if (i + dir >= items.length && !lib.grid.done) await lib.loadGrid(props.slug);
  const next = lib.grid.items[i + dir];
  if (next) openTile(next);
}

// ---- the header's more menu: Delete character (two clicks, like Shutdown) ----
const moreOpen = ref(false);
const armed = ref(false);
let disarm: ReturnType<typeof setTimeout> | undefined;

async function remove() {
  if (!armed.value) {
    armed.value = true;
    disarm = setTimeout(() => (armed.value = false), 4000);
    return;
  }
  clearTimeout(disarm);
  armed.value = false;
  moreOpen.value = false;
  await lib.deleteWatch(props.slug);
  await router.push('/gallery');
}

function onDocClick(e: MouseEvent) {
  if (moreOpen.value && !(e.target as HTMLElement).closest('.more-menu')) moreOpen.value = false;
}

// ---- selecting images to delete (stores/deletion.ts) ------------------------
const artists = ref<GalleryArtist[]>([]);
/** Smart candidates with the default criteria, for the picker's chip */
const suggested = ref<number | null>(null);
const visible = computed(() => lib.grid.items.map((it) => it.sha256));
const bySha = computed(() => new Map(lib.grid.items.map((it) => [it.sha256, it])));

const bySource = computed(() => {
  const out: Record<string, number> = { pixiv: 0, twitter: 0 };
  // the daemon's lists say which source each sha is from; loaded tiles cover By image
  for (const sha of del.effective) {
    const src = del.sourceOf[sha] ?? bySha.value.get(sha)?.source;
    if (src) out[src] = (out[src] ?? 0) + 1;
  }
  return out;
});

async function enter(mode: DeleteMode) {
  del.enter(props.slug, mode);
  lib.closeDetail();
  if (mode === 'tag' && !artists.value.length) {
    artists.value = await api.get<GalleryArtist[]>(`/api/gallery/${props.slug}/artists`);
  }
  if (mode === 'all') await del.loadEverything(lib.gridQuery(props.slug));
}

async function switchMode(mode: DeleteMode) {
  del.switchTo(mode);
  if (mode === 'tag' && !artists.value.length) {
    artists.value = await api.get<GalleryArtist[]>(`/api/gallery/${props.slug}/artists`);
  }
  if (mode === 'all') await del.loadEverything(lib.gridQuery(props.slug));
}

// Esc with a selection asks for a second Esc
const leaving = ref(false);
let leaveTimer: ReturnType<typeof setTimeout> | undefined;

function leave() {
  clearTimeout(leaveTimer);
  leaving.value = false;
  del.exit();
}

function onKey(e: KeyboardEvent) {
  if (e.defaultPrevented) return;
  if (e.key === 'Escape') {
    if (lib.detail) return lib.closeDetail();
    if (!del.active || del.sheet) return;
    if (!del.count || leaving.value) return leave();
    leaving.value = true;
    leaveTimer = setTimeout(() => (leaving.value = false), 3000);
    return;
  }
  const typing = (e.target as HTMLElement | null)?.tagName === 'INPUT';
  if (
    del.mode === 'image' &&
    !del.sheet &&
    !typing &&
    (e.key === 'a' || e.key === 'A') &&
    !e.metaKey &&
    !e.ctrlKey
  ) {
    e.preventDefault();
    del.mark(visible.value);
  }
}

/** a tile click: open the aside, or mark / keep in select mode */
function onTile(it: GalleryItem | null, sha: string, e: MouseEvent) {
  if (suppressClick) return;
  if (!del.active) {
    if (it) openTile(it);
    return;
  }
  if (del.mode === 'image' && e.shiftKey) del.range(visible.value, sha);
  else del.toggle(sha);
}

// By image: drag a box on empty space (or from an unmarked tile) to mark what it covers
const box = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
let dragFrom: { x: number; y: number } | null = null;
let suppressClick = false;

function onPointerDown(e: PointerEvent) {
  if (del.mode !== 'image' || e.button !== 0) return;
  const el = e.target as HTMLElement;
  if (el.closest('.filters, .mhead, button:not(.tile)')) return;
  const tile = el.closest('.tile') as HTMLElement | null;
  if (tile && del.selected.has(tile.dataset.sha ?? '')) return; // a marked tile just toggles
  dragFrom = { x: e.clientX, y: e.clientY };
}

function onPointerMove(e: PointerEvent) {
  if (!dragFrom) return;
  if (!box.value && Math.hypot(e.clientX - dragFrom.x, e.clientY - dragFrom.y) < 5) return;
  box.value = { x1: dragFrom.x, y1: dragFrom.y, x2: e.clientX, y2: e.clientY };
}

function onPointerUp() {
  if (box.value) {
    const b = box.value;
    const [l, r] = b.x1 < b.x2 ? [b.x1, b.x2] : [b.x2, b.x1];
    const [tp, bt] = b.y1 < b.y2 ? [b.y1, b.y2] : [b.y2, b.y1];
    const hit: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>('.masonry .tile[data-sha]')) {
      const rc = el.getBoundingClientRect();
      if (rc.left < r && rc.right > l && rc.top < bt && rc.bottom > tp) hit.push(el.dataset.sha!);
    }
    del.mark(hit);
    suppressClick = true;
    setTimeout(() => (suppressClick = false), 0);
  }
  box.value = null;
  dragFrom = null;
}

const boxStyle = computed(() => {
  const b = box.value;
  if (!b) return undefined;
  return {
    left: `${Math.min(b.x1, b.x2)}px`,
    top: `${Math.min(b.y1, b.y2)}px`,
    width: `${Math.abs(b.x2 - b.x1)}px`,
    height: `${Math.abs(b.y2 - b.y1)}px`,
  };
});

// By tag: chips become selectors; the strip under them shows the arithmetic
function term(kind: TermKind, value: string, chipLabel: string) {
  void del.toggleTerm(kind, value, chipLabel, lib.gridQuery(props.slug), total.value ?? 0);
}

const formula = computed(() => {
  if (!del.terms.length) return '';
  const sep = t(del.match === 'any' ? 'gallery.delete.tag.union' : 'gallery.delete.tag.intersection');

  const terms = del.terms
    .map((x) => t('gallery.delete.tag.term', { label: x.label, n: fm.number(x.shas.length) }))
    .join(sep);

  return t('gallery.delete.tag.formula', {
    terms,
    n: fm.number(del.base.length),
    overlap: fm.number(del.overlap),
    dropped: fm.number(del.dropped.length),
  });
});

const artistKey = (a: GalleryArtist) => `${a.source}:${a.artist_id}`;

// Smart: matches float to the top in the chosen order, the rest below (or hidden)
const smartMatches = computed(() => {
  const r = del.smartResult;
  if (!r) return [];
  const list = r.matches.map((m) => ({ sha: m.sha256, reason: mainReason(m.reasons) }));
  const ORDER = { kind: 0, other: 1, score: 2, dupe: 3, unidentified: 4 };
  if (del.smartSort === 'score')
    list.sort(
      (a, b) =>
        (a.reason && 'score' in a.reason ? a.reason.score : 2) -
        (b.reason && 'score' in b.reason ? b.reason.score : 2),
    );
  else if (del.smartSort === 'reason')
    list.sort((a, b) => ORDER[a.reason?.kind ?? 'unidentified'] - ORDER[b.reason?.kind ?? 'unidentified']);
  else {
    const pos = new Map(visible.value.map((sha, i) => [sha, i]));
    list.sort((a, b) => (pos.get(a.sha) ?? 1e9) - (pos.get(b.sha) ?? 1e9));
  }
  // a tile kept back out sinks to the end, so what is still marked leads
  return pickedFirst(list, (m) => !del.droppedSet.has(m.sha));
});

// By tag: the images the picked chips stand for lead the grid; Smart: its matches have a grid of their own
const rest = computed(() => {
  if (del.mode === 'smart') return lib.grid.items.filter((it) => !del.smartBySha.has(it.sha256));
  if (del.mode === 'tag' && del.terms.length) {
    // marked first, then the chips' other images (kept back out or excluded), then the rest
    const inTerm = new Set(del.terms.flatMap((x) => x.shas));
    const byChip = pickedFirst(lib.grid.items, (it) => inTerm.has(it.sha256));
    return pickedFirst(byChip, (it) => del.selected.has(it.sha256));
  }
  return lib.grid.items;
});

// Masonry as real columns, packed in order (shortest column first), not CSS
// `column-count`: that balances column heights, so two images land in
// columns 1 and 3 with a hole between, and a page that grows as it scrolls
// reflows its whole tail. Greedy packing is stable: appending never moves
// what is already placed.
const narrow = ref(false);
const mq = typeof window.matchMedia === 'function' ? window.matchMedia('(max-width: 1100px)') : null;
const onMq = (e: MediaQueryListEvent | MediaQueryList) => (narrow.value = e.matches);
const colCount = (four: boolean) => (four ? 4 : 5) - (narrow.value ? 1 : 0);
const tall = (it?: GalleryItem) => (it?.width && it?.height ? it.height / it.width : 4 / 3);

function pack<T>(items: T[], n: number, height: (it: T) => number): T[][] {
  const cols: T[][] = Array.from({ length: n }, () => []);
  const h = new Array<number>(n).fill(0);
  for (const it of items) {
    let k = 0;
    for (let i = 1; i < n; i++) if (h[i]! < h[k]!) k = i;
    cols[k]!.push(it);
    h[k]! += height(it);
  }
  return cols;
}

const restCols = computed(() => pack(rest.value, colCount(del.mode === 'smart'), tall));

const smartCols = computed(() =>
  pack(smartMatches.value, colCount(true), (m) => tall(bySha.value.get(m.sha))),
);

function badgeOf(sha: string): { text: string; tone: 'rose' | 'amber' | 'cyan' | 'dim' } | null {
  if (del.mode === 'tag') {
    const first = del.termsOf(sha)[0];
    return first ? { text: first.label, tone: 'rose' } : null;
  }
  if (del.mode === 'smart') {
    const m = del.smartBySha.get(sha);
    const r = m ? mainReason(m.reasons) : null;
    if (!r) return null;

    const text =
      r.kind === 'other'
        ? t('gallery.delete.smart.badge.other', { label: r.label, score: r.score.toFixed(2) })
        : r.kind === 'score'
          ? t('gallery.delete.smart.badge.score', { score: r.score.toFixed(2) })
          : r.kind === 'dupe'
            ? t('gallery.delete.smart.badge.dupe', { n: r.distance })
            : r.kind === 'kind'
              ? t(`gallery.kinds.name.${r.label}`)
              : t('gallery.delete.smart.badge.unidentified');

    return { text, tone: reasonTone(r) };
  }
  return null;
}

/** the sheet's by-reason box */
const sheetReasons = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {};
  if (del.mode === 'tag') {
    for (const sha of del.effective) {
      const first = del.termsOf(sha)[0];
      if (first) out[first.label] = (out[first.label] ?? 0) + 1;
    }
  } else if (del.mode === 'smart') {
    for (const sha of del.effective) {
      const m = del.smartBySha.get(sha);
      const r = m ? mainReason(m.reasons) : null;
      if (r) out[r.kind] = (out[r.kind] ?? 0) + 1;
    }
  } else out.hand = del.count;
  return out;
});

async function reload() {
  await Promise.all([
    lib.loadGrid(props.slug, true),
    lib.loadKinds(props.slug),
    lib.loadWatches(),
    lib.loadCharacters(props.slug),
    lib.loadOrigins(props.slug),
  ]);
}

async function confirmDelete(opts: { trash: boolean; forget: boolean; confirm?: string }) {
  try {
    const r = await del.commit(opts);
    del.closeSheet();
    const slug = props.slug;
    const name = label.value;

    toasts.deleted({
      slug,
      label: name,
      images: r.images,
      bytes: r.bytes,
      forgotten: r.forgotten,
      permanent: r.permanent,
      batchId: r.batch_id,
      undo: async () => {
        if (r.batch_id) await del.undo(r.batch_id);
        if (props.slug === slug) await reload();
      },
    });

    leave();
    await reload();
    suggested.value = null;
  } catch (e) {
    toasts.error({
      slug: props.slug,
      label: label.value,
      sources: [],
      terms: 0,
      code: 'delete_failed',
      message: t('gallery.delete.toast.failed', { error: e instanceof Error ? e.message : String(e) }),
      retry: () => confirmDelete(opts),
    });
  }
}

const empty = computed(() => lib.grid.done && !lib.grid.items.length && !del.active && total.value === 0);

async function loadSuggested() {
  try {
    const r = await api.post<SmartResult>(`/api/gallery/${props.slug}/smart`, {});
    suggested.value = r.matches.length || null;
  } catch {
    suggested.value = null;
  }
}

async function load() {
  // a character or source choice belongs to the gallery it was made in
  lib.character = null;
  lib.source = null;
  lib.kinds = null;
  lib.origins = null;
  allTags.value = false;
  artists.value = [];
  shown.value = null;
  del.exit();

  await Promise.all([
    lib.loadGrid(props.slug, true),
    lib.loadTags(props.slug),
    lib.loadKinds(props.slug),
    lib.loadCharacters(props.slug),
    lib.loadOrigins(props.slug),
  ]);

  void loadSuggested();
  if (route.query.delete === 'smart') await enter('smart');
}

onMounted(async () => {
  viewer.stepOut = stepGrid;
  window.addEventListener('keydown', onKey);
  document.addEventListener('mousedown', onDocClick);
  if (mq) {
    onMq(mq);
    mq.addEventListener('change', onMq);
  }
  await load();

  // keyset "load more" when the sentinel scrolls into view
  io = new IntersectionObserver((es) => {
    if (es[0]?.isIntersecting) lib.loadGrid(props.slug);
  });

  if (sentinel.value) io.observe(sentinel.value);
});

onUnmounted(() => {
  viewer.stepOut = null;
  viewer.close();
  window.removeEventListener('keydown', onKey);
  document.removeEventListener('mousedown', onDocClick);
  mq?.removeEventListener('change', onMq);
  clearTimeout(disarm);
  clearTimeout(leaveTimer);
  if (roll) cancelAnimationFrame(roll);
  io?.disconnect();
  lib.closeDetail();
  del.exit();
});

watch(() => props.slug, load);
</script>

<template>
  <Transition name="morph" mode="out-in">
    <SelectionBar
      v-if="del.active"
      key="bar"
      :total="total ?? lib.grid.items.length"
      :label="label"
      :by-source="bySource"
      :bytes="del.preview?.bytes"
      :leaving="leaving"
      @close="leave"
      @delete="del.openSheet()"
      @switch="switchMode"
    />
    <div v-else key="top" class="top" :class="{ glass: scrolled }">
      <RouterLink
        to="/gallery"
        class="btn gh back"
        :title="$t('gallery.detail.back')"
        :aria-label="$t('gallery.detail.back')"
      >
        <Icon name="chevron-left" :size="14" />
      </RouterLink>
      <div>
        <div class="h1">
          {{ label }}
          <span class="jp sub">{{ w?.pixiv_tags[0] }}</span>
        </div>
        <div class="sub">{{ stats }}</div>
      </div>
      <div class="spacer" />
      <div class="seg" role="group" :aria-label="$t('gallery.detail.source.label')">
        <button
          class="btn sm"
          :class="{ on: !lib.source }"
          :aria-pressed="!lib.source"
          @click="lib.setSource(slug, null)"
        >
          {{ $t('gallery.detail.source.all') }}
        </button>
        <button
          v-for="s in SOURCES"
          :key="s"
          class="btn sm"
          :class="{ on: lib.source === s }"
          :aria-pressed="lib.source === s"
          @click="lib.setSource(slug, s)"
        >
          {{ $t(`gallery.aside.source.${s}`) }}
        </button>
      </div>
      <SelectRoot v-model="order">
        <SelectTrigger class="btn gh rk-select-trigger order" :aria-label="$t('gallery.detail.order.label')">
          <SelectValue />
          <Icon name="chevron-down" :size="14" class="text-dim" />
        </SelectTrigger>
        <SelectPortal>
          <SelectContent class="rk-select-content" position="popper" :side-offset="4">
            <SelectViewport>
              <SelectItem v-for="o in ORDERS" :key="o" :value="o" class="rk-select-item">
                <SelectItemText>{{ $t(`gallery.detail.order.${o}`) }}</SelectItemText>
              </SelectItem>
            </SelectViewport>
          </SelectContent>
        </SelectPortal>
      </SelectRoot>
      <DeleteMenu :total="total ?? 0" :label="label" :suggested="suggested" @pick="enter" />
      <div class="more-menu">
        <button
          class="btn gh sq"
          :aria-label="$t('gallery.delete.more.label')"
          :aria-expanded="moreOpen"
          @click="moreOpen = !moreOpen"
        >
          <Icon name="more" :size="14" />
        </button>
        <div v-if="moreOpen" class="menu" role="menu">
          <button class="item danger" role="menuitem" @click="remove">
            <Icon name="trash" :size="13" />
            {{ armed ? $t('gallery.delete.more.armed') : $t('gallery.delete.more.deleteCharacter') }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
  <div class="stage" :class="{ smart: del.mode === 'smart' }">
    <SmartPanel v-if="del.mode === 'smart'" :slug="slug" />
    <div
      class="body"
      :class="{ selecting: del.active }"
      @scroll.passive="onScroll"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <!-- the filters stay put while the grid scrolls under them, on a frosted
           plate that fades toward the tiles -->
      <div class="filters" :class="{ glass: scrolled }">
        <div v-if="lib.tags.length" class="tagbar">
          <div class="taghead">
            <span class="ptitle">{{ $t('gallery.detail.observedTags') }}</span>
            <span v-if="tagsHint" class="kv">{{ tagsHint }}</span>
            <div class="spacer" />
            <button
              v-if="del.mode !== 'tag' && (allTags || orderedTags.length > shownTags.length)"
              class="more"
              @click="allTags = !allTags"
            >
              {{
                allTags ? $t('gallery.detail.fewer') : $t('gallery.detail.seeAll', { n: orderedTags.length })
              }}
            </button>
          </div>
          <div class="tags">
            <template v-if="del.mode === 'tag'">
              <button
                v-for="tag in shownTags"
                :key="tag.tag_norm"
                class="chip tag pick"
                :class="{ sel: del.isTerm('tag', tag.tag_norm) }"
                :aria-pressed="del.isTerm('tag', tag.tag_norm)"
                @click="term('tag', tag.tag_norm, tag.tag_raw)"
              >
                <Icon v-if="del.isTerm('tag', tag.tag_norm)" name="close" :size="10" />
                <span class="jp name">{{ tag.tag_raw }}</span>
                <span class="mono pct">
                  {{ $t('gallery.detail.share', { n: Math.round(tag.share * 100) }) }}
                </span>
              </button>
            </template>
            <template v-else>
              <span v-for="tag in shownTags" :key="tag.tag_norm" class="chip tag" :class="tag.state">
                <span class="jp name">{{ tag.tag_raw }}</span>
                <span class="mono pct">
                  {{ $t('gallery.detail.share', { n: Math.round(tag.share * 100) }) }}
                </span>
                <span class="sep" />
                <span v-if="tag.state === 'watched'" class="lbl">{{ $t('gallery.detail.watching') }}</span>
                <span v-else-if="tag.state === 'ignored'" class="lbl">
                  {{ $t('gallery.detail.ignored') }}
                </span>
                <template v-else>
                  <button class="act" @click="lib.tagAction(slug, tag.tag_raw, 'watch')">
                    <Icon name="plus" :size="10" />
                    {{ $t('gallery.detail.watch') }}
                  </button>
                  <button class="act dim" @click="lib.tagAction(slug, tag.tag_raw, 'ignore')">
                    {{ $t('gallery.detail.ignore') }}
                  </button>
                </template>
              </span>
            </template>
          </div>
        </div>
        <KindFilter :slug="slug" />
        <IdentityFilter :slug="slug" />
        <OriginFilter :slug="slug" />
        <div v-if="del.mode === 'tag' && artists.length" class="artists">
          <span class="ptitle">{{ $t('gallery.delete.tag.artists') }}</span>
          <button
            v-for="a in artists"
            :key="artistKey(a)"
            class="chip pick"
            :class="{ sel: del.isTerm('artist', artistKey(a)) }"
            :aria-pressed="del.isTerm('artist', artistKey(a))"
            :title="a.handle || a.artist_id"
            @click="term('artist', artistKey(a), a.name)"
          >
            <Icon v-if="del.isTerm('artist', artistKey(a))" name="close" :size="10" />
            <span class="jp">{{ a.name }}</span>
            <em>{{ a.count }}</em>
          </button>
        </div>
        <div v-if="del.mode === 'tag'" class="formula mono">
          <span v-if="formula">{{ formula }}</span>
          <span v-else>{{ $t('gallery.delete.tag.none') }}</span>
          <template v-if="del.everythingPrompt">
            <span class="rose">{{ $t('gallery.delete.tag.everything') }}</span>
            <button class="btn sm" @click="switchMode('all')">{{ $t('gallery.delete.tag.useAll') }}</button>
            <button class="btn sm gh" @click="del.everythingPrompt = null">
              {{ $t('gallery.delete.tag.keepTerm') }}
            </button>
          </template>
        </div>
      </div>

      <template v-if="del.mode === 'smart'">
        <div class="mhead">
          <span class="ptitle rose">
            {{ $t('gallery.delete.smart.matches', { n: fm.number(smartMatches.length) }) }}
          </span>
          <span class="kv">{{ $t('gallery.delete.smart.sorted') }}</span>
          <div class="spacer" />
          <div class="seg" role="group" :aria-label="$t('gallery.delete.smart.sortLabel')">
            <button
              v-for="s in ['score', 'reason', 'newest'] as const"
              :key="s"
              class="btn sm"
              :class="{ on: del.smartSort === s }"
              :aria-pressed="del.smartSort === s"
              @click="del.smartSort = s"
            >
              {{ $t(`gallery.delete.smart.sort.${s}`) }}
            </button>
          </div>
        </div>
        <div class="masonry four">
          <div v-for="(col, ci) in smartCols" :key="ci" class="col">
            <GalleryTile
              v-for="m in col"
              :key="'m' + m.sha"
              :sha="m.sha"
              :item="bySha.get(m.sha)"
              select
              :picked="del.selected.has(m.sha)"
              :kept="del.droppedSet.has(m.sha)"
              :badge="badgeOf(m.sha)?.text"
              :tone="badgeOf(m.sha)?.tone"
              @open="(e) => onTile(bySha.get(m.sha) ?? null, m.sha, e)"
            />
          </div>
        </div>
        <div v-if="!del.reviewOnly" class="mhead">
          <span class="ptitle">{{ $t('gallery.delete.smart.rest', { n: fm.number(rest.length) }) }}</span>
        </div>
      </template>

      <div
        v-show="del.mode !== 'smart' || !del.reviewOnly"
        class="masonry"
        :class="{ four: del.mode === 'smart' }"
      >
        <div v-for="(col, ci) in restCols" :key="ci" class="col">
          <GalleryTile
            v-for="it in col"
            :key="tileKey(it)"
            :sha="it.sha256"
            :item="it"
            :current="selected === tileKey(it)"
            :select="del.active"
            :picked="del.selected.has(it.sha256)"
            :kept="del.droppedSet.has(it.sha256)"
            :excluded="del.mode === 'tag' && del.terms.length > 0 && !del.baseSet.has(it.sha256)"
            :badge="badgeOf(it.sha256)?.text"
            :tone="badgeOf(it.sha256)?.tone"
            @open="(e) => onTile(it, it.sha256, e)"
          />
        </div>
      </div>
      <div v-if="empty" class="nothing">
        <Icon name="images" :size="22" />
        <b>{{ $t('gallery.delete.empty.title') }}</b>
        <span class="kv">{{ $t('gallery.delete.empty.sub') }}</span>
        <RouterLink to="/config" class="btn sm">{{ $t('gallery.delete.empty.crawl') }}</RouterLink>
      </div>
      <div v-show="!empty" ref="sentinel" class="kv end">
        <Icon v-if="!lib.grid.done" name="loader" class="spin" :size="13" />
        {{ lib.grid.done ? $t('gallery.detail.end') : $t('gallery.detail.loading') }}
      </div>
    </div>
    <Transition name="fade">
      <div v-if="lib.detail" class="scrim" @click="lib.closeDetail()" />
    </Transition>
    <DetailAside v-if="lib.detail" :post="lib.detail" @close="lib.closeDetail()" />
  </div>
  <!-- outside the stage: the sheet and its scrim cover the selection strip too,
       everything but the rail -->
  <DeleteSheet
    v-if="del.sheet && del.preview"
    :preview="del.preview"
    :label="label"
    :target="w?.target ?? 100"
    :reasons="sheetReasons"
    @close="del.closeSheet()"
    @confirm="confirmDelete"
  />
  <div v-if="box" class="marquee" :style="boxStyle" />
</template>

<style scoped>
/* ---- header: stays put; frosted once the grid scrolls ---- */
.top {
  transition: background-color 0.2s;
}
.top.glass {
  background: color-mix(in oklch, var(--color-bg) 94%, transparent);
}
.morph-enter-active,
.morph-leave-active {
  transition:
    opacity 0.18s ease-out,
    transform 0.18s ease-out;
}
.morph-enter-from,
.morph-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
.back,
.sq {
  width: 34px;
  height: 34px;
  padding: 0;
  justify-content: center;
  flex: none;
}
.seg {
  display: flex;
  gap: 1px;
  padding: 2px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
}
.seg .btn {
  height: 23px;
  border: 0;
  background: transparent;
  color: var(--color-mut);
  clip-path: none;
}
.seg .btn:hover {
  color: var(--color-tx);
}
.seg .btn.on {
  background: var(--color-line);
  color: var(--color-tx);
}
.order {
  min-width: 0;
}
.more-menu {
  position: relative;
  flex: none;
}
.menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 30;
  min-width: 200px;
  padding: 4px;
  background: color-mix(in oklch, var(--color-surf) 92%, transparent);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
  border: 1px solid var(--color-line);
  box-shadow: 0 14px 40px oklch(0 0 0 / 0.5);
}
.item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: none;
  border: 0;
  color: var(--color-tx);
  font-size: 12px;
  text-align: left;
}
.item.danger {
  color: var(--color-rose);
}
.item:hover {
  background: color-mix(in oklch, var(--color-rose) 10%, transparent);
}

/* ---- the scrolling grid, with the aside laid over it ---- */
.stage {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.stage.smart {
  flex-direction: row;
}
.stage.smart .body {
  flex: 1;
  min-width: 0;
}

/* sticky keeps clear of the scroller's padding, so the strip carries the top
   spacing instead -- otherwise it pins 18px low and tiles show above it */
.stage .body {
  padding-top: 0;
}
.body.selecting {
  user-select: none;
}

/* The filters (observed tags, Show, Who, Characters): sticky at the top of
   the grid. Their plate (::before) fades in on scroll - opaque under the
   header, thinning toward the images, then a feathered edge so tiles slide
   under it instead of being cut off. */
.filters {
  position: sticky;
  top: 0;
  z-index: 2;
  margin: 0 -24px 12px;
  padding: 16px 24px 12px;
}
.filters::before {
  content: '';
  position: absolute;
  inset: 0 0 -28px;
  z-index: -1;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    color-mix(in oklch, var(--color-bg) 94%, transparent) 0%,
    color-mix(in oklch, var(--color-bg) 72%, transparent) calc(100% - 28px),
    transparent 100%
  );
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  backdrop-filter: blur(14px) saturate(1.2);
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 28px), transparent);
  mask-image: linear-gradient(to bottom, #000 calc(100% - 28px), transparent);
  opacity: 0;
  transition: opacity 0.2s;
}
.filters.glass::before {
  opacity: 1;
}
.tagbar {
  margin-bottom: 12px;
}
.taghead {
  display: flex;
  align-items: baseline;
  gap: 9px;
  margin-bottom: 8px;
}
.taghead .kv {
  font-size: 11px;
}
.more {
  background: none;
  border: none;
  padding: 0;
  font-size: 11px;
  color: var(--color-dim);
}
.more:hover {
  color: var(--color-tx);
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  --cut: 6px;
  height: 28px;
  gap: 9px;
  padding: 0 10px;
  border-color: var(--color-line);
}
.tag .name {
  font-size: 12px;
}
.tag .pct {
  font-size: 10px;
  color: var(--color-dim);
}
.tag .sep {
  width: 1px;
  height: 12px;
  background: var(--color-line-soft);
}
.tag .lbl {
  font-size: 10px;
  font-weight: 600;
}
.tag.watched {
  border-color: color-mix(in oklch, var(--color-ember) 45%, transparent);
  background: color-mix(in oklch, var(--color-ember) 12%, var(--color-bg));
}
.tag.watched .name,
.tag.watched .lbl {
  color: var(--color-ember);
}
.tag.ignored {
  border-color: var(--color-line-soft);
  background: transparent;
}
.tag.ignored .name,
.tag.ignored .lbl {
  color: var(--color-dim);
  font-weight: 400;
}
.act {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: none;
  border: none;
  font-size: 10px;
  color: var(--color-moss);
  font-weight: 600;
  padding: 0;
}
.act.dim {
  color: var(--color-dim);
  font-weight: 400;
}
.act:hover {
  filter: brightness(1.25);
}
.chip em {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-dim);
}
.chip.sel em {
  color: inherit;
}
.artists {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 12px;
}
.formula {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--color-rose) 50%, transparent);
  background: color-mix(in srgb, var(--color-rose) 6%, transparent);
  color: var(--color-tx);
}
.mono {
  font: 11px var(--font-mono);
}
.rose {
  color: var(--color-rose);
}
.mhead {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 10px;
}
.mhead .kv {
  font-size: 11px;
}

.masonry {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.masonry .col {
  flex: 1 1 0;
  min-width: 0;
}
.end {
  padding: 16px;
  text-align: center;
}
.nothing {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  color: var(--color-dim);
}
.nothing b {
  color: var(--color-tx);
  font-size: 14px;
}
/* the aside overlays the grid instead of narrowing it */
.scrim {
  position: absolute;
  inset: 0;
  z-index: 4;
  background: oklch(0 0 0 / 0.15);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
/* the box drawn while dragging By image */
.marquee {
  position: fixed;
  z-index: 40;
  border: 1px dashed var(--color-rose);
  background: color-mix(in oklch, var(--color-rose) 8%, transparent);
  pointer-events: none;
}
@media (prefers-reduced-motion: reduce) {
  .top,
  .fade-enter-active,
  .fade-leave-active,
  .morph-enter-active,
  .morph-leave-active {
    transition: none;
  }
}
</style>
