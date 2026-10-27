<script setup lang="ts">
/**
 * The one filter row above a character's grid: the source segmented control
 * (All / pixiv / X) and the label one (Any label / AI / Non-Illust /
 * Unidentified), ANDed - one label per image, picked by the daemon when
 * several apply. Under it, only while the classifiers still owe something
 * (kinds not labeled, characters not identified, origins not judged), one
 * status line with the `label` job that runs all three at once.
 *
 * At the row's end, "View Artists Tags" unfolds the gallery's artists as
 * chips (name, image count), one of which narrows the grid to that artist,
 * ANDed with the source and the label. Open or closed is remembered per
 * viewer (localStorage); the daemon never sees it.
 *
 * In By tag (stores/deletion.ts) the three label options are chips that
 * select the images carrying that label instead of filtering the grid, and
 * "Any label" steps aside. The artists toggle and its chips step aside too:
 * the page's own Artists row is the selector there.
 */
import type { ImageLabel, Source } from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const jobs = useJobs();
const del = useDeletion();
const { t } = useI18n();

const SOURCES: Source[] = ['pixiv', 'twitter'];
const INSTALL = "pip install 'reaver[classify]'"; // data, shown verbatim
const ARTISTS_SHOWN = 30; // artist chips before "see all"
const OPEN_KEY = 'curio.gallery.artists.open';

const selecting = computed(() => del.mode === 'tag');

// ---- the artists row: folded by default, the choice kept per viewer ----
const artistsOpen = ref(readOpen());
const allArtists = ref(false);
const artistsId = computed(() => `artists-${props.slug}`);

const shownArtists = computed(() => (allArtists.value ? lib.artists : lib.artists.slice(0, ARTISTS_SHOWN)));

function readOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === 'true';
  } catch {
    return false;
  }
}

function toggleArtists() {
  artistsOpen.value = !artistsOpen.value;
  try {
    localStorage.setItem(OPEN_KEY, String(artistsOpen.value));
  } catch {
    /* private mode / blocked storage: this session still remembers */
  }
}

/** one artist narrows the grid; the active chip clicked again widens it back */
function pickArtist(key: string) {
  void lib.setArtist(props.slug, lib.artist === key ? null : key);
}

const jobId = ref<string | null>(null);
const job = computed(() => (jobId.value ? (jobs.jobs.find((j) => j.id === jobId.value) ?? null) : null));
const running = computed(() => !!job.value && ['queued', 'running'].includes(job.value.state));

const unlabeled = computed(() => lib.kinds?.counts.unlabeled ?? 0);
const unidentified = computed(() => lib.characters?.counts.pending ?? 0);
const unjudged = computed(() => lib.origins?.counts.pending ?? 0);
/** images at least one classifier has not reached yet */
const pending = computed(() => unlabeled.value + unidentified.value + unjudged.value);

/** none of the three can run: the optional classify extra is not installed */
const unavailable = computed(
  () =>
    !!(lib.kinds || lib.characters || lib.origins) &&
    !lib.kinds?.labeler.available &&
    !lib.characters?.identifier.available &&
    !lib.origins?.detector.available,
);

/** a classifier with work to do has not downloaded its model yet */
const firstUse = computed(
  () =>
    (unlabeled.value > 0 && lib.kinds?.labeler.models === false) ||
    (unidentified.value > 0 && lib.characters?.identifier.models === false) ||
    (unjudged.value > 0 && lib.origins?.detector.models === false),
);

/** every image the grid can hold, for the "this chip is everything" prompt */
const total = computed(() => {
  const c = lib.kinds?.counts;
  return c ? lib.kindsFor(props.slug).reduce((sum, k) => sum + c[k], 0) : 0;
});

function pick(label: ImageLabel | null) {
  if (selecting.value) {
    if (!label) return;
    const name = t(`gallery.label.${LABEL_KEY[label]}`);
    void del.toggleTerm('label', label, name, lib.gridQuery(props.slug), total.value);
    return;
  }
  if (label !== lib.label) void lib.setLabel(props.slug, label);
}

async function labelNow() {
  jobId.value = await jobs.submit('label');
}

// the jobs store follows the daemon's events; when our job ends, recount and redraw
watch(
  () => job.value?.state,
  async (state) => {
    if (state && !['queued', 'running'].includes(state)) {
      await Promise.all([
        lib.loadKinds(props.slug),
        lib.loadCharacters(props.slug),
        lib.loadOrigins(props.slug),
        lib.loadGrid(props.slug, true),
      ]);
    }
  },
);
</script>

<template>
  <div class="labels">
    <div class="row">
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
      <div class="seg" role="radiogroup" :aria-label="$t('gallery.label.filter')">
        <button
          v-if="!selecting"
          class="btn sm"
          role="radio"
          :class="{ on: !lib.label }"
          :aria-checked="!lib.label"
          @click="pick(null)"
        >
          {{ $t('gallery.label.any') }}
        </button>
        <button
          v-for="l in IMAGE_LABELS"
          :key="l"
          class="btn sm"
          role="radio"
          :class="selecting ? { sel: del.isTerm('label', l) } : { on: lib.label === l }"
          :aria-checked="selecting ? del.isTerm('label', l) : lib.label === l"
          @click="pick(l)"
        >
          <Icon v-if="selecting && del.isTerm('label', l)" name="close" :size="10" />
          <i v-else class="sw" :class="l" aria-hidden="true" />
          {{ $t(`gallery.label.${LABEL_KEY[l]}`) }}
        </button>
      </div>
      <button
        v-if="!selecting && lib.artists.length"
        class="more fold"
        :aria-expanded="artistsOpen"
        :aria-controls="artistsId"
        @click="toggleArtists"
      >
        <Icon name="chevron-down" :size="11" class="chev" :class="{ open: artistsOpen }" />
        {{ $t('gallery.label.artists') }}
        <em>{{ lib.artists.length }}</em>
      </button>
    </div>
    <div v-if="!selecting && artistsOpen && lib.artists.length" :id="artistsId" class="artists">
      <button
        v-for="a in shownArtists"
        :key="artistKey(a)"
        class="chip"
        :class="{ on: lib.artist === artistKey(a) }"
        :aria-pressed="lib.artist === artistKey(a)"
        :title="a.handle || a.artist_id"
        @click="pickArtist(artistKey(a))"
      >
        <Icon name="user" :size="11" />
        <span class="jp">{{ a.name }}</span>
        <em>{{ a.count }}</em>
      </button>
      <button v-if="lib.artists.length > ARTISTS_SHOWN" class="more" @click="allArtists = !allArtists">
        {{ allArtists ? $t('gallery.detail.fewer') : $t('gallery.detail.seeAll', { n: lib.artists.length }) }}
      </button>
    </div>
    <div v-if="pending > 0" class="hint status">
      <span>{{ $t('gallery.label.pendingLine', { n: pending }, pending) }}</span>
      <span v-if="unavailable" class="ib">
        <Icon name="warning" :size="12" />
        {{ $t('gallery.label.unavailable', { cmd: INSTALL }) }}
      </span>
      <span v-else-if="running" class="ib data">
        <Icon name="loader" class="spin" :size="12" />
        {{
          job?.total
            ? $t('gallery.label.labeling', { done: job.done, total: job.total })
            : $t('gallery.label.labelingStarting')
        }}
      </span>
      <template v-else>
        <button class="btn sm" @click="labelNow">
          <Icon name="scan" :size="13" />
          {{ $t('gallery.label.labelNow') }}
        </button>
        <span v-if="firstUse">{{ $t('gallery.label.firstUse') }}</span>
      </template>
      <span v-if="job?.state === 'failed'" class="ib err">
        <Icon name="error" :size="12" />
        {{ $t('gallery.label.failed', { error: job.error }) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.labels {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 6px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
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
  gap: 5px;
  border: 0;
  background: transparent;
  color: var(--color-mut);
  clip-path: none;
  white-space: nowrap;
}
.seg .btn:hover {
  color: var(--color-tx);
}
.seg .btn.on {
  background: var(--color-line);
  color: var(--color-tx);
}
/* By tag: a chip stands for the images to delete - rose, never ember */
.seg .btn.sel {
  background: color-mix(in srgb, var(--color-rose) 12%, var(--color-bg));
  color: var(--color-rose);
}
/* the 6x6 swatch each label carries: solid amber, solid muted, or an empty dashed box */
.sw {
  flex: none;
  width: 6px;
  height: 6px;
}
.sw.ai {
  background: var(--color-amber);
}
.sw.non_illust {
  background: var(--color-mut);
}
.sw.unidentified {
  border: 1px dashed var(--color-dim);
}
/* "View Artists Tags 61": a text button; its chevron turns while the row is open */
.more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  padding: 2px 4px;
  font-size: 11px;
  color: var(--color-mut);
  cursor: pointer;
}
.more:hover {
  color: var(--color-tx);
}
.more em,
.chip em {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-dim);
}
.chip.on em {
  color: inherit;
}
.chev {
  transition: transform 0.15s;
}
.chev.open {
  transform: rotate(180deg);
}
.artists {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
button.chip {
  cursor: pointer;
  font: inherit;
  font-size: 11px;
}
.status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-height: 25px;
}
@media (prefers-reduced-motion: reduce) {
  .chev {
    transition: none;
  }
}
.ib {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.err {
  color: var(--color-rose);
}
</style>
