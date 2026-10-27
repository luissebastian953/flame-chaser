<script setup lang="ts">
import type { GalleryItem } from '@/lib/types';

/**
 * One image in a character's grid. Outside select mode it opens the aside
 * (ember ring while open). In select mode it carries a checkbox: rose ring
 * when marked for deletion, and everything NOT marked steps back -- dimmed
 * and desaturated, full again under the pointer -- so what is about to go
 * reads at a glance; faded further when a tag choice left it out, an amber
 * ring with "kept" when the user took it back out of a set, and a reason
 * badge (score, other character, duplicate, the tag that pulled it in).
 * Top-right corner mark: X for a post from X. Bottom-right: the image's label
 * badge (AI / Non-Illust / Unidentified), outside select mode only, where the
 * delete badge lives.
 */
const props = defineProps<{
  sha: string;
  /** the grid row, when loaded; a Smart match beyond the loaded pages has only its sha */
  item?: GalleryItem | null;
  /** the aside shows this image */
  current?: boolean;
  select?: boolean;
  picked?: boolean;
  kept?: boolean;
  excluded?: boolean;
  badge?: string;
  tone?: 'rose' | 'amber' | 'cyan' | 'dim';
}>();

const emit = defineEmits<{ open: [e: MouseEvent] }>();
const { t } = useI18n();

const aspect = computed(() =>
  props.item?.width && props.item?.height ? `${props.item.width}/${props.item.height}` : undefined,
);

const label = computed(() => {
  const title = props.item?.title || props.sha.slice(0, 8);
  return props.picked ? t('gallery.delete.tile.keep', { title }) : t('gallery.delete.tile.mark', { title });
});

/** outside select mode the badge is the tile's name: "Image, label: AI" */
const labeled = computed(() =>
  props.item?.label
    ? t('gallery.tile.labeled', { label: t(`gallery.label.${LABEL_KEY[props.item.label]}`) })
    : undefined,
);
</script>

<template>
  <button
    class="tile"
    :class="{ sel: current, pick: picked, kept, ex: excluded, unmarked: select && !picked && !excluded }"
    :data-sha="sha"
    :aria-current="current || undefined"
    :aria-pressed="select ? picked : undefined"
    :aria-label="select ? label : labeled"
    @click="emit('open', $event)"
  >
    <img
      :src="mediaUrl(sha)"
      loading="lazy"
      decoding="async"
      :style="aspect ? { aspectRatio: aspect } : { aspectRatio: item ? '3/4' : undefined }"
      alt=""
    />
    <span v-if="select && !excluded" class="cb" aria-hidden="true">
      <Icon v-if="picked" name="check" :size="12" />
    </span>
    <span class="marks">
      <span v-if="item?.source === 'twitter'" class="xb">{{ $t('gallery.aside.source.twitter') }}</span>
    </span>
    <span v-if="!select && item?.label" class="lb" :class="item.label">
      {{ $t(`gallery.label.${LABEL_KEY[item.label]}`) }}
    </span>
    <span v-if="badge" class="badge" :class="tone ?? 'dim'">
      {{ kept ? $t('gallery.delete.smart.badge.kept', { text: badge }) : badge }}
    </span>
  </button>
</template>

<style scoped>
.tile {
  position: relative;
  display: block;
  width: 100%;
  margin: 0 0 8px;
  padding: 0;
  border: 0;
  background: var(--color-surf2);
  break-inside: avoid;
  transition:
    box-shadow 0.15s,
    opacity 0.15s;
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
/* marked for deletion: rose ring inside the tile, rose glow */
.tile.pick {
  z-index: 1;
  box-shadow:
    inset 0 0 0 2px var(--color-rose),
    0 0 14px color-mix(in oklch, var(--color-rose) 50%, transparent);
}
.tile.pick img {
  opacity: 0.92;
}
/* select mode, not marked: step back so the marked ones carry the grid */
.tile.unmarked img {
  opacity: 0.42;
  filter: saturate(0.55);
  transition:
    opacity 0.15s,
    filter 0.15s;
}
.tile.unmarked:hover img,
.tile.unmarked:focus-visible img {
  opacity: 0.9;
  filter: none;
}
.tile.unmarked .cb {
  border-color: oklch(0.9 0.02 265 / 0.55);
}
/* kept back out of a set: a thin amber ring */
.tile.kept {
  box-shadow: inset 0 0 0 1px var(--color-amber);
}
/* not a candidate under the current tag choice */
.tile.ex {
  opacity: 0.28;
}
.cb {
  position: absolute;
  top: 7px;
  left: 7px;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px solid oklch(0.9 0.02 265 / 0.85);
  background: color-mix(in oklch, var(--color-bg) 60%, transparent);
  color: var(--color-ember-ink);
}
.tile.pick .cb {
  background: var(--color-rose);
  border-color: var(--color-rose);
}
.marks {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 3px;
}
.xb {
  min-width: 15px;
  height: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
  background: color-mix(in oklch, var(--color-bg) 78%, transparent);
  color: var(--color-cyan);
  font: 600 8px var(--font-sans);
}
/* the label badge: amber = AI, muted = not an illustration, dashed dim = unidentified */
.lb {
  position: absolute;
  right: 6px;
  bottom: 6px;
  z-index: 2;
  height: 16px;
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  border-radius: 2px;
  background: oklch(0.14 0.024 265 / 0.82);
  font: 600 9px var(--font-sans);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
}
.lb.ai {
  color: var(--color-amber);
  border: 1px solid color-mix(in oklch, var(--color-amber) 55%, transparent);
}
.lb.non_illust {
  color: var(--color-mut);
  border: 1px solid var(--color-line);
}
.lb.unidentified {
  color: var(--color-dim);
  border: 1px dashed var(--color-line);
}
.badge {
  position: absolute;
  left: 7px;
  bottom: 7px;
  height: 17px;
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  max-width: calc(100% - 14px);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font: 600 10px var(--font-mono);
  border: 1px solid currentColor;
  background: color-mix(in oklch, var(--color-bg) 85%, transparent);
}
.badge.rose {
  color: var(--color-rose);
}
.badge.amber {
  color: var(--color-amber);
}
.badge.cyan {
  color: var(--color-cyan);
}
.badge.dim {
  color: var(--color-mut);
}
@media (prefers-reduced-motion: reduce) {
  .tile,
  .tile.unmarked img {
    transition: none;
  }
}
</style>
