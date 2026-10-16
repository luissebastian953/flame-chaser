<script setup lang="ts">
import type { GalleryItem, GridOrder, Source } from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const fm = useFormats();
const router = useRouter();
const { t } = useI18n();
const sentinel = ref<HTMLElement | null>(null);
let io: IntersectionObserver | null = null;

const SOURCES: Source[] = ['pixiv', 'twitter'];
const ORDERS: GridOrder[] = ['newest', 'oldest'];
const TAGS_SHOWN = 10; // tag chips before "see all"

const w = computed(() => lib.watches.find((x) => x.slug === props.slug));

/** "1,284 images · 412 posts · 61 artists": every image the grid can hold; what is loaded until the counts arrive. */
const stats = computed(() => {
  const c = lib.kinds?.counts;
  const n = c ? lib.kindsFor(props.slug).reduce((sum, k) => sum + c[k], 0) : null;

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

const shownTags = computed(() =>
  allTags.value
    ? orderedTags.value
    : orderedTags.value.slice(0, Math.max(TAGS_SHOWN, watchedTags.value.length)),
);

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

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && !e.defaultPrevented && lib.detail) lib.closeDetail();
}

// two-step like Shutdown: a stray click never deletes a character
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
  await lib.deleteWatch(props.slug);
  await router.push('/gallery');
}

async function load() {
  // a character or source choice belongs to the gallery it was made in
  lib.character = null;
  lib.source = null;
  lib.kinds = null;
  allTags.value = false;

  await Promise.all([
    lib.loadGrid(props.slug, true),
    lib.loadTags(props.slug),
    lib.loadKinds(props.slug),
    lib.loadCharacters(props.slug),
  ]);
}

onMounted(async () => {
  window.addEventListener('keydown', onKey);
  await load();

  // keyset "load more" when the sentinel scrolls into view
  io = new IntersectionObserver((es) => {
    if (es[0]?.isIntersecting) lib.loadGrid(props.slug);
  });

  if (sentinel.value) io.observe(sentinel.value);
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKey);
  clearTimeout(disarm);
  io?.disconnect();
  lib.closeDetail();
});

watch(() => props.slug, load);
</script>

<template>
  <div class="top" :class="{ glass: scrolled }">
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
        {{ w?.label || slug }}
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
    <button class="btn danger" @click="remove">
      <Icon name="trash" :size="13" />
      {{ armed ? $t('gallery.detail.delete.armed') : $t('gallery.detail.delete.label') }}
    </button>
  </div>
  <div class="stage">
    <div class="body" @scroll.passive="onScroll">
      <!-- the filters stay put while the grid scrolls under them, on a frosted
           plate that fades toward the tiles -->
      <div class="filters" :class="{ glass: scrolled }">
        <div v-if="lib.tags.length" class="tagbar">
          <div class="taghead">
            <span class="ptitle">{{ $t('gallery.detail.observedTags') }}</span>
            <span v-if="tagsHint" class="kv">{{ tagsHint }}</span>
            <div class="spacer" />
            <button
              v-if="allTags || orderedTags.length > shownTags.length"
              class="more"
              @click="allTags = !allTags"
            >
              {{
                allTags ? $t('gallery.detail.fewer') : $t('gallery.detail.seeAll', { n: orderedTags.length })
              }}
            </button>
          </div>
          <div class="tags">
            <span v-for="tag in shownTags" :key="tag.tag_norm" class="chip tag" :class="tag.state">
              <span class="jp name">{{ tag.tag_raw }}</span>
              <span class="mono pct">
                {{ $t('gallery.detail.share', { n: Math.round(tag.share * 100) }) }}
              </span>
              <span class="sep" />
              <span v-if="tag.state === 'watched'" class="lbl">{{ $t('gallery.detail.watching') }}</span>
              <span v-else-if="tag.state === 'ignored'" class="lbl">{{ $t('gallery.detail.ignored') }}</span>
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
          </div>
        </div>
        <KindFilter :slug="slug" />
        <IdentityFilter :slug="slug" />
      </div>
      <div class="masonry">
        <button
          v-for="it in lib.grid.items"
          :key="tileKey(it)"
          class="tile"
          :class="{ sel: selected === tileKey(it) }"
          :aria-current="selected === tileKey(it) || undefined"
          @click="openTile(it)"
        >
          <img
            :src="mediaUrl(it.sha256)"
            loading="lazy"
            decoding="async"
            :style="{ aspectRatio: it.width && it.height ? `${it.width}/${it.height}` : '3/4' }"
            alt=""
          />
          <span v-if="it.source === 'twitter'" class="xb">{{ $t('gallery.aside.source.twitter') }}</span>
        </button>
      </div>
      <div ref="sentinel" class="kv end">
        <Icon v-if="!lib.grid.done" name="loader" class="spin" :size="13" />
        {{ lib.grid.done ? $t('gallery.detail.end') : $t('gallery.detail.loading') }}
      </div>
    </div>
    <Transition name="fade">
      <div v-if="lib.detail" class="scrim" @click="lib.closeDetail()" />
    </Transition>
    <DetailAside v-if="lib.detail" :post="lib.detail" @close="lib.closeDetail()" />
  </div>
</template>

<style scoped>
/* ---- header: stays put; frosted once the grid scrolls ---- */
.top {
  transition: background-color 0.2s;
}
.top.glass {
  background: color-mix(in oklch, var(--color-bg) 94%, transparent);
}
.back {
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

/* ---- the scrolling grid, with the aside laid over it ---- */
.stage {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* sticky keeps clear of the scroller's padding, so the strip carries the top
   spacing instead -- otherwise it pins 18px low and tiles show above it */
.stage .body {
  padding-top: 0;
}

/* The filters (observed tags, Show, Who, Characters): sticky at the top of
   the grid. Their plate (::before) fades in on scroll — opaque under the
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

.masonry {
  column-count: 5;
  column-gap: 8px;
}
.tile {
  position: relative;
  display: block;
  width: 100%;
  margin: 0 0 8px;
  padding: 0;
  border: 0;
  background: var(--color-surf2);
  break-inside: avoid;
  transition: box-shadow 0.15s;
}
.tile img {
  display: block;
  width: 100%;
}
.tile:focus-visible {
  outline: 1px solid var(--color-ember);
  outline-offset: 2px;
}
/* the tile the aside shows: ember ring + glow, lifted over its neighbours */
.tile.sel {
  z-index: 1;
  box-shadow:
    0 0 0 2px var(--color-ember),
    0 0 22px 4px color-mix(in oklch, var(--color-ember) 60%, transparent);
}
.xb {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 15px;
  height: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in oklch, var(--color-bg) 78%, transparent);
  color: var(--color-cyan);
  font: 600 8px var(--font-sans);
}
.end {
  padding: 16px;
  text-align: center;
}
@media (max-width: 1100px) {
  .masonry {
    column-count: 4;
  }
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
@media (prefers-reduced-motion: reduce) {
  .top,
  .tagbar::before,
  .tile,
  .fade-enter-active,
  .fade-leave-active {
    transition: none;
  }
}
</style>
